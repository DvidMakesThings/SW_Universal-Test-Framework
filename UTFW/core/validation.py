"""
UTFW Validation Module
======================
High-level validation and regex test functions for universal testing

This module provides comprehensive validation utilities for test data
including regex matching, numeric range validation, string comparisons,
and specialized validators for common data types like IP addresses,
MAC addresses, and firmware versions.

Author: DvidMakesThings
"""

import re
from typing import Any, List, Dict, Optional, Union


class ValidationTestError(Exception):
    """Exception raised when validation tests fail.
    
    This exception is raised by validation functions when the tested
    data does not meet the specified criteria. It includes descriptive
    error messages to help identify what validation failed.
    
    Args:
        message (str): Description of the validation failure.
    """
    pass


def test_regex_match(text: str, pattern: str, description: str = "") -> bool:
    """Test if text matches a regex pattern from the beginning.
    
    This function uses re.match() to test if the entire text matches
    the provided regex pattern from the start. Use test_regex_search()
    if you need to find the pattern anywhere within the text.
    
    Args:
        text (str): Text to test against the pattern.
        pattern (str): Regular expression pattern to match.
        description (str, optional): Optional description for error messages
            to provide context about what is being validated.
        
    Returns:
        bool: True if the text matches the pattern.
        
    Raises:
        ValidationTestError: If the pattern doesn't match or if the
            regex pattern is invalid.
    
    Example:
        >>> test_regex_match("192.168.1.1", r"^\\d+\\.\\d+\\.\\d+\\.\\d+$", "IP address")
        True
        >>> test_regex_match("invalid", r"^\\d+\\.\\d+\\.\\d+\\.\\d+$", "IP address")
        ValidationTestError: Regex match failed (IP address): 'invalid' does not match '^\\d+\\.\\d+\\.\\d+\\.\\d+$'
    """
    try:
        if not re.match(pattern, text):
            desc_part = f" ({description})" if description else ""
            raise ValidationTestError(f"Regex match failed{desc_part}: '{text}' does not match '{pattern}'")
        return True
    except re.error as e:
        raise ValidationTestError(f"Invalid regex pattern '{pattern}': {e}")


def test_regex_search(text: str, pattern: str, description: str = "") -> bool:
    """Test if text contains a regex pattern anywhere within it.
    
    This function uses re.search() to find the pattern anywhere within
    the text. Use test_regex_match() if you need the entire text to
    match the pattern from the beginning.
    
    Args:
        text (str): Text to search for the pattern.
        pattern (str): Regular expression pattern to find.
        description (str, optional): Optional description for error messages
            to provide context about what is being validated.
        
    Returns:
        bool: True if the pattern is found in the text.
        
    Raises:
        ValidationTestError: If the pattern is not found or if the
            regex pattern is invalid.
    
    Example:
        >>> test_regex_search("Device IP: 192.168.1.1", r"\\d+\\.\\d+\\.\\d+\\.\\d+", "IP in text")
        True
        >>> test_regex_search("No IP here", r"\\d+\\.\\d+\\.\\d+\\.\\d+", "IP in text")
        ValidationTestError: Regex search failed (IP in text): '\\d+\\.\\d+\\.\\d+\\.\\d+' not found in 'No IP here'
    """
    try:
        if not re.search(pattern, text):
            desc_part = f" ({description})" if description else ""
            raise ValidationTestError(f"Regex search failed{desc_part}: '{pattern}' not found in '{text}'")
        return True
    except re.error as e:
        raise ValidationTestError(f"Invalid regex pattern '{pattern}': {e}")


def test_numeric_range(value: Union[str, int, float], min_val: float, max_val: float,
                      description: str = "") -> bool:
    """Test if a numeric value falls within a specified range.
    
    This function can handle numeric values provided as strings, integers,
    or floats. For strings, it attempts to extract the first numeric value
    found using regex pattern matching.
    
    Args:
        value (Union[str, int, float]): Value to test. Can be a number or
            a string containing a numeric value.
        min_val (float): Minimum allowed value (inclusive).
        max_val (float): Maximum allowed value (inclusive).
        description (str, optional): Optional description for error messages.
        
    Returns:
        bool: True if the value is within the specified range.
        
    Raises:
        ValidationTestError: If the value is out of range, cannot be parsed
            as a number, or is invalid.
    
    Example:
        >>> test_numeric_range("3.3V", 3.0, 3.6, "core voltage")
        True
        >>> test_numeric_range(2.5, 3.0, 3.6, "core voltage")
        ValidationTestError: Value out of range (core voltage): 2.5 not in [3.0, 3.6]
    """
    try:
        # Convert to float if string
        if isinstance(value, str):
            # Try to extract numeric value from string
            numeric_match = re.search(r'[-+]?\d*\.?\d+', value)
            if not numeric_match:
                raise ValidationTestError(f"No numeric value found in: '{value}'")
            numeric_value = float(numeric_match.group(0))
        else:
            numeric_value = float(value)
        
        if not (min_val <= numeric_value <= max_val):
            desc_part = f" ({description})" if description else ""
            raise ValidationTestError(
                f"Value out of range{desc_part}: {numeric_value} not in [{min_val}, {max_val}]"
            )
        
        return True
        
    except (ValueError, TypeError) as e:
        raise ValidationTestError(f"Invalid numeric value: {value} ({e})")


def test_exact_match(actual: str, expected: str, description: str = "") -> bool:
    """Test for exact string equality.
    
    This function performs case-sensitive exact string comparison between
    the actual and expected values.
    
    Args:
        actual (str): The actual value to compare.
        expected (str): The expected value to match against.
        description (str, optional): Optional description for error messages.
        
    Returns:
        bool: True if the strings match exactly.
        
    Raises:
        ValidationTestError: If the strings do not match exactly.
    
    Example:
        >>> test_exact_match("PASS", "PASS", "test result")
        True
        >>> test_exact_match("pass", "PASS", "test result")
        ValidationTestError: Exact match failed (test result): expected 'PASS', got 'pass'
    """
    if actual != expected:
        desc_part = f" ({description})" if description else ""
        raise ValidationTestError(f"Exact match failed{desc_part}: expected '{expected}', got '{actual}'")
    
    return True


def test_contains_all(text: str, required_items: List[str], description: str = "") -> bool:
    """Test that text contains all required items.
    
    This function checks that all items in the required_items list are
    present as substrings within the provided text. The search is
    case-sensitive.
    
    Args:
        text (str): Text to search within.
        required_items (List[str]): List of strings that must all be present.
        description (str, optional): Optional description for error messages.
        
    Returns:
        bool: True if all required items are found in the text.
        
    Raises:
        ValidationTestError: If any required items are missing from the text.
    
    Example:
        >>> test_contains_all("HELP SYSINFO REBOOT", ["HELP", "SYSINFO"], "commands")
        True
        >>> test_contains_all("HELP REBOOT", ["HELP", "SYSINFO"], "commands")
        ValidationTestError: Missing required items (commands): ['SYSINFO']
    """
    missing_items = []
    for item in required_items:
        if item not in text:
            missing_items.append(item)
    
    if missing_items:
        desc_part = f" ({description})" if description else ""
        raise ValidationTestError(f"Missing required items{desc_part}: {missing_items}")
    
    return True


def test_key_value_pairs(text: str, expected_pairs: Dict[str, Union[str, re.Pattern]],
                        separators: List[str] = None, description: str = "") -> Dict[str, str]:
    """Test and extract key-value pairs from text.
    
    This function parses key-value pairs from multi-line text and validates
    them against expected values. Expected values can be exact strings or
    compiled regex patterns for flexible matching.
    
    Args:
        text (str): Multi-line text containing key-value pairs.
        expected_pairs (Dict[str, Union[str, re.Pattern]]): Dictionary mapping
            keys to expected values. Values can be strings (for exact match
            or regex pattern) or compiled regex Pattern objects.
        separators (List[str], optional): List of separators to try when
            parsing key-value pairs. Defaults to [":", "="].
        description (str, optional): Optional description for error messages.
        
    Returns:
        Dict[str, str]: Dictionary of all parsed key-value pairs from the text.
        
    Raises:
        ValidationTestError: If any expected keys are missing or if values
            don't match the expected patterns.
    
    Example:
        >>> text = "Device: ENERGIS\\nVersion: 1.2.3\\nStatus: OK"
        >>> expected = {"Device": "ENERGIS", "Version": r"\\d+\\.\\d+\\.\\d+"}
        >>> result = test_key_value_pairs(text, expected)
        {'Device': 'ENERGIS', 'Version': '1.2.3', 'Status': 'OK'}
    """
    if separators is None:
        separators = [":", "="]
    
    # Parse key-value pairs
    parsed_pairs = {}
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        for sep in separators:
            if sep in line:
                key, value = line.split(sep, 1)
                parsed_pairs[key.strip()] = value.strip()
                break
    
    # Validate expected pairs
    failures = []
    for key, expected in expected_pairs.items():
        if key not in parsed_pairs:
            failures.append(f"Missing key: '{key}'")
            continue
        
        actual_value = parsed_pairs[key]
        
        if isinstance(expected, re.Pattern):
            # Compiled regex pattern
            if not expected.match(actual_value):
                failures.append(f"Key '{key}': '{actual_value}' does not match pattern")
        elif isinstance(expected, str):
            # String comparison (can contain regex)
            try:
                if not re.match(expected, actual_value):
                    failures.append(f"Key '{key}': '{actual_value}' does not match '{expected}'")
            except re.error:
                # If regex is invalid, do exact string comparison
                if actual_value != expected:
                    failures.append(f"Key '{key}': expected '{expected}', got '{actual_value}'")
        else:
            # Direct comparison
            if str(actual_value) != str(expected):
                failures.append(f"Key '{key}': expected '{expected}', got '{actual_value}'")
    
    if failures:
        desc_part = f" ({description})" if description else ""
        raise ValidationTestError(f"Key-value validation failed{desc_part}: {'; '.join(failures)}")
    
    return parsed_pairs


def test_firmware_version(version_string: str, expected_format: str = r"^\d+\.\d+\.\d+(?:[-+].*)?$") -> bool:
    """Test firmware version string format.
    
    This function validates that a firmware version string matches the
    expected semantic versioning format. The default pattern expects
    major.minor.patch format with optional pre-release or build metadata.
    
    Args:
        version_string (str): Version string to validate.
        expected_format (str, optional): Regex pattern for expected format.
            Defaults to semantic versioning pattern.
        
    Returns:
        bool: True if the version format is valid.
        
    Raises:
        ValidationTestError: If the version format is invalid.
    
    Example:
        >>> test_firmware_version("1.2.3")
        True
        >>> test_firmware_version("1.2.3-beta")
        True
        >>> test_firmware_version("invalid")
        ValidationTestError: Regex match failed (firmware version): 'invalid' does not match '^\\d+\\.\\d+\\.\\d+(?:[-+].*)?$'
    """
    return test_regex_match(version_string, expected_format, "firmware version")


def test_ip_address(ip_string: str, description: str = "") -> bool:
    """Test IPv4 address format validation.
    
    This function validates that a string represents a valid IPv4 address
    with four octets in the range 0-255.
    
    Args:
        ip_string (str): IP address string to validate.
        description (str, optional): Optional description for error messages.
        
    Returns:
        bool: True if the IP address format is valid.
        
    Raises:
        ValidationTestError: If the IP address format is invalid.
    
    Example:
        >>> test_ip_address("192.168.1.1")
        True
        >>> test_ip_address("256.1.1.1")
        ValidationTestError: Regex match failed (IP address): '256.1.1.1' does not match '^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
    """
    ip_pattern = r"^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
    return test_regex_match(ip_string, ip_pattern, description or "IP address")


def test_mac_address(mac_string: str, description: str = "") -> bool:
    """Test MAC address format validation.
    
    This function validates that a string represents a valid MAC address
    in the format XX:XX:XX:XX:XX:XX or XX-XX-XX-XX-XX-XX where XX are
    hexadecimal digits.
    
    Args:
        mac_string (str): MAC address string to validate.
        description (str, optional): Optional description for error messages.
        
    Returns:
        bool: True if the MAC address format is valid.
        
    Raises:
        ValidationTestError: If the MAC address format is invalid.
    
    Example:
        >>> test_mac_address("00:11:22:33:44:55")
        True
        >>> test_mac_address("00-11-22-33-44-55")
        True
        >>> test_mac_address("invalid")
        ValidationTestError: Regex match failed (MAC address): 'invalid' does not match '^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$'
    """
    mac_pattern = r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$"
    return test_regex_match(mac_string, mac_pattern, description or "MAC address")


def test_frequency_value(freq_string: str, expected_hz: int, tolerance_percent: float = 5.0,
                        description: str = "") -> bool:
    """Test frequency value with tolerance validation.
    
    This function extracts a numeric frequency value from a string and
    validates that it falls within a specified tolerance of the expected
    frequency. Useful for validating clock frequencies and other periodic
    signals where some variation is acceptable.
    
    Args:
        freq_string (str): String containing frequency value (e.g., "48000000 Hz").
        expected_hz (int): Expected frequency value in Hz.
        tolerance_percent (float, optional): Acceptable tolerance as a percentage
            of the expected value. Defaults to 5.0%.
        description (str, optional): Optional description for error messages.
        
    Returns:
        bool: True if the frequency is within tolerance.
        
    Raises:
        ValidationTestError: If no frequency value is found, or if the
            frequency is outside the acceptable tolerance range.
    
    Example:
        >>> test_frequency_value("48000000 Hz", 48000000, 1.0, "USB clock")
        True
        >>> test_frequency_value("50000000 Hz", 48000000, 1.0, "USB clock")
        ValidationTestError: Frequency out of tolerance (USB clock): 50000000 Hz not within 1.0% of 48000000 Hz
    """
    # Extract numeric value
    freq_match = re.search(r'(\d+)', freq_string)
    if not freq_match:
        raise ValidationTestError(f"No frequency value found in: '{freq_string}'")
    
    actual_hz = int(freq_match.group(1))
    tolerance = expected_hz * tolerance_percent / 100.0
    min_hz = expected_hz - tolerance
    max_hz = expected_hz + tolerance
    
    if not (min_hz <= actual_hz <= max_hz):
        desc_part = f" ({description})" if description else ""
        raise ValidationTestError(
            f"Frequency out of tolerance{desc_part}: {actual_hz} Hz not within {tolerance_percent}% of {expected_hz} Hz"
        )
    
    return True