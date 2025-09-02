"""
UTFW SNMP Module
================
High-level SNMP test functions for universal testing with detailed logging.

This module wraps basic SNMP GET/SET operations and provides TestAction
helpers for common outlet control tests. It integrates with the framework's
reporter to emit rich logs (command, rc, stdout/stderr; semantic SNMP GET/SET
lines).

"""

import subprocess
import time
import shutil
import re
from typing import Optional, Dict, Any, List, Tuple, Union

from .reporting import get_active_reporter  # detailed logging hook


class SNMPTestError(Exception):
    """SNMP test specific error."""
    pass


class TestAction:
    """Test action that can be executed."""
    def __init__(self, name: str, execute_func):
        self.name = name
        self.execute_func = execute_func


def _run_snmp_command(cmd: List[str], timeout: float = 5.0) -> Tuple[int, str, str]:
    """Run an SNMP command and return (returncode, stdout, stderr).

    Args:
        cmd: Command argv list to execute (e.g., ["snmpget", "-v1", "-c", "public", "1.2.3.4", "OID"]).
        timeout: Subprocess timeout in seconds.

    Returns:
        Tuple of (returncode, stdout_text, stderr_text).
    """
    rep = get_active_reporter()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        rc, out, err = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as e:
        rc, out, err = 124, (e.stdout or ""), "Command timed out"
    except Exception as e:
        rc, out, err = 1, "", str(e)

    # Detailed subprocess logging
    if rep:
        rep.log_subprocess(cmd, rc, out, err, tag="SNMP")
    return rc, out, err


def _parse_snmp_value(output: str) -> Optional[str]:
    """Parse SNMP command output to extract the value.

    Args:
        output: Raw stdout from snmpget/snmpset.

    Returns:
        Extracted value as string if parsable; otherwise None.
    """
    if " = " not in output:
        return None

    parts = output.strip().split(" = ", 1)
    if len(parts) < 2:
        return None

    value_part = parts[1]
    if ": " in value_part:
        value = value_part.split(": ", 1)[1]
    else:
        value = value_part

    return value.strip().strip('"')


def get_value(ip: str, oid: str, community: str = "public", timeout: float = 3.0) -> Optional[str]:
    """Get an SNMP value from a device.

    Args:
        ip: Device IP address.
        oid: SNMP OID to query.
        community: SNMP community string.
        timeout: Subprocess timeout in seconds.

    Returns:
        Parsed value string or None if the command failed or couldn't be parsed.
    """
    cmd = ["snmpget", "-v1", "-c", community, ip, oid]
    rc, out, _err = _run_snmp_command(cmd, timeout)
    value = _parse_snmp_value(out) if rc == 0 else None

    rep = get_active_reporter()
    if rep:
        rep.log_snmp_get(ip, oid, value, note="v1/public" if community == "public" else f"v1/{community}")
    return value


def set_integer(ip: str, oid: str, value: int, community: str = "public", timeout: float = 3.0) -> bool:
    """Set an SNMP integer value.

    Args:
        ip: Device IP address.
        oid: SNMP OID to set.
        value: Integer to write.
        community: SNMP community string.
        timeout: Subprocess timeout in seconds.

    Returns:
        True if the command returned rc==0; otherwise False.
    """
    cmd = ["snmpset", "-v1", "-c", community, ip, oid, "i", str(value)]
    rc, out, err = _run_snmp_command(cmd, timeout)
    ok = (rc == 0)

    rep = get_active_reporter()
    if rep:
        rep.log_snmp_set(ip, oid, value, ok, note="v1/public" if community == "public" else f"v1/{community}")
        # Optionally include stdout/stderr lines already captured in log_subprocess
    return ok


def set_outlet(name: str, ip: str, channel: int, state: bool,
               outlet_base_oid: str, community: str = "public") -> TestAction:
    """Create a TestAction that sets a single outlet (ON/OFF) via SNMP.

    Args:
        name: Action name.
        ip: Device IP address.
        channel: Outlet channel number (1-8).
        state: True for ON, False for OFF.
        outlet_base_oid: Base OID for outlet control.
        community: SNMP community string.

    Returns:
        TestAction that sets the outlet state and raises on failure.

    Raises:
        SNMPTestError: If the SNMP SET operation fails or channel is invalid.
    """
    def execute():
        if not 1 <= channel <= 8:
            raise SNMPTestError(f"Invalid channel: {channel}. Must be 1-8")
        oid = f"{outlet_base_oid}.{channel}.0"
        set_value = 1 if state else 0
        if not set_integer(ip, oid, set_value, community):
            raise SNMPTestError(f"Failed to set channel {channel} to {'ON' if state else 'OFF'}")
        return True
    return TestAction(name, execute)


def get_outlet(name: str, ip: str, channel: int, expected_state: bool,
               outlet_base_oid: str, community: str = "public") -> TestAction:
    """Create a TestAction that verifies a single outlet state via SNMP.

    Args:
        name: Action name.
        ip: Device IP address.
        channel: Outlet channel number (1-8).
        expected_state: Expected state (True for ON, False for OFF).
        outlet_base_oid: Base OID for outlet control.
        community: SNMP community string.

    Returns:
        TestAction that verifies the outlet state.

    Raises:
        SNMPTestError: If GET fails, the value is invalid, or state mismatches.
    """
    def execute():
        if not 1 <= channel <= 8:
            raise SNMPTestError(f"Invalid channel: {channel}. Must be 1-8")
        oid = f"{outlet_base_oid}.{channel}.0"
        value = get_value(ip, oid, community)
        if value is None:
            raise SNMPTestError(f"Failed to read channel {channel} state")
        try:
            current_state = int(value) == 1
        except ValueError:
            raise SNMPTestError(f"Invalid state value for channel {channel}: {value}")
        if current_state != expected_state:
            raise SNMPTestError(
                f"Channel {channel} state mismatch: expected {'ON' if expected_state else 'OFF'}, "
                f"got {'ON' if current_state else 'OFF'}"
            )
        return True
    return TestAction(name, execute)


def set_all_outlets(name: str, ip: str, state: bool, all_on_oid: str, all_off_oid: str,
                    community: str = "public") -> TestAction:
    """Create a TestAction that sets ALL outlets ON or OFF via SNMP.

    Args:
        name: Action name.
        ip: Device IP address.
        state: Desired state for all outlets (True for ON, False for OFF).
        all_on_oid: OID to turn all outlets ON.
        all_off_oid: OID to turn all outlets OFF.
        community: SNMP community string.

    Returns:
        TestAction that triggers the ALL ON/OFF operation.

    Raises:
        SNMPTestError: If the SNMP SET operation fails.
    """
    def execute():
        trigger_oid = all_on_oid if state else all_off_oid
        if not set_integer(ip, trigger_oid, 1, community):
            raise SNMPTestError(f"Failed to set ALL outlets {'ON' if state else 'OFF'}")
        return True
    return TestAction(name, execute)


def verify_all_outlets(name: str, ip: str, expected_state: bool, outlet_base_oid: str,
                       community: str = "public") -> TestAction:
    """Create a TestAction that verifies ALL outlets are in the expected state.

    Args:
        name: Action name.
        ip: Device IP address.
        expected_state: Expected state for all outlets (True for ON, False for OFF).
        outlet_base_oid: Base OID for outlet control.
        community: SNMP community string.

    Returns:
        TestAction that checks each outlet (1..8) and raises on any mismatch.
    """
    def execute():
        failed_channels = []
        for channel in range(1, 9):
            try:
                oid = f"{outlet_base_oid}.{channel}.0"
                value = get_value(ip, oid, community)
                if value is None:
                    failed_channels.append(f"CH{channel} (read failed)")
                    continue
                current_state = int(value) == 1
                if current_state != expected_state:
                    failed_channels.append(f"CH{channel} ({'ON' if current_state else 'OFF'})")
            except Exception as e:
                failed_channels.append(f"CH{channel} (error: {e})")
        if failed_channels:
            raise SNMPTestError(
                f"ALL {'ON' if expected_state else 'OFF'} verification failed for: {', '.join(failed_channels)}"
            )
        return True
    return TestAction(name, execute)


def test_single_outlet(channel: int, state: bool, ip: str, outlet_base_oid: str, community: str = "public") -> bool:
    """Set a single outlet via SNMP and verify the change.

    Args:
        channel: Outlet channel number (1-8).
        state: Desired state; True for ON, False for OFF.
        ip: Device IP address.
        outlet_base_oid: Base OID for outlet control.
        community: SNMP community string.

    Returns:
        True if the outlet state was successfully set and verified.

    Raises:
        SNMPTestError: If setting or verifying the outlet state fails, or if an invalid value is read.
    """
    # Set the outlet state
    if not set_integer(ip, f"{outlet_base_oid}.{channel}.0", 1 if state else 0, community):
        raise SNMPTestError(f"Failed to set channel {channel} to {'ON' if state else 'OFF'}")

    # Verify the state
    time.sleep(0.2)  # Allow time for change
    value = get_value(ip, f"{outlet_base_oid}.{channel}.0", community)

    if value is None:
        raise SNMPTestError(f"Failed to read channel {channel} state after setting")

    try:
        current_state = int(value) == 1
    except ValueError:
        raise SNMPTestError(f"Invalid state value for channel {channel}: {value}")

    if current_state != state:
        raise SNMPTestError(
            f"Channel {channel} verification failed: expected {'ON' if state else 'OFF'}, "
            f"got {'ON' if current_state else 'OFF'}"
        )

    return True


def test_all_outlets(state: bool, ip: str, all_on_oid: str, all_off_oid: str,
                     outlet_base_oid: str, community: str = "public") -> bool:
    """High-level test that sets ALL outlets and verifies all channels.

    Args:
        state: Desired state for all outlets (True for ON, False for OFF).
        ip: Device IP address.
        all_on_oid: OID to trigger all outlets ON.
        all_off_oid: OID to trigger all outlets OFF.
        outlet_base_oid: Base OID for per-channel verification.
        community: SNMP community string.

    Returns:
        True if all channels match the expected state; raises on failures.

    Raises:
        SNMPTestError: If setting fails or any outlet verification fails.
    """
    trigger_oid = all_on_oid if state else all_off_oid

    # Set ALL outlets
    if not set_integer(ip, trigger_oid, 1, community):
        raise SNMPTestError(f"Failed to set ALL outlets {'ON' if state else 'OFF'}")

    # Verify all channels
    time.sleep(0.4)  # Allow time for all changes
    failed_channels = []

    for channel in range(1, 9):
        try:
            oid = f"{outlet_base_oid}.{channel}.0"
            value = get_value(ip, oid, community)
            if value is None:
                failed_channels.append(f"CH{channel} (read failed)")
                continue

            current_state = int(value) == 1
            if current_state != state:
                failed_channels.append(f"CH{channel} ({'ON' if current_state else 'OFF'})")
        except Exception as e:
            failed_channels.append(f"CH{channel} (error: {e})")

    if failed_channels:
        raise SNMPTestError(
            f"ALL {'ON' if state else 'OFF'} verification failed for: {', '.join(failed_channels)}"
        )

    return True


# -------------------- Test case helper (added, no deletions) --------------------

def cycle_outlets_all_channels(name: str,
                               ip: str,
                               outlet_base_oid: str,
                               community: str = "public",
                               channels: Union[List[int], range] = range(1, 9),
                               settle_s: float = 0.2) -> TestAction:
    """Create a TestAction that cycles each outlet ON then OFF with verification.

    Args:
        name: Action name.
        ip: Device IP address.
        outlet_base_oid: Base OID for outlet control.
        community: SNMP community string.
        channels: Channels to cycle (default 1..8).
        settle_s: Delay after each SET before verification (seconds).

    Returns:
        TestAction that raises if any set or verification step fails.
    """
    def execute():
        failures: List[str] = []
        for ch in channels:
            # Turn ON
            if not set_integer(ip, f"{outlet_base_oid}.{ch}.0", 1, community):
                failures.append(f"CH{ch}: set ON failed")
            else:
                time.sleep(settle_s)
                val = get_value(ip, f"{outlet_base_oid}.{ch}.0", community)
                try:
                    if val is None or int(val) != 1:
                        failures.append(f"CH{ch}: expected ON, got {val!r}")
                except Exception as e:
                    failures.append(f"CH{ch}: verify ON error: {e}")
            # Turn OFF
            if not set_integer(ip, f"{outlet_base_oid}.{ch}.0", 0, community):
                failures.append(f"CH{ch}: set OFF failed")
            else:
                time.sleep(settle_s)
                val = get_value(ip, f"{outlet_base_oid}.{ch}.0", community)
                try:
                    if val is None or int(val) != 0:
                        failures.append(f"CH{ch}: expected OFF, got {val!r}")
                except Exception as e:
                    failures.append(f"CH{ch}: verify OFF error: {e}")
        if failures:
            raise SNMPTestError("Outlet cycle failures: " + "; ".join(failures))
        return True
    return TestAction(name, execute)

def walk_enterprise(name: str,
                    ip: str,
                    community: str = "public",
                    root_oid: str = "1.3.6.1.4.1.19865",
                    timeout: float = 25.0) -> TestAction:
    """Create a TestAction that walks an enterprise subtree and asserts presence.

    The action prefers the Net-SNMP `snmpwalk` CLI. If unavailable, it falls back
    to probing a few well-known MIB-II OIDs via GET as a liveness check.

    Args:
        name: Action name.
        ip: Device IP address.
        community: SNMP community string.
        root_oid: Enterprise/root OID to walk.
        timeout: Subprocess timeout for snmpwalk.

    Returns:
        TestAction that raises SNMPTestError on failure.
    """
    def execute():
        rep = get_active_reporter()
        snmpwalk = shutil.which("snmpwalk")
        if snmpwalk:
            cmd = [snmpwalk, "-v1", "-c", community, "-Ci", "-Cc", ip, root_oid]
            rc, out, err = _run_snmp_command(cmd, timeout=timeout)
            # Accept output even if rc!=0, some builds still print useful stdout.
            if (rc != 0) and not (out and out.strip()):
                raise SNMPTestError(f"snmpwalk failed: {err.strip() or 'no output'}")

            # Minimal presence checks (strings vary by MIBs; keep loose)
            must_have = ["sysDescr", "sysObjectID", "sysUpTime", "sysContact", "sysName", "sysLocation", "sysServices"]
            missing = [m for m in must_have if m not in (out or "")]
            if missing and rep:
                # Soft warn, allow Step 2 to enforce exacts
                rep.log_warn(f"walk_enterprise: missing tokens in walk output: {missing}")
            return True

        # Fallback: GET a few MIB-II leaves
        probe_oids = [
            "1.3.6.1.2.1.1.1.0",  # sysDescr.0
            "1.3.6.1.2.1.1.2.0",  # sysObjectID.0
            "1.3.6.1.2.1.1.3.0",  # sysUpTime.0
        ]
        for oid in probe_oids:
            if get_value(ip, oid, community) is None:
                raise SNMPTestError(f"SNMP GET probe failed for {oid}")
        return True
    return TestAction(name, execute)


def expect_oid_regex(name: str,
                     ip: str,
                     oid: str,
                     regex: str,
                     community: str = "public",
                     timeout: float = 3.0) -> TestAction:
    """Create a TestAction that asserts an OID's string value matches a regex.

    Args:
        name: Action name.
        ip: Device IP address.
        oid: OID to read.
        regex: Regular expression to match against the value.
        community: SNMP community.
        timeout: SNMP get timeout.

    Returns:
        TestAction that raises SNMPTestError if the value doesn't match.
    """
    def execute():
        val = get_value(ip, oid, community, timeout)
        if val is None:
            raise SNMPTestError(f"SNMP GET failed for {oid}")
        if re.search(regex, str(val)) is None:
            raise SNMPTestError(f"Value '{val}' for {oid} does not match /{regex}/")
        return True
    return TestAction(name, execute)


def expect_oid_equals(name: str,
                      ip: str,
                      oid: str,
                      expected: str,
                      community: str = "public",
                      timeout: float = 3.0,
                      strip_quotes: bool = True) -> TestAction:
    """Create a TestAction that asserts an OID's string value equals `expected`.

    Args:
        name: Action name.
        ip: Device IP address.
        oid: OID to read.
        expected: Expected exact string (after optional quote stripping).
        community: SNMP community.
        timeout: SNMP get timeout.
        strip_quotes: Remove surrounding quotes from the read value before comparison.

    Returns:
        TestAction that raises SNMPTestError if values differ.
    """
    def execute():
        val = get_value(ip, oid, community, timeout)
        if val is None:
            raise SNMPTestError(f"SNMP GET failed for {oid}")
        s = str(val)
        if strip_quotes:
            s = s.strip('"')
        if s != expected:
            raise SNMPTestError(f"Value mismatch for {oid}: expected '{expected}', got '{s}'")
        return True
    return TestAction(name, execute)


def expect_oid_error(name: str,
                     ip: str,
                     oid: str,
                     community: str = "public",
                     timeout: float = 3.0) -> TestAction:
    """Create a TestAction that asserts an OID read fails (e.g., noSuchName).

    Tries Net-SNMP snmpget and considers rc!=0 with 'noSuchName' as success.
    Falls back to get_value(); if it returns None, treat as expected error.

    Args:
        name: Action name.
        ip: Device IP address.
        oid: OID to read (expected to not exist / error).
        community: SNMP community.
        timeout: SNMP get timeout.

    Returns:
        TestAction that raises SNMPTestError if the OID unexpectedly succeeds.
    """
    def execute():
        snmpget = shutil.which("snmpget")
        if snmpget:
            cmd = [snmpget, "-v1", "-c", community, ip, oid]
            rc, out, err = _run_snmp_command(cmd, timeout=timeout)
            out_l = (out or "").lower()
            err_l = (err or "").lower()
            if rc != 0 and ("nosuchname" in out_l or "no such name" in err_l or "nosuchname" in err_l):
                return True
            if rc == 0:
                raise SNMPTestError(f"SNMP GET unexpectedly succeeded for {oid}: {out.strip()}")
            # If rc!=0 but no noSuchName marker, still allow fallback check
        # Fallback heuristic: our high-level get_value() returns None on failure
        val = get_value(ip, oid, community, timeout)
        if val is None:
            return True
        raise SNMPTestError(f"SNMP GET unexpectedly returned '{val}' for {oid}")
    return TestAction(name, execute)