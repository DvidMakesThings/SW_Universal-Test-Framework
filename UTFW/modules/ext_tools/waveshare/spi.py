# spi.py
"""
UTFW Waveshare SPI Module
==========================
High-level SPI master test functions and TestAction factories for the
Waveshare USB TO UART/I2C/SPI/JTAG adapter (WCH CH347 chipset).

This module communicates through the CH347 vendor DLL (Windows) for proper
hardware SPI transactions.  The CH347 SPI controller supports:
- SPI modes 0-3 (CPOL/CPHA combinations)
- Clock speeds from 468.75 KHz to 60 MHz
- CS0 / CS1 chip-select lines with configurable polarity
- Full-duplex and half-duplex transfers up to 4096 bytes
- 8-bit or 16-bit data width (16-bit CH347F only)

The device is accessed by *index* (0-15) through CH347OpenDevice, NOT through
a virtual COM port.  Use ``_dll.enumerate_devices()`` to discover the correct
index for the SPI/I2C function interface.

All SPI operations are logged using the UTFW logging system.

Usage:
    import UTFW
    waveshare = UTFW.modules.ext_tools.waveshare

    action = waveshare.spi.transfer(
        "SPI loopback", dev_index=0, tx_data=b'\\xAA\\x55'
    )
    action = waveshare.spi.verify_jedec(
        "Verify W25Q128", dev_index=0,
        expected_manufacturer=0xEF,
    )

Author: DvidMakesThings
"""

from typing import Optional

from ....core.logger import get_active_logger
from ....core.core import TestAction
from ._base import WaveshareError, _format_hex_dump
from . import _dll

# SPI mode constants (CPOL, CPHA)
SPI_MODE_0 = 0  # CPOL=0, CPHA=0
SPI_MODE_1 = 1  # CPOL=0, CPHA=1
SPI_MODE_2 = 2  # CPOL=1, CPHA=0
SPI_MODE_3 = 3  # CPOL=1, CPHA=1

# Clock divider presets (index -> frequency)
SPI_CLK_60MHZ = 0
SPI_CLK_30MHZ = 1
SPI_CLK_15MHZ = 2
SPI_CLK_7_5MHZ = 3
SPI_CLK_3_75MHZ = 4
SPI_CLK_1_875MHZ = 5
SPI_CLK_937KHZ = 6
SPI_CLK_468KHZ = 7

# Chip select lines
CS0 = 0
CS1 = 1


class WaveshareSPIError(WaveshareError):
    """Exception raised when Waveshare SPI operations fail."""
    pass


# ======================== Context Manager ========================

class _SPIDevice:
    """RAII wrapper: opens CH347  device, initialises SPI, closes on exit."""

    def __init__(self, dev_index: int, mode: int = SPI_MODE_0,
                 clock: int = SPI_CLK_30MHZ, byte_order: int = 1,
                 cs: int = CS0):
        self.dev_index = dev_index
        self.mode = mode
        self.clock = clock
        self.byte_order = byte_order
        self.cs = cs

    def __enter__(self):
        try:
            _dll.open_device(self.dev_index)
        except OSError as exc:
            raise WaveshareSPIError(
                f"Cannot open CH347 device {self.dev_index}: {exc}"
            ) from exc
        try:
            if not _dll.spi_init(self.dev_index, self.mode, self.clock,
                                 self.byte_order, self.cs):
                raise WaveshareSPIError("CH347SPI_Init returned FALSE")
        except OSError as exc:
            _dll.close_device(self.dev_index)
            raise WaveshareSPIError(f"SPI init failed: {exc}") from exc
        return self

    def __exit__(self, *_exc):
        _dll.close_device(self.dev_index)


# ======================== Core SPI Functions ========================

def _transfer(dev_index: int, tx_data: bytes, cs: int = CS0,
              mode: int = SPI_MODE_0, clock: int = SPI_CLK_30MHZ) -> bytes:
    """Full-duplex SPI transfer using CH347SPI_WriteRead.

    Opens the device, initialises SPI, performs the transfer, and closes.

    Args:
        dev_index: CH347 device index (0-15).
        tx_data: Data bytes to transmit on MOSI.
        cs: Chip-select line (0 or 1).
        mode: SPI mode (0-3).
        clock: Clock divider (0=60 MHz ... 7=468.75 KHz).

    Returns:
        Data bytes received on MISO (same length as tx_data).
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE SPI] FULL-DUPLEX TRANSFER")
        logger.info("=" * 80)
        logger.info(f"  Device:  #{dev_index}")
        logger.info(f"  CS:      CS{cs}")
        logger.info(f"  Mode:    SPI_MODE_{mode}")
        logger.info(f"  Clock:   divider {clock}")
        logger.info(f"  Length:  {len(tx_data)} bytes")
        logger.info("")
        logger.info("  MOSI (TX):")
        for line in _format_hex_dump(tx_data).split('\n'):
            logger.info(f"    {line}")
        logger.info("")

    with _SPIDevice(dev_index, mode, clock, cs=cs):
        try:
            rx = _dll.spi_write_read(dev_index, tx_data, chip_select=0x80)
        except OSError as exc:
            if logger:
                logger.error(f"[WAVESHARE SPI ERROR] Transfer failed: {exc}")
            raise WaveshareSPIError(f"SPI transfer failed: {exc}") from exc

    if logger:
        logger.info("  MISO (RX):")
        for line in _format_hex_dump(rx).split('\n'):
            logger.info(f"    {line}")
        logger.info("")
        logger.info(f"[OK] Transfer complete ({len(rx)} bytes)")
        logger.info("=" * 80)
        logger.info("")
    return rx


def _write(dev_index: int, data: bytes, cs: int = CS0,
           mode: int = SPI_MODE_0, clock: int = SPI_CLK_30MHZ) -> bool:
    """Write-only SPI transfer using CH347SPI_Write."""
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE SPI] WRITE")
        logger.info("=" * 80)
        logger.info(f"  Device:  #{dev_index}  CS: CS{cs}  Mode: {mode}")
        logger.info(f"  Length:  {len(data)} bytes")
        logger.info("")
        logger.info("  TX Data:")
        for line in _format_hex_dump(data).split('\n'):
            logger.info(f"    {line}")
        logger.info("")

    with _SPIDevice(dev_index, mode, clock, cs=cs):
        try:
            _dll.spi_write(dev_index, data, chip_select=0x80)
        except OSError as exc:
            if logger:
                logger.error(f"[WAVESHARE SPI ERROR] Write failed: {exc}")
            raise WaveshareSPIError(f"SPI write failed: {exc}") from exc

    if logger:
        logger.info(f"[OK] Write complete ({len(data)} bytes)")
        logger.info("=" * 80)
    return True


def _read(dev_index: int, length: int, cs: int = CS0,
          mode: int = SPI_MODE_0, clock: int = SPI_CLK_30MHZ) -> bytes:
    """Read-only SPI transfer (clocks out 0xFF dummy bytes)."""
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE SPI] READ")
        logger.info("=" * 80)
        logger.info(f"  Device:  #{dev_index}  CS: CS{cs}  Mode: {mode}")
        logger.info(f"  Length:  {length} bytes")
        logger.info("")

    dummy = bytes([0xFF] * length)
    result = _transfer(dev_index, dummy, cs, mode, clock)

    if logger:
        logger.info("  RX Data:")
        for line in _format_hex_dump(result).split('\n'):
            logger.info(f"    {line}")
        logger.info("")
    return result


def _write_register(dev_index: int, register: int, data: bytes,
                    cs: int = CS0, mode: int = SPI_MODE_0,
                    clock: int = SPI_CLK_30MHZ) -> bool:
    """Write [register_addr & 0x7F] + data in one SPI transaction."""
    logger = get_active_logger()
    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE SPI] WRITE REGISTER")
        logger.info("=" * 80)
        logger.info(f"  Device:   #{dev_index}  CS: CS{cs}")
        logger.info(f"  Register: 0x{register:02X}")
        logger.info(f"  Length:   {len(data)} bytes")
        logger.info("")

    payload = bytes([register & 0x7F]) + data
    _transfer(dev_index, payload, cs, mode, clock)

    if logger:
        logger.info(f"[OK] Register write complete")
    return True


def _read_register(dev_index: int, register: int, length: int,
                   cs: int = CS0, mode: int = SPI_MODE_0,
                   clock: int = SPI_CLK_30MHZ) -> bytes:
    """Read [register_addr | 0x80] + dummy -> data bytes."""
    logger = get_active_logger()
    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE SPI] READ REGISTER")
        logger.info("=" * 80)
        logger.info(f"  Device:   #{dev_index}  CS: CS{cs}")
        logger.info(f"  Register: 0x{register:02X}")
        logger.info(f"  Length:   {length} bytes")
        logger.info("")

    tx = bytes([register | 0x80]) + bytes([0xFF] * length)
    rx = _transfer(dev_index, tx, cs, mode, clock)
    result = rx[1:1 + length]

    if logger:
        logger.info("  RX Data:")
        for line in _format_hex_dump(result).split('\n'):
            logger.info(f"    {line}")
        logger.info("")
        logger.info(f"[OK] Register read complete")
    return result


# ======================== TestAction Factories ========================

def transfer(
        name: str,
        dev_index: int,
        tx_data: bytes,
        expected_rx: Optional[bytes] = None,
        cs: int = CS0,
        mode: int = SPI_MODE_0,
        clock: int = SPI_CLK_30MHZ,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that performs a full-duplex SPI transfer."""

    def execute():
        logger = get_active_logger()
        result = _transfer(dev_index, tx_data, cs, mode, clock)
        if expected_rx is not None and result != expected_rx:
            if logger:
                logger.error("[WAVESHARE SPI] TRANSFER VALIDATION FAILED")
                logger.error(f"  Expected: {expected_rx.hex(' ').upper()}")
                logger.error(f"  Actual:   {result.hex(' ').upper()}")
            raise WaveshareSPIError(
                f"SPI transfer mismatch: expected {expected_rx.hex(' ').upper()}, "
                f"got {result.hex(' ').upper()}"
            )
        return result

    metadata = {
        'display_command': f"SPI xfer dev#{dev_index} CS{cs} M{mode} [{len(tx_data)}B]",
        'display_expected': expected_rx.hex(' ').upper() if expected_rx else '',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def write(
        name: str,
        dev_index: int,
        data: bytes,
        cs: int = CS0,
        mode: int = SPI_MODE_0,
        clock: int = SPI_CLK_30MHZ,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that writes data on the SPI bus."""

    def execute():
        return _write(dev_index, data, cs, mode, clock)

    metadata = {
        'display_command': f"SPI write dev#{dev_index} CS{cs} [{len(data)}B]",
        'display_expected': 'OK',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def read(
        name: str,
        dev_index: int,
        length: int,
        expected: Optional[bytes] = None,
        cs: int = CS0,
        mode: int = SPI_MODE_0,
        clock: int = SPI_CLK_30MHZ,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that reads data from the SPI bus."""

    def execute():
        logger = get_active_logger()
        result = _read(dev_index, length, cs, mode, clock)
        if expected is not None and result != expected:
            if logger:
                logger.error("[WAVESHARE SPI] READ VALIDATION FAILED")
                logger.error(f"  Expected: {expected.hex(' ').upper()}")
                logger.error(f"  Actual:   {result.hex(' ').upper()}")
            raise WaveshareSPIError(
                f"SPI read mismatch: expected {expected.hex(' ').upper()}, "
                f"got {result.hex(' ').upper()}"
            )
        return result

    metadata = {
        'display_command': f"SPI read dev#{dev_index} CS{cs} [{length}B]",
        'display_expected': expected.hex(' ').upper() if expected else '',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def write_register(
        name: str,
        dev_index: int,
        register: int,
        data: bytes,
        cs: int = CS0,
        mode: int = SPI_MODE_0,
        clock: int = SPI_CLK_30MHZ,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that writes data to a specific SPI register."""

    def execute():
        return _write_register(dev_index, register, data, cs, mode, clock)

    metadata = {
        'display_command': f"SPI wreg 0x{register:02X} dev#{dev_index} CS{cs} [{len(data)}B]",
        'display_expected': 'OK',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def read_register(
        name: str,
        dev_index: int,
        register: int,
        length: int,
        expected: Optional[bytes] = None,
        cs: int = CS0,
        mode: int = SPI_MODE_0,
        clock: int = SPI_CLK_30MHZ,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that reads data from a specific SPI register."""

    def execute():
        logger = get_active_logger()
        result = _read_register(dev_index, register, length, cs, mode, clock)
        if expected is not None and result != expected:
            if logger:
                logger.error("[WAVESHARE SPI] REGISTER READ VALIDATION FAILED")
                logger.error(f"  Register: 0x{register:02X}")
                logger.error(f"  Expected: {expected.hex(' ').upper()}")
                logger.error(f"  Actual:   {result.hex(' ').upper()}")
            raise WaveshareSPIError(
                f"SPI register 0x{register:02X} mismatch: "
                f"expected {expected.hex(' ').upper()}, got {result.hex(' ').upper()}"
            )
        return result

    metadata = {
        'display_command': f"SPI rreg 0x{register:02X} dev#{dev_index} CS{cs} [{length}B]",
        'display_expected': expected.hex(' ').upper() if expected else '',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def verify_jedec(
        name: str,
        dev_index: int,
        expected_manufacturer: Optional[int] = None,
        expected_device_id: Optional[bytes] = None,
        cs: int = CS0,
        mode: int = SPI_MODE_0,
        clock: int = SPI_CLK_30MHZ,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that reads and verifies a JEDEC Flash ID (cmd 0x9F).

    Sends [0x9F, 0xFF, 0xFF, 0xFF] and parses the 3-byte JEDEC response:
    [Manufacturer ID] [Memory Type] [Capacity].
    """

    def execute():
        logger = get_active_logger()
        if logger:
            logger.info("")
            logger.info("=" * 80)
            logger.info("[WAVESHARE SPI] JEDEC ID VERIFICATION")
            logger.info("=" * 80)
            logger.info(f"  Device: #{dev_index}  CS: CS{cs}")
            logger.info("")

        tx = bytes([0x9F, 0xFF, 0xFF, 0xFF])
        rx = _transfer(dev_index, tx, cs, mode, clock)
        jedec_id = rx[1:4]
        manufacturer = jedec_id[0]

        if logger:
            logger.info(f"  JEDEC ID:      {jedec_id.hex(' ').upper()}")
            logger.info(f"  Manufacturer:  0x{manufacturer:02X}")
            logger.info(f"  Memory Type:   0x{jedec_id[1]:02X}")
            logger.info(f"  Capacity:      0x{jedec_id[2]:02X}")
            logger.info("")

        if expected_manufacturer is not None and manufacturer != expected_manufacturer:
            if logger:
                logger.error(f"  Manufacturer mismatch: expected 0x{expected_manufacturer:02X}")
            raise WaveshareSPIError(
                f"JEDEC manufacturer mismatch: expected 0x{expected_manufacturer:02X}, "
                f"got 0x{manufacturer:02X}"
            )
        if expected_device_id is not None and jedec_id != expected_device_id:
            if logger:
                logger.error(f"  JEDEC ID mismatch: expected {expected_device_id.hex(' ').upper()}")
            raise WaveshareSPIError(
                f"JEDEC ID mismatch: expected {expected_device_id.hex(' ').upper()}, "
                f"got {jedec_id.hex(' ').upper()}"
            )
        if logger:
            logger.info(f"  [OK] JEDEC ID verified")
            logger.info("=" * 80)
        return jedec_id

    exp_str = ""
    if expected_device_id:
        exp_str = expected_device_id.hex(' ').upper()
    elif expected_manufacturer is not None:
        exp_str = f"Mfr: 0x{expected_manufacturer:02X}"

    metadata = {
        'display_command': f"SPI JEDEC ID (0x9F) dev#{dev_index} CS{cs}",
        'display_expected': exp_str,
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)
