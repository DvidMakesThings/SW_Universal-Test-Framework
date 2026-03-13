"""
UTFW Metrics Module - Usage Examples
=====================================

This file demonstrates how to use the metrics.py module in the Universal Test
Framework for testing devices that expose Prometheus-style metrics endpoints.

Example Device: Energis power distribution unit with /metrics endpoint
Metrics Endpoint: http://192.168.0.11/metrics
"""

import sys
from pathlib import Path
from UTFW.core import get_hwconfig
from UTFW.core import run_test_with_teardown
from UTFW.core import STE
from UTFW.modules import snmp as SNMP
from UTFW.modules import metrics
from UTFW.modules import serial as UART
from UTFW.modules import nop as NOP


class tc_metrics:
    def __init__(self):
        pass

    def pre(self):
        """Pre-steps: Reboot device and wait for it to be ready.
        These steps prepare the hardware before the actual test begins.
        """
        hw = get_hwconfig()

        return [
            
            # PRE-STEP 1: Send reboot command via UART

        ]
    
    def teardown(self):
        """Teardown: Cleanup actions that always run, even on failure.

        These steps are guaranteed to execute regardless of test outcome.
        Critical for ensuring hardware is left in a safe state.
        """
        hw = get_hwconfig()

        return [
            # TEARDOWN 1.1: Ensure all outputs are OFF (safety measure)
            SNMP.set_all_outlets(
                name="Ensure all outputs OFF",
                ip=hw.BASELINE_IP,
                all_on_oid=hw.ALL_ON_OID,
                all_off_oid=hw.ALL_OFF_OID,
                state=False,
                community=hw.SNMP_COMMUNITY
            ),

            # TEARDOWN 1.2: Final verification all outputs are OFF
            SNMP.verify_all_outlets(
                name="Final verify all outputs OFF",
                ip=hw.BASELINE_IP,
                outlet_base_oid=hw.OUTLET_BASE_OID,
                expected_state=False,
                community=hw.SNMP_COMMUNITY
            ),
        ]


    def setup(self):
        """Main test steps."""
        hw = get_hwconfig()

        metrics_url = f"http://{hw.BASELINE_IP}/metrics"

        return [
            # Step 1: Verify critical system metrics exist
            STE(
                # Step 1.0
                NOP.NOP(
                    name="Pause briefly to allow metrics endpoint to stabilize",
                    duration_ms=2000,
                ),
                # Step 1.1
                metrics.check_metric_exists(
                    name="Verify health metric exists",
                    url=metrics_url,
                    metric_name="energis_up",
                ),
                # Step 1.2
                metrics.check_metric_exists(
                    name="Verify uptime metric exists",
                    url=metrics_url,
                    metric_name="energis_uptime_seconds_total",
                ),
                # Step 1.3
                metrics.check_metric_exists(
                    name="Verify build info exists",
                    url=metrics_url,
                    metric_name="energis_build_info",
                ),
                name="Verify system metrics",
            ),
            # Step 2: Validate system health indicators
            STE(
                # Step 2.1
                metrics.check_metric_value(
                    name="Verify system is healthy",
                    url=metrics_url,
                    metric_name="energis_up",
                    expected_value="1",
                ),
                # Step 2.2
                metrics.check_metric_value(
                    name="Verify temperature calibration enabled",
                    url=metrics_url,
                    metric_name="energis_temp_calibrated",
                    expected_value="1",
                ),
                name="Validate system health status",
            ),
            # Step 3: Validate power supply voltages
            STE(
                # Step 3.1
                metrics.check_metric_range(
                    name="Check USB voltage in range",
                    url=metrics_url,
                    metric_name="energis_vusb_volts",
                    min_value=4.5,
                    max_value=5.5,
                ),
                # Step 3.2
                metrics.check_metric_range(
                    name="Check supply voltage in range",
                    url=metrics_url,
                    metric_name="energis_vsupply_volts",
                    min_value=11.5,
                    max_value=12.5,
                ),
                name="Validate power supply voltages",
            ),
            # Step 4: Verify all 8 channels are OFF (initial state)
            metrics.check_all_channels_state(
                name="Verify all 8 channels are OFF",
                url=metrics_url,
                expected_state=0,
                channel_count=8,
            ),
            # Step 5: Verify channel 1 metrics exist
            STE(
                # Step 5.1
                metrics.check_metric_exists(
                    name="Verify CH1 voltage metric exists",
                    url=metrics_url,
                    metric_name="energis_channel_voltage_volts",
                    labels={"ch": "1"},
                ),
                # Step 5.2
                metrics.check_metric_exists(
                    name="Verify CH1 current metric exists",
                    url=metrics_url,
                    metric_name="energis_channel_current_amps",
                    labels={"ch": "1"},
                ),
                # Step 5.3
                metrics.check_metric_exists(
                    name="Verify CH1 power metric exists",
                    url=metrics_url,
                    metric_name="energis_channel_power_watts",
                    labels={"ch": "1"},
                ),
                name="Verify channel 1 metrics",
            ),
            # Step 6: Validate channel 1 state
            STE(
                # Step 6.1
                metrics.check_metric_value(
                    name="Verify CH1 is OFF",
                    url=metrics_url,
                    metric_name="energis_channel_state",
                    expected_value="0",
                    labels={"ch": "1"},
                ),
                # Step 6.2
                metrics.check_metric_value(
                    name="Verify CH1 telemetry valid",
                    url=metrics_url,
                    metric_name="energis_channel_telemetry_valid",
                    expected_value="1",
                    labels={"ch": "1"},
                ),
                name="Validate channel 1 state",
            ),
            # Step 7: Verify channel 1 measurements are zero (OFF state)
            STE(
                # Step 7.1
                metrics.check_metric_value(
                    name="Verify CH1 voltage is near zero",
                    url=metrics_url,
                    metric_name="energis_channel_voltage_volts",
                    expected_value=(0.0, 0.01),
                    labels={"ch": "1"},
                ),
                # Step 7.2
                metrics.check_metric_value(
                    name="Verify CH1 current is near zero",
                    url=metrics_url,
                    metric_name="energis_channel_current_amps",
                    expected_value=(0.0, 0.005),
                    labels={"ch": "1"},
                ),
                # Step 7.3
                metrics.check_metric_value(
                    name="Verify CH1 power is near zero",
                    url=metrics_url,
                    metric_name="energis_channel_power_watts",
                    expected_value=(0.0, 0.01),
                    labels={"ch": "1"},
                ),
                name="Verify channel 1 measurements (OFF state)",
            ),
            # Step 8: Compare CH1 and CH2 voltages
            STE(
                # Step 8.1
                metrics.check_metrics_comparison(
                    name="Verify CH1 and CH2 voltages match",
                    url=metrics_url,
                    metric1_name="energis_channel_voltage_volts",
                    metric2_name="energis_channel_voltage_volts",
                    comparison="equal",
                    metric1_labels={"ch": "1"},
                    metric2_labels={"ch": "2"},
                    tolerance=0.1,
                ),
                name="Compare channel voltages",
            ),
            # Step 9: Verify supply vs USB voltage relationship
            STE(
                # Step 9.1
                metrics.check_metrics_comparison(
                    name="Verify 12V supply > USB voltage",
                    url=metrics_url,
                    metric1_name="energis_vsupply_volts",
                    metric2_name="energis_vusb_volts",
                    comparison="greater",
                ),
                name="Validate voltage relationships",
            ),
            # Step 10: Wait for device boot (uptime > target)
            metrics.wait_for_metric_condition(
                name="Wait for device boot (uptime > 5s)",
                url=metrics_url,
                metric_name="energis_uptime_seconds_total",
                condition="greater",
                target_value=5.0,
                timeout=30.0,
                poll_interval=1.0,
            ),
            # Step 11: Verify internal temperature stabilized
            metrics.check_metric_range(
                name="Verify temperature stabilized",
                url=metrics_url,
                metric_name="energis_internal_temperature_celsius",
                min_value=20.0,
                max_value=40.0,
            ),
            # Step 12: Record system telemetry metrics
            STE(
                # Step 12.1
                metrics.read_metric(
                    name="Record system uptime",
                    url=metrics_url,
                    metric_name="energis_uptime_seconds_total",
                ),
                # Step 12.2
                metrics.read_metric(
                    name="Record internal temperature",
                    url=metrics_url,
                    metric_name="energis_internal_temperature_celsius",
                ),
                # Step 12.3
                metrics.read_metric(
                    name="Record USB voltage",
                    url=metrics_url,
                    metric_name="energis_vusb_volts",
                ),
                # Step 12.4
                metrics.read_metric(
                    name="Record supply voltage",
                    url=metrics_url,
                    metric_name="energis_vsupply_volts",
                ),
                name="Record system telemetry",
            ),
            # Step 13: Record channel power consumption (CH1-CH3)
            STE(
                # Step 13.1
                metrics.read_metric(
                    name="Record CH1 power",
                    url=metrics_url,
                    metric_name="energis_channel_power_watts",
                    labels={"ch": "1"},
                ),
                # Step 13.2
                metrics.read_metric(
                    name="Record CH2 power",
                    url=metrics_url,
                    metric_name="energis_channel_power_watts",
                    labels={"ch": "2"},
                ),
                # Step 13.3
                metrics.read_metric(
                    name="Record CH3 power",
                    url=metrics_url,
                    metric_name="energis_channel_power_watts",
                    labels={"ch": "3"},
                ),
                name="Record channel power consumption",
            ),
            # Step 14: Re-verify all channels OFF before health summary
            metrics.check_all_channels_state(
                name="Verify all channels initially OFF",
                url=metrics_url,
                expected_state=0,
            ),
            # Step 15: Comprehensive system health check
            STE(
                # Step 15.1
                metrics.check_metric_value(
                    name="System health UP",
                    url=metrics_url,
                    metric_name="energis_up",
                    expected_value="1",
                ),
                # Step 15.2
                metrics.check_metric_range(
                    name="Temperature nominal",
                    url=metrics_url,
                    metric_name="energis_internal_temperature_celsius",
                    min_value=15.0,
                    max_value=45.0,
                ),
                # Step 15.3
                metrics.check_metric_range(
                    name="USB voltage nominal",
                    url=metrics_url,
                    metric_name="energis_vusb_volts",
                    min_value=4.5,
                    max_value=5.5,
                ),
                # Step 15.4
                metrics.check_metric_range(
                    name="Supply voltage nominal",
                    url=metrics_url,
                    metric_name="energis_vsupply_volts",
                    min_value=11.0,
                    max_value=13.0,
                ),
                # Step 15.5
                metrics.check_metric_value(
                    name="Temperature calibration enabled",
                    url=metrics_url,
                    metric_name="energis_temp_calibrated",
                    expected_value="1",
                ),
                name="Comprehensive system health check",
            ),
            # Step 16: Verify telemetry validity for all channels (CH1-CH8)
            STE(
                # Step 16.1
                metrics.check_metric_value(
                    name="CH1 telemetry valid",
                    url=metrics_url,
                    metric_name="energis_channel_telemetry_valid",
                    expected_value="1",
                    labels={"ch": "1"},
                ),
                # Step 16.2
                metrics.check_metric_value(
                    name="CH2 telemetry valid",
                    url=metrics_url,
                    metric_name="energis_channel_telemetry_valid",
                    expected_value="1",
                    labels={"ch": "2"},
                ),
                # Step 16.3
                metrics.check_metric_value(
                    name="CH3 telemetry valid",
                    url=metrics_url,
                    metric_name="energis_channel_telemetry_valid",
                    expected_value="1",
                    labels={"ch": "3"},
                ),
                # Step 16.4
                metrics.check_metric_value(
                    name="CH4 telemetry valid",
                    url=metrics_url,
                    metric_name="energis_channel_telemetry_valid",
                    expected_value="1",
                    labels={"ch": "4"},
                ),
                # Step 16.5
                metrics.check_metric_value(
                    name="CH5 telemetry valid",
                    url=metrics_url,
                    metric_name="energis_channel_telemetry_valid",
                    expected_value="1",
                    labels={"ch": "5"},
                ),
                # Step 16.6
                metrics.check_metric_value(
                    name="CH6 telemetry valid",
                    url=metrics_url,
                    metric_name="energis_channel_telemetry_valid",
                    expected_value="1",
                    labels={"ch": "6"},
                ),
                # Step 16.7
                metrics.check_metric_value(
                    name="CH7 telemetry valid",
                    url=metrics_url,
                    metric_name="energis_channel_telemetry_valid",
                    expected_value="1",
                    labels={"ch": "7"},
                ),
                # Step 16.8
                metrics.check_metric_value(
                    name="CH8 telemetry valid",
                    url=metrics_url,
                    metric_name="energis_channel_telemetry_valid",
                    expected_value="1",
                    labels={"ch": "8"},
                ),
                name="Verify all channel telemetry valid",
            ),
        ]


def main():
    """Create test instance and run"""
    test_instance = tc_metrics()
    return run_test_with_teardown(
        test_class_instance=test_instance,
        test_name="tc_metrics",
        reports_dir="report_tc_metrics",
    )


if __name__ == "__main__":
    sys.exit(main())
