#!/usr/bin/env python3
"""
tc_stress_switching.py - Rapid Channel Switching Stress Test
=============================================================
Tests relay durability and system stability under rapid switching
"""

import sys
from pathlib import Path

from UTFW.core import run_test_with_teardown
from UTFW.core import get_hwconfig
from UTFW.core import STE
from UTFW.modules import serial as UART
from UTFW.modules import snmp as SNMP


class tc_stress_switching_test:
    """Stress test for rapid outlet switching"""

    def __init__(self):
        pass

    def setup(self):
        hw = get_hwconfig()

        # Rapid switching: 10 cycles per channel
        rapid_switching_actions = []
        num_cycles = 10

        for cycle in range(1, num_cycles + 1):
            for channel in range(1, 9):
                rapid_switching_actions.extend([
                    UART.send_command_uart(
                        name=f"Cycle {cycle} - Toggle CH{channel} ON",
                        port=hw.SERIAL_PORT,
                        command=f"SET_CH {channel} ON",
                        baudrate=hw.BAUDRATE
                    ),
                    UART.send_command_uart(
                        name=f"Cycle {cycle} - Toggle CH{channel} OFF",
                        port=hw.SERIAL_PORT,
                        command=f"SET_CH {channel} OFF",
                        baudrate=hw.BAUDRATE
                    )
                ])

        # All channels simultaneous switching
        all_switching_actions = []
        for cycle in range(1, num_cycles + 1):
            all_switching_actions.extend([
                UART.send_command_uart(
                    name=f"Cycle {cycle} - All channels ON",
                    port=hw.SERIAL_PORT,
                    command="SET_CH ALL ON",
                    baudrate=hw.BAUDRATE
                ),
                UART.get_all_channels(
                    name=f"Cycle {cycle} - Verify all ON",
                    port=hw.SERIAL_PORT,
                    baudrate=hw.BAUDRATE,
                    expected=[True] * 8
                ),
                UART.send_command_uart(
                    name=f"Cycle {cycle} - All channels OFF",
                    port=hw.SERIAL_PORT,
                    command="SET_CH ALL OFF",
                    baudrate=hw.BAUDRATE
                ),
                UART.get_all_channels(
                    name=f"Cycle {cycle} - Verify all OFF",
                    port=hw.SERIAL_PORT,
                    baudrate=hw.BAUDRATE,
                    expected=[False] * 8
                )
            ])

        # Alternating pattern stress test
        alternating_actions = []
        for cycle in range(1, num_cycles + 1):
            # Odd channels ON, even OFF
            for channel in range(1, 9):
                state = "ON" if channel % 2 == 1 else "OFF"
                alternating_actions.append(
                    UART.send_command_uart(
                        name=f"Cycle {cycle} - Set CH{channel} {state}",
                        port=hw.SERIAL_PORT,
                        command=f"SET_CH {channel} {state}",
                        baudrate=hw.BAUDRATE
                    )
                )
            # Verify via SNMP
            alternating_actions.append(
                SNMP.verify_all_outlets(
                    name=f"Cycle {cycle} - Verify alternating pattern via SNMP",
                    ip=hw.BASELINE_IP,
                    outlet_base_oid=hw.OUTLET_BASE_OID,
                    expected_state=None,
                    community=hw.SNMP_COMMUNITY
                )
            )
            # Reverse: Even ON, odd OFF
            for channel in range(1, 9):
                state = "OFF" if channel % 2 == 1 else "ON"
                alternating_actions.append(
                    UART.send_command_uart(
                        name=f"Cycle {cycle} - Set CH{channel} {state}",
                        port=hw.SERIAL_PORT,
                        command=f"SET_CH {channel} {state}",
                        baudrate=hw.BAUDRATE
                    )
                )

        return [
            # Step 1: Rapid individual channel switching
            STE(
                *rapid_switching_actions,
                name=f"Rapid switching test - {num_cycles} cycles per channel"
            ),

            # Step 2: All channels simultaneous switching
            STE(
                *all_switching_actions,
                name=f"Simultaneous all-channel switching - {num_cycles} cycles"
            ),

            # Step 3: Alternating pattern stress
            STE(
                *alternating_actions,
                name=f"Alternating pattern stress test - {num_cycles} cycles"
            ),

            # Step 4: Final state verification
            STE(
                UART.send_command_uart(
                    name="Set all channels OFF after stress test",
                    port=hw.SERIAL_PORT,
                    command="SET_CH ALL OFF",
                    baudrate=hw.BAUDRATE
                ),
                UART.get_all_channels(
                    name="Verify all channels OFF",
                    port=hw.SERIAL_PORT,
                    baudrate=hw.BAUDRATE,
                    expected=[False] * 8
                ),
                SNMP.verify_all_outlets(
                    name="Final SNMP verification - all OFF",
                    ip=hw.BASELINE_IP,
                    outlet_base_oid=hw.OUTLET_BASE_OID,
                    expected_state=False,
                    community=hw.SNMP_COMMUNITY
                ),
                name="Final state verification after stress test"
            )
        ]


def main():
    """Create test instance and run"""
    test_instance = tc_stress_switching_test()
    return run_test_with_teardown(
        test_class_instance=test_instance,
        test_name="tc_stress_switching",
        reports_dir="report_tc_stress_switching"
    )


if __name__ == "__main__":
    sys.exit(main())
