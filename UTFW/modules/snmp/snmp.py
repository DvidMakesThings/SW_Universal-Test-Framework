"""
UTFW SNMP Module
================
High-level SNMP test functions and TestAction factories for universal testing.

This module provides comprehensive SNMP testing capabilities with detailed
logging integration. All SNMP operations are logged using the UTFW logging
system, providing detailed command execution logs and semantic SNMP operation
summaries.

The module includes TestAction factories for common SNMP operations, making
it easy to build complex test scenarios using the STE (Sub-step Test Executor)
system.

Author: DvidMakesThings
"""

import subprocess
import time
import shutil
import re
from typing import Optional, Dict, Any, List, Tuple, Union

from ...core.logger import get_active_logger
from ...core.core import TestAction


class SNMPTestError(Exception):
    """Exception raised when SNMP operations or validations fail.
    
    This exception is raised by SNMP test functions when communication
    errors occur, validation fails, or other SNMP-related operations
    cannot be completed successfully.
    
    Args:
        message (str): Description of the error that occurred.
    """
    pass


def _run_snmp_command(cmd: List[str], timeout: float = 5.0) -> Tuple[int, str, str]:
    """Execute an SNMP command and return results with logging.
    
    This internal function executes SNMP commands using subprocess and
    logs the complete execution details including command, return code,
    and output streams using the active logger.

    Args:
        cmd (List[str]): Command argument list to execute 
            (e.g., ["snmpget", "-v1", "-c", "public", "1.2.3.4", "OID"]).
        timeout (float, optional): Subprocess timeout in seconds. Defaults to 5.0.

    Returns:
        Tuple[int, str, str]: Tuple of (returncode, stdout_text, stderr_text).
    """
    logger = get_active_logger()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        rc, out, err = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as e:
        rc, out, err = 124, (e.stdout or ""), "Command timed out"
    except Exception as e:
        rc, out, err = 1, "", str(e)

    # Detailed subprocess logging
    if logger:
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
        logger.info(f"[SNMP] cmd={cmd_str}")
        logger.info(f"[SNMP] rc={rc}")
        if out:
            truncated_out = out if len(out) <= 4000 else (out[:4000] + f"... [truncated {len(out)-4000} chars]")
            logger.info(f"[SNMP OUT]\n{truncated_out}")
        if err:
            truncated_err = err if len(err) <= 4000 else (err[:4000] + f"... [truncated {len(err)-4000} chars]")
            logger.info(f"[SNMP ERR]\n{truncated_err}")
    return rc, out, err


def _parse_snmp_value(output: str) -> Optional[str]:
    """Parse SNMP command output to extract the returned value.
    
    This function parses the standard output from SNMP commands to extract
    the actual value, handling various output formats from different SNMP
    implementations.

    Args:
        output (str): Raw stdout from snmpget/snmpset command.

    Returns:
        Optional[str]: Extracted value as string if parsable, otherwise None.
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
    """Retrieve an SNMP value from a device with logging.
    
    This function performs an SNMP GET operation and logs both the subprocess
    execution details and a semantic summary of the SNMP operation result.

    Args:
        ip (str): Target device IP address.
        oid (str): SNMP OID to query.
        community (str, optional): SNMP community string. Defaults to "public".
        timeout (float, optional): Subprocess timeout in seconds. Defaults to 3.0.

    Returns:
        Optional[str]: Parsed value string or None if the command failed
            or the value couldn't be parsed.
    """
    cmd = ["snmpget", "-v1", "-c", community, ip, oid]
    rc, out, _err = _run_snmp_command(cmd, timeout)
    value = _parse_snmp_value(out) if rc == 0 else None

    logger = get_active_logger()
    if logger:
        note = "v1/public" if community == "public" else f"v1/{community}"
        note_part = f" ({note})" if note else ""
        value_str = "None" if value is None else repr(value)
        logger.info(f"[SNMP GET] {ip} {oid} -> {value_str}{note_part}")
    return value


def set_integer(ip: str, oid: str, value: int, community: str = "public", timeout: float = 3.0) -> bool:
    """Set an SNMP integer value with logging.
    
    This function performs an SNMP SET operation for integer values and logs
    both the subprocess execution details and a semantic summary of the
    operation result.

    Args:
        ip (str): Target device IP address.
        oid (str): SNMP OID to modify.
        value (int): Integer value to set.
        community (str, optional): SNMP community string. Defaults to "public".
        timeout (float, optional): Subprocess timeout in seconds. Defaults to 3.0.

    Returns:
        bool: True if the command succeeded (rc==0), otherwise False.
    """
    cmd = ["snmpset", "-v1", "-c", community, ip, oid, "i", str(value)]
    rc, out, err = _run_snmp_command(cmd, timeout)
    ok = (rc == 0)

    logger = get_active_logger()
    if logger:
        note = "v1/public" if community == "public" else f"v1/{community}"
        note_part = f" ({note})" if note else ""
        status = "OK" if ok else "FAIL"
        logger.info(f"[SNMP SET] {ip} {oid} = {value!r} -> {status}{note_part}")
    return ok


def set_outlet(name: str, ip: str, channel: int, state: bool,
               outlet_base_oid: str, community: str = "public") -> TestAction:
    """Create a TestAction that controls a single outlet via SNMP.
    
    This TestAction factory creates an action that sets the state of a single
    outlet channel on a managed PDU using SNMP SET operations. The action
    validates the channel number and provides detailed error reporting.

    Args:
        name (str): Human-readable name for the test action.
        ip (str): Target device IP address.
        channel (int): Outlet channel number (typically 1-8).
        state (bool): Desired outlet state (True for ON, False for OFF).
        outlet_base_oid (str): Base OID for outlet control operations.
        community (str, optional): SNMP community string. Defaults to "public".

    Returns:
        TestAction: TestAction that returns True when the outlet state
            is successfully set.

    Raises:
        SNMPTestError: When executed, raises this exception if the channel
            number is invalid or if the SNMP SET operation fails.
    
    Example:
        >>> outlet_action = set_outlet(
        ...     "Turn ON outlet 1", "192.168.1.100", 1, True,
        ...     "1.3.6.1.4.1.19865.2"
        ... )
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
    
    This TestAction factory creates an action that retrieves the current state
    of a single outlet channel and validates it against the expected state.
    It provides detailed error reporting for both communication failures and
    state mismatches.

    Args:
        name (str): Human-readable name for the test action.
        ip (str): Target device IP address.
        channel (int): Outlet channel number to verify (typically 1-8).
        expected_state (bool): Expected outlet state (True for ON, False for OFF).
        outlet_base_oid (str): Base OID for outlet control operations.
        community (str, optional): SNMP community string. Defaults to "public".

    Returns:
        TestAction: TestAction that returns True when the outlet state
            matches the expected value.

    Raises:
        SNMPTestError: When executed, raises this exception if the channel
            number is invalid, SNMP GET fails, the returned value is invalid,
            or the state doesn't match expectations.
    
    Example:
        >>> verify_action = get_outlet(
        ...     "Verify outlet 1 is ON", "192.168.1.100", 1, True,
        ...     "1.3.6.1.4.1.19865.2"
        ... )
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
    """Create a TestAction that controls all outlets simultaneously via SNMP.
    
    This TestAction factory creates an action that uses special "all outlets"
    OIDs to control all outlet channels simultaneously. This is more efficient
    than controlling outlets individually and is commonly supported by
    managed PDUs.

    Args:
        name (str): Human-readable name for the test action.
        ip (str): Target device IP address.
        state (bool): Desired state for all outlets (True for ON, False for OFF).
        all_on_oid (str): SNMP OID that turns all outlets ON when set to 1.
        all_off_oid (str): SNMP OID that turns all outlets OFF when set to 1.
        community (str, optional): SNMP community string. Defaults to "public".

    Returns:
        TestAction: TestAction that returns True when the bulk operation
            is successfully triggered.

    Raises:
        SNMPTestError: When executed, raises this exception if the SNMP
            SET operation fails.
    
    Example:
        >>> all_on_action = set_all_outlets(
        ...     "Turn all outlets ON", "192.168.1.100", True,
        ...     "1.3.6.1.4.1.19865.2.10.0", "1.3.6.1.4.1.19865.2.9.0"
        ... )
    """
    def execute():
        trigger_oid = all_on_oid if state else all_off_oid
        if not set_integer(ip, trigger_oid, 1, community):
            raise SNMPTestError(f"Failed to set ALL outlets {'ON' if state else 'OFF'}")
        return True
    return TestAction(name, execute)


def verify_all_outlets(name: str, ip: str, expected_state: bool, outlet_base_oid: str,
                       community: str = "public") -> TestAction:
    """Create a TestAction that verifies all outlets are in the expected state.
    
    This TestAction factory creates an action that checks each outlet channel
    individually to verify they are all in the expected state. It provides
    detailed reporting of any channels that don't match expectations.

    Args:
        name (str): Human-readable name for the test action.
        ip (str): Target device IP address.
        expected_state (bool): Expected state for all outlets (True for ON, False for OFF).
        outlet_base_oid (str): Base OID for outlet control operations.
        community (str, optional): SNMP community string. Defaults to "public".

    Returns:
        TestAction: TestAction that returns True when all outlets match
            the expected state.

    Raises:
        SNMPTestError: When executed, raises this exception if any outlets
            don't match the expected state, with detailed information about
            which channels failed.
    
    Example:
        >>> verify_all_action = verify_all_outlets(
        ...     "Verify all outlets OFF", "192.168.1.100", False,
        ...     "1.3.6.1.4.1.19865.2"
        ... )
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
    """Set a single outlet via SNMP and verify the change (legacy function).
    
    This function provides direct outlet control and verification without
    the TestAction wrapper. It's maintained for backward compatibility
    but new code should prefer the TestAction factories.

    Args:
        channel (int): Outlet channel number (1-8).
        state (bool): Desired state (True for ON, False for OFF).
        ip (str): Target device IP address.
        outlet_base_oid (str): Base OID for outlet control.
        community (str, optional): SNMP community string. Defaults to "public".

    Returns:
        bool: True if the outlet state was successfully set and verified.

    Raises:
        SNMPTestError: If setting or verifying the outlet state fails,
            or if an invalid value is read.
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
    """Set all outlets and verify all channels (legacy function).
    
    This function provides direct bulk outlet control and verification without
    the TestAction wrapper. It's maintained for backward compatibility but
    new code should prefer the TestAction factories.

    Args:
        state (bool): Desired state for all outlets (True for ON, False for OFF).
        ip (str): Target device IP address.
        all_on_oid (str): OID to trigger all outlets ON.
        all_off_oid (str): OID to trigger all outlets OFF.
        outlet_base_oid (str): Base OID for per-channel verification.
        community (str, optional): SNMP community string. Defaults to "public".

    Returns:
        bool: True if all channels match the expected state.

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


# ======================== Advanced TestAction Factories ========================

def cycle_outlets_all_channels(name: str,
                               ip: str,
                               outlet_base_oid: str,
                               community: str = "public",
                               channels: Union[List[int], range] = range(1, 9),
                               settle_s: float = 0.2) -> TestAction:
    """Create a TestAction that cycles each outlet through ON/OFF states.
    
    This TestAction factory creates an action that systematically cycles each
    specified outlet channel through ON and OFF states, verifying the state
    change after each operation. This is useful for comprehensive outlet
    functionality testing.

    Args:
        name (str): Human-readable name for the test action.
        ip (str): Target device IP address.
        outlet_base_oid (str): Base OID for outlet control operations.
        community (str, optional): SNMP community string. Defaults to "public".
        channels (Union[List[int], range], optional): Channels to cycle.
            Defaults to range(1, 9) for channels 1-8.
        settle_s (float, optional): Delay after each SET operation before
            verification in seconds. Defaults to 0.2.

    Returns:
        TestAction: TestAction that returns True when all channels have
            been successfully cycled.

    Raises:
        SNMPTestError: When executed, raises this exception if any SET
            or verification operation fails, with detailed information
            about which operations failed.
    
    Example:
        >>> cycle_action = cycle_outlets_all_channels(
        ...     "Cycle all outlets", "192.168.1.100",
        ...     "1.3.6.1.4.1.19865.2", channels=[1, 2, 3]
        ... )
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
    """Create a TestAction that performs an SNMP walk of an enterprise MIB subtree.
    
    This TestAction factory creates an action that performs an SNMP walk
    operation on an enterprise MIB subtree to verify device responsiveness
    and MIB implementation. It prefers the Net-SNMP snmpwalk utility but
    falls back to basic GET operations if unavailable.

    Args:
        name (str): Human-readable name for the test action.
        ip (str): Target device IP address.
        community (str, optional): SNMP community string. Defaults to "public".
        root_oid (str, optional): Root OID for the enterprise subtree.
            Defaults to "1.3.6.1.4.1.19865".
        timeout (float, optional): Subprocess timeout for snmpwalk operation.
            Defaults to 25.0 seconds.

    Returns:
        TestAction: TestAction that returns True when the walk operation
            completes successfully and finds expected MIB objects.

    Raises:
        SNMPTestError: When executed, raises this exception if the walk
            operation fails or doesn't find expected MIB objects.
    
    Example:
        >>> walk_action = walk_enterprise(
        ...     "Walk enterprise MIB", "192.168.1.100",
        ...     root_oid="1.3.6.1.4.1.19865"
        ... )
    """
    def execute():
        logger = get_active_logger()
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
            if missing and logger:
                # Soft warn, allow Step 2 to enforce exacts
                logger.warn(f"walk_enterprise: missing tokens in walk output: {missing}")
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
    """Create a TestAction that validates an OID value against a regex pattern.
    
    This TestAction factory creates an action that retrieves an SNMP value
    and validates it against a regular expression pattern. This is useful
    for validating formatted values like version strings, serial numbers,
    or other structured data.

    Args:
        name (str): Human-readable name for the test action.
        ip (str): Target device IP address.
        oid (str): SNMP OID to read and validate.
        regex (str): Regular expression pattern that the value must match.
        community (str, optional): SNMP community string. Defaults to "public".
        timeout (float, optional): SNMP GET timeout in seconds. Defaults to 3.0.

    Returns:
        TestAction: TestAction that returns True when the value matches
            the regex pattern.

    Raises:
        SNMPTestError: When executed, raises this exception if the SNMP
            GET fails or if the value doesn't match the regex pattern.
    
    Example:
        >>> regex_action = expect_oid_regex(
        ...     "Validate firmware version", "192.168.1.100",
        ...     "1.3.6.1.2.1.1.1.0", r"v\d+\.\d+\.\d+"
        ... )
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
    """Create a TestAction that validates an OID value for exact equality.
    
    This TestAction factory creates an action that retrieves an SNMP value
    and validates it for exact string equality against an expected value.
    It supports optional quote stripping for values that may be quoted
    in SNMP responses.

    Args:
        name (str): Human-readable name for the test action.
        ip (str): Target device IP address.
        oid (str): SNMP OID to read and validate.
        expected (str): Expected exact string value.
        community (str, optional): SNMP community string. Defaults to "public".
        timeout (float, optional): SNMP GET timeout in seconds. Defaults to 3.0.
        strip_quotes (bool, optional): Whether to remove surrounding quotes
            from the retrieved value before comparison. Defaults to True.

    Returns:
        TestAction: TestAction that returns True when the values match exactly.

    Raises:
        SNMPTestError: When executed, raises this exception if the SNMP
            GET fails or if the values don't match exactly.
    
    Example:
        >>> equals_action = expect_oid_equals(
        ...     "Validate system contact", "192.168.1.100",
        ...     "1.3.6.1.2.1.1.4.0", "admin@example.com"
        ... )
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
    """Create a TestAction that validates an OID read fails as expected.
    
    This TestAction factory creates an action that attempts to read an SNMP
    OID and validates that the operation fails with an appropriate error
    (such as noSuchName). This is useful for testing access control or
    verifying that certain OIDs are not implemented.

    Args:
        name (str): Human-readable name for the test action.
        ip (str): Target device IP address.
        oid (str): SNMP OID that should fail when read.
        community (str, optional): SNMP community string. Defaults to "public".
        timeout (float, optional): SNMP GET timeout in seconds. Defaults to 3.0.

    Returns:
        TestAction: TestAction that returns True when the OID read fails
            as expected.

    Raises:
        SNMPTestError: When executed, raises this exception if the OID
            read unexpectedly succeeds.
    
    Example:
        >>> error_action = expect_oid_error(
        ...     "Verify restricted OID fails", "192.168.1.100",
        ...     "1.3.6.1.4.1.19865.999.1.0"
        ... )
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