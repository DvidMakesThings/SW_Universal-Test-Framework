# jtag.py
"""
UTFW Waveshare JTAG/SWD Module
================================
High-level JTAG and SWD test functions and TestAction factories for the
Waveshare USB TO UART/I2C/SPI/JTAG adapter (WCH CH347 chipset).

This module provides JTAG/SWD interface capabilities through the CH347
adapter by leveraging the bundled OpenOCD binary with CH347 support.
The CH347 in Mode 3/4 exposes a debug master interface supporting:

  - **JTAG**: Standard IEEE 1149.1 operations
  - **SWD**:  ARM Serial Wire Debug (CoreSight DAP)

The implementation delegates low-level TAP/DAP state machine control
to OpenOCD, providing high-level wrappers for:
- JTAG chain scanning and device identification
- IDCODE reading
- Flash programming (erase / write / verify)
- Memory read/write
- Arbitrary OpenOCD command execution
- Device detection and verification

A bundled OpenOCD distribution with the full standard target config
library is included, supporting any OpenOCD-compatible MCU/FPGA.

All operations are logged using the UTFW logging system with full
OpenOCD command/response capture.

Usage:
    import UTFW
    waveshare = UTFW.modules.ext_tools.waveshare

    action = waveshare.jtag.scan("JTAG chain scan")
    action = waveshare.jtag.read_idcode(
        "Read FPGA IDCODE", expected_idcode="0x0362D093"
    )
    action = waveshare.jtag.flash_image(
        "Flash firmware", image="firmware.hex",
        target_cfg="stm32f4x",
    )

Author: DvidMakesThings
"""

import os
import subprocess
import time
import re
from pathlib import Path
from typing import Optional, Dict, List, Any

from ....core.logger import get_active_logger
from ....core.core import TestAction
from ._base import (
    WaveshareError,
    OPENOCD_BIN,
    OPENOCD_SCRIPTS,
    OPENOCD_CFG,
    OPENOCD_SWD_CFG,
    OPENOCD_DIR,
)

DEBUG = False  # Set to True to enable debug prints

# Default OpenOCD timeout (seconds)
OPENOCD_TIMEOUT = 30

# Common JTAG IR lengths
JTAG_IR_LEN_DEFAULT = 4


class WaveshareJTAGError(WaveshareError):
    """Exception raised when Waveshare JTAG operations fail.

    This exception is raised by JTAG test functions when OpenOCD cannot
    communicate with the adapter, the JTAG chain scan fails, or
    verification of IDCODE values cannot be completed.

    Args:
        message (str): Description of the error that occurred.
    """
    pass


# ======================== Internal Helpers ========================

def _check_openocd() -> Path:
    """Verify that the bundled OpenOCD binary is available.

    Returns:
        Path: Resolved path to the OpenOCD binary.

    Raises:
        WaveshareJTAGError: If OpenOCD binary is not found.
    """
    logger = get_active_logger()

    if not OPENOCD_BIN.exists():
        error_msg = f"Bundled OpenOCD not found at: {OPENOCD_BIN}"
        if logger:
            logger.error(f"[WAVESHARE JTAG ERROR] {error_msg}")
            logger.error(f"  Expected location: {OPENOCD_BIN}")
            logger.error(f"  OpenOCD directory:  {OPENOCD_DIR}")
        raise WaveshareJTAGError(error_msg)

    if logger:
        logger.info(f"[WAVESHARE JTAG] OpenOCD binary: {OPENOCD_BIN}")

    return OPENOCD_BIN


def _check_config() -> Path:
    """Verify that the CH347 OpenOCD configuration file is available.

    Returns:
        Path: Resolved path to the ch347.cfg file.

    Raises:
        WaveshareJTAGError: If the config file is not found.
    """
    logger = get_active_logger()

    if not OPENOCD_CFG.exists():
        error_msg = f"CH347 OpenOCD config not found at: {OPENOCD_CFG}"
        if logger:
            logger.error(f"[WAVESHARE JTAG ERROR] {error_msg}")
        raise WaveshareJTAGError(error_msg)

    if logger:
        logger.info(f"[WAVESHARE JTAG] Config file: {OPENOCD_CFG}")

    return OPENOCD_CFG


def _run_openocd(commands: List[str], timeout: float = OPENOCD_TIMEOUT,
                 extra_args: Optional[List[str]] = None,
                 config_file: Optional[str] = None) -> str:
    """Execute OpenOCD with the given commands and return output.

    Runs the bundled OpenOCD binary with the CH347 adapter configuration,
    executes the supplied TCL commands, and captures stdout/stderr.

    Args:
        commands (List[str]): List of OpenOCD/TCL commands to execute.
        timeout (float, optional): Max execution time. Defaults to OPENOCD_TIMEOUT.
        extra_args (Optional[List[str]], optional): Additional CLI arguments.
        config_file (Optional[str], optional): Override default ch347.cfg.

    Returns:
        str: Combined stdout/stderr output from OpenOCD.

    Raises:
        WaveshareJTAGError: If OpenOCD execution fails or times out.
    """
    logger = get_active_logger()
    openocd_bin = _check_openocd()
    cfg = Path(config_file) if config_file else _check_config()

    # Build the command line
    cmd = [str(openocd_bin)]

    # Add search path for scripts
    if OPENOCD_SCRIPTS.exists():
        cmd.extend(["-s", str(OPENOCD_SCRIPTS)])

    # Add the adapter configuration file
    cmd.extend(["-f", str(cfg)])

    # Add any extra arguments
    if extra_args:
        cmd.extend(extra_args)

    # Add each command as a -c argument
    for command in commands:
        cmd.extend(["-c", command])

    # Always end with shutdown
    if not any("shutdown" in c.lower() for c in commands):
        cmd.extend(["-c", "shutdown"])

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE JTAG] OPENOCD EXECUTION")
        logger.info("=" * 80)
        logger.info(f"  Binary:  {openocd_bin}")
        logger.info(f"  Config:  {cfg}")
        logger.info(f"  Timeout: {timeout}s")
        logger.info("")
        logger.info("  Commands:")
        for i, command in enumerate(commands, 1):
            logger.info(f"    [{i}] {command}")
        logger.info("")
        logger.info(f"  Full command line:")
        logger.info(f"    {' '.join(cmd)}")
        logger.info("")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(OPENOCD_DIR),
        )

        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += result.stderr

        if logger:
            logger.info("-" * 80)
            logger.info("  OpenOCD Output:")
            logger.info("-" * 80)
            for line in output.strip().split('\n'):
                logger.info(f"    {line}")
            logger.info("-" * 80)
            logger.info(f"  Exit code: {result.returncode}")
            logger.info("=" * 80)
            logger.info("")

        if result.returncode != 0:
            error_msg = (
                f"OpenOCD exited with non-zero status {result.returncode}. "
                f"See logged output for details."
            )
            if logger:
                logger.error(f"[WAVESHARE JTAG ERROR] {error_msg}")
            raise WaveshareJTAGError(error_msg)

        return output

    except subprocess.TimeoutExpired:
        error_msg = f"OpenOCD timed out after {timeout}s"
        if logger:
            logger.error(f"[WAVESHARE JTAG ERROR] {error_msg}")
        raise WaveshareJTAGError(error_msg)

    except FileNotFoundError:
        error_msg = f"OpenOCD binary not found: {openocd_bin}"
        if logger:
            logger.error(f"[WAVESHARE JTAG ERROR] {error_msg}")
        raise WaveshareJTAGError(error_msg)

    except Exception as e:
        error_msg = f"OpenOCD execution failed: {type(e).__name__}: {e}"
        if logger:
            logger.error(f"[WAVESHARE JTAG ERROR] {error_msg}")
        raise WaveshareJTAGError(error_msg)


def _parse_idcodes(output: str) -> List[str]:
    """Extract JTAG IDCODE values from OpenOCD output.

    Parses the OpenOCD scan_chain output for 32-bit IDCODE values in
    hexadecimal format.

    Args:
        output (str): Raw OpenOCD stdout/stderr text.

    Returns:
        List[str]: List of IDCODE strings (e.g., ["0x0362D093"]).
    """
    idcodes = []

    # Pattern: IDCODE values appear as 0xNNNNNNNN in scan_chain output
    # OpenOCD scan_chain format:
    #    TapName  Enabled  IdCode     Expected   IrLen  IrCap  IrMask
    #    ...      ...      0x0362D093 ...        ...    ...    ...
    pattern = re.compile(r'0x[0-9A-Fa-f]{8}')

    for line in output.split('\n'):
        # Only look at lines that appear to be scan chain entries
        if 'tap' in line.lower() or 'idcode' in line.lower() or pattern.search(line):
            matches = pattern.findall(line)
            for match in matches:
                # Avoid common non-IDCODE values like 0x00000000 and 0xFFFFFFFF
                val = int(match, 16)
                if val != 0x00000000 and val != 0xFFFFFFFF:
                    idcodes.append(match.upper().replace('X', 'x'))

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for code in idcodes:
        if code not in seen:
            seen.add(code)
            unique.append(code)

    return unique


# ======================== Core JTAG Functions ========================

def scan_chain(timeout: float = OPENOCD_TIMEOUT,
               config_file: Optional[str] = None) -> List[str]:
    """Scan the JTAG chain and return detected device IDCODEs.

    Uses OpenOCD to initialise the CH347 adapter, perform a JTAG chain
    scan, and extract all device IDCODEs found on the bus.

    Args:
        timeout (float, optional): OpenOCD execution timeout. Defaults to OPENOCD_TIMEOUT.
        config_file (Optional[str], optional): Override default ch347.cfg.

    Returns:
        List[str]: List of IDCODE strings found on the chain.

    Raises:
        WaveshareJTAGError: If the chain scan fails.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE JTAG] CHAIN SCAN")
        logger.info("=" * 80)
        logger.info("")

    commands = [
        "init",
        "scan_chain",
    ]

    output = _run_openocd(commands, timeout, config_file=config_file)
    idcodes = _parse_idcodes(output)

    if logger:
        logger.info(f"  Devices found: {len(idcodes)}")
        for i, code in enumerate(idcodes, 1):
            logger.info(f"    [{i}] {code}")
        logger.info("")

    return idcodes


def run_openocd_command(commands: List[str], timeout: float = OPENOCD_TIMEOUT,
                        config_file: Optional[str] = None) -> str:
    """Execute arbitrary OpenOCD commands via the CH347 adapter.

    Provides direct access to OpenOCD's TCL command interface for
    advanced JTAG operations not covered by the higher-level functions.

    Args:
        commands (List[str]): List of OpenOCD/TCL commands to execute.
        timeout (float, optional): Execution timeout. Defaults to OPENOCD_TIMEOUT.
        config_file (Optional[str], optional): Override default ch347.cfg.

    Returns:
        str: Combined stdout/stderr output from OpenOCD.

    Raises:
        WaveshareJTAGError: If the command execution fails.
    """
    return _run_openocd(commands, timeout, config_file=config_file)


def _read_idcode(timeout: float = OPENOCD_TIMEOUT,
                 config_file: Optional[str] = None) -> Optional[str]:
    """Read the IDCODE of the first device on the JTAG chain.

    Convenience function that scans the chain and returns the first
    IDCODE found. Useful when only a single device is on the chain.

    Args:
        timeout (float, optional): OpenOCD execution timeout. Defaults to OPENOCD_TIMEOUT.
        config_file (Optional[str], optional): Override default ch347.cfg.

    Returns:
        Optional[str]: First IDCODE string, or None if no device found.

    Raises:
        WaveshareJTAGError: If the chain scan fails.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE JTAG] READ IDCODE")
        logger.info("=" * 80)
        logger.info("")

    idcodes = scan_chain(timeout, config_file)

    if not idcodes:
        if logger:
            logger.warn("  No JTAG devices found on chain")
        return None

    idcode = idcodes[0]

    if logger:
        logger.info(f"  IDCODE: {idcode}")
        logger.info("=" * 80)
        logger.info("")

    return idcode


def detect_device(timeout: float = OPENOCD_TIMEOUT,
                  config_file: Optional[str] = None) -> Dict[str, Any]:
    """Detect the JTAG chain and return device information.

    Performs a chain scan and returns a dictionary describing the detected
    devices, including device count, IDCODEs, and OpenOCD availability.

    Args:
        timeout (float, optional): OpenOCD execution timeout. Defaults to OPENOCD_TIMEOUT.
        config_file (Optional[str], optional): Override default ch347.cfg.

    Returns:
        Dict[str, Any]: Dictionary with keys:
            - 'openocd_available' (bool): Whether OpenOCD binary was found.
            - 'config_available' (bool): Whether ch347.cfg was found.
            - 'device_count' (int): Number of devices on the chain.
            - 'idcodes' (List[str]): List of IDCODE strings.
            - 'raw_output' (str): Full OpenOCD output.

    Raises:
        WaveshareJTAGError: If a critical failure occurs (not device absence).
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE JTAG] DEVICE DETECTION")
        logger.info("=" * 80)
        logger.info("")

    info: Dict[str, Any] = {
        'openocd_available': OPENOCD_BIN.exists(),
        'config_available': OPENOCD_CFG.exists(),
        'device_count': 0,
        'idcodes': [],
        'raw_output': '',
    }

    if logger:
        logger.info(f"  OpenOCD binary: {'[OK]' if info['openocd_available'] else '[FAIL]'} {OPENOCD_BIN}")
        logger.info(f"  CH347 config:   {'[OK]' if info['config_available'] else '[FAIL]'} {OPENOCD_CFG}")

    if not info['openocd_available'] or not info['config_available']:
        if logger:
            logger.warn("  OpenOCD or config not available")
            logger.info("=" * 80)
        return info

    try:
        commands = ["init", "scan_chain"]
        output = _run_openocd(commands, timeout, config_file=config_file)
        idcodes = _parse_idcodes(output)

        info['device_count'] = len(idcodes)
        info['idcodes'] = idcodes
        info['raw_output'] = output

        if logger:
            logger.info("")
            logger.info(f"  Devices detected: {len(idcodes)}")
            for i, code in enumerate(idcodes, 1):
                logger.info(f"    [{i}] {code}")
            logger.info("=" * 80)
            logger.info("")

    except WaveshareJTAGError as e:
        info['raw_output'] = str(e)
        if logger:
            logger.warn(f"  Chain scan failed: {e}")

    return info


# ======================== TestAction Factories ========================

def scan(
        name: str,
        expected_count: Optional[int] = None,
        timeout: float = OPENOCD_TIMEOUT,
        config_file: Optional[str] = None,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that scans the JTAG chain.

    Args:
        name (str): Human-readable name for the test action.
        expected_count (Optional[int], optional): Expected number of devices.
            If None, count is not validated.
        timeout (float, optional): OpenOCD timeout. Defaults to OPENOCD_TIMEOUT.
        config_file (Optional[str], optional): Override default ch347.cfg.
        negative_test (bool, optional): Mark as negative test. Defaults to False.

    Returns:
        TestAction: TestAction that returns the list of IDCODEs.

    Example:
        >>> action = waveshare.jtag.scan(
        ...     "JTAG chain scan", expected_count=1
        ... )
    """

    def execute():
        logger = get_active_logger()
        idcodes = scan_chain(timeout, config_file)

        if expected_count is not None and len(idcodes) != expected_count:
            if logger:
                logger.error("")
                logger.error("=" * 80)
                logger.error("[WAVESHARE JTAG] CHAIN SCAN VALIDATION FAILED")
                logger.error("=" * 80)
                logger.error(f"  Expected devices: {expected_count}")
                logger.error(f"  Found devices:    {len(idcodes)}")
                if idcodes:
                    logger.error(f"  IDCODEs:          {', '.join(idcodes)}")
                logger.error("-" * 80)
            raise WaveshareJTAGError(
                f"Expected {expected_count} JTAG device(s), found {len(idcodes)}"
            )

        if logger:
            logger.info(f"[OK] JTAG chain scan complete ({len(idcodes)} device(s))")

        return idcodes

    metadata = {
        'display_command': "JTAG scan_chain",
        'display_expected': f"{expected_count} device(s)" if expected_count is not None else '',
    }

    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def read_idcode(
        name: str,
        expected_idcode: Optional[str] = None,
        timeout: float = OPENOCD_TIMEOUT,
        config_file: Optional[str] = None,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that reads and optionally verifies the JTAG IDCODE.

    Reads the IDCODE of the first device on the chain and validates it
    against the expected value if provided.

    Args:
        name (str): Human-readable name for the test action.
        expected_idcode (Optional[str], optional): Expected IDCODE string
            (e.g., "0x0362D093"). If None, no validation is performed.
        timeout (float, optional): OpenOCD timeout. Defaults to OPENOCD_TIMEOUT.
        config_file (Optional[str], optional): Override default ch347.cfg.
        negative_test (bool, optional): Mark as negative test. Defaults to False.

    Returns:
        TestAction: TestAction that returns the IDCODE string.

    Example:
        >>> action = waveshare.jtag.read_idcode(
        ...     "Verify FPGA IDCODE", expected_idcode="0x0362D093"
        ... )
    """

    def execute():
        logger = get_active_logger()
        idcode = _read_idcode(timeout, config_file)

        if idcode is None:
            if logger:
                logger.error("[WAVESHARE JTAG] No JTAG device detected")
            raise WaveshareJTAGError("No JTAG device found on chain")

        if expected_idcode is not None:
            # Normalize both for comparison
            actual_norm = idcode.lower().strip()
            expected_norm = expected_idcode.lower().strip()

            if actual_norm != expected_norm:
                if logger:
                    logger.error("")
                    logger.error("=" * 80)
                    logger.error("[WAVESHARE JTAG] IDCODE VERIFICATION FAILED")
                    logger.error("=" * 80)
                    logger.error(f"  Expected: {expected_idcode}")
                    logger.error(f"  Actual:   {idcode}")
                    logger.error("-" * 80)
                raise WaveshareJTAGError(
                    f"JTAG IDCODE mismatch: expected {expected_idcode}, got {idcode}"
                )

            if logger:
                logger.info(f"[OK] JTAG IDCODE verified: {idcode}")

        return idcode

    metadata = {
        'display_command': "JTAG read IDCODE",
        'display_expected': expected_idcode or '',
    }

    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def run_openocd(
        name: str,
        commands: List[str],
        expected_output: Optional[str] = None,
        timeout: float = OPENOCD_TIMEOUT,
        config_file: Optional[str] = None,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that executes arbitrary OpenOCD commands.

    Provides a TestAction wrapper around the OpenOCD command interface
    for custom JTAG operations.

    Args:
        name (str): Human-readable name for the test action.
        commands (List[str]): OpenOCD/TCL commands to execute.
        expected_output (Optional[str], optional): Substring that must
            appear in the output for the test to pass.
        timeout (float, optional): OpenOCD timeout. Defaults to OPENOCD_TIMEOUT.
        config_file (Optional[str], optional): Override default ch347.cfg.
        negative_test (bool, optional): Mark as negative test. Defaults to False.

    Returns:
        TestAction: TestAction that returns the OpenOCD output string.

    Example:
        >>> action = waveshare.jtag.run_openocd(
        ...     "Flash firmware", ["init", "reset halt", "flash write_image erase firmware.bin 0x08000000"]
        ... )
    """

    def execute():
        logger = get_active_logger()
        output = run_openocd_command(commands, timeout, config_file)

        if expected_output is not None and expected_output not in output:
            if logger:
                logger.error("")
                logger.error("=" * 80)
                logger.error("[WAVESHARE JTAG] COMMAND OUTPUT VALIDATION FAILED")
                logger.error("=" * 80)
                logger.error(f"  Expected substring: {expected_output}")
                logger.error(f"  Actual output (truncated):")
                for line in output[:2000].split('\n'):
                    logger.error(f"    {line}")
                logger.error("-" * 80)
            raise WaveshareJTAGError(
                f"Expected '{expected_output}' in OpenOCD output, not found"
            )

        return output

    cmd_str = "; ".join(commands[:3])
    if len(commands) > 3:
        cmd_str += f" (+{len(commands) - 3} more)"

    metadata = {
        'display_command': f"OpenOCD: {cmd_str}",
        'display_expected': expected_output or '',
    }

    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def detect(
        name: str,
        timeout: float = OPENOCD_TIMEOUT,
        config_file: Optional[str] = None,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that detects JTAG devices and reports status.

    Performs comprehensive JTAG chain detection, reporting OpenOCD
    availability, config presence, and all detected devices.

    Args:
        name (str): Human-readable name for the test action.
        timeout (float, optional): OpenOCD timeout. Defaults to OPENOCD_TIMEOUT.
        config_file (Optional[str], optional): Override default ch347.cfg.
        negative_test (bool, optional): Mark as negative test. Defaults to False.

    Returns:
        TestAction: TestAction that returns the detection info dict.

    Example:
        >>> action = waveshare.jtag.detect("Detect JTAG devices")
    """

    def execute():
        logger = get_active_logger()
        info = detect_device(timeout, config_file)

        if not info['openocd_available']:
            if logger:
                logger.error("[WAVESHARE JTAG] OpenOCD binary not found")
            raise WaveshareJTAGError("OpenOCD binary not available")

        if not info['config_available']:
            if logger:
                logger.error("[WAVESHARE JTAG] CH347 config file not found")
            raise WaveshareJTAGError("CH347 OpenOCD config not available")

        if logger:
            logger.info(f"[OK] JTAG detection complete: {info['device_count']} device(s)")

        return info

    metadata = {
        'display_command': "JTAG detect",
        'display_expected': '',
    }

    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


# ======================== Target Configuration ========================

# Pre-built target configs shipped alongside ch347.cfg
_TARGET_CFG_DIR = OPENOCD_DIR / "bin"

# Well-known short names -> actual cfg filenames
_TARGET_ALIASES: Dict[str, str] = {
    "stm32f1x": "stm32f1x.cfg",
    "stm32f1":  "stm32f1x.cfg",
    "stm32f4x": "stm32f4x.cfg",
    "stm32f4":  "stm32f4x.cfg",
}


def _resolve_target_cfg(target_cfg: str) -> Path:
    """Resolve a target config specifier to a file path.

    Accepts:
    - A short alias ("stm32f4x") -> resolves from bundled configs
    - A bare filename ("stm32f4x.cfg") -> looks in bundled dir
    - An absolute path -> used directly

    Returns:
        Resolved Path to the target .cfg file.

    Raises:
        WaveshareJTAGError: If the target config cannot be found.
    """
    # Absolute / relative path
    p = Path(target_cfg)
    if p.is_absolute() and p.exists():
        return p

    # Try alias
    alias_file = _TARGET_ALIASES.get(target_cfg.lower().replace(".cfg", ""))
    if alias_file:
        candidate = _TARGET_CFG_DIR / alias_file
        if candidate.exists():
            return candidate

    # Try bare filename in the bundled dir
    candidate = _TARGET_CFG_DIR / target_cfg
    if candidate.exists():
        return candidate

    # Try OpenOCD standard scripts/target/
    candidate = OPENOCD_SCRIPTS / "target" / target_cfg
    if not candidate.suffix:
        candidate = candidate.with_suffix(".cfg")
    if candidate.exists():
        return candidate

    raise WaveshareJTAGError(
        f"Target config '{target_cfg}' not found. "
        f"Searched: {_TARGET_CFG_DIR}, {OPENOCD_SCRIPTS / 'target'}"
    )


def _run_openocd_with_target(
        commands: List[str],
        target_cfg: str,
        transport: str = "jtag",
        adapter_speed: Optional[int] = None,
        timeout: float = OPENOCD_TIMEOUT,
        config_file: Optional[str] = None,
) -> str:
    """Run OpenOCD with adapter + target config and given commands.

    Builds the full command line:
      openocd -s <scripts>
              -f <ch347.cfg>
              [-c "transport select <transport>"]
              [-c "adapter speed <khz>"]
              -f <target.cfg>
              -c "init" -c <commands...> -c "shutdown"

    Args:
        commands: OpenOCD TCL commands to execute after init.
        target_cfg: Target config name/path (see _resolve_target_cfg).
        transport: "jtag" or "swd" (overrides the default in ch347.cfg).
        adapter_speed: Clock speed in kHz, or None for default.
        timeout: Execution timeout.
        config_file: Override ch347.cfg path.

    Returns:
        Combined stdout+stderr output.
    """
    logger = get_active_logger()
    openocd_bin = _check_openocd()

    # Select the right adapter config for the transport
    if config_file:
        cfg = Path(config_file)
    elif transport.lower() == "swd":
        cfg = OPENOCD_SWD_CFG
    else:
        cfg = _check_config()

    target_path = _resolve_target_cfg(target_cfg)

    cmd: List[str] = [str(openocd_bin)]

    if OPENOCD_SCRIPTS.exists():
        cmd.extend(["-s", str(OPENOCD_SCRIPTS)])

    # Adapter config
    cmd.extend(["-f", str(cfg)])

    if adapter_speed is not None:
        cmd.extend(["-c", f"adapter speed {adapter_speed}"])

    # Target config
    cmd.extend(["-f", str(target_path)])

    # SWD has no SRST line -- override target config's reset_config
    # (must come AFTER target config which may set srst_nogate)
    if transport.lower() == "swd":
        cmd.extend(["-c", "reset_config none"])

    # init + user commands + shutdown
    cmd.extend(["-c", "init"])
    for c in commands:
        cmd.extend(["-c", c])
    if not any("shutdown" in c.lower() for c in commands):
        cmd.extend(["-c", "shutdown"])

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE JTAG] OPENOCD + TARGET EXECUTION")
        logger.info("=" * 80)
        logger.info(f"  Binary:    {openocd_bin}")
        logger.info(f"  Adapter:   {cfg}")
        logger.info(f"  Target:    {target_path}")
        logger.info(f"  Transport: {transport}")
        if adapter_speed:
            logger.info(f"  Speed:     {adapter_speed} kHz")
        logger.info(f"  Timeout:   {timeout}s")
        logger.info("")
        logger.info("  Commands:")
        for i, c in enumerate(commands, 1):
            logger.info(f"    [{i}] {c}")
        logger.info("")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(OPENOCD_DIR),
        )

        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += result.stderr

        if logger:
            logger.info("-" * 80)
            logger.info("  OpenOCD Output:")
            logger.info("-" * 80)
            for line in output.strip().split('\n'):
                logger.info(f"    {line}")
            logger.info("-" * 80)
            logger.info(f"  Exit code: {result.returncode}")
            logger.info("=" * 80)

        if result.returncode != 0:
            raise WaveshareJTAGError(
                f"OpenOCD exited with status {result.returncode}. "
                f"See logged output for details."
            )

        return output

    except subprocess.TimeoutExpired:
        raise WaveshareJTAGError(f"OpenOCD timed out after {timeout}s")
    except FileNotFoundError:
        raise WaveshareJTAGError(f"OpenOCD binary not found: {openocd_bin}")
    except WaveshareJTAGError:
        raise
    except Exception as e:
        raise WaveshareJTAGError(f"OpenOCD execution failed: {type(e).__name__}: {e}")


# ======================== Flash / Target TestActions ========================

def flash_image(
        name: str,
        image: str,
        target_cfg: str,
        address: Optional[int] = None,
        verify: bool = True,
        erase: bool = True,
        reset_after: bool = True,
        transport: str = "jtag",
        adapter_speed: Optional[int] = None,
        timeout: float = 120,
        config_file: Optional[str] = None,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that flashes a firmware image via JTAG/SWD.

    Args:
        name: Human-readable name.
        image: Path to firmware file (.hex, .bin, .elf).
        target_cfg: Target config ("stm32f4x", path, etc.).
        address: Base address for .bin files (ignored for .hex/.elf).
        verify: Verify after write. Defaults to True.
        erase: Erase sectors before write. Defaults to True.
        reset_after: Issue "reset run" after programming.
        transport: "jtag" or "swd".
        adapter_speed: Clock speed in kHz.
        timeout: OpenOCD timeout (flashing can be slow).
        config_file: Override ch347.cfg.
        negative_test: Mark as negative test.
    """

    def execute():
        logger = get_active_logger()
        img_path = Path(image).resolve()
        if not img_path.exists():
            raise WaveshareJTAGError(f"Image file not found: {img_path}")

        if logger:
            logger.info("")
            logger.info("=" * 80)
            logger.info("[WAVESHARE JTAG] FLASH IMAGE")
            logger.info("=" * 80)
            logger.info(f"  Image:   {img_path}")
            logger.info(f"  Target:  {target_cfg}")
            logger.info(f"  Erase:   {erase}  Verify: {verify}")
            logger.info("")

        halt_cmd = "reset init" if transport.lower() == "swd" else "reset halt"
        commands: List[str] = [halt_cmd]

        # Build flash write_image command
        flash_cmd = "flash write_image"
        if erase:
            flash_cmd += " erase"
        flash_cmd += f" {{{str(img_path)}}}"
        if address is not None:
            flash_cmd += f" 0x{address:08X}"
        commands.append(flash_cmd)

        if verify:
            verify_cmd = f"verify_image {{{str(img_path)}}}"
            if address is not None:
                verify_cmd += f" 0x{address:08X}"
            commands.append(verify_cmd)

        if reset_after:
            commands.append("reset run")

        output = _run_openocd_with_target(
            commands, target_cfg, transport, adapter_speed,
            timeout, config_file,
        )

        if logger:
            logger.info(f"[OK] Flash programming complete")

        return output

    metadata = {
        'display_command': f"Flash {Path(image).name} -> {target_cfg}",
        'display_expected': 'verified' if verify else 'written',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def flash_verify(
        name: str,
        image: str,
        target_cfg: str,
        address: Optional[int] = None,
        transport: str = "jtag",
        adapter_speed: Optional[int] = None,
        timeout: float = 60,
        config_file: Optional[str] = None,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that verifies flash contents against an image."""

    def execute():
        img_path = Path(image).resolve()
        if not img_path.exists():
            raise WaveshareJTAGError(f"Image file not found: {img_path}")

        halt_cmd = "reset init" if transport.lower() == "swd" else "reset halt"
        commands = [halt_cmd]
        verify_cmd = f"verify_image {{{str(img_path)}}}"
        if address is not None:
            verify_cmd += f" 0x{address:08X}"
        commands.append(verify_cmd)

        output = _run_openocd_with_target(
            commands, target_cfg, transport, adapter_speed,
            timeout, config_file,
        )

        logger = get_active_logger()
        if logger:
            logger.info(f"[OK] Flash verification passed")
        return output

    metadata = {
        'display_command': f"Verify {Path(image).name} @ {target_cfg}",
        'display_expected': 'match',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def reset_halt(
        name: str,
        target_cfg: str,
        transport: str = "jtag",
        adapter_speed: Optional[int] = None,
        timeout: float = OPENOCD_TIMEOUT,
        config_file: Optional[str] = None,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that resets and halts the target."""

    def execute():
        halt_cmd = "halt" if transport.lower() == "swd" else "reset halt"
        output = _run_openocd_with_target(
            [halt_cmd], target_cfg, transport, adapter_speed,
            timeout, config_file,
        )
        logger = get_active_logger()
        if logger:
            logger.info("[OK] Target halted")
        return output

    metadata = {
        'display_command': f"Reset halt {target_cfg}",
        'display_expected': 'halted',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def read_memory(
        name: str,
        target_cfg: str,
        address: int,
        length: int,
        width: int = 32,
        expected: Optional[str] = None,
        transport: str = "jtag",
        adapter_speed: Optional[int] = None,
        timeout: float = OPENOCD_TIMEOUT,
        config_file: Optional[str] = None,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that reads memory from the target.

    Args:
        name: Human-readable name.
        target_cfg: Target config.
        address: Memory address to read.
        length: Number of units to read.
        width: Access width in bits (8, 16, or 32).
        expected: Optional substring that must appear in output.
        transport: "jtag" or "swd".
    """

    def execute():
        logger = get_active_logger()
        # mdw/mdh/mdb = memory display word/halfword/byte
        cmd_map = {32: "mdw", 16: "mdh", 8: "mdb"}
        md_cmd = cmd_map.get(width, "mdw")

        halt_cmd = "halt" if transport.lower() == "swd" else "reset halt"
        commands = [
            halt_cmd,
            f"{md_cmd} 0x{address:08X} {length}",
        ]

        output = _run_openocd_with_target(
            commands, target_cfg, transport, adapter_speed,
            timeout, config_file,
        )

        if expected is not None and expected not in output:
            if logger:
                logger.error(f"[WAVESHARE JTAG] Memory read validation failed")
                logger.error(f"  Expected substring: {expected}")
            raise WaveshareJTAGError(
                f"Expected '{expected}' in memory read output, not found"
            )

        if logger:
            logger.info(f"[OK] Memory read complete at 0x{address:08X}")
        return output

    metadata = {
        'display_command': f"Read 0x{address:08X} [{length}x{width}b]",
        'display_expected': expected or '',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def write_memory(
        name: str,
        target_cfg: str,
        address: int,
        values: List[int],
        width: int = 32,
        transport: str = "jtag",
        adapter_speed: Optional[int] = None,
        timeout: float = OPENOCD_TIMEOUT,
        config_file: Optional[str] = None,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that writes values to target memory.

    Args:
        name: Human-readable name.
        target_cfg: Target config.
        address: Memory address to write.
        values: List of integer values to write.
        width: Access width in bits (8, 16, or 32).
        transport: "jtag" or "swd".
    """

    def execute():
        logger = get_active_logger()
        # mww/mwh/mwb = memory write word/halfword/byte
        cmd_map = {32: "mww", 16: "mwh", 8: "mwb"}
        mw_cmd = cmd_map.get(width, "mww")

        halt_cmd = "halt" if transport.lower() == "swd" else "reset halt"
        commands = [halt_cmd]
        for i, val in enumerate(values):
            addr = address + i * (width // 8)
            commands.append(f"{mw_cmd} 0x{addr:08X} 0x{val:X}")

        output = _run_openocd_with_target(
            commands, target_cfg, transport, adapter_speed,
            timeout, config_file,
        )

        if logger:
            logger.info(f"[OK] Memory write complete at 0x{address:08X} ({len(values)} values)")
        return output

    val_preview = " ".join(f"0x{v:X}" for v in values[:4])
    if len(values) > 4:
        val_preview += f" ... (+{len(values)-4})"

    metadata = {
        'display_command': f"Write 0x{address:08X} [{val_preview}]",
        'display_expected': 'OK',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def run_target_command(
        name: str,
        target_cfg: str,
        commands: List[str],
        expected_output: Optional[str] = None,
        transport: str = "jtag",
        adapter_speed: Optional[int] = None,
        timeout: float = OPENOCD_TIMEOUT,
        config_file: Optional[str] = None,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that runs OpenOCD commands with a target config.

    Like ``run_openocd`` but also loads a target configuration, allowing
    target-aware commands (flash, memory, reset, etc.).

    Args:
        name: Human-readable name.
        target_cfg: Target config ("stm32f4x", etc.).
        commands: OpenOCD TCL commands (init is added automatically).
        expected_output: Substring that must appear in output.
        transport: "jtag" or "swd".
    """

    def execute():
        logger = get_active_logger()
        output = _run_openocd_with_target(
            commands, target_cfg, transport, adapter_speed,
            timeout, config_file,
        )

        if expected_output is not None and expected_output not in output:
            if logger:
                logger.error(f"[WAVESHARE JTAG] Command output validation failed")
            raise WaveshareJTAGError(
                f"Expected '{expected_output}' in output, not found"
            )
        return output

    cmd_str = "; ".join(commands[:3])
    if len(commands) > 3:
        cmd_str += f" (+{len(commands) - 3} more)"

    metadata = {
        'display_command': f"{target_cfg}: {cmd_str}",
        'display_expected': expected_output or '',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)
