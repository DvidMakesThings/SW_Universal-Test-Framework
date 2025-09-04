#!/usr/bin/env python3

"""
EEPROM Dump Helper

- Opens a serial port, sends "DUMP_EEPROM", captures the device's dump text
  between EE_DUMP_START and EE_DUMP_END, and saves only the dump content
  (without echo lines) as <prefix>_raw.log.
- Parses the hex matrix into bytes and saves a translated ASCII view
  (printables shown, non-printables as '.') as <prefix>_ascii.log.
- Supports verbose mode for detailed progress logs.

Example:
    python eeprom_dump_helper.py -p COM10 -b 115200 -o energis_dump -v

Notes:
    * Requires pyserial:  pip install pyserial
    * Lines expected in the EE_DUMP block look like:
        0x0000 53 4E 2D ...
    * If you already have the dump text in a file, you can skip serial I/O:
        python eeprom_dump_helper.py --from-file raw_input.log -o parsed

Author: DvidMakesThings
"""

import argparse
import re
import sys
import time
from pathlib import Path
from typing import List, Tuple, Optional

# ----------------------------- Serial I/O ------------------------------------


def read_dump_from_serial(
    port: str,
    baud: int = 115200,
    cmd: str = "DUMP_EEPROM",
    timeout: float = 5.0,
    read_grace: float = 1.0,
    verbose: bool = False,
) -> str:
    """
    Open serial, send command, read until EE_DUMP_END shows, then return all captured text.
    """
    try:
        import serial
    except ImportError:
        print("ERROR: pyserial not installed. Install with: pip install pyserial", file=sys.stderr)
        sys.exit(2)

    if verbose:
        print(f"[INFO] Opening serial port {port} at {baud} baud...")

    ser = serial.Serial(port=port, baudrate=baud, timeout=timeout)
    try:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        if verbose:
            print(f"[INFO] Sending command: {cmd}")
        ser.write((cmd + "\r\n").encode("utf-8"))
        ser.flush()

        buf_chunks: List[bytes] = []
        got_start = False
        got_end = False
        t_end_seen: Optional[float] = None
        deadline = time.time() + max(timeout * 6.0, 6.0)

        while time.time() < deadline:
            chunk = ser.read(4096)
            if chunk:
                buf_chunks.append(chunk)
                text_so_far = b"".join(buf_chunks).decode("utf-8", errors="replace")

                if not got_start and "EE_DUMP_START" in text_so_far:
                    got_start = True
                    if verbose:
                        print("[INFO] Found EE_DUMP_START marker.")

                if got_start and "EE_DUMP_END" in text_so_far and not got_end:
                    got_end = True
                    t_end_seen = time.time()
                    if verbose:
                        print("[INFO] Found EE_DUMP_END marker.")

            if got_end and t_end_seen is not None:
                if time.time() - t_end_seen >= read_grace:
                    break

        if verbose:
            print("[INFO] Finished reading dump from serial.")

        return b"".join(buf_chunks).decode("utf-8", errors="replace")
    finally:
        ser.close()
        if verbose:
            print("[INFO] Serial port closed.")


# ----------------------------- Parsing ---------------------------------------


_HEX_LINE_RE = re.compile(
    r"""
    ^\s*0x([0-9A-Fa-f]{4})
    (?:\s+[0-9A-Fa-f]{2}){1,16}\s*$
    """,
    re.VERBOSE,
)


def extract_dump_block(raw_text: str, verbose: bool = False) -> List[str]:
    """
    Return only the lines strictly between EE_DUMP_START and EE_DUMP_END.
    """
    lines = raw_text.splitlines()
    block: List[str] = []
    in_block = False
    for ln in lines:
        if "EE_DUMP_START" in ln:
            in_block = True
            if verbose:
                print("[DEBUG] Entered EE_DUMP block.")
            continue
        if "EE_DUMP_END" in ln:
            if verbose:
                print("[DEBUG] Exited EE_DUMP block.")
            break
        if in_block:
            block.append(ln)
    if verbose:
        print(f"[INFO] Extracted {len(block)} dump lines.")
    return block


def parse_hex_rows(block_lines: List[str], verbose: bool = False) -> Tuple[bytearray, List[int]]:
    """
    Parse the hex rows into a linear bytearray.
    """
    out = bytearray()
    row_addrs: List[int] = []
    for ln in block_lines:
        m = _HEX_LINE_RE.match(ln)
        if not m:
            continue
        parts = ln.split()
        row_addrs.append(int(parts[0], 16))
        for val in parts[1:]:
            out.append(int(val, 16))
    if verbose:
        print(f"[INFO] Parsed {len(out)} bytes from {len(row_addrs)} rows.")
    return out, row_addrs


def bytes_to_printable_ascii(b: bytes) -> str:
    out_chars: List[str] = []
    for x in b:
        if 0x20 <= x <= 0x7E:
            out_chars.append(chr(x))
        else:
            out_chars.append(".")
    return "".join(out_chars)


def build_ascii_table(b: bytes, base_addrs: List[int]) -> str:
    lines: List[str] = []
    total = len(b)
    addr = 0
    for row_idx in range(0, (total + 15) // 16):
        start = row_idx * 16
        end = min(start + 16, total)
        chunk = b[start:end]
        ascii_chunk = bytes_to_printable_ascii(chunk)
        row_addr = base_addrs[row_idx] if row_idx < len(base_addrs) else addr
        addr = row_addr + 16
        hex_cells = " ".join(f"{x:02X}" for x in chunk)
        if len(chunk) < 16:
            hex_cells = hex_cells + " " * ((16 - len(chunk)) * 3)
        lines.append(f"0x{row_addr:04X}  {hex_cells}   |{ascii_chunk}|")
    return "\n".join(lines)


# ----------------------------- File Ops --------------------------------------


def save_text(path: Path, content: str, verbose: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if verbose:
        print(f"[INFO] Saved file: {path}")


# ----------------------------- CLI / Main ------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description="EEPROM dump helper: capture and translate to ASCII.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("-p", "--port", help="Serial port (e.g., COM7, /dev/ttyACM0).")
    src.add_argument("--from-file", help="Read raw terminal text from an existing file instead of serial.")

    ap.add_argument("-b", "--baud", type=int, default=115200, help="Baudrate (default: 115200).")
    ap.add_argument("-c", "--command", default="DUMP_EEPROM", help="Command to trigger dump (default: DUMP_EEPROM).")
    ap.add_argument("-t", "--timeout", type=float, default=5.0, help="Per-read timeout seconds (default: 5).")
    ap.add_argument("-g", "--grace", type=float, default=1.0, help="Extra seconds to read after EE_DUMP_END (default: 1).")
    ap.add_argument("-o", "--output-prefix", default="eeprom_dump", help="Output file prefix (default: eeprom_dump).")
    ap.add_argument("--outdir", default=".", help="Output directory (default: current).")
    ap.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging.")

    args = ap.parse_args()

    outdir = Path(args.outdir)
    raw_path = outdir / f"{args.output_prefix}_raw.log"
    ascii_path = outdir / f"{args.output_prefix}_ascii.log"

    if args.from_file:
        if args.verbose:
            print(f"[INFO] Reading raw text from file: {args.from_file}")
        raw_text = Path(args.from_file).read_text(encoding="utf-8", errors="replace")
    else:
        raw_text = read_dump_from_serial(
            port=args.port,
            baud=args.baud,
            cmd=args.command,
            timeout=args.timeout,
            read_grace=args.grace,
            verbose=args.verbose,
        )

    block = extract_dump_block(raw_text, verbose=args.verbose)
    save_text(raw_path, "\n".join(block), verbose=args.verbose)

    eebytes, row_addrs = parse_hex_rows(block, verbose=args.verbose)
    ascii_table = build_ascii_table(eebytes, row_addrs)
    concatenated = bytes_to_printable_ascii(eebytes)

    translated = (
        "### EEPROM ASCII View\n"
        + ascii_table
    )
    save_text(ascii_path, translated, verbose=args.verbose)

    print(f"Saved EEPROM hex dump to:    {raw_path}")
    print(f"Saved translated ASCII to:   {ascii_path}")
    print(f"Parsed {len(eebytes)} bytes.")


if __name__ == "__main__":
    main()
