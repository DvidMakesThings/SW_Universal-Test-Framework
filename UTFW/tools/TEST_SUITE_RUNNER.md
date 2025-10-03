# Test Suite Runner Documentation

The UTFW framework includes a test suite runner that allows you to execute multiple tests based on YAML or JSON configuration files. This is ideal for regression testing, nightly builds, and custom test suites.

## Overview

The test suite runner (`run_test_suite.py`) executes multiple test cases sequentially, collects results, and generates comprehensive summary reports.

## Features

- Execute multiple tests from a single configuration file
- Support for both YAML and JSON configuration formats
- Per-test timeout configuration
- Enable/disable individual tests without modifying code
- Automatic result collection and reporting
- JSON summary reports for CI/CD integration
- Exit codes for automation (0 = all passed, 1 = some failed, 2 = error)

## Usage

### Basic Usage

```bash
# Run a test suite with hardware config
python UTFW/tools/run_test_suite.py --config test_suites/regression.yaml --hwcfg tests/hardware_config.py

# Run with custom reports directory
python UTFW/tools/run_test_suite.py --config test_suites/nightly.yaml --hwcfg tests/hardware_config.py --reports-dir ./nightly_reports

# Short form
python UTFW/tools/run_test_suite.py -c test_suites/smoke.yaml --hwcfg tests/hardware_config.py -r ./reports
```

### Command Line Options

- `--config, -c`: Path to test suite configuration file (required)
- `--hwcfg`: Path to hardware configuration file (passed to all tests)
- `--reports-dir, -r`: Directory for test reports (default: `_SoftwareTest/Reports`)

## Configuration Format

### YAML Format (Recommended)

```yaml
name: "Regression Tests"
description: "Full regression test suite for pre-release validation"

tests:
  - name: "Serial Communication Test"
    path: "tests/tc_serial/tc_serial_utfw.py"
    enabled: true
    timeout: 300

  - name: "Network Test"
    path: "tests/tc_network_eth/tc_network_eth.py"
    enabled: true
    timeout: 180

  - name: "Experimental Test"
    path: "tests/tc_experimental/tc_experimental.py"
    enabled: false  # Disabled - will be skipped
    timeout: 120
```

### JSON Format

```json
{
  "name": "Network Tests Only",
  "description": "Test suite focused on network functionality",
  "tests": [
    {
      "name": "Ethernet Basic Test",
      "path": "tests/tc_network_eth/tc_network_eth.py",
      "enabled": true,
      "timeout": 300
    },
    {
      "name": "HTTP Network Test",
      "path": "tests/tc_network_http/tc_network_http.py",
      "enabled": true,
      "timeout": 300
    }
  ]
}
```

## Configuration Fields

### Suite Level

- `name` (string): Name of the test suite
- `description` (string, optional): Description of the test suite purpose
- `tests` (array): List of test specifications

### Test Level

- `name` (string): Display name for the test
- `path` (string): Relative path to the test Python file
- `enabled` (boolean, optional): Whether to run this test (default: true)
- `timeout` (integer, optional): Timeout in seconds (default: 600)

## Pre-configured Test Suites

The framework includes several pre-configured test suites in the `test_suites/` directory:

### 1. Smoke Tests (`smoke.yaml`)

Quick validation tests for basic functionality.

- Duration: 5-10 minutes
- Tests: Serial communication, basic network
- Use case: Quick sanity checks after code changes

```bash
python UTFW/tools/run_test_suite.py -c test_suites/smoke.yaml --hwcfg tests/hardware_config.py
```

### 2. Regression Tests (`regression.yaml`)

Comprehensive test suite for pre-release validation.

- Duration: 30-60 minutes
- Tests: All functional tests (serial, network, PCAP, EEPROM, power)
- Use case: Pre-release validation, merge request validation

```bash
python UTFW/tools/run_test_suite.py -c test_suites/regression.yaml --hwcfg tests/hardware_config.py
```

### 3. Nightly Tests (`nightly.yaml`)

Extended test suite including stress tests.

- Duration: 2-4 hours
- Tests: All functional tests + stress tests
- Use case: Overnight automated testing, stability validation

```bash
python UTFW/tools/run_test_suite.py -c test_suites/nightly.yaml --hwcfg tests/hardware_config.py
```

### 4. Network Tests Only (`network_only.json`)

Focused test suite for network functionality.

- Duration: 15-20 minutes
- Tests: Ethernet, HTTP, SNMP, PCAP network tests
- Use case: Network-specific validation

```bash
python UTFW/tools/run_test_suite.py -c test_suites/network_only.json --hwcfg tests/hardware_config.py
```

## Output and Reports

### Report Organization

The test suite runner organizes all test reports in the specified reports directory:

- **Suite summary report**: `<reports_dir>/test_suite_<suite_name>_<timestamp>.json`
- **Individual test reports**: `<reports_dir>/report_<test_name>/`

Each test's reports are automatically placed in a subdirectory within the suite reports directory, keeping everything organized in one location.

**Example structure:**
```
_SoftwareTest/Reports/
├── test_suite_Regression_Tests_20251003_143000.json  (Suite summary)
├── report_tc_serial_utfw/                             (Individual test reports)
│   ├── test_report.html
│   ├── test_report.json
│   └── test_log.txt
├── report_tc_network_eth/
│   ├── test_report.html
│   ├── test_report.json
│   └── test_log.txt
└── report_tc_stress_switching/
    ├── test_report.html
    ├── test_report.json
    └── test_log.txt
```

### Console Output

The runner provides real-time progress updates and a summary at the end:

```
################################################################################
# Test Suite: Regression Tests
# Description: Full regression test suite for pre-release validation
# Total Tests: 10
# Started: 2025-10-03 14:30:00
################################################################################

[1/10] Running: Serial Communication Test
File: tests/tc_serial/tc_serial_utfw.py
================================================================================
...

================================================================================
TEST SUITE SUMMARY: Regression Tests
================================================================================
Total Duration: 1234.56s
Total Tests:    10
  ✓ Passed:     8
  ✗ Failed:     2
  ⊗ Timeout:    0
  ! Error:      0
  - Skipped:    0
================================================================================
```

### JSON Summary Report

A detailed JSON report is saved to the reports directory:

```json
{
  "suite_name": "Regression Tests",
  "description": "Full regression test suite for pre-release validation",
  "started_at": "2025-10-03T14:30:00",
  "duration": 1234.56,
  "total_tests": 10,
  "passed": 8,
  "failed": 2,
  "skipped": 0,
  "timeout": 0,
  "error": 0,
  "results": [
    {
      "name": "Serial Communication Test",
      "path": "tests/tc_serial/tc_serial_utfw.py",
      "status": "PASS",
      "exit_code": 0,
      "duration": 123.45
    }
  ]
}
```

## Exit Codes

- `0`: All tests passed
- `1`: One or more tests failed
- `2`: Error running the suite (configuration error, etc.)

## CI/CD Integration

### Example GitHub Actions

```yaml
name: Nightly Tests

on:
  schedule:
    - cron: '0 2 * * *'  # Run at 2 AM daily

jobs:
  test:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v2
      - name: Run nightly test suite
        run: python UTFW/tools/run_test_suite.py -c test_suites/nightly.yaml --hwcfg tests/hardware_config.py
      - name: Upload reports
        uses: actions/upload-artifact@v2
        if: always()
        with:
          name: test-reports
          path: _SoftwareTest/Reports/
```

### Example Jenkins Pipeline

```groovy
pipeline {
    agent any
    triggers {
        cron('0 2 * * *')  // Run at 2 AM daily
    }
    stages {
        stage('Run Regression Tests') {
            steps {
                sh 'python UTFW/tools/run_test_suite.py -c test_suites/regression.yaml --hwcfg tests/hardware_config.py'
            }
        }
    }
    post {
        always {
            archiveArtifacts artifacts: '_SoftwareTest/Reports/**', allowEmptyArchive: true
        }
    }
}
```

## Creating Custom Test Suites

### Step 1: Create Configuration File

Create a new YAML or JSON file in the `test_suites/` directory:

```yaml
name: "My Custom Suite"
description: "Custom test suite for specific validation"

tests:
  - name: "Test 1"
    path: "tests/tc_serial/tc_serial_utfw.py"
    enabled: true
    timeout: 300
```

### Step 2: Run Your Suite

```bash
python UTFW/tools/run_test_suite.py -c test_suites/my_custom_suite.yaml
```

## Best Practices

1. **Use descriptive names**: Make test suite and test names clear and descriptive
2. **Set appropriate timeouts**: Consider test complexity when setting timeouts
3. **Group related tests**: Create focused suites for specific areas (network, serial, etc.)
4. **Disable flaky tests**: Use `enabled: false` for tests under development
5. **Version control configs**: Keep test suite configs in version control
6. **Document purpose**: Always include a description for custom test suites

## Troubleshooting

### YAML Import Error

If you get "PyYAML is required" error:

```bash
pip install pyyaml
```

### Test Not Found

Verify the path is correct relative to the project root:

```yaml
# Correct
path: "tests/tc_serial/tc_serial_utfw.py"

# Incorrect
path: "/absolute/path/tests/tc_serial/tc_serial_utfw.py"
```

### Timeout Issues

Increase timeout for long-running tests:

```yaml
- name: "Long Running Test"
  path: "tests/tc_stress_concurrent/tc_stress_concurrent.py"
  timeout: 3600  # 1 hour
```

## Requirements

- Python 3.7+
- PyYAML (optional, for YAML support): `pip install pyyaml`
- All test dependencies must be installed

## See Also

- [Main README](README.md) - Framework overview
- [Quick Reference](QUICK_REFERENCE.md) - Test writing guide
- Individual test documentation in `tests/` directories
