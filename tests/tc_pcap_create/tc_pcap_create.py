#!/usr/bin/env python3
"""
ENERGIS PCAP Generation + Analysis (UTFW)
=========================================

Generates a single PCAP file that demonstrates:
- PCAP with nanosecond timestamps (libpcap nanosecond variant)
- Frames include Ethernet FCS (CRC-32) and optional XOR corruption mask
- Payload per frame: user-defined or randomly generated
- Inter-frame timing by explicit nanoseconds or IFG bytes (converted via link speed)
- Total frame size control (including FCS) with automatic padding
- IPv4 fragmentation:
  - Manual: directly set DF/MF/Identification/Fragment Offset
  - Automatic: split payload into correct fragments by a given fragment payload size

Then analyzes the PCAP with tshark-based checks (sizes, timing, payload patterns, MACs, VLAN).

Place under: <project>/TestCases/tc_network_pcapgen/tc_network_pcapgen_utfw.py
"""

import sys
import struct
from pathlib import Path

from UTFW.core import run_test_with_teardown
from UTFW.core import get_hwconfig
from UTFW.core import get_reports_dir
from UTFW.core import STE
from UTFW.modules.network import pcapgen as FrameGen
from UTFW.modules.network import pcap_analyze as analyzer


class tc_network_pcapgen_test:
    """UTFW test suite to generate and analyze a single PCAP showcasing all PCAPGen features."""

    def __init__(self):
        pass

    def setup(self):
        """Assemble and return ordered TestAction list."""
        hw = get_hwconfig()
        reports_dir = get_reports_dir()

        # Paths
        Path(reports_dir).mkdir(parents=True, exist_ok=True)
        output_pcap = str(Path(reports_dir) / hw.PCAP_FILENAME)

        # Minimal IPv4 UDP segment (checksum 0) -> header(8) + data
        def _udp_segment(
            src_port: int, dst_port: int, data_len: int, fill_byte: int = 0x22
        ) -> bytes:
            data = bytes([fill_byte]) * int(data_len)
            length = 8 + len(data)
            return (
                struct.pack(
                    "!HHHH",
                    int(src_port) & 0xFFFF,
                    int(dst_port) & 0xFFFF,
                    length & 0xFFFF,
                    0,
                )
                + data
            )

        return [
            # =========================
            # Step 1: Generate PCAP
            # =========================
            STE(
                FrameGen.pcap_create(
                    name="UDP128",
                    output_path=output_pcap,
                    ipv4=True,
                    ip_src=hw.UDP128_SRC_IP,
                    ip_dst=hw.UDP128_DST_IP,
                    ip_protocol=17,  # UDP
                    ip_payload=_udp_segment(
                        hw.UDP128_SRC_PORT, hw.UDP128_DST_PORT, 64, fill_byte=0x22
                    ),
                    total_size_including_fcs=128,
                ),
                FrameGen.pcap_create(
                    name="CorruptFCS200",
                    output_path=output_pcap,
                    dst_mac=hw.MAC_A,
                    src_mac=hw.MAC_B,
                    ethertype=hw.ETHERTYPE,
                    payload_len=60,  # random payload
                    total_size_including_fcs=200,
                    fcs_xormask=0xDEADBEEF,
                    delta_ns=200_000,  # 200 µs
                    link_speed_bps=hw.LINK_SPEED_BPS,
                ),
                FrameGen.pcap_create(
                    name="AA128",
                    output_path=output_pcap,
                    dst_mac=hw.MAC_A,
                    src_mac=hw.MAC_B,
                    ethertype=hw.ETHERTYPE,
                    payload=b"\xaa" * 100,
                    total_size_including_fcs=128,
                    delta_ns=250_000,
                    link_speed_bps=hw.LINK_SPEED_BPS,
                ),
                FrameGen.pcap_create(
                    name="IFG12B256",
                    output_path=output_pcap,
                    dst_mac=hw.MAC_A,
                    src_mac=hw.MAC_B,
                    ethertype=hw.ETHERTYPE,
                    payload_len=100,
                    total_size_including_fcs=256,
                    ifg_bytes=hw.IFG_BYTES,  # e.g. 12B IFG @1G = 96 ns (end-to-start)
                    link_speed_bps=hw.LINK_SPEED_BPS,
                ),
                FrameGen.pcap_create(
                    name="IPv4FragManual300",
                    output_path=output_pcap,
                    ipv4=True,
                    ip_src=hw.FRAG_MANUAL_SRC_IP,
                    ip_dst=hw.FRAG_MANUAL_DST_IP,
                    ip_protocol=253,  # experimental proto, avoid UDP decode
                    ip_payload_len=262,  # 14+20+262+4 = 300
                    ip_identification=0x1234,
                    ip_df=False,
                    ip_mf=True,
                    ip_frag_offset_units8=0,
                    total_size_including_fcs=300,
                    delta_ns=100_000,
                    link_speed_bps=hw.LINK_SPEED_BPS,
                ),
                FrameGen.pcap_create(
                    name="UDPFragAuto",
                    output_path=output_pcap,
                    ipv4=True,
                    ip_src=hw.FRAG_AUTO_SRC_IP,
                    ip_dst=hw.FRAG_AUTO_DST_IP,
                    ip_protocol=17,  # UDP
                    ip_payload=_udp_segment(
                        hw.FRAG_AUTO_SRC_PORT,
                        hw.FRAG_AUTO_DST_PORT,
                        1400,
                        fill_byte=0x33,
                    ),
                    ip_auto_fragment_payload_size=600,
                    ifg_bytes=hw.IFG_BYTES,
                    link_speed_bps=hw.LINK_SPEED_BPS,
                ),
                name="Generate PCAP",
            ),
            # =========================
            # Step 2: Analyze PCAP (basic)
            # =========================
            STE(
                analyzer.analyze_PCAP(
                    name="Count_UDP128",
                    pcap_path=output_pcap,
                    display_filter=f"ip.src=={hw.UDP128_SRC_IP} && ip.dst=={hw.UDP128_DST_IP} && ip.proto==17 && frame.len==128",
                    expect_count=1,
                    frame_size={"eq": 128},
                ),
                analyzer.analyze_PCAP(
                    name="AA128_Payload",
                    pcap_path=output_pcap,
                    display_filter=f"eth.type==0x{hw.ETHERTYPE:04x} && frame.len==128",
                    expect_count=1,
                    payload_patterns=[{"contains_hex": "AA" * 16}],
                ),
                analyzer.analyze_PCAP(
                    name="IFG12B_Timing",
                    pcap_path=output_pcap,
                    display_filter=f"eth.type==0x{hw.ETHERTYPE:04x} && (frame.len==128 || frame.len==256)",
                    expect_count=2,
                    # First-to-first = tx_time(prev 128B at 1G = 1024 ns) + IFG(12B) = 96 ns => 1120 ns total
                    time_delta_ns={"per_pair": [hw.IFG12B_PAIR_DELTA_NS]},
                    expect_mac={"src": hw.MAC_B, "dst": hw.MAC_A},
                ),
                name="Analyze – basic",
            ),
            # =========================
            # Step 3: Analyze fragments
            # =========================
            STE(
                analyzer.analyze_PCAP(
                    name="IPv4Frag_Manual",
                    pcap_path=output_pcap,
                    display_filter=f"ip.id==0x1234 && ip.flags.mf==1 && ip.src=={hw.FRAG_MANUAL_SRC_IP} && ip.dst=={hw.FRAG_MANUAL_DST_IP} && ip.proto==253",
                    expect_count=1,
                    frame_size={"eq": 300},
                ),
                analyzer.pcap_checkFrames(
                    name="UDPFrag_Lens",
                    pcap_path=output_pcap,
                    display_filter=f"ip.src=={hw.FRAG_AUTO_SRC_IP} && ip.dst=={hw.FRAG_AUTO_DST_IP} && ip.proto==17",
                    expect_count=len(hw.UDPFRAG_EXPECTED_LENS),
                    expected_frames=[{"len": L} for L in hw.UDPFRAG_EXPECTED_LENS],
                    ordered=False,
                ),
                name="Analyze – fragments",
            ),
            # Optional: dump all frames to the report/log
            analyzer.read_PCAPFrames(
                name="Read_AllFrames", pcap_path=output_pcap, display_filter=None
            ),
        ]


def main():
    """Create test instance and run"""
    test_instance = tc_network_pcapgen_test()
    return run_test_with_teardown(
        test_class_instance=test_instance,
        test_name="tc_pcap_create",
        reports_dir="report_tc_pcap_create",
    )


if __name__ == "__main__":
    sys.exit(main())
