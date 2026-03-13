# eeprom.py
"""
UTFW Waveshare EEPROM Module
==============================
High-level I2C EEPROM read/write/verify functions and TestAction factories
for the Waveshare USB TO UART/I2C/SPI/JTAG adapter (WCH CH347 chipset).

Supported EEPROM types: 24C01 through 24C4096.

The vendor DLL exposes dedicated ``CH347ReadEEPROM`` / ``CH347WriteEEPROM``
calls that handle addressing internally; the caller only specifies the
EEPROM type constant and byte offset.

The device is accessed by *index* (0-15) through CH347OpenDevice.

Usage:
    import UTFW
    waveshare = UTFW.modules.ext_tools.waveshare

    action = waveshare.eeprom.read("Read 256 bytes",
        dev_index=0, eeprom_type=waveshare.eeprom.TYPE_24C256,
        addr=0x0000, length=256)

Author: DvidMakesThings
"""

from typing import Optional

from ....core.logger import get_active_logger
from ....core.core import TestAction
from ._base import WaveshareError, _format_hex_dump
from . import _dll

# EEPROM type constants (re-exported from _dll for convenience)
TYPE_24C01 = _dll.EEPROM_24C01
TYPE_24C02 = _dll.EEPROM_24C02
TYPE_24C04 = _dll.EEPROM_24C04
TYPE_24C08 = _dll.EEPROM_24C08
TYPE_24C16 = _dll.EEPROM_24C16
TYPE_24C32 = _dll.EEPROM_24C32
TYPE_24C64 = _dll.EEPROM_24C64
TYPE_24C128 = _dll.EEPROM_24C128
TYPE_24C256 = _dll.EEPROM_24C256
TYPE_24C512 = _dll.EEPROM_24C512
TYPE_24C1024 = _dll.EEPROM_24C1024
TYPE_24C2048 = _dll.EEPROM_24C2048
TYPE_24C4096 = _dll.EEPROM_24C4096

# Human-readable names for display
_TYPE_NAMES = {
    TYPE_24C01: "24C01 (128B)",
    TYPE_24C02: "24C02 (256B)",
    TYPE_24C04: "24C04 (512B)",
    TYPE_24C08: "24C08 (1KB)",
    TYPE_24C16: "24C16 (2KB)",
    TYPE_24C32: "24C32 (4KB)",
    TYPE_24C64: "24C64 (8KB)",
    TYPE_24C128: "24C128 (16KB)",
    TYPE_24C256: "24C256 (32KB)",
    TYPE_24C512: "24C512 (64KB)",
    TYPE_24C1024: "24C1024 (128KB)",
    TYPE_24C2048: "24C2048 (256KB)",
    TYPE_24C4096: "24C4096 (512KB)",
}


class WaveshareEEPROMError(WaveshareError):
    """Exception raised when Waveshare EEPROM operations fail."""
    pass


# ======================== Context Manager ========================

class _EEPROMDevice:
    """RAII wrapper: opens CH347 device, closes on exit."""

    def __init__(self, dev_index: int):
        self.dev_index = dev_index

    def __enter__(self):
        try:
            _dll.open_device(self.dev_index)
        except OSError as exc:
            raise WaveshareEEPROMError(
                f"Cannot open CH347 device {self.dev_index}: {exc}"
            ) from exc
        return self

    def __exit__(self, *_exc):
        _dll.close_device(self.dev_index)


# ======================== Core EEPROM Functions ========================

def _read_eeprom(dev_index: int, eeprom_type: int, addr: int,
                 length: int) -> bytes:
    """Read data from an I2C EEPROM.

    Args:
        dev_index: CH347 device index (0-15).
        eeprom_type: EEPROM type constant (TYPE_24C01 ... TYPE_24C4096).
        addr: Starting byte address inside the EEPROM.
        length: Number of bytes to read.

    Returns:
        Read data bytes.
    """
    logger = get_active_logger()
    type_name = _TYPE_NAMES.get(eeprom_type, f"type={eeprom_type}")

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE EEPROM] READ")
        logger.info("=" * 80)
        logger.info(f"  Device: #{dev_index}  EEPROM: {type_name}")
        logger.info(f"  Addr:   0x{addr:04X}  Length: {length}")
        logger.info("")

    with _EEPROMDevice(dev_index):
        try:
            data = _dll.eeprom_read(dev_index, eeprom_type, addr, length)
        except OSError as exc:
            if logger:
                logger.error(f"[WAVESHARE EEPROM ERROR] Read failed: {exc}")
            raise WaveshareEEPROMError(
                f"EEPROM read failed at 0x{addr:04X}: {exc}"
            ) from exc

    if logger:
        logger.info("  Data:")
        for line in _format_hex_dump(data).split('\n'):
            logger.info(f"    {line}")
        logger.info("")
        logger.info(f"  [OK] Read complete ({len(data)} bytes)")
        logger.info("=" * 80)
    return data


def _write_eeprom(dev_index: int, eeprom_type: int, addr: int,
                  data: bytes) -> bool:
    """Write data to an I2C EEPROM.

    Args:
        dev_index: CH347 device index (0-15).
        eeprom_type: EEPROM type constant.
        addr: Starting byte address inside the EEPROM.
        data: Data bytes to write.

    Returns:
        True on success.
    """
    logger = get_active_logger()
    type_name = _TYPE_NAMES.get(eeprom_type, f"type={eeprom_type}")

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE EEPROM] WRITE")
        logger.info("=" * 80)
        logger.info(f"  Device: #{dev_index}  EEPROM: {type_name}")
        logger.info(f"  Addr:   0x{addr:04X}  Length: {len(data)}")
        logger.info("")
        logger.info("  Data:")
        for line in _format_hex_dump(data).split('\n'):
            logger.info(f"    {line}")
        logger.info("")

    with _EEPROMDevice(dev_index):
        try:
            _dll.eeprom_write(dev_index, eeprom_type, addr, data)
        except OSError as exc:
            if logger:
                logger.error(f"[WAVESHARE EEPROM ERROR] Write failed: {exc}")
            raise WaveshareEEPROMError(
                f"EEPROM write failed at 0x{addr:04X}: {exc}"
            ) from exc

    if logger:
        logger.info(f"  [OK] Write complete ({len(data)} bytes)")
        logger.info("=" * 80)
    return True


def _verify_eeprom(dev_index: int, eeprom_type: int, addr: int,
                   expected: bytes) -> bool:
    """Write data then read back and verify.

    Performs a write followed by a read at the same address and compares
    the result byte-for-byte.

    Args:
        dev_index: CH347 device index.
        eeprom_type: EEPROM type constant.
        addr: Starting byte address.
        expected: The data to write and verify.

    Returns:
        True if readback matches.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE EEPROM] WRITE-VERIFY")
        logger.info("=" * 80)

    _write_eeprom(dev_index, eeprom_type, addr, expected)
    readback = _read_eeprom(dev_index, eeprom_type, addr, len(expected))

    if readback != expected:
        if logger:
            logger.error("[WAVESHARE EEPROM] VERIFICATION FAILED")
            logger.error(f"  Addr: 0x{addr:04X}  Length: {len(expected)}")
            # Find first mismatch
            for i, (e, a) in enumerate(zip(expected, readback)):
                if e != a:
                    logger.error(
                        f"  First mismatch at offset 0x{i:04X}: "
                        f"expected 0x{e:02X}, got 0x{a:02X}"
                    )
                    break
        raise WaveshareEEPROMError(
            f"EEPROM verify failed at 0x{addr:04X}: "
            f"expected {expected[:16].hex(' ').upper()}... "
            f"got {readback[:16].hex(' ').upper()}..."
        )

    if logger:
        logger.info(f"  [OK] Verification passed ({len(expected)} bytes)")
        logger.info("=" * 80)
    return True


# ======================== TestAction Factories ========================

def read(
        name: str,
        dev_index: int,
        eeprom_type: int,
        addr: int,
        length: int,
        expected: Optional[bytes] = None,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that reads EEPROM data."""

    def execute():
        logger = get_active_logger()
        data = _read_eeprom(dev_index, eeprom_type, addr, length)

        if expected is not None and data != expected:
            if logger:
                logger.error("[WAVESHARE EEPROM] READ VALIDATION FAILED")
                logger.error(f"  Expected: {expected[:16].hex(' ').upper()}...")
                logger.error(f"  Actual:   {data[:16].hex(' ').upper()}...")
            raise WaveshareEEPROMError(
                f"EEPROM read mismatch at 0x{addr:04X}"
            )
        return data

    type_name = _TYPE_NAMES.get(eeprom_type, f"type={eeprom_type}")
    metadata = {
        'display_command': f"EEPROM read {type_name} 0x{addr:04X} [{length}B]",
        'display_expected': expected[:8].hex(' ').upper() + '...' if expected else '',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def write(
        name: str,
        dev_index: int,
        eeprom_type: int,
        addr: int,
        data: bytes,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that writes EEPROM data."""

    def execute():
        return _write_eeprom(dev_index, eeprom_type, addr, data)

    type_name = _TYPE_NAMES.get(eeprom_type, f"type={eeprom_type}")
    metadata = {
        'display_command': f"EEPROM write {type_name} 0x{addr:04X} [{len(data)}B]",
        'display_expected': 'OK',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def verify(
        name: str,
        dev_index: int,
        eeprom_type: int,
        addr: int,
        data: bytes,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that writes then reads back EEPROM data to verify."""

    def execute():
        return _verify_eeprom(dev_index, eeprom_type, addr, data)

    type_name = _TYPE_NAMES.get(eeprom_type, f"type={eeprom_type}")
    metadata = {
        'display_command': f"EEPROM verify {type_name} 0x{addr:04X} [{len(data)}B]",
        'display_expected': 'match',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)
