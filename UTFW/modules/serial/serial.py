# serial.py
"""
UTFW Serial Module
==================
High-level serial/UART test functions and TestAction factories for universal testing

This module provides comprehensive serial communication testing capabilities with
detailed logging integration. All functions that perform actual communication
integrate with the UTFW logging system to provide detailed TX/RX logging with
hex dumps and printable previews.

The module includes TestAction factories for common serial operations, making
it easy to build complex test scenarios using the STE (Sub-step Test Executor)
system.

Author: DvidMakesThings
"""

import time
import re
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any, Union

from ...core.logger import get_active_logger
from ...core.core import TestAction

DEBUG = False  # Set to True to enable debug prints

# Global response caching for validation chaining
_LAST_RESPONSE: Optional[str] = None


def _set_last_response(text: str) -> None:
    """Store the last response for use in validation functions.
    
    Args:
        text (str): Response text to cache.
    """
    global _LAST_RESPONSE
    _LAST_RESPONSE = text


def _use_response(explicit: str) -> str:
    """Get response text, either explicit or from cache.
    
    Args:
        explicit (str): Explicitly provided response text.
        
    Returns:
        str: Response text to use for validation.
        
    Raises:
        SerialTestError: If no response is available.
    """
    if explicit:
        return explicit
    if _LAST_RESPONSE:
        return _LAST_RESPONSE
    raise SerialTestError("No response available. Provide `response` explicitly or call send_* first.")


class SerialTestError(Exception):
    """Exception raised when serial communication or validation fails.
    
    This exception is raised by serial test functions when communication
    errors occur, validation fails, or other serial-related operations
    cannot be completed successfully.
    
    Args:
        message (str): Description of the error that occurred.
    """
    pass


def _ensure_pyserial():
    """Ensure pyserial library is available for import.
    
    Raises:
        ImportError: If pyserial is not installed.
    """
    try:
        import serial  # noqa: F401
    except ImportError:
        raise ImportError("pyserial is required. Install with: pip install pyserial")


def _open_connection(port: str, baudrate: int = 115200, timeout: float = 2.0):
    """Open a serial connection with proper configuration and logging.
    
    This function opens a serial port with the specified parameters and
    configures it for reliable communication. It also logs the connection
    event using the active logger.
    
    Args:
        port (str): Serial port identifier (e.g., "COM3", "/dev/ttyUSB0").
        baudrate (int, optional): Communication baud rate. Defaults to 115200.
        timeout (float, optional): Read timeout in seconds. Defaults to 2.0.
        
    Returns:
        serial.Serial: Configured and opened serial port object.
        
    Raises:
        SerialTestError: If the port cannot be opened or configured.
    """
    _ensure_pyserial()
    import serial

    try:
        ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=timeout,
            write_timeout=2.0,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False
        )
        time.sleep(0.1)  # Allow connection to stabilize
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        # Log serial connection opening
        logger = get_active_logger()
        if logger:
            logger.serial_open(port, baudrate)

        return ser
    except Exception as e:
        raise SerialTestError(f"Failed to open serial port {port}: {e}")


def send_command(port: str, command: str, baudrate: int = 115200, timeout: float = 2.0) -> str:
    """Send a command via serial port and return the complete response.
    
    This function opens a serial connection, sends the specified command,
    waits for and captures the response, then closes the connection. All
    communication is logged using the active logger with TX/RX details.
    
    Args:
        port (str): Serial port identifier (e.g., "COM3", "/dev/ttyUSB0").
        command (str): Command string to send (CR+LF will be appended).
        baudrate (int, optional): Communication baud rate. Defaults to 115200.
        timeout (float, optional): Response timeout in seconds. Defaults to 2.0.
        
    Returns:
        str: Complete response received from the device.
        
    Raises:
        SerialTestError: If communication fails or times out.
    """
    ser = _open_connection(port, baudrate, timeout)
    logger = get_active_logger()

    try:
        # Send command
        payload = (command.strip() + "\r\n")
        if logger:
            logger.serial_tx(payload)
        cmd_bytes = payload.encode('utf-8')
        ser.write(cmd_bytes)
        ser.flush()
        time.sleep(0.05)

        # Read response
        response_bytes = bytearray()
        start_time = time.time()
        last_data_time = start_time

        while (time.time() - start_time) < timeout:
            if ser.in_waiting > 0:
                chunk = ser.read(ser.in_waiting)
                response_bytes.extend(chunk)
                last_data_time = time.time()
            elif (time.time() - last_data_time) > 0.5:
                break
            time.sleep(0.01)

        text = response_bytes.decode('utf-8', errors='ignore')
        if logger:
            logger.serial_rx(text)
        return text

    finally:
        try:
            ser.close()
        finally:
            # Log serial connection closing
            if logger:
                logger.serial_close(port)


def wait_for_reboot_and_ready(port: str, ready_token: str = "SYSTEM READY",
                              baudrate: int = 115200, timeout: float = 10.0) -> bool:
    """Wait for device to reboot and display the ready signal.
    
    This function monitors a serial port for a device reboot sequence and
    waits for the specified ready token to appear in the output. It handles
    connection retries and logs all received data during the wait period.
    
    Args:
        port (str): Serial port identifier to monitor.
        ready_token (str, optional): Text token indicating device is ready.
            Defaults to "SYSTEM READY".
        baudrate (int, optional): Communication baud rate. Defaults to 115200.
        timeout (float, optional): Maximum time to wait in seconds. Defaults to 10.0.
        
    Returns:
        bool: True if the ready token was detected within the timeout,
            False otherwise.
    """
    _ensure_pyserial()
    import serial

    deadline = time.time() + timeout
    time.sleep(0.2)  # Give device time to start rebooting
    logger = get_active_logger()

    while time.time() < deadline:
        try:
            ser = serial.Serial(port=port, baudrate=baudrate, timeout=1.0)
            try:
                time.sleep(0.1)
                response_bytes = bytearray()
                banner_found = False
                while time.time() < deadline:
                    if ser.in_waiting > 0:
                        chunk = ser.read(ser.in_waiting)
                        response_bytes.extend(chunk)
                        text_chunk = chunk.decode('utf-8', errors='ignore')
                        if DEBUG: print(f"[DEBUG] Received during reboot: {text_chunk}")
                        # Check for banner in the latest chunk
                        if ready_token.lower() in text_chunk.lower():
                            banner_found = True
                            break
                    time.sleep(0.05)
                response = response_bytes.decode('utf-8', errors='ignore')
                if logger and response:
                    logger.serial_rx(response, note="reconnect")
                if banner_found:
                    return True
            finally:
                try:
                    ser.close()
                finally:
                    if logger:
                        logger.serial_close(port)
        except Exception:
            pass
        time.sleep(0.2)
    return False


def parse_sysinfo_response(response: str) -> Dict[str, str]:
    """Parse SYSINFO command response into a structured dictionary.
    
    This function parses the multi-line response from a SYSINFO command
    and extracts key system information into a dictionary with standardized
    key names.
    
    Args:
        response (str): Raw SYSINFO command response text.
        
    Returns:
        Dict[str, str]: Dictionary containing parsed system information
            with keys like "Serial", "Firmware", "Core Voltage", etc.
    """
    sysinfo = {}
    lines = response.replace("\r\n", "\n").replace("\r", "\n").splitlines()

    for line in lines:
        line = line.strip()
        if not line or line in ["SYSTEM INFORMATION:", "Clock Sources :"]:
            continue

        if line.startswith("[ECHO]"):
            line = line[6:].strip()

        if not line or line in ["SYSTEM INFORMATION:", "Clock Sources :"]:
            continue

        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()

            if "Device Serial" in key:
                sysinfo["Serial"] = value
            elif "Firmware Ver" in key:
                sysinfo["Firmware"] = value
            elif "Core voltage" in key:
                sysinfo["Core Voltage"] = value
            elif key == "SYS":
                sysinfo["SYS Frequency"] = value
            elif key == "USB":
                sysinfo["USB Frequency"] = value
            elif key == "PER":
                sysinfo["PER Frequency"] = value
            elif key == "ADC":
                sysinfo["ADC Frequency"] = value
            else:
                sysinfo[key] = value

    return sysinfo


def validate_sysinfo_data(sysinfo: Dict[str, str], validation: Dict[str, Any]):
    """Validate parsed SYSINFO data against specified validation rules.
    
    This function checks parsed system information against a set of validation
    rules including firmware version format, voltage ranges, and frequency
    expectations.
    
    Args:
        sysinfo (Dict[str, str]): Parsed system information dictionary.
        validation (Dict[str, Any]): Validation rules dictionary containing
            rules for firmware_regex, core_voltage_range, frequencies, etc.
            
    Raises:
        SerialTestError: If any validation rules fail.
    """
    failures = []

    # Firmware regex validation
    if 'firmware_regex' in validation:
        firmware = sysinfo.get("Firmware", "")
        if not re.match(validation['firmware_regex'], firmware):
            failures.append(f"Invalid firmware format: {firmware}")

    # Core voltage range validation
    if 'core_voltage_range' in validation:
        core_voltage_str = sysinfo.get("Core Voltage", "0")
        try:
            voltage_match = re.search(r'([\d.]+)', core_voltage_str)
            if voltage_match:
                core_voltage = float(voltage_match.group(1))
                min_v, max_v = validation['core_voltage_range']
                if not (min_v <= core_voltage <= max_v):
                    failures.append(f"Core voltage out of range: {core_voltage}V (expected {min_v}-{max_v}V)")
            else:
                failures.append(f"Could not parse core voltage: {core_voltage_str}")
        except ValueError:
            failures.append(f"Invalid core voltage value: {core_voltage_str}")

    # Frequency validations
    freq_validations = validation.get('frequencies', {})
    for freq_type, expected_hz in freq_validations.items():
        freq_field = f"{freq_type.replace('_hz_min', '').replace('_hz_expect', '').upper()} Frequency"

        if freq_field in sysinfo:
            try:
                freq_str = sysinfo[freq_field]
                freq_match = re.search(r'(\d+)', freq_str)
                if freq_match:
                    freq_value = int(freq_match.group(1))
                    if 'min' in freq_type:
                        if freq_value < expected_hz:
                            failures.append(f"{freq_field} too low: {freq_value} < {expected_hz}")
                    else:
                        if freq_value != expected_hz:
                            failures.append(f"{freq_field} mismatch: {freq_value} != {expected_hz}")
                else:
                    failures.append(f"Could not parse frequency: {freq_str}")
            except ValueError:
                failures.append(f"Invalid frequency value for {freq_field}: {sysinfo[freq_field]}")

    if failures:
        raise SerialTestError(f"SYSINFO validation failed: {'; '.join(failures)}")


def parse_get_ch_all(response: str) -> Dict[int, bool]:
    """Parse a multi-line 'GET_CH ALL' response into a channel state mapping.
    
    This function parses the response from a 'GET_CH ALL' command and extracts
    the state (ON/OFF) of each channel into a dictionary.

    Args:
        response (str): Raw response text from 'GET_CH ALL' command.
        
    Returns:
        Dict[int, bool]: Dictionary mapping channel numbers (1-8) to their
            states (True for ON, False for OFF).
    
    Example:
        Input response:
        [ECHO] Received CMD: "GET_CH ALL"
        [ECHO] CH1: OFF
        [ECHO] CH2: OFF
        ...
        [ECHO] CH8: OFF
        
        Returns: {1: False, 2: False, ..., 8: False}
    """
    lines = response.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    ch_map: Dict[int, bool] = {}
    pat = re.compile(r"CH\s*([1-8])\s*:\s*(ON|OFF)", re.IGNORECASE)

    for raw in lines:
        s = raw.strip()
        # strip optional "[ECHO]" prefix if present
        if s.startswith("[ECHO]"):
            s = s[6:].strip()

        m = pat.search(s)
        if not m:
            continue
        ch = int(m.group(1))
        on = m.group(2).upper() == "ON"
        ch_map[ch] = on

    return ch_map


# ======================== TestAction Factories ========================

def wait_for_reboot(
        name: str,
        port: str,
        banner: str = "SYSTEM READY",
        baudrate: int = 115200,
        timeout: float = 15.0
        ) -> "TestAction":
    """Create a TestAction that waits for device reboot and ready banner.
    
    This TestAction factory creates an action that monitors a serial port
    for a device reboot sequence and waits for the specified ready banner
    to appear. It's designed to be used in test steps where device reboots
    are expected.

    The action will continuously monitor the serial port, handling connection
    retries and logging all received data until the banner appears or the
    timeout is reached.

    Args:
        name (str): Human-readable name for the test step shown in reports.
            Should describe what reboot/ready state is being waited for.
        port (str): Serial port identifier (e.g., "COM11", "/dev/ttyACM0").
        banner (str, optional): Text banner indicating device is ready.
            Defaults to "SYSTEM READY".
        baudrate (int, optional): Serial communication baud rate.
            Defaults to 115200.
        timeout (float, optional): Maximum time to wait for ready banner
            in seconds. Defaults to 15.0.

    Returns:
        TestAction: TestAction that returns True when the banner is detected
            within the timeout period.

    Raises:
        SerialTestError: When executed, raises this exception if the device
            does not become ready within the timeout or if serial communication
            errors occur.
    
    Example:
        >>> reboot_action = wait_for_reboot(
        ...     "Wait for device reboot", "COM3", "SYSTEM READY", timeout=30.0
        ... )
        >>> # Use in STE: STE(reboot_action, next_action, ...)
    """
    def execute():
        ok = wait_for_reboot_and_ready(port, banner, baudrate, timeout)
        if not ok:
            raise SerialTestError(f"Device did not become ready (banner='{banner}', timeout={timeout}s)")
        return True

    return TestAction(name, execute)


def validate_all_channels_state(
        name: str,
        response: str,
        expected: Union[bool, List[bool], Dict[int, bool]]
        ) -> TestAction:
    """Create a TestAction that validates channel states from GET_CH ALL response.
    
    This TestAction factory creates an action that parses a 'GET_CH ALL' response
    and validates that the channel states match the expected configuration. It
    supports multiple formats for specifying expected states.

    Args:
        name (str): Human-readable name for the test action.
        response (str): Full response text to parse. If empty, uses the last
            cached response from a previous send_command_uart call.
        expected (Union[bool, List[bool], Dict[int, bool]]): Expected channel
            states in one of these formats:
            - bool: All 8 channels must be this state (True=ON, False=OFF)
            - List[bool]: List of 8 booleans, one per channel (index 0 = CH1)
            - Dict[int, bool]: Per-channel expectations {channel: state}.
              Only specified channels are validated.

    Returns:
        TestAction: TestAction that returns True if all validations pass.

    Raises:
        SerialTestError: When executed, raises this exception if any channel
            states don't match expectations, with detailed mismatch information.
    
    Example:
        >>> # Validate all channels are OFF
        >>> validate_action = validate_all_channels_state(
        ...     "Verify all channels OFF", "", False
        ... )
        >>> # Validate specific channels
        >>> validate_action = validate_all_channels_state(
        ...     "Verify CH1=ON, CH2=OFF", "", {1: True, 2: False}
        ... )
    """
    def execute():
        text = _use_response(response)
        actual = parse_get_ch_all(text)  # Dict[int,bool]

        # Build expected map
        if isinstance(expected, bool):
            exp_map = {i: expected for i in range(1, 9)}
        elif isinstance(expected, list) or isinstance(expected, tuple):
            if len(expected) != 8:
                raise SerialTestError(f"Expected list must have 8 items, got {len(expected)}")
            exp_map = {i: bool(expected[i-1]) for i in range(1, 9)}
        elif isinstance(expected, dict):
            # Only validate provided keys
            exp_map = {int(k): bool(v) for k, v in expected.items()}
        else:
            raise SerialTestError("Unsupported 'expected' type; use bool, List[bool], or Dict[int,bool]")

        # Compute mismatches
        mismatches = []
        missing = []
        for ch, want in exp_map.items():
            got = actual.get(ch)
            if got is None:
                missing.append(ch)
            elif got != want:
                mismatches.append((ch, want, got))

        if missing or mismatches:
            parts = []
            if missing:
                parts.append("missing: " + ", ".join(f"CH{c}" for c in sorted(missing)))
            if mismatches:
                parts.append("mismatch: " + ", ".join(
                    f"CH{c}=expected {'ON' if w else 'OFF'} got {'ON' if g else 'OFF'}"
                    for (c, w, g) in mismatches
                ))
            raise SerialTestError("GET_CH ALL validation failed: " + "; ".join(parts))

        return True

    return TestAction(name, execute)


def get_all_channels(
        name: str,
        port: str,
        expected: Optional[Union[bool, List[bool], Dict[int, bool]]] = None,
        baudrate: int = 115200,
        timeout: float = 2.0
        ) -> TestAction:
    """Create a TestAction that retrieves and optionally validates all channel states.
    
    This TestAction factory creates an action that sends a 'GET_CH ALL' command
    via UART, parses the response to extract channel states, and optionally
    validates them against expected values. The response is cached for use
    by subsequent validation actions.

    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier (e.g., "COM5", "/dev/ttyACM0").
        expected (Optional[Union[bool, List[bool], Dict[int, bool]]], optional):
            Expected channel states for validation. If None, only retrieval
            is performed. Formats:
            - bool: All channels must be this state
            - List[bool]: 8 booleans, one per channel
            - Dict[int, bool]: Per-channel expectations
        baudrate (int, optional): Serial communication baud rate.
            Defaults to 115200.
        timeout (float, optional): Response timeout in seconds.
            Defaults to 2.0.

    Returns:
        TestAction: TestAction that returns a dictionary mapping channel
            numbers (1-8) to their states (True=ON, False=OFF).

    Raises:
        SerialTestError: When executed, raises this exception if communication
            fails or if validation fails (when expected values are provided).
    
    Example:
        [ECHO] Received CMD: "GET_CH ALL"
        [ECHO] CH1: ON
        [ECHO] CH2: OFF
        ...
        [ECHO] CH8: OFF
        
        Usage:
        >>> get_action = get_all_channels("Get channel states", "COM5")
        >>> states = get_action.execute()  # Returns {1: True, 2: False, ...}
    """

    def execute():
        resp = send_command(port, "GET_CH ALL", baudrate, timeout)
        _set_last_response(resp)
        states = parse_get_ch_all(resp)
        if expected is not None:
            # Reuse validator to report detailed diff
            validate_all_channels_state(
                name=f"{name} – validate",
                response=resp,
                expected=expected
            ).execute_func()
        return states

    return TestAction(name, execute)


def send_command_uart(
        name: str,
        port: str,
        command,   # str or list[str]
        baudrate: int = 115200,
        timeout: float = 2.0
        ):
    """Create TestAction(s) for sending command(s) via UART with response caching.
    
    This function creates TestAction instances for sending commands via UART.
    It supports both single commands and multiple commands, with automatic
    response caching for use by subsequent validation actions.

    Args:
        name (str): Base name for the test action(s). For multiple commands,
            each action gets a numbered suffix with the command text.
        port (str): Serial port identifier (e.g., "COM3", "/dev/ttyACM0").
        command (Union[str, List[str]]): Command string or list of command
            strings to send via UART.
        baudrate (int, optional): Serial communication baud rate.
            Defaults to 115200.
        timeout (float, optional): Response timeout in seconds.
            Defaults to 2.0.

    Returns:
        Union[TestAction, List[TestAction]]: Single TestAction if command
            is a string, or list of TestActions if command is a list.

    Raises:
        TypeError: If command is neither a string nor a list/tuple of strings.

    Example:
        # Single command (legacy behavior, unchanged)
        action = send_command_uart(
            name="Read NETINFO",
            port="COM5",
            command="NETINFO",
            baudrate=115200
        )

        # Multiple commands (new functionality)
        actions = send_command_uart(
            name="Run GET_CH on all channels",
            port="COM5",
            command=[f"GET_CH {i}" for i in range(1, 9)],
            baudrate=115200
        )
    """
    def make_execute(cmd):
        def execute():
            resp = send_command(port, cmd, baudrate, timeout)
            _set_last_response(resp)   # store it for later validation
            return resp
        return execute

    if isinstance(command, str):
        return TestAction(name, make_execute(command))
    elif isinstance(command, (list, tuple)):
        actions = []
        for idx, cmd in enumerate(command, start=1):
            actions.append(
                TestAction(f"{name} [{idx}] {cmd}", make_execute(cmd))
            )
        return actions
    else:
        raise TypeError("command must be str or list[str]")


def test_sysinfo_complete(
        name: str,
        port: str,
        validation: Dict[str, Any],
        baudrate: int = 115200
        ) -> TestAction:
    """Create a TestAction that performs complete SYSINFO testing and validation.
    
    This TestAction factory creates an action that sends a SYSINFO command,
    parses the response into structured data, and validates it against
    comprehensive validation rules including firmware format, voltage ranges,
    and frequency expectations.
    
    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier to use for communication.
        validation (Dict[str, Any]): Dictionary containing validation rules:
            - firmware_regex: Regex pattern for firmware version format
            - core_voltage_range: [min, max] voltage range in volts
            - frequencies: Dict of frequency expectations (e.g., sys_hz_min)
        baudrate (int, optional): Serial communication baud rate.
            Defaults to 115200.
            
    Returns:
        TestAction: TestAction that returns the parsed SYSINFO dictionary
            if all validations pass.
            
    Raises:
        SerialTestError: When executed, raises this exception if communication
            fails or if any validation rules fail.
    
    Example:
        >>> validation_rules = {
        ...     "firmware_regex": r"^\d+\.\d+\.\d+$",
        ...     "core_voltage_range": [3.0, 3.6],
        ...     "frequencies": {"sys_hz_min": 100000000}
        ... }
        >>> sysinfo_action = test_sysinfo_complete(
        ...     "Validate system information", "COM3", validation_rules
        ... )
    """
    def execute():
        response = send_command(port, "SYSINFO", baudrate)
        sysinfo = parse_sysinfo_response(response)
        validate_sysinfo_data(sysinfo, validation)
        return sysinfo
    return TestAction(name, execute)


def validate_single_token(
        name: str,
        response: str,
        token: str
        ) -> TestAction:
    """Create a TestAction that validates the presence of a single token.
    
    This TestAction factory creates an action that checks if a specific
    token (substring) is present in the provided response text.
    
    Args:
        name (str): Human-readable name for the test action.
        response (str): Response text to search within.
        token (str): Token (substring) that must be present in the response.
        
    Returns:
        TestAction: TestAction that returns True if the token is found.
        
    Raises:
        SerialTestError: When executed, raises this exception if the token
            is not found in the response.
    
    Example:
        >>> token_action = validate_single_token(
        ...     "Check for HELP command", response_text, "HELP"
        ... )
    """
    def execute():
        if token not in response:
            raise SerialTestError(f"Missing required token: {token}")
        return True
    return TestAction(name, execute)


def validate_tokens(
        name: str,
        response: str,
        tokens: List[str]
        ) -> TestAction:
    """Create a TestAction that validates the presence of multiple tokens.
    
    This TestAction factory creates an action that checks if all specified
    tokens are present in the response text. It uses cached response if
    the response parameter is empty.
    
    Args:
        name (str): Human-readable name for the test action.
        response (str): Response text to search within. If empty, uses
            the last cached response from send_command_uart.
        tokens (List[str]): List of tokens that must all be present.
        
    Returns:
        TestAction: TestAction that returns True if all tokens are found.
        
    Raises:
        SerialTestError: When executed, raises this exception if any tokens
            are missing from the response.
    
    Example:
        >>> tokens_action = validate_tokens(
        ...     "Check for required commands", "", 
        ...     ["HELP", "SYSINFO", "REBOOT", "NETINFO"]
        ... )
    """
    def execute():
        text = _use_response(response)
        missing = [t for t in tokens if t not in text]
        if missing:
            raise SerialTestError(f"Missing required tokens: {', '.join(missing)}")
        return True
    return TestAction(name, execute)


def set_network_parameter(
        name: str,
        port: str,
        param: str,
        value: str,
        baudrate: int = 115200,
        reboot_timeout: float = 10.0
        ) -> TestAction:
    """Create a TestAction that sets network parameters via UART with reboot handling.
    
    This TestAction factory creates an action that sends network configuration
    commands via UART and handles the expected device reboot sequence. It
    supports individual parameter setting (IP, GW, SN, DNS) and bulk
    configuration (CONFIG_NETWORK).
    
    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier to use.
        param (str): Network parameter type to set. Supported values:
            - "IP", "GW", "SN", "DNS": Individual parameters
            - "CONFIG_NETWORK": Bulk configuration (value should be "ip gw sn dns")
        value (str): Value(s) to set. For CONFIG_NETWORK, provide space-separated
            values or "$"-separated values.
        baudrate (int, optional): Serial communication baud rate.
            Defaults to 115200.
        reboot_timeout (float, optional): Maximum time to wait for device
            reboot and ready signal. Defaults to 10.0 seconds.
            
    Returns:
        TestAction: TestAction that returns True when the parameter is set
            and the device is ready.
            
    Raises:
        SerialTestError: When executed, raises this exception if the device
            does not become ready after setting the parameter.
    
    Example:
        >>> ip_action = set_network_parameter(
        ...     "Set device IP", "COM3", "IP", "192.168.1.100"
        ... )
        >>> config_action = set_network_parameter(
        ...     "Configure network", "COM3", "CONFIG_NETWORK", 
        ...     "192.168.1.100 192.168.1.1 255.255.255.0 8.8.8.8"
        ... )
    """
    def _build_command(p: str, v: str) -> str:
        p_up = (p or "").strip().upper()
        v_str = (v or "").strip()

        # If caller already passed a full command, use it verbatim.
        if v_str.startswith(("SET_IP", "SET_GW", "SET_SN", "SET_DNS", "CONFIG_NETWORK")):
            return v_str
        if p_up.startswith(("SET_IP", "SET_GW", "SET_SN", "SET_DNS", "CONFIG_NETWORK")):
            return f"{p_up} {v_str}".strip()

        if p_up in {"IP", "GW", "SN", "DNS"}:
            return f"SET_{p_up} {v_str}"

        if p_up == "CONFIG_NETWORK":
            # Accept either already joined "ip$gw$sn$dns" or four tokens separated by spaces
            if "$" in v_str:
                parts = v_str.split("$")
            else:
                parts = v_str.split()
            if len(parts) != 4:
                raise SerialTestError("CONFIG_NETWORK requires 4 values: ip gw sn dns")
            ip, gw, sn, dns = [x.strip() for x in parts]
            return f"CONFIG_NETWORK {ip}${gw}${sn}${dns}"

        # Fallback: send as-is ("PARAM value")
        return f"{p_up} {v_str}".strip()

    def execute():
        cmd = _build_command(param, value)

        # Send command and expect reboot
        try:
            send_command(port, cmd, baudrate, 1.0)
        except Exception:
            # Connection may drop during reboot; that's expected.
            pass

        # Wait for device ready banner
        if not wait_for_reboot_and_ready(port, "SYSTEM READY", baudrate, reboot_timeout):
            raise SerialTestError(f"Device did not become ready after '{cmd}'")

        return True

    return TestAction(name, execute)


def set_network_parameter_simple(
        name: str,
        port: str,
        param: str,
        value: str,
        baudrate: int = 115200,
        reboot_timeout: float = 10.0
        ) -> TestAction:
    """Create a TestAction for setting network parameters (backward compatibility).
    
    This function is a backward-compatible wrapper for set_network_parameter()
    that provides the same functionality with the same interface.
    
    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier to use.
        param (str): Network parameter type to set.
        value (str): Value to set for the parameter.
        baudrate (int, optional): Serial communication baud rate.
            Defaults to 115200.
        reboot_timeout (float, optional): Device reboot timeout.
            Defaults to 10.0 seconds.
            
    Returns:
        TestAction: TestAction that sets the network parameter.
    """
    return set_network_parameter(name, port, param, value, baudrate, reboot_timeout)


def verify_network_change(
        name: str,
        port: str,
        param: str,
        expected_value: str,
        baudrate: int = 115200
        ) -> TestAction:
    """Create a TestAction that verifies network parameter changes.
    
    This TestAction factory creates an action that sends a NETINFO command
    and verifies that the expected value appears in the response, confirming
    that a network parameter change was successful.
    
    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier to use.
        param (str): Network parameter name being verified (used in error messages).
        expected_value (str): Expected value that should appear in the NETINFO response.
        baudrate (int, optional): Serial communication baud rate.
            Defaults to 115200.
            
    Returns:
        TestAction: TestAction that returns the NETINFO response if
            verification succeeds.
            
    Raises:
        SerialTestError: When executed, raises this exception if the expected
            value is not found in the NETINFO response.
    
    Example:
        >>> verify_action = verify_network_change(
        ...     "Verify IP change", "COM3", "IP", "192.168.1.100"
        ... )
    """
    def execute():
        response = send_command(port, "NETINFO", baudrate)
        if expected_value not in response:
            raise SerialTestError(f"{param} verification failed: {expected_value} not found in NETINFO")
        return response
    return TestAction(name, execute)


def factory_reset_complete(
        name: str,
        port: str,
        baudrate: int = 115200
        ) -> TestAction:
    """Create a TestAction that performs a complete factory reset sequence.
    
    This TestAction factory creates an action that sends an RFS (Reset Factory
    Settings) command, waits for the device to reboot, and verifies that the
    system information is accessible after the reset.
    
    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier to use.
        baudrate (int, optional): Serial communication baud rate.
            Defaults to 115200.
            
    Returns:
        TestAction: TestAction that returns the parsed SYSINFO dictionary
            after successful factory reset.
            
    Raises:
        SerialTestError: When executed, raises this exception if the device
            does not reboot properly or if system information cannot be
            retrieved after reset.
    
    Example:
        >>> reset_action = factory_reset_complete(
        ...     "Perform factory reset", "COM3"
        ... )
    """
    def execute():
        # Send RFS and wait for reboot
        try:
            send_command(port, "RFS", baudrate, 1.0)
        except Exception:
            pass  # Connection drops during reboot

        if not wait_for_reboot_and_ready(port, "SYSTEM READY", baudrate, 10.0):
            raise SerialTestError("Device did not reboot after RFS")

        # Verify system after reset
        response = send_command(port, "SYSINFO", baudrate)
        sysinfo = parse_sysinfo_response(response)
        return sysinfo
    return TestAction(name, execute)


# ======================== EEPROM Dump Helpers ========================

def _read_until_markers(port: str,
                        baudrate: int,
                        command: str,
                        want_start: str,
                        want_end: str,
                        per_read_timeout: float = 1.0,
                        overall_timeout: float = 20.0,
                        read_grace: float = 1.0) -> str:
    """Send command and read until both start and end markers appear.
    
    This internal helper function sends a command and continues reading
    until both start and end markers are detected in the response. It's
    used specifically for EEPROM dump operations that have defined
    start/end boundaries.
    
    Args:
        port (str): Serial port identifier.
        baudrate (int): Serial communication baud rate.
        command (str): Command to send.
        want_start (str): Start marker to wait for.
        want_end (str): End marker to wait for.
        per_read_timeout (float, optional): Per-read timeout. Defaults to 1.0.
        overall_timeout (float, optional): Overall operation timeout. Defaults to 20.0.
        read_grace (float, optional): Grace period after end marker. Defaults to 1.0.
        
    Returns:
        str: Complete captured text including both markers.
    """
    ser = _open_connection(port, baudrate, per_read_timeout)
    logger = get_active_logger()
    try:
        # Send command
        payload = (command.strip() + "\r\n")
        if logger:
            logger.serial_tx(payload)
        ser.write(payload.encode("utf-8"))
        ser.flush()

        # Read loop
        buf = bytearray()
        got_start = False
        got_end = False
        t_end_seen: Optional[float] = None
        deadline = time.time() + max(overall_timeout, 6.0)

        old_timeout = ser.timeout
        ser.timeout = per_read_timeout
        try:
            while time.time() < deadline:
                chunk = ser.read(4096)
                if chunk:
                    buf.extend(chunk)
                    text_so_far = buf.decode("utf-8", errors="replace")

                    if not got_start and (not want_start or want_start in text_so_far):
                        got_start = True

                    if got_start and want_end and want_end in text_so_far and not got_end:
                        got_end = True
                        t_end_seen = time.time()

                if got_end and t_end_seen is not None:
                    if time.time() - t_end_seen >= read_grace:
                        break
            text = buf.decode("utf-8", errors="replace")
            if logger:
                logger.serial_rx(text, note="eeprom-dump")
            return text
        finally:
            ser.timeout = old_timeout
    finally:
        try:
            ser.close()
        finally:
            if logger:
                logger.serial_close(port)


def send_eeprom_dump_command(
        name: str,
        port: str,
        baudrate: int = 115200) -> TestAction:
    """Create a TestAction that captures a complete EEPROM dump with markers.
    
    This TestAction factory creates an action that sends a DUMP_EEPROM command
    and captures the complete response including the EE_DUMP_START and
    EE_DUMP_END markers. The captured data can be used by subsequent
    validation or analysis actions.
    
    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier to use.
        baudrate (int, optional): Serial communication baud rate.
            Defaults to 115200.
            
    Returns:
        TestAction: TestAction that returns the complete EEPROM dump text
            including start and end markers.
    
    Example:
        >>> dump_action = send_eeprom_dump_command(
        ...     "Capture EEPROM dump", "COM3"
        ... )
    """
    def execute():
        # IMPORTANT: capture UNTIL both markers are present, and include them.
        return _read_until_markers(
            port=port,
            baudrate=baudrate,
            command="DUMP_EEPROM",
            want_start="EE_DUMP_START",
            want_end="EE_DUMP_END",
            per_read_timeout=1.0,
            overall_timeout=20.0,
            read_grace=1.0,
        )
    return TestAction(name, execute)


def validate_eeprom_markers(name: str, response: str) -> TestAction:
    """Create a TestAction that validates EEPROM dump markers are present.
    
    This TestAction factory creates an action that verifies both the
    EE_DUMP_START and EE_DUMP_END markers are present in an EEPROM dump
    response, ensuring the dump is complete and properly formatted.
    
    Args:
        name (str): Human-readable name for the test action.
        response (str): EEPROM dump response text to validate.
        
    Returns:
        TestAction: TestAction that returns True if both markers are present.
        
    Raises:
        SerialTestError: When executed, raises this exception if either
            the start or end marker is missing from the response.
    
    Example:
        >>> validate_action = validate_eeprom_markers(
        ...     "Validate EEPROM markers", dump_response
        ... )
    """
    def execute():
        if "EE_DUMP_START" not in response or "EE_DUMP_END" not in response:
            raise SerialTestError("EEPROM dump missing expected markers")
        return True
    return TestAction(name, execute)


def analyze_eeprom_dump(name: str, port: str, baudrate: int, checks: str, reports_dir: Optional[str] = None) -> TestAction:
    """Create a TestAction that performs comprehensive EEPROM dump analysis.
    
    This TestAction factory creates an action that captures an EEPROM dump,
    parses it according to validation rules from a JSON file, and generates
    detailed analysis reports. It integrates with the utilities module to
    handle the actual dump capture and parsing.

    The action performs:
    1. EEPROM dump capture via utilities.parse_eeprom_data()
    2. Validation rules loading from JSON file
    3. ASCII hexdump parsing into byte arrays
    4. Validation execution (ascii/hex, pattern/regex/expect/contains)
    5. Summary report generation

    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier (e.g., "COM10").
        baudrate (int): Serial communication baud rate.
        checks (str): Path to JSON file containing validation rules.
        reports_dir (Optional[str]): Base directory for reports. If None,
            uses the active logger's directory or falls back to TestCases/Reports.

    Returns:
        TestAction: TestAction that returns a dictionary containing analysis
            results including file paths, address ranges, and validation findings.
    
    Example:
        >>> analysis_action = analyze_eeprom_dump(
        ...     "Analyze EEPROM content", "COM3", 115200, 
        ...     "eeprom_checks.json"
        ... )
        >>> results = analysis_action.execute()
        >>> print(results['summary_path'])
    """
    def execute():
        import json
        import re
        import inspect
        from pathlib import Path
        from ...core import utilities
        from ...core.logger import get_active_logger

        def _find_testcases_root() -> Path:
            """Return nearest 'TestCases' directory from stack or CWD."""
            for frame in inspect.stack():
                try:
                    p = Path(frame.filename).resolve()
                except Exception:
                    continue
                for anc in (p, *p.parents):
                    if anc.name.lower() == "testcases":
                        return anc
            cwd = Path.cwd().resolve()
            for anc in (cwd, *cwd.parents):
                if anc.name.lower() == "testcases":
                    return anc
            return Path.cwd().resolve()

        class _LocalError(Exception):
            """Internal parsing/validation error."""

        def _to_int(x, default=None):
            if x is None:
                return default
            if isinstance(x, int):
                return x
            s = str(x).strip()
            if s.lower().startswith("0x"):
                return int(s, 16)
            return int(s)

        def _fmt_hex_bytes(b: bytes) -> str:
            return " ".join(f"{x:02X}" for x in b)

        # ---- Resolve save_dir to align with the active reporter (preferred) ----
        logger = get_active_logger()
        if logger is not None and hasattr(logger, 'log_file') and logger.log_file:
            base_reports = logger.log_file.parent
        elif reports_dir:
            base_reports = Path(reports_dir)
        else:
            # Legacy fallback: <TestCases>/Reports/<testcase>
            stack = inspect.stack()
            testcase_file = None
            for frame in stack:
                fn = Path(frame.filename)
                if fn.name.startswith("tc_") and fn.suffix == ".py":
                    testcase_file = fn
                    break
            if testcase_file is None:
                testcase_file = Path(__file__)
            testcase_name = testcase_file.stem
            base_reports = (_find_testcases_root() / "Reports" / testcase_name)

        save_dir = base_reports / "EEPROM"
        save_dir.mkdir(parents=True, exist_ok=True)

        # 1) Run helper to capture raw/ascii dumps (over serial)
        parsed = utilities.parse_eeprom_data(port=port, baudrate=baudrate, save_to_dir=str(save_dir))
        ascii_text = (parsed.get("ascii") or "").replace("\r\n", "\n").replace("\r", "\n")
        raw_path = save_dir / "eeprom_dump_raw.log"
        ascii_path = save_dir / "eeprom_dump_ascii.log"

        if not ascii_text.strip():
            if ascii_path.exists():
                ascii_text = ascii_path.read_text(encoding="utf-8")
            if not ascii_text.strip():
                raise SerialTestError("ASCII EEPROM dump is empty after helper processing.")

        # 2) Load checks JSON
        checks_path = Path(checks)
        if not checks_path.exists():
            raise FileNotFoundError(f"Checks JSON not found: {checks_path}")
        with checks_path.open("r", encoding="utf-8") as cf:
            check_list = json.load(cf)
        if not isinstance(check_list, list):
            raise ValueError("Checks JSON must be a list of check objects.")

        # 3) Parse ASCII hexdump into rows and contiguous image
        hex_line_pat = re.compile(
            r"^\s*(0x[0-9A-Fa-f]{4,})\s+((?:[0-9A-Fa-f]{2}\s+){15}[0-9A-Fa-f]{2})\s+\|.*\|\s*$"
        )
        lines = [ln for ln in ascii_text.split("\n") if ln.strip()]
        rows = []
        for ln in lines:
            m = hex_line_pat.match(ln)
            if not m:
                continue
            addr_s, hex_block = m.groups()
            addr = int(addr_s, 16)
            data = bytes(int(bt, 16) for bt in hex_block.split())
            if len(data) != 16:
                continue
            rows.append((addr, data))
        if not rows:
            raise SerialTestError("No valid hexdump rows recognized in ASCII dump.")

        min_addr = min(a for a, _ in rows)
        max_addr = max(a + len(b) - 1 for a, b in rows)
        image = bytearray([0xFF] * (max_addr + 1))
        for a, b in rows:
            image[a:a+len(b)] = b

        # 4) Execute checks
        findings = []

        def _slice(addr_start: int, length: int = None, addr_end: int = None) -> bytes:
            if addr_end is not None and length is None:
                if addr_end < addr_start:
                    raise _LocalError("end < start in check")
                length = addr_end - addr_start + 1
            if length is None:
                raise _LocalError("either length or end must be provided")
            s = max(0, min(addr_start, len(image)))
            e = max(0, min(addr_start + length, len(image)))
            return bytes(image[s:e])

        for idx, chk in enumerate(check_list, 1):
            try:
                label = str(chk.get("label", f"check_{idx}"))
                start = _to_int(chk.get("start"))
                end = _to_int(chk.get("end"))
                length = _to_int(chk.get("length"))
                typ = (chk.get("type") or "ascii").lower()
                regex = chk.get("regex")
                pattern = chk.get("pattern")
                expect = chk.get("expect")
                contains = chk.get("contains")
                trim_nul = bool(chk.get("trim_nul", typ == "ascii"))

                if start is None:
                    raise _LocalError("missing 'start'")
                buf = _slice(start, length, end)

                if typ == "ascii":
                    if trim_nul and b"\x00" in buf:
                        buf = buf[:buf.index(b"\x00")]
                    try:
                        s = buf.decode("utf-8", errors="ignore")
                    except Exception:
                        s = "".join(chr(c) if 32 <= c <= 126 else "." for c in buf)

                    status, notes = "OK", []
                    if pattern and pattern not in s:
                        status, notes = "MISS", notes + [f"pattern '{pattern}' not found"]
                    if regex and not re.search(regex, s):
                        status, notes = "MISS", notes + [f"regex '{regex}' not matched"]
                    if isinstance(expect, str) and expect != "" and s != expect:
                        status, notes = "MISS", notes + ["exact string mismatch"]
                    findings.append({
                        "label": label, "type": "ascii", "addr": f"0x{start:04X}",
                        "length": len(buf), "value": s, "status": status,
                        "notes": "; ".join(notes) if notes else ""
                    })

                elif typ == "hex":
                    hex_str = _fmt_hex_bytes(buf)
                    status, notes = "OK", []
                    if isinstance(expect, str) and expect.strip():
                        exp_bytes = bytes(int(b, 16) for b in expect.split())
                        if buf != exp_bytes:
                            status, notes = "MISS", notes + ["expect mismatch"]
                    if isinstance(contains, str) and contains.strip():
                        sub = bytes(int(b, 16) for b in contains.split())
                        if sub not in buf:
                            status, notes = "MISS", notes + [f"missing subsequence {contains}"]
                    findings.append({
                        "label": label, "type": "hex", "addr": f"0x{start:04X}",
                        "length": len(buf), "value": hex_str, "status": status,
                        "notes": "; ".join(notes) if notes else ""
                    })
                else:
                    raise _LocalError(f"unknown type '{typ}'")

            except Exception as e:
                findings.append({
                    "label": chk.get("label", f"check_{idx}"),
                    "type": chk.get("type", "?"),
                    "addr": chk.get("start", "?"),
                    "length": chk.get("length", "?"),
                    "value": "",
                    "status": "ERROR",
                    "notes": str(e),
                })

        # 5) Write summary
        summary_path = save_dir / "eeprom_summary.txt"
        with summary_path.open("w", encoding="utf-8") as sf:
            sf.write(f"EEPROM Parse Summary – {name}\n")
            sf.write(f"Source lines parsed: {len(rows)}\n")
            sf.write(f"Address span: 0x{min_addr:04X} – 0x{max_addr:04X} ({max_addr - min_addr + 1} bytes)\n")
            sf.write(f"Dump (raw)   : {raw_path.name if raw_path.exists() else '<missing>'}\n")
            sf.write(f"Dump (ascii) : {ascii_path.name if ascii_path.exists() else '<missing>'}\n")
            sf.write(f"Checks file  : {checks_path.name}\n")
            sf.write("\n-- Findings --\n")
            for item in findings:
                sf.write(f"[{item['status']}] {item['label']} @ {item['addr']} len={item['length']}\n")
                if item["type"] == "ascii":
                    sf.write(f"    ASCII: {item['value']}\n")
                else:
                    sf.write(f"    HEX  : {item['value']}\n")
                if item["notes"]:
                    sf.write(f"    Notes: {item['notes']}\n")
            def _get(label):
                for it in findings:
                    if "label" in it and it["label"] == label:
                        return it
                return None
            sn = _get("Device Serial"); ver = _get("FW Version")
            dn = _get("Device Name"); dl = _get("Device Location")
            sf.write("\n-- Extracted --\n")
            if sn: sf.write(f"Serial  : {sn.get('value','')}\n")
            if ver: sf.write(f"Firmware: {ver.get('value','')}\n")
            if dn:  sf.write(f"Name    : {dn.get('value','')}\n")
            if dl:  sf.write(f"Location: {dl.get('value','')}\n")

        return {
            "raw_path": str(raw_path) if raw_path.exists() else "",
            "ascii_path": str(ascii_path) if ascii_path.exists() else "",
            "summary_path": str(summary_path),
            "min_addr": min_addr,
            "max_addr": max_addr,
            "findings": findings,
        }

    return TestAction(name, execute)


def load_eeprom_checks_from_json(json_path: str) -> list:
    """Load EEPROM validation checks from a JSON file.
    
    This utility function loads and validates an EEPROM checks configuration
    file that defines validation rules for EEPROM content analysis.

    Args:
        json_path (str): Path to the JSON file containing EEPROM validation checks.

    Returns:
        list: List of check dictionaries loaded from the JSON file.
        
    Raises:
        FileNotFoundError: If the JSON file cannot be found.
        ValueError: If the JSON file doesn't contain a list of checks.
    
    Example:
        >>> checks = load_eeprom_checks_from_json("eeprom_checks.json")
        >>> print(len(checks))
        5
    """
    import json
    from pathlib import Path

    p = Path(json_path)
    if not p.exists():
        raise FileNotFoundError(f"Checks JSON not found: {json_path}")
    with p.open("r", encoding="utf-8") as f:
        checks = json.load(f)
    if not isinstance(checks, list):
        raise ValueError("Checks JSON must be a list of check objects.")
    return checks
