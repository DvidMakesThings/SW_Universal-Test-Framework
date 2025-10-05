# UTFW/ethernet.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UTFW Ethernet Module
====================

Advanced HTTP and web testing utilities with comprehensive logging and validation.

This module provides sophisticated HTTP testing capabilities that go beyond
basic network operations. It includes features like request pacing for hardware
safety, detailed HTTP transaction logging, response dumping, and tolerance for
connection drops during device operations.

All HTTP operations integrate with the UTFW logging system to provide detailed
subprocess and HTTP activity logs, with optional HTTP transaction dumps written
to the active test's reports directory.

Author: DvidMakesThings
"""

from __future__ import annotations

import platform
import subprocess
import time
import json
import os
import re
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List

from ...core.core import TestAction
from ...core.logger import get_active_logger


class EthernetTestError(Exception):
    """Exception raised when HTTP/Ethernet operations fail.

    This exception is raised by ethernet test functions when HTTP requests
    fail, connectivity issues occur, validation fails, or other web-related
    operations cannot be completed successfully.

    Args:
        message (str): Description of the error that occurred.
    """


# ======================== Request Pacing (Rate Limiting) ========================

_last_event_time: Dict[str, float] = {}


def _pace(pace_key: Optional[str], min_interval_s: float) -> None:
    """Enforce minimum delay between actions for hardware safety.

    This function implements rate limiting to prevent overwhelming hardware
    devices with rapid successive requests. It maintains per-key timestamps
    to enforce minimum intervals between operations.

    Args:
        pace_key (Optional[str]): Identifier for the paced operation domain
            (e.g., "relay", "config"). If None or empty, pacing is disabled.
        min_interval_s (float): Minimum interval between executions in seconds.
            If <= 0, pacing is disabled.

    Note:
        Uses an in-process timestamp map, so pacing is not enforced across
        different process instances.
    """
    logger = get_active_logger()

    if logger:
        logger.log(f"[ETHERNET] _pace() called: pace_key={pace_key}, min_interval_s={min_interval_s}")

    if not pace_key or min_interval_s <= 0:
        if logger:
            logger.log(f"[ETHERNET] _pace() skipped (key empty or interval <= 0)")
        return

    now = time.time()
    last = _last_event_time.get(pace_key, 0.0)
    delta = now - last

    if logger:
        logger.log(f"[ETHERNET] _pace() timing: now={now:.3f}, last={last:.3f}, delta={delta:.3f}s")

    if delta < min_interval_s:
        sleep_time = min_interval_s - delta
        if logger:
            logger.log(f"[ETHERNET] _pace() sleeping for {sleep_time:.3f}s to enforce minimum interval")
        time.sleep(sleep_time)
    else:
        if logger:
            logger.log(f"[ETHERNET] _pace() no sleep needed, delta >= min_interval")

    _last_event_time[pace_key] = time.time()

    if logger:
        logger.log(f"[ETHERNET] _pace() complete, updated timestamp for key '{pace_key}'")


# ======================== Internal Helper Functions ========================


def _log_subprocess(cmd, rc, out, err, tag: str = "SUBPROC") -> None:
    """Log subprocess execution to the active logger.

    This function logs subprocess execution details including command,
    return code, and output streams using the active UTFW logger.

    Args:
        cmd: Command that was executed (string or list).
        rc (int): Return code.
        out (str): Captured standard output.
        err (str): Captured standard error.
        tag (str, optional): Tag for categorizing the subprocess. Defaults to "SUBPROC".
    """
    logger = get_active_logger()
    if logger:
        logger.subprocess(cmd, rc, out, err, tag=tag)


def _ensure_dir(path: str) -> None:
    """Create directory if it doesn't exist, ignoring errors.

    This utility function creates a directory and all necessary parent
    directories, silently ignoring any errors that occur during creation.

    Args:
        path (str): Directory path to create.
    """
    logger = get_active_logger()

    if logger:
        logger.log(f"[ETHERNET] _ensure_dir() called: path={path}")

    try:
        os.makedirs(path, exist_ok=True)
        if logger:
            logger.log(f"[ETHERNET] _ensure_dir() success: directory ensured")
    except Exception as e:
        if logger:
            logger.log(f"[ETHERNET] _ensure_dir() exception (ignored): {type(e).__name__}: {e}")


def _ts() -> str:
    """Generate a filename-safe timestamp string.

    Creates a timestamp string suitable for use in filenames, including
    microseconds for uniqueness.

    Returns:
        str: Timestamp in format 'YYYYMMDD_HHMMSS_microseconds'.
    """
    logger = get_active_logger()
    result = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    if logger:
        logger.log(f"[ETHERNET] _ts() generated: {result}")

    return result


def _dump_http(
    base_url: str,
    path: str,
    method: str,
    status: int,
    headers: Dict[str, str],
    body: str,
    dump_subdir: Optional[str] = None,
) -> None:
    """Write HTTP transaction dump to the reports directory.

    This function writes detailed HTTP transaction information to a file
    under the active test's reports directory. The dump includes URL,
    method, status, headers, and response body for debugging and analysis.

    Files are written to: <reports_dir>/<dump_subdir>/ if dump_subdir is
    provided and an active logger with reports directory is available.

    Args:
        base_url (str): Base URL of the request.
        path (str): Request path (can be empty for root).
        method (str): HTTP method for filename generation.
        status (int): Response status code.
        headers (Dict[str, str]): Response headers dictionary.
        body (str): Response body content.
        dump_subdir (Optional[str]): Subdirectory name under reports directory.

    Note:
        I/O errors are silently ignored to avoid interfering with test execution.
    """
    logger = get_active_logger()

    if logger:
        logger.log(f"[ETHERNET] _dump_http() called")
        logger.log(f"[ETHERNET]   base_url={base_url}")
        logger.log(f"[ETHERNET]   path={path}")
        logger.log(f"[ETHERNET]   method={method}")
        logger.log(f"[ETHERNET]   status={status}")
        logger.log(f"[ETHERNET]   headers={len(headers)} entries")
        logger.log(f"[ETHERNET]   body={len(body)} bytes")
        logger.log(f"[ETHERNET]   dump_subdir={dump_subdir}")

    dump_dir = None
    if logger and hasattr(logger, "log_file") and logger.log_file and dump_subdir:
        dump_dir = os.path.join(logger.log_file.parent, dump_subdir)
        if logger:
            logger.log(f"[ETHERNET] _dump_http() resolved dump_dir={dump_dir}")

    if not dump_dir:
        if logger:
            logger.log(f"[ETHERNET] _dump_http() skipped (no dump_dir available)")
        return

    _ensure_dir(dump_dir)
    safe_path = re.sub(r"[^A-Za-z0-9_.-]+", "_", (path or "root"))
    fname = f"{_ts()}_{method}_{safe_path}_{status}.txt"
    full_path = os.path.join(dump_dir, fname)

    if logger:
        logger.log(f"[ETHERNET] _dump_http() writing to: {full_path}")

    try:
        with open(full_path, "w", encoding="utf-8", errors="replace") as f:
            f.write(f"URL: {base_url}{path}\nMETHOD: {method}\nSTATUS: {status}\n\n")
            f.write("=== HEADERS ===\n")
            for k, v in headers.items():
                f.write(f"{k}: {v}\n")
            f.write("\n=== BODY ===\n")
            f.write(body or "")

        if logger:
            logger.log(f"[ETHERNET] _dump_http() write complete: {len(body or '')} bytes written")

    except Exception as e:
        if logger:
            logger.log(f"[ETHERNET] _dump_http() write error (ignored): {type(e).__name__}: {e}")


def _url(base: str, path: str) -> str:
    """Join base URL and path into a complete URL.

    This function properly combines a base URL with a path, handling
    various edge cases like trailing slashes and absolute URLs.

    Args:
        base (str): Base URL (e.g., "http://host:80").
        path (str): Relative path or absolute URL.

    Returns:
        str: Complete absolute URL.
    """
    logger = get_active_logger()

    if logger:
        logger.log(f"[ETHERNET] _url() called: base={base}, path={path}")

    if not path:
        if logger:
            logger.log(f"[ETHERNET] _url() no path, returning base: {base}")
        return base

    if path.startswith("http://") or path.startswith("https://"):
        if logger:
            logger.log(f"[ETHERNET] _url() path is absolute URL: {path}")
        return path

    if not base.endswith("/") and not path.startswith("/"):
        result = base + "/" + path
    else:
        result = base + path

    if logger:
        logger.log(f"[ETHERNET] _url() result: {result}")

    return result


def _ping_once(host: str, timeout_s: float = 1.0) -> bool:
    """Execute a single ICMP ping using the system ping utility.

    This function performs a single ping operation using the appropriate
    system ping command for the current platform, with full logging of
    the command execution.

    Args:
        host (str): Target hostname or IP address.
        timeout_s (float, optional): Ping timeout in seconds. Defaults to 1.0.

    Returns:
        bool: True if ping succeeds (return code 0), False otherwise.
    """
    logger = get_active_logger()

    if logger:
        logger.log(f"[ETHERNET] _ping_once() called: host={host}, timeout={timeout_s}s")

    sysname = platform.system().lower()

    if logger:
        logger.log(f"[ETHERNET] _ping_once() detected system: {sysname}")

    if "windows" in sysname:
        cmd = ["ping", "-n", "1", "-w", str(int(timeout_s * 1000)), host]
    else:
        cmd = ["ping", "-c", "1", "-W", str(int(timeout_s)), host]

    if logger:
        logger.log(f"[ETHERNET] _ping_once() command: {' '.join(cmd)}")

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s + 2.0)
        success = r.returncode == 0

        if logger:
            logger.log(f"[ETHERNET] _ping_once() result: rc={r.returncode}, success={success}")

        _log_subprocess(cmd, r.returncode, r.stdout, r.stderr, tag="PING")
        return success

    except subprocess.TimeoutExpired as e:
        if logger:
            logger.log(f"[ETHERNET] _ping_once() timeout after {timeout_s + 2.0}s")
        _log_subprocess(cmd, 124, "", f"Timeout after {timeout_s + 2.0}s", tag="PING")
        return False

    except Exception as e:
        if logger:
            logger.log(f"[ETHERNET] _ping_once() exception: {type(e).__name__}: {e}")
        _log_subprocess(cmd, 1, "", str(e), tag="PING")
        return False


def _http_request(
    method: str,
    url: str,
    *,
    timeout: float = 3.0,
    headers: Optional[Dict[str, str]] = None,
    data_bytes: Optional[bytes] = None,
) -> Tuple[int, Dict[str, str], str]:
    """Perform HTTP request with retry logic and comprehensive logging.

    This function performs HTTP requests with automatic retry for transient
    errors, comprehensive logging, and structured error handling. It supports
    all HTTP methods and includes detailed execution logging.

    Args:
        method (str): HTTP method (e.g., "GET", "POST", "PUT").
        url (str): Absolute URL for the request.
        timeout (float, optional): Socket timeout in seconds. Defaults to 3.0.
        headers (Optional[Dict[str, str]], optional): Additional request headers.
        data_bytes (Optional[bytes], optional): Request body data.

    Returns:
        Tuple[int, Dict[str, str], str]: Tuple of (status_code, response_headers, body_text).

    Raises:
        EthernetTestError: On transport errors or after retry attempts are exhausted.
    """
    import http.client
    import socket

    logger = get_active_logger()

    if logger:
        logger.log(f"[ETHERNET] _http_request() called")
        logger.log(f"[ETHERNET]   method={method}")
        logger.log(f"[ETHERNET]   url={url}")
        logger.log(f"[ETHERNET]   timeout={timeout}s")
        logger.log(f"[ETHERNET]   headers={headers}")
        logger.log(f"[ETHERNET]   data_bytes={len(data_bytes or b'')} bytes")

    if logger:
        h_preview = " ".join(f"{k}={repr(v)}" for k, v in (headers or {}).items())
        logger.info(
            f"[HTTP {method}] {url} timeout={timeout}s headers={h_preview or 'none'} data_len={len(data_bytes or b'')}"
        )

    attempts = 3
    last_err = None

    for attempt in range(1, attempts + 1):
        if logger and attempt > 1:
            logger.log(f"[ETHERNET] _http_request() attempt {attempt}/{attempts}")

        conn = None
        try:
            if logger:
                logger.log(f"[ETHERNET] _http_request() opening connection...")

            # Parse URL to get host and path
            from urllib.parse import urlparse
            parsed = urlparse(url)
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == 'https' else 80)
            path = parsed.path or '/'
            if parsed.query:
                path += '?' + parsed.query

            # Use HTTPConnection for more control
            if parsed.scheme == 'https':
                conn = http.client.HTTPSConnection(host, port, timeout=timeout)
            else:
                conn = http.client.HTTPConnection(host, port, timeout=timeout)

            # Prepare headers
            req_headers = headers.copy() if headers else {}
            if 'Host' not in req_headers:
                req_headers['Host'] = host
            if 'Connection' not in req_headers:
                req_headers['Connection'] = 'close'

            # Send request
            conn.request(method.upper(), path, body=data_bytes, headers=req_headers)

            # Get response
            resp = conn.getresponse()
            status_code = resp.status
            response_headers = dict(resp.headers)

            if logger:
                logger.log(f"[ETHERNET] _http_request() response status: {status_code}")
                logger.log(f"[ETHERNET] _http_request() response headers: {response_headers}")

            # Read body
            body = resp.read()

            if logger:
                logger.log(f"[ETHERNET] _http_request() received {len(body)} bytes")

            try:
                text = body.decode("utf-8", errors="replace")
            except Exception as decode_err:
                if logger:
                    logger.log(f"[ETHERNET] _http_request() decode error: {decode_err}")
                text = ""

            if logger:
                logger.log(f"[ETHERNET] _http_request() success on attempt {attempt}")

            return status_code, response_headers, text

        except urllib.error.HTTPError as e:
            # This should not happen with HTTPConnection, but keep for compatibility
            if logger:
                logger.log(f"[ETHERNET] _http_request() HTTPError: {e.code} {e.reason}")

            body = ""
            try:
                body = (e.read() or b"").decode("utf-8", errors="replace")
                if logger:
                    logger.log(f"[ETHERNET] _http_request() HTTPError body: {len(body)} bytes")
            except Exception as body_err:
                if logger:
                    logger.log(f"[ETHERNET] _http_request() HTTPError body read error: {body_err}")

            headers_dict = dict(getattr(e, "headers", {}) or {})

            if logger:
                logger.log(f"[ETHERNET] _http_request() returning HTTPError: status={e.code}, headers={len(headers_dict)}, body={len(body)}B")

            return e.code, headers_dict, body

        except (
            http.client.IncompleteRead,
            http.client.RemoteDisconnected,
            socket.timeout,
            TimeoutError,
        ) as e:
            last_err = e

            if logger:
                logger.log(f"[ETHERNET] _http_request() transient error: {type(e).__name__}: {e}")
                logger.info(
                    f"[HTTP RETRY {attempt}/{attempts}] {method} {url} due to transient error: {e}"
                )

            sleep_time = 0.15 * attempt
            if logger:
                logger.log(f"[ETHERNET] _http_request() sleeping {sleep_time:.3f}s before retry...")

            time.sleep(sleep_time)
            continue

        except Exception as e:
            last_err = e

            if logger:
                logger.log(f"[ETHERNET] _http_request() unexpected error: {type(e).__name__}: {e}")

            break

        finally:
            # Always close the connection
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    if logger:
        logger.log(f"[ETHERNET] _http_request() all attempts failed, raising EthernetTestError")
        logger.log(f"[ETHERNET] _http_request() last error: {type(last_err).__name__}: {last_err}")

    raise EthernetTestError(f"{method} {url} failed: {last_err}")


# ======================== TestAction Factories ========================


def ping_action(
    name: str, ip: str, count: int = 1, timeout_per_pkt: float = 1.0
,
        negative_test: bool = False) -> TestAction:
    """Create a TestAction that performs ICMP ping operations.

    This TestAction factory creates an action that performs one or more
    ping operations to test network connectivity. All ping attempts must
    succeed for the action to pass.

    Args:
        name (str): Human-readable name for the test action.
        ip (str): Target hostname or IP address.
        count (int, optional): Number of ping packets to send. Defaults to 1.
        timeout_per_pkt (float, optional): Timeout per packet in seconds. Defaults to 1.0.

    Returns:
        TestAction: TestAction that returns True when all pings succeed.

    Raises:
        EthernetTestError: When executed, raises this exception if any
            ping attempts fail.

    Example:
        >>> ping_test = ping_action("Test connectivity", "192.168.1.1", count=3)
    """

    def execute():
        for _ in range(max(1, int(count))):
            if not _ping_once(ip, timeout_per_pkt):
                raise EthernetTestError(f"Ping to {ip} failed")
        return True

    return TestAction(name, execute, negative_test=negative_test)


def http_get_action(
    name: str,
    base_url: str,
    path: str,
    timeout: float,
    *,
    accept_status: Tuple[int, ...] = (200, 304),
    require_nonempty: Optional[bool] = False,
    headers: Optional[Dict[str, str]] = None,
    dump_subdir: Optional[str] = None,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that performs HTTP GET with validation.

    This TestAction factory creates an action that performs an HTTP GET
    request and validates the response status and optionally the body content.
    It supports HTTP transaction dumping for debugging purposes.

    Args:
        name (str): Human-readable name for the test action.
        base_url (str): Base URL (e.g., "http://192.168.1.100").
        path (str): Resource path or absolute URL.
        timeout (float): Request timeout in seconds.
        accept_status (Tuple[int, ...], optional): Acceptable HTTP status codes.
            Defaults to (200, 304).
        require_nonempty (bool, optional): Whether response body must be non-empty.
            Defaults to False.
        headers (Optional[Dict[str, str]], optional): Additional request headers.
        dump_subdir (Optional[str], optional): Subdirectory for HTTP dumps.

    Returns:
        TestAction: TestAction that returns a dictionary with 'status',
            'headers', and 'body' keys.

    Raises:
        EthernetTestError: When executed, raises this exception if the
            request fails, status is unacceptable, or body validation fails.

    Example:
        >>> get_action = http_get_action(
        ...     "Get device status", "http://192.168.1.100", "/status", 5.0,
        ...     require_nonempty=True, dump_subdir="http_dumps"
        ... )
    """

    def execute():
        url = _url(base_url, path)
        status, hdrs, body = _http_request("GET", url, timeout=timeout, headers=headers)
        _dump_http(base_url, path, "GET", status, hdrs, body, dump_subdir)
        if status not in accept_status:
            raise EthernetTestError(f"GET {path} -> {status}")
        if require_nonempty and not (body or "").strip():
            raise EthernetTestError(f"GET {path} empty body")
        return {"status": status, "headers": hdrs, "body": body}

    return TestAction(name, execute, negative_test=negative_test)


def http_post_form_action(
    name: str,
    base_url: str,
    path: str,
    form: Dict[str, Any],
    timeout: float,
    *,
    headers: Optional[Dict[str, str]] = None,
    accept_status: Tuple[int, ...] = (200, 202, 204),
    dump_subdir: Optional[str] = None,
    pace_key: Optional[str] = None,
    min_interval_s: float = 0.0,
    tolerate_disconnect: bool = False,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that performs HTTP POST with form data.

    This TestAction factory creates an action that performs an HTTP POST
    request with URL-encoded form data. It supports request pacing for
    hardware safety and can tolerate connection drops during device reboots.

    Args:
        name (str): Human-readable name for the test action.
        base_url (str): Base URL for the request.
        path (str): Resource path or absolute URL.
        form (Dict[str, Any]): Form fields to be URL-encoded.
        timeout (float): Request timeout in seconds.
        headers (Optional[Dict[str, str]], optional): Additional headers to merge.
        accept_status (Tuple[int, ...], optional): Acceptable status codes.
            Defaults to (200, 202, 204).
        dump_subdir (Optional[str], optional): Subdirectory for HTTP dumps.
        pace_key (Optional[str], optional): Pacing key for rate limiting.
        min_interval_s (float, optional): Minimum interval between requests
            with the same pace_key. Defaults to 0.0 (no pacing).
        tolerate_disconnect (bool, optional): Whether to treat connection
            drops as expected (useful for device reboot scenarios). Defaults to False.

    Returns:
        TestAction: TestAction that returns a dictionary with response data.
            When tolerate_disconnect=True and a disconnect occurs, status may be None.

    Raises:
        EthernetTestError: When executed, raises this exception if the
            request fails (unless tolerated) or status is unacceptable.

    Example:
        >>> form_action = http_post_form_action(
        ...     "Configure device", "http://192.168.1.100", "/config",
        ...     {"ip": "192.168.1.101", "mask": "255.255.255.0"}, 10.0,
        ...     pace_key="config", min_interval_s=2.0, tolerate_disconnect=True
        ... )
    """

    def execute():
        _pace(pace_key, min_interval_s)
        h = {"Content-Type": "application/x-www-form-urlencoded"}
        if headers:
            h.update(headers)
        data = urllib.parse.urlencode(form).encode("utf-8")
        url = _url(base_url, path)
        try:
            status, hdrs, body = _http_request(
                "POST", url, timeout=timeout, headers=h, data_bytes=data
            )
        except EthernetTestError as e:
            logger = get_active_logger()
            if tolerate_disconnect and logger:
                logger.info(
                    f"[HTTP POST tolerated disconnect] {url} -> proceeding (reason: {e})"
                )
                return {"status": None, "headers": {}, "body": ""}
            if tolerate_disconnect:
                return {"status": None, "headers": {}, "body": ""}
            raise
        _dump_http(base_url, path, "POST", status, hdrs, body, dump_subdir)
        if status not in accept_status:
            raise EthernetTestError(f"POST {path} -> {status}, body={body[:200]}")
        return {"status": status, "headers": hdrs, "body": body}

    return TestAction(name, execute, negative_test=negative_test)


def http_post_json_action(
    name: str,
    base_url: str,
    path: str,
    obj: Dict[str, Any],
    timeout: float,
    *,
    headers: Optional[Dict[str, str]] = None,
    accept_status: Tuple[int, ...] = (200, 202, 204),
    dump_subdir: Optional[str] = None,
    pace_key: Optional[str] = None,
    min_interval_s: float = 0.0,
    tolerate_disconnect: bool = False,
    negative_test: bool = False
) -> TestAction:
    """Create a TestAction that performs HTTP POST with JSON data.

    This TestAction factory creates an action that performs an HTTP POST
    request with JSON-encoded data. It supports the same pacing and
    disconnect tolerance features as the form POST action.

    Args:
        name (str): Human-readable name for the test action.
        base_url (str): Base URL for the request.
        path (str): Resource path or absolute URL.
        obj (Dict[str, Any]): Object to be JSON-encoded as request body.
        timeout (float): Request timeout in seconds.
        headers (Optional[Dict[str, str]], optional): Additional headers to merge.
        accept_status (Tuple[int, ...], optional): Acceptable status codes.
            Defaults to (200, 202, 204).
        dump_subdir (Optional[str], optional): Subdirectory for HTTP dumps.
        pace_key (Optional[str], optional): Pacing key for rate limiting.
        min_interval_s (float, optional): Minimum interval between requests. Defaults to 0.0.
        tolerate_disconnect (bool, optional): Whether to treat connection drops
            as expected. Defaults to False.

    Returns:
        TestAction: TestAction that returns a dictionary with response data.

    Raises:
        EthernetTestError: When executed, raises this exception if the
            request fails (unless tolerated) or status is unacceptable.

    Example:
        >>> json_action = http_post_json_action(
        ...     "Update settings", "http://192.168.1.100", "/api/settings",
        ...     {"network": {"dhcp": True}}, 5.0, pace_key="api"
        ... )
    """

    def execute():
        _pace(pace_key, min_interval_s)
        h = {"Content-Type": "application/json"}
        if headers:
            h.update(headers)
        data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        url = _url(base_url, path)
        try:
            status, hdrs, body = _http_request(
                "POST", url, timeout=timeout, headers=h, data_bytes=data
            )
        except EthernetTestError as e:
            logger = get_active_logger()
            if tolerate_disconnect and logger:
                logger.info(
                    f"[HTTP POST tolerated disconnect] {url} -> proceeding (reason: {e})"
                )
                return {"status": None, "headers": {}, "body": ""}
            if tolerate_disconnect:
                return {"status": None, "headers": {}, "body": ""}
            raise
        _dump_http(base_url, path, "POST", status, hdrs, body, dump_subdir)
        if status not in accept_status:
            raise EthernetTestError(f"POST {path} -> {status}, body={body[:200]}")
        return {"status": status, "headers": hdrs, "body": body}

    return TestAction(name, execute, negative_test=negative_test)


def expect_header_prefix_action(
    name: str,
    base_url: str,
    path: str,
    header_name: str,
    prefix: str,
    timeout: float,
    *,
    dump_subdir: Optional[str] = None,
    negative_test: bool = False
) -> TestAction:
    """Create a TestAction that validates HTTP response header prefixes.

    This TestAction factory creates an action that performs an HTTP GET
    request and validates that a specific response header starts with
    the expected prefix. This is useful for validating server versions,
    content types, or other header-based information.

    Args:
        name (str): Human-readable name for the test action.
        base_url (str): Base URL for the request.
        path (str): Resource path or absolute URL.
        header_name (str): Name of the header to check (case-insensitive).
        prefix (str): Expected prefix for the header value (case-insensitive).
        timeout (float): Request timeout in seconds.
        dump_subdir (Optional[str], optional): Subdirectory for HTTP dumps.

    Returns:
        TestAction: TestAction that returns True when the header validation passes.

    Raises:
        EthernetTestError: When executed, raises this exception if the
            request fails, status is unexpected, or header validation fails.

    Example:
        >>> header_action = expect_header_prefix_action(
        ...     "Check server type", "http://192.168.1.100", "/",
        ...     "Server", "nginx", 3.0
        ... )
    """

    def execute():
        url = _url(base_url, path)
        status, hdrs, body = _http_request("GET", url, timeout=timeout)
        _dump_http(base_url, path, "GET", status, hdrs, body, dump_subdir)
        if status not in (200, 304):
            raise EthernetTestError(f"{path} unexpected status {status}")
        val = hdrs.get(header_name) or hdrs.get(header_name.lower()) or ""
        if not str(val).lower().startswith(prefix.lower()):
            raise EthernetTestError(
                f"{path} header {header_name!r}='{val}' does not start with '{prefix}'"
            )
        return True

    return TestAction(name, execute, negative_test=negative_test)


def etag_roundtrip_action(
    name: str,
    base_url: str,
    path: str,
    timeout: float,
    *,
    dump_subdir: Optional[str] = None,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that validates ETag conditional GET behavior.

    This TestAction factory creates an action that tests proper ETag
    implementation by performing a GET request, extracting the ETag,
    then performing a conditional GET with If-None-Match to verify
    304 Not Modified behavior.

    The test procedure:
    1. GET the resource and extract the ETag header
    2. GET with If-None-Match=<etag> and expect 304 Not Modified

    Args:
        name (str): Human-readable name for the test action.
        base_url (str): Base URL for the requests.
        path (str): Resource path or absolute URL.
        timeout (float): Request timeout in seconds.
        dump_subdir (Optional[str], optional): Subdirectory for HTTP dumps.

    Returns:
        TestAction: TestAction that returns True when ETag behavior is correct.

    Raises:
        EthernetTestError: When executed, raises this exception if the
            ETag is missing or conditional GET behavior is incorrect.

    Example:
        >>> etag_action = etag_roundtrip_action(
        ...     "Validate ETag caching", "http://192.168.1.100", "/api/status", 5.0
        ... )
    """

    def execute():
        url = _url(base_url, path)
        s1, h1, b1 = _http_request("GET", url, timeout=timeout)
        _dump_http(base_url, path, "GET", s1, h1, b1, dump_subdir)
        if s1 not in (200, 304):
            raise EthernetTestError(f"{path} -> {s1}")
        etag = h1.get("ETag") or h1.get("etag")
        if not etag:
            raise EthernetTestError(f"{path} missing ETag")
        req = urllib.request.Request(url, method="GET", headers={"If-None-Match": etag})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raise EthernetTestError(f"{path} expected 304, got {resp.getcode()}")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = (e.read() or b"").decode("utf-8", errors="replace")
            except Exception:
                pass
            _dump_http(
                base_url,
                path,
                "GET-IFNM",
                e.code,
                dict(getattr(e, "headers", {}) or {}),
                body,
                dump_subdir,
            )
            if e.code != 304:
                raise EthernetTestError(
                    f"{path} conditional GET expected 304, got {e.code}"
                )
        return True

    return TestAction(name, execute, negative_test=negative_test)


def crawl_links_action(
    name: str,
    base_url: str,
    path: str,
    timeout: float,
    *,
    dump_subdir: Optional[str] = None,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that crawls and validates linked resources.

    This TestAction factory creates an action that fetches a web page,
    extracts all href and src links, and verifies that each linked
    resource is accessible. This is useful for comprehensive web
    interface testing.

    Args:
        name (str): Human-readable name for the test action.
        base_url (str): Base URL for the requests.
        path (str): Path to the page to crawl.
        timeout (float): Request timeout in seconds.
        dump_subdir (Optional[str], optional): Subdirectory for HTTP dumps.

    Returns:
        TestAction: TestAction that returns True when all links are accessible.

    Raises:
        EthernetTestError: When executed, raises this exception if the
            base page fails or any linked assets are inaccessible.

    Example:
        >>> crawl_action = crawl_links_action(
        ...     "Validate web interface", "http://192.168.1.100", "/", 10.0,
        ...     dump_subdir="crawl_dumps"
        ... )
    """

    def execute():
        s, h, body = _http_request("GET", _url(base_url, path), timeout=timeout)
        _dump_http(base_url, path, "GET", s, h, body, dump_subdir)
        if s not in (200, 304):
            raise EthernetTestError(f"{path} -> {s}")
        links = re.findall(r"""(?:href|src)\s*=\s*["']([^"']+)["']""", body, flags=re.I)
        bad: List[str] = []
        for link in links:
            if link.startswith("#") or link.lower().startswith("mailto:"):
                continue
            u = _url(base_url, link)
            s2, h2, b2 = _http_request("GET", u, timeout=timeout)
            _dump_http(base_url, link, "GET", s2, h2, b2, dump_subdir)
            if s2 not in (200, 304):
                bad.append(f"{link} -> {s2}")
        if bad:
            raise EthernetTestError(
                "Broken assets: "
                + ", ".join(bad[:10])
                + ("..." if len(bad) > 10 else "")
            )
        return True

    return TestAction(name, execute, negative_test=negative_test)


def expect_status_action(
    name: str,
    base_url: str,
    path: str,
    expected_status: int,
    timeout: float,
    *,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body_bytes: Optional[bytes] = None,
    dump_subdir: Optional[str] = None,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that validates specific HTTP status codes.

    This TestAction factory creates an action that performs an HTTP
    request and validates that the response has exactly the expected
    status code. This is useful for testing error conditions or
    specific response scenarios.

    Args:
        name (str): Human-readable name for the test action.
        base_url (str): Base URL for the request.
        path (str): Resource path or absolute URL.
        expected_status (int): Expected HTTP status code (e.g., 404, 500).
        timeout (float): Request timeout in seconds.
        method (str, optional): HTTP method to use. Defaults to "GET".
        headers (Optional[Dict[str, str]], optional): Additional request headers.
        body_bytes (Optional[bytes], optional): Request body data.
        dump_subdir (Optional[str], optional): Subdirectory for HTTP dumps.

    Returns:
        TestAction: TestAction that returns True when the status matches exactly.

    Raises:
        EthernetTestError: When executed, raises this exception if the
            request fails or status doesn't match expectations.

    Example:
        >>> status_action = expect_status_action(
        ...     "Verify 404 for missing page", "http://192.168.1.100",
        ...     "/nonexistent", 404, 3.0
        ... )
    """

    def execute():
        url = _url(base_url, path)
        status, hdrs, body = _http_request(
            method, url, timeout=timeout, headers=headers, data_bytes=body_bytes
        )
        _dump_http(base_url, path, method, status, hdrs, body, dump_subdir)
        if status != expected_status:
            raise EthernetTestError(
                f"{method} {path} expected {expected_status}, got {status}"
            )
        return True

    return TestAction(name, execute, negative_test=negative_test)


def wait_http_ready_action(
    name: str, base_url: str, path: str, timeout_total: float
,
        negative_test: bool = False) -> TestAction:
    """Create a TestAction that waits for HTTP service readiness.

    This TestAction factory creates an action that polls an HTTP endpoint
    until it returns a successful status (200 or 304) or the timeout
    is reached. This is useful for waiting for services to become ready
    after startup or configuration changes.

    Args:
        name (str): Human-readable name for the test action.
        base_url (str): Base URL for the requests.
        path (str): Resource path to poll.
        timeout_total (float): Total time budget for polling in seconds.

    Returns:
        TestAction: TestAction that returns True when the service becomes ready.

    Raises:
        EthernetTestError: When executed, raises this exception if the
            service doesn't become ready within the timeout period.

    Example:
        >>> ready_action = wait_http_ready_action(
        ...     "Wait for web service", "http://192.168.1.100", "/", 30.0
        ... )
    """

    def execute():
        deadline = time.time() + timeout_total
        last = None
        while time.time() < deadline:
            try:
                s, _, _ = _http_request("GET", _url(base_url, path), timeout=2.0)
                last = s
                if s in (200, 304):
                    return True
            except EthernetTestError:
                pass
            time.sleep(0.3)
        raise EthernetTestError(f"HTTP not ready at {path} (last={last})")

    return TestAction(name, execute, negative_test=negative_test)
