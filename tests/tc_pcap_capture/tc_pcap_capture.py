#!/usr/bin/env python3
"""
ENERGIS PCAP Capture Integration Test (UTFW)
============================================

This test uses only framework-provided actions to:
  1) Start an ICMP stimulus in the background (Ping).
  2) Capture live traffic to a PCAP file (CapturePcap).
  3) Validate that ICMP was captured (analyze_PCAP).

No custom helpers; no STE wrappers for single actions.
"""

import sys
from pathlib import Path

from UTFW.core import run_test_with_teardown, get_hwconfig
from UTFW.modules.network.pcap_capture import CapturePcap, Ping
from UTFW.modules.network import pcap_analyze as analyzer
from UTFW.core import get_reports_dir


class tc_pcap_capture_test:
    def __init__(self):
        pass

    def setup(self):
        hw = get_hwconfig()
        reports_dir = get_reports_dir()

        # Paths from hardware config
        Path(reports_dir).mkdir(parents=True, exist_ok=True)
        output_pcap = str(Path(reports_dir) / hw.PCAP_CAPTURE_FILENAME)

        # Use loopback by default; override in hw if desired
        iface = "lo"
        ping_target = "127.0.0.1"

        return [
            # Step 1: start ping stimulus in the background so it overlaps with capture
            Ping(
                name="Ping 127.0.0.1",
                target=ping_target,
                background=True,
                count=0,          # continuous
                duration_s=6.0,   # ≥ capture duration
                timeout_s=1.0,
                interval_s=0.2
                ),

            # Step 2: capture for a window inside the ping duration
            CapturePcap(
                name="Capture PCAP",
                output_path=output_pcap,
                interface=iface,
                bpf=f"icmp and host {ping_target}",
                duration_s=5,
                packet_count=None,
                snaplen=256,
                promiscuous=False,
                file_format="pcap",
                require_tool=None,
            ),

            # Step 3: verify ICMP was captured
            analyzer.analyze_PCAP(
                name="Check_ICMP_Captured",
                pcap_path=output_pcap,
                display_filter=f"icmp && ip.addr=={ping_target}",
                expect_count_min=1,
                frame_size=None
            ),
        ]


def main():
    test_instance = tc_pcap_capture_test()
    return run_test_with_teardown(
        test_class_instance=test_instance,
        test_name="tc_pcap_capture",
        reports_dir="report_tc_pcap_capture",
    )


if __name__ == "__main__":
    sys.exit(main())
