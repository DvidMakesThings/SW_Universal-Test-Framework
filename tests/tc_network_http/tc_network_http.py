#!/usr/bin/env python3
"""
tc_network_http.py - HTTP Web Interface Test
=============================================
Tests web interface functionality for outlet control and settings
"""

import sys
from pathlib import Path

from UTFW.core import run_test_with_teardown
from UTFW.core import get_hwconfig
from UTFW.core import STE
from UTFW.modules import ethernet as ETH
from UTFW.modules import snmp as SNMP
from UTFW.modules import serial as UART


class tc_network_http_test:
    """HTTP web interface test"""

    def __init__(self):
        pass

    def setup(self):
        hw = get_hwconfig()

        base_url = f"http://{hw.BASELINE_IP}:{hw.HTTP_PORT}"
        dumps_dir = "http_dumps"

        # Test control page functionality
        control_actions = []
        for channel in range(1, 9):
            control_actions.extend([
                # Turn ON via web interface
                ETH.http_post_action(
                    name=f"POST /control - Turn ON CH{channel}",
                    base_url=base_url,
                    path=hw.CONTROL_PATH,
                    data={f"outlet{channel}": "on"},
                    timeout=hw.HTTP_TIMEOUT,
                    accept_status=(200, 302),
                    dump_subdir=dumps_dir
                ),
                # Verify via SNMP
                SNMP.get_outlet(
                    name=f"Verify CH{channel} ON via SNMP",
                    ip=hw.BASELINE_IP,
                    channel=channel,
                    expected_state=True,
                    outlet_base_oid=hw.OUTLET_BASE_OID,
                    community=hw.SNMP_COMMUNITY
                ),
                # Turn OFF via web interface
                ETH.http_post_action(
                    name=f"POST /control - Turn OFF CH{channel}",
                    base_url=base_url,
                    path=hw.CONTROL_PATH,
                    data={f"outlet{channel}": "off"},
                    timeout=hw.HTTP_TIMEOUT,
                    accept_status=(200, 302),
                    dump_subdir=dumps_dir
                ),
                # Verify via SNMP
                SNMP.get_outlet(
                    name=f"Verify CH{channel} OFF via SNMP",
                    ip=hw.BASELINE_IP,
                    channel=channel,
                    expected_state=False,
                    outlet_base_oid=hw.OUTLET_BASE_OID,
                    community=hw.SNMP_COMMUNITY
                )
            ])

        return [
            # Step 1: Basic HTTP connectivity
            STE(
                ETH.ping_action(
                    name="Ping device",
                    ip=hw.BASELINE_IP,
                    count=1,
                    timeout_per_pkt=1
                ),
                ETH.http_get_action(
                    name="GET / (root page)",
                    base_url=base_url,
                    path="/",
                    timeout=hw.HTTP_TIMEOUT,
                    accept_status=(200, 304),
                    require_nonempty=True,
                    dump_subdir=dumps_dir
                ),
                ETH.expect_header_prefix_action(
                    name="Verify Content-Type is HTML",
                    base_url=base_url,
                    path="/",
                    header_name="Content-Type",
                    prefix="text/html",
                    timeout=hw.HTTP_TIMEOUT,
                    dump_subdir=dumps_dir
                ),
                name="Basic HTTP connectivity test"
            ),

            # Step 2: Test control page availability
            STE(
                ETH.http_get_action(
                    name="GET /control.html",
                    base_url=base_url,
                    path="/control.html",
                    timeout=hw.HTTP_TIMEOUT,
                    accept_status=(200, 304),
                    require_nonempty=True,
                    dump_subdir=dumps_dir
                ),
                ETH.http_get_action(
                    name="GET /settings.html",
                    base_url=base_url,
                    path="/settings.html",
                    timeout=hw.HTTP_TIMEOUT,
                    accept_status=(200, 304),
                    require_nonempty=True,
                    dump_subdir=dumps_dir
                ),
                name="Test web interface page availability"
            ),

            # Step 3: Test outlet control via HTTP POST
            STE(
                *control_actions,
                name="Test outlet control via HTTP and verify with SNMP"
            ),

            # Step 4: Test settings page form submission
            STE(
                UART.send_command_uart(
                    name="Get current network config via Serial",
                    port=hw.SERIAL_PORT,
                    command=hw.NETINFO_CMD,
                    baudrate=hw.BAUDRATE
                ),
                UART.validate_tokens(
                    name="Verify baseline network config",
                    response="",
                    tokens=[hw.BASELINE_IP, hw.BASELINE_GATEWAY, hw.BASELINE_SUBNET]
                ),
                ETH.http_post_action(
                    name="POST /settings - Update network config",
                    base_url=base_url,
                    path=hw.SETTINGS_PATH,
                    data={
                        "ip": hw.TEMP_NEW_IP,
                        "subnet": hw.BASELINE_SUBNET,
                        "gateway": hw.BASELINE_GATEWAY,
                        "dns": hw.BASELINE_DNS
                    },
                    timeout=hw.HTTP_TIMEOUT,
                    accept_status=(200, 302),
                    dump_subdir=dumps_dir
                ),
                name="Test network settings update via HTTP (expect reboot)"
            ),

            # Step 5: Verify new IP after reboot
            STE(
                UART.send_command_uart(
                    name="Wait for reboot and verify new IP",
                    port=hw.SERIAL_PORT,
                    command=hw.NETINFO_CMD,
                    baudrate=hw.BAUDRATE,
                    reboot=True
                ),
                UART.validate_tokens(
                    name="Verify new IP in NETINFO",
                    response="",
                    tokens=[hw.TEMP_NEW_IP]
                ),
                ETH.ping_action(
                    name="Ping new IP address",
                    ip=hw.TEMP_NEW_IP,
                    count=1,
                    timeout_per_pkt=2
                ),
                name="Verify device responds on new IP"
            ),

            # Step 6: Revert to baseline configuration
            STE(
                UART.set_network_parameter(
                    name="Revert to baseline network config",
                    port=hw.SERIAL_PORT,
                    param="CONFIG_NETWORK",
                    value=f"{hw.BASELINE_IP}${hw.BASELINE_SUBNET}${hw.BASELINE_GATEWAY}${hw.BASELINE_DNS}",
                    baudrate=hw.BAUDRATE,
                    reboot_timeout=20
                ),
                ETH.ping_action(
                    name="Ping baseline IP after revert",
                    ip=hw.BASELINE_IP,
                    count=1,
                    timeout_per_pkt=2
                ),
                ETH.http_get_action(
                    name="GET / to confirm HTTP working on baseline IP",
                    base_url=base_url,
                    path="/",
                    timeout=hw.HTTP_TIMEOUT,
                    accept_status=(200, 304),
                    require_nonempty=True,
                    dump_subdir=dumps_dir
                ),
                name="Revert to baseline configuration"
            )
        ]


def main():
    """Create test instance and run"""
    test_instance = tc_network_http_test()
    return run_test_with_teardown(
        test_class_instance=test_instance,
        test_name="tc_network_http",
        reports_dir="report_tc_network_http"
    )


if __name__ == "__main__":
    sys.exit(main())
