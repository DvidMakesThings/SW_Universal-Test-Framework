"""
UTFW/modules/ext_tools/__init__.py

UTFW External Tools Package
============================

Hardware tool drivers for USB-based multi-protocol adapters.

Available tools:
- waveshare: Waveshare USB TO UART/I2C/SPI/JTAG adapter driver
             (WCH CH347 chipset, sub-modules: uart, i2c, spi, jtag)
- PU2CANFD: Pibiger USB TO CAN FD adapter driver
            (SavvyCAN-FD series, sub-modules: can, canopen)

Author: DvidMakesThings
"""

import importlib

__all__ = [
    "waveshare",
    "PU2CANFD",
]


def __getattr__(name):  # pragma: no cover - simple delegation
    if name in __all__:
        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__} has no attribute {name}")
