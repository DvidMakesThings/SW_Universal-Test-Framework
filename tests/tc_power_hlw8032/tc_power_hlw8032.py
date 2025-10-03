#!/usr/bin/env python3
"""
tc_power_hlw8032.py - Power Monitoring Test using HLW8032
==========================================================
Tests power monitoring functionality via READ_HLW8032 command
"""

import sys
from pathlib import Path

from UTFW.core import run_test_with_teardown
from UTFW.core import get_hwconfig
from UTFW.core import STE
from UTFW.modules import serial as UART


class tc_power_hlw8032_test:
    """Power monitoring test for HLW8032 chip"""

    def __init__(self):
        pass

    def setup(self):
        hw = get_hwconfig()

        # Power monitoring test actions
        power_actions = []

        # Test each channel's power monitoring
        for channel in range(1, 9):
            power_actions.extend([
                # Turn channel ON first
                UART.send_command_uart(
                    name=f"Turn ON Channel {channel}",
                    port=hw.SERIAL_PORT,
                    command=f"SET_CH {channel} ON",
                    baudrate=hw.BAUDRATE
                ),
                # Read power data
                UART.send_command_uart(
                    name=f"Read power data for Channel {channel}",
                    port=hw.SERIAL_PORT,
                    command=f"READ_HLW8032 {channel}",
                    baudrate=hw.BAUDRATE
                ),
                UART.validate_tokens(
                    name=f"Validate power response for CH{channel}",
                    response="",
                    tokens=["Voltage", "Current", "Power"]
                ),
                # Turn channel OFF
                UART.send_command_uart(
                    name=f"Turn OFF Channel {channel}",
                    port=hw.SERIAL_PORT,
                    command=f"SET_CH {channel} OFF",
                    baudrate=hw.BAUDRATE
                )
            ])

        # Test reading all channels
        read_all_actions = []
        for channel in range(1, 9):
            read_all_actions.append(
                UART.send_command_uart(
                    name=f"Read power data for Channel {channel}",
                    port=hw.SERIAL_PORT,
                    command=f"READ_HLW8032 {channel}",
                    baudrate=hw.BAUDRATE
                )
            )

        return [
            # Step 1: Test individual channel power monitoring
            STE(
                *power_actions,
                name="Test power monitoring per channel with ON/OFF cycles"
            ),

            # Step 2: Read all channels continuously
            STE(
                *read_all_actions,
                name="Read power data from all channels"
            ),

            # Step 3: Test bulk READ_HLW8032 command (no channel specified)
            STE(
                UART.send_command_uart(
                    name="Read all power data at once",
                    port=hw.SERIAL_PORT,
                    command="READ_HLW8032",
                    baudrate=hw.BAUDRATE
                ),
                UART.validate_tokens(
                    name="Validate bulk power response",
                    response="",
                    tokens=["Voltage", "Current", "Power"]
                ),
                name="Test bulk power monitoring command"
            )
        ]


def main():
    """Create test instance and run"""
    test_instance = tc_power_hlw8032_test()
    return run_test_with_teardown(
        test_class_instance=test_instance,
        test_name="tc_power_hlw8032",
        reports_dir="report_tc_power_hlw8032"
    )


if __name__ == "__main__":
    sys.exit(main())
