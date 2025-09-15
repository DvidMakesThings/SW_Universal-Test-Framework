#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UTFW PCAP Generation Module
===========================

Create libpcap (nanosecond) files with Ethernet frames that include FCS.
Supports:
- ns timestamps (libpcap nanosecond variant)
- FCS generation (CRC-32) with optional XOR mask corruption
- Payload per frame: user-provided or randomly generated
- Inter-frame timing: either Δt (first-to-first) or IFG bytes converted via link speed
- Total frame size control (including FCS) with automatic padding
- IPv4:
    * Manual flags DF/MF/frag offset
    * Automatic fragmentation by payload size (correct fragments)

All operations integrate with UTFW's logger. Each TestAction is named and logged.

Author: DvidMakesThings
"""

from __future__ import annotations

import os
import struct
import zlib
import ipaddress
from typing import Optional, Union, List, Tuple, Any

from ...core.core import TestAction
from ...core.logger import get_active_logger

# ======================== Exceptions ========================

class PCAPGenError(Exception):
    """Raised when PCAP generation fails (bad params, IO, etc.)."""

# ======================== Constants ========================

# libpcap "nanosecond" magic (little-endian)
# https://www.tcpdump.org/linktypes.html
_PCAP_NS_MAGIC = 0xA1B23C4D
_PCAP_VERSION_MAJOR = 2
_PCAP_VERSION_MINOR = 4
_PCAP_THISZONE = 0
_PCAP_SIGFIGS = 0
_PCAP_SNAPLEN = 65535
_PCAP_NETWORK_ETHERNET = 1  # LINKTYPE_ETHERNET

# Ethernet overheads
ETH_HDR_LEN = 14
ETH_FCS_LEN = 4

# ======================== Speed Parser ========================

def _parse_link_speed_bps(speed: Optional[Union[int, float, str]]) -> Optional[float]:
    """
    Accepts:
      - number (int/float) -> used as-is
      - str: '10M', '100M', '1G', '2.5G', '5G', '10G', etc.
    Returns float(bps) or None.
    """
    if speed is None:
        return None
    if isinstance(speed, (int, float)):
        return float(speed)
    s = str(speed).strip().lower().replace(" ", "")
    if s.endswith("g"):
        return float(s[:-1]) * 1_000_000_000.0
    if s.endswith("m"):
        return float(s[:-1]) * 1_000_000.0
    if s.endswith("k"):
        return float(s[:-1]) * 1_000.0
    # raw int string
    try:
        return float(int(s))
    except Exception:
        return None

# ======================== Helpers ========================

def _mac_from_any(x: Union[str, bytes]) -> bytes:
    if isinstance(x, bytes) and len(x) == 6:
        return x
    s = str(x).strip()
    s = s.replace("-", ":").lower()
    parts = s.split(":")
    if len(parts) != 6:
        raise PCAPGenError(f"Invalid MAC: {x!r}")
    try:
        return bytes(int(p, 16) & 0xFF for p in parts)
    except Exception:
        raise PCAPGenError(f"Invalid MAC hex: {x!r}")

def _ip4_bytes(x: Union[str, bytes]) -> bytes:
    if isinstance(x, bytes) and len(x) == 4:
        return x
    try:
        return ipaddress.IPv4Address(str(x)).packed
    except Exception:
        raise PCAPGenError(f"Invalid IPv4 address: {x!r}")

def _checksum16(data: bytes) -> int:
    # standard IP header checksum
    if len(data) % 2 == 1:
        data += b"\x00"
    s = sum(int.from_bytes(data[i:i+2], "big") for i in range(0, len(data), 2))
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return (~s) & 0xFFFF

def _crc32_le(data: bytes) -> int:
    # Ethernet FCS is CRC-32 (poly 0xEDB88320) and transmitted little-endian
    return zlib.crc32(data) & 0xFFFFFFFF

def _ensure_dir(path: str) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        pass

def _pcap_write_global_header_if_missing(path: str, linktype: int = _PCAP_NETWORK_ETHERNET) -> None:
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return
    _ensure_dir(path)
    with open(path, "wb") as f:
        f.write(struct.pack("<IHHIIII",
                            _PCAP_NS_MAGIC,
                            _PCAP_VERSION_MAJOR,
                            _PCAP_VERSION_MINOR,
                            _PCAP_THISZONE,
                            _PCAP_SIGFIGS,
                            _PCAP_SNAPLEN,
                            linktype))
    logger = get_active_logger()
    if logger:
        logger.log(f"[PCAPGEN] Wrote ns-global-header to {path} (linktype={linktype})")

def _pcap_append_record_ns(path: str, ts_ns: int, frame: bytes) -> None:
    ts_sec = int(ts_ns // 1_000_000_000)
    ts_nano = int(ts_ns % 1_000_000_000)
    caplen = len(frame)
    with open(path, "ab") as f:
        f.write(struct.pack("<IIII", ts_sec, ts_nano, caplen, caplen))
        f.write(frame)
    logger = get_active_logger()
    if logger:
        logger.log(f"[PCAPGEN] wrote rec ts={ts_ns}ns (sec={ts_sec} ns={ts_nano}) len={caplen}")

def _pcap_read_last_record(path: str) -> Tuple[Optional[int], Optional[int]]:
    """Return (last_ts_ns, last_frame_len) or (None, None) if no packets."""
    if not os.path.exists(path) or os.path.getsize(path) <= 24:
        return None, None
    try:
        with open(path, "rb") as f:
            data = f.read()
        # Iterate records from offset 24
        off = 24
        last_ts = None
        last_len = None
        n = len(data)
        while off + 16 <= n:
            ts_sec, ts_ns, caplen, origlen = struct.unpack_from("<IIII", data, off)
            off += 16
            if off + caplen > n:
                break
            off += caplen
            last_ts = ts_sec * 1_000_000_000 + ts_ns
            last_len = caplen
        return last_ts, last_len
    except Exception:
        return None, None

def _frame_wire_bits(frame_len_bytes: int) -> int:
    return int(frame_len_bytes * 8)

def _ns_from_ifg_bytes(prev_wire_bits: int, ifg_bytes: int, link_bps: float) -> int:
    if link_bps <= 0:
        raise PCAPGenError("link_speed_bps must be > 0")
    return int(((prev_wire_bits + (ifg_bytes * 8)) / link_bps) * 1e9)

def build_ipv4_packet(*, src: Union[str, bytes], dst: Union[str, bytes],
                      payload: bytes, protocol: int,
                      identification: Optional[int],
                      flags_df: bool, flags_mf: bool,
                      frag_offset_units8: int,
                      ttl: int, tos: int) -> bytes:
    ip_src = _ip4_bytes(src)
    ip_dst = _ip4_bytes(dst)
    ver_ihl = (4 << 4) | 5  # no options
    total_len = 20 + len(payload)
    ident = int(identification) & 0xFFFF if identification is not None else 0
    df = 0x2 if flags_df else 0
    mf = 0x1 if flags_mf else 0
    flags_off = ((df | mf) << 13) | (int(frag_offset_units8) & 0x1FFF)
    ihdr = struct.pack("!BBHHHBBH4s4s",
                       ver_ihl, int(tos) & 0xFF,
                       total_len & 0xFFFF,
                       ident,
                       flags_off & 0xFFFF,
                       int(ttl) & 0xFF,
                       int(protocol) & 0xFF,
                       0,  # checksum placeholder
                       ip_src, ip_dst)
    cksum = _checksum16(ihdr)
    ihdr = ihdr[:10] + struct.pack("!H", cksum) + ihdr[12:]
    return ihdr + payload

def fragment_ipv4_payload_auto(*, src: Union[str, bytes], dst: Union[str, bytes],
                               full_payload: bytes, protocol: int,
                               frag_payload_size: int,
                               identification: Optional[int],
                               ttl: int, tos: int) -> List[bytes]:
    """
    Split payload into IPv4 fragments with data sizes multiple of 8 bytes except last.
    Returns list of complete IPv4 packets (headers + fragment payload).
    """
    if frag_payload_size <= 0:
        raise PCAPGenError("ip_auto_fragment_payload_size must be > 0")
    ident = int(identification) & 0xFFFF if identification is not None else 0
    packets: List[bytes] = []
    offset = 0
    total = len(full_payload)
    while offset < total:
        remaining = total - offset
        frag_len = frag_payload_size if remaining > frag_payload_size else remaining
        # For non-last fragment, ensure multiple of 8 bytes
        more = (offset + frag_len) < total
        if more and (frag_len % 8) != 0:
            frag_len = (frag_len // 8) * 8
            if frag_len == 0:
                frag_len = min(8, remaining)
        frag_data = full_payload[offset: offset + frag_len]
        frag_off_units8 = offset // 8
        pkt = build_ipv4_packet(
            src=src, dst=dst, payload=frag_data, protocol=protocol,
            identification=ident, flags_df=False, flags_mf=more,
            frag_offset_units8=frag_off_units8, ttl=ttl, tos=tos
        )
        packets.append(pkt)
        offset += frag_len
    return packets

def build_ethernet_frame(*,
                         dst_mac: Union[str, bytes],
                         src_mac: Union[str, bytes],
                         ethertype: Union[int, str],
                         payload: bytes,
                         total_size_including_fcs: Optional[int],
                         fcs_xormask: int) -> bytes:
    """Return Ethernet frame bytes including FCS. Enforces total_size_including_fcs when provided."""
    d = _mac_from_any(dst_mac)
    s = _mac_from_any(src_mac)
    if isinstance(ethertype, str):
        # Accept common names or hex strings like "0x88b6"
        name = ethertype.strip().lower()
        ETHERTYPE_MAP = {
            "ipv4": 0x0800, "arp": 0x0806, "wakeonlan": 0x0842, "vlan": 0x8100,
            "ipv6": 0x86DD, "mpls_uc": 0x8847, "mpls_mc": 0x8848, "pppoe_discovery": 0x8863,
            "pppoe_session": 0x8864, "lldp": 0x88B5, "homeplug": 0x887B, "profinet": 0x8892
        }
        if name.startswith("0x"):
            et = int(name, 16)
        else:
            et = ETHERTYPE_MAP.get(name)
            if et is None:
                raise PCAPGenError(f"Unknown ethertype name {ethertype!r}")
    else:
        et = int(ethertype) & 0xFFFF
    hdr = d + s + struct.pack("!H", et)
    body = payload or b""
    frame_wo_fcs = hdr + body

    # Enforce total size including FCS, if requested
    if total_size_including_fcs is not None:
        want = int(total_size_including_fcs)
        min_len = len(frame_wo_fcs) + ETH_FCS_LEN
        if want < min_len:
            raise PCAPGenError("total_size_including_fcs smaller than header+payload+FCS")
        pad_needed = (want - ETH_FCS_LEN) - len(frame_wo_fcs)
        if pad_needed > 0:
            frame_wo_fcs += b"\x00" * pad_needed

    # FCS
    fcs = _crc32_le(frame_wo_fcs) ^ (int(fcs_xormask) & 0xFFFFFFFF)
    fcs_bytes = struct.pack("<I", fcs)  # little-endian on the wire (LSB first)
    return frame_wo_fcs + fcs_bytes

def _pcap_append_frames_ns(path: str, frames: List[bytes], timestamps_ns: List[int], linktype: int = _PCAP_NETWORK_ETHERNET) -> None:
    if len(frames) != len(timestamps_ns):
        raise PCAPGenError("frames/timestamps length mismatch")
    _pcap_write_global_header_if_missing(path, linktype)
    for ts, fr in zip(timestamps_ns, frames):
        _pcap_append_record_ns(path, int(ts), fr)

# ======================== New Per-Frame Factory ========================

def pcap_create(name: str,
                output_path: str,
                *,
                # Ethernet
                dst_mac: Optional[Union[str, bytes]] = None,
                src_mac: Optional[Union[str, bytes]] = None,
                ethertype: Optional[Union[int, str]] = 0x0800,
                payload: Optional[bytes] = None,
                payload_len: Optional[int] = None,
                total_size_including_fcs: Optional[int] = None,
                fcs_xormask: int = 0,
                # Timing
                delta_ns: Optional[int] = None,
                ifg_bytes: Optional[int] = None,
                start_time_ns: int = 0,
                link_speed_bps: Optional[float] = None,
                # IPv4 (optional)
                ipv4: bool = False,
                ip_src: Optional[Union[str, bytes]] = None,
                ip_dst: Optional[Union[str, bytes]] = None,
                ip_protocol: int = 17,
                ip_payload: Optional[bytes] = None,
                ip_payload_len: Optional[int] = None,
                ip_identification: Optional[int] = None,
                ip_df: bool = False,
                ip_mf: bool = False,
                ip_frag_offset_units8: int = 0,
                ip_ttl: int = 64,
                ip_tos: int = 0,
                ip_auto_fragment_payload_size: Optional[int] = None) -> TestAction:
    """
    Append one "frame" specification to a PCAP file (created on first call).

    - If the file doesn't exist (or empty), a global header is written and the
      first packet's timestamp uses start_time_ns (or 0 if omitted).
    - If the file already has packets, the new timestamp is computed from the last
      packet using delta_ns or ifg_bytes (converted with link speed), or
      back-to-back by serialization time if link_speed_bps is provided.

    IPv4:
    - If ipv4=True and ip_auto_fragment_payload_size is set, multiple packets are
      appended (correct fragments).
    - Manual DF/MF/frag offset can be set for a single IPv4 packet.

    Returns:
        TestAction that writes packet(s) and returns output_path.
    """
    def execute():
        logger = get_active_logger()

        # Determine previous timestamp and length (for timing)
        last_ts_ns, last_len = _pcap_read_last_record(output_path)
        current_ts = int(start_time_ns if last_ts_ns is None else last_ts_ns)
        prev_len = int(last_len or 0)

        link_bps = _parse_link_speed_bps(link_speed_bps)

        if logger:
            logger.log(f"[PCAPGEN] pcap_create -> target={output_path} last_ts_ns={last_ts_ns} last_len={last_len} "
                       f"params delta_ns={delta_ns} ifg_bytes={ifg_bytes} link_bps={link_bps}")

        frames_to_write: List[bytes] = []
        deltas_ns: List[Optional[int]] = []

        if ipv4:
            if not ip_src or not ip_dst:
                raise PCAPGenError("ipv4=True requires ip_src and ip_dst")

            # Prepare IPv4 payload
            if ip_payload is None:
                if ip_payload_len is not None:
                    ip_payload_final = os.urandom(int(ip_payload_len))
                else:
                    ip_payload_final = b""
            else:
                ip_payload_final = ip_payload

            if logger:
                logger.log(f"[PCAPGEN] IPv4 build: src={ip_src} dst={ip_dst} proto={ip_protocol} "
                           f"payload_len={len(ip_payload_final)} ident={ip_identification} "
                           f"df={int(ip_df)} mf={int(ip_mf)} off8={int(ip_frag_offset_units8)}")

            if ip_auto_fragment_payload_size and ip_auto_fragment_payload_size > 0:
                frags = fragment_ipv4_payload_auto(
                    src=ip_src, dst=ip_dst, full_payload=ip_payload_final,
                    protocol=ip_protocol, frag_payload_size=int(ip_auto_fragment_payload_size),
                    identification=ip_identification, ttl=ip_ttl, tos=ip_tos
                )
                if logger:
                    logger.log(f"[PCAPGEN] IPv4 auto-fragment -> {len(frags)} packets "
                               f"(frag_payload_size={ip_auto_fragment_payload_size})")
                for idx, pkt in enumerate(frags, start=1):
                    eth = build_ethernet_frame(
                        dst_mac=(dst_mac or "ff:ff:ff:ff:ff:ff"),
                        src_mac=(src_mac or "00:11:22:33:44:55"),
                        ethertype=0x0800,
                        payload=pkt,
                        total_size_including_fcs=total_size_including_fcs,
                        fcs_xormask=fcs_xormask
                    )
                    frames_to_write.append(eth)
                    deltas_ns.append(delta_ns)
                    if logger:
                        logger.log(f"[PCAPGEN]  frag#{idx} eth_len={len(eth)}")
            else:
                pkt = build_ipv4_packet(
                    src=ip_src, dst=ip_dst, payload=ip_payload_final,
                    protocol=ip_protocol, identification=ip_identification,
                    flags_df=ip_df, flags_mf=ip_mf,
                    frag_offset_units8=int(ip_frag_offset_units8 or 0),
                    ttl=ip_ttl, tos=ip_tos
                )
                eth = build_ethernet_frame(
                    dst_mac=(dst_mac or "ff:ff:ff:ff:ff:ff"),
                    src_mac=(src_mac or "00:11:22:33:44:55"),
                    ethertype=0x0800,
                    payload=pkt,
                    total_size_including_fcs=total_size_including_fcs,
                    fcs_xormask=fcs_xormask
                )
                frames_to_write.append(eth)
                deltas_ns.append(delta_ns)
                if logger:
                    logger.log(f"[PCAPGEN] IPv4 single eth_len={len(eth)}")
        else:
            # Raw Ethernet
            if payload is None:
                if payload_len is not None:
                    payload_final = os.urandom(int(payload_len))
                else:
                    payload_final = b""
            else:
                payload_final = payload

            eth = build_ethernet_frame(
                dst_mac=(dst_mac or "ff:ff:ff:ff:ff:ff"),
                src_mac=(src_mac or "00:11:22:33:44:55"),
                ethertype=(ethertype if ethertype is not None else 0x0800),
                payload=payload_final,
                total_size_including_fcs=total_size_including_fcs,
                fcs_xormask=fcs_xormask
            )
            frames_to_write.append(eth)
            deltas_ns.append(delta_ns)
            if logger:
                logger.log(f"[PCAPGEN] Ether frame len={len(eth)} et={ethertype} "
                           f"payload_len={len(payload_final)} fcs_xor=0x{int(fcs_xormask):08X}")

        # Compute timestamps and append
        timestamps: List[int] = []
        for i, (frame_bytes, d_ns) in enumerate(zip(frames_to_write, deltas_ns), start=1):
            if last_ts_ns is None and i == 1:
                timestamps.append(current_ts)
                if logger:
                    logger.log(f"[PCAPGEN] first packet ts={current_ts} ns")
            else:
                if d_ns is not None:
                    current_ts = (last_ts_ns if (i == 1 and last_ts_ns is not None) else current_ts) + int(d_ns)
                    if logger:
                        logger.log(f"[PCAPGEN] Δt=explicit {int(d_ns)} ns -> ts={current_ts}")
                elif ifg_bytes is not None:
                    if not link_bps:
                        raise PCAPGenError("link_speed_bps required when using ifg_bytes")
                    prev_bits = _frame_wire_bits(prev_len)
                    add_ns = _ns_from_ifg_bytes(prev_bits, int(ifg_bytes), float(link_bps))
                    current_ts = (last_ts_ns if (i == 1 and last_ts_ns is not None) else current_ts) + add_ns
                    if logger:
                        logger.log(f"[PCAPGEN] Δt=serialize({prev_len}B)+IFG({ifg_bytes}B) @ {link_bps}bps "
                                   f"= {add_ns} ns -> ts={current_ts}")
                else:
                    prev_bits = _frame_wire_bits(prev_len)
                    if link_bps:
                        ser_ns = int((prev_bits / float(link_bps)) * 1e9)
                        current_ts = (last_ts_ns if (i == 1 and last_ts_ns is not None) else current_ts) + ser_ns
                        if logger:
                            logger.log(f"[PCAPGEN] Δt=serialize-only {ser_ns} ns -> ts={current_ts}")
                    else:
                        if logger:
                            logger.log("[PCAPGEN] Δt=0 ns (same timestamp)")
                        current_ts = (last_ts_ns if (i == 1 and last_ts_ns is not None) else current_ts)
                timestamps.append(current_ts)

            # Per-frame detail
            prev_len = len(frame_bytes)
            last_ts_ns = current_ts

            if logger:
                body_wo_fcs = frame_bytes[:-ETH_FCS_LEN]
                fcs_raw = struct.unpack("<I", frame_bytes[-ETH_FCS_LEN:])[0]
                crc_calc = _crc32_le(body_wo_fcs)
                logger.log(f"[PCAPGEN] frame#{i} ts={timestamps[-1]} ns len={len(frame_bytes)} "
                           f"crc=0x{crc_calc:08X} xor=0x{int(fcs_xormask):08X} fcs=0x{fcs_raw:08X}")

        _pcap_append_frames_ns(output_path, frames_to_write, timestamps, linktype=_PCAP_NETWORK_ETHERNET)

        if logger:
            logger.log(f"[PCAPGEN] appended {len(frames_to_write)} frame(s) -> {output_path} "
                       f"last_ts_ns={timestamps[-1] if timestamps else 'N/A'}")

        return output_path

    return TestAction(name, execute)

# ======================== Spec-List Factory ========================

def pcap_from_spec_action(name: str,
                          output_path: str,
                          frames_spec: List[dict],
                          *,
                          start_time_ns: int = 0,
                          link_speed_bps: Optional[float] = None) -> TestAction:
    """
    Append a list of frames to the PCAP (created on first call).

    Each spec dict can include the same keys used by pcap_create:
      - Ethernet: dst_mac, src_mac, ethertype, payload, payload_len,
                  total_size_including_fcs, fcs_xormask
      - Timing:   delta_ns, ifg_bytes
      - IPv4:     ipv4, ip_src, ip_dst, ip_protocol, ip_payload, ip_payload_len,
                  ip_identification, ip_df, ip_mf, ip_frag_offset_units8,
                  ip_ttl, ip_tos, ip_auto_fragment_payload_size

    The first packet in the file uses start_time_ns when the file is empty.
    Subsequent timestamps are computed using per-spec delta_ns / ifg_bytes rules.
    """
    def execute():
        logger = get_active_logger()

        last_ts_ns, last_len = _pcap_read_last_record(output_path)
        current_ts = int(start_time_ns if last_ts_ns is None else last_ts_ns)
        prev_len = int(last_len or 0)
        default_bps = _parse_link_speed_bps(link_speed_bps)

        if logger:
            logger.log(f"[PCAPGEN] from-spec target={output_path} last_ts_ns={last_ts_ns} last_len={last_len} "
                       f"default link_bps={default_bps} specs={len(frames_spec)}")

        out_frames: List[bytes] = []
        out_ts: List[int] = []

        for idx, spec in enumerate(frames_spec, start=1):
            ipv4 = bool(spec.get("ipv4", False))
            if logger:
                logger.log(f"[PCAPGEN] spec#{idx} -> {spec}")

            frames_to_write: List[bytes] = []
            deltas_ns: List[Optional[int]] = []

            if ipv4:
                ip_src = spec.get("ip_src")
                ip_dst = spec.get("ip_dst")
                if not ip_src or not ip_dst:
                    raise PCAPGenError(f"spec[{idx}] ipv4=True requires ip_src/ip_dst")

                ip_payload = spec.get("ip_payload")
                ip_payload_len = spec.get("ip_payload_len")
                if ip_payload is None:
                    if ip_payload_len is not None:
                        ip_payload_final = os.urandom(int(ip_payload_len))
                    else:
                        ip_payload_final = b""
                else:
                    ip_payload_final = ip_payload

                ip_auto = spec.get("ip_auto_fragment_payload_size")
                ip_protocol = int(spec.get("ip_protocol", 17))
                ip_ident = spec.get("ip_identification")
                ip_df = bool(spec.get("ip_df", False))
                ip_mf = bool(spec.get("ip_mf", False))
                ip_off8 = int(spec.get("ip_frag_offset_units8", 0))
                ip_ttl = int(spec.get("ip_ttl", 64))
                ip_tos = int(spec.get("ip_tos", 0))

                if logger:
                    logger.log(f"[PCAPGEN] spec#{idx} IPv4 src={ip_src} dst={ip_dst} proto={ip_protocol} "
                               f"payload_len={len(ip_payload_final)} ident={ip_ident} df={int(ip_df)} "
                               f"mf={int(ip_mf)} off8={ip_off8} auto_frag={ip_auto}")

                if ip_auto and ip_auto > 0:
                    frags = fragment_ipv4_payload_auto(
                        src=ip_src, dst=ip_dst, full_payload=ip_payload_final,
                        protocol=ip_protocol, frag_payload_size=int(ip_auto),
                        identification=ip_ident, ttl=ip_ttl, tos=ip_tos
                    )
                    for fi, pkt in enumerate(frags, start=1):
                        eth = build_ethernet_frame(
                            dst_mac=(spec.get("dst_mac") or "ff:ff:ff:ff:ff:ff"),
                            src_mac=(spec.get("src_mac") or "00:11:22:33:44:55"),
                            ethertype=0x0800,
                            payload=pkt,
                            total_size_including_fcs=spec.get("total_size_including_fcs"),
                            fcs_xormask=int(spec.get("fcs_xormask", 0))
                        )
                        frames_to_write.append(eth)
                        deltas_ns.append(spec.get("delta_ns"))
                        if logger:
                            logger.log(f"[PCAPGEN] spec#{idx} auto-frag#{fi} len={len(eth)}")
                else:
                    pkt = build_ipv4_packet(
                        src=ip_src, dst=ip_dst, payload=ip_payload_final,
                        protocol=ip_protocol, identification=ip_ident,
                        flags_df=ip_df, flags_mf=ip_mf,
                        frag_offset_units8=ip_off8, ttl=ip_ttl, tos=ip_tos
                    )
                    eth = build_ethernet_frame(
                        dst_mac=(spec.get("dst_mac") or "ff:ff:ff:ff:ff:ff"),
                        src_mac=(spec.get("src_mac") or "00:11:22:33:44:55"),
                        ethertype=0x0800,
                        payload=pkt,
                        total_size_including_fcs=spec.get("total_size_including_fcs"),
                        fcs_xormask=int(spec.get("fcs_xormask", 0))
                    )
                    frames_to_write.append(eth)
                    deltas_ns.append(spec.get("delta_ns"))
                    if logger:
                        logger.log(f"[PCAPGEN] spec#{idx} IPv4 single len={len(eth)}")
            else:
                # Raw Ethernet
                payload = spec.get("payload")
                payload_len = spec.get("payload_len")
                if payload is None:
                    if payload_len is not None:
                        payload_final = os.urandom(int(payload_len))
                    else:
                        payload_final = b""
                else:
                    payload_final = payload

                ethertype = spec.get("ethertype", 0x0800)
                eth = build_ethernet_frame(
                    dst_mac=(spec.get("dst_mac") or "ff:ff:ff:ff:ff:ff"),
                    src_mac=(spec.get("src_mac") or "00:11:22:33:44:55"),
                    ethertype=ethertype,
                    payload=payload_final,
                    total_size_including_fcs=spec.get("total_size_including_fcs"),
                    fcs_xormask=int(spec.get("fcs_xormask", 0))
                )
                frames_to_write.append(eth)
                deltas_ns.append(spec.get("delta_ns"))
                if logger:
                    logger.log(f"[PCAPGEN] spec#{idx} Ether frame len={len(eth)} et={ethertype} "
                               f"payload_len={len(payload_final)} fcs_xor=0x{int(spec.get('fcs_xormask', 0)):08X}")

            # Timing for frames built by this spec (could be >1 due to auto-frag)
            this_ifg = spec.get("ifg_bytes")
            this_link = _parse_link_speed_bps(spec.get("link_speed_bps", link_speed_bps))

            for fi, (frame_bytes, d_ns) in enumerate(zip(frames_to_write, deltas_ns), start=1):
                if last_ts_ns is None and not out_ts:
                    # first packet overall
                    out_ts.append(current_ts)
                    if logger:
                        logger.log(f"[PCAPGEN] first packet ts={current_ts} ns")
                else:
                    if d_ns is not None:
                        current_ts = (last_ts_ns if (not out_ts and last_ts_ns is not None) else current_ts) + int(d_ns)
                        if logger:
                            logger.log(f"[PCAPGEN] Δt=explicit {int(d_ns)} ns -> ts={current_ts}")
                    elif this_ifg is not None:
                        use_bps = this_link or default_bps
                        if not use_bps:
                            raise PCAPGenError("link_speed_bps required when using ifg_bytes in spec")
                        prev_bits = _frame_wire_bits(prev_len)
                        add_ns = _ns_from_ifg_bytes(prev_bits, int(this_ifg), float(use_bps))
                        current_ts = (last_ts_ns if (not out_ts and last_ts_ns is not None) else current_ts) + add_ns
                        if logger:
                            logger.log(f"[PCAPGEN] Δt=serialize({prev_len}B)+IFG({this_ifg}B) @ {use_bps}bps "
                                       f"= {add_ns} ns -> ts={current_ts}")
                    else:
                        use_bps = this_link or default_bps
                        if use_bps:
                            ser_ns = int((_frame_wire_bits(prev_len) / float(use_bps)) * 1e9)
                            current_ts = (last_ts_ns if (not out_ts and last_ts_ns is not None) else current_ts) + ser_ns
                            if logger:
                                logger.log(f"[PCAPGEN] Δt=serialize-only {ser_ns} ns -> ts={current_ts}")
                        else:
                            if logger:
                                logger.log("[PCAPGEN] Δt=0 ns (same timestamp)")
                            current_ts = (last_ts_ns if (not out_ts and last_ts_ns is not None) else current_ts)

                    out_ts.append(current_ts)

                prev_len = len(frame_bytes)
                last_ts_ns = current_ts
                out_frames.append(frame_bytes)

                if logger:
                    body_wo_fcs = frame_bytes[:-ETH_FCS_LEN]
                    fcs_raw = struct.unpack("<I", frame_bytes[-ETH_FCS_LEN:])[0]
                    crc_calc = _crc32_le(body_wo_fcs)
                    logger.log(f"[PCAPGEN] spec#{idx} frame#{fi} ts={out_ts[-1]} ns len={len(frame_bytes)} "
                               f"crc=0x{crc_calc:08X} fcs=0x{fcs_raw:08X}")

        _pcap_append_frames_ns(output_path, out_frames, out_ts, linktype=_PCAP_NETWORK_ETHERNET)

        if logger:
            logger.log(f"[PCAPGEN] from-spec appended {len(out_frames)} frame(s) to {output_path} "
                       f"Last ts_ns={out_ts[-1] if out_ts else 'N/A'}")

        return output_path

    return TestAction(name, execute)
