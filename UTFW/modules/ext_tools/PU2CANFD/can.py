# can.py
"""
UTFW PU2CANFD CAN Module
==========================
High-level CAN / CAN FD communication functions and TestAction factories
for the Pibiger USB TO CAN FD adapter (PU2CANFD / SavvyCAN-FD series).

This module provides CAN bus communication through the python-can library,
supporting both SocketCAN (Linux) and SLCAN (Windows) backends. The
PU2CANFD adapter is a SocketCAN-class device that supports classic CAN
and CAN FD with data bitrates up to 12 Mbit/s.

All communication is logged using the UTFW logging system with detailed
frame dumps including ID, DLC, data hex, and frame type.

The module includes TestAction factories for common CAN operations:
- send: Transmit a CAN frame
- receive: Wait for and capture a CAN frame
- send_receive: Send a frame and wait for a response
- send_periodic: Transmit frames at a fixed interval
- bus_scan: Listen on the bus and report all traffic
- loopback: Validate CAN loopback (TX → RX on two channels)

Usage:
    import UTFW
    pu2canfd = UTFW.modules.ext_tools.PU2CANFD

    # Open a CAN bus connection
    bus = pu2canfd.can.open_bus("can0", bitrate=500000)

    # Use TestAction factories for framework integration
    action = pu2canfd.can.send(
        "Send heartbeat", channel="can0", arb_id=0x700,
        data=[0x05], bitrate=1000000
    )

Author: DvidMakesThings
"""

import time
import threading
from typing import Optional, Dict, List, Any, Union

from ....core.logger import get_active_logger
from ....core.core import TestAction
from ._base import (
    PU2CANFDError,
    _format_hex_dump,
    _format_can_id,
    _format_can_frame,
    _ensure_python_can,
    _get_default_bustype,
    CAN_EFF_FLAG,
    CAN_RTR_FLAG,
    CAN_SFF_MASK,
    CAN_EFF_MASK,
    CAN_MAX_DLC,
    CANFD_MAX_DLC,
    CAN_BITRATE_1000K,
    CAN_BITRATE_500K,
    CANFD_DBITRATE_2M,
    DEFAULT_SEND_TIMEOUT,
    DEFAULT_RECV_TIMEOUT,
)


class PU2CANFDCANError(PU2CANFDError):
    """Exception raised when CAN communication or validation fails.

    Args:
        message (str): Description of the error that occurred.
    """
    pass


# ======================== Global State ========================

_LAST_RX_MESSAGE: Optional[Any] = None


def _set_last_message(msg) -> None:
    """Store the last received CAN message for validation chaining.

    Args:
        msg: python-can Message object.
    """
    global _LAST_RX_MESSAGE
    _LAST_RX_MESSAGE = msg


def _get_last_message():
    """Get the last received CAN message.

    Returns:
        The last received python-can Message, or None.
    """
    return _LAST_RX_MESSAGE


# ======================== Bus Management ========================

def open_bus(channel: str, bustype: Optional[str] = None,
             bitrate: int = CAN_BITRATE_500K,
             dbitrate: Optional[int] = None,
             fd: bool = False,
             **kwargs) -> Any:
    """Open a CAN bus connection through the PU2CANFD adapter.

    Creates and returns a python-can Bus instance configured for the
    specified channel and parameters.

    Args:
        channel (str): CAN interface name.
            Linux: "can0", "can1", "vcan0", etc.
            Windows: COM port for SLCAN (e.g., "COM3").
        bustype (str, optional): python-can bus type.
            Defaults to "socketcan" on Linux, "slcan" on Windows.
        bitrate (int, optional): Nominal CAN bitrate in bit/s.
            Defaults to 500000 (500 kbit/s).
        dbitrate (int, optional): CAN FD data bitrate in bit/s.
            Required when fd=True. Defaults to None.
        fd (bool, optional): Enable CAN FD mode. Defaults to False.
        **kwargs: Additional keyword arguments passed to python-can Bus().

    Returns:
        can.Bus: Configured and opened CAN bus instance.

    Raises:
        PU2CANFDCANError: If the bus cannot be opened.
    """
    _ensure_python_can()
    import can

    logger = get_active_logger()

    if bustype is None:
        bustype = _get_default_bustype()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[PU2CANFD] OPEN BUS")
        logger.info("=" * 80)
        logger.info(f"  Channel:    {channel}")
        logger.info(f"  Bus Type:   {bustype}")
        logger.info(f"  Bitrate:    {bitrate} bit/s")
        if fd:
            logger.info(f"  FD Mode:    Enabled")
            logger.info(f"  D-Bitrate:  {dbitrate} bit/s")
        logger.info("")

    try:
        bus_kwargs = {
            "channel": channel,
            "bustype": bustype,
            "bitrate": bitrate,
        }

        if fd:
            bus_kwargs["fd"] = True
            if dbitrate is not None:
                bus_kwargs["dbitrate"] = dbitrate

        bus_kwargs.update(kwargs)

        bus = can.Bus(**bus_kwargs)

        if logger:
            logger.info(f"  Bus opened successfully")
            logger.info("=" * 80)
            logger.info("")

        return bus

    except Exception as e:
        if logger:
            logger.error("=" * 80)
            logger.error("[PU2CANFD ERROR] FAILED TO OPEN BUS")
            logger.error("=" * 80)
            logger.error(f"  Channel:  {channel}")
            logger.error(f"  Error:    {type(e).__name__}: {e}")
            logger.error("=" * 80)
        raise PU2CANFDCANError(
            f"Failed to open CAN bus on {channel}: {type(e).__name__}: {e}"
        )


def close_bus(bus) -> None:
    """Close a CAN bus connection.

    Args:
        bus: python-can Bus instance to close.
    """
    logger = get_active_logger()

    try:
        bus.shutdown()
        if logger:
            logger.info("[PU2CANFD] Bus closed")
    except Exception as e:
        if logger:
            logger.error(f"[PU2CANFD ERROR] Failed to close bus: {type(e).__name__}: {e}")


# ======================== Core CAN Functions ========================

def send_frame(bus, arb_id: int, data: Union[bytes, List[int]],
               is_extended: bool = False, is_fd: bool = False,
               is_remote: bool = False, bitrate_switch: bool = False,
               timeout: float = DEFAULT_SEND_TIMEOUT) -> None:
    """Send a single CAN frame on the bus.

    Args:
        bus: python-can Bus instance (from open_bus()).
        arb_id (int): CAN arbitration ID (11-bit or 29-bit).
        data (bytes or List[int]): Frame payload (0-8 bytes for CAN,
            0-64 bytes for CAN FD).
        is_extended (bool, optional): Use extended 29-bit ID. Defaults to False.
        is_fd (bool, optional): Send as CAN FD frame. Defaults to False.
        is_remote (bool, optional): Send as remote request. Defaults to False.
        bitrate_switch (bool, optional): Enable CAN FD bitrate switching
            for the data phase. Defaults to False.
        timeout (float, optional): Send timeout in seconds. Defaults to 1.0.

    Raises:
        PU2CANFDCANError: If the frame cannot be sent.
    """
    _ensure_python_can()
    import can

    logger = get_active_logger()
    data_bytes = bytes(data) if not isinstance(data, bytes) else data

    max_len = CANFD_MAX_DLC if is_fd else CAN_MAX_DLC
    if len(data_bytes) > max_len:
        raise PU2CANFDCANError(
            f"Data length {len(data_bytes)} exceeds maximum {max_len} bytes"
        )

    if logger:
        logger.info("")
        logger.info("-" * 80)
        logger.info("[PU2CANFD TX] TRANSMITTING")
        logger.info("-" * 80)
        logger.info(_format_can_frame(arb_id, data_bytes, is_extended, is_fd, is_remote))
        if data_bytes:
            logger.info(f"  Hex Dump:")
            for line in _format_hex_dump(data_bytes).split('\n'):
                logger.info(f"    {line}")
        logger.info("")

    try:
        msg = can.Message(
            arbitration_id=arb_id,
            data=data_bytes,
            is_extended_id=is_extended,
            is_fd=is_fd,
            is_remote_frame=is_remote,
            bitrate_switch=bitrate_switch,
        )
        bus.send(msg, timeout=timeout)

        if logger:
            logger.info(f"  [TX OK] Frame sent successfully")
            logger.info("")

    except can.CanError as e:
        if logger:
            logger.error(f"  [TX FAIL] {type(e).__name__}: {e}")
        raise PU2CANFDCANError(f"Failed to send CAN frame: {type(e).__name__}: {e}")


def receive_frame(bus, timeout: float = DEFAULT_RECV_TIMEOUT,
                  filter_id: Optional[int] = None) -> Optional[Any]:
    """Receive a single CAN frame from the bus.

    Blocks until a frame is received or the timeout expires. Optionally
    filters by arbitration ID.

    Args:
        bus: python-can Bus instance (from open_bus()).
        timeout (float, optional): Receive timeout in seconds. Defaults to 5.0.
        filter_id (int, optional): If set, only accept frames with this
            arbitration ID (masked to 11 or 29 bits). Defaults to None.

    Returns:
        can.Message or None: Received message, or None if timeout.

    Raises:
        PU2CANFDCANError: If a bus error occurs during receive.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("-" * 80)
        logger.info("[PU2CANFD RX] WAITING FOR FRAME")
        logger.info("-" * 80)
        logger.info(f"  Timeout:   {timeout:.1f}s")
        if filter_id is not None:
            logger.info(f"  Filter ID: 0x{filter_id:03X}")
        logger.info("")

    start = time.time()

    try:
        while True:
            remaining = timeout - (time.time() - start)
            if remaining <= 0:
                if logger:
                    logger.info(f"  [RX TIMEOUT] No frame received within {timeout:.1f}s")
                return None

            msg = bus.recv(timeout=remaining)

            if msg is None:
                if logger:
                    logger.info(f"  [RX TIMEOUT] No frame received within {timeout:.1f}s")
                return None

            # Apply ID filter if specified
            if filter_id is not None and msg.arbitration_id != filter_id:
                continue

            _set_last_message(msg)

            if logger:
                is_ext = msg.is_extended_id
                is_fd = getattr(msg, 'is_fd', False)
                is_rtr = msg.is_remote_frame
                logger.info(f"  [RX OK] Frame received")
                logger.info(_format_can_frame(
                    msg.arbitration_id, bytes(msg.data),
                    is_ext, is_fd, is_rtr
                ))
                if msg.data:
                    logger.info(f"  Hex Dump:")
                    for line in _format_hex_dump(bytes(msg.data)).split('\n'):
                        logger.info(f"      {line}")
                logger.info(f"  Timestamp: {msg.timestamp:.6f}")
                logger.info("")

            return msg

    except Exception as e:
        if logger:
            logger.error(f"  [RX ERROR] {type(e).__name__}: {e}")
        raise PU2CANFDCANError(f"Error receiving CAN frame: {type(e).__name__}: {e}")


def send_and_receive(bus, arb_id: int, data: Union[bytes, List[int]],
                     response_id: Optional[int] = None,
                     is_extended: bool = False, is_fd: bool = False,
                     bitrate_switch: bool = False,
                     timeout: float = DEFAULT_RECV_TIMEOUT) -> Optional[Any]:
    """Send a CAN frame and wait for a response.

    Transmits a frame and then listens for a reply, optionally filtered
    by a specific response arbitration ID.

    Args:
        bus: python-can Bus instance.
        arb_id (int): Arbitration ID for the outgoing frame.
        data (bytes or List[int]): Payload for the outgoing frame.
        response_id (int, optional): Expected response arbitration ID.
            If None, accepts the first frame received.
        is_extended (bool, optional): Use extended 29-bit ID. Defaults to False.
        is_fd (bool, optional): Send as CAN FD frame. Defaults to False.
        bitrate_switch (bool, optional): CAN FD bitrate switching. Defaults to False.
        timeout (float, optional): Receive timeout. Defaults to 5.0.

    Returns:
        can.Message or None: Response message, or None on timeout.

    Raises:
        PU2CANFDCANError: If send fails or a bus error occurs.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[PU2CANFD] SEND AND RECEIVE")
        logger.info("=" * 80)
        logger.info("")

    send_frame(bus, arb_id, data, is_extended=is_extended, is_fd=is_fd,
               bitrate_switch=bitrate_switch)

    return receive_frame(bus, timeout=timeout, filter_id=response_id)


def bus_scan(bus, duration: float = 5.0) -> List[Any]:
    """Listen on the CAN bus and collect all traffic.

    Passively captures all CAN frames for the specified duration.
    Useful for bus diagnostics and device discovery.

    Args:
        bus: python-can Bus instance.
        duration (float, optional): Capture duration in seconds. Defaults to 5.0.

    Returns:
        List[can.Message]: All captured CAN messages.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[PU2CANFD] BUS SCAN")
        logger.info("=" * 80)
        logger.info(f"  Duration: {duration:.1f}s")
        logger.info("")

    messages = []
    start = time.time()

    while (time.time() - start) < duration:
        remaining = duration - (time.time() - start)
        msg = bus.recv(timeout=min(remaining, 0.5))
        if msg is not None:
            messages.append(msg)

    # Log summary
    if logger:
        unique_ids = set(m.arbitration_id for m in messages)
        logger.info(f"  Total frames captured: {len(messages)}")
        logger.info(f"  Unique IDs:            {len(unique_ids)}")
        for uid in sorted(unique_ids):
            count = sum(1 for m in messages if m.arbitration_id == uid)
            logger.info(f"    0x{uid:03X}: {count} frames")
        logger.info("=" * 80)
        logger.info("")

    return messages


def set_filters(bus, filters: List[Dict[str, int]]) -> None:
    """Configure hardware acceptance filters on the CAN bus.

    Args:
        bus: python-can Bus instance.
        filters (List[Dict[str, int]]): List of filter dictionaries.
            Each dict should contain:
            - "can_id" (int): Acceptance ID
            - "can_mask" (int): Acceptance mask
            - "extended" (bool, optional): Extended ID filter

    Raises:
        PU2CANFDCANError: If filters cannot be set.
    """
    logger = get_active_logger()

    if logger:
        logger.info("[PU2CANFD] Setting bus filters:")
        for f in filters:
            logger.info(f"    ID: 0x{f['can_id']:03X}  Mask: 0x{f['can_mask']:03X}")

    try:
        bus.set_filters(filters)
    except Exception as e:
        if logger:
            logger.error(f"[PU2CANFD ERROR] Failed to set filters: {type(e).__name__}: {e}")
        raise PU2CANFDCANError(f"Failed to set CAN filters: {type(e).__name__}: {e}")


# ======================== Bus Context Manager ========================

class CANBus:
    """RAII context manager for CAN bus connections.

    Opens the bus on entry and ensures clean shutdown on exit.

    Usage:
        with CANBus("can0", bitrate=500000) as bus:
            send_frame(bus, 0x123, [0x01, 0x02])
            msg = receive_frame(bus)
    """

    def __init__(self, channel: str, bustype: Optional[str] = None,
                 bitrate: int = CAN_BITRATE_500K,
                 dbitrate: Optional[int] = None,
                 fd: bool = False, **kwargs):
        self.channel = channel
        self.bustype = bustype
        self.bitrate = bitrate
        self.dbitrate = dbitrate
        self.fd = fd
        self.kwargs = kwargs
        self._bus = None

    def __enter__(self):
        self._bus = open_bus(
            self.channel, self.bustype, self.bitrate,
            self.dbitrate, self.fd, **self.kwargs
        )
        return self._bus

    def __exit__(self, *_exc):
        if self._bus is not None:
            close_bus(self._bus)
            self._bus = None


# ======================== Linux Interface Setup ========================

def setup_interface(channel: str, bitrate: int = CAN_BITRATE_500K,
                    dbitrate: Optional[int] = None,
                    fd: bool = False) -> None:
    """Configure a SocketCAN interface (Linux only).

    Brings the interface down, sets bitrate parameters, then brings it
    back up. Requires appropriate permissions (typically root or CAP_NET_ADMIN).

    Args:
        channel (str): SocketCAN interface name (e.g., "can0").
        bitrate (int, optional): Nominal bitrate. Defaults to 500000.
        dbitrate (int, optional): CAN FD data bitrate. Required if fd=True.
        fd (bool, optional): Enable CAN FD mode. Defaults to False.

    Raises:
        PU2CANFDCANError: If the interface cannot be configured.
    """
    import subprocess

    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[PU2CANFD] SETUP INTERFACE")
        logger.info("=" * 80)
        logger.info(f"  Channel:   {channel}")
        logger.info(f"  Bitrate:   {bitrate}")
        if fd:
            logger.info(f"  D-Bitrate: {dbitrate}")
            logger.info(f"  FD Mode:   Enabled")
        logger.info("")

    try:
        # Bring interface down
        subprocess.run(
            ["ip", "link", "set", channel, "down"],
            check=True, capture_output=True, text=True
        )

        # Build link set command
        cmd = ["ip", "link", "set", channel, "up", "type", "can",
               "bitrate", str(bitrate)]
        if fd and dbitrate is not None:
            cmd.extend(["dbitrate", str(dbitrate), "fd", "on"])

        subprocess.run(cmd, check=True, capture_output=True, text=True)

        if logger:
            logger.info(f"  Interface {channel} configured and up")
            logger.info("=" * 80)
            logger.info("")

    except subprocess.CalledProcessError as e:
        if logger:
            logger.error(f"[PU2CANFD ERROR] Interface setup failed: {e.stderr.strip()}")
        raise PU2CANFDCANError(
            f"Failed to configure {channel}: {e.stderr.strip()}"
        )
    except FileNotFoundError:
        raise PU2CANFDCANError(
            "ip command not found. Interface setup requires Linux with iproute2."
        )


def teardown_interface(channel: str) -> None:
    """Bring a SocketCAN interface down (Linux only).

    Args:
        channel (str): SocketCAN interface name (e.g., "can0").
    """
    import subprocess

    logger = get_active_logger()

    try:
        subprocess.run(
            ["ip", "link", "set", channel, "down"],
            check=True, capture_output=True, text=True
        )
        if logger:
            logger.info(f"[PU2CANFD] Interface {channel} brought down")
    except Exception as e:
        if logger:
            logger.error(f"[PU2CANFD ERROR] Failed to bring down {channel}: {e}")


# ======================== TestAction Factories ========================

def send(name: str, channel: str, arb_id: int,
         data: Union[bytes, List[int]],
         bitrate: int = CAN_BITRATE_500K,
         bustype: Optional[str] = None,
         is_extended: bool = False,
         is_fd: bool = False,
         dbitrate: Optional[int] = None,
         bitrate_switch: bool = False,
         negative_test: bool = False) -> TestAction:
    """Create a TestAction that sends a CAN frame.

    Args:
        name (str): Human-readable action name.
        channel (str): CAN interface (e.g., "can0", "COM3").
        arb_id (int): CAN arbitration ID.
        data (bytes or List[int]): Frame payload.
        bitrate (int, optional): Nominal bitrate. Defaults to 500000.
        bustype (str, optional): python-can bus type. Auto-detected if None.
        is_extended (bool, optional): Extended 29-bit ID. Defaults to False.
        is_fd (bool, optional): CAN FD frame. Defaults to False.
        dbitrate (int, optional): CAN FD data bitrate.
        bitrate_switch (bool, optional): CAN FD bitrate switching.
        negative_test (bool, optional): Expect failure. Defaults to False.

    Returns:
        TestAction: Configured test action for CAN transmit.
    """
    data_bytes = bytes(data) if not isinstance(data, bytes) else data

    def execute():
        with CANBus(channel, bustype, bitrate, dbitrate, is_fd) as bus:
            send_frame(bus, arb_id, data_bytes,
                       is_extended=is_extended, is_fd=is_fd,
                       bitrate_switch=bitrate_switch)
        return True

    id_str = _format_can_id(arb_id, is_extended)
    data_str = ' '.join(f'{b:02X}' for b in data_bytes)

    metadata = {
        'display_command': f"CAN TX → {id_str} [{data_str}]",
        'display_expected': "Frame sent",
        'sent': f"CAN TX {id_str} [{data_str}] on {channel}",
    }

    return TestAction(
        name=name,
        execute_func=execute,
        negative_test=negative_test,
        metadata=metadata,
    )


def receive(name: str, channel: str,
            bitrate: int = CAN_BITRATE_500K,
            bustype: Optional[str] = None,
            filter_id: Optional[int] = None,
            timeout: float = DEFAULT_RECV_TIMEOUT,
            is_fd: bool = False,
            dbitrate: Optional[int] = None,
            negative_test: bool = False) -> TestAction:
    """Create a TestAction that receives a CAN frame.

    Args:
        name (str): Human-readable action name.
        channel (str): CAN interface.
        bitrate (int, optional): Nominal bitrate. Defaults to 500000.
        bustype (str, optional): python-can bus type. Auto-detected if None.
        filter_id (int, optional): Only accept frames with this ID.
        timeout (float, optional): Receive timeout. Defaults to 5.0.
        is_fd (bool, optional): CAN FD mode. Defaults to False.
        dbitrate (int, optional): CAN FD data bitrate.
        negative_test (bool, optional): Expect failure. Defaults to False.

    Returns:
        TestAction: Configured test action for CAN receive.
    """

    def execute():
        with CANBus(channel, bustype, bitrate, dbitrate, is_fd) as bus:
            msg = receive_frame(bus, timeout=timeout, filter_id=filter_id)
            if msg is None:
                raise PU2CANFDCANError(
                    f"No CAN frame received on {channel} within {timeout:.1f}s"
                )
            return {
                "arbitration_id": msg.arbitration_id,
                "data": list(msg.data),
                "dlc": msg.dlc,
                "is_extended_id": msg.is_extended_id,
                "is_fd": getattr(msg, 'is_fd', False),
                "timestamp": msg.timestamp,
            }

    filter_str = f" filter=0x{filter_id:03X}" if filter_id is not None else ""

    metadata = {
        'display_command': f"CAN RX ← {channel}{filter_str}",
        'display_expected': "Frame received",
    }

    return TestAction(
        name=name,
        execute_func=execute,
        negative_test=negative_test,
        metadata=metadata,
    )


def send_receive(name: str, channel: str, arb_id: int,
                 data: Union[bytes, List[int]],
                 response_id: Optional[int] = None,
                 bitrate: int = CAN_BITRATE_500K,
                 bustype: Optional[str] = None,
                 is_extended: bool = False,
                 is_fd: bool = False,
                 dbitrate: Optional[int] = None,
                 bitrate_switch: bool = False,
                 timeout: float = DEFAULT_RECV_TIMEOUT,
                 negative_test: bool = False) -> TestAction:
    """Create a TestAction that sends a CAN frame and waits for a response.

    Args:
        name (str): Human-readable action name.
        channel (str): CAN interface.
        arb_id (int): TX arbitration ID.
        data (bytes or List[int]): TX payload.
        response_id (int, optional): Expected response ID.
        bitrate (int, optional): Nominal bitrate. Defaults to 500000.
        bustype (str, optional): Bus type. Auto-detected if None.
        is_extended (bool, optional): Extended ID. Defaults to False.
        is_fd (bool, optional): CAN FD mode. Defaults to False.
        dbitrate (int, optional): CAN FD data bitrate.
        bitrate_switch (bool, optional): CAN FD bitrate switching.
        timeout (float, optional): RX timeout. Defaults to 5.0.
        negative_test (bool, optional): Expect failure. Defaults to False.

    Returns:
        TestAction: Configured test action for CAN send/receive.
    """
    data_bytes = bytes(data) if not isinstance(data, bytes) else data

    def execute():
        with CANBus(channel, bustype, bitrate, dbitrate, is_fd) as bus:
            msg = send_and_receive(
                bus, arb_id, data_bytes,
                response_id=response_id,
                is_extended=is_extended, is_fd=is_fd,
                bitrate_switch=bitrate_switch,
                timeout=timeout,
            )
            if msg is None:
                raise PU2CANFDCANError(
                    f"No response received for ID 0x{arb_id:03X} on {channel}"
                )
            return {
                "arbitration_id": msg.arbitration_id,
                "data": list(msg.data),
                "dlc": msg.dlc,
                "is_extended_id": msg.is_extended_id,
                "is_fd": getattr(msg, 'is_fd', False),
                "timestamp": msg.timestamp,
            }

    id_str = _format_can_id(arb_id, is_extended)
    data_str = ' '.join(f'{b:02X}' for b in data_bytes)
    resp_str = f" → 0x{response_id:03X}" if response_id else ""

    metadata = {
        'display_command': f"CAN TX {id_str} [{data_str}]{resp_str}",
        'display_expected': "Response received",
        'sent': f"CAN TX {id_str} [{data_str}] on {channel}",
    }

    return TestAction(
        name=name,
        execute_func=execute,
        negative_test=negative_test,
        metadata=metadata,
    )


def loopback(name: str, tx_channel: str, rx_channel: str,
             arb_id: int, data: Union[bytes, List[int]],
             bitrate: int = CAN_BITRATE_500K,
             bustype: Optional[str] = None,
             is_fd: bool = False,
             dbitrate: Optional[int] = None,
             timeout: float = DEFAULT_RECV_TIMEOUT,
             negative_test: bool = False) -> TestAction:
    """Create a TestAction that validates CAN loopback between two channels.

    Sends a frame on tx_channel and verifies it is received on rx_channel.
    Useful for hardware verification with two PU2CANFD adapters or a
    loopback cable.

    Args:
        name (str): Human-readable action name.
        tx_channel (str): Transmit CAN interface.
        rx_channel (str): Receive CAN interface.
        arb_id (int): CAN arbitration ID.
        data (bytes or List[int]): Frame payload.
        bitrate (int, optional): Nominal bitrate. Defaults to 500000.
        bustype (str, optional): Bus type. Auto-detected if None.
        is_fd (bool, optional): CAN FD mode. Defaults to False.
        dbitrate (int, optional): CAN FD data bitrate.
        timeout (float, optional): RX timeout. Defaults to 5.0.
        negative_test (bool, optional): Expect failure. Defaults to False.

    Returns:
        TestAction: Configured test action for CAN loopback validation.
    """
    data_bytes = bytes(data) if not isinstance(data, bytes) else data

    def execute():
        logger = get_active_logger()

        if logger:
            logger.info("")
            logger.info("=" * 80)
            logger.info("[PU2CANFD] LOOPBACK TEST")
            logger.info("=" * 80)
            logger.info(f"  TX Channel: {tx_channel}")
            logger.info(f"  RX Channel: {rx_channel}")
            logger.info(f"  Arb ID:     0x{arb_id:03X}")
            logger.info(f"  Data:       {' '.join(f'{b:02X}' for b in data_bytes)}")
            logger.info("")

        tx_bus = open_bus(tx_channel, bustype, bitrate, dbitrate, is_fd)
        rx_bus = open_bus(rx_channel, bustype, bitrate, dbitrate, is_fd)

        try:
            send_frame(tx_bus, arb_id, data_bytes, is_fd=is_fd)
            msg = receive_frame(rx_bus, timeout=timeout, filter_id=arb_id)

            if msg is None:
                raise PU2CANFDCANError(
                    f"Loopback failed: no frame received on {rx_channel} "
                    f"within {timeout:.1f}s"
                )

            rx_data = bytes(msg.data)
            if rx_data != data_bytes:
                raise PU2CANFDCANError(
                    f"Loopback data mismatch:\n"
                    f"  TX: {' '.join(f'{b:02X}' for b in data_bytes)}\n"
                    f"  RX: {' '.join(f'{b:02X}' for b in rx_data)}"
                )

            if logger:
                logger.info("[PU2CANFD] Loopback test PASSED")
                logger.info("=" * 80)
                logger.info("")

            return rx_data

        finally:
            close_bus(tx_bus)
            close_bus(rx_bus)

    id_str = _format_can_id(arb_id, False)
    data_str = ' '.join(f'{b:02X}' for b in data_bytes)

    metadata = {
        'display_command': f"CAN loopback {tx_channel}→{rx_channel} {id_str} [{data_str}]",
        'display_expected': "Data matches",
        'sent': f"CAN loopback {id_str} [{data_str}]",
    }

    return TestAction(
        name=name,
        execute_func=execute,
        negative_test=negative_test,
        metadata=metadata,
    )


def scan(name: str, channel: str,
         bitrate: int = CAN_BITRATE_500K,
         bustype: Optional[str] = None,
         duration: float = 5.0,
         is_fd: bool = False,
         dbitrate: Optional[int] = None,
         negative_test: bool = False) -> TestAction:
    """Create a TestAction that scans the CAN bus for traffic.

    Listens passively for the specified duration and returns a summary
    of all captured traffic.

    Args:
        name (str): Human-readable action name.
        channel (str): CAN interface.
        bitrate (int, optional): Nominal bitrate. Defaults to 500000.
        bustype (str, optional): Bus type. Auto-detected if None.
        duration (float, optional): Scan duration. Defaults to 5.0.
        is_fd (bool, optional): CAN FD mode. Defaults to False.
        dbitrate (int, optional): CAN FD data bitrate.
        negative_test (bool, optional): Expect failure. Defaults to False.

    Returns:
        TestAction: Configured test action for CAN bus scanning.
    """

    def execute():
        with CANBus(channel, bustype, bitrate, dbitrate, is_fd) as bus:
            messages = bus_scan(bus, duration=duration)
            if not messages:
                raise PU2CANFDCANError(
                    f"No CAN traffic detected on {channel} in {duration:.1f}s"
                )

            unique_ids = set(m.arbitration_id for m in messages)
            return {
                "total_frames": len(messages),
                "unique_ids": sorted(unique_ids),
                "duration": duration,
                "frames_per_second": len(messages) / duration if duration > 0 else 0,
            }

    metadata = {
        'display_command': f"CAN scan {channel} ({duration:.1f}s)",
        'display_expected': "Traffic detected",
    }

    return TestAction(
        name=name,
        execute_func=execute,
        negative_test=negative_test,
        metadata=metadata,
    )


def validate_last_frame(name: str, expected_id: Optional[int] = None,
                        expected_data: Optional[Union[bytes, List[int]]] = None,
                        negative_test: bool = False) -> TestAction:
    """Create a TestAction that validates the last received CAN frame.

    Uses the cached last-received message (from receive_frame or
    send_and_receive) for validation without requiring a new bus
    transaction.

    Args:
        name (str): Human-readable action name.
        expected_id (int, optional): Expected arbitration ID.
        expected_data (bytes or List[int], optional): Expected payload.
        negative_test (bool, optional): Expect failure. Defaults to False.

    Returns:
        TestAction: Configured test action for frame validation.
    """

    def execute():
        logger = get_active_logger()
        msg = _get_last_message()

        if msg is None:
            raise PU2CANFDCANError(
                "No cached CAN message. Call receive or send_receive first."
            )

        if logger:
            logger.info("")
            logger.info("-" * 80)
            logger.info("[PU2CANFD] VALIDATE LAST FRAME")
            logger.info("-" * 80)

        if expected_id is not None:
            if msg.arbitration_id != expected_id:
                raise PU2CANFDCANError(
                    f"ID mismatch: expected 0x{expected_id:03X}, "
                    f"got 0x{msg.arbitration_id:03X}"
                )
            if logger:
                logger.info(f"  ID:   0x{msg.arbitration_id:03X} == 0x{expected_id:03X}  OK")

        if expected_data is not None:
            expected_bytes = bytes(expected_data) if not isinstance(expected_data, bytes) else expected_data
            rx_data = bytes(msg.data)
            if rx_data != expected_bytes:
                raise PU2CANFDCANError(
                    f"Data mismatch:\n"
                    f"  Expected: {' '.join(f'{b:02X}' for b in expected_bytes)}\n"
                    f"  Received: {' '.join(f'{b:02X}' for b in rx_data)}"
                )
            if logger:
                logger.info(f"  Data: {' '.join(f'{b:02X}' for b in rx_data)}  OK")

        if logger:
            logger.info(f"  Validation PASSED")
            logger.info("")

        return True

    expected_parts = []
    if expected_id is not None:
        expected_parts.append(f"ID=0x{expected_id:03X}")
    if expected_data is not None:
        data_bytes = bytes(expected_data) if not isinstance(expected_data, bytes) else expected_data
        expected_parts.append(f"Data=[{' '.join(f'{b:02X}' for b in data_bytes)}]")

    metadata = {
        'display_command': "Validate last CAN frame",
        'display_expected': ', '.join(expected_parts) if expected_parts else "Valid frame",
    }

    return TestAction(
        name=name,
        execute_func=execute,
        negative_test=negative_test,
        metadata=metadata,
    )
