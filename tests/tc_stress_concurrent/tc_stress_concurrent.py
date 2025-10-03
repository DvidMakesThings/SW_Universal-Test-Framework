#!/usr/bin/env python3
"""
tc_stress_concurrent.py - Concurrent Operations Stress Test
============================================================
Tests system stability under simultaneous SNMP, Serial, and HTTP operations
"""

import sys
from pathlib import Path

from UTFW.core import run_test_with_teardown
from UTFW.core import get_hwconfig
from UTFW.core import STE
from UTFW.core import PSE
from UTFW.core import startFirstWith
from UTFW.modules import serial as UART
from UTFW.modules import snmp as SNMP
from UTFW.modules import ethernet as ETH


class tc_stress_concurrent_test:
    """Concurrent operations stress test"""

    def __init__(self):
        pass

    def setup(self):
        hw = get_hwconfig()

        base_url = f"http://{hw.BASELINE_IP}:{hw.HTTP_PORT}"
        dumps_dir = "http_dumps"

        # Concurrent test 1: Serial + SNMP simultaneously
        concurrent_serial_snmp = []
        for channel in range(1, 9):
            concurrent_serial_snmp.append(
                PSE(
                    UART.send_command_uart(
                        name=f"Serial: Set CH{channel} ON",
                        port=hw.SERIAL_PORT,
                        command=f"SET_CH {channel} ON",
                        baudrate=hw.BAUDRATE
                    ),
                    SNMP.get_outlet(
                        name=f"SNMP: Read CH{channel} state",
                        ip=hw.BASELINE_IP,
                        channel=channel,
                        expected_state=None,
                        outlet_base_oid=hw.OUTLET_BASE_OID,
                        community=hw.SNMP_COMMUNITY
                    ),
                    name=f"Concurrent Serial+SNMP for CH{channel}"
                )
            )

        # Concurrent test 2: HTTP + SNMP + Serial simultaneously
        concurrent_all_protocols = []
        for channel in range(1, 5):
            concurrent_all_protocols.append(
                PSE(
                    ETH.http_post_action(
                        name=f"HTTP: Set CH{channel} ON",
                        base_url=base_url,
                        path=hw.CONTROL_PATH,
                        data={f"outlet{channel}": "on"},
                        timeout=hw.HTTP_TIMEOUT,
                        accept_status=(200, 302),
                        dump_subdir=dumps_dir
                    ),
                    SNMP.get_outlet(
                        name=f"SNMP: Verify CH{channel}",
                        ip=hw.BASELINE_IP,
                        channel=channel,
                        expected_state=None,
                        outlet_base_oid=hw.OUTLET_BASE_OID,
                        community=hw.SNMP_COMMUNITY
                    ),
                    UART.send_command_uart(
                        name=f"Serial: Read CH{channel}",
                        port=hw.SERIAL_PORT,
                        command=f"GET_CH {channel}",
                        baudrate=hw.BAUDRATE
                    ),
                    name=f"Concurrent HTTP+SNMP+Serial for CH{channel}"
                )
            )

        # Concurrent test 3: Multiple simultaneous reads
        concurrent_reads = PSE(
            UART.send_command_uart(
                name="Serial: Read SYSINFO",
                port=hw.SERIAL_PORT,
                command=hw.SYSINFO_CMD,
                baudrate=hw.BAUDRATE
            ),
            UART.send_command_uart(
                name="Serial: Read NETINFO",
                port=hw.SERIAL_PORT,
                command=hw.NETINFO_CMD,
                baudrate=hw.BAUDRATE
            ),
            SNMP.snmp_get(
                name="SNMP: Read sysDescr",
                ip=hw.BASELINE_IP,
                oid=hw.SYS_DESCR,
                community=hw.SNMP_COMMUNITY
            ),
            SNMP.snmp_get(
                name="SNMP: Read sysName",
                ip=hw.BASELINE_IP,
                oid=hw.SYS_NAME,
                community=hw.SNMP_COMMUNITY
            ),
            ETH.http_get_action(
                name="HTTP: GET root page",
                base_url=base_url,
                path="/",
                timeout=hw.HTTP_TIMEOUT,
                accept_status=(200, 304),
                require_nonempty=True,
                dump_subdir=dumps_dir
            ),
            name="Concurrent read operations across all protocols"
        )

        # Rapid fire operations
        rapid_operations = []
        for i in range(1, 11):
            rapid_operations.append(
                PSE(
                    SNMP.get_outlet(
                        name=f"Rapid SNMP read {i}",
                        ip=hw.BASELINE_IP,
                        channel=1,
                        expected_state=None,
                        outlet_base_oid=hw.OUTLET_BASE_OID,
                        community=hw.SNMP_COMMUNITY
                    ),
                    UART.send_command_uart(
                        name=f"Rapid Serial GET_CH 1 - {i}",
                        port=hw.SERIAL_PORT,
                        command="GET_CH 1",
                        baudrate=hw.BAUDRATE
                    ),
                    name=f"Rapid fire operation {i}"
                )
            )

        return [
            # Step 1: Baseline verification
            STE(
                ETH.ping_action(
                    name="Ping device",
                    ip=hw.BASELINE_IP,
                    count=1,
                    timeout_per_pkt=1
                ),
                UART.send_command_uart(
                    name="Verify Serial communication",
                    port=hw.SERIAL_PORT,
                    command=hw.HELP_CMD,
                    baudrate=hw.BAUDRATE
                ),
                SNMP.snmp_get(
                    name="Verify SNMP communication",
                    ip=hw.BASELINE_IP,
                    oid=hw.SYS_DESCR,
                    community=hw.SNMP_COMMUNITY
                ),
                name="Baseline connectivity verification"
            ),

            # Step 2: Concurrent Serial + SNMP operations
            STE(
                *concurrent_serial_snmp,
                name="Concurrent Serial and SNMP operations"
            ),

            # Step 3: Concurrent HTTP + SNMP + Serial operations
            STE(
                *concurrent_all_protocols,
                name="Concurrent operations across all protocols"
            ),

            # Step 4: Concurrent reads
            concurrent_reads,

            # Step 5: Rapid fire stress test
            STE(
                *rapid_operations,
                name="Rapid fire concurrent operations (10 cycles)"
            ),

            # Step 6: Recovery verification
            STE(
                UART.send_command_uart(
                    name="Verify system responsive after stress",
                    port=hw.SERIAL_PORT,
                    command=hw.SYSINFO_CMD,
                    baudrate=hw.BAUDRATE
                ),
                UART.validate_tokens(
                    name="Verify SYSINFO response intact",
                    response="",
                    tokens=["Firmware", "Core Voltage"]
                ),
                UART.get_all_channels(
                    name="Verify all channels readable",
                    port=hw.SERIAL_PORT,
                    baudrate=hw.BAUDRATE,
                    expected=None
                ),
                SNMP.verify_all_outlets(
                    name="Verify SNMP still functional",
                    ip=hw.BASELINE_IP,
                    outlet_base_oid=hw.OUTLET_BASE_OID,
                    expected_state=None,
                    community=hw.SNMP_COMMUNITY
                ),
                ETH.http_get_action(
                    name="Verify HTTP still functional",
                    base_url=base_url,
                    path="/",
                    timeout=hw.HTTP_TIMEOUT,
                    accept_status=(200, 304),
                    require_nonempty=True,
                    dump_subdir=dumps_dir
                ),
                name="Recovery and functionality verification"
            ),

            # Step 7: Final cleanup
            STE(
                UART.send_command_uart(
                    name="Turn all channels OFF",
                    port=hw.SERIAL_PORT,
                    command="SET_CH ALL OFF",
                    baudrate=hw.BAUDRATE
                ),
                UART.get_all_channels(
                    name="Verify all OFF",
                    port=hw.SERIAL_PORT,
                    baudrate=hw.BAUDRATE,
                    expected=[False] * 8
                ),
                name="Final cleanup - all channels OFF"
            )
        ]


def main():
    """Create test instance and run"""
    test_instance = tc_stress_concurrent_test()
    return run_test_with_teardown(
        test_class_instance=test_instance,
        test_name="tc_stress_concurrent",
        reports_dir="report_tc_stress_concurrent"
    )


if __name__ == "__main__":
    sys.exit(main())
