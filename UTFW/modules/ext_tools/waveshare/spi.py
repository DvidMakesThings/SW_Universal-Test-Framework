# spi.py
"""
UTFW Waveshare SPI Module
==========================
High-level SPI master test functions and TestAction factories for the
Waveshare USB TO UART/I2C/SPI/JTAG adapter (WCH CH347 chipset).

This module provides SPI bus communication capabilities through the CH347
adapter. It uses pyserial for USB communication and implements the CH347
SPI protocol for full-duplex transfers, register read/write operations,
and device identification.

The CH347 in Mode 1/2 exposes an SPI master interface supporting:
- SPI modes 0–3 (CPOL/CPHA combinations)
- Configurable clock speed
- CS0 / CS1 chip-select lines
- Full-duplex and half-duplex transfers
- Arbitrary read/write transactions

All SPI operations are logged using the UTFW logging system with detailed
bus transaction summaries.

Usage:
    import UTFW
    waveshare = UTFW.modules.ext_tools.waveshare

    action = waveshare.spi.transfer(
        "SPI loopback", "COM3", tx_data=b'\\xAA\\x55'
    )
    action = waveshare.spi.read_register(
        "Read JEDEC ID", "COM3", 0x9F, length=3
    )

Author: DvidMakesThings
"""

import time
from typing import Optional, Dict, List, Any, Tuple

from ....core.logger import get_active_logger
from ....core.core import TestAction
from ._base import WaveshareError, _format_hex_dump, _ensure_pyserial

DEBUG = False  # Set to True to enable debug prints

# SPI mode constants (CPOL, CPHA)
SPI_MODE_0 = 0  # CPOL=0, CPHA=0  (idle low, sample leading edge)
SPI_MODE_1 = 1  # CPOL=0, CPHA=1  (idle low, sample trailing edge)
SPI_MODE_2 = 2  # CPOL=1, CPHA=0  (idle high, sample leading edge)
SPI_MODE_3 = 3  # CPOL=1, CPHA=1  (idle high, sample trailing edge)

# Default SPI speed (Hz)
SPI_DEFAULT_SPEED = 1_000_000  # 1 MHz

# Chip select lines
CS0 = 0
CS1 = 1


class WaveshareSPIError(WaveshareError):
    """Exception raised when Waveshare SPI operations fail.

    This exception is raised by SPI test functions when bus communication
    errors occur, chip-select failures happen, or validation of SPI data
    cannot be completed.

    Args:
        message (str): Description of the error that occurred.
    """
    pass


# ======================== Internal Helpers ========================

def _open_spi_port(port: str, timeout: float = 2.0):
    """Open the CH347 serial port for SPI communication.

    The CH347 exposes SPI through a USB serial interface. This helper
    opens the port with the appropriate settings for the SPI protocol
    bridge.

    Args:
        port (str): Serial port identifier.
        timeout (float, optional): Read timeout in seconds. Defaults to 2.0.

    Returns:
        serial.Serial: Configured serial port object.

    Raises:
        WaveshareSPIError: If the port cannot be opened.
    """
    _ensure_pyserial()
    import serial as pyserial

    logger = get_active_logger()

    if logger:
        logger.info("[WAVESHARE SPI] Opening SPI port...")
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
            logger.info(f"✓ SPI port {port} opened")

        return ser

    except Exception as e:
        error_msg = f"Failed to open SPI port {port}: {type(e).__name__}: {e}"
        if logger:
            logger.error(f"[WAVESHARE SPI ERROR] {error_msg}")
        raise WaveshareSPIError(error_msg)


# ======================== Core SPI Functions ========================

def _transfer(port: str, tx_data: bytes, cs: int = CS0,
              mode: int = SPI_MODE_0, timeout: float = 2.0) -> bytes:
    """Perform a full-duplex SPI transfer.

    Simultaneously clocks out tx_data on MOSI while capturing the same
    number of bytes from MISO. This is the fundamental SPI operation.

    Args:
        port (str): Serial port identifier for the Waveshare adapter.
        tx_data (bytes): Data bytes to transmit on MOSI.
        cs (int, optional): Chip-select line (0 or 1). Defaults to CS0.
        mode (int, optional): SPI mode (0–3). Defaults to SPI_MODE_0.
        timeout (float, optional): Transaction timeout. Defaults to 2.0.

    Returns:
        bytes: Data bytes received on MISO (same length as tx_data).

    Raises:
        WaveshareSPIError: If the transfer fails.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE SPI] FULL-DUPLEX TRANSFER")
        logger.info("=" * 80)
        logger.info(f"  Port:    {port}")
        logger.info(f"  CS:      CS{cs}")
        logger.info(f"  Mode:    SPI_MODE_{mode}")
        logger.info(f"  Length:  {len(tx_data)} bytes")
        logger.info("")
        logger.info("  MOSI (TX):")
        for line in _format_hex_dump(tx_data).split('\n'):
            logger.info(f"    {line}")
        logger.info("")

    if mode not in (SPI_MODE_0, SPI_MODE_1, SPI_MODE_2, SPI_MODE_3):
        raise WaveshareSPIError(f"Invalid SPI mode: {mode} (must be 0–3)")

    if cs not in (CS0, CS1):
        raise WaveshareSPIError(f"Invalid chip-select: {cs} (must be 0 or 1)")

    try:
        ser = _open_spi_port(port, timeout)
    except WaveshareSPIError:
        raise

    try:
        # Build SPI transfer frame
        # CH347 SPI frame: [CS_ASSERT] + [MODE_BYTE] + [DATA...] + [CS_DEASSERT]
        mode_byte = (mode & 0x03) | ((cs & 0x01) << 2)
        frame = bytes([mode_byte]) + tx_data

        ser.write(frame)
        ser.flush()

        # Collect MISO response (same length as TX)
        rx_data = bytearray()
        start_time = time.time()
        target_len = len(tx_data)

        while len(rx_data) < target_len and (time.time() - start_time) < timeout:
            if ser.in_waiting > 0:
                chunk = ser.read(min(ser.in_waiting, target_len - len(rx_data)))
                rx_data.extend(chunk)
            else:
                time.sleep(0.005)

        result = bytes(rx_data[:target_len])

        if logger:
            logger.info("  MISO (RX):")
            for line in _format_hex_dump(result).split('\n'):
                logger.info(f"    {line}")
            logger.info("")
            logger.info(f"✓ Transfer complete ({len(result)} bytes)")
            logger.info("=" * 80)
            logger.info("")

        return result

    except WaveshareSPIError:
        raise
    except Exception as e:
        if logger:
            logger.error(f"[WAVESHARE SPI ERROR] Transfer failed: {type(e).__name__}: {e}")
        raise WaveshareSPIError(f"SPI transfer failed: {type(e).__name__}: {e}")

    finally:
        try:
            ser.close()
        except Exception:
            pass


def _write(port: str, data: bytes, cs: int = CS0,
           mode: int = SPI_MODE_0, timeout: float = 2.0) -> bool:
    """Write data bytes on the SPI bus (TX only, discard MISO).

    Performs a half-duplex write by clocking out data on MOSI. The MISO
    response is discarded.

    Args:
        port (str): Serial port identifier for the Waveshare adapter.
        data (bytes): Data bytes to transmit.
        cs (int, optional): Chip-select line. Defaults to CS0.
        mode (int, optional): SPI mode (0–3). Defaults to SPI_MODE_0.
        timeout (float, optional): Transaction timeout. Defaults to 2.0.

    Returns:
        bool: True if the write completed.

    Raises:
        WaveshareSPIError: If the write fails.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE SPI] WRITE")
        logger.info("=" * 80)
        logger.info(f"  Port:    {port}")
        logger.info(f"  CS:      CS{cs}")
        logger.info(f"  Mode:    SPI_MODE_{mode}")
        logger.info(f"  Length:  {len(data)} bytes")
        logger.info("")
        logger.info("  TX Data:")
        for line in _format_hex_dump(data).split('\n'):
            logger.info(f"    {line}")
        logger.info("")

    # Use transfer under the hood, discard MISO
    _transfer(port, data, cs, mode, timeout)

    if logger:
        logger.info(f"✓ Write complete ({len(data)} bytes on CS{cs})")

    return True


def _read(port: str, length: int, cs: int = CS0,
          mode: int = SPI_MODE_0, timeout: float = 2.0) -> bytes:
    """Read data bytes from the SPI bus (TX dummy 0xFF, capture MISO).

    Clocks out 0xFF bytes on MOSI while capturing the response from MISO.
    This is the standard SPI read pattern.

    Args:
        port (str): Serial port identifier for the Waveshare adapter.
        length (int): Number of bytes to read.
        cs (int, optional): Chip-select line. Defaults to CS0.
        mode (int, optional): SPI mode (0–3). Defaults to SPI_MODE_0.
        timeout (float, optional): Transaction timeout. Defaults to 2.0.

    Returns:
        bytes: Data bytes received on MISO.

    Raises:
        WaveshareSPIError: If the read fails.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE SPI] READ")
        logger.info("=" * 80)
        logger.info(f"  Port:    {port}")
        logger.info(f"  CS:      CS{cs}")
        logger.info(f"  Mode:    SPI_MODE_{mode}")
        logger.info(f"  Length:  {length} bytes")
        logger.info("")

    # Clock out 0xFF dummy bytes to read MISO
    dummy_tx = bytes([0xFF] * length)
    result = _transfer(port, dummy_tx, cs, mode, timeout)

    if logger:
        logger.info("  RX Data:")
        for line in _format_hex_dump(result).split('\n'):
            logger.info(f"    {line}")
        logger.info("")

    return result


def _write_register(port: str, register: int, data: bytes, cs: int = CS0,
                    mode: int = SPI_MODE_0, timeout: float = 2.0) -> bool:
    """Write data to a specific register via SPI.

    Many SPI devices use an address byte followed by data. The MSB of the
    register address is commonly cleared for a write operation (device-
    dependent). This function sends [REGISTER | 0x00] + [DATA] as a
    single SPI transaction.

    Args:
        port (str): Serial port identifier for the Waveshare adapter.
        register (int): Register address byte (0x00–0x7F).
        data (bytes): Data bytes to write.
        cs (int, optional): Chip-select line. Defaults to CS0.
        mode (int, optional): SPI mode (0–3). Defaults to SPI_MODE_0.
        timeout (float, optional): Transaction timeout. Defaults to 2.0.

    Returns:
        bool: True if the write completed.

    Raises:
        WaveshareSPIError: If the write fails.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE SPI] WRITE REGISTER")
        logger.info("=" * 80)
        logger.info(f"  Port:     {port}")
        logger.info(f"  CS:       CS{cs}")
        logger.info(f"  Register: 0x{register:02X}")
        logger.info(f"  Length:   {len(data)} bytes")
        logger.info("")

    # Write command: register address (MSB=0) + data
    write_addr = register & 0x7F
    payload = bytes([write_addr]) + data
    _transfer(port, payload, cs, mode, timeout)

    if logger:
        logger.info(f"✓ Register write complete (0x{register:02X}, {len(data)} bytes)")

    return True


def _read_register(port: str, register: int, length: int, cs: int = CS0,
                   mode: int = SPI_MODE_0, timeout: float = 2.0) -> bytes:
    """Read data from a specific register via SPI.

    Sends the register address with MSB set (read flag) followed by dummy
    bytes to clock out the response data.

    Args:
        port (str): Serial port identifier for the Waveshare adapter.
        register (int): Register address byte (0x00–0x7F).
        length (int): Number of data bytes to read.
        cs (int, optional): Chip-select line. Defaults to CS0.
        mode (int, optional): SPI mode (0–3). Defaults to SPI_MODE_0.
        timeout (float, optional): Transaction timeout. Defaults to 2.0.

    Returns:
        bytes: Data bytes read from the register.

    Raises:
        WaveshareSPIError: If the read fails.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE SPI] READ REGISTER")
        logger.info("=" * 80)
        logger.info(f"  Port:     {port}")
        logger.info(f"  CS:       CS{cs}")
        logger.info(f"  Register: 0x{register:02X}")
        logger.info(f"  Length:   {length} bytes")
        logger.info("")

    # Read command: register address with MSB set (read flag) + dummy bytes
    read_addr = register | 0x80
    tx_data = bytes([read_addr]) + bytes([0xFF] * length)
    rx_data = _transfer(port, tx_data, cs, mode, timeout)

    # Skip the first byte (response to address byte)
    result = rx_data[1:1 + length]

    if logger:
        logger.info("  RX Data:")
        for line in _format_hex_dump(result).split('\n'):
            logger.info(f"    {line}")
        logger.info("")
        logger.info(f"✓ Register read complete (0x{register:02X}, {len(result)} bytes)")

    return result


# ======================== TestAction Factories ========================

def transfer(
        name: str,
        port: str,
        tx_data: bytes,
        expected_rx: Optional[bytes] = None,
        cs: int = CS0,
        mode: int = SPI_MODE_0,
        timeout: float = 2.0,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that performs a full-duplex SPI transfer.

    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier.
        tx_data (bytes): Data bytes to transmit on MOSI.
        expected_rx (Optional[bytes], optional): Expected MISO data for
            validation. If None, no validation is performed.
        cs (int, optional): Chip-select line. Defaults to CS0.
        mode (int, optional): SPI mode. Defaults to SPI_MODE_0.
        timeout (float, optional): Transaction timeout. Defaults to 2.0.
        negative_test (bool, optional): Mark as negative test. Defaults to False.

    Returns:
        TestAction: TestAction that returns the MISO response bytes.

    Example:
        >>> action = waveshare.spi.transfer(
        ...     "SPI loopback test", "COM3", b'\\xAA\\x55',
        ...     expected_rx=b'\\xAA\\x55'
        ... )
    """

    def execute():
        logger = get_active_logger()
        result = _transfer(port, tx_data, cs, mode, timeout)

        if expected_rx is not None and result != expected_rx:
            if logger:
                logger.error("")
                logger.error("=" * 80)
                logger.error("[WAVESHARE SPI] TRANSFER VALIDATION FAILED")
                logger.error("=" * 80)
                logger.error(f"  Expected: {expected_rx.hex(' ').upper()}")
                logger.error(f"  Actual:   {result.hex(' ').upper()}")
                logger.error("-" * 80)
            raise WaveshareSPIError(
                f"SPI transfer mismatch: expected {expected_rx.hex(' ').upper()}, "
                f"got {result.hex(' ').upper()}"
            )

        return result

    metadata = {
        'display_command': f"SPI xfer CS{cs} M{mode} [{len(tx_data)}B]",
        'display_expected': expected_rx.hex(' ').upper() if expected_rx else '',
    }

    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def write(
        name: str,
        port: str,
        data: bytes,
        cs: int = CS0,
        mode: int = SPI_MODE_0,
        timeout: float = 2.0,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that writes data on the SPI bus.

    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier.
        data (bytes): Data bytes to write.
        cs (int, optional): Chip-select line. Defaults to CS0.
        mode (int, optional): SPI mode. Defaults to SPI_MODE_0.
        timeout (float, optional): Transaction timeout. Defaults to 2.0.
        negative_test (bool, optional): Mark as negative test. Defaults to False.

    Returns:
        TestAction: TestAction that returns True on success.

    Example:
        >>> action = waveshare.spi.write(
        ...     "Send SPI command", "COM3", b'\\x06'
        ... )
    """

    def execute():
        return _write(port, data, cs, mode, timeout)

    metadata = {
        'display_command': f"SPI write CS{cs} M{mode} [{len(data)}B]",
        'display_expected': 'OK',
    }

    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def read(
        name: str,
        port: str,
        length: int,
        expected: Optional[bytes] = None,
        cs: int = CS0,
        mode: int = SPI_MODE_0,
        timeout: float = 2.0,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that reads data from the SPI bus.

    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier.
        length (int): Number of bytes to read.
        expected (Optional[bytes], optional): Expected data for validation.
        cs (int, optional): Chip-select line. Defaults to CS0.
        mode (int, optional): SPI mode. Defaults to SPI_MODE_0.
        timeout (float, optional): Transaction timeout. Defaults to 2.0.
        negative_test (bool, optional): Mark as negative test. Defaults to False.

    Returns:
        TestAction: TestAction that returns the read bytes.

    Example:
        >>> action = waveshare.spi.read(
        ...     "Read SPI status", "COM3", 1, expected=b'\\x00'
        ... )
    """

    def execute():
        logger = get_active_logger()
        result = _read(port, length, cs, mode, timeout)

        if expected is not None and result != expected:
            if logger:
                logger.error("")
                logger.error("=" * 80)
                logger.error("[WAVESHARE SPI] READ VALIDATION FAILED")
                logger.error("=" * 80)
                logger.error(f"  Expected: {expected.hex(' ').upper()}")
                logger.error(f"  Actual:   {result.hex(' ').upper()}")
                logger.error("-" * 80)
            raise WaveshareSPIError(
                f"SPI read mismatch: expected {expected.hex(' ').upper()}, "
                f"got {result.hex(' ').upper()}"
            )

        return result

    metadata = {
        'display_command': f"SPI read CS{cs} M{mode} [{length}B]",
        'display_expected': expected.hex(' ').upper() if expected else '',
    }

    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def write_register(
        name: str,
        port: str,
        register: int,
        data: bytes,
        cs: int = CS0,
        mode: int = SPI_MODE_0,
        timeout: float = 2.0,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that writes data to a specific SPI register.

    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier.
        register (int): Register address byte.
        data (bytes): Data bytes to write to the register.
        cs (int, optional): Chip-select line. Defaults to CS0.
        mode (int, optional): SPI mode. Defaults to SPI_MODE_0.
        timeout (float, optional): Transaction timeout. Defaults to 2.0.
        negative_test (bool, optional): Mark as negative test. Defaults to False.

    Returns:
        TestAction: TestAction that returns True on success.

    Example:
        >>> action = waveshare.spi.write_register(
        ...     "Write config", "COM3", 0x20, b'\\x77'
        ... )
    """

    def execute():
        return _write_register(port, register, data, cs, mode, timeout)

    metadata = {
        'display_command': f"SPI wreg 0x{register:02X} CS{cs} [{len(data)}B]",
        'display_expected': 'OK',
    }

    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def read_register(
        name: str,
        port: str,
        register: int,
        length: int,
        expected: Optional[bytes] = None,
        cs: int = CS0,
        mode: int = SPI_MODE_0,
        timeout: float = 2.0,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that reads data from a specific SPI register.

    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier.
        register (int): Register address byte.
        length (int): Number of data bytes to read.
        expected (Optional[bytes], optional): Expected data for validation.
        cs (int, optional): Chip-select line. Defaults to CS0.
        mode (int, optional): SPI mode. Defaults to SPI_MODE_0.
        timeout (float, optional): Transaction timeout. Defaults to 2.0.
        negative_test (bool, optional): Mark as negative test. Defaults to False.

    Returns:
        TestAction: TestAction that returns the read bytes.

    Example:
        >>> action = waveshare.spi.read_register(
        ...     "Read WHO_AM_I", "COM3", 0x0F, 1, expected=b'\\x6B'
        ... )
    """

    def execute():
        logger = get_active_logger()
        result = _read_register(port, register, length, cs, mode, timeout)

        if expected is not None and result != expected:
            if logger:
                logger.error("")
                logger.error("=" * 80)
                logger.error("[WAVESHARE SPI] REGISTER READ VALIDATION FAILED")
                logger.error("=" * 80)
                logger.error(f"  Register: 0x{register:02X}")
                logger.error(f"  Expected: {expected.hex(' ').upper()}")
                logger.error(f"  Actual:   {result.hex(' ').upper()}")
                logger.error("-" * 80)
            raise WaveshareSPIError(
                f"SPI register 0x{register:02X} read mismatch: "
                f"expected {expected.hex(' ').upper()}, got {result.hex(' ').upper()}"
            )

        return result

    metadata = {
        'display_command': f"SPI rreg 0x{register:02X} CS{cs} [{length}B]",
        'display_expected': expected.hex(' ').upper() if expected else '',
    }

    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def verify_jedec(
        name: str,
        port: str,
        expected_manufacturer: Optional[int] = None,
        expected_device_id: Optional[bytes] = None,
        cs: int = CS0,
        mode: int = SPI_MODE_0,
        timeout: float = 2.0,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that reads and verifies a JEDEC Flash ID.

    Sends the standard JEDEC Read ID command (0x9F) and reads back the
    3-byte response: [Manufacturer ID] [Memory Type] [Capacity].

    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier.
        expected_manufacturer (Optional[int], optional): Expected JEDEC
            manufacturer ID byte. If None, manufacturer is not validated.
        expected_device_id (Optional[bytes], optional): Expected full 3-byte
            JEDEC ID. If None, full ID is not validated.
        cs (int, optional): Chip-select line. Defaults to CS0.
        mode (int, optional): SPI mode. Defaults to SPI_MODE_0.
        timeout (float, optional): Transaction timeout. Defaults to 2.0.
        negative_test (bool, optional): Mark as negative test. Defaults to False.

    Returns:
        TestAction: TestAction that returns the 3-byte JEDEC ID.

    Example:
        >>> action = waveshare.spi.verify_jedec(
        ...     "Verify W25Q128", "COM3",
        ...     expected_manufacturer=0xEF,
        ...     expected_device_id=b'\\xEF\\x40\\x18'
        ... )
    """

    def execute():
        logger = get_active_logger()

        if logger:
            logger.info("")
            logger.info("=" * 80)
            logger.info("[WAVESHARE SPI] JEDEC ID VERIFICATION")
            logger.info("=" * 80)
            logger.info(f"  Port: {port}")
            logger.info(f"  CS:   CS{cs}")
            logger.info("")

        # Send JEDEC Read ID command (0x9F) + 3 dummy bytes
        tx = bytes([0x9F, 0xFF, 0xFF, 0xFF])
        rx = _transfer(port, tx, cs, mode, timeout)
        jedec_id = rx[1:4]  # Skip response to command byte

        manufacturer = jedec_id[0]
        memory_type = jedec_id[1]
        capacity = jedec_id[2]

        if logger:
            logger.info(f"  JEDEC ID:      {jedec_id.hex(' ').upper()}")
            logger.info(f"  Manufacturer:  0x{manufacturer:02X}")
            logger.info(f"  Memory Type:   0x{memory_type:02X}")
            logger.info(f"  Capacity:      0x{capacity:02X}")
            logger.info("")

        # Validate manufacturer if specified
        if expected_manufacturer is not None and manufacturer != expected_manufacturer:
            if logger:
                logger.error(f"  ✗ Manufacturer mismatch")
                logger.error(f"    Expected: 0x{expected_manufacturer:02X}")
                logger.error(f"    Actual:   0x{manufacturer:02X}")
                logger.error("=" * 80)
            raise WaveshareSPIError(
                f"JEDEC manufacturer mismatch: expected 0x{expected_manufacturer:02X}, "
                f"got 0x{manufacturer:02X}"
            )

        # Validate full ID if specified
        if expected_device_id is not None and jedec_id != expected_device_id:
            if logger:
                logger.error(f"  ✗ JEDEC ID mismatch")
                logger.error(f"    Expected: {expected_device_id.hex(' ').upper()}")
                logger.error(f"    Actual:   {jedec_id.hex(' ').upper()}")
                logger.error("=" * 80)
            raise WaveshareSPIError(
                f"JEDEC ID mismatch: expected {expected_device_id.hex(' ').upper()}, "
                f"got {jedec_id.hex(' ').upper()}"
            )

        if logger:
            logger.info(f"  ✓ JEDEC ID verified")
            logger.info("=" * 80)
            logger.info("")

        return jedec_id

    exp_str = ""
    if expected_device_id:
        exp_str = expected_device_id.hex(' ').upper()
    elif expected_manufacturer is not None:
        exp_str = f"Mfr: 0x{expected_manufacturer:02X}"

    metadata = {
        'display_command': f"SPI JEDEC ID (0x9F) CS{cs}",
        'display_expected': exp_str,
    }

    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)
