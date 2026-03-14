# canopen.py
"""
UTFW PU2CANFD CANopen Module
===============================
CANopen protocol helpers and TestAction factories for interfacing
with CANopen devices (e.g., the eWald development board) through
the PU2CANFD USB-CAN adapter.

This module implements common CANopen services on top of the raw CAN
driver, allowing the test framework to communicate with CANopen nodes
using standard protocol operations.

Supported CANopen Services:
- NMT (Network Management): Start, Stop, Pre-Operational, Reset
- SDO (Service Data Object): Read/write object dictionary entries
- PDO (Process Data Object): Receive and parse process data
- Heartbeat: Monitor node health
- SYNC: Trigger synchronous PDO exchange

eWald Object Dictionary Reference (from CONFIG.h / app_canopen.c):
    0x2000       : Micro mode
    0x2010:01-02 : Measurement short mode / time
    0x2020:01-03 : DC PID mode / voltage / current
    0x2030:01-04 : PWM voltage / frequency / duty / pulses
    0x2040:01-02 : Load mode / short time
    0x2050:01    : Resistance
    0x2060:01-03 : Pulse edge mode / threshold / count
    0x3000:01-08 : Return status (state/dio/flags/duty/freq/V/I/pulses)
    0x4000-4070  : Trigger objects
    0x5000-5090  : Settings (feedback/sbus/dio/threshold/pid/prescaler)

Usage:
    import UTFW
    pu2canfd = UTFW.modules.ext_tools.PU2CANFD

    # Send NMT Start to node 5
    action = pu2canfd.canopen.nmt_start("Start eWald", "can0", node_id=5)

    # Read SDO from object 0x3000:06 (voltage)
    action = pu2canfd.canopen.sdo_read(
        "Read voltage", "can0", node_id=5, index=0x3000, subindex=6
    )

Author: DvidMakesThings
"""

import struct
import time
from typing import Optional, Dict, List, Any, Union

from ....core.logger import get_active_logger
from ....core.core import TestAction
from ._base import (
    PU2CANFDError,
    _format_hex_dump,
    _format_can_id,
    CAN_BITRATE_500K,
    CAN_BITRATE_1000K,
    DEFAULT_RECV_TIMEOUT,
)
from .can import (
    PU2CANFDCANError,
    CANBus,
    send_frame,
    receive_frame,
)


# ======================== CANopen Constants ========================

# NMT (Network Management) command specifiers
NMT_START_REMOTE_NODE = 0x01
NMT_STOP_REMOTE_NODE = 0x02
NMT_ENTER_PREOPERATIONAL = 0x80
NMT_RESET_NODE = 0x81
NMT_RESET_COMMUNICATION = 0x82

NMT_CMD_NAMES = {
    NMT_START_REMOTE_NODE: "Start",
    NMT_STOP_REMOTE_NODE: "Stop",
    NMT_ENTER_PREOPERATIONAL: "Pre-Operational",
    NMT_RESET_NODE: "Reset Node",
    NMT_RESET_COMMUNICATION: "Reset Communication",
}

# CANopen function codes (COB-ID = function_code + node_id)
CANOPEN_NMT = 0x000          # NMT master → all nodes
CANOPEN_SYNC = 0x080         # SYNC broadcast
CANOPEN_EMERGENCY = 0x080    # Emergency (+ node ID)
CANOPEN_TPDO1 = 0x180        # Transmit PDO1
CANOPEN_RPDO1 = 0x200        # Receive PDO1
CANOPEN_TPDO2 = 0x280        # Transmit PDO2
CANOPEN_RPDO2 = 0x300        # Receive PDO2
CANOPEN_TPDO3 = 0x380        # Transmit PDO3
CANOPEN_RPDO3 = 0x400        # Receive PDO3
CANOPEN_TPDO4 = 0x480        # Transmit PDO4
CANOPEN_RPDO4 = 0x500        # Receive PDO4
CANOPEN_SDO_TX = 0x580       # SDO response (server → client)
CANOPEN_SDO_RX = 0x600       # SDO request  (client → server)
CANOPEN_HEARTBEAT = 0x700    # Heartbeat / NMT error control

# SDO command specifiers (client → server)
SDO_CCS_DOWNLOAD_INITIATE = 0x20   # Write (initiate)
SDO_CCS_UPLOAD_INITIATE = 0x40     # Read (initiate)
SDO_CCS_ABORT = 0x80               # Abort transfer

# SDO command specifiers (server → client)
SDO_SCS_UPLOAD_INITIATE = 0x40     # Read response
SDO_SCS_DOWNLOAD_INITIATE = 0x60   # Write confirmation
SDO_SCS_ABORT = 0x80               # Abort from server

# SDO abort codes
SDO_ABORT_CODES = {
    0x05030000: "Toggle bit not alternated",
    0x05040000: "SDO protocol timed out",
    0x05040001: "Client/server specifier not valid",
    0x05040005: "Out of memory",
    0x06010000: "Unsupported access to object",
    0x06010001: "Attempt to read a write-only object",
    0x06010002: "Attempt to write a read-only object",
    0x06020000: "Object does not exist in dictionary",
    0x06040041: "Object cannot be mapped to PDO",
    0x06040042: "Number of mapped objects exceeds PDO length",
    0x06040043: "General parameter incompatibility",
    0x06070010: "Data type mismatch (length of service parameter)",
    0x06070012: "Data type mismatch (length too high)",
    0x06070013: "Data type mismatch (length too low)",
    0x06090011: "Sub-index does not exist",
    0x06090030: "Value range exceeded",
    0x06090031: "Value too high",
    0x06090032: "Value too low",
    0x08000000: "General error",
    0x08000020: "Data cannot be transferred or stored",
    0x08000021: "Data cannot be transferred (local control)",
    0x08000022: "Data cannot be transferred (device state)",
}

# Heartbeat states
HEARTBEAT_BOOT_UP = 0x00
HEARTBEAT_STOPPED = 0x04
HEARTBEAT_OPERATIONAL = 0x05
HEARTBEAT_PRE_OPERATIONAL = 0x7F

HEARTBEAT_STATE_NAMES = {
    HEARTBEAT_BOOT_UP: "Boot-Up",
    HEARTBEAT_STOPPED: "Stopped",
    HEARTBEAT_OPERATIONAL: "Operational",
    HEARTBEAT_PRE_OPERATIONAL: "Pre-Operational",
}


class PU2CANFDCANopenError(PU2CANFDError):
    """Exception raised when a CANopen protocol operation fails.

    Args:
        message (str): Description of the error.
    """
    pass


# ======================== Global State ========================

_LAST_SDO_VALUE: Optional[bytes] = None


def _set_last_sdo(value: bytes) -> None:
    """Cache the last SDO read value for validation chaining."""
    global _LAST_SDO_VALUE
    _LAST_SDO_VALUE = value


def _get_last_sdo() -> Optional[bytes]:
    """Get the last cached SDO read value."""
    return _LAST_SDO_VALUE


# ======================== NMT Functions ========================

def nmt_command(bus, node_id: int, command: int) -> None:
    """Send an NMT command to a CANopen node.

    NMT frames are sent to COB-ID 0x000 with 2 bytes:
    [command_specifier, node_id] (node_id=0 addresses all nodes).

    Args:
        bus: python-can Bus instance.
        node_id (int): Target node ID (1-127), or 0 for broadcast.
        command (int): NMT command specifier.

    Raises:
        PU2CANFDCANopenError: If the command cannot be sent.
    """
    logger = get_active_logger()
    cmd_name = NMT_CMD_NAMES.get(command, f"Unknown(0x{command:02X})")

    if logger:
        logger.info("")
        logger.info("-" * 80)
        logger.info(f"[CANopen NMT] {cmd_name}")
        logger.info("-" * 80)
        logger.info(f"  Node ID: {node_id}")
        logger.info(f"  Command: 0x{command:02X} ({cmd_name})")
        logger.info("")

    try:
        send_frame(bus, CANOPEN_NMT, [command, node_id])
    except PU2CANFDCANError as e:
        raise PU2CANFDCANopenError(f"NMT {cmd_name} failed: {e}")


# ======================== SYNC Function ========================

def sync(bus) -> None:
    """Send a CANopen SYNC broadcast.

    SYNC is sent to COB-ID 0x080 with no data payload.

    Args:
        bus: python-can Bus instance.
    """
    logger = get_active_logger()

    if logger:
        logger.info("[CANopen] SYNC broadcast")

    send_frame(bus, CANOPEN_SYNC, [])


# ======================== SDO Functions ========================

def sdo_read_raw(bus, node_id: int, index: int, subindex: int,
                 timeout: float = DEFAULT_RECV_TIMEOUT) -> bytes:
    """Read an SDO value from a CANopen node (expedited upload).

    Sends an SDO upload initiate request and waits for the response.
    Supports expedited transfers (up to 4 bytes).

    Args:
        bus: python-can Bus instance.
        node_id (int): Target node ID (1-127).
        index (int): Object dictionary index (16-bit).
        subindex (int): Object dictionary sub-index (8-bit).
        timeout (float, optional): Response timeout. Defaults to 5.0.

    Returns:
        bytes: Raw SDO value (1-4 bytes).

    Raises:
        PU2CANFDCANopenError: If the read fails or is aborted.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("-" * 80)
        logger.info("[CANopen SDO] READ (Upload Initiate)")
        logger.info("-" * 80)
        logger.info(f"  Node ID:  {node_id}")
        logger.info(f"  Index:    0x{index:04X}")
        logger.info(f"  SubIndex: 0x{subindex:02X}")
        logger.info("")

    # Build SDO upload initiate request
    # Byte 0: command specifier (0x40 = upload initiate)
    # Byte 1-2: index (little-endian)
    # Byte 3: sub-index
    # Byte 4-7: reserved (zero)
    sdo_data = struct.pack('<BHBI', SDO_CCS_UPLOAD_INITIATE, index, subindex, 0)

    tx_cob_id = CANOPEN_SDO_RX + node_id
    rx_cob_id = CANOPEN_SDO_TX + node_id

    send_frame(bus, tx_cob_id, sdo_data)
    response = receive_frame(bus, timeout=timeout, filter_id=rx_cob_id)

    if response is None:
        raise PU2CANFDCANopenError(
            f"SDO read timeout: node {node_id}, "
            f"index 0x{index:04X}:{subindex:02X}"
        )

    rdata = bytes(response.data)

    # Check for abort
    if rdata[0] & 0xE0 == SDO_SCS_ABORT:
        abort_code = struct.unpack_from('<I', rdata, 4)[0]
        abort_msg = SDO_ABORT_CODES.get(abort_code, "Unknown")
        raise PU2CANFDCANopenError(
            f"SDO abort from node {node_id}: "
            f"0x{abort_code:08X} ({abort_msg})"
        )

    # Parse expedited upload response
    # Byte 0: SCS + flags (size indication, expedited, etc.)
    scs = rdata[0]
    expedited = bool(scs & 0x02)
    size_indicated = bool(scs & 0x01)

    if expedited:
        # Number of bytes that do NOT contain data
        n = (scs >> 2) & 0x03
        data_len = 4 - n if size_indicated else 4
        value = rdata[4:4 + data_len]
    else:
        # Non-expedited: for now, just take 4 bytes
        value = rdata[4:8]

    _set_last_sdo(value)

    if logger:
        logger.info(f"  [SDO OK] Value: {' '.join(f'{b:02X}' for b in value)}")
        logger.info(f"           ({int.from_bytes(value, 'little') if len(value) <= 4 else 'multi-byte'})")
        logger.info("")

    return value


def sdo_write_raw(bus, node_id: int, index: int, subindex: int,
                  data: Union[bytes, List[int]], size: int = 0,
                  timeout: float = DEFAULT_RECV_TIMEOUT) -> None:
    """Write an SDO value to a CANopen node (expedited download).

    Sends an SDO download initiate request with the given data and
    waits for confirmation.

    Args:
        bus: python-can Bus instance.
        node_id (int): Target node ID (1-127).
        index (int): Object dictionary index (16-bit).
        subindex (int): Object dictionary sub-index (8-bit).
        data (bytes or List[int]): Value to write (1-4 bytes for expedited).
        size (int, optional): Explicit data size. If 0, inferred from data.
        timeout (float, optional): Response timeout. Defaults to 5.0.

    Raises:
        PU2CANFDCANopenError: If the write fails or is aborted.
    """
    logger = get_active_logger()
    data_bytes = bytes(data) if not isinstance(data, bytes) else data

    if size == 0:
        size = len(data_bytes)

    if logger:
        logger.info("")
        logger.info("-" * 80)
        logger.info("[CANopen SDO] WRITE (Download Initiate)")
        logger.info("-" * 80)
        logger.info(f"  Node ID:  {node_id}")
        logger.info(f"  Index:    0x{index:04X}")
        logger.info(f"  SubIndex: 0x{subindex:02X}")
        logger.info(f"  Value:    {' '.join(f'{b:02X}' for b in data_bytes)}")
        logger.info("")

    # Build expedited download initiate
    # n = number of bytes in data part that do not contain data
    n = 4 - size
    # Command byte: CCS=0x20 | n<<2 | expedited=0x02 | size_indicated=0x01
    cmd = SDO_CCS_DOWNLOAD_INITIATE | ((n & 0x03) << 2) | 0x02 | 0x01

    sdo_frame = bytearray(8)
    sdo_frame[0] = cmd
    struct.pack_into('<H', sdo_frame, 1, index)
    sdo_frame[3] = subindex
    sdo_frame[4:4 + size] = data_bytes[:size]

    tx_cob_id = CANOPEN_SDO_RX + node_id
    rx_cob_id = CANOPEN_SDO_TX + node_id

    send_frame(bus, tx_cob_id, bytes(sdo_frame))
    response = receive_frame(bus, timeout=timeout, filter_id=rx_cob_id)

    if response is None:
        raise PU2CANFDCANopenError(
            f"SDO write timeout: node {node_id}, "
            f"index 0x{index:04X}:{subindex:02X}"
        )

    rdata = bytes(response.data)

    # Check for abort
    if rdata[0] & 0xE0 == SDO_SCS_ABORT:
        abort_code = struct.unpack_from('<I', rdata, 4)[0]
        abort_msg = SDO_ABORT_CODES.get(abort_code, "Unknown")
        raise PU2CANFDCANopenError(
            f"SDO abort from node {node_id}: "
            f"0x{abort_code:08X} ({abort_msg})"
        )

    if logger:
        logger.info(f"  [SDO OK] Write confirmed")
        logger.info("")


# ======================== Typed SDO Helpers ========================

def sdo_read_u8(bus, node_id: int, index: int, subindex: int,
                timeout: float = DEFAULT_RECV_TIMEOUT) -> int:
    """Read an 8-bit unsigned integer from the object dictionary."""
    raw = sdo_read_raw(bus, node_id, index, subindex, timeout)
    return raw[0]


def sdo_read_u16(bus, node_id: int, index: int, subindex: int,
                 timeout: float = DEFAULT_RECV_TIMEOUT) -> int:
    """Read a 16-bit unsigned integer from the object dictionary."""
    raw = sdo_read_raw(bus, node_id, index, subindex, timeout)
    return int.from_bytes(raw[:2], 'little')


def sdo_read_u32(bus, node_id: int, index: int, subindex: int,
                 timeout: float = DEFAULT_RECV_TIMEOUT) -> int:
    """Read a 32-bit unsigned integer from the object dictionary."""
    raw = sdo_read_raw(bus, node_id, index, subindex, timeout)
    return int.from_bytes(raw[:4], 'little')


def sdo_read_float(bus, node_id: int, index: int, subindex: int,
                   timeout: float = DEFAULT_RECV_TIMEOUT) -> float:
    """Read a 32-bit float from the object dictionary."""
    raw = sdo_read_raw(bus, node_id, index, subindex, timeout)
    return struct.unpack('<f', raw[:4])[0]


def sdo_write_u8(bus, node_id: int, index: int, subindex: int,
                 value: int, timeout: float = DEFAULT_RECV_TIMEOUT) -> None:
    """Write an 8-bit unsigned integer to the object dictionary."""
    sdo_write_raw(bus, node_id, index, subindex, bytes([value & 0xFF]), size=1, timeout=timeout)


def sdo_write_u16(bus, node_id: int, index: int, subindex: int,
                  value: int, timeout: float = DEFAULT_RECV_TIMEOUT) -> None:
    """Write a 16-bit unsigned integer to the object dictionary."""
    sdo_write_raw(bus, node_id, index, subindex,
                  struct.pack('<H', value & 0xFFFF), size=2, timeout=timeout)


def sdo_write_u32(bus, node_id: int, index: int, subindex: int,
                  value: int, timeout: float = DEFAULT_RECV_TIMEOUT) -> None:
    """Write a 32-bit unsigned integer to the object dictionary."""
    sdo_write_raw(bus, node_id, index, subindex,
                  struct.pack('<I', value & 0xFFFFFFFF), size=4, timeout=timeout)


def sdo_write_float(bus, node_id: int, index: int, subindex: int,
                    value: float, timeout: float = DEFAULT_RECV_TIMEOUT) -> None:
    """Write a 32-bit float to the object dictionary."""
    sdo_write_raw(bus, node_id, index, subindex,
                  struct.pack('<f', value), size=4, timeout=timeout)


# ======================== Heartbeat Monitoring ========================

def wait_for_heartbeat(bus, node_id: int,
                       expected_state: Optional[int] = None,
                       timeout: float = DEFAULT_RECV_TIMEOUT) -> Dict[str, Any]:
    """Wait for a heartbeat message from a CANopen node.

    Heartbeat messages are sent on COB-ID 0x700 + node_id, with a
    single data byte indicating the node state.

    Args:
        bus: python-can Bus instance.
        node_id (int): Target node ID (1-127).
        expected_state (int, optional): If set, waits until this state
            is seen or timeout. Use HEARTBEAT_* constants.
        timeout (float, optional): Timeout in seconds. Defaults to 5.0.

    Returns:
        Dict with keys: "node_id", "state", "state_name", "timestamp".

    Raises:
        PU2CANFDCANopenError: If no heartbeat is received in time.
    """
    logger = get_active_logger()
    hb_cob_id = CANOPEN_HEARTBEAT + node_id

    if logger:
        logger.info("")
        logger.info("-" * 80)
        logger.info("[CANopen] WAIT FOR HEARTBEAT")
        logger.info("-" * 80)
        logger.info(f"  Node ID:  {node_id}")
        logger.info(f"  COB-ID:   0x{hb_cob_id:03X}")
        if expected_state is not None:
            logger.info(f"  Expected: {HEARTBEAT_STATE_NAMES.get(expected_state, '?')}")
        logger.info("")

    start = time.time()

    while (time.time() - start) < timeout:
        remaining = timeout - (time.time() - start)
        msg = receive_frame(bus, timeout=remaining, filter_id=hb_cob_id)

        if msg is None:
            break

        state = msg.data[0] & 0x7F
        state_name = HEARTBEAT_STATE_NAMES.get(state, f"Unknown(0x{state:02X})")

        if logger:
            logger.info(f"  Heartbeat: node {node_id} state={state_name}")

        if expected_state is None or state == expected_state:
            return {
                "node_id": node_id,
                "state": state,
                "state_name": state_name,
                "timestamp": msg.timestamp,
            }

    raise PU2CANFDCANopenError(
        f"No heartbeat from node {node_id} within {timeout:.1f}s"
    )


# ======================== eWald Object Dictionary Indices ========================
# Mirrors CONFIG.h from the eWald firmware

EWALD_OD_MICRO_MODE = 0x2000
EWALD_OD_MEAS_SHORT = 0x2010
EWALD_OD_DCPID = 0x2020
EWALD_OD_PWM_CFG = 0x2030
EWALD_OD_LOAD = 0x2040
EWALD_OD_RESISTANCE = 0x2050
EWALD_OD_PULSE = 0x2060
EWALD_OD_STATUS = 0x3000
EWALD_OD_SHORT_TRIGGER = 0x4000
EWALD_OD_TEMPERATURE = 0x4010
EWALD_OD_PULSE_TRIGGER = 0x4020
EWALD_OD_TRIGGER_PWM = 0x4030
EWALD_OD_TRIGGER_PULSE = 0x4040
EWALD_OD_PULSES_COMPLETE = 0x4050
EWALD_OD_PULSE_DURATION = 0x4060
EWALD_OD_SERIAL_NUMBER = 0x4070
EWALD_OD_FEEDBACK = 0x5000
EWALD_OD_SBUS = 0x5010
EWALD_OD_DIGITALIO = 0x5020
EWALD_OD_THRESHOLD = 0x5030
EWALD_OD_PID_PARAM = 0x5050
EWALD_OD_VERSION = 0x5060
EWALD_OD_PWM_PRESCALER = 0x5070
EWALD_OD_FREQ_DETAIL = 0x5080
EWALD_OD_TRIGGER_FW_UPDATE = 0x5090

# eWald status sub-indices (0x3000)
EWALD_SUB_STATE = 0x01
EWALD_SUB_DIO = 0x02
EWALD_SUB_FLAGS = 0x03
EWALD_SUB_DUTY = 0x04
EWALD_SUB_FREQUENCY = 0x05
EWALD_SUB_VOLTAGE = 0x06
EWALD_SUB_CURRENT = 0x07
EWALD_SUB_PULSES_DONE = 0x08

# Default eWald CAN settings (from CONFIG.h)
EWALD_DEFAULT_BITRATE = CAN_BITRATE_1000K


# ======================== TestAction Factories ========================

def nmt_start(name: str, channel: str, node_id: int,
              bitrate: int = CAN_BITRATE_1000K,
              bustype: Optional[str] = None,
              negative_test: bool = False) -> TestAction:
    """Create a TestAction that sends NMT Start to a CANopen node.

    Transitions the node to Operational state.

    Args:
        name (str): Human-readable action name.
        channel (str): CAN interface.
        node_id (int): Target node ID (1-127).
        bitrate (int, optional): Bitrate. Defaults to 1000000.
        bustype (str, optional): Bus type. Auto-detected if None.
        negative_test (bool, optional): Expect failure. Defaults to False.

    Returns:
        TestAction: Configured NMT start action.
    """

    def execute():
        with CANBus(channel, bustype, bitrate) as bus:
            nmt_command(bus, node_id, NMT_START_REMOTE_NODE)
        return True

    metadata = {
        'display_command': f"NMT Start → node {node_id}",
        'display_expected': "Command sent",
        'sent': f"NMT Start node {node_id} on {channel}",
    }

    return TestAction(name=name, execute_func=execute,
                      negative_test=negative_test, metadata=metadata)


def nmt_stop(name: str, channel: str, node_id: int,
             bitrate: int = CAN_BITRATE_1000K,
             bustype: Optional[str] = None,
             negative_test: bool = False) -> TestAction:
    """Create a TestAction that sends NMT Stop to a CANopen node."""

    def execute():
        with CANBus(channel, bustype, bitrate) as bus:
            nmt_command(bus, node_id, NMT_STOP_REMOTE_NODE)
        return True

    metadata = {
        'display_command': f"NMT Stop → node {node_id}",
        'display_expected': "Command sent",
    }

    return TestAction(name=name, execute_func=execute,
                      negative_test=negative_test, metadata=metadata)


def nmt_reset(name: str, channel: str, node_id: int,
              bitrate: int = CAN_BITRATE_1000K,
              bustype: Optional[str] = None,
              negative_test: bool = False) -> TestAction:
    """Create a TestAction that sends NMT Reset to a CANopen node."""

    def execute():
        with CANBus(channel, bustype, bitrate) as bus:
            nmt_command(bus, node_id, NMT_RESET_NODE)
        return True

    metadata = {
        'display_command': f"NMT Reset → node {node_id}",
        'display_expected': "Command sent",
    }

    return TestAction(name=name, execute_func=execute,
                      negative_test=negative_test, metadata=metadata)


def nmt_preoperational(name: str, channel: str, node_id: int,
                       bitrate: int = CAN_BITRATE_1000K,
                       bustype: Optional[str] = None,
                       negative_test: bool = False) -> TestAction:
    """Create a TestAction that sends NMT Pre-Operational to a CANopen node."""

    def execute():
        with CANBus(channel, bustype, bitrate) as bus:
            nmt_command(bus, node_id, NMT_ENTER_PREOPERATIONAL)
        return True

    metadata = {
        'display_command': f"NMT Pre-Op → node {node_id}",
        'display_expected': "Command sent",
    }

    return TestAction(name=name, execute_func=execute,
                      negative_test=negative_test, metadata=metadata)


def sdo_read(name: str, channel: str, node_id: int,
             index: int, subindex: int = 0,
             dtype: str = "u8",
             bitrate: int = CAN_BITRATE_1000K,
             bustype: Optional[str] = None,
             timeout: float = DEFAULT_RECV_TIMEOUT,
             negative_test: bool = False) -> TestAction:
    """Create a TestAction that reads an SDO value from a CANopen node.

    Args:
        name (str): Human-readable action name.
        channel (str): CAN interface.
        node_id (int): Target node ID (1-127).
        index (int): OD index (16-bit).
        subindex (int, optional): OD sub-index. Defaults to 0.
        dtype (str, optional): Data type for decoding -- "u8", "u16",
            "u32", "float", or "raw". Defaults to "u8".
        bitrate (int, optional): Bitrate. Defaults to 1000000.
        bustype (str, optional): Bus type. Auto-detected if None.
        timeout (float, optional): SDO timeout. Defaults to 5.0.
        negative_test (bool, optional): Expect failure. Defaults to False.

    Returns:
        TestAction: Configured SDO read action.
    """
    typed_readers = {
        "u8": sdo_read_u8,
        "u16": sdo_read_u16,
        "u32": sdo_read_u32,
        "float": sdo_read_float,
    }

    def execute():
        with CANBus(channel, bustype, bitrate) as bus:
            if dtype == "raw":
                value = sdo_read_raw(bus, node_id, index, subindex, timeout)
            elif dtype in typed_readers:
                value = typed_readers[dtype](bus, node_id, index, subindex, timeout)
            else:
                raise PU2CANFDCANopenError(f"Unknown dtype '{dtype}'")
            return value

    metadata = {
        'display_command': f"SDO Read 0x{index:04X}:{subindex:02X} node {node_id}",
        'display_expected': f"Value ({dtype})",
    }

    return TestAction(name=name, execute_func=execute,
                      negative_test=negative_test, metadata=metadata)


def sdo_write(name: str, channel: str, node_id: int,
              index: int, subindex: int, value: Any,
              dtype: str = "u8",
              bitrate: int = CAN_BITRATE_1000K,
              bustype: Optional[str] = None,
              timeout: float = DEFAULT_RECV_TIMEOUT,
              negative_test: bool = False) -> TestAction:
    """Create a TestAction that writes an SDO value to a CANopen node.

    Args:
        name (str): Human-readable action name.
        channel (str): CAN interface.
        node_id (int): Target node ID (1-127).
        index (int): OD index (16-bit).
        subindex (int): OD sub-index.
        value: Value to write (type depends on dtype).
        dtype (str, optional): Data type -- "u8", "u16", "u32", "float".
            Defaults to "u8".
        bitrate (int, optional): Bitrate. Defaults to 1000000.
        bustype (str, optional): Bus type. Auto-detected if None.
        timeout (float, optional): SDO timeout. Defaults to 5.0.
        negative_test (bool, optional): Expect failure. Defaults to False.

    Returns:
        TestAction: Configured SDO write action.
    """
    typed_writers = {
        "u8": sdo_write_u8,
        "u16": sdo_write_u16,
        "u32": sdo_write_u32,
        "float": sdo_write_float,
    }

    def execute():
        with CANBus(channel, bustype, bitrate) as bus:
            if dtype in typed_writers:
                typed_writers[dtype](bus, node_id, index, subindex, value, timeout)
            else:
                raise PU2CANFDCANopenError(f"Unknown dtype '{dtype}'")
            return True

    metadata = {
        'display_command': f"SDO Write 0x{index:04X}:{subindex:02X} = {value}",
        'display_expected': "Write confirmed",
    }

    return TestAction(name=name, execute_func=execute,
                      negative_test=negative_test, metadata=metadata)


def heartbeat(name: str, channel: str, node_id: int,
              expected_state: Optional[int] = None,
              bitrate: int = CAN_BITRATE_1000K,
              bustype: Optional[str] = None,
              timeout: float = DEFAULT_RECV_TIMEOUT,
              negative_test: bool = False) -> TestAction:
    """Create a TestAction that waits for a CANopen heartbeat.

    Args:
        name (str): Human-readable action name.
        channel (str): CAN interface.
        node_id (int): Target node ID (1-127).
        expected_state (int, optional): Expected heartbeat state.
            Use HEARTBEAT_* constants.
        bitrate (int, optional): Bitrate. Defaults to 1000000.
        bustype (str, optional): Bus type. Auto-detected if None.
        timeout (float, optional): Timeout. Defaults to 5.0.
        negative_test (bool, optional): Expect failure. Defaults to False.

    Returns:
        TestAction: Configured heartbeat monitor action.
    """

    def execute():
        with CANBus(channel, bustype, bitrate) as bus:
            result = wait_for_heartbeat(bus, node_id, expected_state, timeout)
            return result

    state_str = (HEARTBEAT_STATE_NAMES.get(expected_state, "Any")
                 if expected_state is not None else "Any")

    metadata = {
        'display_command': f"Heartbeat node {node_id}",
        'display_expected': f"State: {state_str}",
    }

    return TestAction(name=name, execute_func=execute,
                      negative_test=negative_test, metadata=metadata)


def sync_trigger(name: str, channel: str,
                 bitrate: int = CAN_BITRATE_1000K,
                 bustype: Optional[str] = None,
                 negative_test: bool = False) -> TestAction:
    """Create a TestAction that sends a CANopen SYNC broadcast.

    Args:
        name (str): Human-readable action name.
        channel (str): CAN interface.
        bitrate (int, optional): Bitrate. Defaults to 1000000.
        bustype (str, optional): Bus type. Auto-detected if None.
        negative_test (bool, optional): Expect failure. Defaults to False.

    Returns:
        TestAction: Configured SYNC action.
    """

    def execute():
        with CANBus(channel, bustype, bitrate) as bus:
            sync(bus)
        return True

    metadata = {
        'display_command': "CANopen SYNC",
        'display_expected': "Broadcast sent",
    }

    return TestAction(name=name, execute_func=execute,
                      negative_test=negative_test, metadata=metadata)


# ======================== eWald Convenience TestActions ========================

def ewald_set_mode(name: str, channel: str, node_id: int, mode: int,
                   bitrate: int = EWALD_DEFAULT_BITRATE,
                   bustype: Optional[str] = None,
                   timeout: float = DEFAULT_RECV_TIMEOUT,
                   negative_test: bool = False) -> TestAction:
    """Create a TestAction that sets the eWald micro mode.

    Writes to OD index 0x2000 and then sends NMT Start to apply.

    Args:
        name (str): Human-readable action name.
        channel (str): CAN interface.
        node_id (int): eWald node ID.
        mode (int): Micro mode value (see eWald firmware docs).
        bitrate (int, optional): Bitrate. Defaults to 1000000.
        bustype (str, optional): Bus type. Auto-detected if None.
        timeout (float, optional): SDO timeout. Defaults to 5.0.
        negative_test (bool, optional): Expect failure. Defaults to False.

    Returns:
        TestAction: Configured mode-change action.
    """

    def execute():
        logger = get_active_logger()

        if logger:
            logger.info("")
            logger.info("=" * 80)
            logger.info(f"[eWald] SET MODE = {mode}")
            logger.info("=" * 80)
            logger.info("")

        with CANBus(channel, bustype, bitrate) as bus:
            sdo_write_u8(bus, node_id, EWALD_OD_MICRO_MODE, 0, mode, timeout)
            nmt_command(bus, node_id, NMT_START_REMOTE_NODE)
        return True

    metadata = {
        'display_command': f"eWald mode = {mode}",
        'display_expected': "Mode set + NMT Start",
    }

    return TestAction(name=name, execute_func=execute,
                      negative_test=negative_test, metadata=metadata)


def ewald_read_status(name: str, channel: str, node_id: int,
                      bitrate: int = EWALD_DEFAULT_BITRATE,
                      bustype: Optional[str] = None,
                      timeout: float = DEFAULT_RECV_TIMEOUT,
                      negative_test: bool = False) -> TestAction:
    """Create a TestAction that reads the eWald status object (0x3000).

    Reads all 8 sub-indices of the status object and returns a dict.

    Args:
        name (str): Human-readable action name.
        channel (str): CAN interface.
        node_id (int): eWald node ID.
        bitrate (int, optional): Bitrate. Defaults to 1000000.
        bustype (str, optional): Bus type. Auto-detected if None.
        timeout (float, optional): SDO timeout. Defaults to 5.0.
        negative_test (bool, optional): Expect failure. Defaults to False.

    Returns:
        TestAction: Action returning dict with status fields.
    """

    def execute():
        logger = get_active_logger()

        if logger:
            logger.info("")
            logger.info("=" * 80)
            logger.info("[eWald] READ STATUS")
            logger.info("=" * 80)
            logger.info("")

        with CANBus(channel, bustype, bitrate) as bus:
            status = {
                "state": sdo_read_u8(bus, node_id, EWALD_OD_STATUS, EWALD_SUB_STATE, timeout),
                "digital_io": sdo_read_u8(bus, node_id, EWALD_OD_STATUS, EWALD_SUB_DIO, timeout),
                "flags": sdo_read_u8(bus, node_id, EWALD_OD_STATUS, EWALD_SUB_FLAGS, timeout),
                "duty_cycle": sdo_read_u16(bus, node_id, EWALD_OD_STATUS, EWALD_SUB_DUTY, timeout),
                "frequency": sdo_read_u16(bus, node_id, EWALD_OD_STATUS, EWALD_SUB_FREQUENCY, timeout),
                "voltage": sdo_read_u16(bus, node_id, EWALD_OD_STATUS, EWALD_SUB_VOLTAGE, timeout),
                "current": sdo_read_u16(bus, node_id, EWALD_OD_STATUS, EWALD_SUB_CURRENT, timeout),
                "pulses_done": sdo_read_u8(bus, node_id, EWALD_OD_STATUS, EWALD_SUB_PULSES_DONE, timeout),
            }

        if logger:
            logger.info(f"  State:      {status['state']}")
            logger.info(f"  Digital IO: 0x{status['digital_io']:02X}")
            logger.info(f"  Flags:      0x{status['flags']:02X}")
            logger.info(f"  Duty Cycle: {status['duty_cycle']}")
            logger.info(f"  Frequency:  {status['frequency']} Hz")
            logger.info(f"  Voltage:    {status['voltage']}")
            logger.info(f"  Current:    {status['current']}")
            logger.info(f"  Pulses OK:  {status['pulses_done']}")
            logger.info("=" * 80)
            logger.info("")

        return status

    metadata = {
        'display_command': f"eWald status node {node_id}",
        'display_expected': "Status read",
    }

    return TestAction(name=name, execute_func=execute,
                      negative_test=negative_test, metadata=metadata)


def ewald_read_version(name: str, channel: str, node_id: int,
                       bitrate: int = EWALD_DEFAULT_BITRATE,
                       bustype: Optional[str] = None,
                       timeout: float = DEFAULT_RECV_TIMEOUT,
                       negative_test: bool = False) -> TestAction:
    """Create a TestAction that reads the eWald firmware version (0x5060).

    Returns:
        TestAction: Action returning dict with major, minor, patch.
    """

    def execute():
        logger = get_active_logger()

        with CANBus(channel, bustype, bitrate) as bus:
            major = sdo_read_u8(bus, node_id, EWALD_OD_VERSION, 1, timeout)
            minor = sdo_read_u8(bus, node_id, EWALD_OD_VERSION, 2, timeout)
            patch = sdo_read_u8(bus, node_id, EWALD_OD_VERSION, 3, timeout)

        version = {"major": major, "minor": minor, "patch": patch}

        if logger:
            logger.info(f"[eWald] Firmware version: {major}.{minor}.{patch}")

        return version

    metadata = {
        'display_command': f"eWald FW version node {node_id}",
        'display_expected': "Version read",
    }

    return TestAction(name=name, execute_func=execute,
                      negative_test=negative_test, metadata=metadata)


def ewald_read_serial(name: str, channel: str, node_id: int,
                      bitrate: int = EWALD_DEFAULT_BITRATE,
                      bustype: Optional[str] = None,
                      timeout: float = DEFAULT_RECV_TIMEOUT,
                      negative_test: bool = False) -> TestAction:
    """Create a TestAction that reads the eWald serial number (0x4070).

    The serial number consists of 4 x 32-bit words from the SAMD21
    unique device ID register.

    Returns:
        TestAction: Action returning serial number as hex string.
    """

    def execute():
        logger = get_active_logger()

        with CANBus(channel, bustype, bitrate) as bus:
            words = []
            for sub in range(1, 5):
                words.append(sdo_read_u32(bus, node_id, EWALD_OD_SERIAL_NUMBER, sub, timeout))

        serial_hex = '-'.join(f'{w:08X}' for w in words)

        if logger:
            logger.info(f"[eWald] Serial: {serial_hex}")

        return serial_hex

    metadata = {
        'display_command': f"eWald serial node {node_id}",
        'display_expected': "Serial number",
    }

    return TestAction(name=name, execute_func=execute,
                      negative_test=negative_test, metadata=metadata)


def ewald_read_temperature(name: str, channel: str, node_id: int,
                           bitrate: int = EWALD_DEFAULT_BITRATE,
                           bustype: Optional[str] = None,
                           timeout: float = DEFAULT_RECV_TIMEOUT,
                           negative_test: bool = False) -> TestAction:
    """Create a TestAction that reads the eWald temperature (0x4010).

    Returns:
        TestAction: Action returning raw ADC temperature value.
    """

    def execute():
        with CANBus(channel, bustype, bitrate) as bus:
            # SDO read triggers the temperature measurement
            temp = sdo_read_u16(bus, node_id, EWALD_OD_TEMPERATURE, 0, timeout)

        logger = get_active_logger()
        if logger:
            logger.info(f"[eWald] Temperature ADC raw: {temp}")

        return temp

    metadata = {
        'display_command': f"eWald temperature node {node_id}",
        'display_expected': "Temperature value",
    }

    return TestAction(name=name, execute_func=execute,
                      negative_test=negative_test, metadata=metadata)
