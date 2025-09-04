"""
UTFW Validation Module
======================
High-level validation and regex test functions for universal testing

Author: DvidMakesThings
"""

import re
from typing import Any, List, Dict, Optional, Union


class ValidationTestError(Exception):
    """Validation test specific error"""
    pass


def test_regex_match(text: str, pattern: str, description: str = "") -> bool:
    """
    Test if text matches regex pattern
    
    Args:
        text: Text to test
        pattern: Regex pattern
        description: Optional description for error messages
        
    Returns:
        True if matches
        
    Raises:
        ValidationTestError: If pattern doesn't match
    """
    try:
        if not re.match(pattern, text):
            desc_part = f" ({description})" if description else ""
            raise ValidationTestError(f"Regex match failed{desc_part}: '{text}' does not match '{pattern}'")
        return True
    except re.error as e:
        raise ValidationTestError(f"Invalid regex pattern '{pattern}': {e}")


def test_regex_search(text: str, pattern: str, description: str = "") -> bool:
    """
    Test if text contains regex pattern
    
    Args:
        text: Text to search
        pattern: Regex pattern
        description: Optional description for error messages
        
    Returns:
        True if found
        
    Raises:
        ValidationTestError: If pattern not found
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
    """
    Test if numeric value is within range
    
    Args:
        value: Value to test (can be string, int, or float)
        min_val: Minimum allowed value
        max_val: Maximum allowed value
        description: Optional description for error messages
        
    Returns:
        True if in range
        
    Raises:
        ValidationTestError: If value is out of range or invalid
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
    """
    Test exact string match
    
    Args:
        actual: Actual value
        expected: Expected value
        description: Optional description for error messages
        
    Returns:
        True if matches exactly
        
    Raises:
        ValidationTestError: If values don't match
    """
    if actual != expected:
        desc_part = f" ({description})" if description else ""
        raise ValidationTestError(f"Exact match failed{desc_part}: expected '{expected}', got '{actual}'")
    
    return True


def test_contains_all(text: str, required_items: List[str], description: str = "") -> bool:
    """
    Test that text contains all required items
    
    Args:
        text: Text to search
        required_items: List of required strings
        description: Optional description for error messages
        
    Returns:
        True if all items found
        
    Raises:
        ValidationTestError: If any items are missing
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
    """
    Test key-value pairs in text
    
    Args:
        text: Text containing key-value pairs
        expected_pairs: Dict of key->expected_value (can be string or regex pattern)
        separators: List of separators to try (default: [":", "="])
        description: Optional description for error messages
        
    Returns:
        Dict of parsed key-value pairs
        
    Raises:
        ValidationTestError: If validation fails
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
            # Regex pattern
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
    """
    Test firmware version format
    
    Args:
        version_string: Version string to test
        expected_format: Regex pattern for expected format
        
    Returns:
        True if valid format
        
    Raises:
        ValidationTestError: If format is invalid
    """
    return test_regex_match(version_string, expected_format, "firmware version")


def test_ip_address(ip_string: str, description: str = "") -> bool:
    """
    Test IP address format
    
    Args:
        ip_string: IP address string
        description: Optional description
        
    Returns:
        True if valid IP format
        
    Raises:
        ValidationTestError: If IP format is invalid
    """
    ip_pattern = r"^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
    return test_regex_match(ip_string, ip_pattern, description or "IP address")


def test_mac_address(mac_string: str, description: str = "") -> bool:
    """
    Test MAC address format
    
    Args:
        mac_string: MAC address string
        description: Optional description
        
    Returns:
        True if valid MAC format
        
    Raises:
        ValidationTestError: If MAC format is invalid
    """
    mac_pattern = r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$"
    return test_regex_match(mac_string, mac_pattern, description or "MAC address")


def test_frequency_value(freq_string: str, expected_hz: int, tolerance_percent: float = 5.0,
                        description: str = "") -> bool:
    """
    Test frequency value with tolerance
    
    Args:
        freq_string: Frequency string (e.g., "48000000 Hz")
        expected_hz: Expected frequency in Hz
        tolerance_percent: Tolerance percentage
        description: Optional description
        
    Returns:
        True if frequency is within tolerance
        
    Raises:
        ValidationTestError: If frequency is out of tolerance
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