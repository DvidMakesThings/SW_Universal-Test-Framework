"""
UTFW Network Module
===================
High-level network test functions for universal testing

Author: DvidMakesThings
"""

import platform
import subprocess
import urllib.request
import urllib.parse
import urllib.error
import json
from typing import Dict, Any, Optional, Tuple


class NetworkTestError(Exception):
    """
    Exception raised for network test failures.

    Args:
        message (str): Description of the error.
    """
    pass


class TestAction:
    """
    Represents a test action that can be executed.

    Args:
        name (str): Name of the test action.
        execute_func (Callable): Function to execute the test action.
    """
    def __init__(self, name: str, execute_func):
        self.name = name
        self.execute_func = execute_func


def ping_host(ip: str, count: int = 1, timeout: int = 1) -> bool:
    """
    Ping a host and return True if successful.

    Args:
        ip (str): IP address to ping.
        count (int, optional): Number of ping packets. Defaults to 1.
        timeout (int, optional): Timeout per packet in seconds. Defaults to 1.

    Returns:
        bool: True if ping successful, False otherwise.
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


def http_get(url: str, timeout: float = 3.0, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    Perform an HTTP GET request.

    Args:
        url (str): URL to request.
        timeout (float, optional): Request timeout in seconds. Defaults to 3.0.
        headers (Optional[Dict[str, str]], optional): Optional headers dictionary. Defaults to None.

    Returns:
        Dict[str, Any]: Dictionary with 'status_code', 'headers', 'content', 'success', and optionally 'error' keys.
    """
    try:
        req = urllib.request.Request(url)
        
        if headers:
            for key, value in headers.items():
                req.add_header(key, value)
        
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content = response.read().decode('utf-8')
            
            return {
                'status_code': response.getcode(),
                'headers': dict(response.headers),
                'content': content,
                'success': True
            }
            
    except urllib.error.HTTPError as e:
        return {
            'status_code': e.code,
            'headers': dict(e.headers) if hasattr(e, 'headers') else {},
            'content': e.read().decode('utf-8') if hasattr(e, 'read') else str(e),
            'success': False,
            'error': str(e)
        }
    except Exception as e:
        return {
            'status_code': 0,
            'headers': {},
            'content': '',
            'success': False,
            'error': str(e)
        }


def http_post(url: str, data: Dict[str, Any], timeout: float = 3.0, 
              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    Perform an HTTP POST request.

    Args:
        url (str): URL to request.
        data (Dict[str, Any]): POST data dictionary.
        timeout (float, optional): Request timeout in seconds. Defaults to 3.0.
        headers (Optional[Dict[str, str]], optional): Optional headers dictionary. Defaults to None.

    Returns:
        Dict[str, Any]: Dictionary with 'status_code', 'headers', 'content', 'success', and optionally 'error' keys.
    """
    if headers is None:
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    
    try:
        post_data = urllib.parse.urlencode(data).encode('utf-8')
        req = urllib.request.Request(url, data=post_data, method='POST')
        
        for key, value in headers.items():
            req.add_header(key, value)
        
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content = response.read().decode('utf-8')
            
            return {
                'status_code': response.getcode(),
                'headers': dict(response.headers),
                'content': content,
                'success': True
            }
            
    except urllib.error.HTTPError as e:
        return {
            'status_code': e.code,
            'headers': dict(e.headers) if hasattr(e, 'headers') else {},
            'content': e.read().decode('utf-8') if hasattr(e, 'read') else str(e),
            'success': False,
            'error': str(e)
        }
    except Exception as e:
        return {
            'status_code': 0,
            'headers': {},
            'content': '',
            'success': False,
            'error': str(e)
        }


def test_connectivity(ip: str, timeout: int = 1) -> bool:
    """
    Test basic network connectivity to a host using ping.

    Args:
        ip (str): IP address to test.
        timeout (int, optional): Ping timeout in seconds. Defaults to 1.

    Returns:
        bool: True if host is reachable.

    Raises:
        NetworkTestError: If connectivity test fails.
    """
    if not ping_host(ip, timeout=timeout):
        raise NetworkTestError(f"Host {ip} is not reachable via ping")
    
    return True


def test_http_endpoint(base_url: str, path: str = "/", 
                      expected_content: Optional[str] = None,
                      expected_status: int = 200, timeout: float = 3.0) -> str:
    """
    Test HTTP endpoint availability and verify response content.

    Args:
        base_url (str): Base URL (e.g., 'http://192.168.0.11').
        path (str, optional): Path to test (e.g., '/', '/control'). Defaults to '/'.
        expected_content (Optional[str], optional): Expected content in response. Defaults to None.
        expected_status (int, optional): Expected HTTP status code. Defaults to 200.
        timeout (float, optional): Request timeout in seconds. Defaults to 3.0.

    Returns:
        str: Response content.

    Raises:
        NetworkTestError: If endpoint test fails.
    """
    url = f"{base_url.rstrip('/')}{path}"
    response = http_get(url, timeout)
    
    if not response['success']:
        raise NetworkTestError(f"HTTP GET {url} failed: {response.get('error', 'Unknown error')}")
    
    if response['status_code'] != expected_status:
        raise NetworkTestError(
            f"HTTP GET {url} returned status {response['status_code']}, expected {expected_status}"
        )
    
    if expected_content and expected_content not in response['content']:
        raise NetworkTestError(
            f"HTTP GET {url} response missing expected content: '{expected_content}'"
        )
    
    return response['content']


def test_web_form_submission(base_url: str, form_path: str, form_data: Dict[str, Any],
                           expected_status: int = 200, verification_path: Optional[str] = None,
                           verify_content: Optional[str] = None, timeout: float = 3.0) -> bool:
    """
    Test web form submission and optionally verify the result.

    Args:
        base_url (str): Base URL.
        form_path (str): Path to form handler (e.g., '/control').
        form_data (Dict[str, Any]): Form data to submit.
        expected_status (int, optional): Expected HTTP status code. Defaults to 200.
        verification_path (Optional[str], optional): Path to check for verification. Defaults to None.
        verify_content (Optional[str], optional): Content to verify after submission. Defaults to None.
        timeout (float, optional): Request timeout in seconds. Defaults to 3.0.

    Returns:
        bool: True if test passed.

    Raises:
        NetworkTestError: If form submission test fails.
    """
    form_url = f"{base_url.rstrip('/')}{form_path}"
    
    # Submit form
    response = http_post(form_url, form_data, timeout)
    
    if not response['success']:
        raise NetworkTestError(f"Form submission to {form_url} failed: {response.get('error')}")
    
    if response['status_code'] != expected_status:
        raise NetworkTestError(
            f"Form submission returned status {response['status_code']}, expected {expected_status}"
        )
    
    # Optional verification
    if verification_path and verify_content:
        verify_url = f"{base_url.rstrip('/')}{verification_path}"
        verify_response = http_get(verify_url, timeout)
        
        if not verify_response['success']:
            raise NetworkTestError(f"Verification GET {verify_url} failed")
        
        if verify_content not in verify_response['content']:
            raise NetworkTestError(f"Verification failed: '{verify_content}' not found in response")
    
    return True


def test_outlet_control_via_web(base_url: str, channel: int, state: bool,
                               form_path: str = "/control", timeout: float = 3.0) -> bool:
    """
    Test outlet control via web interface.

    Args:
        base_url (str): Base URL.
        channel (int): Outlet channel (1-8).
        state (bool): Desired state (True=ON, False=OFF).
        form_path (str, optional): Path to control form. Defaults to '/control'.
        timeout (float, optional): Request timeout in seconds. Defaults to 3.0.

    Returns:
        bool: True if successful.

    Raises:
        NetworkTestError: If outlet control fails.
    """
    if not 1 <= channel <= 8:
        raise NetworkTestError(f"Invalid channel: {channel}. Must be 1-8")
    
    # Prepare form data (this may need adjustment based on actual web interface)
    form_data = {f'channel{channel}': '1' if state else '0'}
    
    return test_web_form_submission(
        base_url=base_url,
        form_path=form_path,
        form_data=form_data,
        timeout=timeout
    )


def test_network_config_via_web(base_url: str, config_changes: Dict[str, str],
                               form_path: str = "/settings", timeout: float = 3.0) -> bool:
    """
    Test network configuration changes via web interface.

    Args:
        base_url (str): Base URL.
        config_changes (Dict[str, str]): Dictionary of parameter-value changes.
        form_path (str, optional): Path to settings form. Defaults to '/settings'.
        timeout (float, optional): Request timeout in seconds. Defaults to 3.0.

    Returns:
        bool: True if successful.

    Raises:
        NetworkTestError: If network config test fails.
    """
    return test_web_form_submission(
        base_url=base_url,
        form_path=form_path,
        form_data=config_changes,
        timeout=timeout
    )


def ping_host(name: str, ip: str, count: int = 1, timeout: int = 1) -> TestAction:
    """
    Create a TestAction for pinging a host.

    Args:
        name (str): Name of the test action.
        ip (str): IP address to ping.
        count (int, optional): Number of ping packets. Defaults to 1.
        timeout (int, optional): Timeout per packet in seconds. Defaults to 1.

    Returns:
        TestAction: TestAction object for pinging the host.

    Raises:
        NetworkTestError: If ping fails when executed.
    """
    def execute():
        if not ping_host(ip, count, timeout):
            raise NetworkTestError(f"Ping to {ip} failed")
        return True
    return TestAction(name, execute)