# UTFW/modules/network/pcap_capture.py
import os
import shlex
import time
import signal
import random
import string
import platform
import subprocess
from pathlib import Path
from typing import Optional, List, Union, Tuple

from UTFW.core.logger import get_active_logger
from UTFW.core.core import TestAction


class PCAPCaptureError(Exception):
    """Raised when packet capture fails to start, execute, or write the expected output file."""


def _which(exe: str) -> Optional[str]:
    """Return absolute path to executable if it exists in PATH."""
    for p in os.environ.get("PATH", "").split(os.pathsep):
        cand = Path(p) / exe
        if cand.exists() and cand.is_file():
            return str(cand)
        # Windows: also try with .exe
        if platform.system().lower().startswith("win"):
            cand_exe = cand.with_suffix(".exe")
            if cand_exe.exists() and cand_exe.is_file():
                return str(cand_exe)
    return None


def _quote_list(argv: List[str]) -> str:
    """Human-friendly quoted command string for logs."""
    def q(x: str) -> str:
        # Avoid shlex.quote on Windows to keep paths readable; still safe for logging only
        if platform.system().lower().startswith("win"):
            if " " in x or any(c in x for c in ['"', "'"]):
                return f'"{x}"'
            return x
        import shlex as _shlex
        return _shlex.quote(x)
    return " ".join(q(x) for x in argv)


def _make_parent_dirs(path: Union[str, os.PathLike]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def _rand_tag(n: int = 6) -> str:
    return "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(n))


def _dumpcap_list_interfaces(dumpcap_exe: str, env: Optional[dict], cwd: Optional[Union[str, os.PathLike]]) -> List[str]:
    """
    Return lines of `dumpcap -D` output (interface list). Each line typically looks like:
      1. \\Device\\NPF_{GUID} (Ethernet 2)
      2. \\Device\\NPF_Loopback (Npcap Loopback Adapter)
    """
    logger = get_active_logger()

    if logger:
        logger.log(f"[PCAP-CAPTURE] _dumpcap_list_interfaces() called")
        logger.log(f"[PCAP-CAPTURE]   dumpcap_exe={dumpcap_exe}")
        logger.log(f"[PCAP-CAPTURE]   cwd={cwd or os.getcwd()}")

    try:
        proc = subprocess.run(
            [dumpcap_exe, "-D"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            cwd=str(cwd) if cwd else None,
            timeout=10
        )
        lines = (proc.stdout or "").splitlines()
        result = [ln.strip() for ln in lines if ln.strip()]

        if logger:
            logger.log(f"[PCAP-CAPTURE] dumpcap -D returned {len(result)} interfaces")
            for ln in result:
                logger.log(f"[PCAP-CAPTURE]   {ln}")

        return result

    except subprocess.TimeoutExpired as e:
        if logger:
            logger.log(f"[PCAP-CAPTURE ERROR] dumpcap -D timed out after 10s")
        return []
    except Exception as e:
        if logger:
            logger.log(f"[PCAP-CAPTURE ERROR] dumpcap -D failed: {type(e).__name__}: {e}")
        return []


def _dumpcap_resolve_interface(requested: str, dumpcap_exe: str, env: Optional[dict], cwd: Optional[Union[str, os.PathLike]]) -> Tuple[str, Optional[str]]:
    """
    Resolve a user-provided interface name/alias/number to what dumpcap accepts.
    Order of preference:
      1) Numeric index (as-is)
      2) Windows convenience: if requested in {'lo','loopback', 'npcap loopback', '127.0.0.1'}
         choose the entry whose desc/dev contains 'loopback'
      3) Exact match on description or device
      4) Substring match on description or device
      5) Fallback to original string
    """
    logger = get_active_logger()

    if logger:
        logger.log(f"[PCAP-CAPTURE] _dumpcap_resolve_interface() called")
        logger.log(f"[PCAP-CAPTURE]   requested={requested}")

    req = (requested or "").strip()
    if req.isdigit():
        if logger:
            logger.log(f"[PCAP-CAPTURE] Interface is numeric: {req} (using as-is)")
        return req, None

    lines = _dumpcap_list_interfaces(dumpcap_exe, env, cwd)
    pretty = "\n".join(lines) if lines else None

    entries = []
    for ln in lines:
        idx = dev = desc = None
        try:
            if ". " in ln:
                idx_part, rest = ln.split(". ", 1)
                idx = idx_part.strip()
                if "(" in rest and rest.endswith(")"):
                    left, _, right = rest.partition(" (")
                    dev = left.strip()
                    desc = right[:-1].strip()
                else:
                    desc = rest.strip()
                    dev = desc
        except Exception:
            pass
        if idx is not None:
            entries.append((idx, dev or "", desc or ""))

    sys_is_win = platform.system().lower().startswith("win")
    lower_req = req.lower()

    # (2) Prefer loopback explicitly on Windows BEFORE any generic substring matches
    if sys_is_win and lower_req in {"lo", "loopback", "npcap loopback", "npcap loopback adapter", "127.0.0.1"}:
        if logger:
            logger.log(f"[PCAP-CAPTURE] Windows loopback alias detected, searching for loopback interface...")
        for idx, dev, desc in entries:
            if "loopback" in desc.lower() or "loopback" in dev.lower():
                if logger:
                    logger.log(f"[PCAP-CAPTURE] Resolved to loopback: idx={idx}, desc={desc}")
                return idx, pretty

    # (3) Exact match on desc or dev
    if logger:
        logger.log(f"[PCAP-CAPTURE] Trying exact match on description or device...")
    for idx, dev, desc in entries:
        if lower_req == desc.lower() or lower_req == dev.lower():
            if logger:
                logger.log(f"[PCAP-CAPTURE] Exact match found: idx={idx}, dev={dev}, desc={desc}")
            return idx, pretty

    # (4) Substring match on desc or dev
    if logger:
        logger.log(f"[PCAP-CAPTURE] No exact match, trying substring match...")
    for idx, dev, desc in entries:
        if lower_req in desc.lower() or lower_req in dev.lower():
            if logger:
                logger.log(f"[PCAP-CAPTURE] Substring match found: idx={idx}, dev={dev}, desc={desc}")
            return idx, pretty

    # (5) Fallback
    if logger:
        logger.log(f"[PCAP-CAPTURE] No match found, using requested value as-is: {req}")
    return req, pretty


def CapturePcap(name: str,
                output_path: str,
                *,
                interface: str,
                bpf: Optional[str] = None,
                duration_s: Optional[float] = None,
                packet_count: Optional[int] = None,
                snaplen: Optional[int] = None,
                promiscuous: bool = True,
                file_format: str = "pcapng",
                ring_files: Optional[int] = None,
                ring_megabytes: Optional[int] = None,
                require_tool: Optional[str] = None,
                env: Optional[dict] = None,
                cwd: Optional[Union[str, os.PathLike]] = None,
        negative_test: bool = False) -> TestAction:
    """Create a TestAction that captures packets from a live interface into a PCAP/PCAPNG file.

    This TestAction factory starts a live capture using **dumpcap** (Wireshark capture engine)
    when available, and falls back to **tcpdump** if dumpcap is not found. It writes the capture
    to `output_path`, applying optional BPF filtering, capture limits (duration or packet count),
    snap length, and ring buffering.

    The action logs every detail: selected tool, fully expanded command line, environment deltas,
    timing, output sizes, and tool stdout/stderr. If both `duration_s` and `packet_count` are
    omitted, the action will capture until the tool exits (or until the framework times out
    the whole test, if applicable).

    Args:
        name (str): Human-readable name for the test action.
        output_path (str): Path to the capture file to write (created, parents ensured).
        interface (str): OS interface name, description, or numeric index (dumpcap -D).
        bpf (str, optional): Capture-time Berkeley Packet Filter, e.g., "udp and port 53".
        duration_s (float, optional): Stop capture after this many seconds (dumpcap: -a duration;
            tcpdump fallback uses a timed stop).
        packet_count (int, optional): Stop after capturing this many packets (dumpcap/tcpdump: -c).
        snaplen (int, optional): Maximum bytes per packet to capture (dumpcap/tcpdump: -s).
        promiscuous (bool, optional): Enable promiscuous mode (default True). If False, pass "-p".
        file_format (str, optional): "pcapng" (default) or "pcap". For dumpcap, use "-F pcap" to write pcap.
            tcpdump always writes classic pcap.
        ring_files (int, optional): With dumpcap, create a ring buffer with this many files (-b files:N).
            Ignored by tcpdump unless advanced rotation is implemented.
        ring_megabytes (int, optional): With dumpcap, rotate each file at this approximate size in MB
            (-b filesize:KB). Ignored by tcpdump unless advanced rotation is implemented.
        require_tool (str, optional): Force a specific tool: "dumpcap" or "tcpdump". If the requested tool
            is not available, the action raises PCAPCaptureError.
        env (dict, optional): Extra environment variables for the capture subprocess.
        cwd (str | PathLike, optional): Working directory for the capture subprocess.

    Returns:
        TestAction: Action that runs the capture and returns `output_path` when the capture completes.

    Raises:
        PCAPCaptureError: If no suitable capture tool is available, if the tool exits with non-zero status,
            or when no output file is produced.

    Example:
        >>> action = CapturePcap(
        ...     "Capture 10s UDP:53 on eth0",
        ...     "captures/dns10s.pcapng",
        ...     interface="eth0",
        ...     bpf="udp and port 53",
        ...     duration_s=10,
        ...     snaplen=256,
        ...     file_format="pcapng"
        ... )
        >>> action()
    """
    # PRE-RESOLVE: Do expensive setup BEFORE execute() to minimize startup latency
    # This is critical for parallel execution where timing matters
    dumpcap_path = _which("dumpcap")
    tcpdump_path = _which("tcpdump")

    tool = None
    if require_tool:
        rq = require_tool.strip().lower()
        if rq == "dumpcap":
            if not dumpcap_path:
                raise PCAPCaptureError("Requested tool 'dumpcap' not found in PATH.")
            tool = ("dumpcap", dumpcap_path)
        elif rq == "tcpdump":
            if not tcpdump_path:
                raise PCAPCaptureError("Requested tool 'tcpdump' not found in PATH.")
            tool = ("tcpdump", tcpdump_path)
        else:
            raise PCAPCaptureError(f"Unknown require_tool={require_tool!r}; use 'dumpcap' or 'tcpdump'.")
    else:
        # Prefer dumpcap when available
        if dumpcap_path:
            tool = ("dumpcap", dumpcap_path)
        elif tcpdump_path:
            tool = ("tcpdump", tcpdump_path)
        else:
            raise PCAPCaptureError("Neither 'dumpcap' nor 'tcpdump' found in PATH.")

    tool_name, tool_exe = tool

    # PRE-RESOLVE interface for dumpcap to avoid delay during execution
    pre_resolved_iface = None
    pre_listing_text = None
    if tool_name == "dumpcap":
        pre_resolved_iface, pre_listing_text = _dumpcap_resolve_interface(interface, tool_exe, os.environ.copy(), cwd)

    def execute():
        logger = get_active_logger()
        tag = _rand_tag()

        # Ensure output directory exists
        _make_parent_dirs(output_path)

        # Build command
        argv: List[str] = [tool_exe]

        if tool_name == "dumpcap":
            # Use pre-resolved interface
            resolved_iface = pre_resolved_iface
            listing_text = pre_listing_text
            if logger:
                if listing_text:
                    logger.log(f"[PCAP-CAPTURE] tag={tag} dumpcap -D:\n{listing_text}")
                if resolved_iface != interface:
                    logger.log(f"[PCAP-CAPTURE] tag={tag} resolved interface {interface!r} -> {resolved_iface!r}")

            # Interface
            argv += ["-i", resolved_iface]

            # File format: use modern flag (-F) instead of deprecated -P
            fmt = str(file_format).strip().lower()
            if fmt in {"pcap", "pcapng"}:
                argv += ["-F", fmt]

            # Output file
            argv += ["-w", output_path]

            # Promiscuous
            if not promiscuous:
                argv += ["-p"]

            # Snap length
            if snaplen is not None:
                argv += ["-s", str(int(snaplen))]

            # Packet count
            if packet_count is not None:
                argv += ["-c", str(int(packet_count))]

            # Duration (auto-stop)
            if duration_s is not None:
                # dumpcap expects integer seconds for -a duration
                argv += ["-a", f"duration:{int(float(duration_s))}"]

            # Ring buffer
            if ring_files is not None:
                argv += ["-b", f"files:{int(ring_files)}"]
            if ring_megabytes is not None:
                # dumpcap uses KB for `filesize`, so convert MB->KB
                argv += ["-b", f"filesize:{int(ring_megabytes) * 1024}"]

            # BPF filter at capture time
            if bpf:
                # Validate BPF filter syntax before starting capture
                if logger:
                    logger.log(f"[PCAP-CAPTURE] tag={tag} validating BPF filter: {bpf}")
                argv += ["-f", bpf]

        else:  # tcpdump
            # Interface
            argv += ["-i", interface]

            # Promiscuous
            if not promiscuous:
                argv += ["-p"]

            # Snap length
            if snaplen is not None:
                argv += ["-s", str(int(snaplen))]

            # Output file (classic pcap)
            argv += ["-w", output_path]

            # Packet count
            if packet_count is not None:
                argv += ["-c", str(int(packet_count))]

            # NOTE: tcpdump doesn't have a simple built-in `-a duration` like dumpcap.
            # We implement timed stop by sending SIGINT after duration_s below.

            # BPF filter expression must be LAST (no -f flag)
            if bpf:
                argv += [bpf]

        # Environment
        proc_env = os.environ.copy()
        # Ensure dumpcap honors system capture privileges (Windows: Npcap in Admin mode might be needed)
        if env:
            for k, v in env.items():
                if v is None and k in proc_env:
                    proc_env.pop(k, None)
                elif v is not None:
                    proc_env[str(k)] = str(v)

        # Logging â€“ pre-exec
        if logger:
            logger.log(f"[PCAP-CAPTURE] tag={tag} tool={tool_name} exe={tool_exe}")
            logger.log(f"[PCAP-CAPTURE] tag={tag} interface={interface!r} promiscuous={promiscuous} "
                       f"snaplen={snaplen} duration_s={duration_s} packet_count={packet_count} "
                       f"file_format={file_format} ring_files={ring_files} ring_megabytes={ring_megabytes}")
            logger.log(f"[PCAP-CAPTURE] tag={tag} bpf={bpf!r}")
            logger.log(f"[PCAP-CAPTURE] tag={tag} output_path={output_path}")
            if env:
                logger.log(f"[PCAP-CAPTURE] tag={tag} env_overrides={env}")
            logger.log(f"[PCAP-CAPTURE] tag={tag} cwd={cwd or os.getcwd()}")
            logger.log(f"[PCAP-CAPTURE] tag={tag} argv={_quote_list(argv)}")

        # Launch
        start_time = time.time()
        try:
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=proc_env,
                cwd=str(cwd) if cwd else None,
                text=True,
            )
        except FileNotFoundError as e:
            raise PCAPCaptureError(f"Failed to start {tool_name}: {e}") from e
        except Exception as e:
            raise PCAPCaptureError(f"Failed to launch capture tool: {e}") from e

        # Give capture tool time to initialize and start capturing
        # This is critical on Windows where dumpcap needs time to initialize the interface
        # and apply BPF filters. Wait for the output file to be created with header.
        if logger:
            logger.log(f"[PCAP-CAPTURE] tag={tag} waiting for capture tool to initialize...")

        # Wait up to 3 seconds for dumpcap to create the output file and write the header
        init_deadline = time.time() + 3.0
        file_created = False
        while time.time() < init_deadline:
            if Path(output_path).exists() and Path(output_path).stat().st_size >= 24:
                file_created = True
                if logger:
                    logger.log(f"[PCAP-CAPTURE] tag={tag} output file created, dumpcap is ready")
                break
            time.sleep(0.1)

        if not file_created and logger:
            logger.log(f"[PCAP-CAPTURE] tag={tag} WARNING: output file not created within 3s, proceeding anyway")

        # Additional 200ms buffer to ensure dumpcap is truly ready to capture
        time.sleep(0.2)

        # Manage duration for tcpdump (dumpcap already has -a duration)
        timed_stop = False
        if tool_name == "tcpdump" and duration_s is not None and packet_count is None:
            if logger:
                logger.log(f"[PCAP-CAPTURE] tag={tag} tcpdump timed-run for {duration_s}s then SIGINT")
            try:
                try:
                    proc.wait(timeout=float(duration_s))
                except subprocess.TimeoutExpired:
                    timed_stop = True
                    # Try graceful stop
                    if platform.system().lower().startswith("win"):
                        proc.terminate()
                    else:
                        proc.send_signal(signal.SIGINT)
                    try:
                        proc.wait(timeout=5.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            except Exception as e:
                proc.kill()
                raise PCAPCaptureError(f"Error while timing tcpdump capture: {e}") from e

        # Collect output (for dumpcap or tcpdump default modes)
        try:
            stdout, stderr = proc.communicate(
                timeout=None if (tool_name == "dumpcap" or packet_count is not None or duration_s is not None) else 1.0
            )
        except subprocess.TimeoutExpired:
            if logger:
                logger.log(f"[PCAP-CAPTURE] tag={tag} safety stop: no duration/count set; terminating capture")
            try:
                if platform.system().lower().startswith("win"):
                    proc.terminate()
                else:
                    proc.send_signal(signal.SIGINT)
                stdout, stderr = proc.communicate(timeout=5.0)
            except Exception:
                proc.kill()
                stdout, stderr = ("", "forced kill due to timeout")

        rc = proc.returncode
        elapsed = time.time() - start_time

        # Logging â€“ post-exec
        if logger:
            logger.log(f"[PCAP-CAPTURE] tag={tag} exit_code={rc} elapsed_s={elapsed:.3f} timed_stop={timed_stop}")
            if stdout:
                logger.log("[PCAP-CAPTURE STDOUT]\n" + stdout.rstrip())
            if stderr:
                logger.log("[PCAP-CAPTURE STDERR]\n" + stderr.rstrip())

        if rc not in (0, None):
            # Provide helpful hint when interface may be invalid
            hint = ""
            if tool_name == "dumpcap" and "no such device" in (stderr or "").lower():
                hint = " (check interface name or use numeric index from 'dumpcap -D')"
            raise PCAPCaptureError(f"{tool_name} exited with non-zero status {rc}{hint}")

        # Validate output
        out_path = Path(output_path)
        file_size = out_path.stat().st_size if out_path.exists() else 0
        if logger:
            logger.log(f"[PCAP-CAPTURE] tag={tag} file size after capture: {file_size} bytes")
            if file_size == 24:
                logger.log(f"[PCAP-CAPTURE] tag={tag} WARNING: File contains only PCAP header, no packets captured!")
                logger.log(f"[PCAP-CAPTURE] tag={tag} This suggests either:")
                logger.log(f"[PCAP-CAPTURE] tag={tag}   1. BPF filter '{bpf}' matched zero packets")
                logger.log(f"[PCAP-CAPTURE] tag={tag}   2. No traffic occurred during capture window")
                logger.log(f"[PCAP-CAPTURE] tag={tag}   3. Interface '{interface}' did not see the expected traffic")
        if not out_path.exists() or out_path.stat().st_size == 0:
            # dumpcap ring buffer: if ring_files specified, the base -w is a prefix and files may have suffixes.
            # Try to find at least one produced file.
            produced = []
            if tool_name == "dumpcap" and (ring_files or ring_megabytes):
                parent = out_path.parent
                prefix = out_path.name
                for f in parent.glob(prefix + "*"):
                    if f.is_file() and f.stat().st_size > 0:
                        produced.append(str(f))
                if produced and logger:
                    for f in produced:
                        logger.log(f"[PCAP-CAPTURE] tag={tag} produced ring file: {f} size={Path(f).stat().st_size} bytes")
            else:
                raise PCAPCaptureError(f"No capture output written to {output_path!r}")

        # Final log
        if logger and out_path.exists():
            logger.log(f"[PCAP-CAPTURE] tag={tag} output_size={out_path.stat().st_size} bytes")

        return output_path

    return TestAction(name, execute, negative_test=negative_test)

def Ping(name: str,
         target: str,
         *,
         count: int = 1,
         timeout_s: float = 2.0,
         interval_s: Optional[float] = None,
         background: bool = False,
         duration_s: Optional[float] = None,
        negative_test: bool = False) -> TestAction:
    """Create a TestAction that sends ICMP echo(s) to a target host.

    This TestAction invokes the system `ping` in a cross-platform way to
    generate predictable ICMP traffic. It supports both blocking (foreground)
    and background modes.

    Foreground mode (background=False):
        Runs `ping` and waits for completion. `count`, `timeout_s`, and (on Unix)
        `interval_s` are respected.

    Background mode (background=True):
        Starts `ping` and returns immediately so other actions (e.g., capture)
        can run concurrently.
        - If `duration_s` is provided and `count <= 0`, the action runs
          ping in *continuous* mode for the given duration (Windows: `-t`,
          Unix: omit `-c`) and then stops it via a watchdog.
        - If `duration_s` is provided and `count > 0`, the action starts ping
          with the requested count; it will likely finish before `duration_s`.
        - If `duration_s` is None and `count <= 0`, ping runs continuously
          until externally stopped.

    Args:
        name (str): Human-readable name for the test action.
        target (str): Destination IP or hostname (e.g., "127.0.0.1").
        count (int, optional): Number of echo requests. Use <=0 for continuous
            in background mode. Defaults to 1.
        timeout_s (float, optional): Per-request timeout in seconds. Defaults to 2.0.
            (Windows uses `-w` milliseconds, Unix uses `-W` seconds.)
        interval_s (Optional[float], optional): Interval between requests (Unix `-i` only).
        background (bool, optional): Start ping in background (non-blocking). Defaults to False.
        duration_s (Optional[float], optional): If set in background mode with continuous ping
            (`count <= 0`), stop ping after this many seconds via a watchdog thread.

    Returns:
        TestAction:
            - Foreground: returns True on success (raises on error).
            - Background: returns True immediately after starting the process.

    Raises:
        PCAPCaptureError: If `ping` is not found or fails to start/execute.

    Example:
        >>> # Foreground, one echo:
        >>> Ping("Ping loopback once", "127.0.0.1")()
        >>> # Background, continuous for 6 seconds (overlaps with capture):
        >>> Ping("Ping BG", "127.0.0.1", background=True, count=0, duration_s=6.0)()
    """
    def execute():
        logger = get_active_logger()

        ping_exe = _which("ping")
        if not ping_exe:
            raise PCAPCaptureError("`ping` tool not found on PATH")

        sysname = platform.system().lower()
        is_windows = "windows" in sysname

        argv: List[str] = [ping_exe]

        # Build command according to mode/OS
        if is_windows:
            # Windows flags:
            # -n <count>, -w <timeout_ms>, -t (continuous)
            if background and count <= 0:
                # Continuous mode to ensure overlap with capture window
                argv.append("-t")
            else:
                argv.extend(["-n", str(max(1, int(count)))])
            argv.extend(["-w", str(int(float(timeout_s) * 1000))])
            argv.append(str(target))
        else:
            # Unix-like flags:
            # -c <count>, -W <timeout_s>, -i <interval_s>
            if background and count <= 0:
                # Continuous mode: omit -c
                argv.extend(["-W", str(int(float(timeout_s)))])
                if interval_s is not None:
                    argv.extend(["-i", str(float(interval_s))])
                argv.append(str(target))
            else:
                argv.extend(["-c", str(max(1, int(count)))])
                argv.extend(["-W", str(int(float(timeout_s)))])
                if interval_s is not None:
                    argv.extend(["-i", str(float(interval_s))])
                argv.append(str(target))

        if logger:
            logger.log("")
            logger.log("=" * 80)
            logger.log(f"[PING] {'BACKGROUND' if background else 'FOREGROUND'} MODE")
            logger.log("=" * 80)
            logger.log(f"  Target:   {target}")
            logger.log(f"  Count:    {count}")
            logger.log(f"  Timeout:  {timeout_s}s")
            if interval_s:
                logger.log(f"  Interval: {interval_s}s")
            if duration_s:
                logger.log(f"  Duration: {duration_s}s")
            logger.log("")
            logger.log(f"  Command: {_quote_list(argv)}")
            logger.log("")

        if background:
            # Start process and optionally schedule a watchdog to stop it
            try:
                proc = subprocess.Popen(
                    argv,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            except Exception as e:
                raise PCAPCaptureError(f"Failed to start ping: {e}") from e

            if logger:
                logger.log(f"✓ Background ping started (PID: {proc.pid})")
                logger.log("=" * 80)
                logger.log("")

            # If user wants a bounded background run and it's continuous (count<=0), stop after duration_s
            if duration_s is not None and duration_s > 0:
                import threading

                def _stop_later():
                    try:
                        time.sleep(float(duration_s))
                        if proc.poll() is None:
                            if is_windows:
                                proc.terminate()
                            else:
                                try:
                                    proc.send_signal(signal.SIGINT)
                                except Exception:
                                    proc.terminate()
                            try:
                                proc.wait(timeout=5.0)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                        try:
                            stdout, stderr = proc.communicate(timeout=1.0)
                        except Exception:
                            stdout, stderr = ("", "")
                        if logger:
                            logger.log(f"[PING] BG stopped pid={proc.pid} rc={proc.returncode}")
                            if stdout:
                                logger.log("[PING STDOUT]\n" + stdout.rstrip())
                            if stderr:
                                logger.log("[PING STDERR]\n" + stderr.rstrip())
                    except Exception as e:
                        if logger:
                            logger.log(f"[PING] BG watchdog error: {e}")

                threading.Thread(target=_stop_later, daemon=True).start()

            return True

        # Foreground: run and wait
        try:
            proc = subprocess.run(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        except Exception as e:
            raise PCAPCaptureError(f"Failed to execute ping: {e}") from e

        if logger:
            if proc.returncode == 0:
                logger.log(f"✓ Ping successful (RC: {proc.returncode})")
            else:
                logger.log(f"✗ Ping failed (RC: {proc.returncode})")
            logger.log("-" * 80)
            if proc.stdout:
                logger.log("")
                logger.log("  Output:")
                for line in proc.stdout.rstrip().splitlines():
                    if line.strip():
                        logger.log(f"    {line}")
            if proc.stderr:
                logger.log("")
                logger.log("  Errors:")
                for line in proc.stderr.rstrip().splitlines():
                    if line.strip():
                        logger.log(f"    {line}")
            logger.log("")
            logger.log("=" * 80)
            logger.log("")

        if proc.returncode != 0:
            raise PCAPCaptureError(f"ping failed (rc={proc.returncode}) for target {target!r}")

        return True

    return TestAction(name, execute, negative_test=negative_test)