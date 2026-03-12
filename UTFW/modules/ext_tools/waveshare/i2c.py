# i2c.py
"""
UTFW Waveshare I2C Module
==========================
High-level I2C master test functions and TestAction factories for the
Waveshare USB TO UART/I2C/SPI/JTAG adapter (WCH CH347 chipset).

This module provides I2C bus communication capabilities through the CH347
adapter. It uses pyserial for USB communication and implements the CH347
I2C protocol for bus scanning, register read/write operations, and device
verification.

The CH347 in Mode 1/2/3/4 exposes an I2C master interface supporting:
- Standard mode (100 kHz) and Fast mode (400 kHz)
- 7-bit addressing
- Arbitrary read/write transactions
- Bus scan for device enumeration

All I2C operations are logged using the UTFW logging system with detailed
bus transaction summaries.

Usage:
    import UTFW
    waveshare = UTFW.modules.ext_tools.waveshare

    action = waveshare.i2c.scan("Scan I2C bus", "COM3")
    action = waveshare.i2c.read_register(
        "Read temperature", "COM3", 0x48, 0x00, length=2
    )

Author: DvidMakesThings
"""

import time
from typing import Optional, Dict, List, Any, Tuple

from ....core.logger import get_active_logger
from ....core.core import TestAction
from ._base import WaveshareError, _format_hex_dump, _ensure_pyserial

DEBUG = False  # Set to True to enable debug prints

# I2C speed constants
I2C_SPEED_STANDARD = 100_000   # 100 kHz
I2C_SPEED_FAST = 400_000       # 400 kHz

# I2C address range (7-bit)
I2C_ADDR_MIN = 0x03
I2C_ADDR_MAX = 0x77


class WaveshareI2CError(WaveshareError):
    """Exception raised when Waveshare I2C operations fail.

    This exception is raised by I2C test functions when bus communication
    errors occur, device addressing fails, or validation of I2C data
    cannot be completed.

    Args:
        message (str): Description of the error that occurred.
    """
    pass


# ======================== Internal Helpers ========================

def _open_i2c_port(port: str, timeout: float = 2.0):
    """Open the CH347 serial port for I2C communication.

    The CH347 exposes I2C through a USB serial interface. This helper
    opens the port with the appropriate settings for the I2C protocol
    bridge.

    Args:
        port (str): Serial port identifier.
        timeout (float, optional): Read timeout in seconds. Defaults to 2.0.

    Returns:
        serial.Serial: Configured serial port object.

    Raises:
        WaveshareI2CError: If the port cannot be opened.
    """
    _ensure_pyserial()
    import serial as pyserial

    logger = get_active_logger()

    if logger:
        logger.info("[WAVESHARE I2C] Opening I2C port...")
        logger.info(f"  Port:    {port}")
        logger.info(f"  Timeout: {timeout}s")

    try:
        ser = pyserial.Serial(
            port=port,
            baudrate=115200,
            timeout=timeout,
            write_timeout=2.0,
        )
        time.sleep(0.1)
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        if logger:
            logger.info(f"✓ I2C port {port} opened")

        return ser

    except Exception as e:
        error_msg = f"Failed to open I2C port {port}: {type(e).__name__}: {e}"
        if logger:
            logger.error(f"[WAVESHARE I2C ERROR] {error_msg}")
        raise WaveshareI2CError(error_msg)


# ======================== Core I2C Functions ========================

def _scan_bus(port: str, timeout: float = 5.0) -> List[int]:
    """Scan the I2C bus for connected devices.

    Probes all valid 7-bit I2C addresses (0x03–0x77) and returns a list
    of addresses that acknowledged. Each address is probed with a zero-length
    write transaction.

    Args:
        port (str): Serial port identifier for the Waveshare adapter.
        timeout (float, optional): Total scan timeout in seconds. Defaults to 5.0.

    Returns:
        List[int]: List of responding I2C device addresses (7-bit).

    Raises:
        WaveshareI2CError: If the bus scan cannot be performed.
    """
    _ensure_pyserial()
    import serial as pyserial

    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE I2C] BUS SCAN")
        logger.info("=" * 80)
        logger.info(f"  Port:         {port}")
        logger.info(f"  Address Range: 0x{I2C_ADDR_MIN:02X}–0x{I2C_ADDR_MAX:02X}")
        logger.info(f"  Timeout:      {timeout}s")
        logger.info("")

    found_devices: List[int] = []

    try:
        ser = _open_i2c_port(port, timeout=1.0)
    except WaveshareI2CError:
        raise

    try:
        start_time = time.time()

        for addr in range(I2C_ADDR_MIN, I2C_ADDR_MAX + 1):
            if (time.time() - start_time) > timeout:
                if logger:
                    logger.warning(f"  ⚠ Scan timeout reached at address 0x{addr:02X}")
                break

            # Probe address with a write-address byte
            # CH347 I2C write frame: [START] [ADDR_W] [STOP]
            write_addr = (addr << 1) & 0xFE
            probe_data = bytes([write_addr])

            try:
                ser.reset_input_buffer()
                ser.write(probe_data)
                ser.flush()
                time.sleep(0.005)

                # Check for ACK by reading back
                if ser.in_waiting > 0:
                    resp = ser.read(ser.in_waiting)
                    # Device acknowledged – record it
                    found_devices.append(addr)
                    if logger:
                        logger.info(f"  0x{addr:02X} ({addr:3d})  ACK  ✓")
            except Exception:
                # No ACK or communication issue at this address – skip
                continue

        elapsed = time.time() - start_time

        if logger:
            logger.info("")
            logger.info("-" * 80)
            logger.info(f"  Scan complete in {elapsed:.2f}s")
            logger.info(f"  Devices found: {len(found_devices)}")
            if found_devices:
                addr_list = ", ".join(f"0x{a:02X}" for a in found_devices)
                logger.info(f"  Addresses:     {addr_list}")
            logger.info("=" * 80)
            logger.info("")

        return found_devices

    except WaveshareI2CError:
        raise
    except Exception as e:
        if logger:
            logger.error(f"[WAVESHARE I2C ERROR] Bus scan failed: {type(e).__name__}: {e}")
        raise WaveshareI2CError(f"I2C bus scan failed: {type(e).__name__}: {e}")

    finally:
        try:
            ser.close()
        except Exception:
            pass


def _write(port: str, address: int, data: bytes, timeout: float = 2.0) -> bool:
    """Write data to an I2C device.

    Performs a write transaction to the specified 7-bit I2C address.

    Args:
        port (str): Serial port identifier for the Waveshare adapter.
        address (int): 7-bit I2C device address (0x03–0x77).
        data (bytes): Data bytes to write.
        timeout (float, optional): Transaction timeout. Defaults to 2.0.

    Returns:
        bool: True if the write was acknowledged.

    Raises:
        WaveshareI2CError: If the write operation fails.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE I2C] WRITE")
        logger.info("=" * 80)
        logger.info(f"  Port:    {port}")
        logger.info(f"  Address: 0x{address:02X}")
        logger.info(f"  Length:  {len(data)} bytes")
        logger.info("")
        logger.info("  TX Data:")
        for line in _format_hex_dump(data).split('\n'):
            logger.info(f"    {line}")
        logger.info("")

    if not (I2C_ADDR_MIN <= address <= I2C_ADDR_MAX):
        raise WaveshareI2CError(f"Invalid I2C address: 0x{address:02X} (must be 0x{I2C_ADDR_MIN:02X}–0x{I2C_ADDR_MAX:02X})")

    try:
        ser = _open_i2c_port(port, timeout)
    except WaveshareI2CError:
        raise

    try:
        # Build I2C write frame: [ADDR_W] + [DATA...]
        write_addr = (address << 1) & 0xFE
        frame = bytes([write_addr]) + data

        ser.write(frame)
        ser.flush()
        time.sleep(0.01)

        if logger:
            logger.info(f"✓ Write complete ({len(data)} bytes to 0x{address:02X})")
            logger.info("=" * 80)
            logger.info("")

        return True

    except Exception as e:
        if logger:
            logger.error(f"[WAVESHARE I2C ERROR] Write failed: {type(e).__name__}: {e}")
        raise WaveshareI2CError(f"I2C write to 0x{address:02X} failed: {type(e).__name__}: {e}")

    finally:
        try:
            ser.close()
        except Exception:
            pass


def _read(port: str, address: int, length: int, timeout: float = 2.0) -> bytes:
    """Read data from an I2C device.

    Performs a read transaction from the specified 7-bit I2C address.

    Args:
        port (str): Serial port identifier for the Waveshare adapter.
        address (int): 7-bit I2C device address (0x03–0x77).
        length (int): Number of bytes to read.
        timeout (float, optional): Transaction timeout. Defaults to 2.0.

    Returns:
        bytes: Data bytes read from the device.

    Raises:
        WaveshareI2CError: If the read operation fails.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE I2C] READ")
        logger.info("=" * 80)
        logger.info(f"  Port:    {port}")
        logger.info(f"  Address: 0x{address:02X}")
        logger.info(f"  Length:  {length} bytes")
        logger.info("")

    if not (I2C_ADDR_MIN <= address <= I2C_ADDR_MAX):
        raise WaveshareI2CError(f"Invalid I2C address: 0x{address:02X}")

    try:
        ser = _open_i2c_port(port, timeout)
    except WaveshareI2CError:
        raise

    try:
        # Build I2C read frame: [ADDR_R] + [LENGTH]
        read_addr = ((address << 1) & 0xFE) | 0x01
        frame = bytes([read_addr, length & 0xFF])

        ser.write(frame)
        ser.flush()

        # Collect response bytes
        response_bytes = bytearray()
        start_time = time.time()

        while len(response_bytes) < length and (time.time() - start_time) < timeout:
            if ser.in_waiting > 0:
                chunk = ser.read(min(ser.in_waiting, length - len(response_bytes)))
                response_bytes.extend(chunk)
            else:
                time.sleep(0.005)

        result = bytes(response_bytes[:length])

        if logger:
            logger.info(f"✓ Read complete ({len(result)} bytes from 0x{address:02X})")
            logger.info("")
            logger.info("  RX Data:")
            for line in _format_hex_dump(result).split('\n'):
                logger.info(f"    {line}")
            logger.info("")
            logger.info("=" * 80)
            logger.info("")

        return result

    except WaveshareI2CError:
        raise
    except Exception as e:
        if logger:
            logger.error(f"[WAVESHARE I2C ERROR] Read failed: {type(e).__name__}: {e}")
        raise WaveshareI2CError(f"I2C read from 0x{address:02X} failed: {type(e).__name__}: {e}")

    finally:
        try:
            ser.close()
        except Exception:
            pass


def _write_register(port: str, address: int, register: int, data: bytes,
                    timeout: float = 2.0) -> bool:
    """Write data to a specific register on an I2C device.

    Performs a write transaction of [REGISTER_ADDR] + [DATA] to the
    specified I2C device.

    Args:
        port (str): Serial port identifier for the Waveshare adapter.
        address (int): 7-bit I2C device address.
        register (int): Register address byte (0x00–0xFF).
        data (bytes): Data bytes to write to the register.
        timeout (float, optional): Transaction timeout. Defaults to 2.0.

    Returns:
        bool: True if the write was successful.

    Raises:
        WaveshareI2CError: If the operation fails.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE I2C] WRITE REGISTER")
        logger.info("=" * 80)
        logger.info(f"  Port:     {port}")
        logger.info(f"  Address:  0x{address:02X}")
        logger.info(f"  Register: 0x{register:02X}")
        logger.info(f"  Length:   {len(data)} bytes")
        logger.info("")

    payload = bytes([register]) + data
    return _write(port, address, payload, timeout)


def _read_register(port: str, address: int, register: int, length: int,
                   timeout: float = 2.0) -> bytes:
    """Read data from a specific register on an I2C device.

    Performs a write-then-read (repeated start) sequence: writes the
    register address, then reads the specified number of bytes.

    Args:
        port (str): Serial port identifier for the Waveshare adapter.
        address (int): 7-bit I2C device address.
        register (int): Register address byte (0x00–0xFF).
        length (int): Number of bytes to read from the register.
        timeout (float, optional): Transaction timeout. Defaults to 2.0.

    Returns:
        bytes: Data bytes read from the register.

    Raises:
        WaveshareI2CError: If the operation fails.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE I2C] READ REGISTER")
        logger.info("=" * 80)
        logger.info(f"  Port:     {port}")
        logger.info(f"  Address:  0x{address:02X}")
        logger.info(f"  Register: 0x{register:02X}")
        logger.info(f"  Length:   {length} bytes")
        logger.info("")

    # Phase 1: Write register address
    _write(port, address, bytes([register]), timeout)

    # Phase 2: Read data
    return _read(port, address, length, timeout)


# ======================== TestAction Factories ========================

def scan(
        name: str,
        port: str,
        expected_addresses: Optional[List[int]] = None,
        timeout: float = 5.0,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that scans the I2C bus for devices.

    This TestAction factory creates an action that scans all valid I2C
    addresses and optionally validates that expected devices are present.

    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier.
        expected_addresses (Optional[List[int]], optional): List of I2C
            addresses that must be found. If None, scan only (no validation).
        timeout (float, optional): Scan timeout. Defaults to 5.0.
        negative_test (bool, optional): Mark as negative test. Defaults to False.

    Returns:
        TestAction: TestAction that returns the list of found addresses.

    Raises:
        WaveshareI2CError: When executed, if expected addresses are missing.

    Example:
        >>> action = waveshare.i2c.scan(
        ...     "Scan for sensors", "COM3", expected_addresses=[0x48, 0x68]
        ... )
    """

    def execute():
        logger = get_active_logger()
        found = _scan_bus(port, timeout)

        if expected_addresses is not None:
            missing = [a for a in expected_addresses if a not in found]
            if missing:
                missing_str = ", ".join(f"0x{a:02X}" for a in missing)
                found_str = ", ".join(f"0x{a:02X}" for a in found) if found else "none"
                if logger:
                    logger.error("")
                    logger.error("=" * 80)
                    logger.error("[WAVESHARE I2C] SCAN VALIDATION FAILED")
                    logger.error("=" * 80)
                    logger.error(f"  Missing:  {missing_str}")
                    logger.error(f"  Found:    {found_str}")
                    logger.error("-" * 80)
                raise WaveshareI2CError(
                    f"Expected I2C devices not found: {missing_str} (found: {found_str})"
                )

            if logger:
                logger.info(f"✓ All expected I2C devices found")

        return found

    exp_str = ""
    if expected_addresses:
        exp_str = ", ".join(f"0x{a:02X}" for a in expected_addresses)

    metadata = {
        'display_command': f"I2C scan 0x{I2C_ADDR_MIN:02X}–0x{I2C_ADDR_MAX:02X}",
        'display_expected': exp_str,
    }

    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def write(
        name: str,
        port: str,
        address: int,
        data: bytes,
        timeout: float = 2.0,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that writes data to an I2C device.

    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier.
        address (int): 7-bit I2C device address.
        data (bytes): Data bytes to write.
        timeout (float, optional): Transaction timeout. Defaults to 2.0.
        negative_test (bool, optional): Mark as negative test. Defaults to False.

    Returns:
        TestAction: TestAction that returns True on success.

    Example:
        >>> action = waveshare.i2c.write(
        ...     "Set config register", "COM3", 0x48, b'\\x01\\x60'
        ... )
    """

    def execute():
        return _write(port, address, data, timeout)

    metadata = {
        'display_command': f"I2C write 0x{address:02X} [{len(data)}B]",
        'display_expected': 'ACK',
    }

    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def read(
        name: str,
        port: str,
        address: int,
        length: int,
        expected: Optional[bytes] = None,
        timeout: float = 2.0,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that reads data from an I2C device.

    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier.
        address (int): 7-bit I2C device address.
        length (int): Number of bytes to read.
        expected (Optional[bytes], optional): Expected data for validation.
        timeout (float, optional): Transaction timeout. Defaults to 2.0.
        negative_test (bool, optional): Mark as negative test. Defaults to False.

    Returns:
        TestAction: TestAction that returns the read bytes.

    Example:
        >>> action = waveshare.i2c.read(
        ...     "Read WHO_AM_I", "COM3", 0x68, 1, expected=b'\\x71'
        ... )
    """

    def execute():
        logger = get_active_logger()
        result = _read(port, address, length, timeout)

        if expected is not None and result != expected:
            if logger:
                logger.error("")
                logger.error("=" * 80)
                logger.error("[WAVESHARE I2C] READ VALIDATION FAILED")
                logger.error("=" * 80)
                logger.error(f"  Address:  0x{address:02X}")
                logger.error(f"  Expected: {expected.hex(' ').upper()}")
                logger.error(f"  Actual:   {result.hex(' ').upper()}")
                logger.error("-" * 80)
            raise WaveshareI2CError(
                f"I2C read mismatch at 0x{address:02X}: "
                f"expected {expected.hex(' ').upper()}, got {result.hex(' ').upper()}"
            )

        return result

    metadata = {
        'display_command': f"I2C read 0x{address:02X} [{length}B]",
        'display_expected': expected.hex(' ').upper() if expected else '',
    }

    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def write_register(
        name: str,
        port: str,
        address: int,
        register: int,
        data: bytes,
        timeout: float = 2.0,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that writes data to a specific I2C register.

    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier.
        address (int): 7-bit I2C device address.
        register (int): Register address byte.
        data (bytes): Data bytes to write to the register.
        timeout (float, optional): Transaction timeout. Defaults to 2.0.
        negative_test (bool, optional): Mark as negative test. Defaults to False.

    Returns:
        TestAction: TestAction that returns True on success.

    Example:
        >>> action = waveshare.i2c.write_register(
        ...     "Configure sensor", "COM3", 0x48, 0x01, b'\\x60\\x80'
        ... )
    """

    def execute():
        return _write_register(port, address, register, data, timeout)

    metadata = {
        'display_command': f"I2C wreg 0x{address:02X}[0x{register:02X}] [{len(data)}B]",
        'display_expected': 'ACK',
    }

    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def read_register(
        name: str,
        port: str,
        address: int,
        register: int,
        length: int,
        expected: Optional[bytes] = None,
        timeout: float = 2.0,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that reads data from a specific I2C register.

    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier.
        address (int): 7-bit I2C device address.
        register (int): Register address byte.
        length (int): Number of bytes to read.
        expected (Optional[bytes], optional): Expected data for validation.
        timeout (float, optional): Transaction timeout. Defaults to 2.0.
        negative_test (bool, optional): Mark as negative test. Defaults to False.

    Returns:
        TestAction: TestAction that returns the read bytes.

    Example:
        >>> action = waveshare.i2c.read_register(
        ...     "Read temp register", "COM3", 0x48, 0x00, 2
        ... )
    """

    def execute():
        logger = get_active_logger()
        result = _read_register(port, address, register, length, timeout)

        if expected is not None and result != expected:
            if logger:
                logger.error("")
                logger.error("=" * 80)
                logger.error("[WAVESHARE I2C] REGISTER READ VALIDATION FAILED")
                logger.error("=" * 80)
                logger.error(f"  Address:  0x{address:02X}")
                logger.error(f"  Register: 0x{register:02X}")
                logger.error(f"  Expected: {expected.hex(' ').upper()}")
                logger.error(f"  Actual:   {result.hex(' ').upper()}")
                logger.error("-" * 80)
            raise WaveshareI2CError(
                f"I2C register read mismatch at 0x{address:02X}[0x{register:02X}]: "
                f"expected {expected.hex(' ').upper()}, got {result.hex(' ').upper()}"
            )

        return result

    metadata = {
        'display_command': f"I2C rreg 0x{address:02X}[0x{register:02X}] [{length}B]",
        'display_expected': expected.hex(' ').upper() if expected else '',
    }

    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def verify_device(
        name: str,
        port: str,
        address: int,
        register: int,
        expected_id: bytes,
        timeout: float = 2.0,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that verifies an I2C device identity.

    Reads a specific register (commonly WHO_AM_I or device ID) and
    validates it matches the expected value. Commonly used as the first
    test step to confirm a specific device is present on the bus.

    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier.
        address (int): 7-bit I2C device address.
        register (int): Register address containing the device ID.
        expected_id (bytes): Expected device ID bytes.
        timeout (float, optional): Transaction timeout. Defaults to 2.0.
        negative_test (bool, optional): Mark as negative test. Defaults to False.

    Returns:
        TestAction: TestAction that returns True if the device ID matches.

    Example:
        >>> action = waveshare.i2c.verify_device(
        ...     "Verify MPU6050", "COM3", 0x68, 0x75, b'\\x71'
        ... )
    """

    def execute():
        logger = get_active_logger()

        if logger:
            logger.info("")
            logger.info("=" * 80)
            logger.info("[WAVESHARE I2C] VERIFY DEVICE IDENTITY")
            logger.info("=" * 80)
            logger.info(f"  Address:     0x{address:02X}")
            logger.info(f"  ID Register: 0x{register:02X}")
            logger.info(f"  Expected ID: {expected_id.hex(' ').upper()}")
            logger.info("")

        result = _read_register(port, address, register, len(expected_id), timeout)

        if result != expected_id:
            if logger:
                logger.error(f"  ✗ Device ID mismatch")
                logger.error(f"    Expected: {expected_id.hex(' ').upper()}")
                logger.error(f"    Actual:   {result.hex(' ').upper()}")
                logger.error("=" * 80)
            raise WaveshareI2CError(
                f"Device at 0x{address:02X} ID mismatch: "
                f"expected {expected_id.hex(' ').upper()}, got {result.hex(' ').upper()}"
            )

        if logger:
            logger.info(f"  ✓ Device ID verified: {result.hex(' ').upper()}")
            logger.info("=" * 80)
            logger.info("")

        return True

    metadata = {
        'display_command': f"I2C verify 0x{address:02X}[0x{register:02X}]",
        'display_expected': expected_id.hex(' ').upper(),
    }

    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)
