# UTFW/ethernet.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UTFW Ethernet Module

Universal HTTP + reachability helper actions for the UTFW framework.
No project-specific logic; callers pass all specifics (hosts, paths, pacing).
Integrates with UTFW.reporting to log subprocess/HTTP activity and (optionally)
write HTTP dumps under the active test's reports_dir.
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

from .core import TestAction
from .reporting import get_active_reporter


class EthernetTestError(Exception):
    """
    Generic Ethernet/Web helper failure.

    Raised on connectivity errors, invalid HTTP status, or failed validations.
    Intended to bubble up into the reporter as a FAILED step.
    """


# --------------------------- Pacing (rate limiting) ---------------------------

_last_event_time: Dict[str, float] = {}

def _pace(pace_key: Optional[str], min_interval_s: float) -> None:
    """
    Enforce a minimum delay between actions sharing the same key.

    Args:
        pace_key (str | None): Identifier for a paced domain (e.g., "relay").
                               If None/empty, pacing is disabled.
        min_interval_s (float): Minimum interval between executions (seconds).
                                If <= 0, pacing is disabled.

    Returns:
        None

    Notes:
        Uses an in-process timestamp map. Not cross-process safe.
    """
    if not pace_key or min_interval_s <= 0:
        return
    now = time.time()
    last = _last_event_time.get(pace_key, 0.0)
    delta = now - last
    if delta < min_interval_s:
        time.sleep(min_interval_s - delta)
    _last_event_time[pace_key] = time.time()


# ------------------------------ Internal helpers ------------------------------

def _log_subprocess(cmd, rc, out, err, tag: str = "SUBPROC") -> None:
    """
    Log a subprocess invocation to the active TestReporter.

    Args:
        cmd (Sequence[str]): Full command vector.
        rc (int): Return code.
        out (str): Captured stdout.
        err (str): Captured stderr.
        tag (str): Arbitrary label for grouping (default: "SUBPROC").

    Returns:
        None
    """
    rep = get_active_reporter()
    if rep:
        rep.log_subprocess(cmd, rc, out, err, tag=tag)


def _ensure_dir(path: str) -> None:
    """
    Create a directory if missing. Silently ignores errors.

    Args:
        path (str): Directory path.

    Returns:
        None
    """
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass


def _ts() -> str:
    """
    Generate a filename-safe timestamp.

    Returns:
        str: 'YYYYMMDD_HHMMSS_microseconds'
    """
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _dump_http(base_url: str, path: str, method: str,
               status: int, headers: Dict[str, str], body: str,
               dump_subdir: Optional[str] = None) -> None:
    """
    Write a single HTTP transaction dump under the active reports_dir.

    Output files are written into:
        <reports_dir>/<dump_subdir>/...      (if dump_subdir is provided)

    If no reporter or no reports_dir is active, or dump_subdir is None/empty,
    nothing is written.

    Args:
        base_url (str): Base URL (e.g., "http://192.168.0.11:80").
        path (str): Request path or '' for root (e.g., "/settings").
        method (str): HTTP method label for filename (e.g., "GET", "POST").
        status (int): Response status code.
        headers (Dict[str, str]): Response headers.
        body (str): UTF-8 decoded response body.
        dump_subdir (str, optional): Subdirectory name under reports_dir.

    Returns:
        None

    Notes:
        - Filenames contain timestamp, method, sanitized path, and status.
        - I/O errors are swallowed to avoid interfering with test flow.
    """
    rep = get_active_reporter()
    dump_dir = None
    if rep and getattr(rep, "reports_dir", None) and dump_subdir:
        dump_dir = os.path.join(rep.reports_dir, dump_subdir)
    if not dump_dir:
        return
    _ensure_dir(dump_dir)
    safe_path = re.sub(r"[^A-Za-z0-9_.-]+", "_", (path or "root"))
    fname = f"{_ts()}_{method}_{safe_path}_{status}.txt"
    try:
        with open(os.path.join(dump_dir, fname), "w", encoding="utf-8", errors="replace") as f:
            f.write(f"URL: {base_url}{path}\nMETHOD: {method}\nSTATUS: {status}\n\n")
            f.write("=== HEADERS ===\n")
            for k, v in headers.items():
                f.write(f"{k}: {v}\n")
            f.write("\n=== BODY ===\n")
            f.write(body or "")
    except Exception:
        pass


def _url(base: str, path: str) -> str:
    """
    Join base URL and path.

    Args:
        base (str): Base URL, e.g., "http://host:80".
        path (str): Relative path ("/", "control") or absolute URL.

    Returns:
        str: Absolute URL. If `path` is absolute, it is returned unchanged.
    """
    if not path:
        return base
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not base.endswith("/") and not path.startswith("/"):
        return base + "/" + path
    return base + path


def _ping_once(host: str, timeout_s: float = 1.0) -> bool:
    """
    Execute a single ICMP ping using the system utility.

    Args:
        host (str): Destination hostname/IP.
        timeout_s (float): Per-packet timeout (s).

    Returns:
        bool: True if RC=0, else False.

    Reporting:
        Logs the command, RC, stdout, stderr to the active reporter.
    """
    sysname = platform.system().lower()
    if "windows" in sysname:
        cmd = ["ping", "-n", "1", "-w", str(int(timeout_s * 1000)), host]
    else:
        cmd = ["ping", "-c", "1", "-W", str(int(timeout_s)), host]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s + 2.0)
        _log_subprocess(cmd, r.returncode, r.stdout, r.stderr, tag="PING")
        return r.returncode == 0
    except Exception as e:
        _log_subprocess(cmd, 1, "", str(e), tag="PING")
        return False


def _http_request(method: str, url: str, *, timeout: float = 3.0,
                  headers: Optional[Dict[str, str]] = None,
                  data_bytes: Optional[bytes] = None) -> Tuple[int, Dict[str, str], str]:
    """
    Perform an HTTP request and return status, headers, and body.

    Args:
        method (str): HTTP method (e.g., "GET", "POST").
        url (str): Absolute URL.
        timeout (float): Socket timeout (s).
        headers (Dict[str, str], optional): Extra request headers.
        data_bytes (bytes, optional): Raw request body (form/json/etc.).

    Returns:
        Tuple[int, Dict[str, str], str]: (status, headers, body_text_utf8)

    Raises:
        EthernetTestError: On transport errors (DNS, TCP, TLS, timeout, etc.).

    Reporting:
        Logs a one-line summary (method, URL, timeout, headers preview, body length).
    """
    import http.client
    import socket
    req = urllib.request.Request(url, method=method.upper())
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    rep = get_active_reporter()
    if rep:
        h_preview = " ".join(f"{k}={repr(v)}" for k, v in (headers or {}).items())
        rep.log_info(f"[HTTP {method}] {url} timeout={timeout}s headers={h_preview or 'none'} data_len={len(data_bytes or b'')}")
    attempts = 3
    last_err = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout, data=data_bytes) as resp:
                body = resp.read()
                try:
                    text = body.decode("utf-8", errors="replace")
                except Exception:
                    text = ""
                return resp.getcode(), dict(resp.headers), text
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = (e.read() or b"").decode("utf-8", errors="replace")
            except Exception:
                pass
            return e.code, dict(getattr(e, "headers", {}) or {}), body
        except (http.client.IncompleteRead, http.client.RemoteDisconnected, socket.timeout, TimeoutError) as e:
            last_err = e
            if rep:
                rep.log_info(f"[HTTP RETRY {attempt}/{attempts}] {method} {url} due to transient error: {e}")
            time.sleep(0.15 * attempt)
            continue
        except Exception as e:
            last_err = e
            break
    raise EthernetTestError(f"{method} {url} failed: {last_err}")


# ------------------------------ Public TestActions ------------------------------

def ping_action(name: str, ip: str, count: int = 1, timeout_per_pkt: float = 1.0) -> TestAction:
    """
    Ping host one or more times and require all attempts to succeed.

    Args:
        name (str): Step name shown in reports.
        ip (str): Target host/IP.
        count (int): Number of single-packet pings (default: 1).
        timeout_per_pkt (float): Per-packet timeout in seconds (default: 1.0).

    Returns:
        TestAction: Executes pings, returns True on success.

    Raises:
        EthernetTestError: If any ping fails.

    Reporting:
        Each ping subprocess is logged (command, RC, stdout, stderr).
    """
    def execute():
        for _ in range(max(1, int(count))):
            if not _ping_once(ip, timeout_per_pkt):
                raise EthernetTestError(f"Ping to {ip} failed")
        return True
    return TestAction(name, execute)


def http_get_action(name: str, base_url: str, path: str, timeout: float,
                    *, accept_status: Tuple[int, ...] = (200, 304),
                    require_nonempty: bool = False,
                    headers: Optional[Dict[str, str]] = None,
                    dump_subdir: Optional[str] = None) -> TestAction:
    """
    GET a resource and validate status/body.

    Args:
        name (str): Step name.
        base_url (str): Base URL (e.g., "http://<ip>:<port>").
        path (str): Resource path ("/", "/control") or absolute URL.
        timeout (float): Socket timeout (s).
        accept_status (Tuple[int, ...]): Accepted status codes (default: (200, 304)).
        require_nonempty (bool): If True, body must be non-empty (default: False).
        headers (Dict[str, str], optional): Extra headers.
        dump_subdir (str, optional): If set, dumps into <reports_dir>/<dump_subdir>/.

    Returns:
        TestAction: On success returns {'status','headers','body'} dict.

    Raises:
        EthernetTestError: On transport errors or invalid status/body.

    Reporting:
        Logs summary and optionally writes a dump file.
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
    return TestAction(name, execute)


def http_post_form_action(name: str, base_url: str, path: str, form: Dict[str, Any],
                          timeout: float, *, headers: Optional[Dict[str, str]] = None,
                          accept_status: Tuple[int, ...] = (200, 202, 204),
                          dump_subdir: Optional[str] = None,
                          pace_key: Optional[str] = None,
                          min_interval_s: float = 0.0,
                          tolerate_disconnect: bool = False) -> TestAction:
    """
    POST application/x-www-form-urlencoded fields and validate the response.

    Args:
        name (str): Step name.
        base_url (str): Base URL.
        path (str): Resource path or absolute URL.
        form (Dict[str, Any]): Key-value fields to encode as form data.
        timeout (float): Socket timeout (s).
        headers (Dict[str, str], optional): Extra headers to merge.
        accept_status (Tuple[int, ...]): Accepted statuses (default: (200,202,204)).
        dump_subdir (str, optional): Dump dir under reports_dir.
        pace_key (str, optional): Pacing domain key (e.g., "relay").
        min_interval_s (float): Min delay between executions for pace_key.
        tolerate_disconnect (bool): If True, transport errors (e.g., timeout/connection
            drop during POST) are treated as **expected** and the action returns
            {'status': None, 'headers': {}, 'body': ''} instead of failing. This is
            useful for "apply settings -> device reboots" flows.

    Returns:
        TestAction: On success returns {'status','headers','body'} dict (status may be None when tolerated).

    Raises:
        EthernetTestError: On transport errors (unless tolerated) or invalid status.

    Reporting:
        Logs summary and optionally writes a dump file.

    Hardware Safety:
        If `pace_key` is provided, enforces spacing via an in-process rate limiter.
    """
    def execute():
        _pace(pace_key, min_interval_s)
        h = {"Content-Type": "application/x-www-form-urlencoded"}
        if headers:
            h.update(headers)
        data = urllib.parse.urlencode(form).encode("utf-8")
        url = _url(base_url, path)
        try:
            status, hdrs, body = _http_request("POST", url, timeout=timeout, headers=h, data_bytes=data)
        except EthernetTestError as e:
            rep = get_active_reporter()
            if tolerate_disconnect and rep:
                rep.log_info(f"[HTTP POST tolerated disconnect] {url} -> proceeding (reason: {e})")
                return {"status": None, "headers": {}, "body": ""}
            if tolerate_disconnect:
                return {"status": None, "headers": {}, "body": ""}
            raise
        _dump_http(base_url, path, "POST", status, hdrs, body, dump_subdir)
        if status not in accept_status:
            raise EthernetTestError(f"POST {path} -> {status}, body={body[:200]}")
        return {"status": status, "headers": hdrs, "body": body}
    return TestAction(name, execute)


def http_post_json_action(name: str, base_url: str, path: str, obj: Dict[str, Any],
                          timeout: float, *, headers: Optional[Dict[str, str]] = None,
                          accept_status: Tuple[int, ...] = (200, 202, 204),
                          dump_subdir: Optional[str] = None,
                          pace_key: Optional[str] = None,
                          min_interval_s: float = 0.0,
                          tolerate_disconnect: bool = False) -> TestAction:
    """
    POST a JSON body and validate the response.

    Args:
        name (str): Step name.
        base_url (str): Base URL.
        path (str): Resource path or absolute URL.
        obj (Dict[str, Any]): Object to serialize as JSON (UTF-8).
        timeout (float): Socket timeout (s).
        headers (Dict[str, str], optional): Extra headers to merge.
        accept_status (Tuple[int, ...]): Accepted statuses (default: (200,202,204)).
        dump_subdir (str, optional): Dump dir under reports_dir.
        pace_key (str, optional): Pacing domain key (e.g., "mutate").
        min_interval_s (float): Min delay between executions for pace_key.
        tolerate_disconnect (bool): If True, transport errors (e.g., timeout/connection
            drop during POST) are treated as **expected** and the action returns
            {'status': None, 'headers': {}, 'body': ''} instead of failing.

    Returns:
        TestAction: On success returns {'status','headers','body'} dict (status may be None when tolerated).

    Raises:
        EthernetTestError: On transport errors (unless tolerated) or invalid status.

    Reporting:
        Logs summary and optionally writes a dump file.

    Hardware Safety:
        Supports the same pacing controls as http_post_form_action.
    """
    def execute():
        _pace(pace_key, min_interval_s)
        h = {"Content-Type": "application/json"}
        if headers:
            h.update(headers)
        data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        url = _url(base_url, path)
        try:
            status, hdrs, body = _http_request("POST", url, timeout=timeout, headers=h, data_bytes=data)
        except EthernetTestError as e:
            rep = get_active_reporter()
            if tolerate_disconnect and rep:
                rep.log_info(f"[HTTP POST tolerated disconnect] {url} -> proceeding (reason: {e})")
                return {"status": None, "headers": {}, "body": ""}
            if tolerate_disconnect:
                return {"status": None, "headers": {}, "body": ""}
            raise
        _dump_http(base_url, path, "POST", status, hdrs, body, dump_subdir)
        if status not in accept_status:
            raise EthernetTestError(f"POST {path} -> {status}, body={body[:200]}")
        return {"status": status, "headers": hdrs, "body": body}
    return TestAction(name, execute)


def expect_header_prefix_action(name: str, base_url: str, path: str,
                                header_name: str, prefix: str,
                                timeout: float, *, dump_subdir: Optional[str] = None) -> TestAction:
    """
    GET a resource and assert that a response header starts with a given prefix.

    Args:
        name (str): Step name.
        base_url (str): Base URL.
        path (str): Resource path or absolute URL.
        header_name (str): Header to check (case-insensitive lookup attempted).
        prefix (str): Expected prefix (case-insensitive match).
        timeout (float): Socket timeout (s).
        dump_subdir (str, optional): Dump dir under reports_dir.

    Returns:
        TestAction: Returns True on success.

    Raises:
        EthernetTestError: If status is not 200/304 or header check fails.

    Reporting:
        Logs summary and optionally writes a dump file.
    """
    def execute():
        url = _url(base_url, path)
        status, hdrs, body = _http_request("GET", url, timeout=timeout)
        _dump_http(base_url, path, "GET", status, hdrs, body, dump_subdir)
        if status not in (200, 304):
            raise EthernetTestError(f"{path} unexpected status {status}")
        val = (hdrs.get(header_name) or hdrs.get(header_name.lower()) or "")
        if not str(val).lower().startswith(prefix.lower()):
            raise EthernetTestError(f"{path} header {header_name!r}='{val}' does not start with '{prefix}'")
        return True
    return TestAction(name, execute)


def etag_roundtrip_action(name: str, base_url: str, path: str, timeout: float,
                          *, dump_subdir: Optional[str] = None) -> TestAction:
    """
    Validate an ETag conditional GET roundtrip.

    Procedure:
        1) GET `path`, read ETag (fail if missing).
        2) GET with If-None-Match=<etag>, expect 304.

    Args:
        name (str): Step name.
        base_url (str): Base URL.
        path (str): Resource path or absolute URL.
        timeout (float): Socket timeout (s).
        dump_subdir (str, optional): Dump dir under reports_dir.

    Returns:
        TestAction: Returns True on success.

    Raises:
        EthernetTestError: On missing ETag or incorrect 304 behavior.

    Reporting:
        Dumps both transactions if `dump_subdir` provided.
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
            _dump_http(base_url, path, "GET-IFNM", e.code, dict(getattr(e, "headers", {}) or {}), body, dump_subdir)
            if e.code != 304:
                raise EthernetTestError(f"{path} conditional GET expected 304, got {e.code}")
        return True
    return TestAction(name, execute)


def crawl_links_action(name: str, base_url: str, path: str, timeout: float,
                       *, dump_subdir: Optional[str] = None) -> TestAction:
    """
    Crawl href/src links from a page and verify linked assets are reachable.

    Args:
        name (str): Step name.
        base_url (str): Base URL.
        path (str): Page path or absolute URL.
        timeout (float): Socket timeout (s).
        dump_subdir (str, optional): Dump dir under reports_dir.

    Returns:
        TestAction: Returns True on success.

    Raises:
        EthernetTestError: If the base page or any asset returns non-200/304.

    Reporting:
        Dumps the base page and each child link if `dump_subdir` provided.
    """
    def execute():
        s, h, body = _http_request("GET", _url(base_url, path), timeout=timeout)
        _dump_http(base_url, path, "GET", s, h, body, dump_subdir)
        if s not in (200, 304):
            raise EthernetTestError(f"{path} -> {s}")
        links = re.findall(r'''(?:href|src)\s*=\s*["']([^"']+)["']''', body, flags=re.I)
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
            raise EthernetTestError("Broken assets: " + ", ".join(bad[:10]) + ("..." if len(bad) > 10 else ""))
        return True
    return TestAction(name, execute)


def expect_status_action(name: str, base_url: str, path: str, expected_status: int,
                         timeout: float, *, method: str = "GET",
                         headers: Optional[Dict[str, str]] = None,
                         body_bytes: Optional[bytes] = None,
                         dump_subdir: Optional[str] = None) -> TestAction:
    """
    Issue an HTTP request and require an exact status code.

    Args:
        name (str): Step name.
        base_url (str): Base URL.
        path (str): Request path or absolute URL.
        expected_status (int): Required status (e.g., 404).
        timeout (float): Socket timeout (s).
        method (str): HTTP method (default: "GET").
        headers (Dict[str, str], optional): Extra headers.
        body_bytes (bytes, optional): Raw request body.
        dump_subdir (str, optional): Dump dir under reports_dir.

    Returns:
        TestAction: Returns True on success.

    Raises:
        EthernetTestError: If transport fails or status != expected_status.

    Reporting:
        Logs summary and optionally writes a dump file.
    """
    def execute():
        url = _url(base_url, path)
        status, hdrs, body = _http_request(method, url, timeout=timeout, headers=headers, data_bytes=body_bytes)
        _dump_http(base_url, path, method, status, hdrs, body, dump_subdir)
        if status != expected_status:
            raise EthernetTestError(f"{method} {path} expected {expected_status}, got {status}")
        return True
    return TestAction(name, execute)


def wait_http_ready_action(name: str, base_url: str, path: str, timeout_total: float) -> TestAction:
    """
    Poll a resource until it returns 200/304 or time budget is exhausted.

    Args:
        name (str): Step name.
        base_url (str): Base URL.
        path (str): Resource path or absolute URL.
        timeout_total (float): Total time budget (s).

    Returns:
        TestAction: Returns True if ready within budget.

    Raises:
        EthernetTestError: If readiness is not reached in time.

    Reporting:
        Each probe logs via the shared HTTP request logger; no dumps are written.
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
    return TestAction(name, execute)
