#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UTFW PCAP Analyze Module
========================

Read and validate PCAPs using tshark with UTFW-style logging and TestActions.

Capabilities
------------
1) Filter content using tshark display filters, then validate over remaining frames:
   - Frame size (eq/min/max)
   - Time deltas between frames (eq/min/max; global or per-pair)
   - Payload patterns (hex/ASCII contains, or regex on hex/ASCII)
   - Source/Destination MAC
   - VLAN parameters (ID, priority; stacked VLANs supported)

2) Read-and-expect mode:
   - Return frames with timestamps as a list for further processing
   - Validate vs. an expected frame list:
     - Number of frames
     - Payload patterns
     - Ordered or unordered presence by criteria (src/dst/len/payload)

Notes
-----
- Requires 'tshark' in PATH. Fails with a clear error if not available.
- Timestamps are parsed from tshark and converted to nanoseconds.
- Payload is taken from 'data.data' field (hex). If tshark cannot expose the
  bytes, payload may be empty; FCS presence depends on capture/decoder.

Author: DvidMakesThings
"""

from __future__ import annotations

import os
import shutil
import subprocess
import re
from typing import Any, Dict, List, Optional, Tuple

from ...core.core import TestAction
from ...core.logger import get_active_logger


class PCAPAnalyzeError(Exception):
    """Raised when PCAP analysis fails (tshark invocation, parsing, or checks)."""


# ======================== Subprocess logging ========================


def _log_subprocess(cmd, rc, out, err, tag: str = "TSHARK") -> None:
    logger = get_active_logger()
    if logger:
        logger.subprocess(cmd, rc, out, err, tag=tag)


def _log(msg: str) -> None:
    logger = get_active_logger()
    if logger:
        logger.log(msg)


def _ensure_tshark():
    if shutil.which("tshark") is None:
        raise PCAPAnalyzeError("tshark is required but not found in PATH.")


# ======================== Helpers ========================


def _to_int(s: str, default: int = 0) -> int:
    try:
        return int(s)
    except Exception:
        try:
            return int(float(s))
        except Exception:
            return default


def _to_ns_from_epoch(epoch_str: str) -> int:
    # tshark 'frame.time_epoch' returns float seconds as string; convert to ns
    try:
        v = float(epoch_str)
    except Exception:
        return 0
    return int(v * 1_000_000_000)


def _decode_hex(s: str) -> bytes:
    s = (s or "").strip()
    if not s:
        return b""
    s = s.replace(":", "").replace(" ", "").replace("-", "")
    try:
        return bytes.fromhex(s)
    except Exception:
        return b""


def _match_payload_patterns(
    payload: bytes, patterns: List[Dict[str, Any]]
) -> Optional[str]:
    """
    Return None if all patterns satisfied, else error string.
    Pattern entries support:
      - {"contains_hex": "AA11BB"}             # substring in hex bytes
      - {"contains_ascii": "literal"}          # substring in ascii-decoded (errors='replace')
      - {"regex_hex": r"..."}                  # regex over hex string (lowercase, no separators)
      - {"regex_ascii": r"..."}                # regex over decoded ascii
    """
    hex_str = payload.hex()
    asc = payload.decode("utf-8", errors="replace")

    for p in patterns or []:
        if "contains_hex" in p:
            needle = re.sub(r"[^0-9A-Fa-f]", "", str(p["contains_hex"]))
            if needle.lower() not in hex_str.lower():
                return f"payload missing hex substring '{needle}'"
        if "contains_ascii" in p:
            needle = str(p["contains_ascii"])
            if needle not in asc:
                return f"payload missing ascii substring '{needle}'"
        if "regex_hex" in p:
            rgx = re.compile(str(p["regex_hex"]))
            if not rgx.search(hex_str):
                return f"payload hex regex not matched: {p['regex_hex']}"
        if "regex_ascii" in p:
            rgx = re.compile(str(p["regex_ascii"]))
            if not rgx.search(asc):
                return f"payload ascii regex not matched: {p['regex_ascii']}"
    return None


# ======================== tshark readers ========================

_TS_FIELDS_BASE = [
    "frame.number",
    "frame.len",
    "frame.time_epoch",
    "eth.src",
    "eth.dst",
    "vlan.id",
    "vlan.priority",
    "data.data",
]


def _run_tshark_fields(
    pcap_path: str,
    display_filter: Optional[str],
    extra_fields: Optional[List[str]] = None,
) -> Tuple[str, str, int]:
    _ensure_tshark()
    fields = list(_TS_FIELDS_BASE)
    if extra_fields:
        fields.extend(extra_fields)
    cmd = [
        "tshark",
        "-r",
        pcap_path,
        "-T",
        "fields",
        "-E",
        "header=n",
        "-E",
        "separator=\t",
        "-E",
        "occurrence=f",
    ]
    for f in fields:
        cmd += ["-e", f]
    if display_filter:
        cmd += ["-Y", display_filter]
    try:
        _log(f"[PCAP-CHECK] tshark fields start filter={display_filter or 'none'}")
        r = subprocess.run(cmd, capture_output=True, text=True)
        _log_subprocess(cmd, r.returncode, r.stdout, r.stderr, tag="TSHARK-FIELDS")
        return r.stdout, r.stderr, r.returncode
    except Exception as e:
        _log_subprocess(cmd, 1, "", str(e), tag="TSHARK-FIELDS")
        raise PCAPAnalyzeError(f"tshark execution failed: {e}")


def _run_tshark_vlan_stack(
    pcap_path: str, display_filter: Optional[str]
) -> List[List[Tuple[int, Optional[int]]]]:
    """
    Extract stacked VLANs per frame as list of (vid, pcp) tuples.
    Uses -e vlan.id and -e vlan.priority with -E occurrence=a to emit all occurrences comma-separated.
    """
    _ensure_tshark()
    cmd = [
        "tshark",
        "-r",
        pcap_path,
        "-T",
        "fields",
        "-E",
        "header=n",
        "-E",
        "separator=\t",
        "-E",
        "occurrence=a",
        "-e",
        "vlan.id",
        "-e",
        "vlan.priority",
    ]
    if display_filter:
        cmd += ["-Y", display_filter]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        _log_subprocess(cmd, r.returncode, r.stdout, r.stderr, tag="TSHARK-VLAN")
        if r.returncode != 0:
            return []
        lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
        stacks: List[List[Tuple[int, Optional[int]]]] = []
        for ln in lines:
            parts = ln.split("\t")
            vids = (parts[0].split(",")) if len(parts) > 0 and parts[0] else []
            pcps = (parts[1].split(",")) if len(parts) > 1 and parts[1] else []
            row: List[Tuple[int, Optional[int]]] = []
            for i, vid in enumerate(vids):
                try:
                    v = int(vid)
                except Exception:
                    continue
                pcp = None
                if i < len(pcps):
                    try:
                        pcp = int(pcps[i])
                    except Exception:
                        pcp = None
                row.append((v, pcp))
            stacks.append(row)
        return stacks
    except Exception as e:
        _log_subprocess(cmd, 1, "", str(e), tag="TSHARK-VLAN")
        return []


def _parse_field_lines(stdout: str) -> List[Dict[str, Any]]:
    frames: List[Dict[str, Any]] = []
    for ln in stdout.splitlines():
        if not ln.strip():
            continue
        cols = ln.split("\t")
        num = cols[0] if len(cols) > 0 else ""
        flen = cols[1] if len(cols) > 1 else ""
        tsec = cols[2] if len(cols) > 2 else ""
        src = cols[3] if len(cols) > 3 else ""
        dst = cols[4] if len(cols) > 4 else ""
        vlan_id = cols[5] if len(cols) > 5 else ""
        vlan_pcp = cols[6] if len(cols) > 6 else ""
        datahex = cols[7] if len(cols) > 7 else ""

        frames.append(
            {
                "frame_number": _to_int(num, 0),
                "frame_len": _to_int(flen, 0),
                "timestamp_ns": _to_ns_from_epoch(tsec),
                "eth_src": src or "",
                "eth_dst": dst or "",
                "vlan_id": _to_int(vlan_id, 0) if vlan_id else None,
                "vlan_pcp": _to_int(vlan_pcp, 0) if vlan_pcp else None,
                "payload": _decode_hex(datahex),
            }
        )
    return frames


# ======================== Public TestAction Factories ========================


def read_PCAPFrames(
    name: str, pcap_path: str, display_filter: Optional[str] = None
) -> TestAction:
    """
    Read frames (optionally filtered) and return a list of dicts:
      {
        frame_number:int, frame_len:int, timestamp_ns:int,
        eth_src:str, eth_dst:str, vlan_id:Optional[int], vlan_pcp:Optional[int],
        payload:bytes, vlan_stack: List[(vid:int, pcp:Optional[int])]
      }
    """

    def execute():
        if not os.path.exists(pcap_path):
            raise PCAPAnalyzeError(f"PCAP not found: {pcap_path}")
        _log(f"[PCAP-READ] path={pcap_path} filter={display_filter or 'none'}")
        out, err, rc = _run_tshark_fields(pcap_path, display_filter)
        if rc != 0:
            raise PCAPAnalyzeError(f"tshark failed: {err.strip() or 'unknown error'}")
        frames = _parse_field_lines(out)
        vlan_stack = _run_tshark_vlan_stack(pcap_path, display_filter)
        if vlan_stack and len(vlan_stack) == len(frames):
            for i, st in enumerate(vlan_stack):
                frames[i]["vlan_stack"] = st
        else:
            for f in frames:
                f["vlan_stack"] = (
                    []
                    if f.get("vlan_id") is None
                    else [(f["vlan_id"], f.get("vlan_pcp"))]
                )
        _log(f"[PCAP-READ] parsed={len(frames)}")
        # Dump concise summary
        for f in frames[:20]:
            _log(
                f"[PCAP-READ] fnum={f['frame_number']} len={f['frame_len']} "
                f"t={f['timestamp_ns']}ns src={f['eth_src']} dst={f['eth_dst']} "
                f"vlan={f.get('vlan_stack')}"
            )
        return frames

    return TestAction(name, execute)


def analyze_PCAP(
    name: str,
    pcap_path: str,
    display_filter: str,
    *,
    expect_count: Optional[int] = None,
    frame_size: Optional[Dict[str, int]] = None,
    time_delta_ns: Optional[Dict[str, Any]] = None,
    payload_patterns: Optional[List[Dict[str, Any]]] = None,
    expect_mac: Optional[Dict[str, str]] = None,
    vlan_expect: Optional[Dict[str, Any]] = None,
) -> TestAction:
    """
    Step 1: filter via tshark display filter.
    Step 2: validate over remaining frames.

    Examples:
      frame_size={"eq": 128}
      frame_size={"min": 64, "max": 1518}
      time_delta_ns={"min": 100_000, "max": 300_000}
      time_delta_ns={"eq": 200_000}
      time_delta_ns={"per_pair": [100_000, 200_000, 120_000]}  # len == (n-1)
      payload_patterns=[{"contains_hex":"DEADBEEF"}, {"regex_ascii": r"OK|PASS"}]
      expect_mac={"src":"aa:bb:cc:dd:ee:02", "dst":"aa:bb:cc:dd:ee:01"}
      vlan_expect={"id": 100} or {"id":[100,200], "priority": 3}
    """

    def execute():
        _log(f"[PCAP-CHECK] analyze start path={pcap_path} filter={display_filter}")
        frames = read_PCAPFrames("read tmp", pcap_path, display_filter).execute_func()

        if expect_count is not None and len(frames) != int(expect_count):
            raise PCAPAnalyzeError(
                f"Expected {expect_count} frames after filter, got {len(frames)}"
            )
        _log(f"[PCAP-CHECK] filtered={len(frames)} (expect_count={expect_count})")

        # Frame size checks
        if frame_size:
            eq = frame_size.get("eq")
            mn = frame_size.get("min")
            mx = frame_size.get("max")
            _log(f"[PCAP-CHECK] size check eq={eq} min={mn} max={mx}")
            for f in frames:
                L = f["frame_len"]
                if eq is not None and L != int(eq):
                    raise PCAPAnalyzeError(
                        f"Frame {f['frame_number']} length {L} != {eq}"
                    )
                if mn is not None and L < int(mn):
                    raise PCAPAnalyzeError(
                        f"Frame {f['frame_number']} length {L} < min {mn}"
                    )
                if mx is not None and L > int(mx):
                    raise PCAPAnalyzeError(
                        f"Frame {f['frame_number']} length {L} > max {mx}"
                    )

        # Time delta checks (between consecutive frames)
        if time_delta_ns and len(frames) >= 2:
            deltas = [
                frames[i]["timestamp_ns"] - frames[i - 1]["timestamp_ns"]
                for i in range(1, len(frames))
            ]
            _log(f"[PCAP-CHECK] Δt array ns={deltas}")
            if "eq" in time_delta_ns:
                want = int(time_delta_ns["eq"])
                for i, d in enumerate(deltas, start=2):
                    if d != want:
                        raise PCAPAnalyzeError(f"Δt[{i-1}->{i}] {d}ns != {want}ns")
            elif "min" in time_delta_ns or "max" in time_delta_ns:
                mn = time_delta_ns.get("min")
                mx = time_delta_ns.get("max")
                for i, d in enumerate(deltas, start=2):
                    if mn is not None and d < int(mn):
                        raise PCAPAnalyzeError(f"Δt[{i-1}->{i}] {d}ns < min {mn}ns")
                    if mx is not None and d > int(mx):
                        raise PCAPAnalyzeError(f"Δt[{i-1}->{i}] {d}ns > max {mx}ns")
            elif "per_pair" in time_delta_ns:
                arr = list(map(int, time_delta_ns["per_pair"] or []))
                if len(arr) != len(deltas):
                    raise PCAPAnalyzeError(
                        f"time_delta_ns.per_pair length {len(arr)} != expected {len(deltas)}"
                    )
                for i, (d, want) in enumerate(zip(deltas, arr), start=2):
                    if d != want:
                        raise PCAPAnalyzeError(f"Δt[{i-1}->{i}] {d}ns != {want}ns")

        # Payload patterns (apply to all frames)
        if payload_patterns:
            _log(f"[PCAP-CHECK] payload patterns={payload_patterns}")
            for f in frames:
                msg = _match_payload_patterns(f["payload"], payload_patterns)
                if msg:
                    raise PCAPAnalyzeError(f"Frame {f['frame_number']} {msg}")

        # MAC checks
        if expect_mac:
            src = expect_mac.get("src")
            dst = expect_mac.get("dst")
            _log(f"[PCAP-CHECK] expect_mac src={src} dst={dst}")
            for f in frames:
                if src and f["eth_src"].lower() != src.lower():
                    raise PCAPAnalyzeError(
                        f"Frame {f['frame_number']} eth.src {f['eth_src']} != {src}"
                    )
                if dst and f["eth_dst"].lower() != dst.lower():
                    raise PCAPAnalyzeError(
                        f"Frame {f['frame_number']} eth.dst {f['eth_dst']} != {dst}"
                    )

        # VLAN checks
        if vlan_expect:
            want_ids = vlan_expect.get("id")
            want_pcp = vlan_expect.get("priority")
            _log(f"[PCAP-CHECK] vlan_expect ids={want_ids} pcp={want_pcp}")
            for f in frames:
                stack = f.get("vlan_stack") or (
                    []
                    if f.get("vlan_id") is None
                    else [(f["vlan_id"], f.get("vlan_pcp"))]
                )
                ids = [vid for (vid, _pcp) in stack]
                if want_ids is not None:
                    if isinstance(want_ids, list):
                        missing = [v for v in want_ids if v not in ids]
                        if missing:
                            raise PCAPAnalyzeError(
                                f"Frame {f['frame_number']} missing VLAN IDs {missing}, got {ids}"
                            )
                    else:
                        if int(want_ids) not in ids:
                            raise PCAPAnalyzeError(
                                f"Frame {f['frame_number']} VLAN id {want_ids} not in {ids}"
                            )
                if want_pcp is not None:
                    pcps = [p for (_, p) in stack if p is not None]
                    if not pcps or int(want_pcp) not in pcps:
                        raise PCAPAnalyzeError(
                            f"Frame {f['frame_number']} VLAN priority {want_pcp} not in {pcps or '[]'}"
                        )

        _log(
            f"[PCAP-CHECK] Filter '{display_filter}' passed on {len(frames)} frame(s) in {pcap_path}"
        )
        return True

    return TestAction(name, execute)


def pcap_checkFrames(
    name: str,
    pcap_path: str,
    *,
    display_filter: Optional[str] = None,
    expect_count: Optional[int] = None,
    expected_frames: Optional[List[Dict[str, Any]]] = None,
    ordered: bool = True,
) -> TestAction:
    """
    Read frames (optionally filtered), return the parsed list, and validate against
    an expected frame list.

    expected_frames: list of criteria dicts, each can include:
      {
        "len": 128,                           # exact frame length
        "src": "aa:bb:cc:dd:ee:02",
        "dst": "aa:bb:cc:dd:ee:01",
        "payload_patterns": [ ... ]           # same pattern keys as above
      }

    If ordered=True, we match expected[i] against frames[i] (prefix match allowed if fewer expected).
    If ordered=False, we match each expected against any remaining frame (greedy).
    """

    def _frame_satisfies(f: Dict[str, Any], exp: Dict[str, Any]) -> Optional[str]:
        if "len" in exp and f["frame_len"] != int(exp["len"]):
            return f"len {f['frame_len']} != {exp['len']}"
        if "src" in exp and f["eth_src"].lower() != str(exp["src"]).lower():
            return f"eth.src {f['eth_src']} != {exp['src']}"
        if "dst" in exp and f["eth_dst"].lower() != str(exp["dst"]).lower():
            return f"eth.dst {f['eth_dst']} != {exp['dst']}"
        if "payload_patterns" in exp:
            msg = _match_payload_patterns(f["payload"], exp["payload_patterns"])
            if msg:
                return msg
        return None

    def execute():
        _log(
            f"[PCAP-EXPECT] checkFrames start path={pcap_path} filter={display_filter or 'none'} "
            f"ordered={ordered} expect_count={expect_count} n_expected={len(expected_frames or [])}"
        )

        frames = read_PCAPFrames("read tmp", pcap_path, display_filter).execute_func()

        if expect_count is not None and len(frames) != int(expect_count):
            raise PCAPAnalyzeError(f"Expected {expect_count} frames, got {len(frames)}")

        if not expected_frames:
            _log(
                f"[PCAP-EXPECT] no expected_frames specified, returning parsed list (n={len(frames)})"
            )
            return frames

        if ordered:
            if len(expected_frames) > len(frames):
                raise PCAPAnalyzeError(
                    f"Expected {len(expected_frames)} frames (ordered), got {len(frames)}"
                )
            for idx, exp in enumerate(expected_frames):
                msg = _frame_satisfies(frames[idx], exp)
                if msg:
                    raise PCAPAnalyzeError(
                        f"Frame[{idx+1}] does not satisfy expectation: {msg}"
                    )
                _log(f"[PCAP-EXPECT] ordered match idx={idx+1} ok {exp}")
        else:
            remaining = list(frames)
            for ei, exp in enumerate(expected_frames, start=1):
                hit_index = None
                fail_reasons: List[str] = []
                for i, f in enumerate(remaining):
                    msg = _frame_satisfies(f, exp)
                    if msg is None:
                        hit_index = i
                        break
                    fail_reasons.append(f"cand#{i+1}:{msg}")
                if hit_index is None:
                    raise PCAPAnalyzeError(
                        f"Expected frame #{ei} not found among {len(remaining)} candidates; "
                        f"reasons: {', '.join(fail_reasons[:4])}"
                    )
                del remaining[hit_index]
                _log(f"[PCAP-EXPECT] unordered match exp#{ei} ok {exp}")

        _log(
            f"[PCAP-EXPECT] validated {len(expected_frames)} expected frame(s) "
            f"({'ordered' if ordered else 'unordered'}) in {pcap_path}"
        )
        return frames

    return TestAction(name, execute)
