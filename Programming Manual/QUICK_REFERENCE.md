# UTFW Quick Reference

## Test Phases

### Four Test Phases Available

Tests can implement up to four phases for better organization:

1. **pre()** - Optional preparation (labeled `PRE-STEP 1, 2, ...`)
2. **setup()** - Required main test steps (labeled `STEP 1, 2, ...`)
3. **post()** - Optional post-success cleanup (labeled `POST-STEP 1, 2, ...`)
4. **teardown()** - Optional guaranteed cleanup (labeled `TEARDOWN 1.1, 1.2, ...`)

### Example with All Phases

```python
class MyTest:
    def pre(self):
        """Runs before main test"""
        return [power_on_device(), wait_for_boot()]

    def setup(self):
        """Main test (required)"""
        return [run_test(), verify_results()]

    def post(self):
        """Runs only if test passes"""
        return [save_logs()]

    def teardown(self):
        """Always runs, even on failure"""
        return [power_off_device()]
```

### When Each Phase Runs

**Success**: pre → setup → post → teardown
**Failure**: pre → setup (fails) → teardown (post skipped)

See [PRE_POST_TEARDOWN.md](PRE_POST_TEARDOWN.md) for detailed examples.

---

## Negative Tests

### How to Use Negative Tests

### Basic Usage
```python
# Any TestAction can be marked as negative test
UART.send_command_uart(
    name="Test description",
    port=hw.SERIAL_PORT,
    command="INVALID_CMD",
    baudrate=hw.BAUDRATE,
    negative_test=True  # Add this parameter
)
```

### When to Use
- ✅ Testing invalid commands
- ✅ Testing malformed inputs
- ✅ Testing boundary conditions
- ✅ Validating error messages
- ✅ Testing system error handling

### What Happens
| Test Outcome | negative_test=False | negative_test=True |
|-------------|--------------------|--------------------|
| Test Passes | ✅ PASS | ❌ FAIL_NEG (unexpected) |
| Test Fails  | ❌ FAIL (stops) | ✅ PASS_NEG (continues) |

## All Supported Modules

Every TestAction factory in these modules supports `negative_test`:

### Serial Module
```python
UART.send_command_uart(..., negative_test=True)
UART.validate_tokens(..., negative_test=True)
UART.set_network_parameter(..., negative_test=True)
UART.get_all_channels(..., negative_test=True)
# ... and 11 more functions
```

### SNMP Module
```python
SNMP.get_outlet(..., negative_test=True)
SNMP.set_outlet(..., negative_test=True)
SNMP.verify_all_outlets(..., negative_test=True)
# ... and 6 more functions
```

### Ethernet/HTTP Module
```python
ETH.http_get_action(..., negative_test=True)
ETH.http_post_action(..., negative_test=True)
ETH.ping_action(..., negative_test=True)
# ... and 6 more functions
```

### Network Module
```python
NET.ping_host(..., negative_test=True)
# ... and 1 more function
```

## Common Patterns

### Pattern 1: Test Invalid Commands
```python
STE(
    UART.send_command_uart(
        name="Test unknown command",
        port=hw.SERIAL_PORT,
        command="UNKNOWN_CMD_XYZ",
        baudrate=hw.BAUDRATE,
        negative_test=True
    ),
    name="Validate error handling for unknown commands"
)
```

### Pattern 2: Test Boundary Values
```python
STE(
    UART.send_command_uart(
        name="Test channel out of range",
        port=hw.SERIAL_PORT,
        command="SET_CH 99 ON",
        baudrate=hw.BAUDRATE,
        negative_test=True
    ),
    UART.send_command_uart(
        name="Test negative channel",
        port=hw.SERIAL_PORT,
        command="SET_CH -1 ON",
        baudrate=hw.BAUDRATE,
        negative_test=True
    ),
    name="Channel boundary tests"
)
```

### Pattern 3: Mixed Positive and Negative
```python
STE(
    # Positive test
    UART.send_command_uart(
        name="Valid command",
        port=hw.SERIAL_PORT,
        command="HELP",
        baudrate=hw.BAUDRATE
    ),
    # Negative test
    UART.send_command_uart(
        name="Invalid command",
        port=hw.SERIAL_PORT,
        command="INVALID",
        baudrate=hw.BAUDRATE,
        negative_test=True
    ),
    # Positive test to verify recovery
    UART.send_command_uart(
        name="Valid command after error",
        port=hw.SERIAL_PORT,
        command="SYSINFO",
        baudrate=hw.BAUDRATE
    ),
    name="Error recovery test"
)
```

## Log Output

### Positive Test
```
[STEP 1.1] Send HELP command
[PASS] STEP 1.1 completed successfully
```

### Negative Test (Expected Failure)
```
[STEP 1.2] Send invalid command (should fail) [NEGATIVE TEST]
[PASS_NEG] STEP 1.2 failed as expected (negative test): Unknown command
```

### Negative Test (Unexpected Success)
```
[STEP 1.3] Test should fail but passed [NEGATIVE TEST]
[FAIL_NEG] STEP 1.3 passed but expected to fail (negative test)
```

## New Test Suites Available

| Test Suite | Purpose |
|-----------|---------|
| tc_power_hlw8032 | Power monitoring (HLW8032 chip) |
| tc_stress_switching | Rapid relay switching stress test |
| tc_network_http | HTTP web interface testing |
| tc_eeprom_persistence | Configuration persistence |
| tc_stress_concurrent | Concurrent operations stress |
| tc_serial_errors | Error handling validation |

## Example Test File

See: `tests/tc_serial_errors/example_negative_test.py`

## PSE Alias

```python
# Both work identically:
PSE(action1, action2, name="Parallel test")
PTE(action1, action2, name="Parallel test")
```

## Tips

1. **Always test recovery** - After negative tests, verify system still works
2. **Be specific** - Use descriptive names for negative tests
3. **Test boundaries** - Invalid channels, IPs, values
4. **Test malformed input** - Missing params, wrong types
5. **Document expectations** - Explain why test should fail

## Report Generation

Reports automatically distinguish between:
- Regular passes: `PASS`
- Regular failures: `FAIL`
- Expected failures: `PASS_NEG`
- Unexpected successes: `FAIL_NEG`

Overall test passes if all positive tests pass and all negative tests fail as expected.
