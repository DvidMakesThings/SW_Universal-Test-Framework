# _base.py
"""
UTFW Waveshare Adapter - Shared Base Module
============================================
Device discovery, connection management, and shared utilities for the
Waveshare USB TO UART/I2C/SPI/JTAG adapter (WCH CH347 chipset).

This module provides foundational functionality shared across all protocol
sub-modules including device enumeration, USB identification, hex dump
formatting, and common error handling.

Chip Variants:
- CH347T: Standard variant (VID 0x1A86, PID 0x55DD in Mode 3)
- CH347F: Extended variant (VID 0x1A86, PID 0x55DE)

Operating Modes:
- Mode 0: UART0 + UART1
- Mode 1: UART1 + SPI + I2C
- Mode 2: HID UART1 + SPI + I2C
- Mode 3: UART1 + JTAG + I2C
- Mode 4 (CH347F only): UARTx2 + JTAG/SPI/I2C

Author: DvidMakesThings
"""

import os
import platform
from pathlib import Path
from typing import Optional, Dict, List, Any

from ....core.logger import get_active_logger

DEBUG = False  # Set to True to enable debug prints

# ======================== CH347 Constants ========================

CH347_VID = 0x1A86  # WCH vendor ID
CH347T_PID = 0x55DD  # CH347T product ID (Mode 1/3)
CH347T_UART_PID = 0x55DA  # CH347T product ID (Mode 0: dual UART)
CH347T_HID_PID = 0x55DC  # CH347T product ID (Mode 2: HID)
CH347F_PID = 0x55DE  # CH347F product ID

CH347_MODES = {
    0: "Mode 0: UART0 + UART1",
    1: "Mode 1: UART1 + SPI + I2C",
    2: "Mode 2: HID UART1 + SPI + I2C",
    3: "Mode 3: UART1 + JTAG + I2C",
    4: "Mode 4 (CH347F): UARTx2 + JTAG/SPI/I2C",
}

# USB endpoint addresses used by the CH347 chip
CH347_EP_OUT = 0x06  # Bulk OUT endpoint
CH347_EP_IN = 0x86   # Bulk IN endpoint

# USB timeouts in milliseconds
USB_WRITE_TIMEOUT_MS = 500
USB_READ_TIMEOUT_MS = 500

# Path to bundled OpenOCD binary (shipped alongside this package)
_MODULE_DIR = Path(__file__).resolve().parent
OPENOCD_DIR = _MODULE_DIR / "openocd"
OPENOCD_BIN = OPENOCD_DIR / "bin" / ("openocd.exe" if platform.system() == "Windows" else "openocd")
OPENOCD_SCRIPTS = OPENOCD_DIR / "scripts"
OPENOCD_CFG = OPENOCD_DIR / "bin" / "ch347.cfg"
OPENOCD_SWD_CFG = OPENOCD_DIR / "bin" / "ch347_swd.cfg"


class WaveshareError(Exception):
    """Base exception for all Waveshare adapter operations.

    This exception is raised by Waveshare/CH347 functions when device
    discovery fails, USB communication errors occur, or other adapter-level
    operations cannot be completed successfully.

    Args:
        message (str): Description of the error that occurred.
    """
    pass


# ======================== Hex Dump Utility ========================

def _format_hex_dump(data: bytes, bytes_per_line: int = 16) -> str:
    """Format binary data as a detailed hex dump with ASCII preview.

    Creates a formatted hex dump showing offset, hex values, and printable
    ASCII characters for debugging and log output.

    Args:
        data (bytes): Binary data to format.
        bytes_per_line (int, optional): Number of bytes per line. Defaults to 16.

    Returns:
        str: Formatted hex dump string.
    """
    if not data:
        return "[empty]"

    lines = []
    for i in range(0, len(data), bytes_per_line):
        chunk = data[i:i + bytes_per_line]
        hex_part = ' '.join(f'{b:02X}' for b in chunk)
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        lines.append(f"  {i:04X}  {hex_part:<{bytes_per_line * 3}}  |{ascii_part}|")

    return '\n'.join(lines)


# ======================== Dependency Checks ========================

def _ensure_pyserial():
    """Ensure pyserial library is available for serial port enumeration.

    Raises:
        ImportError: If pyserial is not installed.
    """
    try:
        import serial.tools.list_ports  # noqa: F401
    except ImportError:
        raise ImportError("pyserial is required. Install with: pip install pyserial")


# ======================== Device Discovery ========================

def find_devices() -> List[Dict[str, Any]]:
    """Discover all connected Waveshare / CH347-based USB adapters.

    Enumerates USB serial ports and identifies CH347 devices by their
    vendor and product IDs. Returns detailed information about each
    discovered adapter including port name, VID/PID, serial number,
    and chip variant.

    Returns:
        List[Dict[str, Any]]: List of dictionaries, each containing:
            - port (str): Serial port name (e.g., "COM3", "/dev/ttyACM0")
            - vid (int): USB vendor ID
            - pid (int): USB product ID
            - serial (str): USB serial number string
            - description (str): Port description from OS
            - variant (str): Chip variant ("CH347T", "CH347F", or "Unknown")
            - hwid (str): Hardware ID string

    Raises:
        WaveshareError: If port enumeration fails entirely.
    """
    _ensure_pyserial()
    import serial.tools.list_ports

    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE] DEVICE DISCOVERY")
        logger.info("=" * 80)
        logger.info("")

    try:
        all_ports = list(serial.tools.list_ports.comports())
    except Exception as e:
        if logger:
            logger.error(f"[WAVESHARE ERROR] Failed to enumerate ports: {type(e).__name__}: {e}")
        raise WaveshareError(f"Failed to enumerate serial ports: {type(e).__name__}: {e}")

    if logger:
        logger.info(f"  Total ports found: {len(all_ports)}")
        logger.info("")

    devices = []
    for port_info in all_ports:
        vid = port_info.vid
        pid = port_info.pid

        if vid != CH347_VID:
            continue

        if pid == CH347T_PID:
            variant = "CH347T"
        elif pid == CH347T_UART_PID:
            variant = "CH347T (Mode 0)"
        elif pid == CH347T_HID_PID:
            variant = "CH347T (HID)"
        elif pid == CH347F_PID:
            variant = "CH347F"
        else:
            variant = "Unknown"

        device = {
            "port": port_info.device,
            "vid": vid,
            "pid": pid,
            "serial": port_info.serial_number or "",
            "description": port_info.description or "",
            "variant": variant,
            "hwid": port_info.hwid or "",
        }
        devices.append(device)

        if logger:
            logger.info(f"  Found Waveshare adapter:")
            logger.info(f"    Port:        {device['port']}")
            logger.info(f"    VID:PID:     {vid:04X}:{pid:04X}")
            logger.info(f"    Variant:     {variant}")
            logger.info(f"    Serial:      {device['serial']}")
            logger.info(f"    Description: {device['description']}")
            logger.info("")

    if logger:
        logger.info(f"  Waveshare adapters found: {len(devices)}")
        logger.info("=" * 80)
        logger.info("")

    return devices


def get_device_info(port: str) -> Dict[str, Any]:
    """Retrieve detailed information about a specific Waveshare adapter.

    Queries the operating system for information about the adapter
    connected on the specified serial port.

    Args:
        port (str): Serial port identifier (e.g., "COM3", "/dev/ttyACM0").

    Returns:
        Dict[str, Any]: Device information dictionary with keys:
            - port (str): Port name
            - vid (int): USB vendor ID
            - pid (int): USB product ID
            - serial (str): Serial number
            - description (str): Port description
            - variant (str): Chip variant string
            - hwid (str): Hardware ID

    Raises:
        WaveshareError: If the specified port is not a CH347 device or
            cannot be queried.
    """
    _ensure_pyserial()
    import serial.tools.list_ports

    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE] GET DEVICE INFO")
        logger.info("=" * 80)
        logger.info(f"  Port: {port}")
        logger.info("")

    try:
        all_ports = list(serial.tools.list_ports.comports())
    except Exception as e:
        if logger:
            logger.error(f"[WAVESHARE ERROR] Port enumeration failed: {type(e).__name__}: {e}")
        raise WaveshareError(f"Port enumeration failed: {type(e).__name__}: {e}")

    for port_info in all_ports:
        if port_info.device == port:
            vid = port_info.vid or 0
            pid = port_info.pid or 0

            if vid == CH347_VID and pid in (CH347T_PID, CH347T_UART_PID, CH347T_HID_PID):
                variant = "CH347T"
            elif vid == CH347_VID and pid == CH347F_PID:
                variant = "CH347F"
            else:
                variant = "Unknown"

            info = {
                "port": port_info.device,
                "vid": vid,
                "pid": pid,
                "serial": port_info.serial_number or "",
                "description": port_info.description or "",
                "variant": variant,
                "hwid": port_info.hwid or "",
            }

            if logger:
                logger.info(f"  Device Found:")
                logger.info(f"    VID:PID:     {vid:04X}:{pid:04X}")
                logger.info(f"    Variant:     {variant}")
                logger.info(f"    Serial:      {info['serial']}")
                logger.info(f"    Description: {info['description']}")
                logger.info(f"    HWID:        {info['hwid']}")
                logger.info("")
                logger.info("=" * 80)
                logger.info("")

            return info

    if logger:
        logger.error(f"[WAVESHARE ERROR] Port {port} not found or not a Waveshare/CH347 device")
        logger.error("=" * 80)

    raise WaveshareError(f"Port {port} not found or is not a Waveshare/CH347 device")


def get_chip_mode_description(mode: int) -> str:
    """Get human-readable description of a CH347 chip operating mode.

    Args:
        mode (int): Chip mode number (0-4).

    Returns:
        str: Mode description string.
    """
    return CH347_MODES.get(mode, f"Unknown mode: {mode}")
