"""
UTFW/modules/ext_tools/PU2CANFD/__init__.py

UTFW PU2CANFD Adapter Module
==============================

CAN / CAN FD test module for the Pibiger USB TO CAN FD adapter
(PU2CANFD / SavvyCAN-FD series).

This package exposes two protocol sub-modules accessible as:
    PU2CANFD.can.send(...)              # Raw CAN frame operations
    PU2CANFD.can.receive(...)
    PU2CANFD.can.loopback(...)
    PU2CANFD.canopen.sdo_read(...)      # CANopen protocol layer
    PU2CANFD.canopen.nmt_start(...)
    PU2CANFD.canopen.heartbeat(...)

Sub-modules:
- can:     Raw CAN / CAN FD frame send, receive, loopback, bus scan
- canopen: CANopen NMT, SDO, PDO, heartbeat, and eWald board helpers

Shared utilities (interface discovery, hex formatting) are available
from the package level:
    PU2CANFD.find_interfaces()

Hardware Features:
- SocketCAN-compatible (Linux native kernel driver, zero-config)
- Supports CAN 2.0A/B and CAN FD (up to 12 Mbit/s data rate)
- 2.5 kV signal & power isolation
- 1 us timestamp resolution

Dependencies:
    pip install python-can

Author: DvidMakesThings
"""

import importlib

from ._base import (
    PU2CANFDError,
    find_interfaces,
    _format_hex_dump,
    _format_can_id,
    _format_can_frame,
    PU2CANFD_USB_VID,
    PU2CANFD_USB_PID,
    PCAN_USBBUS1,
    PCAN_USBBUS2,
    CAN_BITRATE_1000K,
    CAN_BITRATE_500K,
    CAN_BITRATE_250K,
    CAN_BITRATE_125K,
    CAN_BITRATE_100K,
    CAN_BITRATE_50K,
    CANFD_DBITRATE_8M,
    CANFD_DBITRATE_5M,
    CANFD_DBITRATE_2M,
    CANFD_DBITRATE_1M,
    CAN_EFF_FLAG,
    CAN_RTR_FLAG,
    CAN_ERR_FLAG,
    CAN_SFF_MASK,
    CAN_EFF_MASK,
    CAN_MAX_DLC,
    CANFD_MAX_DLC,
)

__all__ = [
    # Sub-modules (lazy loaded)
    "can",
    "canopen",

    # Base exception
    "PU2CANFDError",

    # Device discovery
    "find_interfaces",

    # Device identity
    "PU2CANFD_USB_VID",
    "PU2CANFD_USB_PID",
    "PCAN_USBBUS1",
    "PCAN_USBBUS2",

    # CAN bitrate constants
    "CAN_BITRATE_1000K",
    "CAN_BITRATE_500K",
    "CAN_BITRATE_250K",
    "CAN_BITRATE_125K",
    "CAN_BITRATE_100K",
    "CAN_BITRATE_50K",

    # CAN FD data bitrate constants
    "CANFD_DBITRATE_8M",
    "CANFD_DBITRATE_5M",
    "CANFD_DBITRATE_2M",
    "CANFD_DBITRATE_1M",

    # CAN ID flags & masks
    "CAN_EFF_FLAG",
    "CAN_RTR_FLAG",
    "CAN_ERR_FLAG",
    "CAN_SFF_MASK",
    "CAN_EFF_MASK",
    "CAN_MAX_DLC",
    "CANFD_MAX_DLC",
]


def __getattr__(name):  # pragma: no cover - simple delegation
    """Lazy-load protocol sub-modules on first access."""
    if name in ("can", "canopen"):
        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__} has no attribute {name}")
