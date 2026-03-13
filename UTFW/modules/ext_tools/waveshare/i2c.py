# i2c.py
"""
UTFW Waveshare I2C Module
==========================
High-level I2C master test functions and TestAction factories for the
Waveshare USB TO UART/I2C/SPI/JTAG adapter (WCH CH347 chipset).

This module communicates through the CH347 vendor DLL (Windows) using
``CH347StreamI2C`` for all bus transactions.  The CH347 I2C master supports:
- Clock speeds: 20 KHz, 50 KHz, 100 KHz, 200 KHz, 400 KHz, 750 KHz, 1 MHz
- 7-bit addressing
- Arbitrary read/write/write-then-read transactions
- Clock stretching (slave hold SCL low)

The device is accessed by *index* (0-15) through CH347OpenDevice.
Use ``_dll.enumerate_devices()`` to discover the correct index for
the SPI/I2C or JTAG/I2C function interface.

All I2C operations are logged using the UTFW logging system.

Usage:
    import UTFW
    waveshare = UTFW.modules.ext_tools.waveshare

    action = waveshare.i2c.scan("Scan I2C bus", dev_index=0)
    action = waveshare.i2c.read_register(
        "Read temperature", dev_index=0, address=0x48,
        register=0x00, length=2,
    )

Author: DvidMakesThings
"""

from typing import Optional, List

from ....core.logger import get_active_logger
from ....core.core import TestAction
from ._base import WaveshareError, _format_hex_dump
from . import _dll

# I2C speed mode constants  (bits 1-0 of the mode word passed to CH347I2C_Set)
I2C_SPEED_20KHZ = 0   # Low speed
I2C_SPEED_100KHZ = 1  # Standard mode  (default)
I2C_SPEED_400KHZ = 2  # Fast mode
I2C_SPEED_750KHZ = 3  # High speed

# I2C address range (7-bit, excluding reserved)
I2C_ADDR_MIN = 0x03
I2C_ADDR_MAX = 0x77


class WaveshareI2CError(WaveshareError):
    """Exception raised when Waveshare I2C operations fail."""
    pass


# ======================== Context Manager ========================

class _I2CDevice:
    """RAII wrapper: opens CH347 device, configures I2C speed, closes on exit."""

    def __init__(self, dev_index: int, speed: int = I2C_SPEED_100KHZ):
        self.dev_index = dev_index
        self.speed = speed

    def __enter__(self):
        try:
            _dll.open_device(self.dev_index)
        except OSError as exc:
            raise WaveshareI2CError(
                f"Cannot open CH347 device {self.dev_index}: {exc}"
            ) from exc
        try:
            if not _dll.i2c_set(self.dev_index, self.speed):
                raise WaveshareI2CError("CH347I2C_Set returned FALSE")
        except OSError as exc:
            _dll.close_device(self.dev_index)
            raise WaveshareI2CError(f"I2C config failed: {exc}") from exc
        return self

    def __exit__(self, *_exc):
        _dll.close_device(self.dev_index)


# ======================== Core I2C Functions ========================

def _scan_bus(dev_index: int, speed: int = I2C_SPEED_100KHZ) -> List[int]:
    """Scan the I2C bus for connected devices.

    Probes all valid 7-bit addresses (0x03-0x77) using a single-byte
    write with the address.  Devices that ACK are recorded.

    Args:
        dev_index: CH347 device index (0-15).
        speed: I2C clock speed constant.

    Returns:
        List of responding 7-bit I2C addresses.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE I2C] BUS SCAN")
        logger.info("=" * 80)
        logger.info(f"  Device:  #{dev_index}")
        logger.info(f"  Range:   0x{I2C_ADDR_MIN:02X}-0x{I2C_ADDR_MAX:02X}")
        logger.info("")

    found: List[int] = []

    with _I2CDevice(dev_index, speed):
        dll = _dll.get_dll()
        for addr in range(I2C_ADDR_MIN, I2C_ADDR_MAX + 1):
            # Probe with a zero-length read after the address byte
            write_addr = (addr << 1) & 0xFE
            write_buf = ((_dll.ctypes.c_ubyte) * 1)(write_addr)
            ok = dll.CH347StreamI2C(dev_index, 1, write_buf, 0, None)
            if ok:
                found.append(addr)
                if logger:
                    logger.info(f"  0x{addr:02X} ({addr:3d})  ACK")

    if logger:
        logger.info("")
        logger.info(f"  Devices found: {len(found)}")
        if found:
            logger.info(f"  Addresses: {', '.join(f'0x{a:02X}' for a in found)}")
        logger.info("=" * 80)
        logger.info("")

    return found


def _write(dev_index: int, address: int, data: bytes,
           speed: int = I2C_SPEED_100KHZ) -> bool:
    """Write data to an I2C device via CH347StreamI2C.

    Args:
        dev_index: CH347 device index.
        address: 7-bit I2C device address.
        data: Data bytes to write.
        speed: I2C clock speed constant.

    Returns:
        True on success.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE I2C] WRITE")
        logger.info("=" * 80)
        logger.info(f"  Device:  #{dev_index}  Address: 0x{address:02X}")
        logger.info(f"  Length:  {len(data)} bytes")
        logger.info("")
        logger.info("  TX Data:")
        for line in _format_hex_dump(data).split('\n'):
            logger.info(f"    {line}")
        logger.info("")

    if not (I2C_ADDR_MIN <= address <= I2C_ADDR_MAX):
        raise WaveshareI2CError(
            f"Invalid I2C address: 0x{address:02X} "
            f"(must be 0x{I2C_ADDR_MIN:02X}-0x{I2C_ADDR_MAX:02X})"
        )

    # CH347StreamI2C: first byte of write buffer = (addr << 1) | W
    write_addr = (address << 1) & 0xFE
    payload = bytes([write_addr]) + data

    with _I2CDevice(dev_index, speed):
        try:
            _dll.i2c_stream(dev_index, payload, read_length=0)
        except OSError as exc:
            if logger:
                logger.error(f"[WAVESHARE I2C ERROR] Write failed: {exc}")
            raise WaveshareI2CError(
                f"I2C write to 0x{address:02X} failed: {exc}"
            ) from exc

    if logger:
        logger.info(f"[OK] Write complete ({len(data)} bytes to 0x{address:02X})")
        logger.info("=" * 80)
    return True


def _read(dev_index: int, address: int, length: int,
          speed: int = I2C_SPEED_100KHZ) -> bytes:
    """Read data from an I2C device via CH347StreamI2C.

    Sends the address with R bit set, then reads *length* bytes.

    Args:
        dev_index: CH347 device index.
        address: 7-bit I2C device address.
        length: Number of bytes to read.
        speed: I2C clock speed constant.

    Returns:
        Data bytes read from the device.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE I2C] READ")
        logger.info("=" * 80)
        logger.info(f"  Device:  #{dev_index}  Address: 0x{address:02X}")
        logger.info(f"  Length:  {length} bytes")
        logger.info("")

    if not (I2C_ADDR_MIN <= address <= I2C_ADDR_MAX):
        raise WaveshareI2CError(f"Invalid I2C address: 0x{address:02X}")

    # CH347StreamI2C: write buffer = address byte with R bit
    read_addr = ((address << 1) & 0xFE) | 0x01
    write_buf = bytes([read_addr])

    with _I2CDevice(dev_index, speed):
        try:
            result = _dll.i2c_stream(dev_index, write_buf, read_length=length)
        except OSError as exc:
            if logger:
                logger.error(f"[WAVESHARE I2C ERROR] Read failed: {exc}")
            raise WaveshareI2CError(
                f"I2C read from 0x{address:02X} failed: {exc}"
            ) from exc

    if logger:
        logger.info("  RX Data:")
        for line in _format_hex_dump(result).split('\n'):
            logger.info(f"    {line}")
        logger.info("")
        logger.info(f"[OK] Read complete ({len(result)} bytes)")
        logger.info("=" * 80)
    return result


def _write_register(dev_index: int, address: int, register: int,
                    data: bytes, speed: int = I2C_SPEED_100KHZ) -> bool:
    """Write data to a specific register on an I2C device.

    Sends [ADDR_W] [REGISTER] [DATA...] in a single transaction.
    """
    logger = get_active_logger()
    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE I2C] WRITE REGISTER")
        logger.info("=" * 80)
        logger.info(f"  Device:   #{dev_index}  Address: 0x{address:02X}")
        logger.info(f"  Register: 0x{register:02X}  Length: {len(data)} bytes")
        logger.info("")

    write_addr = (address << 1) & 0xFE
    payload = bytes([write_addr, register]) + data

    with _I2CDevice(dev_index, speed):
        try:
            _dll.i2c_stream(dev_index, payload, read_length=0)
        except OSError as exc:
            if logger:
                logger.error(f"[WAVESHARE I2C ERROR] Write register failed: {exc}")
            raise WaveshareI2CError(
                f"I2C write register 0x{register:02X} at 0x{address:02X} failed: {exc}"
            ) from exc

    if logger:
        logger.info(f"[OK] Register write complete")
        logger.info("=" * 80)
    return True


def _read_register(dev_index: int, address: int, register: int,
                   length: int, speed: int = I2C_SPEED_100KHZ) -> bytes:
    """Read data from a specific register on an I2C device.

    Performs a write-then-read (repeated START):
    [ADDR_W] [REGISTER] [rSTART] [ADDR_R] [DATA...]
    CH347StreamI2C handles the repeated start internally.
    """
    logger = get_active_logger()
    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE I2C] READ REGISTER")
        logger.info("=" * 80)
        logger.info(f"  Device:   #{dev_index}  Address: 0x{address:02X}")
        logger.info(f"  Register: 0x{register:02X}  Length: {length} bytes")
        logger.info("")

    # CH347StreamI2C with both write and read does a write-then-repeated-start-read
    write_addr = (address << 1) & 0xFE
    write_buf = bytes([write_addr, register])

    with _I2CDevice(dev_index, speed):
        try:
            result = _dll.i2c_stream(dev_index, write_buf, read_length=length)
        except OSError as exc:
            if logger:
                logger.error(f"[WAVESHARE I2C ERROR] Read register failed: {exc}")
            raise WaveshareI2CError(
                f"I2C read register 0x{register:02X} at 0x{address:02X} failed: {exc}"
            ) from exc

    if logger:
        logger.info("  RX Data:")
        for line in _format_hex_dump(result).split('\n'):
            logger.info(f"    {line}")
        logger.info("")
        logger.info(f"[OK] Register read complete")
        logger.info("=" * 80)
    return result


# ======================== TestAction Factories ========================

def scan(
        name: str,
        dev_index: int,
        expected_addresses: Optional[List[int]] = None,
        speed: int = I2C_SPEED_100KHZ,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that scans the I2C bus for devices.

    Args:
        name: Human-readable name for the test action.
        dev_index: CH347 device index.
        expected_addresses: Addresses that must be found (None = no check).
        speed: I2C clock speed constant.
        negative_test: Mark as negative test.

    Returns:
        TestAction that returns the list of found addresses.
    """

    def execute():
        logger = get_active_logger()
        found = _scan_bus(dev_index, speed)

        if expected_addresses is not None:
            missing = [a for a in expected_addresses if a not in found]
            if missing:
                missing_str = ", ".join(f"0x{a:02X}" for a in missing)
                found_str = ", ".join(f"0x{a:02X}" for a in found) if found else "none"
                if logger:
                    logger.error("[WAVESHARE I2C] SCAN VALIDATION FAILED")
                    logger.error(f"  Missing: {missing_str}")
                    logger.error(f"  Found:   {found_str}")
                raise WaveshareI2CError(
                    f"Expected I2C devices not found: {missing_str} (found: {found_str})"
                )
            if logger:
                logger.info(f"[OK] All expected I2C devices found")
        return found

    exp_str = ""
    if expected_addresses:
        exp_str = ", ".join(f"0x{a:02X}" for a in expected_addresses)

    metadata = {
        'display_command': f"I2C scan dev#{dev_index} 0x{I2C_ADDR_MIN:02X}-0x{I2C_ADDR_MAX:02X}",
        'display_expected': exp_str,
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def write(
        name: str,
        dev_index: int,
        address: int,
        data: bytes,
        speed: int = I2C_SPEED_100KHZ,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that writes data to an I2C device."""

    def execute():
        return _write(dev_index, address, data, speed)

    metadata = {
        'display_command': f"I2C write dev#{dev_index} 0x{address:02X} [{len(data)}B]",
        'display_expected': 'ACK',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def read(
        name: str,
        dev_index: int,
        address: int,
        length: int,
        expected: Optional[bytes] = None,
        speed: int = I2C_SPEED_100KHZ,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that reads data from an I2C device."""

    def execute():
        logger = get_active_logger()
        result = _read(dev_index, address, length, speed)
        if expected is not None and result != expected:
            if logger:
                logger.error("[WAVESHARE I2C] READ VALIDATION FAILED")
                logger.error(f"  Address:  0x{address:02X}")
                logger.error(f"  Expected: {expected.hex(' ').upper()}")
                logger.error(f"  Actual:   {result.hex(' ').upper()}")
            raise WaveshareI2CError(
                f"I2C read mismatch at 0x{address:02X}: "
                f"expected {expected.hex(' ').upper()}, got {result.hex(' ').upper()}"
            )
        return result

    metadata = {
        'display_command': f"I2C read dev#{dev_index} 0x{address:02X} [{length}B]",
        'display_expected': expected.hex(' ').upper() if expected else '',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def write_register(
        name: str,
        dev_index: int,
        address: int,
        register: int,
        data: bytes,
        speed: int = I2C_SPEED_100KHZ,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that writes data to a specific I2C register."""

    def execute():
        return _write_register(dev_index, address, register, data, speed)

    metadata = {
        'display_command': f"I2C wreg dev#{dev_index} 0x{address:02X}[0x{register:02X}] [{len(data)}B]",
        'display_expected': 'ACK',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def read_register(
        name: str,
        dev_index: int,
        address: int,
        register: int,
        length: int,
        expected: Optional[bytes] = None,
        speed: int = I2C_SPEED_100KHZ,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that reads data from a specific I2C register."""

    def execute():
        logger = get_active_logger()
        result = _read_register(dev_index, address, register, length, speed)
        if expected is not None and result != expected:
            if logger:
                logger.error("[WAVESHARE I2C] REGISTER READ VALIDATION FAILED")
                logger.error(f"  0x{address:02X}[0x{register:02X}]")
                logger.error(f"  Expected: {expected.hex(' ').upper()}")
                logger.error(f"  Actual:   {result.hex(' ').upper()}")
            raise WaveshareI2CError(
                f"I2C register read mismatch at 0x{address:02X}[0x{register:02X}]: "
                f"expected {expected.hex(' ').upper()}, got {result.hex(' ').upper()}"
            )
        return result

    metadata = {
        'display_command': f"I2C rreg dev#{dev_index} 0x{address:02X}[0x{register:02X}] [{length}B]",
        'display_expected': expected.hex(' ').upper() if expected else '',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def verify_device(
        name: str,
        dev_index: int,
        address: int,
        register: int,
        expected_id: bytes,
        speed: int = I2C_SPEED_100KHZ,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that verifies an I2C device identity by reading
    a WHO_AM_I / device-ID register.
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

        result = _read_register(dev_index, address, register, len(expected_id), speed)

        if result != expected_id:
            if logger:
                logger.error(f"  Device ID mismatch")
                logger.error(f"    Expected: {expected_id.hex(' ').upper()}")
                logger.error(f"    Actual:   {result.hex(' ').upper()}")
            raise WaveshareI2CError(
                f"Device at 0x{address:02X} ID mismatch: "
                f"expected {expected_id.hex(' ').upper()}, got {result.hex(' ').upper()}"
            )

        if logger:
            logger.info(f"  [OK] Device ID verified: {result.hex(' ').upper()}")
            logger.info("=" * 80)
        return True

    metadata = {
        'display_command': f"I2C verify dev#{dev_index} 0x{address:02X}[0x{register:02X}]",
        'display_expected': expected_id.hex(' ').upper(),
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)
