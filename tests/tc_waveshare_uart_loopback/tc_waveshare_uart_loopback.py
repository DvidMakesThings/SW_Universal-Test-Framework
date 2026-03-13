#!/usr/bin/env python3
"""Waveshare CH347 dual-UART cross-loopback test.

Hardware setup:
- Configure adapter in dual-UART mode (mode 0).
- Connect UART0-TX → UART1-RX  and  UART1-TX → UART0-RX.
- hardware_config.py must define SERIAL_PORT_UART0 and SERIAL_PORT_UART1.
"""

import sys

from UTFW.core import run_test_with_teardown
from UTFW.core import get_hwconfig
from UTFW.modules.ext_tools import waveshare


class tc_waveshare_uart_loopback:
    """Cross-port loopback test across both CH347 UART channels."""

    def __init__(self):
        pass

    def setup(self):
        hw = get_hwconfig()

        payload = b"UTFW_LOOPBACK_01\x55\xAA"

        return [
            # 1. Verify both ports can be opened
            waveshare.uart.detect(
                name="Detect UART0",
                port=hw.SERIAL_PORT_UART0,
                baudrate=hw.BAUDRATE,
            ),
            waveshare.uart.detect(
                name="Detect UART1",
                port=hw.SERIAL_PORT_UART1,
                baudrate=hw.BAUDRATE,
            ),

            # 2. UART0-TX → UART1-RX
            waveshare.uart.cross_loopback(
                name="Loopback UART0 → UART1",
                tx_port=hw.SERIAL_PORT_UART0,
                rx_port=hw.SERIAL_PORT_UART1,
                payload=payload,
                baudrate=hw.BAUDRATE,
                timeout=2.0,
            ),

            # 3. UART1-TX → UART0-RX
            waveshare.uart.cross_loopback(
                name="Loopback UART1 → UART0",
                tx_port=hw.SERIAL_PORT_UART1,
                rx_port=hw.SERIAL_PORT_UART0,
                payload=payload,
                baudrate=hw.BAUDRATE,
                timeout=2.0,
            ),
        ]


def main():
    test_instance = tc_waveshare_uart_loopback()
    return run_test_with_teardown(
        test_class_instance=test_instance,
        test_name="tc_waveshare_uart_loopback",
        reports_dir="report_tc_waveshare_uart_loopback",
    )


if __name__ == "__main__":
    sys.exit(main())
