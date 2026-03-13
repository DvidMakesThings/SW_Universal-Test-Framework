# gpio.py
"""
UTFW Waveshare GPIO Module
============================
High-level GPIO pin control functions and TestAction factories for the
Waveshare USB TO UART/I2C/SPI/JTAG adapter (WCH CH347 chipset).

The CH347 exposes 8 general-purpose I/O pins (GPIO0-GPIO7) accessible
through the vendor DLL.  Each pin can be independently configured as
input or output, and its level read or driven.

The device is accessed by *index* (0-15) through CH347OpenDevice.

Usage:
    import UTFW
    waveshare = UTFW.modules.ext_tools.waveshare

    action = waveshare.gpio.get_pins("Read all pins", dev_index=0)
    action = waveshare.gpio.set_pin("Drive GPIO0 high", dev_index=0,
                                     pin=0, direction=1, level=1)

Author: DvidMakesThings
"""

from typing import Optional, Dict

from ....core.logger import get_active_logger
from ....core.core import TestAction
from ._base import WaveshareError
from . import _dll

# Number of GPIO pins on the CH347
NUM_PINS = 8


class WaveshareGPIOError(WaveshareError):
    """Exception raised when Waveshare GPIO operations fail."""
    pass


# ======================== Context Manager ========================

class _GPIODevice:
    """RAII wrapper: opens CH347 device, closes on exit."""

    def __init__(self, dev_index: int):
        self.dev_index = dev_index

    def __enter__(self):
        try:
            _dll.open_device(self.dev_index)
        except OSError as exc:
            raise WaveshareGPIOError(
                f"Cannot open CH347 device {self.dev_index}: {exc}"
            ) from exc
        return self

    def __exit__(self, *_exc):
        _dll.close_device(self.dev_index)


# ======================== Core GPIO Functions ========================

def _get_pins(dev_index: int) -> Dict[int, dict]:
    """Read direction and level of all 8 GPIO pins.

    Args:
        dev_index: CH347 device index (0-15).

    Returns:
        Dict mapping pin number (0-7) to
        ``{"direction": "input"|"output", "level": 0|1}``.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE GPIO] READ PINS")
        logger.info("=" * 80)
        logger.info(f"  Device: #{dev_index}")
        logger.info("")

    with _GPIODevice(dev_index):
        try:
            dir_byte, data_byte = _dll.gpio_get(dev_index)
        except OSError as exc:
            if logger:
                logger.error(f"[WAVESHARE GPIO ERROR] Read failed: {exc}")
            raise WaveshareGPIOError(
                f"GPIO read failed on device #{dev_index}: {exc}"
            ) from exc

    pins: Dict[int, dict] = {}
    for i in range(NUM_PINS):
        d = "output" if (dir_byte >> i) & 1 else "input"
        l = (data_byte >> i) & 1
        pins[i] = {"direction": d, "level": l}

    if logger:
        logger.info("  Pin  Dir      Level")
        logger.info("  ---  -------  -----")
        for i in range(NUM_PINS):
            p = pins[i]
            logger.info(f"   {i}   {p['direction']:<7}  {p['level']}")
        logger.info("")
        logger.info("=" * 80)

    return pins


def _set_pin(dev_index: int, pin: int, direction: int, level: int) -> bool:
    """Configure a single GPIO pin.

    Args:
        dev_index: CH347 device index.
        pin: Pin number (0-7).
        direction: 0 = input, 1 = output.
        level: 0 = low, 1 = high (only relevant for output pins).

    Returns:
        True on success.
    """
    logger = get_active_logger()

    if not 0 <= pin < NUM_PINS:
        raise WaveshareGPIOError(f"Invalid pin number {pin} (must be 0-{NUM_PINS - 1})")

    dir_str = "OUTPUT" if direction else "INPUT"
    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE GPIO] SET PIN")
        logger.info("=" * 80)
        logger.info(f"  Device: #{dev_index}  Pin: {pin}")
        logger.info(f"  Dir:    {dir_str}  Level: {level}")
        logger.info("")

    enable_mask = 1 << pin
    dir_bits = (direction & 1) << pin
    data_bits = (level & 1) << pin

    with _GPIODevice(dev_index):
        try:
            _dll.gpio_set(dev_index, enable_mask, dir_bits, data_bits)
        except OSError as exc:
            if logger:
                logger.error(f"[WAVESHARE GPIO ERROR] Set pin failed: {exc}")
            raise WaveshareGPIOError(
                f"GPIO set pin {pin} failed on device #{dev_index}: {exc}"
            ) from exc

    if logger:
        logger.info(f"  [OK] GPIO{pin} -> {dir_str} {'HIGH' if level else 'LOW'}")
        logger.info("=" * 80)
    return True


def _set_pins(dev_index: int, enable_mask: int, direction: int,
              data: int) -> bool:
    """Configure multiple GPIO pins at once.

    Args:
        dev_index: CH347 device index.
        enable_mask: Bitmask of pins to configure (bits 0-7 -> GPIO0-7).
        direction: Direction bits (0=input, 1=output) for enabled pins.
        data: Output data bits (0=low, 1=high) for output pins.

    Returns:
        True on success.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE GPIO] SET PINS (BATCH)")
        logger.info("=" * 80)
        logger.info(f"  Device:   #{dev_index}")
        logger.info(f"  Enable:   0b{enable_mask:08b}")
        logger.info(f"  Dir:      0b{direction:08b}")
        logger.info(f"  Data:     0b{data:08b}")
        logger.info("")

    with _GPIODevice(dev_index):
        try:
            _dll.gpio_set(dev_index, enable_mask, direction, data)
        except OSError as exc:
            if logger:
                logger.error(f"[WAVESHARE GPIO ERROR] Batch set failed: {exc}")
            raise WaveshareGPIOError(
                f"GPIO batch set failed on device #{dev_index}: {exc}"
            ) from exc

    if logger:
        logger.info(f"  [OK] Pins configured")
        logger.info("=" * 80)
    return True


# ======================== TestAction Factories ========================

def get_pins(
        name: str,
        dev_index: int,
        expected: Optional[Dict[int, dict]] = None,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that reads all GPIO pin states.

    Args:
        name: Human-readable name for the test action.
        dev_index: CH347 device index.
        expected: Optional dict of ``{pin: {"direction": ..., "level": ...}}``
                  to validate against.
        negative_test: Mark as negative test.

    Returns:
        TestAction returning pin state dict.
    """

    def execute():
        logger = get_active_logger()
        pins = _get_pins(dev_index)

        if expected is not None:
            for pin_num, exp in expected.items():
                actual = pins.get(pin_num)
                if actual is None:
                    raise WaveshareGPIOError(f"Pin {pin_num} not in result")
                for key in ("direction", "level"):
                    if key in exp and exp[key] != actual[key]:
                        if logger:
                            logger.error(
                                f"[WAVESHARE GPIO] Pin {pin_num} {key} mismatch: "
                                f"expected {exp[key]}, got {actual[key]}"
                            )
                        raise WaveshareGPIOError(
                            f"GPIO{pin_num} {key} expected {exp[key]}, got {actual[key]}"
                        )
            if logger:
                logger.info(f"  [OK] All expected pin states verified")
        return pins

    metadata = {
        'display_command': f"GPIO get dev#{dev_index}",
        'display_expected': str(expected) if expected else '',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def set_pin(
        name: str,
        dev_index: int,
        pin: int,
        direction: int,
        level: int,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that configures a single GPIO pin."""

    def execute():
        return _set_pin(dev_index, pin, direction, level)

    dir_str = "OUT" if direction else "IN"
    lvl_str = "HIGH" if level else "LOW"
    metadata = {
        'display_command': f"GPIO{pin}->{dir_str} {lvl_str} dev#{dev_index}",
        'display_expected': 'OK',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def set_pins(
        name: str,
        dev_index: int,
        enable_mask: int,
        direction: int,
        data: int,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that configures multiple GPIO pins at once."""

    def execute():
        return _set_pins(dev_index, enable_mask, direction, data)

    metadata = {
        'display_command': f"GPIO batch dev#{dev_index} en=0x{enable_mask:02X}",
        'display_expected': 'OK',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def toggle_pin(
        name: str,
        dev_index: int,
        pin: int,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that toggles a GPIO pin (reads current level,
    then writes the inverse as output)."""

    def execute():
        logger = get_active_logger()
        if logger:
            logger.info("")
            logger.info("=" * 80)
            logger.info(f"[WAVESHARE GPIO] TOGGLE PIN {pin}")
            logger.info("=" * 80)

        with _GPIODevice(dev_index):
            dir_byte, data_byte = _dll.gpio_get(dev_index)
            current = (data_byte >> pin) & 1
            new_level = 1 - current
            enable_mask = 1 << pin
            dir_bits = 1 << pin  # set as output
            data_bits = new_level << pin
            _dll.gpio_set(dev_index, enable_mask, dir_bits, data_bits)

        if logger:
            logger.info(f"  GPIO{pin}: {current} -> {new_level}")
            logger.info("=" * 80)
        return new_level

    metadata = {
        'display_command': f"GPIO{pin} toggle dev#{dev_index}",
        'display_expected': 'toggled',
    }
    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)
