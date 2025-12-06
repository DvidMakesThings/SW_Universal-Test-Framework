# UTFW GUI Frontend

An optional graphical user interface for the Universal Test Framework (UTFW).

## Overview

The UTFW GUI provides a user-friendly interface for discovering, viewing, and running UTFW tests. It shows test steps in real-time with live status updates, log output, and detailed metadata about each step.

### Key Features

- **Test Discovery**: Automatically finds all test modules under a selected directory
- **Step Preview**: View all test steps before running (PRE/STEP/POST/TEARDOWN)
- **Live Execution**: Real-time status updates with color-coded results (green=PASS, red=FAIL)
- **Log Streaming**: Live log output as tests execute
- **Metadata Display**: Shows expected values, min/max ranges, SNMP OIDs, commands, etc.
- **Sub-step Support**: Fully supports STE (sequential) and PTE (parallel) sub-steps

## Installation

The GUI requires PySide6. Install it with:

```bash
pip install PySide6
```

**Note:** PySide6 is only required for the GUI. CLI/headless usage works without it.

## Usage

### Launching the GUI

From the repository root:

```bash
python utfw_gui.py
```

Or from anywhere:

```bash
python -m UTFW.gui.app
```

### Using the GUI

1. **Select Test Root**: Click "Select Test Root" and choose your tests directory
   - The GUI will auto-discover `tests/` if present in the current directory

2. **Browse Tests**: Tests appear in the left panel
   - Click any test to load its step structure

3. **View Steps**: The right panel shows:
   - All test steps organized by phase (PRE-STEP, STEP, POST-STEP, TEARDOWN)
   - Sub-steps are indented with → symbol
   - Expected values, ranges, and other metadata

4. **Run Tests**: Click "Run Selected Test"
   - Steps update live with PASS/FAIL status
   - Log output streams in real-time
   - Green rows = PASS, Red rows = FAIL, Yellow = RUNNING

5. **Inspect Details**: Click any step to view full metadata
   - Shows all captured variables (expected, min/max, IP, OID, commands, etc.)

## Architecture

The GUI is completely separate from the core framework and follows these principles:

### 1. No CLI Impact

- All core functionality remains unchanged
- CLI tests work exactly as before
- No new dependencies for CLI users

### 2. Event/Listener System

The GUI hooks into the framework via:

- `TestReporter.add_listener()`: Receives test events (step_start, step_end, log messages)
- `UniversalLogger.add_subscriber()`: Receives raw log lines

These are **optional** and only used by the GUI.

### 3. Generic Action Handling

The GUI treats all actions generically:

- Uses the same `_resolve_action()` logic as the core framework
- Supports TestAction, STE, PTE, and any action-like objects
- New modules automatically work without GUI changes

### 4. Metadata Extraction

Expected values and other metadata are extracted by inspecting action closures:

```python
def extract_action_metadata(action) -> Dict[str, Any]:
    # Inspects execute_func.__closure__ and __code__.co_freevars
    # Returns dict with captured variables: expected, min_val, max_val, ip, oid, etc.
```

This works generically without requiring modules to know about the GUI.

## File Structure

```
UTFW/gui/
├── __init__.py          # Package init
├── model.py             # Non-GUI logic (discovery, metadata, execution)
├── main_window.py       # PySide6 GUI implementation
├── app.py               # Application entry point
└── README.md            # This file

utfw_gui.py              # Top-level launcher script
```

## Test Discovery

The GUI discovers tests using these patterns:

1. **Directories**: `tc_*/tc_*.py` (e.g., `tc_serial/tc_serial.py`)
2. **Standalone files**: `tc_*.py` (e.g., `tc_sanity_check.py`)

For each module, it looks for:

- A class matching the module name (e.g., `tc_serial` in `tc_serial.py`), OR
- Any class with a `setup()` method

## Limitations and Future Enhancements

### Current Limitations

- **No test interruption**: Tests cannot be stopped mid-execution
- **Single test at a time**: Only one test can run at a time
- **No test history**: Previous results are not saved between runs
- **Basic step timing**: Duration tracking is basic (from core TestStep data)

### Future Enhancements

- Stop button to interrupt running tests
- Test history and result comparison
- Filter/search for specific tests
- Export test results
- Test suite execution (run multiple tests)
- Configuration editor for hardware_config.py

## Thread Safety

The GUI uses Qt signals/slots for thread-safe communication:

```python
class EventBridge(QObject):
    event_received = Signal(dict)
    log_line_received = Signal(str)
    test_finished = Signal(int)
```

Events from the background test thread are marshalled to the GUI thread via signals.

## Contributing

When adding new UTFW modules:

1. **No GUI changes needed**: The GUI automatically handles new modules
2. **Use standard patterns**: Return TestAction, STE, or PTE from test methods
3. **Capture important variables**: Use closures to capture expected values, IPs, commands, etc.

Example:

```python
def my_action(ip, oid, expected):
    def execute():
        # Test logic here
        pass
    return TestAction(f"Read OID {oid}", execute)
```

The GUI will automatically extract `ip`, `oid`, and `expected` from the closure.

## Troubleshooting

### GUI won't start

```bash
pip install PySide6
```

### No tests found

- Verify test root directory contains `tc_*` directories or files
- Check that test files have classes with `setup()` methods

### Steps not showing

- Ensure test class has `pre()`, `setup()`, `post()`, or `teardown()` methods
- Check that methods return lists of actions

### Metadata not showing

- Metadata is extracted from closure variables
- Only whitelisted variable names are shown (expected, min_val, max_val, ip, oid, etc.)
- See `extract_action_metadata()` in `model.py` for full list

## License

Same as UTFW framework.
