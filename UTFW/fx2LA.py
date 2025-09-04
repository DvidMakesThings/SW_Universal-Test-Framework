# fx2LA.py

"""
UTFW FX2 Logic Analyzer Module
==============================
High-level helpers to drive Sigrok (sigrok-cli) and PulseView with an FX2(LAFW)-
based logic analyzer. Provides TestAction factories for common capture workflows,
UART decoding, and expected-value assertions. Integrates with UTFW's reporter
for rich subprocess logging.

Default device: fx2lafw (generic driver for FX2-based LAs)

Typical usage:
    from UTFW import FX2

    # 1) Capture a trace into .srzip
    FX2.capture_trace(
        name="Capture 500ms 24MHz D0-D1",
        samplerate="24MHz",
        channels=[0, 1],
        time_ms=500,
        output_basename="fx2_capture_500ms",
        output_format="srzip"
    )

    # 2) Decode the saved .srzip as UART (ASCII) and assert it contains "hello"
    FX2.decode_uart_capture(
        name="Decode UART RX ASCII and expect 'hello'",
        input_basename="fx2_capture_500ms",   # without extension; resolved under Reports/<suite>
        ch_rx=0,
        ch_tx=1,
        baudrate=115200,
        fmt="ascii",
        expected="hello",
        match_mode="contains"
    )

Author: DvidMakesThings
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple, Union

from .reporting import get_active_reporter
from .utilities import sanitize_filename
from .core import TestAction


# ----------------------------- Exceptions -----------------------------


class FX2TestError(Exception):
    """Logic analyzer test specific error."""
    pass


# ------------------------------ Paths --------------------------------


DEFAULT_SIGROK_CLI = r"C:\Program Files\sigrok\sigrok-cli\sigrok-cli.exe"


def _which(exe: str) -> Optional[str]:
    """
    Locate an executable on PATH.

    Args:
        exe (str): Executable name, e.g., 'sigrok-cli'.

    Returns:
        Optional[str]: Absolute path if found, else None.
    """
    return shutil.which(exe)


def _resolve_sigrok_cli(sigrok_cli: Optional[str], pulseview_dir: Optional[str]) -> str:
    """
    Resolve the path to sigrok-cli.

    Resolution order:
      1) Explicit 'sigrok_cli' parameter, if exists.
      2) Default Windows installation path (DEFAULT_SIGROK_CLI).
      3) 'sigrok-cli' from PATH.
      4) 'pulseview_dir' sibling or within provided tree (best effort search).

    Args:
        sigrok_cli (Optional[str]): Explicit path to sigrok-cli.exe (or 'sigrok-cli').
        pulseview_dir (Optional[str]): Directory where pulseview.exe resides.

    Returns:
        str: Resolved path to sigrok-cli executable.

    Raises:
        FX2TestError: If no valid sigrok-cli executable is found.
    """
    # 1) Explicit
    if sigrok_cli:
        p = Path(sigrok_cli)
        if p.is_file():
            return str(p)
        from_path = _which(sigrok_cli)
        if from_path:
            return from_path

    # 2) Default Windows path
    p = Path(DEFAULT_SIGROK_CLI)
    if p.is_file():
        return str(p)

    # 3) PATH
    wp = _which("sigrok-cli")
    if wp:
        return wp

    # 4) Search near PulseView dir
    if pulseview_dir:
        pv = Path(pulseview_dir)
        candidates = [
            pv / "sigrok-cli.exe",
            pv / "bin" / "sigrok-cli.exe",
            pv.parent / "sigrok-cli" / "sigrok-cli.exe",
            pv.parent / "sigrok" / "sigrok-cli.exe",
        ]
        for c in candidates:
            if c.is_file():
                return str(c)

    raise FX2TestError(
        "sigrok-cli not found. Provide 'sigrok_cli' or install Sigrok CLI. "
        "Expected at default path or on PATH."
    )


def _resolve_pulseview(pulseview_dir: Optional[str]) -> str:
    """
    Resolve the path to PulseView executable.

    Args:
        pulseview_dir (Optional[str]): Directory that contains pulseview.exe.

    Returns:
        str: Absolute path to pulseview.exe or 'pulseview' if available on PATH.

    Raises:
        FX2TestError: If PulseView is not found.
    """
    if pulseview_dir:
        exe = Path(pulseview_dir) / "pulseview.exe"
        if exe.is_file():
            return str(exe)

    pv = _which("pulseview")
    if pv:
        return pv

    raise FX2TestError("PulseView not found. Provide 'pulseview_dir' pointing to pulseview.exe.")


# --------------------------- Command Builder --------------------------


def _build_channels_arg(channels: List[int]) -> str:
    """
    Build the '-C' channels string for sigrok-cli.

    Args:
        channels (List[int]): Digital channel indices, e.g., [0,1,2] for D0..D2.

    Returns:
        str: Comma-separated channel names (e.g., 'D0,D1,D2').

    Raises:
        FX2TestError: If an invalid channel index is provided.
    """
    names = []
    for ch in channels:
        if not isinstance(ch, int) or ch < 0:
            raise FX2TestError(f"Invalid channel index: {ch}")
        names.append(f"D{ch}")
    return ",".join(names)


def _append_decoder_args(cmd: List[str], decoders: Optional[List[Dict[str, Any]]]) -> None:
    """
    Append protocol decoder arguments (-P ...) to the command.

    Each decoder dict can have:
      {
        "name": "uart" | "i2c" | "spi" | ... (sigrok decoder short name),
        "channels": {"rx":"D0","tx":"D1"} or {"scl":"D0","sda":"D1"} (optional),
        "options": {"baudrate":"115200","data_bits":"8","parity":"none","stop_bits":"1.0",...} (optional)
      }

    Args:
        cmd (List[str]): Command being built.
        decoders (Optional[List[Dict[str, Any]]]): Decoder configurations.

    Notes:
        We intentionally do NOT emit '-A', '-M', or '-B' flags by default to avoid
        Windows builds misinterpreting them as decoder names (e.g., 'all','summary').
    """
    if not decoders:
        return

    for d in decoders:
        name = d.get("name")
        if not name:
            raise FX2TestError("Decoder missing 'name'.")

        parts = [name]

        # Map channels if provided
        ch_map = d.get("channels") or {}
        if ch_map:
            parts.extend(f"{k}={v}" for k, v in ch_map.items())

        # Map options (ensure string values)
        opts = d.get("options") or {}
        if opts:
            parts.extend(f"{k}={str(v)}" for k, v in opts.items())

        cmd += ["-P", ":".join(parts)]


def _append_time_or_samples(cmd: List[str], time_ms: Optional[int], samples: Optional[int]) -> None:
    """
    Append either '--time' (ms) or '--samples' to the command.

    Args:
        cmd (List[str]): Command being built.
        time_ms (Optional[int]): Duration in milliseconds.
        samples (Optional[int]): Number of samples.

    Raises:
        FX2TestError: If both parameters are provided simultaneously.
    """
    if time_ms is not None and samples is not None:
        raise FX2TestError("Specify either 'time_ms' or 'samples', not both.")
    if time_ms is not None:
        if time_ms <= 0:
            raise FX2TestError("time_ms must be > 0.")
        cmd += ["--time", str(int(time_ms))]
    elif samples is not None:
        if samples <= 0:
            raise FX2TestError("samples must be > 0.")
        cmd += ["--samples", str(int(samples))]


def _append_triggers(cmd: List[str], triggers: Optional[str], wait_trigger: bool) -> None:
    """
    Append trigger configuration.

    Args:
        cmd (List[str]): Command being built.
        triggers (Optional[str]): Trigger string as accepted by sigrok-cli (e.g., 'D0=r').
        wait_trigger (bool): If True, add '--wait-trigger'.
    """
    if triggers:
        cmd += ["-t", str(triggers)]
    if wait_trigger:
        cmd += ["--wait-trigger"]


def _ensure_reports_dir() -> Path:
    """
    Determine the framework's active Reports/<test_name> directory from reporter.

    Returns:
        Path: Directory where outputs should be stored by default.

    Raises:
        FX2TestError: If no active reporter is present.
    """
    rep = get_active_reporter()
    if not rep:
        raise FX2TestError("Active reporter not set. Initialize TestFramework first.")
    return Path(rep.reports_dir)


def _resolve_reports_file(basename: str, ext: str) -> Path:
    """
    Build a file path under the active Reports/<suite> directory.

    Args:
        basename (str): Base name without extension.
        ext (str): File extension without dot (e.g., 'srzip').

    Returns:
        Path: Resolved path under Reports/<suite>/basename.ext
    """
    reports_dir = _ensure_reports_dir()
    safe_base = sanitize_filename(basename or "fx2_capture")
    return reports_dir / f"{safe_base}.{ext}"


# --------------------------- Public Utilities -------------------------


def sigrok_scan(sigrok_cli: Optional[str] = None,
                pulseview_dir: Optional[str] = None,
                loglevel: int = 1) -> Tuple[int, str, str]:
    """
    Run 'sigrok-cli --scan' to list attached devices.

    Args:
        sigrok_cli (Optional[str]): Explicit path to sigrok-cli.
        pulseview_dir (Optional[str]): PulseView directory used as a fallback search root.
        loglevel (int): Sigrok log level (5 is most verbose).

    Returns:
        Tuple[int, str, str]: (returncode, stdout, stderr)

    Notes:
        Also logs the subprocess via the active reporter (tag='SIGROK').
    """
    exe = _resolve_sigrok_cli(sigrok_cli, pulseview_dir)
    cmd = [exe, "--scan", "-l", str(int(loglevel))]
    rep = get_active_reporter()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except Exception as e:
        rc, out, err = 1, "", str(e)
    if rep:
        rep.log_subprocess(cmd, rc, out, err, tag="SIGROK")
    return rc, out, err


def build_driver_spec(driver: str = "fx2lafw",
                      conn: Optional[str] = None,
                      serial: Optional[str] = None) -> str:
    """
    Build a sigrok driver specification string.

    Args:
        driver (str): Driver short name, default 'fx2lafw'.
        conn (Optional[str]): Connection hint, e.g., '1.11' for a specific USB path.
        serial (Optional[str]): Device serial if multiple units are present.

    Returns:
        str: Driver spec like 'fx2lafw' or 'fx2lafw:conn=1.11:serial=ABC123'.
    """
    spec = [driver]
    suffix = []
    if conn:
        suffix.append(f"conn={conn}")
    if serial:
        suffix.append(f"serial={serial}")
    if suffix:
        spec.append(":".join(suffix))
        return ":".join(spec)
    return spec[0]


def capture_trace(
    name: str,
    *,
    samplerate: str,
    channels: List[int],
    time_ms: Optional[int] = None,
    samples: Optional[int] = None,
    triggers: Optional[str] = None,
    wait_trigger: bool = False,
    decoders: Optional[List[Dict[str, Any]]] = None,
    output_basename: str = "fx2_capture",
    output_format: str = "srzip",
    driver_spec: Optional[str] = None,
    sigrok_cli: Optional[str] = None,
    pulseview_dir: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
    verify_uart: Optional[Dict[str, Any]] = None,
) -> TestAction:
    """
    Capture a logic trace using sigrok-cli and save it to the active report folder,
    optionally running an immediate UART decode/expectation check on the saved file.

    This method builds a robust capture command for FX2-based LAs (or any sigrok
    driver), stores outputs under Reports/<suite>, logs the subprocess, and can
    immediately decode the saved .srzip with UART to verify content (ASCII or HEX).

    Args:
        name (str): Human-readable step name shown in reports.
        samplerate (str): Sample rate (e.g., '24MHz', '4MHz', '1MHz').
        channels (List[int]): Enabled digital channels by index (e.g., [0,1] => D0,D1).
        time_ms (Optional[int]): Acquisition duration in ms. Mutually exclusive with 'samples'.
        samples (Optional[int]): Number of samples to capture. Mutually exclusive with 'time_ms'.
        triggers (Optional[str]): Trigger expression (e.g., 'D0=r', 'D1=f').
        wait_trigger (bool): If True, add '--wait-trigger' so acquisition waits for trigger.
        decoders (Optional[List[Dict[str, Any]]]): One or more protocol decoders to attach
            during capture; each dict: {'name': 'uart'|'i2c'|..., 'channels': {...}, 'options': {...}}.
            (No '-A'/'-M' flags are added here to avoid compatibility issues.)
        output_basename (str): Base filename (no extension). Default 'fx2_capture'.
        output_format (str): Sigrok output format ('srzip', 'vcd', 'bits', ...).
            Default 'srzip'.
        driver_spec (Optional[str]): Sigrok driver spec (e.g., 'fx2lafw', 'fx2lafw:conn=1.11').
            Default 'fx2lafw'.
        sigrok_cli (Optional[str]): Path to sigrok-cli.exe; resolved automatically if not set.
        pulseview_dir (Optional[str]): Directory of pulseview.exe to help locate sigrok-cli.
        extra_args (Optional[List[str]]): Extra args appended to the sigrok command (advanced use).
        verify_uart (Optional[Dict[str, Any]]): If provided, immediately decode the saved file
            as UART and validate. Supported keys:
            - ch_rx (int|str|None), ch_tx (int|str|None)  # at least one required
            - baudrate, data_bits, parity, stop_bits, bit_order, fmt,
            invert_rx, invert_tx, sample_point,
            rx_packet_delim, tx_packet_delim, rx_packet_len, tx_packet_len
            - expected (str), match_mode ('equals'|'contains'|'startswith'|'endswith'|'regex')
            - ann_filter (str, optional '-A' value; auto-fallback if it errors)
            - hex_strip_00 (bool, default True for HEX)
            The method logs assembled ASCII/HEX previews and enforces the expectation.

    Returns:
        TestAction: A UTFW TestAction. On execution, returns the output file path
        as a string if capture (and optional verification) succeeds.

    Raises:
        FX2TestError: If arguments are invalid, sigrok-cli fails, the output file is
        missing/empty, the UART decode fails, or the expectation check fails.

    Notes:
        - File path: '<Reports/<suite>>/<output_basename>.<output_format>'.
        - Logging: full capture subprocess is logged; UART verify also logs command
        and decoder previews.
        - Mutual exclusivity: supply either 'time_ms' or 'samples', not both.
    """
    def execute():
        exe = _resolve_sigrok_cli(sigrok_cli, pulseview_dir)
        out_file = _resolve_reports_file(output_basename or "fx2_capture", output_format)

        # Build capture command
        cmd = [exe]
        spec = driver_spec or "fx2lafw"
        cmd += ["-d", spec]
        if channels:
            cmd += ["-C", _build_channels_arg(channels)]
        if not samplerate:
            raise FX2TestError("samplerate is required, e.g., '24MHz'.")
        cmd += ["-c", f"samplerate={samplerate}"]
        _append_time_or_samples(cmd, time_ms, samples)
        _append_triggers(cmd, triggers, wait_trigger)
        _append_decoder_args(cmd, decoders)
        cmd += ["-O", output_format, "-o", str(out_file)]
        cmd += ["-l", "3"]
        if extra_args:
            cmd += list(extra_args)

        rep = get_active_reporter()
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            rc, out, err = res.returncode, res.stdout, res.stderr
        except Exception as e:
            rc, out, err = 1, "", str(e)

        if rep:
            rep.log_subprocess(cmd, rc, out, err, tag="SIGROK")

        if rc != 0:
            raise FX2TestError(f"sigrok-cli capture failed (rc={rc}). See logs. STDERR:\n{err}")

        if not out_file.exists() or out_file.stat().st_size == 0:
            raise FX2TestError(f"Capture output missing or empty: {out_file}")

        # Optional: immediate UART verification on the saved file
        if verify_uart:
            rx_name = _fmt_dch(verify_uart.get("ch_rx"), required=False)
            tx_name = _fmt_dch(verify_uart.get("ch_tx"), required=False)
            if not rx_name and not tx_name:
                raise FX2TestError("verify_uart requires ch_rx or ch_tx (at least one).")

            # Build UART PD spec
            parts = ["uart"]
            if rx_name:
                parts.append(f"rx={rx_name}")
            if tx_name:
                parts.append(f"tx={tx_name}")

            # Map options with defaults
            baudrate = verify_uart.get("baudrate", 115200)
            data_bits = verify_uart.get("data_bits", 8)
            parity = verify_uart.get("parity", "none")
            stop_bits = verify_uart.get("stop_bits", "1.0")
            bit_order = verify_uart.get("bit_order", "lsb-first")
            fmt = verify_uart.get("fmt", "ascii")
            invert_rx = "yes" if verify_uart.get("invert_rx", False) else "no"
            invert_tx = "yes" if verify_uart.get("invert_tx", False) else "no"
            sample_point = verify_uart.get("sample_point", 50)
            rx_packet_delim = verify_uart.get("rx_packet_delim", -1)
            tx_packet_delim = verify_uart.get("tx_packet_delim", -1)
            rx_packet_len = verify_uart.get("rx_packet_len", -1)
            tx_packet_len = verify_uart.get("tx_packet_len", -1)
            ann_filter = verify_uart.get("ann_filter", None)
            hex_strip_00 = bool(verify_uart.get("hex_strip_00", True))

            parts += [
                f"baudrate={baudrate}",
                f"data_bits={data_bits}",
                f"parity={parity}",
                f"stop_bits={stop_bits}",
                f"bit_order={bit_order}",
                f"format={fmt}",
                f"invert_rx={invert_rx}",
                f"invert_tx={invert_tx}",
                f"sample_point={sample_point}",
                f"rx_packet_delim={rx_packet_delim}",
                f"tx_packet_delim={tx_packet_delim}",
                f"rx_packet_len={rx_packet_len}",
                f"tx_packet_len={tx_packet_len}",
            ]

            base_decode = [exe, "-i", str(out_file), "-P", ":".join(parts)]
            decode_cmd = list(base_decode)
            if ann_filter:
                decode_cmd += ["-A", ann_filter]
            decode_cmd += ["-l", "3"]

            try:
                dec = subprocess.run(decode_cmd, capture_output=True, text=True)
                drc, dout, derr = dec.returncode, dec.stdout, dec.stderr
            except Exception as e:
                drc, dout, derr = 1, "", str(e)

            if rep:
                rep.log_subprocess(decode_cmd, drc, dout, derr, tag="SIGROK-UART")

            if drc != 0 and ann_filter:
                fallback_cmd = list(base_decode) + ["-l", "3"]
                try:
                    dec2 = subprocess.run(fallback_cmd, capture_output=True, text=True)
                    drc, dout, derr = dec2.returncode, dec2.stdout, dec2.stderr
                except Exception as e:
                    drc, dout, derr = 1, "", str(e)
                if rep:
                    rep.log_info("UART decode re-run without '-A' due to previous error.")
                    rep.log_subprocess(fallback_cmd, drc, dout, derr, tag="SIGROK-UART")

            if drc != 0:
                raise FX2TestError(f"UART decode failed (rc={drc}). STDERR:\n{derr}")

            decoded_text = (dout or "").strip()
            ascii_joined, hex_joined = _assemble_uart_stream(decoded_text, fmt=str(fmt), ignore_bit_tokens=True)

            if rep:
                a_prev = ascii_joined if len(ascii_joined) <= 200 else ascii_joined[:200] + f"... [{len(ascii_joined)-200} more]"
                h_norm = _normalize_hex(hex_joined)
                h_prev = h_norm if len(h_norm) <= 200 else h_norm[:200] + f"... [{len(h_norm)-200} more]"
                rep.log_info(f"[UART] Joined ASCII: {a_prev}")
                rep.log_info(f"[UART] Joined HEX   : {h_prev}")
                if str(fmt).lower() == "hex" and hex_strip_00:
                    h_no00 = " ".join(b for b in h_norm.split() if b != "00")
                    h_prev2 = h_no00 if len(h_no00) <= 200 else h_no00[:200] + f"... [{len(h_no00)-200} more]"
                    rep.log_info(f"[UART] HEX (drop 00): {h_prev2}")

            expected = verify_uart.get("expected", None)
            if expected is not None:
                mode = verify_uart.get("match_mode", "contains")

                if str(fmt).lower() == "hex":
                    target = _normalize_hex(hex_joined)
                    if hex_strip_00:
                        target = " ".join(b for b in target.split() if b != "00")
                    exp = _normalize_hex(expected)
                else:
                    target = ascii_joined
                    exp = expected

                ok = _match_string(target, exp, mode)
                if not ok:
                    prev = target if len(target) <= 500 else target[:500] + f"... [{len(target)-500} more]"
                    raise FX2TestError(
                        f"UART expected check failed (mode={mode}).\n"
                        f"Expected: {expected}\n"
                        f"Got     : {prev}"
                    )
                if rep:
                    rep.log_info(f"[UART] Expected check PASSED (mode={mode}).")

        return str(out_file)

    return TestAction(name, execute)


def launch_pulseview(
    name: str,
    *,
    pulseview_dir: str,
    driver_spec: Optional[str] = None,
    session_file: Optional[str] = None,
    samplerate: Optional[str] = None,
    channels: Optional[List[int]] = None,
    triggers: Optional[str] = None,
    wait_trigger: bool = False,
    extra_args: Optional[List[str]] = None,
) -> TestAction:
    """
    Create a TestAction that launches PulseView (GUI) with an optional device setup.

    Args:
        name (str): Action name.
        pulseview_dir (str): Directory containing pulseview.exe.
        driver_spec (Optional[str]): Device spec, e.g., 'fx2lafw' or 'fx2lafw:conn=1.11'.
        session_file (Optional[str]): PulseView session file to open (.sr or .srzip).
        samplerate (Optional[str]): Optional sample rate hint (PulseView may ignore CLI samplerate).
        channels (Optional[List[int]]): Optional list of channels to enable, e.g., [0,1,2].
        triggers (Optional[str]): Optional trigger config string.
        wait_trigger (bool): If True, add '--wait-trigger' (if supported by PulseView).
        extra_args (Optional[List[str]]): Additional raw args appended.

    Returns:
        TestAction: Execute to spawn PulseView. Returns 0 on successful spawn, or error code.

    Notes:
        PulseView is primarily interactive; some versions may not honor CLI hints.
    """
    def execute():
        exe = _resolve_pulseview(pulseview_dir)

        cmd = [exe]

        if session_file:
            cmd.append(str(session_file))

        if driver_spec:
            cmd += ["-d", driver_spec]

        if channels:
            try:
                cmd += ["-C", _build_channels_arg(channels)]
            except Exception:
                pass

        if samplerate:
            cmd += ["-c", f"samplerate={samplerate}"]

        if triggers:
            cmd += ["-t", str(triggers)]
        if wait_trigger:
            cmd += ["--wait-trigger"]

        if extra_args:
            cmd += list(extra_args)

        rep = get_active_reporter()
        try:
            proc = subprocess.Popen(cmd)
            rc, out, err = 0, f"Spawned PID={proc.pid}", ""
        except Exception as e:
            rc, out, err = 1, "", str(e)

        if rep:
            rep.log_subprocess(cmd, rc, out, err, tag="PULSEVIEW")

        if rc != 0:
            raise FX2TestError(f"Failed to launch PulseView: {err}")
        return rc

    return TestAction(name, execute)


# ----------------------- Decoder Convenience APIs ---------------------

def _assemble_hex_from_annotations(decoded_stdout: str) -> str:
    """
    Extract and assemble hex byte tokens from sigrok protocol-decoder stdout.

    This helper scans only the quoted annotation payloads (strings inside
    double quotes) and collects all standalone hex byte pairs (two hex digits).
    It preserves encounter order and returns a space-separated sequence.

    Args:
        decoded_stdout (str): Raw stdout produced by 'sigrok-cli -P ...'.

    Returns:
        str: Normalized hex byte stream like "A0 00 10 3F".

    Notes:
        - This deliberately ignores non-hex tokens (e.g., "Start", "ACK") and
          any numbers outside quotes (timestamps/sample ranges).
        - Case-insensitive; output is uppercased pairs separated by single spaces.
    """
    hex_bytes: List[str] = []
    # Find content within quotes to avoid picking up sample numbers.
    for seg in re.findall(r'"([^"]*)"', decoded_stdout):
        for hb in re.findall(r'(?i)(?<![0-9A-F])([0-9A-F]{2})(?![0-9A-F])', seg):
            hex_bytes.append(hb.upper())
    return " ".join(hex_bytes)


def ascii2hex(text: str, *, sep: str = " ", upper: bool = False, encoding: str = "latin-1") -> str:
    """
    Convert an ASCII/byte-string to a space-separated hex byte string.

    Example:
        ascii2hex("SYSINFO\\r\\n") -> "53 59 53 49 4e 46 4f 0d 0a"
        ascii2hex("SYSINFO\\r\\n", upper=True) -> "53 59 53 49 4E 46 4F 0D 0A"

    Args:
        text (str): Input string. Escape sequences like "\\r", "\\n", "\\t" are
            interpreted by Python string literals as usual.
        sep (str): Separator placed between hex bytes. Default: single space.
        upper (bool): If True, output hex bytes are uppercase. Default False (lowercase).
        encoding (str): Character encoding for conversion to bytes. Use "latin-1"
            to map codepoints 0..255 directly to single bytes. Default "latin-1".

    Returns:
        str: Hex bytes string, e.g., "53 59 53 49 4e 46 4f 0d 0a".
    """
    data = text.encode(encoding, errors="strict")
    hex_bytes = [f"{b:02x}" for b in data]
    if upper:
        hex_bytes = [hb.upper() for hb in hex_bytes]
    return sep.join(hex_bytes)



def _fmt_dch(idx: Optional[Union[int, str]], *, required: bool = False) -> Optional[str]:
    """
    Normalize a digital channel identifier into standardized 'D<N>' form.

    Accepts int indices, digit strings, already-formatted 'D<N>' names, or None
    for optional channels. This avoids crashes like 'int(None)' and ensures a
    consistent channel string is emitted in sigrok-cli '-P' arguments.

    Args:
        idx (Optional[Union[int, str]]): Channel identifier:
            - int: 0 -> 'D0'
            - str digits: '1' -> 'D1'
            - preformatted: 'D2' or 'd3' -> 'D2'
            - None: allowed only if required=False
        required (bool): If True, None is not allowed and raises an error.

    Returns:
        Optional[str]: 'D<N>' if idx is provided/valid; None if idx is None and
        required=False.

    Raises:
        FX2TestError: If 'required=True' and idx is None, or if the provided value
        cannot be interpreted as a valid channel.

    Examples:
        _fmt_dch(0)        -> 'D0'
        _fmt_dch('1')      -> 'D1'
        _fmt_dch('D7')     -> 'D7'
        _fmt_dch(None)     -> None              # when required=False
        _fmt_dch(None, required=True)  # raises FX2TestError
    """
    if idx is None:
        if required:
            raise FX2TestError("Required channel is None.")
        return None

    if isinstance(idx, str):
        s = idx.strip()
        if s.upper().startswith("D"):
            num = s[1:]
            if not num.isdigit():
                raise FX2TestError(f"Invalid channel string '{idx}'. Expected 'D<N>'.")
            return f"D{int(num)}"
        if not s.isdigit():
            raise FX2TestError(f"Invalid channel string '{idx}'. Use int, '<N>' or 'D<N>'.")
        return f"D{int(s)}"

    try:
        return f"D{int(idx)}"
    except Exception:
        raise FX2TestError(f"Invalid channel value '{idx}'.")



def simple_uart_decoder(
    ch_rx: Optional[Union[int, str]] = None,
    *,
    ch_tx: Optional[Union[int, str]] = None,
    baudrate: Union[int, str] = 115200,
    data_bits: Union[int, str] = 8,
    parity: str = "none",
    stop_bits: Union[float, str] = "1.0",
    bit_order: str = "lsb-first",
    fmt: str = "ascii",
    invert_rx: bool = False,
    invert_tx: bool = True,
    sample_point: Union[int, str] = 50,
    rx_packet_delim: int = -1,
    tx_packet_delim: int = -1,
    rx_packet_len: int = -1,
    tx_packet_len: int = -1,
) -> Dict[str, Any]:
    """
    Build a UART protocol decoder configuration dictionary suitable for
    inclusion in 'decoders' for a capture, or for documentation/inspection.

    Both RX and TX channels are optional; provide at least one (RX-only, TX-only,
    or both). Channels accept int indices (0 => D0), simple digits ("1" => D1),
    or already formatted names ("D1").

    Args:
        ch_rx (Optional[Union[int, str]]): RX channel index/name (int, 'N', or 'DN').
            Optional if TX is provided.
        ch_tx (Optional[Union[int, str]]): TX channel index/name (int, 'N', or 'DN').
            Optional if RX is provided.
        baudrate (Union[int, str]): UART baud (e.g., 115200, "1M"). Default 115200.
        data_bits (Union[int, str]): Data bits (5..9). Default 8.
        parity (str): 'none'|'odd'|'even'|'zero'|'one'|'ignore'. Default 'none'.
        stop_bits (Union[float, str]): '0.0'|'0.5'|'1.0'|'1.5'|'2.0'. Default '1.0'.
        bit_order (str): 'lsb-first' or 'msb-first'. Default 'lsb-first'.
        fmt (str): Output format 'ascii'|'hex'|'dec'|'oct'|'bin'. Default 'ascii'.
        invert_rx (bool): Invert RX line. Default False.
        invert_tx (bool): Invert TX line. Default False.
        sample_point (Union[int, str]): Sample point in %. Default 50.
        rx_packet_delim (int): RX packet delimiter (decimal). Default -1 (disabled).
        tx_packet_delim (int): TX packet delimiter (decimal). Default -1.
        rx_packet_len (int): RX fixed length. Default -1 (disabled).
        tx_packet_len (int): TX fixed length. Default -1 (disabled).

    Returns:
        Dict[str, Any]: A dict with:
            {
            "name": "uart",
            "channels": {"rx": "D0", "tx": "D1"}  # as provided,
            "options": { ... }                    # stringified option values
            }

    Raises:
        FX2TestError: If neither channel is provided or channel values are invalid.

    Notes:
        - This helper only builds a configuration object; it does not start decoding.
        - Use 'decode_uart_capture()' to decode a saved .srzip, or pass this dict
        into 'capture_trace(decoders=[...])' to attach the PD during capture.
    """

    rx_name = _fmt_dch(ch_rx, required=False)
    tx_name = _fmt_dch(ch_tx, required=False)
    if not rx_name and not tx_name:
        raise FX2TestError("UART decoder requires at least one channel: provide ch_rx or ch_tx.")

    channels: Dict[str, str] = {}
    if rx_name:
        channels["rx"] = rx_name
    if tx_name:
        channels["tx"] = tx_name

    options: Dict[str, Union[str, int]] = {
        "baudrate": str(baudrate),
        "data_bits": str(data_bits),
        "parity": parity,
        "stop_bits": str(stop_bits),
        "bit_order": bit_order,
        "format": fmt,
        "invert_rx": "yes" if invert_rx else "no",
        "invert_tx": "yes" if invert_tx else "no",
        "sample_point": str(sample_point),
        "rx_packet_delim": str(rx_packet_delim),
        "tx_packet_delim": str(tx_packet_delim),
        "rx_packet_len": str(rx_packet_len),
        "tx_packet_len": str(tx_packet_len),
    }

    return {
        "name": "uart",
        "channels": channels,
        "options": options,
    }


# ----------------------- UART Decode & Assert -------------------------


def decode_uart_capture(
    name: str,
    *,
    input_basename: str,
    ch_rx: Optional[Union[int, str]] = None,
    ch_tx: Optional[Union[int, str]] = None,
    baudrate: Union[int, str] = 115200,
    data_bits: Union[int, str] = 8,
    parity: str = "none",
    stop_bits: Union[float, str] = "1.0",
    bit_order: str = "lsb-first",
    fmt: str = "ascii",
    invert_rx: bool = False,
    invert_tx: bool = False,
    sample_point: Union[int, str] = 50,
    rx_packet_delim: int = -1,
    tx_packet_delim: int = -1,
    rx_packet_len: int = -1,
    tx_packet_len: int = -1,
    expected: Optional[str] = None,
    match_mode: str = "contains",
    sigrok_cli: Optional[str] = None,
    pulseview_dir: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
    ann_filter: Optional[str] = None,
    hex_strip_00: bool = True,
) -> TestAction:
    """
    Decode a saved logic capture (.srzip) as UART via sigrok-cli and (optionally)
    assert the decoded payload against an expected value.

    The decoder supports RX-only, TX-only, or both lines. It assembles a clean
    ASCII stream and a normalized HEX stream from sigrok's verbose annotation
    output, logs short previews, and validates using flexible match modes.
    On some Windows builds, using '-A <ann-classes>' can fail; if that happens
    and 'ann_filter' is set, the method automatically re-runs without '-A'.

    Args:
        name (str): Human-readable step name shown in reports.
        input_basename (str): Base filename (without extension) of the capture
            stored under the active Reports/<suite> folder. The method will
            decode '<basename>.srzip'.
        ch_rx (Optional[Union[int, str]]): UART RX channel; int (0 => D0), "N"
            (=> DN), or "DN". Optional if TX is provided.
        ch_tx (Optional[Union[int, str]]): UART TX channel; int/"N"/"DN". Optional
            if RX is provided.
        baudrate (Union[int, str]): UART baud (e.g., 115200, "1M"). Default 115200.
        data_bits (Union[int, str]): Data bits (5..9). Default 8.
        parity (str): 'none'|'odd'|'even'|'zero'|'one'|'ignore'. Default 'none'.
        stop_bits (Union[float, str]): '0.0'|'0.5'|'1.0'|'1.5'|'2.0'. Default '1.0'.
        bit_order (str): 'lsb-first' or 'msb-first'. Default 'lsb-first'.
        fmt (str): Decoder output format: 'ascii'|'hex'|'dec'|'oct'|'bin'.
            Affects both parsing and comparison. Default 'ascii'.
        invert_rx (bool): Invert RX line. Default False.
        invert_tx (bool): Invert TX line. Default False.
        sample_point (Union[int, str]): Sample point in %. Default 50.
        rx_packet_delim (int): RX packet delimiter (decimal). Default -1 (disabled).
        tx_packet_delim (int): TX packet delimiter (decimal). Default -1.
        rx_packet_len (int): RX fixed packet length. Default -1 (disabled).
        tx_packet_len (int): TX fixed packet length. Default -1 (disabled).
        expected (Optional[str]): Expected value to check against the assembled
            stream. If fmt='ascii', compare text. If fmt='hex', compare bytes
            written as "68 65 6c 6c 6f" or "68656c6c6f" (case/spacing ignored).
        match_mode (str): 'equals'|'contains'|'startswith'|'endswith'|'regex'.
            Default 'contains'.
        sigrok_cli (Optional[str]): Path to sigrok-cli.exe. If not provided, the
            module tries the default install path, PATH, or near 'pulseview_dir'.
        pulseview_dir (Optional[str]): Directory of pulseview.exe used as a
            fallback search root for resolving sigrok-cli.
        extra_args (Optional[List[str]]): Extra arguments appended to the sigrok
            command (advanced use).
        ann_filter (Optional[str]): Annotation classes for '-A', e.g., 'rx-data,tx-data'.
            If this causes "Protocol decoder '<ann>' not found", the method logs a
            note and retries without '-A'.
        hex_strip_00 (bool): When fmt='hex', drop 0x00 bytes from the target stream
            before comparison. Helps when decoding both RX+TX where [00] artifacts
            can appear. Default True.

    Returns:
        TestAction: A UTFW TestAction. On execution, returns the assembled ASCII
        string (for convenience) if decoding succeeds and any expectation check
        passes.

    Raises:
        FX2TestError: If the capture is missing, sigrok-cli fails, no channel is
        provided (neither RX nor TX), the expected check fails, or parameters are
        invalid.

    Notes:
        - File resolution: input is '<Reports/<suite>>/<input_basename>.srzip'.
        - Logging: full subprocess (cmd/rc/stdout/stderr) is logged to the report.
        Short previews of assembled ASCII/HEX are also logged as INFO.
        - Parsing: the method ignores bit-level "0"/"1" annotations, consumes
        quoted printable chars, '[HH]' tokens, and plain hex pairs when fmt='hex'.
        - HEX normalization: spaces/case are ignored; "68 65 6C" == "68656c".
        - Use TX-only (set ch_tx, leave ch_rx None) if your signal is on TX to avoid
        interleaved artifacts. Keep 'hex_strip_00=True' when validating HEX if
        both lanes are decoded.
    """
    def execute():
        exe = _resolve_sigrok_cli(sigrok_cli, pulseview_dir)
        in_file = _resolve_reports_file(input_basename, "srzip")

        if not in_file.is_file():
            raise FX2TestError(f"Input capture not found: {in_file}")

        rx_name = _fmt_dch(ch_rx, required=False)
        tx_name = _fmt_dch(ch_tx, required=False)
        if not rx_name and not tx_name:
            raise FX2TestError("UART decode requires at least one channel: provide ch_rx or ch_tx.")

        parts = ["uart"]
        if rx_name:
            parts.append(f"rx={rx_name}")
        if tx_name:
            parts.append(f"tx={tx_name}")
        parts += [
            f"baudrate={baudrate}",
            f"data_bits={data_bits}",
            f"parity={parity}",
            f"stop_bits={stop_bits}",
            f"bit_order={bit_order}",
            f"format={fmt}",
            f"invert_rx={'yes' if invert_rx else 'no'}",
            f"invert_tx={'yes' if invert_tx else 'no'}",
            f"sample_point={sample_point}",
            f"rx_packet_delim={rx_packet_delim}",
            f"tx_packet_delim={tx_packet_delim}",
            f"rx_packet_len={rx_packet_len}",
            f"tx_packet_len={tx_packet_len}",
        ]

        base_cmd = [exe, "-i", str(in_file), "-P", ":".join(parts)]
        cmd = list(base_cmd)
        if ann_filter:
            cmd += ["-A", ann_filter]
        cmd += ["-l", "3"]
        if extra_args:
            cmd += list(extra_args)

        rep = get_active_reporter()
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            rc, out, err = res.returncode, res.stdout, res.stderr
        except Exception as e:
            rc, out, err = 1, "", str(e)

        if rep:
            rep.log_subprocess(cmd, rc, out, err, tag="SIGROK-UART")

        if rc != 0 and ann_filter:
            # Retry without '-A' (seen on some Windows builds)
            fallback = list(base_cmd) + ["-l", "3"]
            if extra_args:
                fallback += list(extra_args)
            try:
                res2 = subprocess.run(fallback, capture_output=True, text=True)
                rc, out, err = res2.returncode, res2.stdout, res2.stderr
            except Exception as e:
                rc, out, err = 1, "", str(e)
            if rep:
                rep.log_info("UART decode re-run without '-A' due to previous error.")
                rep.log_subprocess(fallback, rc, out, err, tag="SIGROK-UART")

        if rc != 0:
            raise FX2TestError(f"UART decode failed (rc={rc}). STDERR:\n{err}")

        decoded_text = (out or "").strip()
        ascii_joined, hex_joined = _assemble_uart_stream(decoded_text, fmt=str(fmt), ignore_bit_tokens=True)

        if rep:
            a_prev = ascii_joined if len(ascii_joined) <= 200 else ascii_joined[:200] + f"... [{len(ascii_joined)-200} more]"
            h_norm = _normalize_hex(hex_joined)
            h_prev = h_norm if len(h_norm) <= 200 else h_norm[:200] + f"... [{len(h_norm)-200} more]"
            rep.log_info(f"[UART] Joined ASCII: {a_prev}")
            rep.log_info(f"[UART] Joined HEX   : {h_prev}")
            if fmt.lower() == "hex" and hex_strip_00:
                h_no00 = " ".join(b for b in h_norm.split() if b != "00")
                h_prev2 = h_no00 if len(h_no00) <= 200 else h_no00[:200] + f"... [{len(h_no00)-200} more]"
                rep.log_info(f"[UART] HEX (drop 00): {h_prev2}")

        if expected is not None:
            if str(fmt).lower() == "hex":
                target = _normalize_hex(hex_joined)
                if hex_strip_00:
                    target = " ".join(b for b in target.split() if b != "00")
                exp = _normalize_hex(expected)
            else:
                target = ascii_joined
                exp = expected

            ok = _match_string(target, exp, match_mode)
            if not ok:
                prev = target if len(target) <= 500 else target[:500] + f"... [{len(target)-500} more]"
                raise FX2TestError(
                    f"UART expected check failed (mode={match_mode}).\n"
                    f"Expected: {expected}\n"
                    f"Got     : {prev}"
                )

            if rep:
                rep.log_info(f"[UART] Expected check PASSED (mode={match_mode}).")

        return ascii_joined

    return TestAction(name, execute)

# ----------------------- I2C Decode & Assert -------------------------

def decode_i2c_capture(
    name: str,
    *,
    input_basename: str,
    scl: Union[int, str],
    sda: Union[int, str],
    expected: Optional[str] = None,
    match_mode: str = "contains",
    ann_filter: Optional[str] = "data",
    sigrok_cli: Optional[str] = None,
    pulseview_dir: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
) -> TestAction:
    """
    Decode a saved .srzip capture as I²C (HEX only) via sigrok-cli and
    optionally assert the byte stream against an expected HEX string.

    The function extracts only hexadecimal byte tokens from the decoder output
    (e.g., “data” annotations), assembles them into a normalized, space-
    separated sequence ("AA BB CC …"), logs a short preview, and compares it
    using the selected match mode.

    Args:
        name (str): Action name for reporting.
        input_basename (str): Base filename (no extension) under Reports/<suite>;
            the file '<input_basename>.srzip' is decoded.
        scl (Union[int, str]): SCL channel index/name (e.g., 0, "1", "D1").
        sda (Union[int, str]): SDA channel index/name.
        expected (Optional[str]): Expected HEX string to compare against
            (spacing and case ignored). Examples: "A0 00 10", "a00010".
        match_mode (str): Comparison mode: 'equals' | 'contains' | 'startswith'
            | 'endswith' | 'regex'. Default 'contains'.
        ann_filter (Optional[str]): Optional '-A' filter for annotation classes,
            e.g., "data,address". If this causes a "not found" error on some
            builds, the method auto-retries without '-A'.
        sigrok_cli (Optional[str]): Path to sigrok-cli.exe; resolved if omitted.
        pulseview_dir (Optional[str]): PulseView directory used as a fallback
            search root for locating sigrok-cli.
        extra_args (Optional[List[str]]): Extra raw args appended to sigrok-cli.

    Returns:
        TestAction: On execution, returns the assembled HEX string.

    Raises:
        FX2TestError: If the capture is missing, sigrok-cli fails, channels are
            invalid, or the expected check fails.
    """
    def execute() -> str:
        exe = _resolve_sigrok_cli(sigrok_cli, pulseview_dir)
        in_file = _resolve_reports_file(input_basename, "srzip")
        if not in_file.is_file():
            raise FX2TestError(f"Input capture not found: {in_file}")

        scl_name = _fmt_dch(scl, required=True)
        sda_name = _fmt_dch(sda, required=True)

        parts = ["i2c", f"scl={scl_name}", f"sda={sda_name}"]

        base_cmd = [exe, "-i", str(in_file), "-P", ":".join(parts)]
        cmd = list(base_cmd)
        if ann_filter:
            cmd += ["-A", ann_filter]
        cmd += ["-l", "3"]
        if extra_args:
            cmd += list(extra_args)

        rep = get_active_reporter()
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            rc, out, err = res.returncode, res.stdout, res.stderr
        except Exception as e:
            rc, out, err = 1, "", str(e)
        if rep:
            rep.log_subprocess(cmd, rc, out, err, tag="SIGROK-I2C")

        if rc != 0 and ann_filter:
            # Retry without '-A' (some Windows builds require qualified names).
            fallback = list(base_cmd) + ["-l", "3"]
            if extra_args:
                fallback += list(extra_args)
            try:
                res2 = subprocess.run(fallback, capture_output=True, text=True)
                rc, out, err = res2.returncode, res2.stdout, res2.stderr
            except Exception as e:
                rc, out, err = 1, "", str(e)
            if rep:
                rep.log_info("I2C decode re-run without '-A' due to previous error.")
                rep.log_subprocess(fallback, rc, out, err, tag="SIGROK-I2C")

        if rc != 0:
            raise FX2TestError(f"I2C decode failed (rc={rc}). STDERR:\n{err}")

        decoded = (out or "").strip()
        hex_joined = _assemble_hex_from_annotations(decoded)

        if rep:
            prev = hex_joined if len(hex_joined) <= 200 else hex_joined[:200] + f"... [{len(hex_joined)-200} more]"
            rep.log_info(f"[I2C] HEX: {prev}")

        if expected is not None:
            target = _normalize_hex(hex_joined)
            exp = _normalize_hex(expected)
            ok = _match_string(target, exp, match_mode)
            if not ok:
                prev = target if len(target) <= 500 else target[:500] + f"... [{len(target)-500} more]"
                raise FX2TestError(
                    f"I2C expected check failed (mode={match_mode}).\n"
                    f"Expected: {expected}\n"
                    f"Got     : {prev}"
                )
            if rep:
                rep.log_info(f"[I2C] Expected check PASSED (mode={match_mode}).")

        return hex_joined

    return TestAction(name, execute)



# ----------------------- SPI Decode & Assert -------------------------

def decode_spi_capture(
    name: str,
    *,
    input_basename: str,
    clk: Union[int, str],
    mosi: Optional[Union[int, str]] = None,
    miso: Optional[Union[int, str]] = None,
    cs: Optional[Union[int, str]] = None,
    cpol: Union[int, str] = 0,
    cpha: Union[int, str] = 0,
    bit_order: str = "msb-first",
    lane: str = "mosi",
    expected: Optional[str] = None,
    match_mode: str = "contains",
    ann_filter: Optional[str] = None,
    sigrok_cli: Optional[str] = None,
    pulseview_dir: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
) -> TestAction:
    """
    Decode a saved .srzip capture as SPI (HEX only) via sigrok-cli and
    optionally assert the byte stream for a selected lane (MOSI/MISO).

    This function extracts hex byte tokens from the decoder output, assembles
    a normalized, space-separated sequence, logs a short preview, and compares
    using the selected match mode.

    Args:
        name (str): Action name for reporting.
        input_basename (str): Base filename (no extension) under Reports/<suite>;
            the file '<input_basename>.srzip' is decoded.
        clk (Union[int, str]): SPI clock channel (CLK/SCK).
        mosi (Optional[Union[int, str]]): MOSI channel (optional if you only need MISO).
        miso (Optional[Union[int, str]]): MISO channel (optional if you only need MOSI).
        cs (Optional[Union[int, str]]): Chip-select channel (optional but recommended).
        cpol (Union[int, str]): Clock polarity (0 or 1). Default 0.
        cpha (Union[int, str]): Clock phase (0 or 1). Default 0.
        bit_order (str): 'msb-first' or 'lsb-first'. Default 'msb-first'.
        lane (str): Which lane to assemble: 'mosi' | 'miso' | 'both'.
            If 'both', bytes from both lanes are concatenated in encounter order.
        expected (Optional[str]): Expected HEX string to compare (spacing/case ignored).
        match_mode (str): 'equals' | 'contains' | 'startswith' | 'endswith' | 'regex'.
        ann_filter (Optional[str]): Optional '-A' filter. If omitted, a sensible
            default is used based on 'lane':
              - 'mosi' -> 'mosi-data'
              - 'miso' -> 'miso-data'
              - 'both' -> 'mosi-data,miso-data'
            If this causes a "not found" error, the method auto-retries without '-A'.
        sigrok_cli (Optional[str]): Path to sigrok-cli.exe; resolved if omitted.
        pulseview_dir (Optional[str]): PulseView directory used as a fallback.
        extra_args (Optional[List[str]]): Extra raw args appended to sigrok-cli.

    Returns:
        TestAction: On execution, returns the assembled HEX string.

    Raises:
        FX2TestError: If the capture is missing, sigrok-cli fails, no lane
            channels are provided, or the expected check fails.
    """
    def execute() -> str:
        exe = _resolve_sigrok_cli(sigrok_cli, pulseview_dir)
        in_file = _resolve_reports_file(input_basename, "srzip")
        if not in_file.is_file():
            raise FX2TestError(f"Input capture not found: {in_file}")

        clk_name = _fmt_dch(clk, required=True)
        mosi_name = _fmt_dch(mosi, required=False)
        miso_name = _fmt_dch(miso, required=False)
        cs_name = _fmt_dch(cs, required=False)

        if lane not in ("mosi", "miso", "both"):
            raise FX2TestError("lane must be 'mosi', 'miso', or 'both'.")
        if lane in ("mosi", "both") and not mosi_name and not miso_name:
            # If both MOSI/MISO are missing, it's invalid.
            raise FX2TestError("Provide MOSI and/or MISO channel(s) for SPI decode.")
        if lane == "mosi" and not mosi_name:
            raise FX2TestError("lane='mosi' requires a MOSI channel.")
        if lane == "miso" and not miso_name:
            raise FX2TestError("lane='miso' requires a MISO channel.")

        parts = ["spi", f"clk={clk_name}"]
        if mosi_name:
            parts.append(f"mosi={mosi_name}")
        if miso_name:
            parts.append(f"miso={miso_name}")
        if cs_name:
            parts.append(f"cs={cs_name}")
        parts += [f"cpol={cpol}", f"cpha={cpha}", f"bitorder={bit_order}"]

        base_cmd = [exe, "-i", str(in_file), "-P", ":".join(parts)]
        # Determine default annotation filter if none provided.
        af = ann_filter
        if af is None:
            af = {"mosi": "mosi-data", "miso": "miso-data", "both": "mosi-data,miso-data"}[lane]

        cmd = list(base_cmd)
        if af:
            cmd += ["-A", af]
        cmd += ["-l", "3"]
        if extra_args:
            cmd += list(extra_args)

        rep = get_active_reporter()
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            rc, out, err = res.returncode, res.stdout, res.stderr
        except Exception as e:
            rc, out, err = 1, "", str(e)
        if rep:
            rep.log_subprocess(cmd, rc, out, err, tag="SIGROK-SPI")

        if rc != 0 and af:
            fallback = list(base_cmd) + ["-l", "3"]
            if extra_args:
                fallback += list(extra_args)
            try:
                res2 = subprocess.run(fallback, capture_output=True, text=True)
                rc, out, err = res2.returncode, res2.stdout, res2.stderr
            except Exception as e:
                rc, out, err = 1, "", str(e)
            if rep:
                rep.log_info("SPI decode re-run without '-A' due to previous error.")
                rep.log_subprocess(fallback, rc, out, err, tag="SIGROK-SPI")

        if rc != 0:
            raise FX2TestError(f"SPI decode failed (rc={rc}). STDERR:\n{err}")

        decoded = (out or "").strip()
        hex_joined = _assemble_hex_from_annotations(decoded)

        if rep:
            prev = hex_joined if len(hex_joined) <= 200 else hex_joined[:200] + f"... [{len(hex_joined)-200} more]"
            rep.log_info(f"[SPI:{lane.upper()}] HEX: {prev}")

        if expected is not None:
            target = _normalize_hex(hex_joined)
            exp = _normalize_hex(expected)
            ok = _match_string(target, exp, match_mode)
            if not ok:
                prev = target if len(target) <= 500 else target[:500] + f"... [{len(target)-500} more]"
                raise FX2TestError(
                    f"SPI expected check failed (mode={match_mode}).\n"
                    f"Expected: {expected}\n"
                    f"Got     : {prev}"
                )
            if rep:
                rep.log_info(f"[SPI:{lane.upper()}] Expected check PASSED (mode={match_mode}).")

        return hex_joined

    return TestAction(name, execute)



# -------------------------- Tool Availability -------------------------


def verify_sigrok_available(name: str,
                            sigrok_cli: Optional[str] = None,
                            pulseview_dir: Optional[str] = None) -> TestAction:
    """
    Create a TestAction that verifies sigrok-cli is resolvable and responsive.

    Args:
        name (str): Action name.
        sigrok_cli (Optional[str]): Explicit path to sigrok-cli.
        pulseview_dir (Optional[str]): Fallback search root for sigrok-cli.

    Returns:
        TestAction: Execute to run 'sigrok-cli --version'. Returns version text on success.

    Raises:
        FX2TestError: If sigrok-cli cannot be resolved or returns non-zero.
    """
    def execute():
        exe = _resolve_sigrok_cli(sigrok_cli, pulseview_dir)
        cmd = [exe, "--version"]
        rep = get_active_reporter()
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            rc, out, err = res.returncode, res.stdout, res.stderr
        except Exception as e:
            rc, out, err = 1, "", str(e)

        if rep:
            rep.log_subprocess(cmd, rc, out, err, tag="SIGROK")

        if rc != 0:
            raise FX2TestError(f"sigrok-cli not working (rc={rc}). STDERR: {err}")
        return out.strip()

    return TestAction(name, execute)


def verify_pulseview_available(name: str, pulseview_dir: str) -> TestAction:
    """
    Create a TestAction that verifies PulseView is locatable.

    Args:
        name (str): Action name.
        pulseview_dir (str): Directory where pulseview.exe resides.

    Returns:
        TestAction: Execute to resolve PulseView path. Returns resolved path.

    Raises:
        FX2TestError: If PulseView cannot be found.
    """
    def execute():
        exe = _resolve_pulseview(pulseview_dir)
        rep = get_active_reporter()
        if rep:
            rep.log_info(f"PulseView resolved: {exe}")
        return exe

    return TestAction(name, execute)


# --------------------------- Parsing Helpers --------------------------


def _assemble_uart_stream(raw_stdout: str, *, fmt: Optional[str] = None, ignore_bit_tokens: bool = True) -> Tuple[str, str]:
    """
    Assemble continuous ASCII and HEX streams from sigrok-cli UART decoder output.

    This parser is robust to verbose outputs that mix:
      - data-bit annotations ("0"/"1"),
      - data-value annotations ('h', 'e', ...),
      - hex bytes in bracket form ([0D], [6F], ...),
      - hex bytes in plain form when format=hex ("68", "0d", possibly multiple pairs like "68656c"),
      - other messages ("Start bit", "Stop bit", "Frame error", ...).

    By default, single-character tokens '0' and '1' are **ignored** because they usually
    come from bit-level rows and will otherwise pollute the stream (e.g., HEX becomes
    '31 30 30 31 ...' which are ASCII codes for '1'/'0').

    Args:
        raw_stdout (str): Raw text from sigrok-cli UART decoder (stdout).
        fmt (Optional[str]): Decoder 'format' argument ('ascii'|'hex'|'dec'|'oct'|'bin'). Used to
            better interpret tokens that contain multiple hex digits in a single quoted string.
        ignore_bit_tokens (bool): If True, drop single '0'/'1' tokens (bit-level annotations).

    Returns:
        Tuple[str, str]: (ascii_joined, hex_joined)
            - ascii_joined: concatenated printable characters from RX/TX data values.
            - hex_joined  : space-separated hex byte pairs (lowercase), including both the
                            byte value of ascii chars and any explicit hex tokens seen.
    """
    ascii_chars: List[str] = []
    hex_bytes: List[str] = []
    fmt = (fmt or "").lower()

    for m in re.finditer(r"\"([^\"]+)\"", raw_stdout):
        token = m.group(1)

        # 1) Bracketed hex byte like [0D], [6f], [00]
        hx = re.fullmatch(r"\[([0-9A-Fa-f]{2})\]", token)
        if hx:
            hex_bytes.append(hx.group(1).lower())
            continue

        # 2) Bit-level tokens "0"/"1" — ignore by default
        if ignore_bit_tokens and token in ("0", "1"):
            continue

        # 3) When format=hex, the PD often emits plain hex pairs in a single token.
        #    Accept 2,4,6,... hex digits and split into byte pairs.
        if re.fullmatch(r"[0-9A-Fa-f]{2}([0-9A-Fa-f]{2})*", token):
            for i in range(0, len(token), 2):
                byte = token[i:i+2].lower()
                hex_bytes.append(byte)
                # Also reconstruct ASCII if printable
                try:
                    ch = bytes.fromhex(byte).decode("latin1")
                    if ch.isprintable():
                        ascii_chars.append(ch)
                except Exception:
                    pass
            continue

        # 4) Single printable character => treat as decoded data byte
        if len(token) == 1 and token.isprintable():
            ascii_chars.append(token)
            hex_bytes.append(f"{ord(token):02x}")
            continue

        # 5) Everything else (e.g., "Start bit", "Stop bit", "Frame error") => ignore

    ascii_joined = "".join(ascii_chars)
    hex_joined = " ".join(hex_bytes)
    return ascii_joined, hex_joined


def _normalize_hex(s: str) -> str:
    """
    Normalize hex string for comparison: lowercase, single spaces between byte pairs.
    """
    tokens = re.findall(r"[0-9A-Fa-f]{2}", s)
    return " ".join(t.lower() for t in tokens)


def _match_string(target: str, expected: str, mode: str) -> bool:
    """
    Compare strings using selected mode.

    Args:
        target (str): String produced by decode.
        expected (str): Expected pattern or string.
        mode (str): 'equals' | 'contains' | 'startswith' | 'endswith' | 'regex'.

    Returns:
        bool: True if match condition met, else False.
    """
    if mode == "equals":
        return target == expected
    if mode == "contains":
        return expected in target
    if mode == "startswith":
        return target.startswith(expected)
    if mode == "endswith":
        return target.endswith(expected)
    if mode == "regex":
        try:
            return re.search(expected, target, re.MULTILINE) is not None
        except re.error:
            return False
    raise FX2TestError(f"Unsupported match_mode '{mode}'.")

def _append_set(
    cmd: List[str],
    set_list: Optional[List[str]],
) -> None:
    if set_list:
        for item in set_list:
            cmd += ["--set", item]

def _append_input_file(
    cmd: List[str],
    input_file: Optional[Path],
) -> None:
    if input_file:
        cmd += ["-i", str(input_file)]

def _append_input_format(
    cmd: List[str],
    input_format: Optional[str],
) -> None:
    if input_format:
        cmd += ["-I", input_format]

def _append_output_format(
    cmd: List[str],
    output_format: str,
    output_file: Optional[Path],
) -> None:
    cmd += ["-O", output_format]
    if output_file:
        cmd += ["-o", str(output_file)]

def _append_log_level(
    cmd: List[str],
    loglevel: int,
) -> None:
    cmd += ["-l", str(loglevel)]

def convert_any(
    name: str,
    *,
    input_file: str,
    input_format: Optional[str] = None,
    output_basename: str,
    output_format: str,
    sigrok_cli: Optional[str] = None,
    pulseview_dir: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
) -> TestAction[str]:
    """
    Convert a file that sigrok understands into another sigrok-supported format
    in a single pass using sigrok-cli.

    This action resolves the active Reports/<suite> directory, reads the given
    input file from there, and writes the converted file back into the same
    report folder under '<output_basename>.<output_format>'. The full
    subprocess (command, rc, stdout, stderr) is logged into the UTFW report.

    Args:
        name (str): Human-readable step name shown in reports.
        input_file (str): File name with extension located under Reports/<suite>,
            e.g., 'capture.srzip', 'trace.csv', 'raw.bin'.
        input_format (Optional[str]): Force a specific input reader (same values
            as 'sigrok-cli -I'; None lets sigrok auto-detect).
        output_basename (str): Base name (no extension) for the converted file.
        output_format (str): Target format (same values as 'sigrok-cli -O',
            e.g., 'vcd', 'srzip', 'csv', 'bits', 'wav', ...).
        sigrok_cli (Optional[str]): Explicit path to sigrok-cli.exe. If not set,
            standard locations/PATH are tried (and PulseView dir as a hint).
        pulseview_dir (Optional[str]): Directory of pulseview.exe used as a
            fallback root for locating sigrok-cli.
        extra_args (Optional[List[str]]): Additional raw arguments appended to
            the sigrok-cli command (advanced use).

    Returns:
        TestAction: On execution, returns the absolute path to the created file
        as a string if conversion succeeds.

    Raises:
        FX2TestError: If the input file is missing, sigrok-cli cannot be
        resolved, the conversion fails (non-zero rc), or parameters are invalid.

    Notes:
        - The input path is resolved as: '<Reports/<suite>>/<input_file>'.
        - The output path is: '<Reports/<suite>>/<output_basename>.<output_format>'.
        - Typical examples:
            * CSV → VCD:
                convert_any("CSV→VCD", input_file="log.csv",
                            output_basename="log", output_format="vcd")
            * SRZIP → CSV with writer options:
                convert_any("SRZIP→CSV", input_file="capture.srzip",
                            output_basename="capture", output_format="csv",
                            extra_args=["-O", "csv:column_formats=*l"])
            * Auto-detect input, produce SRZIP:
                convert_any("ANY→SRZIP", input_file="unknown.bin",
                            output_basename="unknown", output_format="srzip")
    """
    def execute() -> str:
        exe = _resolve_sigrok_cli(sigrok_cli, pulseview_dir)
        in_path = _ensure_reports_dir() / input_file
        if not in_path.exists():
            raise FX2TestError(f"Input file not found: {in_path}")

        out_path = _resolve_reports_file(output_basename, output_format)

        cmd = [exe, "-i", str(in_path)]
        if input_format:
            cmd += ["-I", input_format]
        cmd += ["-O", output_format, "-o", str(out_path)]
        if extra_args:
            cmd += extra_args
        _append_log_level(cmd, 1)

        rep = get_active_reporter()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
            rc, out, err = proc.returncode, proc.stdout, proc.stderr
        except Exception as e:
            rc, out, err = 1, "", str(e)
        if rep:
            rep.log_subprocess(cmd, rc, out, err, tag="SIGROK-CONV")
        if rc:
            raise FX2TestError(f"Conversion failed (rc={rc}): {err}")
        return str(out_path)

    return TestAction(name, execute)
