"""
UTFW Display Helpers
====================
Helper functions for formatting display_command and display_expected metadata.

These helpers are used by modules to populate metadata for GUI display.
"""

from typing import Any, List, Optional


def format_range_expected(min_val: Optional[float] = None, max_val: Optional[float] = None) -> str:
    """Format range validation for expected column.

    Args:
        min_val: Minimum value (optional)
        max_val: Maximum value (optional)

    Returns:
        Formatted range string like "[0.0, 10.0]" or ">= 5.0"
    """
    if min_val is not None and max_val is not None:
        return f"[{min_val}, {max_val}]"
    elif min_val is not None:
        return f">= {min_val}"
    elif max_val is not None:
        return f"<= {max_val}"
    return ""


def format_state_expected(expected_state: bool) -> str:
    """Format boolean state for expected column.

    Args:
        expected_state: Expected boolean state

    Returns:
        "State: ON" or "State: OFF"
    """
    return f"State: {'ON' if expected_state else 'OFF'}"


def format_value_expected(expected_value: Any) -> str:
    """Format expected value for expected column.

    Args:
        expected_value: Expected value

    Returns:
        Formatted string like "= 42" or "= [1, 2, 3]"
    """
    if expected_value is None:
        return ""

    if isinstance(expected_value, list):
        if len(expected_value) <= 4:
            return f"= {expected_value}"
        else:
            return f"= [{len(expected_value)} items]"

    return f"= {expected_value}"


def format_tokens_expected(tokens: List[str]) -> str:
    """Format tokens list for expected column.

    Args:
        tokens: List of expected tokens

    Returns:
        Formatted string like "Tokens: foo, bar"
    """
    if not tokens:
        return ""

    if len(tokens) <= 3:
        tokens_str = ", ".join(str(t) for t in tokens)
        return f"Tokens: {tokens_str}"
    else:
        return f"Tokens: [{len(tokens)} items]"


def combine_expected(*parts: str) -> str:
    """Combine multiple expected parts into a single string.

    Args:
        *parts: Variable number of expected part strings

    Returns:
        Combined string separated by ", " or "-" if no parts
    """
    valid_parts = [p for p in parts if p]
    return ", ".join(valid_parts) if valid_parts else "-"
