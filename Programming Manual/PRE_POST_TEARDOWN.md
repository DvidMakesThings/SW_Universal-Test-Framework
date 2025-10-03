# Pre/Post/Teardown Test Phases

UTFW framework supports optional test phases for better test organization and guaranteed cleanup operations.

## Test Class Methods

A test class can implement up to four methods:

### 1. `pre()` - Preparation Phase (Optional)
Returns a list of preparation steps executed **before** the main test.

- **Label**: PRE-STEP 1, PRE-STEP 2, ...
- **Purpose**: Environment setup, power on equipment, initialize test conditions
- **When**: Always executed before `setup()` if defined
- **Report**: Appears with blue indicator in HTML reports

```python
def pre(self):
    return [
        power_on_device(),
        wait_for_boot(),
        initialize_test_environment()
    ]
```

### 2. `setup()` - Main Test Phase (Required)
Returns a list of main test steps.

- **Label**: STEP 1, STEP 2, ...
- **Purpose**: Core test logic
- **When**: Always executed (required method)
- **Report**: Standard appearance

```python
def setup(self):
    return [
        connect_to_device(),
        run_test_scenario(),
        verify_results()
    ]
```

### 3. `post()` - Normal Cleanup Phase (Optional)
Returns a list of cleanup steps executed **after successful** test completion.

- **Label**: POST-STEP 1, POST-STEP 2, ...
- **Purpose**: Normal cleanup operations (save logs, archive results)
- **When**: Only executed if `setup()` passes
- **Report**: Appears with green indicator in HTML reports

```python
def post(self):
    return [
        save_test_logs(),
        archive_results(),
        send_notification()
    ]
```

### 4. `teardown()` - Emergency Cleanup Phase (Optional)
Returns a list of critical cleanup steps that **always execute**.

- **Label**: TEARDOWN 1.1, 1.2, 1.3, ... (sub-step numbering)
- **Purpose**: Critical cleanup that must always happen (power off, disconnect, release resources)
- **When**:
  - **On failure**: Executes immediately when test fails
  - **On success**: Executes after `post()` completes
- **Report**: Appears with orange indicator in HTML reports
- **Important**: Teardown failures don't change test result

```python
def teardown(self):
    return [
        power_off_device(),
        disconnect_equipment(),
        release_resources()
    ]
```

## Execution Flow

### Success Path
```
pre() → setup() → post() → teardown()
```

All phases execute when the test passes successfully.

### Failure Path
```
pre() → setup() → [FAILURE] → teardown()
```

When any step fails, `post()` is skipped and `teardown()` executes immediately.

**Important Notes:**
- If `pre()` fails, the test stops and `teardown()` is called immediately
- If `setup()` fails, `post()` is skipped and `teardown()` is called
- `teardown()` ALWAYS executes, regardless of test outcome
- Failures in `teardown()` are logged but don't override the original test result

## Complete Example

```python
import sys
from pathlib import Path
from UTFW.core import run_test_with_teardown
from UTFW.core import get_hwconfig
from UTFW.modules import serial as UART

class MyDeviceTest:
    def __init__(self):
        pass

    def pre(self):
        """Preparation: Power on and initialize"""
        hw = get_hwconfig()
        return [
            UART.send_command_uart(
                name="Power on device",
                port=hw.SERIAL_PORT,
                command="POWER ON",
                baudrate=hw.BAUDRATE
            ),
            UART.send_command_uart(
                name="Wait for boot",
                port=hw.SERIAL_PORT,
                command="STATUS",
                baudrate=hw.BAUDRATE,
                expected_response="READY"
            )
        ]

    def setup(self):
        """Main test steps"""
        hw = get_hwconfig()
        return [
            UART.send_command_uart(
                name="Run test command",
                port=hw.SERIAL_PORT,
                command="TEST",
                baudrate=hw.BAUDRATE
            ),
            UART.send_command_uart(
                name="Verify result",
                port=hw.SERIAL_PORT,
                command="GET_RESULT",
                baudrate=hw.BAUDRATE,
                expected_response="PASS"
            )
        ]

    def post(self):
        """Normal cleanup: Save results"""
        hw = get_hwconfig()
        return [
            UART.send_command_uart(
                name="Save logs",
                port=hw.SERIAL_PORT,
                command="SAVE_LOGS",
                baudrate=hw.BAUDRATE
            )
        ]

    def teardown(self):
        """Critical cleanup: Always power off"""
        hw = get_hwconfig()
        return [
            UART.send_command_uart(
                name="Power off device",
                port=hw.SERIAL_PORT,
                command="POWER OFF",
                baudrate=hw.BAUDRATE
            )
        ]

def main():
    test_instance = MyDeviceTest()
    return run_test_with_teardown(
        test_class_instance=test_instance,
        test_name="device_test",
        reports_dir="report_device_test"
    )

if __name__ == "__main__":
    sys.exit(main())
```

## HTML Report Appearance

The HTML test reports clearly label each test phase with their respective prefixes:

- **PRE-STEP 1, PRE-STEP 2, ...** - Pre-execution steps
- **STEP 1, STEP 2, ...** - Main test steps
- **POST-STEP 1, POST-STEP 2, ...** - Post-execution steps
- **TEARDOWN 1.1, TEARDOWN 1.2, ...** - Teardown steps (substep numbering)

Each step appears as a separate, expandable entry in the report, making it easy to identify which phase a step belongs to when reviewing test results.

## Best Practices

1. **Use `pre()` for**:
   - Powering on equipment
   - Establishing connections
   - Setting up test environment
   - Operations that might fail before the actual test

2. **Use `setup()` for**:
   - Core test logic
   - Test scenarios and validations
   - All operations that determine test pass/fail

3. **Use `post()` for**:
   - Saving logs and results
   - Sending notifications
   - Normal cleanup operations
   - Operations that should only run on success

4. **Use `teardown()` for**:
   - Powering off equipment (safety critical)
   - Disconnecting from devices
   - Releasing shared resources
   - **Any operation that MUST happen regardless of test outcome**

5. **Keep teardown simple**: Teardown should be as simple and reliable as possible. Avoid complex logic that might fail.

6. **Teardown is not for test validation**: Don't put test checks in teardown. It's purely for cleanup.

## Backward Compatibility

All test phases except `setup()` are optional. Existing tests with only `setup()` will continue to work without modification.
