"""
UTFW/modules/ext_tools/waveshare/swd.py

SWD convenience wrapper around the JTAG/SWD module.

Provides the same TestAction API as ``waveshare.jtag`` but with SWD
transport pre-selected and SWD-native discovery commands (SWD has no
scan chain -- ``dap info`` replaces ``scan_chain``).

This lets test authors write::

    waveshare.swd.scan("Find STM32", target_cfg="stm32f1x", expected_count=1)
    waveshare.swd.read_idcode("Read DPIDR", target_cfg="stm32f1x")

instead of manually juggling ``config_file`` / ``transport`` params.

Every public TestAction from ``jtag.py`` that accepts a ``config_file``
or ``transport`` parameter is re-exported here with SWD defaults.
"""

import re
from typing import Dict, List, Optional

from ._base import OPENOCD_SWD_CFG
from .jtag import (                    # noqa: F401 - re-export public API
    # Exceptions (pass-through)
    WaveshareJTAGError,
    # Internal helpers for SWD-native implementations
    _run_openocd_with_target,
    # Direct (non-TestAction) helpers - re-export for convenience
    run_openocd_command,
    detect_device,
    # Constants
    OPENOCD_TIMEOUT,
)
from .jtag import (
    run_openocd as _run_openocd,
    detect as _detect,
    flash_image as _flash_image,
    flash_verify as _flash_verify,
    reset_halt as _reset_halt,
    read_memory as _read_memory,
    write_memory as _write_memory,
    run_target_command as _run_target_command,
)
from UTFW.core import TestAction
from UTFW.core.logger import get_active_logger

_SWD_CFG = str(OPENOCD_SWD_CFG)

# Regex to pull DPIDR from `dap info` output, e.g. "DPIDR 0x1BA01477"
_DPIDR_RE = re.compile(r"DPIDR\s+(0x[0-9A-Fa-f]+)", re.IGNORECASE)


# -- SWD-native discovery TestActions ---------------------------------
# SWD is point-to-point (no chain).  Discovery uses `dap info` instead
# of the JTAG-only `scan_chain` command.

def scan(
        name: str,
        target_cfg: str = "stm32f1x",
        expected_count: Optional[int] = None,
        adapter_speed: Optional[int] = None,
        timeout: float = OPENOCD_TIMEOUT,
        config_file: Optional[str] = None,
        negative_test: bool = False,
) -> TestAction:
    """Scan for a device over SWD using ``dap info``.

    Unlike JTAG ``scan_chain``, SWD needs a target config to establish
    the DAP link.  The function runs ``dap info`` and inspects the
    DPIDR to confirm a device is responding.

    Args:
        name: Human-readable test step name.
        target_cfg: Target config for the expected device (default stm32f1x).
        expected_count: Expected number of DPIDRs (typically 1 for SWD).
        adapter_speed: Optional clock speed in kHz.
        timeout: OpenOCD timeout.
        config_file: Override SWD adapter config.
        negative_test: Mark as negative test.
    """

    def execute():
        logger = get_active_logger()
        output = _run_openocd_with_target(
            ["dap info"],
            target_cfg, "swd", adapter_speed, timeout, config_file,
        )

        # Extract DPIDR(s) from the output
        dpidrs = _DPIDR_RE.findall(output)

        if expected_count is not None and len(dpidrs) != expected_count:
            if logger:
                logger.error("")
                logger.error("=" * 80)
                logger.error("[WAVESHARE SWD] SCAN VALIDATION FAILED")
                logger.error("=" * 80)
                logger.error(f"  Expected devices: {expected_count}")
                logger.error(f"  Found DPIDRs:     {len(dpidrs)}")
                if dpidrs:
                    logger.error(f"  DPIDRs:          {', '.join(dpidrs)}")
                logger.error("-" * 80)
            raise WaveshareJTAGError(
                f"Expected {expected_count} SWD device(s), found {len(dpidrs)}"
            )

        if logger:
            logger.info(f"[OK] SWD scan complete ({len(dpidrs)} device(s))")
            for d in dpidrs:
                logger.info(f"  DPIDR: {d}")

        return dpidrs

    metadata = {
        'display_command': f"SWD dap info ({target_cfg})",
        'display_expected': f"{expected_count} device(s)" if expected_count is not None else '',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def read_idcode(
        name: str,
        target_cfg: str = "stm32f1x",
        expected_idcode: Optional[str] = None,
        adapter_speed: Optional[int] = None,
        timeout: float = OPENOCD_TIMEOUT,
        config_file: Optional[str] = None,
        negative_test: bool = False,
) -> TestAction:
    """Read the SWD DPIDR (the SWD equivalent of JTAG IDCODE).

    Args:
        name: Human-readable test step name.
        target_cfg: Target config (default stm32f1x).
        expected_idcode: DPIDR to validate against (e.g. "0x1BA01477").
        adapter_speed: Optional clock speed in kHz.
        timeout: OpenOCD timeout.
        config_file: Override SWD adapter config.
        negative_test: Mark as negative test.
    """

    def execute():
        logger = get_active_logger()
        output = _run_openocd_with_target(
            ["dap info"],
            target_cfg, "swd", adapter_speed, timeout, config_file,
        )

        dpidrs = _DPIDR_RE.findall(output)
        if not dpidrs:
            if logger:
                logger.error("[WAVESHARE SWD] No DPIDR found in dap info output")
            raise WaveshareJTAGError("No SWD device found (no DPIDR in output)")

        dpidr = dpidrs[0]

        if expected_idcode is not None:
            actual = dpidr.lower().strip()
            expected = expected_idcode.lower().strip()
            if actual != expected:
                if logger:
                    logger.error("")
                    logger.error("=" * 80)
                    logger.error("[WAVESHARE SWD] DPIDR VERIFICATION FAILED")
                    logger.error("=" * 80)
                    logger.error(f"  Expected: {expected_idcode}")
                    logger.error(f"  Actual:   {dpidr}")
                    logger.error("-" * 80)
                raise WaveshareJTAGError(
                    f"SWD DPIDR mismatch: expected {expected_idcode}, got {dpidr}"
                )
            if logger:
                logger.info(f"[OK] SWD DPIDR verified: {dpidr}")
        else:
            if logger:
                logger.info(f"[OK] SWD DPIDR: {dpidr}")

        return dpidr

    metadata = {
        'display_command': f"SWD read DPIDR ({target_cfg})",
        'display_expected': expected_idcode or '',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def run_openocd(
        name: str,
        commands: List[str],
        expected_output: Optional[str] = None,
        timeout: float = OPENOCD_TIMEOUT,
        config_file: Optional[str] = None,
        negative_test: bool = False,
) -> TestAction:
    """Run raw OpenOCD commands over SWD.  See :func:`jtag.run_openocd`."""
    return _run_openocd(
        name=name,
        commands=commands,
        expected_output=expected_output,
        timeout=timeout,
        config_file=config_file or _SWD_CFG,
        negative_test=negative_test,
    )


def detect(
        name: str,
        timeout: float = OPENOCD_TIMEOUT,
        config_file: Optional[str] = None,
        negative_test: bool = False,
) -> TestAction:
    """SWD device detection.  See :func:`jtag.detect` for full docs."""
    return _detect(
        name=name,
        timeout=timeout,
        config_file=config_file or _SWD_CFG,
        negative_test=negative_test,
    )


# -- Target-aware TestActions (have transport param) ------------------

def flash_image(
        name: str,
        image: str,
        target_cfg: str,
        address: Optional[int] = None,
        verify: bool = True,
        erase: bool = True,
        reset_after: bool = True,
        transport: str = "swd",
        adapter_speed: Optional[int] = None,
        timeout: float = 120,
        config_file: Optional[str] = None,
        negative_test: bool = False,
) -> TestAction:
    """Flash firmware via SWD.  See :func:`jtag.flash_image`."""
    return _flash_image(
        name=name, image=image, target_cfg=target_cfg,
        address=address, verify=verify, erase=erase,
        reset_after=reset_after, transport=transport,
        adapter_speed=adapter_speed, timeout=timeout,
        config_file=config_file, negative_test=negative_test,
    )


def flash_verify(
        name: str,
        image: str,
        target_cfg: str,
        address: Optional[int] = None,
        transport: str = "swd",
        adapter_speed: Optional[int] = None,
        timeout: float = 60,
        config_file: Optional[str] = None,
        negative_test: bool = False,
) -> TestAction:
    """Verify flash via SWD.  See :func:`jtag.flash_verify`."""
    return _flash_verify(
        name=name, image=image, target_cfg=target_cfg,
        address=address, transport=transport,
        adapter_speed=adapter_speed, timeout=timeout,
        config_file=config_file, negative_test=negative_test,
    )


def reset_halt(
        name: str,
        target_cfg: str,
        transport: str = "swd",
        adapter_speed: Optional[int] = None,
        timeout: float = OPENOCD_TIMEOUT,
        config_file: Optional[str] = None,
        negative_test: bool = False,
) -> TestAction:
    """Reset-halt via SWD.  See :func:`jtag.reset_halt`."""
    return _reset_halt(
        name=name, target_cfg=target_cfg, transport=transport,
        adapter_speed=adapter_speed, timeout=timeout,
        config_file=config_file, negative_test=negative_test,
    )


def read_memory(
        name: str,
        target_cfg: str,
        address: int,
        length: int,
        width: int = 32,
        expected: Optional[str] = None,
        transport: str = "swd",
        adapter_speed: Optional[int] = None,
        timeout: float = OPENOCD_TIMEOUT,
        config_file: Optional[str] = None,
        negative_test: bool = False,
) -> TestAction:
    """Read target memory via SWD.  See :func:`jtag.read_memory`."""
    return _read_memory(
        name=name, target_cfg=target_cfg, address=address,
        length=length, width=width, expected=expected,
        transport=transport, adapter_speed=adapter_speed,
        timeout=timeout, config_file=config_file,
        negative_test=negative_test,
    )


def write_memory(
        name: str,
        target_cfg: str,
        address: int,
        values: List[int],
        width: int = 32,
        transport: str = "swd",
        adapter_speed: Optional[int] = None,
        timeout: float = OPENOCD_TIMEOUT,
        config_file: Optional[str] = None,
        negative_test: bool = False,
) -> TestAction:
    """Write target memory via SWD.  See :func:`jtag.write_memory`."""
    return _write_memory(
        name=name, target_cfg=target_cfg, address=address,
        values=values, width=width, transport=transport,
        adapter_speed=adapter_speed, timeout=timeout,
        config_file=config_file, negative_test=negative_test,
    )


def run_target_command(
        name: str,
        target_cfg: str,
        commands: List[str],
        expected_output: Optional[str] = None,
        transport: str = "swd",
        adapter_speed: Optional[int] = None,
        timeout: float = OPENOCD_TIMEOUT,
        config_file: Optional[str] = None,
        negative_test: bool = False,
) -> TestAction:
    """Run target-aware OpenOCD commands via SWD.  See :func:`jtag.run_target_command`."""
    return _run_target_command(
        name=name, target_cfg=target_cfg, commands=commands,
        expected_output=expected_output, transport=transport,
        adapter_speed=adapter_speed, timeout=timeout,
        config_file=config_file, negative_test=negative_test,
    )
