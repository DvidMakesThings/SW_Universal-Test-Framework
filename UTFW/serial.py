# serial.py
"""
UTFW Serial Module
==================
High-level serial/UART test functions for universal testing

Author: DvidMakesThings
"""

import time
import re
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any, Union

from .reporting import get_active_reporter  # (added) for detailed TX/RX logging


# at top of serial.py (where you added EEPROM helpers)
_LAST_RESPONSE: Optional[str] = None

def _set_last_response(text: str) -> None:
    global _LAST_RESPONSE
    _LAST_RESPONSE = text

def _use_response(explicit: str) -> str:
    if explicit:
        return explicit
    if _LAST_RESPONSE:
        return _LAST_RESPONSE
    raise SerialTestError("No response available. Provide `response` explicitly or call send_* first.")


class SerialTestError(Exception):
    """Serial test specific error"""
    pass


class TestAction:
    """Test action that can be executed"""
    def __init__(self, name: str, execute_func):
        self.name = name
        self.execute_func = execute_func


def _ensure_pyserial():
    """Ensure pyserial is available"""
    try:
        import serial
    except ImportError:
        raise ImportError("pyserial is required. Install with: pip install pyserial")


def _open_connection(port: str, baudrate: int = 115200, timeout: float = 2.0):
    """Open serial connection"""
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

        # Added: log serial open
        rep = get_active_reporter()
        if rep:
            rep.log_serial_open(port, baudrate)

        return ser
    except Exception as e:
        raise SerialTestError(f"Failed to open serial port {port}: {e}")


def send_command(port: str, command: str, baudrate: int = 115200, timeout: float = 2.0) -> str:
    """Send command via serial and return response"""
    ser = _open_connection(port, baudrate, timeout)
    rep = get_active_reporter()
    
    try:
        # Send command
        payload = (command.strip() + "\r\n")
        if rep:
            rep.log_serial_tx(payload)
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
        if rep:
            rep.log_serial_rx(text)
        return text
        
    finally:
        try:
            ser.close()
        finally:
            # Added: log serial close
            if rep:
                rep.log_serial_close(port)


def wait_for_reboot_and_ready(port: str, ready_token: str = "SYSTEM READY", 
                             baudrate: int = 115200, timeout: float = 10.0) -> bool:
    """Wait for device to reboot and show ready signal"""
    _ensure_pyserial()
    import serial
    
    deadline = time.time() + timeout
    time.sleep(0.2)  # Give device time to start rebooting
    rep = get_active_reporter()
    
    while time.time() < deadline:
        try:
            ser = serial.Serial(port=port, baudrate=baudrate, timeout=1.0)
            try:
                time.sleep(0.1)
                remaining_time = max(0.5, deadline - time.time())
                response_bytes = bytearray()
                read_deadline = time.time() + min(remaining_time, 2.0)
                
                while time.time() < read_deadline:
                    if ser.in_waiting > 0:
                        chunk = ser.read(ser.in_waiting)
                        response_bytes.extend(chunk)
                    time.sleep(0.05)
                
                response = response_bytes.decode('utf-8', errors='ignore')

                # Added: log reconnect RX preview
                if rep and response:
                    rep.log_serial_rx(response, note="reconnect")
                
                if ready_token.lower() in response.lower():
                    return True
                    
            finally:
                try:
                    ser.close()
                finally:
                    if rep:
                        rep.log_serial_close(port)
                
        except Exception:
            pass
            
        time.sleep(0.2)
    
    return False


def parse_sysinfo_response(response: str) -> Dict[str, str]:
    """Parse SYSINFO response into key-value dict"""
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
    """Validate SYSINFO data against validation rules"""
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
    """
    Parse a multi-line response of 'GET_CH ALL' into a channel->state map.

    Expected input example:
        [ECHO] Received CMD: "GET_CH ALL"
        [ECHO] CH1: OFF
        [ECHO] CH2: OFF
        ...
        [ECHO] CH8: OFF

    Returns:
        Dict[int, bool]: {1: False, 2: False, ..., 8: False} (True for ON)
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

#################################################################################################################
#                                       TESTACTION FACTORIES
#################################################################################################################

def wait_for_reboot(
        name: str, 
        port: str, 
        banner: str = "SYSTEM READY",
        baudrate: int = 115200, 
        timeout: float = 15.0
        ) -> "TestAction":
    """
    Wait for device reboot and the READY banner over UART, as a TestAction.

    Internally calls the existing reboot-wait helper and wraps it so it can be
    scheduled directly inside STE(...) without defining any extra functions in
    the test file.

    Args:
        name (str): Step name shown in the report (e.g., "Wait for reboot & SYSTEM READY").
        port (str): Serial port (e.g., "COM11", "/dev/ttyACM0").
        banner (str): Ready marker to wait for (default: "SYSTEM READY").
        baudrate (int): UART baud rate (default: 115200).
        timeout (float): Overall wait budget in seconds (default: 15.0).

    Returns:
        TestAction: Returns True when the banner is observed within the timeout.

    Raises:
        SerialTestError: If the device does not become ready within the timeout
                         or any serial error occurs.
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
    """
    Validate that the parsed 'GET_CH ALL' response matches the expected states.

    Args:
        name: Test action name.
        response: Full text to parse (or leave empty "" to use last cached response).
        expected:
            - bool            -> all 8 channels must be this state
            - List[bool]      -> len == 8, channel i -> expected[i-1]
            - Dict[int, bool] -> per-channel expectation (1..8). Missing keys are ignored.

    Raises:
        SerialTestError on mismatch with a detailed diff.
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
    """
    Send "GET_CH ALL" over UART, parse the response into channel states, and
    optionally validate against expected values.

    The device returns lines like:
        [ECHO] Received CMD: "GET_CH ALL"
        [ECHO] CH1: ON
        [ECHO] CH2: OFF
        ...
        [ECHO] CH8: OFF

    Args:
        name (str):
            Name of the test action.
        port (str):
            Serial port to use (e.g. "COM5" or "/dev/ttyACM0").
        expected (optional):
            - None (default): Only parse and return states, no validation.
            - bool: Require all 8 channels to be this state.
                True  -> all must be ON
                False -> all must be OFF
            - List[bool]: A list of 8 booleans, one per channel.
                Example: [True, False, ..., True] → CH1=ON, CH2=OFF, ..., CH8=ON
            - Dict[int,bool]: Explicit mapping {channel_number: state}.
                Example: {1: True, 3: False} → require CH1=ON, CH3=OFF;
                other channels are ignored.
        baudrate (int, optional):
            Baud rate for serial communication. Defaults to 115200.
        timeout (float, optional):
            Timeout for reading the response. Defaults to 2.0 seconds.

    Returns:
        TestAction:
            On execution, sends "GET_CH ALL" and returns a dict:
                {1: bool, 2: bool, ..., 8: bool}
            where each bool is True for ON, False for OFF.

    Raises:
        SerialTestError:
            If validation fails when `expected` is provided.
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
    """
    Creates one or more TestActions that send command(s) via UART/serial and return the response(s).

    This function is flexible:  
    - If a **string** is provided for `command`, it behaves exactly like the original
      `send_command_uart` and returns a single TestAction.  
    - If a **list of strings** is provided, it returns a list of TestActions, each
      corresponding to one command in the list.  

    When executed, each action sends the specified command to the device via UART,
    captures the response, and stores it for later validation.

    Args:
        name (str): 
            Base name of the test action(s). If multiple commands are provided, 
            the name is suffixed with an index and the actual command for clarity.
        port (str): 
            Serial port to use (e.g., "COM3" or "/dev/ttyACM0").
        command (str | list[str]): 
            The command (or list of commands) to send.
        baudrate (int, optional): 
            Baud rate for serial communication. Defaults to 115200.
        timeout (float, optional): 
            Timeout in seconds to wait for a response. Defaults to 2.0 seconds.

    Returns:
        TestAction | list[TestAction]:
            - A single TestAction if `command` is a string.  
            - A list of TestActions if `command` is a list of strings.  

    Raises:
        TypeError: If `command` is neither a string nor a list/tuple of strings.

    Usage Examples:
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

    Notes:
        - The last response is cached globally for use with later validation 
          functions such as `Serial.validate_tokens`.
        - Use descriptive `name` values to make log outputs clear, especially 
          when sending multiple commands.
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
    """
    Creates a TestAction that performs a complete SYSINFO test.
    When executed, this action sends the SYSINFO command, parses the response, and validates the data against provided rules.
    Args:
        name (str): Name of the test action.
        port (str): Serial port to use.
        validation (Dict[str, Any]): Validation rules for SYSINFO data.
        baudrate (int, optional): Baud rate for serial communication. Defaults to 115200.
    Returns:
        TestAction: Action to perform SYSINFO test and validation.
    Raises:
        SerialTestError: If validation fails.
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
    """
    Creates a TestAction that validates the presence of a single token in a response.
    When executed, this action checks if the specified token is present in the response string.
    Args:
        name (str): Name of the test action.
        response (str): Response text to check.
        token (str): Token to validate.
    Returns:
        TestAction: Action to validate the token.
    Raises:
        SerialTestError: If the token is missing.
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
    """
    Creates a TestAction that validates the presence of multiple tokens in a response.
    When executed, this action checks if all specified tokens are present in the response string.
    Args:
        name (str): Name of the test action.
        response (str): Response text to check (or uses last response if empty).
        tokens (List[str]): List of tokens to validate.
    Returns:
        TestAction: Action to validate all tokens.
    Raises:
        SerialTestError: If any token is missing.
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
    """
    Creates a TestAction that sets a network parameter (IP, GW, SN, DNS, or CONFIG_NETWORK) via UART/serial.
    When executed, this action sends the appropriate command to set the network parameter and waits for device reboot and ready signal.
    Args:
        name (str): Name of the test action.
        port (str): Serial port to use.
        param (str): Network parameter to set (IP, GW, SN, DNS, CONFIG_NETWORK).
        value (str): Value to set for the parameter.
        baudrate (int, optional): Baud rate for serial communication. Defaults to 115200.
        reboot_timeout (float, optional): Timeout for device reboot. Defaults to 10.0 seconds.
    Returns:
        TestAction: Action to set the network parameter and verify device readiness.
    Raises:
        SerialTestError: If device does not become ready after setting parameter.
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
    """
    Backward-compatible wrapper for set_network_parameter().
    Returns a TestAction that sets a network parameter using the main function.
    """
    return set_network_parameter(name, port, param, value, baudrate, reboot_timeout)

def verify_network_change(
        name: str, 
        port: str, 
        param: str, 
        expected_value: str,
        baudrate: int = 115200
        ) -> TestAction:
    """
    Creates a TestAction that verifies a network parameter change via UART/serial.
    When executed, this action sends the NETINFO command and checks if the expected value is present in the response.
    Args:
        name (str): Name of the test action.
        port (str): Serial port to use.
        param (str): Network parameter to verify.
        expected_value (str): Expected value to find in NETINFO response.
        baudrate (int, optional): Baud rate for serial communication. Defaults to 115200.
    Returns:
        TestAction: Action to verify the network change.
    Raises:
        SerialTestError: If expected value is not found in response.
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
    """
    Creates a TestAction that performs a complete factory reset via UART/serial.
    When executed, this action sends the RFS command, waits for device reboot, and verifies system info after reset.
    Args:
        name (str): Name of the test action.
        port (str): Serial port to use.
        baudrate (int, optional): Baud rate for serial communication. Defaults to 115200.
    Returns:
        TestAction: Action to perform factory reset and verify system info.
    Raises:
        SerialTestError: If device does not reboot or system info validation fails.
    """
    def execute():
        # Send RFS and wait for reboot
        try:
            send_command(port, "RFS", baudrate, 1.0)
        except:
            pass  # Connection drops during reboot
        
        if not wait_for_reboot_and_ready(port, "SYSTEM READY", baudrate, 10.0):
            raise SerialTestError("Device did not reboot after RFS")
        
        # Verify system after reset
        response = send_command(port, "SYSINFO", baudrate)
        sysinfo = parse_sysinfo_response(response)
        return sysinfo
    return TestAction(name, execute)


# -------------------- EEPROM dump helpers (added, no deletions) --------------------

def _read_until_markers(port: str,
                        baudrate: int,
                        command: str,
                        want_start: str,
                        want_end: str,
                        per_read_timeout: float = 1.0,
                        overall_timeout: float = 20.0,
                        read_grace: float = 1.0) -> str:
    """
    Send `command` and read until both `want_start` and `want_end` markers appear.
    Returns the entire captured text INCLUDING markers.
    """
    ser = _open_connection(port, baudrate, per_read_timeout)
    rep = get_active_reporter()
    try:
        # Send command
        payload = (command.strip() + "\r\n")
        if rep:
            rep.log_serial_tx(payload)
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
            if rep:
                rep.log_serial_rx(text, note="eeprom-dump")
            return text
        finally:
            ser.timeout = old_timeout
    finally:
        try:
            ser.close()
        finally:
            if rep:
                rep.log_serial_close(port)


def send_eeprom_dump_command(
        name: str, 
        port: str, 
        baudrate: int = 115200) -> TestAction:
    """
    Creates a TestAction that sends the EEPROM dump command via UART/serial and captures the full dump including markers.
    When executed, this action sends the DUMP_EEPROM command and reads until both EE_DUMP_START and EE_DUMP_END markers are present.
    Args:
        name (str): Name of the test action.
        port (str): Serial port to use.
        baudrate (int, optional): Baud rate for serial communication. Defaults to 115200.
    Returns:
        TestAction: Action to send EEPROM dump command and capture output.
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
    """
    Creates a TestAction that validates the presence of EEPROM dump start and end markers in a response.
    When executed, this action checks if both EE_DUMP_START and EE_DUMP_END markers are present in the response.
    Args:
        name (str): Name of the test action.
        response (str): EEPROM dump response to check.
    Returns:
        TestAction: Action to validate EEPROM dump markers.
    Raises:
        SerialTestError: If either marker is missing.
    """
    def execute():
        if "EE_DUMP_START" not in response or "EE_DUMP_END" not in response:
            raise SerialTestError("EEPROM dump missing expected markers")
        return True
    return TestAction(name, execute)


def analyze_eeprom_dump(name: str, port: str, baudrate: int, checks: str, reports_dir: Optional[str] = None) -> TestAction:
    """Capture, parse, and validate an EEPROM dump; write artifacts under the active report directory.

    This action:
      1) Runs the helper via `utilities.parse_eeprom_data(port, baudrate, save_to_dir=...)`
      2) Loads checks from a JSON file path (`checks`)
      3) Parses the ASCII hexdump into a contiguous byte image
      4) Executes validations (ascii/hex, pattern/regex/expect/contains)
      5) Writes 'eeprom_summary.txt' under '<reports_dir>/EEPROM'
      6) Returns paths and findings

    Args:
        name: Step name.
        port: Serial port (e.g., "COM10").
        baudrate: Serial baudrate (e.g., 115200).
        checks: Path to `eeprom_checks.json`.
        reports_dir: Optional base reports directory. If omitted, uses the active reporter's
            directory when available; otherwise falls back to the legacy TestCases/Reports path.

    Returns:
        TestAction: Executable test action.
    """
    def execute():
        import json
        import re
        import inspect
        from pathlib import Path
        from . import utilities
        from .reporting import get_active_reporter

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
        rep = get_active_reporter()
        if rep is not None:
            base_reports = Path(rep.reports_dir)
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
    """
    Helper to load EEPROM 'checks' from a JSON file.

    Args:
        json_path (str): Path to eeprom_checks.json

    Returns:
        list: Parsed checks list
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
