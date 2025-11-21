# UTFW Metrics Module

## Overview

The `metrics.py` module is a comprehensive testing framework for Prometheus-style metrics endpoints. It provides high-level functions and TestAction factories for fetching, parsing, and validating metrics exposed by devices in Prometheus text format.

## Key Features

- **Universal Design**: Works with any device exposing Prometheus-format metrics
- **Comprehensive Parsing**: Supports metrics with and without labels
- **Detailed Logging**: All operations logged through UTFW logging system
- **Flexible Validation**: Multiple validation methods (existence, value, range, comparison)
- **Easy Integration**: TestAction factories work seamlessly with STE
- **Wait Conditions**: Poll metrics until conditions are met
- **Channel Support**: Built-in support for multi-channel devices

## Installation

Place `metrics.py` in your UTFW installation:
```
UTFW/modules/network/metrics.py
```

## Quick Start

```python
from UTFW.core.core import run_test_with_teardown, STE
from UTFW.modules.network import metrics

class MyMetricsTest:
    def setup(self):
        metrics_url = "http://192.168.0.11/metrics"
        
        return [
            # Check metric exists
            metrics.check_metric_exists(
                "Verify health metric",
                metrics_url,
                "device_up"
            ),
            
            # Validate value
            metrics.check_metric_value(
                "Check system healthy",
                metrics_url,
                "device_up",
                "1"
            ),
            
            # Check numeric range
            metrics.check_metric_range(
                "Validate temperature",
                metrics_url,
                "temperature_celsius",
                min_value=20.0,
                max_value=35.0
            ),
        ]

if __name__ == "__main__":
    import sys
    test = MyMetricsTest()
    exit_code = run_test_with_teardown(test, "MyMetricsTest")
    sys.exit(exit_code)
```

## Core Functions

### fetch_metrics(url, timeout=5.0)
Fetches raw metrics text from an HTTP endpoint.

**Args:**
- `url` (str): Full URL to metrics endpoint
- `timeout` (float): Request timeout in seconds

**Returns:** Raw metrics text as string

**Example:**
```python
metrics_text = fetch_metrics("http://192.168.0.11/metrics")
```

### parse_metrics(metrics_text)
Parses Prometheus-formatted text into structured data.

**Args:**
- `metrics_text` (str): Raw metrics text

**Returns:** Dictionary mapping metric names to lists of (labels, value) tuples

**Example:**
```python
metrics = parse_metrics(metrics_text)
# Returns: {'temperature_celsius': [({}, '25.5')], 
#           'channel_voltage': [({'ch': '1'}, '12.0'), ({'ch': '2'}, '11.9')]}
```

### get_metric_value(metrics, metric_name, labels=None)
Extracts a specific metric value from parsed metrics.

**Args:**
- `metrics` (dict): Parsed metrics from parse_metrics()
- `metric_name` (str): Metric name
- `labels` (dict, optional): Label filters

**Returns:** Metric value as string, or None if not found

### validate_metric_exists(url, metric_name, labels=None, timeout=5.0)
Validates a metric exists at the endpoint.

**Returns:** True if exists, False otherwise

### validate_metric_value(url, metric_name, expected_value, labels=None, timeout=5.0)
Validates a metric has an expected string value.

**Returns:** True if matches

**Raises:** MetricsTestError if mismatch or not found

### validate_metric_range(url, metric_name, min_value=None, max_value=None, labels=None, timeout=5.0)
Validates a numeric metric falls within range.

**Args:**
- `min_value` (float, optional): Minimum acceptable value (inclusive)
- `max_value` (float, optional): Maximum acceptable value (inclusive)

**Returns:** Actual metric value as float

**Raises:** MetricsTestError if out of range or not found

### compare_metrics(url, metric1_name, metric2_name, comparison="equal", ...)
Compares two metrics against each other.

**Args:**
- `comparison` (str): One of "equal", "greater", "less", "greater_equal", "less_equal"
- `tolerance` (float): Tolerance for "equal" comparison

**Returns:** Tuple of (metric1_value, metric2_value)

### get_all_labels_for_metric(url, metric_name, timeout=5.0)
Gets all label combinations for a metric.

**Returns:** List of label dictionaries

**Example:**
```python
labels = get_all_labels_for_metric(url, "channel_voltage")
# Returns: [{'ch': '1'}, {'ch': '2'}, {'ch': '3'}, ...]
```

## TestAction Factories

All TestAction factories follow the same pattern and return TestAction objects that can be used directly in test steps or grouped with STE.

### check_metric_exists()
Creates TestAction that validates metric existence.

**Example:**
```python
metrics.check_metric_exists(
    "Verify uptime metric",
    "http://192.168.0.11/metrics",
    "device_uptime_seconds"
)
```

### check_metric_value()
Creates TestAction that validates exact value match.

**Example:**
```python
# Simple value
metrics.check_metric_value(
    "Verify system healthy",
    "http://192.168.0.11/metrics",
    "device_up",
    "1"
)

# Labeled metric
metrics.check_metric_value(
    "Verify CH1 OFF",
    "http://192.168.0.11/metrics",
    "channel_state",
    "0",
    labels={"ch": "1"}
)
```

### check_metric_range()
Creates TestAction that validates numeric range.

**Example:**
```python
# Full range
metrics.check_metric_range(
    "Check temperature",
    "http://192.168.0.11/metrics",
    "temperature_celsius",
    min_value=20.0,
    max_value=35.0
)

# Min only
metrics.check_metric_range(
    "USB voltage above 4.5V",
    "http://192.168.0.11/metrics",
    "usb_volts",
    min_value=4.5
)

# Max only
metrics.check_metric_range(
    "Temperature below 40C",
    "http://192.168.0.11/metrics",
    "temperature_celsius",
    max_value=40.0
)
```

### check_metrics_comparison()
Creates TestAction that compares two metrics.

**Example:**
```python
# Equal comparison with tolerance
metrics.check_metrics_comparison(
    "CH1 and CH2 voltages match",
    "http://192.168.0.11/metrics",
    "channel_voltage",
    "channel_voltage",
    comparison="equal",
    metric1_labels={"ch": "1"},
    metric2_labels={"ch": "2"},
    tolerance=0.1
)

# Greater than
metrics.check_metrics_comparison(
    "Supply > USB voltage",
    "http://192.168.0.11/metrics",
    "vsupply_volts",
    "vusb_volts",
    comparison="greater"
)
```

### read_metric()
Creates TestAction that reads and logs a metric without validation.

**Example:**
```python
metrics.read_metric(
    "Record uptime",
    "http://192.168.0.11/metrics",
    "device_uptime_seconds"
)
```

### check_all_channels_state()
Creates TestAction that validates all channels have specific state.

**Example:**
```python
# Check all 8 channels are OFF
metrics.check_all_channels_state(
    "Verify all channels OFF",
    "http://192.168.0.11/metrics",
    expected_state=0,
    channel_count=8
)

# Check all channels are ON
metrics.check_all_channels_state(
    "Verify all channels ON",
    "http://192.168.0.11/metrics",
    expected_state=1
)
```

### wait_for_metric_condition()
Creates TestAction that polls until condition is met.

**Example:**
```python
# Wait for boot complete
metrics.wait_for_metric_condition(
    "Wait for device boot",
    "http://192.168.0.11/metrics",
    "uptime_seconds",
    condition="greater",
    target_value=10.0,
    timeout=60.0,
    poll_interval=1.0
)

# Wait for channel ON
metrics.wait_for_metric_condition(
    "Wait for CH1 ON",
    "http://192.168.0.11/metrics",
    "channel_state",
    condition="equals",
    target_value="1",
    labels={"ch": "1"},
    timeout=10.0
)
```

**Supported conditions:**
- `"equals"`: String equality
- `"not_equals"`: String inequality
- `"greater"`: Numeric greater than
- `"less"`: Numeric less than
- `"greater_equal"`: Numeric greater or equal
- `"less_equal"`: Numeric less or equal

## Working with Labeled Metrics

Many Prometheus metrics include labels to distinguish between multiple instances (e.g., channels, interfaces). The metrics module fully supports labeled metrics.

### Single Label
```python
metrics.check_metric_value(
    "Check CH1 voltage",
    url,
    "channel_voltage_volts",
    "12.0",
    labels={"ch": "1"}
)
```

### Multiple Labels
```python
metrics.check_metric_value(
    "Check interface status",
    url,
    "interface_status",
    "up",
    labels={"interface": "eth0", "type": "physical"}
)
```

### No Labels
```python
# If labels=None, matches metrics without labels or returns first instance
metrics.check_metric_value(
    "Check temperature",
    url,
    "temperature_celsius",
    "25.5"
)
```

## Error Handling

All functions raise `MetricsTestError` on failure with descriptive messages:

```python
try:
    validate_metric_value(url, "invalid_metric", "value")
except MetricsTestError as e:
    print(f"Validation failed: {e}")
```

Common error scenarios:
- HTTP request failures (network, timeout)
- Metric not found
- Value mismatch
- Parse errors (non-numeric for range validation)
- Out of range values

## Logging

All operations are logged through UTFW's logging system with `[METRICS]` prefix:

```
[METRICS] fetch_metrics() called
[METRICS]   URL: http://192.168.0.11/metrics, Timeout: 5.0s
[METRICS] Sending GET request to http://192.168.0.11/metrics...
[METRICS] Response received: status=200
[METRICS]   Content length: 3456 bytes
[METRICS]   Lines: 142
[METRICS] parse_metrics() called
[METRICS] Parsed 45 unique metric names
[METRICS]   energis_up: 1 instance(s)
[METRICS]   energis_uptime_seconds_total: 1 instance(s)
[METRICS]   energis_channel_voltage_volts: 8 instance(s)
[METRICS] ✓ Metric 'energis_up' exists with value: 1
```

## Prometheus Format Support

The module parses standard Prometheus text format:

```
# HELP metric_name Description of the metric
# TYPE metric_name gauge
metric_name 42.5
metric_name{label1="value1",label2="value2"} 100.0
```

**Supported:**
- Metrics with and without labels
- Multiple label key-value pairs
- Gauge, Counter, Histogram, Summary types (parsed as values)
- Comments (ignored)

**Limitations:**
- Histogram/Summary metrics are not fully decomposed (buckets/quantiles not parsed)
- Timestamps are ignored if present

## Integration with STE

TestActions can be grouped with STE for organized sub-steps:

```python
def setup(self):
    url = "http://192.168.0.11/metrics"
    
    return [
        # Step 1: System health check
        STE(
            metrics.check_metric_value(
                "System UP",
                url,
                "device_up",
                "1"
            ),
            metrics.check_metric_range(
                "Temperature nominal",
                url,
                "temperature_celsius",
                min_value=20.0,
                max_value=35.0
            ),
            metrics.check_metric_range(
                "Voltage nominal",
                url,
                "supply_volts",
                min_value=11.5,
                max_value=12.5
            ),
            name="System health check"
        ),
        
        # Step 2: Channel validation
        STE(
            metrics.check_all_channels_state(
                "All channels OFF",
                url,
                expected_state=0
            ),
            name="Channel state validation"
        ),
    ]
```

## Best Practices

1. **Use descriptive action names** - They appear in test reports
   ```python
   # Good
   metrics.check_metric_value("Verify temperature calibration enabled", ...)
   
   # Bad
   metrics.check_metric_value("Check value", ...)
   ```

2. **Group related checks with STE**
   ```python
   STE(
       metrics.check_metric_value(...),
       metrics.check_metric_range(...),
       name="System health validation"
   )
   ```

3. **Use appropriate validation type**
   - Existence: `check_metric_exists()` - Does it exist?
   - Exact: `check_metric_value()` - States, flags, enums
   - Range: `check_metric_range()` - Temperatures, voltages, percentages
   - Comparison: `check_metrics_comparison()` - Relationships between metrics

4. **Set appropriate timeouts**
   - Fast local networks: 3-5 seconds
   - Slow/remote networks: 10-30 seconds
   - Waiting for conditions: Match expected state change time

5. **Use read_metric() for documentation**
   ```python
   # Record values without validation
   metrics.read_metric("Record baseline temperature", url, "temp_celsius")
   ```

6. **Leverage wait_for_metric_condition()**
   ```python
   # Instead of time.sleep(), wait for actual state change
   metrics.wait_for_metric_condition(
       "Wait for ready",
       url,
       "status",
       condition="equals",
       target_value="ready",
       timeout=30.0
   )
   ```

## DUT Compatibility

The module is designed to work with any device exposing Prometheus-format metrics:

- Network equipment (routers, switches)
- Power distribution units (PDUs)
- Environmental sensors
- Server applications
- IoT devices
- Custom embedded systems

Tested with devices exposing metrics at common paths:
- `/metrics`
- `/prometheus`
- `/api/metrics`

## Troubleshooting

**Metric not found:**
- Verify metric name spelling (case-sensitive)
- Check labels match exactly
- Use `get_all_labels_for_metric()` to discover available labels
- Fetch raw metrics with `fetch_metrics()` to inspect format

**Parse errors:**
- Ensure endpoint returns Prometheus text format
- Check for proper line formatting
- Verify labels use proper syntax: `metric{label="value"}`

**Timeout errors:**
- Increase timeout parameter
- Check network connectivity
- Verify URL is correct
- Check device is accessible

**Range validation fails:**
- Ensure metric is numeric
- Check min/max values are reasonable
- Use `read_metric()` to see actual value first

## Example Test Patterns

### Pattern 1: Pre-test Health Check
```python
def pre(self):
    url = "http://192.168.0.11/metrics"
    return [
        STE(
            metrics.check_metric_value("System UP", url, "device_up", "1"),
            metrics.check_metric_range("Temp OK", url, "temp", min_value=15, max_value=45),
            name="Pre-test health verification"
        )
    ]
```

### Pattern 2: State Change Verification
```python
def setup(self):
    url = "http://192.168.0.11/metrics"
    return [
        # Command device (via other module)
        ...,
        
        # Wait for state change
        metrics.wait_for_metric_condition(
            "Wait for CH1 ON",
            url,
            "channel_state",
            condition="equals",
            target_value="1",
            labels={"ch": "1"},
            timeout=10.0
        ),
        
        # Verify measurements
        metrics.check_metric_range(
            "CH1 voltage nominal",
            url,
            "channel_voltage",
            min_value=11.5,
            max_value=12.5,
            labels={"ch": "1"}
        )
    ]
```

### Pattern 3: Multi-Channel Validation
```python
def setup(self):
    url = "http://192.168.0.11/metrics"
    
    # Validate all channels systematically
    channel_actions = []
    for ch in range(1, 9):
        channel_actions.append(
            metrics.check_metric_value(
                f"CH{ch} telemetry valid",
                url,
                "channel_telemetry_valid",
                "1",
                labels={"ch": str(ch)}
            )
        )
    
    return [
        STE(*channel_actions, name="Validate all channel telemetry")
    ]
```

## License

Part of Universal Test Framework (UTFW)
Author: DvidMakesThings
