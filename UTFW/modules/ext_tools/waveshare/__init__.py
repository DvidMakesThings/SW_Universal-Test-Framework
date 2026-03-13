"""
UTFW/modules/ext_tools/waveshare/__init__.py

UTFW Waveshare Adapter Module
===============================

Multi-protocol test module for the Waveshare USB TO UART/I2C/SPI/JTAG
adapter (WCH CH347 chipset).

This package exposes seven protocol sub-modules accessible as:
    waveshare.uart.send_action(...)
    waveshare.i2c.scan_action(...)
    waveshare.spi.transfer_action(...)
    waveshare.jtag.scan_action(...)     # JTAG transport (default)
    waveshare.swd.scan(...)             # SWD transport (convenience)
    waveshare.gpio.get_pins(...)
    waveshare.eeprom.read(...)

Each sub-module provides:
- Core communication functions for direct use
- TestAction factories for UTFW framework integration
- Protocol-specific exception classes

Shared utilities (device discovery, hex dump formatting) are available
from the package level:
    waveshare.find_devices()
    waveshare.get_device_info(port)

Author: DvidMakesThings
"""

import importlib

from ._base import (
    WaveshareError,
    find_devices,
    get_device_info,
    get_chip_mode_description,
    get_current_mode,
    get_current_mode_by_pid,
    ensure_mode,
    CH347_VID,
    CH347T_PID,
    CH347T_UART_PID,
    CH347T_HID_PID,
    CH347T_UART_PID,
    CH347T_HID_PID,
    CH347F_PID,
    CH347_MODES,
    OPENOCD_BIN,
    OPENOCD_DIR,
    OPENOCD_CFG,
    OPENOCD_SWD_CFG,
    OPENOCD_SCRIPTS,
)

__all__ = [
    # Sub-modules (lazy loaded)
    "uart",
    "i2c",
    "spi",
    "jtag",
    "swd",
    "gpio",
    "eeprom",

    # Base exception
    "WaveshareError",

    # Device discovery & mode management
    "find_devices",
    "get_device_info",
    "get_chip_mode_description",
    "get_current_mode",
    "get_current_mode_by_pid",
    "ensure_mode",

    # Constants
    "CH347_VID",
    "CH347T_PID",
    "CH347F_PID",
    "CH347_MODES",
    "OPENOCD_BIN",
    "OPENOCD_DIR",
    "OPENOCD_CFG",
    "OPENOCD_SWD_CFG",
    "OPENOCD_SCRIPTS",
]


def __getattr__(name):  # pragma: no cover - simple delegation
    """Lazy-load protocol sub-modules on first access."""
    if name in ("uart", "i2c", "spi", "jtag", "swd", "gpio", "eeprom"):
        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__} has no attribute {name}")
