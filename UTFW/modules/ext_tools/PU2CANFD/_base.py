# _base.py
"""
UTFW PU2CANFD Adapter - Shared Base Module
============================================
Device discovery, channel management, and shared utilities for the
Pibiger USB TO CAN FD adapter (PU2CANFD / SavvyCAN-FD series).

This module provides foundational functionality shared across all CAN
sub-modules including interface enumeration, hex dump formatting,
and common error handling.

Hardware Overview:
- Pibiger SavvyCAN-FD: PCAN-USB FD compatible USB-CAN FD adapter
- USB VID:PID 0C72:0012 (PEAK-System Technik GmbH compatible)
- Supports CAN 2.0A/B (standard & extended) and CAN FD
- CAN FD data bitrates up to 12 Mbit/s
- Signal & power individually isolated up to 2.5 kV
- Timestamp resolution up to 1 us

Backends:
- Linux: SocketCAN (native kernel driver, zero-config)
- Windows: PCAN (requires PEAK device driver + PCANBasic.dll)
  Download from: https://www.peak-system.com/PCAN-Basic.239.0.html

Author: DvidMakesThings
"""

import os
import platform
from typing import Optional, Dict, List, Any

from ....core.logger import get_active_logger


# ======================== Device Identity ========================

# PU2CANFD USB identifiers (PCAN-USB FD compatible)
PU2CANFD_USB_VID = 0x0C72    # Vendor ID
PU2CANFD_USB_PID = 0x0012    # Product ID
PU2CANFD_USB_PRODUCT = "PCAN-USB FD"  # USB product string

# PCAN channel names for python-can (Windows)
PCAN_USBBUS1 = "PCAN_USBBUS1"
PCAN_USBBUS2 = "PCAN_USBBUS2"

# ======================== Constants ========================

# Standard CAN bitrates (kbit/s)
CAN_BITRATE_1000K = 1000000
CAN_BITRATE_500K = 500000
CAN_BITRATE_250K = 250000
CAN_BITRATE_125K = 125000
CAN_BITRATE_100K = 100000
CAN_BITRATE_50K = 50000

# CAN FD data bitrates (bit/s)
CANFD_DBITRATE_8M = 8000000
CANFD_DBITRATE_5M = 5000000
CANFD_DBITRATE_2M = 2000000
CANFD_DBITRATE_1M = 1000000

# CAN ID flags
CAN_EFF_FLAG = 0x80000000  # Extended frame format (29-bit ID)
CAN_RTR_FLAG = 0x40000000  # Remote transmission request
CAN_ERR_FLAG = 0x20000000  # Error frame

# Masks
CAN_SFF_MASK = 0x000007FF  # Standard frame ID mask (11-bit)
CAN_EFF_MASK = 0x1FFFFFFF  # Extended frame ID mask (29-bit)

# Maximum data lengths
CAN_MAX_DLC = 8           # Classic CAN max data bytes
CANFD_MAX_DLC = 64        # CAN FD max data bytes

# Default timeouts (seconds)
DEFAULT_SEND_TIMEOUT = 1.0
DEFAULT_RECV_TIMEOUT = 5.0

# ======================== Exceptions ========================


class PU2CANFDError(Exception):
    """Base exception for all PU2CANFD adapter operations.

    This exception is raised by PU2CANFD functions when device
    discovery fails, CAN communication errors occur, or other
    adapter-level operations cannot be completed.

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


def _format_can_id(can_id: int, is_extended: bool = False) -> str:
    """Format a CAN arbitration ID for display.

    Args:
        can_id (int): CAN arbitration ID (11-bit or 29-bit).
        is_extended (bool): Whether this is an extended (29-bit) ID.

    Returns:
        str: Formatted CAN ID string (e.g., "0x123" or "0x1234ABCD").
    """
    if is_extended:
        return f"0x{can_id & CAN_EFF_MASK:08X}"
    return f"0x{can_id & CAN_SFF_MASK:03X}"


def _format_can_frame(arb_id: int, data: bytes, is_extended: bool = False,
                      is_fd: bool = False, is_remote: bool = False) -> str:
    """Format a complete CAN frame for log display.

    Args:
        arb_id (int): CAN arbitration ID.
        data (bytes): Frame payload.
        is_extended (bool): Extended frame format (29-bit ID).
        is_fd (bool): CAN FD frame.
        is_remote (bool): Remote transmission request.

    Returns:
        str: Multi-line formatted CAN frame string.
    """
    frame_type = "CAN FD" if is_fd else "CAN 2.0"
    if is_remote:
        frame_type += " RTR"
    id_type = "EXT" if is_extended else "STD"

    lines = [
        f"  Type:    {frame_type} ({id_type})",
        f"  ID:      {_format_can_id(arb_id, is_extended)}",
        f"  DLC:     {len(data)}",
        f"  Data:    {' '.join(f'{b:02X}' for b in data) if data else '[empty]'}",
    ]
    return '\n'.join(lines)


# ======================== Dependency Checks ========================

def _ensure_python_can():
    """Ensure python-can library is available.

    Raises:
        ImportError: If python-can is not installed.
    """
    try:
        import can  # noqa: F401
    except ImportError:
        raise ImportError(
            "python-can is required for PU2CANFD support. "
            "Install with: pip install python-can"
        )


# ======================== Platform Detection ========================

def _get_platform() -> str:
    """Detect the current operating system.

    Returns:
        str: "linux", "windows", or "other".
    """
    system = platform.system().lower()
    if system == "linux":
        return "linux"
    elif system == "windows":
        return "windows"
    return "other"


def _get_default_bustype() -> str:
    """Get the default python-can bus type for the current platform.

    The PU2CANFD adapter is PCAN-USB FD compatible:
    - Linux: appears as a SocketCAN interface (native driver)
    - Windows: requires PEAK PCANBasic driver ("pcan" interface)

    Returns:
        str: Bus type string for python-can (e.g., "socketcan", "pcan").
    """
    plat = _get_platform()
    if plat == "linux":
        return "socketcan"
    return "pcan"


def _check_pcan_driver() -> bool:
    """Check if the PEAK PCANBasic driver is installed (Windows).

    Returns:
        bool: True if PCANBasic.dll is available.
    """
    if _get_platform() != "windows":
        return True  # Not needed on Linux

    import ctypes
    try:
        ctypes.windll.LoadLibrary("PCANBasic")
        return True
    except OSError:
        return False


# ======================== Device Discovery ========================

def find_interfaces() -> List[Dict[str, Any]]:
    """Discover available CAN interfaces on the system.

    On Linux, enumerates SocketCAN interfaces (can0, can1, ...) from
    /sys/class/net/. On Windows, detects PCAN-USB FD adapters via USB
    enumeration and the PCANBasic driver.

    Returns:
        List[Dict[str, Any]]: List of dictionaries, each containing:
            - channel (str): Interface name (e.g., "can0", "PCAN_USBBUS1")
            - bustype (str): python-can bus type ("socketcan", "pcan")
            - platform (str): "linux" or "windows"
            - active (bool): Whether the interface is ready
            - vid (int, optional): USB vendor ID (Windows only)
            - pid (int, optional): USB product ID (Windows only)

    Raises:
        PU2CANFDError: If interface enumeration fails.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[PU2CANFD] INTERFACE DISCOVERY")
        logger.info("=" * 80)
        logger.info("")

    plat = _get_platform()
    interfaces = []

    try:
        if plat == "linux":
            interfaces = _find_linux_interfaces()
        elif plat == "windows":
            interfaces = _find_windows_interfaces()
        else:
            if logger:
                logger.warn(f"  Unsupported platform: {plat}")
    except Exception as e:
        if logger:
            logger.error(f"[PU2CANFD ERROR] Interface discovery failed: {type(e).__name__}: {e}")
        raise PU2CANFDError(f"Failed to enumerate CAN interfaces: {type(e).__name__}: {e}")

    if logger:
        logger.info(f"  CAN interfaces found: {len(interfaces)}")
        for iface in interfaces:
            logger.info(f"    Channel:  {iface['channel']}")
            logger.info(f"    Bustype:  {iface['bustype']}")
            logger.info(f"    Active:   {iface.get('active', 'N/A')}")
            logger.info("")
        logger.info("=" * 80)
        logger.info("")

    return interfaces


def _find_linux_interfaces() -> List[Dict[str, Any]]:
    """Enumerate SocketCAN interfaces on Linux.

    Returns:
        List[Dict[str, Any]]: List of CAN interface info dicts.
    """
    interfaces = []
    net_dir = "/sys/class/net"

    if not os.path.isdir(net_dir):
        return interfaces

    for name in sorted(os.listdir(net_dir)):
        if not name.startswith("can") and not name.startswith("vcan"):
            continue

        # Check if the interface type is CAN
        type_path = os.path.join(net_dir, name, "type")
        try:
            with open(type_path, "r") as f:
                net_type = f.read().strip()
            # Type 280 = ARPHRD_CAN
            if net_type != "280":
                continue
        except (OSError, IOError):
            continue

        # Check operstate
        oper_path = os.path.join(net_dir, name, "operstate")
        active = False
        try:
            with open(oper_path, "r") as f:
                active = f.read().strip().lower() == "up"
        except (OSError, IOError):
            pass

        interfaces.append({
            "channel": name,
            "bustype": "socketcan",
            "platform": "linux",
            "active": active,
        })

    return interfaces


def _find_windows_interfaces() -> List[Dict[str, Any]]:
    """Enumerate PCAN-USB FD adapters on Windows.

    First checks for the PU2CANFD device via USB enumeration, then
    verifies PCANBasic driver availability. The adapter uses the PEAK
    PCAN-USB FD protocol (VID 0x0C72, PID 0x0012).

    Returns:
        List[Dict[str, Any]]: List of CAN interface info dicts.
    """
    logger = get_active_logger()
    interfaces = []

    # Check if the PU2CANFD USB device is physically present
    usb_present = _detect_usb_device()

    if not usb_present:
        if logger:
            logger.info("  No PU2CANFD USB device detected")
        return interfaces

    # Check if PCANBasic driver is installed
    pcan_ok = _check_pcan_driver()

    if not pcan_ok:
        if logger:
            logger.warn("  PU2CANFD USB device found but PEAK driver not installed!")
            logger.warn("  Download PCANBasic from: https://www.peak-system.com/PCAN-Basic.239.0.html")
            logger.warn("  Install the driver, then re-run discovery.")
        # Still report the device so the user knows it's there
        interfaces.append({
            "channel": PCAN_USBBUS1,
            "bustype": "pcan",
            "platform": "windows",
            "active": False,
            "vid": PU2CANFD_USB_VID,
            "pid": PU2CANFD_USB_PID,
            "error": "PCANBasic driver not installed",
        })
        return interfaces

    # Try to detect how many PCAN channels are available
    channels = _enumerate_pcan_channels()
    if not channels:
        # Driver OK but no channels found — device may need re-plug
        channels = [PCAN_USBBUS1]

    for ch in channels:
        interfaces.append({
            "channel": ch,
            "bustype": "pcan",
            "platform": "windows",
            "active": True,
            "vid": PU2CANFD_USB_VID,
            "pid": PU2CANFD_USB_PID,
        })

    return interfaces


def _detect_usb_device() -> bool:
    """Check if a PU2CANFD USB device is physically connected.

    Uses libusb (via libusb_package) to detect the device by VID:PID.

    Returns:
        bool: True if the device is found on the USB bus.
    """
    try:
        import libusb_package
        import usb.core
        import usb.backend.libusb1 as libusb1

        be = libusb1.get_backend(find_library=libusb_package.find_library)
        dev = usb.core.find(idVendor=PU2CANFD_USB_VID,
                            idProduct=PU2CANFD_USB_PID, backend=be)
        return dev is not None
    except ImportError:
        # libusb not available, fall through
        pass
    except Exception:
        pass

    return False


def _enumerate_pcan_channels() -> List[str]:
    """Enumerate active PCAN USB channels via PCANBasic.

    Returns:
        List[str]: PCAN channel names (e.g., ["PCAN_USBBUS1"]).
    """
    try:
        from can.interfaces.pcan import PcanBus
        import ctypes

        pcan = ctypes.windll.LoadLibrary("PCANBasic")

        # PCAN_USBBUS1 = 0x51, check up to 8 channels
        channels = []
        for i in range(1, 9):
            handle = 0x50 + i  # PCAN_USBBUS1..PCAN_USBBUS8
            # Try GetStatus — returns 0 if channel is OK
            status = pcan.CAN_GetStatus(handle)
            if status == 0 or status == 0x20000:  # OK or bus light
                channels.append(f"PCAN_USBBUS{i}")

        return channels
    except Exception:
        return []
