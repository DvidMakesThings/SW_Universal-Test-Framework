"""
UTFW Network Module
===================
High-level network test functions and TestAction factories for universal testing

This module provides basic network connectivity and HTTP testing capabilities
with integration into the UTFW logging system. It focuses on fundamental
network operations like ping, HTTP requests, and web form interactions.

For more advanced HTTP testing capabilities, see the ethernet module which
provides additional features like detailed logging, request pacing, and
comprehensive validation options.

Author: DvidMakesThings
"""

import platform
import subprocess
import urllib.request
import urllib.parse
import urllib.error
import json
from typing import Dict, Any, Optional, Tuple

from ...core.core import TestAction


class NetworkTestError(Exception):
    """Exception raised when network operations or validations fail.

    This exception is raised by network test functions when connectivity
    issues occur, HTTP requests fail, validation fails, or other network-related
    operations cannot be completed successfully.

    Args:
        message (str): Description of the error.
    """

    pass


def ping_host(ip: str, count: int = 1, timeout: int = 1) -> bool:
    """Ping a host using the system ping utility.

    This function executes the system ping command to test basic network
    connectivity to a target host. It handles both Windows and Unix-like
    systems with appropriate command-line arguments.

    Args:
        ip (str): IP address to ping.
        count (int, optional): Number of ping packets to send. Defaults to 1.
        timeout (int, optional): Timeout per packet in seconds. Defaults to 1.

    Returns:
        bool: True if all ping packets succeed, False otherwise.
    """
    system = platform.system().lower()

    if "windows" in system:
        cmd = ["ping", "-n", str(count), "-w", str(timeout * 1000), ip]
    else:
        cmd = ["ping", "-c", str(count), "-W", str(timeout), ip]

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout + 3)
        return result.returncode == 0
    except Exception:
        return False


def http_get(
    url: str, timeout: float = 3.0, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Perform an HTTP GET request with error handling.

    This function performs an HTTP GET request and returns a structured
    response dictionary containing status, headers, content, and success
    information. It handles both successful responses and various error
    conditions gracefully.

    Args:
        url (str): URL to request.
        timeout (float, optional): Request timeout in seconds. Defaults to 3.0.
        headers (Optional[Dict[str, str]], optional): Optional HTTP headers
            to include in the request. Defaults to None.

    Returns:
        Dict[str, Any]: Response dictionary containing:
            - status_code (int): HTTP status code
            - headers (dict): Response headers
            - content (str): Response body content
            - success (bool): Whether the request succeeded
            - error (str, optional): Error message if request failed
    """
    try:
        req = urllib.request.Request(url)

        if headers:
            for key, value in headers.items():
                req.add_header(key, value)

        with urllib.request.urlopen(req, timeout=timeout) as response:
            content = response.read().decode("utf-8")

            return {
                "status_code": response.getcode(),
                "headers": dict(response.headers),
                "content": content,
                "success": True,
            }

    except urllib.error.HTTPError as e:
        return {
            "status_code": e.code,
            "headers": dict(e.headers) if hasattr(e, "headers") else {},
            "content": e.read().decode("utf-8") if hasattr(e, "read") else str(e),
            "success": False,
            "error": str(e),
        }
    except Exception as e:
        return {
            "status_code": 0,
            "headers": {},
            "content": "",
            "success": False,
            "error": str(e),
        }


def http_post(
    url: str,
    data: Dict[str, Any],
    timeout: float = 3.0,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Perform an HTTP POST request with form data.

    This function performs an HTTP POST request with form-encoded data
    and returns a structured response dictionary. It handles both successful
    responses and various error conditions gracefully.

    Args:
        url (str): URL to request.
        data (Dict[str, Any]): Form data dictionary to be URL-encoded.
        timeout (float, optional): Request timeout in seconds. Defaults to 3.0.
        headers (Optional[Dict[str, str]], optional): Optional HTTP headers.
            If not provided, defaults to form-encoded content type.

    Returns:
        Dict[str, Any]: Response dictionary with same structure as http_get().
    """
    if headers is None:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

    try:
        post_data = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(url, data=post_data, method="POST")

        for key, value in headers.items():
            req.add_header(key, value)

        with urllib.request.urlopen(req, timeout=timeout) as response:
            content = response.read().decode("utf-8")

            return {
                "status_code": response.getcode(),
                "headers": dict(response.headers),
                "content": content,
                "success": True,
            }

    except urllib.error.HTTPError as e:
        return {
            "status_code": e.code,
            "headers": dict(e.headers) if hasattr(e, "headers") else {},
            "content": e.read().decode("utf-8") if hasattr(e, "read") else str(e),
            "success": False,
            "error": str(e),
        }
    except Exception as e:
        return {
            "status_code": 0,
            "headers": {},
            "content": "",
            "success": False,
            "error": str(e),
        }


def test_connectivity(ip: str, timeout: int = 1) -> bool:
    """Test basic network connectivity using ping with error handling.

    This function tests network connectivity to a host using ICMP ping
    and raises an exception if the host is not reachable. It's designed
    for use in test scenarios where connectivity is a prerequisite.

    Args:
        ip (str): IP address or hostname to test connectivity to.
        timeout (int, optional): Ping timeout in seconds. Defaults to 1.

    Returns:
        bool: True if the host is reachable via ping.

    Raises:
        NetworkTestError: If the host is not reachable via ping.
    """
    if not ping_host(ip, timeout=timeout):
        raise NetworkTestError(f"Host {ip} is not reachable via ping")

    return True


def test_http_endpoint(
    base_url: str,
    path: str = "/",
    expected_content: Optional[str] = None,
    expected_status: Optional[int] = 200,
    timeout: float = 3.0,
) -> str:
    """Test HTTP endpoint availability and validate response.

    This function tests an HTTP endpoint by performing a GET request
    and validating both the status code and optionally the response
    content. It's useful for verifying web service availability and
    basic functionality.

    Args:
        base_url (str): Base URL (e.g., 'http://192.168.0.11').
        path (str, optional): Path to append to base URL. Defaults to '/'.
        expected_content (Optional[str], optional): Substring that must be
            present in the response content. Defaults to None (no content check).
        expected_status (int, optional): Expected HTTP status code. Defaults to 200.
        timeout (float, optional): Request timeout in seconds. Defaults to 3.0.

    Returns:
        str: Complete response content from the endpoint.

    Raises:
        NetworkTestError: If the request fails, status code doesn't match,
            or expected content is not found.
    """
    url = f"{base_url.rstrip('/')}{path}"
    response = http_get(url, timeout)

    if not response["success"]:
        raise NetworkTestError(
            f"HTTP GET {url} failed: {response.get('error', 'Unknown error')}"
        )

    if response["status_code"] != expected_status:
        raise NetworkTestError(
            f"HTTP GET {url} returned status {response['status_code']}, expected {expected_status}"
        )

    if expected_content and expected_content not in response["content"]:
        raise NetworkTestError(
            f"HTTP GET {url} response missing expected content: '{expected_content}'"
        )

    return response["content"]


def test_web_form_submission(
    base_url: str,
    form_path: str,
    form_data: Dict[str, Any],
    expected_status: int = 200,
    verification_path: Optional[str] = None,
    verify_content: Optional[str] = None,
    timeout: float = 3.0,
) -> bool:
    """Test web form submission with optional result verification.

    This function submits form data to a web endpoint and optionally
    verifies the result by checking another endpoint for expected content.
    It's useful for testing web-based configuration interfaces.

    Args:
        base_url (str): Base URL of the web service.
        form_path (str): Path to the form handler endpoint (e.g., '/control').
        form_data (Dict[str, Any]): Form data dictionary to submit.
        expected_status (int, optional): Expected HTTP status code. Defaults to 200.
        verification_path (Optional[str], optional): Optional path to check
            for verification after form submission. Defaults to None.
        verify_content (Optional[str], optional): Content that must be present
            in the verification response. Defaults to None.
        timeout (float, optional): Request timeout in seconds. Defaults to 3.0.

    Returns:
        bool: True if the form submission and optional verification succeed.

    Raises:
        NetworkTestError: If form submission fails, status code doesn't match,
            or verification fails.
    """
    form_url = f"{base_url.rstrip('/')}{form_path}"

    # Submit form
    response = http_post(form_url, form_data, timeout)

    if not response["success"]:
        raise NetworkTestError(
            f"Form submission to {form_url} failed: {response.get('error')}"
        )

    if response["status_code"] != expected_status:
        raise NetworkTestError(
            f"Form submission returned status {response['status_code']}, expected {expected_status}"
        )

    # Optional verification
    if verification_path and verify_content:
        verify_url = f"{base_url.rstrip('/')}{verification_path}"
        verify_response = http_get(verify_url, timeout)

        if not verify_response["success"]:
            raise NetworkTestError(f"Verification GET {verify_url} failed")

        if verify_content not in verify_response["content"]:
            raise NetworkTestError(
                f"Verification failed: '{verify_content}' not found in response"
            )

    return True


def test_outlet_control_via_web(
    base_url: str,
    channel: int,
    state: bool,
    form_path: str = "/control",
    timeout: float = 3.0,
) -> bool:
    """Test outlet control via web interface form submission.

    This function tests outlet control functionality through a web interface
    by submitting form data to control individual outlet channels. The exact
    form field format may need adjustment based on the specific device's
    web interface implementation.

    Args:
        base_url (str): Base URL of the device web interface.
        channel (int): Outlet channel number (typically 1-8).
        state (bool): Desired outlet state (True for ON, False for OFF).
        form_path (str, optional): Path to the control form handler.
            Defaults to '/control'.
        timeout (float, optional): Request timeout in seconds. Defaults to 3.0.

    Returns:
        bool: True if the outlet control operation succeeds.

    Raises:
        NetworkTestError: If the channel number is invalid or if the
            web form submission fails.
    """
    if not 1 <= channel <= 8:
        raise NetworkTestError(f"Invalid channel: {channel}. Must be 1-8")

    # Prepare form data (this may need adjustment based on actual web interface)
    form_data = {f"channel{channel}": "1" if state else "0"}

    return test_web_form_submission(
        base_url=base_url, form_path=form_path, form_data=form_data, timeout=timeout
    )


def test_network_config_via_web(
    base_url: str,
    config_changes: Dict[str, str],
    form_path: str = "/settings",
    timeout: float = 3.0,
) -> bool:
    """Test network configuration changes via web interface.

    This function tests network configuration functionality through a web
    interface by submitting configuration changes via form data. It's
    useful for testing web-based network management interfaces.

    Args:
        base_url (str): Base URL of the device web interface.
        config_changes (Dict[str, str]): Dictionary mapping configuration
            parameter names to their new values.
        form_path (str, optional): Path to the settings form handler.
            Defaults to '/settings'.
        timeout (float, optional): Request timeout in seconds. Defaults to 3.0.

    Returns:
        bool: True if the network configuration operation succeeds.

    Raises:
        NetworkTestError: If the web form submission fails.
    """
    return test_web_form_submission(
        base_url=base_url,
        form_path=form_path,
        form_data=config_changes,
        timeout=timeout,
    )


def ping_host(name: str, ip: str, count: int = 1, timeout: int = 1,
negative_test: bool = False) -> TestAction:
    """Create a TestAction that tests network connectivity via ping.

    This TestAction factory creates an action that performs ICMP ping
    operations to test basic network connectivity to a target host.
    The action will fail if any ping packets are lost.

    Args:
        name (str): Human-readable name for the test action.
        ip (str): IP address or hostname to ping.
        count (int, optional): Number of ping packets to send. Defaults to 1.
        timeout (int, optional): Timeout per packet in seconds. Defaults to 1.

    Returns:
        TestAction: TestAction that returns True when all pings succeed.

    Raises:
        NetworkTestError: When executed, raises this exception if any
            ping packets fail or if the host is unreachable.

    Example:
        >>> ping_action = ping_host("Test connectivity", "192.168.1.1", count=3)
        >>> # Use in STE: STE(ping_action, other_actions, ...)
    """

    def execute():
        if not ping_host(ip, count, timeout):
            raise NetworkTestError(f"Ping to {ip} failed")
        return True

    return TestAction(name, execute, negative_test=negative_test)
