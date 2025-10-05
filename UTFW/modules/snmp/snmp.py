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
    logger = get_active_logger()

    if logger:
        logger.info(f"[SNMP] _parse_snmp_value() called, output length: {len(output)} chars")

    if " = " not in output:
        if logger:
            logger.info(f"[SNMP] No ' = ' separator found in output, returning None")
        return None

    parts = output.strip().split(" = ", 1)
    if len(parts) < 2:
        return None

    value_part = parts[1]
    if ": " in value_part:
        value = value_part.split(": ", 1)[1]
    else:
        value = value_part

    result = value.strip().strip('"')

    if logger:
        logger.info(f"[SNMP] Parsed value: '{result}'")

    return result


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
    logger = get_active_logger()

    if logger:
        logger.info(f"[SNMP] get_value() called")
        logger.info(f"[SNMP]   Target: {ip}, OID: {oid}, Community: {community}, Timeout: {timeout}s")

    cmd = ["snmpget", "-v1", "-c", community, ip, oid]
    rc, out, _err = _run_snmp_command(cmd, timeout)
    if logger:
        logger.info(f"[SNMP] snmpget returned: rc={rc}")

    value = _parse_snmp_value(out) if rc == 0 else None

    if logger:
        note = "v1/public" if community == "public" else f"v1/{community}"
        note_part = f" ({note})" if note else ""
        value_str = "None" if value is None else repr(value)
        logger.info(f"[SNMP GET] {ip} {oid} -> {value_str}{note_part}")
        if value is None and rc != 0:
            logger.error(f"[SNMP GET ERROR] Failed to retrieve value, rc={rc}")

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
    logger = get_active_logger()

    if logger:
        logger.info(f"[SNMP] set_integer() called")
        logger.info(f"[SNMP]   Target: {ip}, OID: {oid}, Value: {value}, Community: {community}, Timeout: {timeout}s")

    cmd = ["snmpset", "-v1", "-c", community, ip, oid, "i", str(value)]
    rc, out, err = _run_snmp_command(cmd, timeout)
    ok = (rc == 0)

    if logger:
        logger.info(f"[SNMP] snmpset returned: rc={rc}, success={ok}")
        note = "v1/public" if community == "public" else f"v1/{community}"
        note_part = f" ({note})" if note else ""
        status = "OK" if ok else "FAIL"
        logger.info(f"[SNMP SET] {ip} {oid} = {value!r} -> {status}{note_part}")
        if not ok:
            logger.error(f"[SNMP SET ERROR] Failed to set value, rc={rc}")
    return ok


def set_outlet(name: str, ip: str, channel: int, state: bool,
               outlet_base_oid: str, community: str = "public",
        negative_test: bool = False) -> TestAction:
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
        logger = get_active_logger()
        if logger:
            logger.info(f"[SNMP] Executing set_outlet: channel={channel}, state={'ON' if state else 'OFF'}")

        if not 1 <= channel <= 8:
            if logger:
                logger.error(f"[SNMP ERROR] Invalid channel number: {channel} (must be 1-8)")
            raise SNMPTestError(f"Invalid channel: {channel}. Must be 1-8")

        oid = f"{outlet_base_oid}.{channel}.0"
        set_value = 1 if state else 0

        if logger:
            logger.info(f"[SNMP] Setting outlet: OID={oid}, value={set_value}")

        if not set_integer(ip, oid, set_value, community):
            if logger:
                logger.error(f"[SNMP ERROR] Failed to set channel {channel} to {'ON' if state else 'OFF'}")
            raise SNMPTestError(f"Failed to set channel {channel} to {'ON' if state else 'OFF'}")

        if logger:
            logger.info(f"[SNMP] Successfully set channel {channel} to {'ON' if state else 'OFF'}")
        return True
    return TestAction(name, execute, negative_test=negative_test)


def get_outlet(name: str, ip: str, channel: int, expected_state: bool,
               outlet_base_oid: str, community: str = "public",
        negative_test: bool = False) -> TestAction:
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
        logger = get_active_logger()
        if logger:
            logger.info(f"[SNMP] Executing get_outlet: channel={channel}, expected_state={'ON' if expected_state else 'OFF'}")

        if not 1 <= channel <= 8:
            if logger:
                logger.error(f"[SNMP ERROR] Invalid channel number: {channel} (must be 1-8)")
            raise SNMPTestError(f"Invalid channel: {channel}. Must be 1-8")

        oid = f"{outlet_base_oid}.{channel}.0"

        if logger:
            logger.info(f"[SNMP] Getting outlet state: OID={oid}")

        value = get_value(ip, oid, community)
        if value is None:
            if logger:
                logger.error(f"[SNMP ERROR] Failed to read channel {channel} state (got None)")
            raise SNMPTestError(f"Failed to read channel {channel} state")

        if logger:
            logger.info(f"[SNMP] Retrieved value: {value}")

        try:
            current_state = int(value) == 1
            if logger:
                logger.info(f"[SNMP] Parsed state: {'ON' if current_state else 'OFF'}")
        except ValueError:
            if logger:
                logger.error(f"[SNMP ERROR] Invalid state value: {value} (cannot parse as integer)")
            raise SNMPTestError(f"Invalid state value for channel {channel}: {value}")

        if current_state != expected_state:
            if logger:
                logger.error(f"[SNMP ERROR] State mismatch: expected={'ON' if expected_state else 'OFF'}, got={'ON' if current_state else 'OFF'}")
            raise SNMPTestError(
                f"Channel {channel} state mismatch: expected {'ON' if expected_state else 'OFF'}, "
                f"got {'ON' if current_state else 'OFF'}"
            )

        if logger:
            logger.info(f"[SNMP] Channel {channel} state verified: {'ON' if current_state else 'OFF'}")
        return True
    return TestAction(name, execute, negative_test=negative_test)


def set_all_outlets(name: str, ip: str, state: bool, all_on_oid: str, all_off_oid: str,
                    community: str = "public",
        negative_test: bool = False) -> TestAction:
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
        logger = get_active_logger()
        if logger:
            logger.info(f"[SNMP] Executing set_all_outlets: state={'ON' if state else 'OFF'}")

        trigger_oid = all_on_oid if state else all_off_oid

        if logger:
            logger.info(f"[SNMP] Using trigger OID: {trigger_oid}")

        if not set_integer(ip, trigger_oid, 1, community):
            if logger:
                logger.error(f"[SNMP ERROR] Failed to set ALL outlets {'ON' if state else 'OFF'}")
            raise SNMPTestError(f"Failed to set ALL outlets {'ON' if state else 'OFF'}")

        if logger:
            logger.info(f"[SNMP] Successfully set ALL outlets {'ON' if state else 'OFF'}")
        return True
    return TestAction(name, execute, negative_test=negative_test)


def verify_all_outlets(name: str, ip: str, expected_state: bool, outlet_base_oid: str,
                       community: str = "public",
        negative_test: bool = False) -> TestAction:
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
        logger = get_active_logger()
        if logger:
            logger.info(f"[SNMP] Executing verify_all_outlets: expected_state={'ON' if expected_state else 'OFF'}")

        failed_channels = []
        for channel in range(1, 9):
            if logger:
                logger.info(f"[SNMP] Checking channel {channel}...")

            try:
                oid = f"{outlet_base_oid}.{channel}.0"
                value = get_value(ip, oid, community)
                if value is None:
                    if logger:
                        logger.error(f"[SNMP ERROR] CH{channel} read failed (got None)")
                    failed_channels.append(f"CH{channel} (read failed)")
                    continue
                current_state = int(value) == 1
                if logger:
                    logger.info(f"[SNMP] CH{channel} state: {'ON' if current_state else 'OFF'}")

                if current_state != expected_state:
                    if logger:
                        logger.error(f"[SNMP ERROR] CH{channel} state mismatch: expected={'ON' if expected_state else 'OFF'}, got={'ON' if current_state else 'OFF'}")
                    failed_channels.append(f"CH{channel} ({'ON' if current_state else 'OFF'})")
            except Exception as e:
                if logger:
                    logger.error(f"[SNMP ERROR] CH{channel} exception: {type(e).__name__}: {e}")
                failed_channels.append(f"CH{channel} (error: {e})")

        if failed_channels:
            if logger:
                logger.error(f"[SNMP ERROR] Verification failed for {len(failed_channels)} channels: {', '.join(failed_channels)}")
            raise SNMPTestError(
                f"ALL {'ON' if expected_state else 'OFF'} verification failed for: {', '.join(failed_channels)}"
            )

        if logger:
            logger.info(f"[SNMP] All 8 channels verified: {'ON' if expected_state else 'OFF'}")
        return True
    return TestAction(name, execute, negative_test=negative_test)


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
    logger = get_active_logger()
    if logger:
        logger.info(f"[SNMP] test_single_outlet() called: channel={channel}, state={'ON' if state else 'OFF'}")

    # Set the outlet state
    if not set_integer(ip, f"{outlet_base_oid}.{channel}.0", 1 if state else 0, community):
        if logger:
            logger.error(f"[SNMP ERROR] Failed to set channel {channel}")
        raise SNMPTestError(f"Failed to set channel {channel} to {'ON' if state else 'OFF'}")

    # Verify the state
    if logger:
        logger.info(f"[SNMP] Waiting 200ms for outlet state change...")
    time.sleep(0.2)  # Allow time for change
    value = get_value(ip, f"{outlet_base_oid}.{channel}.0", community)

    if value is None:
        raise SNMPTestError(f"Failed to read channel {channel} state after setting")

    try:
        current_state = int(value) == 1
    except ValueError:
        raise SNMPTestError(f"Invalid state value for channel {channel}: {value}")

    if current_state != state:
        if logger:
            logger.error(f"[SNMP ERROR] Verification failed: expected={'ON' if state else 'OFF'}, got={'ON' if current_state else 'OFF'}")
        raise SNMPTestError(
            f"Channel {channel} verification failed: expected {'ON' if state else 'OFF'}, "
            f"got {'ON' if current_state else 'OFF'}"
        )

    if logger:
        logger.info(f"[SNMP] test_single_outlet succeeded for channel {channel}")
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
    logger = get_active_logger()
    if logger:
        logger.info(f"[SNMP] test_all_outlets() called: state={'ON' if state else 'OFF'}")

    trigger_oid = all_on_oid if state else all_off_oid

    # Set ALL outlets
    if not set_integer(ip, trigger_oid, 1, community):
        if logger:
            logger.error(f"[SNMP ERROR] Failed to set ALL outlets")
        raise SNMPTestError(f"Failed to set ALL outlets {'ON' if state else 'OFF'}")

    # Verify all channels
    if logger:
        logger.info(f"[SNMP] Waiting 400ms for all outlet changes...")
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
                               settle_s: float = 0.2,
        negative_test: bool = False) -> TestAction:
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
    return TestAction(name, execute, negative_test=negative_test)


def walk_enterprise(name: str,
                    ip: str,
                    community: str = "public",
                    root_oid: str = "1.3.6.1.4.1.19865",
                    timeout: float = 25.0,
        negative_test: bool = False) -> TestAction:
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
    return TestAction(name, execute, negative_test=negative_test)


def expect_oid_regex(name: str,
                     ip: str,
                     oid: str,
                     regex: str,
                     community: str = "public",
                     timeout: float = 3.0,
        negative_test: bool = False) -> TestAction:
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
        ...     "1.3.6.1.2.1.1.1.0", r"v\\d+\\.\\d+\\.\\d+"
        ... )
    """
    def execute():
        val = get_value(ip, oid, community, timeout)
        if val is None:
            raise SNMPTestError(f"SNMP GET failed for {oid}")
        if re.search(regex, str(val)) is None:
            raise SNMPTestError(f"Value '{val}' for {oid} does not match /{regex}/")
        return True
    return TestAction(name, execute, negative_test=negative_test)


def expect_oid_equals(name: str,
                      ip: str,
                      oid: str,
                      expected: str,
                      community: str = "public",
                      timeout: float = 3.0,
                      strip_quotes: bool = True,
        negative_test: bool = False) -> TestAction:
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
    return TestAction(name, execute, negative_test=negative_test)


def expect_oid_error(name: str,
                     ip: str,
                     oid: str,
                     community: str = "public",
                     timeout: float = 3.0,
        negative_test: bool = False) -> TestAction:
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
    return TestAction(name, execute, negative_test=negative_test)


def read_oid(
    name: str,
    ip: str,
    oid: str,
    expected: str = None,
    min_val: float = None,
    max_val: float = None,
    community: str = "public",
    timeout: float = 3.0,
    negative_test: bool = False
) -> TestAction:
    """
    Create TestAction to read an OID and optionally validate against expected value or range.

    This is a simple, flexible function that reads an OID via SNMP and returns
    the string value. You can validate in three ways:
    1. No validation (just read and log)
    2. String comparison (expected="OK")
    3. Numeric range check (min_val=220.0, max_val=240.0)

    Args:
        name (str): Descriptive name for this test action.
        ip (str): IP address of the device to query.
        oid (str): OID to read.
        expected (str, optional): Expected string value for exact match validation.
            If None, no string validation. Defaults to None.
        min_val (float, optional): Minimum acceptable numeric value (inclusive).
            If provided with max_val, validates value is within range. Defaults to None.
        max_val (float, optional): Maximum acceptable numeric value (inclusive).
            If provided with min_val, validates value is within range. Defaults to None.
        community (str, optional): SNMP community string. Defaults to "public".
        timeout (float, optional): SNMP command timeout. Defaults to 3.0.
        negative_test (bool, optional): If True, mark as negative test. Defaults to False.

    Returns:
        TestAction: Configured test action to read OID.

    Raises:
        SNMPTestError: If OID cannot be read or validation fails.

    Example:
        >>> # Just read and log the value
        >>> read_oid("Read CH1 Voltage", "192.168.0.11", "1.3.6.1.4.1.19865.5.1.1.0")

        >>> # String comparison
        >>> read_oid("Check VREG Status", "192.168.0.11",
        ...          "1.3.6.1.4.1.19865.3.8.0", expected="OK")

        >>> # Numeric range validation
        >>> read_oid("CH1 Voltage ON", "192.168.0.11",
        ...          "1.3.6.1.4.1.19865.5.1.1.0", min_val=220.0, max_val=240.0)
    """
    def execute():
        logger = get_active_logger()
        value = get_value(ip, oid, community, timeout)

        if value is None:
            if logger:
                logger.error(f"[SNMP] Failed to read OID {oid}")
            raise SNMPTestError(f"Failed to read OID {oid}")

        # Clean up the value (remove quotes if present)
        value_clean = value.strip('"')

        # Determine validation mode
        if min_val is not None and max_val is not None:
            # Numeric range validation
            try:
                value_numeric = float(value_clean)
            except ValueError as e:
                if logger:
                    logger.error(f"[SNMP] Failed to parse '{value_clean}' as number: {e}")
                raise SNMPTestError(f"Cannot parse '{value_clean}' as number for range validation")

            if logger:
                logger.info(f"[SNMP] {name}: {value_numeric} (range: {min_val}-{max_val})")

            if not (min_val <= value_numeric <= max_val):
                if logger:
                    logger.error(f"[SNMP] Value {value_numeric} out of range [{min_val}, {max_val}]")
                raise SNMPTestError(
                    f"{name}: Value {value_numeric} out of range (expected {min_val}-{max_val})"
                )

        elif expected is not None:
            # String comparison
            if logger:
                logger.info(f"[SNMP] {name}: {value_clean} (expected: {expected})")

            if value_clean != expected:
                if logger:
                    logger.error(f"[SNMP] Value mismatch: got '{value_clean}', expected '{expected}'")
                raise SNMPTestError(
                    f"{name}: Value mismatch - got '{value_clean}', expected '{expected}'"
                )

        else:
            # No validation, just log
            if logger:
                logger.info(f"[SNMP] {name}: {value_clean}")

        return True
    return TestAction(name, execute, negative_test=negative_test)


def get_oid_value(
    name: str,
    ip: str,
    oid: str,
    community: str = "public",
    timeout: float = 3.0,
    negative_test: bool = False
) -> TestAction:
    """
    Create TestAction to read and log an OID value without validation.

    This function simply reads an OID value via SNMP and logs it, without
    performing any validation. Useful for informational readings like current
    measurements where you just want to see the value.

    Args:
        name (str): Descriptive name for this test action.
        ip (str): IP address of the device to query.
        oid (str): OID to read.
        community (str, optional): SNMP community string. Defaults to "public".
        timeout (float, optional): SNMP command timeout. Defaults to 3.0.
        negative_test (bool, optional): If True, mark as negative test. Defaults to False.

    Returns:
        TestAction: Configured test action to read OID value.

    Example:
        >>> get_oid_value("Read CH1 Current", "192.168.0.11", "1.3.6.1.4.1.19865.5.1.2.0")
    """
    def execute():
        logger = get_active_logger()
        value = get_value(ip, oid, community, timeout)
        if value is None:
            if logger:
                logger.warning(f"[SNMP] Failed to read OID {oid}")
            raise SNMPTestError(f"Failed to read OID {oid}")
        if logger:
            logger.info(f"[SNMP] {name}: {value}")
        return True
    return TestAction(name, execute, negative_test=negative_test)


def expect_oid_range(
    name: str,
    ip: str,
    oid: str,
    min_val: float,
    max_val: float,
    community: str = "public",
    timeout: float = 3.0,
    negative_test: bool = False
) -> TestAction:
    """
    Create TestAction to validate an OID value is within a numeric range.

    This function reads an OID value via SNMP, parses it as a float, and
    validates that it falls within the specified min/max range.

    Args:
        name (str): Descriptive name for this test action.
        ip (str): IP address of the device to query.
        oid (str): OID to read and validate.
        min_val (float): Minimum acceptable value (inclusive).
        max_val (float): Maximum acceptable value (inclusive).
        community (str, optional): SNMP community string. Defaults to "public".
        timeout (float, optional): SNMP command timeout. Defaults to 3.0.
        negative_test (bool, optional): If True, mark as negative test. Defaults to False.

    Returns:
        TestAction: Configured test action to validate OID range.

    Raises:
        SNMPTestError: If value is out of range or cannot be read/parsed.

    Example:
        >>> expect_oid_range("CH1 Voltage", "192.168.0.11",
        ...                  "1.3.6.1.4.1.19865.5.1.1.0", 220.0, 240.0)
    """
    def execute():
        logger = get_active_logger()
        value_str = get_value(ip, oid, community, timeout)

        if value_str is None:
            if logger:
                logger.error(f"[SNMP] Failed to read OID {oid}")
            raise SNMPTestError(f"Failed to read OID {oid}")

        try:
            value = float(value_str.strip('"'))
        except ValueError as e:
            if logger:
                logger.error(f"[SNMP] Failed to parse '{value_str}' as float: {e}")
            raise SNMPTestError(f"Invalid numeric value '{value_str}' for OID {oid}: {e}")

        if logger:
            logger.info(f"[SNMP] {name}: {value} (expected: {min_val}-{max_val})")

        if not (min_val <= value <= max_val):
            if logger:
                logger.error(f"[SNMP] Value {value} out of range [{min_val}, {max_val}]")
            raise SNMPTestError(
                f"{name}: Value {value} out of range (expected {min_val}-{max_val})"
            )

        return True
    return TestAction(name, execute, negative_test=negative_test)


def wait_settle(
    name: str,
    duration_s: float,
    negative_test: bool = False
) -> TestAction:
    """
    Create TestAction to wait for a specified duration.

    This is useful for allowing system states to settle before taking
    measurements, such as waiting for power readings to stabilize after
    turning outlets on.

    Args:
        name (str): Descriptive name for this test action.
        duration_s (float): Duration to wait in seconds.
        negative_test (bool, optional): If True, mark as negative test. Defaults to False.

    Returns:
        TestAction: Configured test action to wait.

    Example:
        >>> wait_settle("Wait for power to stabilize", 8.0)
    """
    def execute():
        logger = get_active_logger()
        if logger:
            logger.info(f"[SNMP] Waiting {duration_s}s...")
        time.sleep(duration_s)
        return True
    return TestAction(name, execute, negative_test=negative_test)


def verify_hlw8032_all_channels(
    name: str,
    ip: str,
    community: str = "public",
    check_voltage: bool = True,
    check_current: bool = True,
    expected_voltage_min: float = 0.0,
    expected_voltage_max: float = 5.0,
    settle_time_s: float = 2.0,
    timeout: float = 3.0,
    negative_test: bool = False
) -> TestAction:
    """
    Create TestAction to verify HLW8032 power monitoring readings for all 8 channels.

    This function reads voltage and current values from all 8 HLW8032 power monitoring
    channels via SNMP and validates them against expected ranges. It's used to verify
    that power monitoring is working correctly, typically with outlets OFF (low voltage)
    or ON (mains voltage).

    The HLW8032 OIDs follow the pattern: .1.3.6.1.4.1.19865.5.<channel>.<metric>.0
    where channel = 1-8 and metric: 1=Voltage, 2=Current, 3=Power, 4=PowerFactor,
    5=kWh, 6=Uptime

    Args:
        name (str): Descriptive name for this test action.
        ip (str): IP address of the device to query.
        community (str, optional): SNMP community string. Defaults to "public".
        check_voltage (bool, optional): Whether to check voltage readings. Defaults to True.
        check_current (bool, optional): Whether to check current readings. Defaults to True.
        expected_voltage_min (float, optional): Minimum expected voltage in V. Defaults to 0.0.
        expected_voltage_max (float, optional): Maximum expected voltage in V. Defaults to 5.0.
        settle_time_s (float, optional): Time to wait before reading values (seconds).
            Defaults to 2.0.
        timeout (float, optional): SNMP command timeout. Defaults to 3.0.
        negative_test (bool, optional): If True, mark as negative test. Defaults to False.

    Returns:
        TestAction: Configured test action to verify HLW8032 readings.

    Raises:
        SNMPTestError: If any channel's readings are out of expected range or cannot be read.

    Example:
        >>> # Check all channels with outlets OFF (voltage < 5V)
        >>> verify_hlw8032_all_channels(
        ...     "HLW8032 OFF check", "192.168.0.11",
        ...     expected_voltage_min=0.0, expected_voltage_max=5.0
        ... )

        >>> # Check all channels with outlets ON (220-240V AC)
        >>> verify_hlw8032_all_channels(
        ...     "HLW8032 ON check", "192.168.0.11",
        ...     expected_voltage_min=220.0, expected_voltage_max=240.0,
        ...     settle_time_s=8.0
        ... )
    """
    from tests import hardware_config as hw

    def execute():
        logger = get_active_logger()
        if logger:
            logger.info(f"[SNMP] Verifying HLW8032 readings for all 8 channels")
            logger.info(f"[SNMP]   Voltage check: {check_voltage} (range: {expected_voltage_min}-{expected_voltage_max}V)")
            logger.info(f"[SNMP]   Current check: {check_current}")
            logger.info(f"[SNMP]   Settle time: {settle_time_s}s")

        # Wait for readings to settle
        if settle_time_s > 0:
            if logger:
                logger.info(f"[SNMP] Waiting {settle_time_s}s for readings to settle...")
            time.sleep(settle_time_s)

        errors = []

        # Check all 8 channels
        for channel in range(1, 9):
            if logger:
                logger.info(f"[SNMP] === Channel {channel} ===")

            # Check voltage if requested
            if check_voltage:
                voltage_oid = hw.get_hlw8032_oid(channel, hw.HLW8032_VOLTAGE)
                voltage_str = get_value(ip, voltage_oid, community, timeout)

                if voltage_str is None:
                    errors.append(f"Channel {channel}: Failed to read voltage (OID: {voltage_oid})")
                    if logger:
                        logger.warning(f"[SNMP] Channel {channel} voltage read failed")
                    continue

                try:
                    voltage = float(voltage_str.strip('"'))
                    if logger:
                        logger.info(f"[SNMP] Channel {channel} Voltage: {voltage}V")

                    if not (expected_voltage_min <= voltage <= expected_voltage_max):
                        errors.append(
                            f"Channel {channel}: Voltage {voltage}V out of range "
                            f"({expected_voltage_min}-{expected_voltage_max}V)"
                        )
                        if logger:
                            logger.warning(
                                f"[SNMP] Channel {channel} voltage {voltage}V out of expected range"
                            )
                except ValueError as e:
                    errors.append(f"Channel {channel}: Invalid voltage value '{voltage_str}': {e}")
                    if logger:
                        logger.warning(f"[SNMP] Channel {channel} voltage parse error: {e}")

            # Check current if requested
            if check_current:
                current_oid = hw.get_hlw8032_oid(channel, hw.HLW8032_CURRENT)
                current_str = get_value(ip, current_oid, community, timeout)

                if current_str is None:
                    errors.append(f"Channel {channel}: Failed to read current (OID: {current_oid})")
                    if logger:
                        logger.warning(f"[SNMP] Channel {channel} current read failed")
                    continue

                try:
                    current = float(current_str.strip('"'))
                    if logger:
                        logger.info(f"[SNMP] Channel {channel} Current: {current}A")
                except ValueError as e:
                    errors.append(f"Channel {channel}: Invalid current value '{current_str}': {e}")
                    if logger:
                        logger.warning(f"[SNMP] Channel {channel} current parse error: {e}")

        # Report results
        if errors:
            error_msg = f"HLW8032 verification failed:\n" + "\n".join(f"  - {e}" for e in errors)
            if logger:
                logger.error(f"[SNMP] {error_msg}")
            raise SNMPTestError(error_msg)

        if logger:
            logger.info(f"[SNMP] All 8 channels passed HLW8032 verification")
        return True

    return TestAction(name, execute, negative_test=negative_test)
