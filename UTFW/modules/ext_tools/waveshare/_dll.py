# _dll.py
"""
UTFW Waveshare Adapter - CH347 DLL Wrapper (Windows)
=====================================================
Low-level ctypes bindings for the WCH CH347 vendor DLL.

This module loads CH347DLLA64.DLL (64-bit) or CH347DLL.DLL (32-bit)
from the system path and exposes the C API as typed Python functions.
All higher-level modules (SPI, I2C, GPIO, EEPROM) call through this layer.

Reference: CH347DLL_EN.H  V1.5
Author: DvidMakesThings (auto-generated from vendor header)
"""

import ctypes
import ctypes.wintypes as wt
import platform
import struct as _struct
from typing import Optional, List, Tuple

from ....core.logger import get_active_logger

# --------------------------- DLL Loading ---------------------------

_dll: Optional[ctypes.WinDLL] = None
_dll_load_error: Optional[str] = None


def _load_dll() -> ctypes.WinDLL:
    """Load the CH347 vendor DLL, auto-detecting architecture."""
    global _dll, _dll_load_error
    if _dll is not None:
        return _dll

    if platform.system() != "Windows":
        _dll_load_error = "CH347 DLL is only available on Windows"
        raise OSError(_dll_load_error)

    is_64bit = _struct.calcsize("P") * 8 == 64
    dll_name = "CH347DLLA64.DLL" if is_64bit else "CH347DLL.DLL"

    try:
        _dll = ctypes.WinDLL(dll_name)
    except OSError as exc:
        _dll_load_error = (
            f"Cannot load {dll_name}: {exc}. "
            "Install the WCH CH347 USB driver from http://wch.cn"
        )
        raise OSError(_dll_load_error) from exc

    _setup_prototypes(_dll)
    return _dll


def is_available() -> bool:
    """Return True if the CH347 DLL can be loaded on this platform."""
    try:
        _load_dll()
        return True
    except OSError:
        return False


def get_dll() -> ctypes.WinDLL:
    """Return the loaded DLL handle, raising OSError if unavailable."""
    return _load_dll()


# ----------------------- Packed Structures -------------------------

class SpiConfig(ctypes.Structure):
    """Mirrors mSpiCfgS from CH347DLL.H  (#pragma pack(1))."""
    _pack_ = 1
    _fields_ = [
        ("iMode", ctypes.c_ubyte),             # 0-3: SPI Mode 0/1/2/3
        ("iClock", ctypes.c_ubyte),            # 0=60MHz ... 7=468.75KHz
        ("iByteOrder", ctypes.c_ubyte),        # 0=LSB, 1=MSB
        ("iSpiWriteReadInterval", ctypes.c_ushort),  # us
        ("iSpiOutDefaultData", ctypes.c_ubyte),      # MOSI default (reads)
        ("iChipSelect", ctypes.c_ulong),       # bit7 enables CS control
        ("CS1Polarity", ctypes.c_ubyte),       # 0=active-low, 1=active-high
        ("CS2Polarity", ctypes.c_ubyte),       # 0=active-low, 1=active-high
        ("iIsAutoDeativeCS", ctypes.c_ushort), # auto-deassert CS after op
        ("iActiveDelay", ctypes.c_ushort),     # us delay after CS assert
        ("iDelayDeactive", ctypes.c_ulong),    # us delay after CS deassert
    ]


class DeviceInfo(ctypes.Structure):
    """Mirrors mDeviceInforS from CH347DLL.H  (#pragma pack(1))."""
    _pack_ = 1
    _fields_ = [
        ("iIndex", ctypes.c_ubyte),
        ("DevicePath", ctypes.c_ubyte * 260),  # MAX_PATH
        ("UsbClass", ctypes.c_ubyte),
        ("FuncType", ctypes.c_ubyte),
        ("DeviceID", ctypes.c_char * 64),
        ("ChipMode", ctypes.c_ubyte),
        ("DevHandle", wt.HANDLE),
        ("BulkOutEndpMaxSize", ctypes.c_ushort),
        ("BulkInEndpMaxSize", ctypes.c_ushort),
        ("UsbSpeedType", ctypes.c_ubyte),
        ("CH347IfNum", ctypes.c_ubyte),
        ("DataUpEndp", ctypes.c_ubyte),
        ("DataDnEndp", ctypes.c_ubyte),
        ("ProductString", ctypes.c_char * 64),
        ("ManufacturerString", ctypes.c_char * 64),
        ("WriteTimeout", ctypes.c_ulong),
        ("ReadTimeout", ctypes.c_ulong),
        ("FuncDescStr", ctypes.c_char * 64),
        ("FirewareVer", ctypes.c_ubyte),
    ]


# EEPROM type enum (matches C enum)
EEPROM_24C01 = 0
EEPROM_24C02 = 1
EEPROM_24C04 = 2
EEPROM_24C08 = 3
EEPROM_24C16 = 4
EEPROM_24C32 = 5
EEPROM_24C64 = 6
EEPROM_24C128 = 7
EEPROM_24C256 = 8
EEPROM_24C512 = 9
EEPROM_24C1024 = 10
EEPROM_24C2048 = 11
EEPROM_24C4096 = 12

# Chip type constants
CHIP_TYPE_CH341 = 0
CHIP_TYPE_CH347T = 1
CHIP_TYPE_CH347F = 2
CHIP_TYPE_CH339W = 3

# Function interface numbers
CH347_FUNC_UART = 0
CH347_FUNC_SPI_IIC = 1
CH347_FUNC_JTAG_IIC = 2
CH347_FUNC_JTAG_IIC_SPI = 3  # CH347F

INVALID_HANDLE_VALUE = wt.HANDLE(-1).value


# --------------------- Prototype Declarations ---------------------

def _setup_prototypes(dll: ctypes.WinDLL):
    """Declare argument/return types for every DLL entry we use."""

    # -- Common --
    dll.CH347OpenDevice.argtypes = [ctypes.c_ulong]
    dll.CH347OpenDevice.restype = wt.HANDLE

    dll.CH347CloseDevice.argtypes = [ctypes.c_ulong]
    dll.CH347CloseDevice.restype = wt.BOOL

    dll.CH347GetDeviceInfor.argtypes = [ctypes.c_ulong, ctypes.POINTER(DeviceInfo)]
    dll.CH347GetDeviceInfor.restype = wt.BOOL

    dll.CH347GetChipType.argtypes = [ctypes.c_ulong]
    dll.CH347GetChipType.restype = ctypes.c_ubyte

    dll.CH347SetTimeout.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    dll.CH347SetTimeout.restype = wt.BOOL

    dll.CH347GetVersion.argtypes = [
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ubyte),
        ctypes.POINTER(ctypes.c_ubyte),
        ctypes.POINTER(ctypes.c_ubyte),
        ctypes.POINTER(ctypes.c_ubyte),
    ]
    dll.CH347GetVersion.restype = wt.BOOL

    # -- SPI --
    dll.CH347SPI_Init.argtypes = [ctypes.c_ulong, ctypes.POINTER(SpiConfig)]
    dll.CH347SPI_Init.restype = wt.BOOL

    dll.CH347SPI_GetCfg.argtypes = [ctypes.c_ulong, ctypes.POINTER(SpiConfig)]
    dll.CH347SPI_GetCfg.restype = wt.BOOL

    dll.CH347SPI_SetFrequency.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
    dll.CH347SPI_SetFrequency.restype = wt.BOOL

    dll.CH347SPI_SetDataBits.argtypes = [ctypes.c_ulong, ctypes.c_ubyte]
    dll.CH347SPI_SetDataBits.restype = wt.BOOL

    dll.CH347SPI_ChangeCS.argtypes = [ctypes.c_ulong, ctypes.c_ubyte]
    dll.CH347SPI_ChangeCS.restype = wt.BOOL

    dll.CH347SPI_SetChipSelect.argtypes = [
        ctypes.c_ulong, ctypes.c_ushort, ctypes.c_ushort,
        ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
    ]
    dll.CH347SPI_SetChipSelect.restype = wt.BOOL

    dll.CH347SPI_Write.argtypes = [
        ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
        ctypes.c_ulong, ctypes.c_void_p,
    ]
    dll.CH347SPI_Write.restype = wt.BOOL

    dll.CH347SPI_Read.argtypes = [
        ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p,
    ]
    dll.CH347SPI_Read.restype = wt.BOOL

    dll.CH347SPI_WriteRead.argtypes = [
        ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p,
    ]
    dll.CH347SPI_WriteRead.restype = wt.BOOL

    dll.CH347StreamSPI4.argtypes = [
        ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p,
    ]
    dll.CH347StreamSPI4.restype = wt.BOOL

    # -- I2C --
    dll.CH347I2C_Set.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
    dll.CH347I2C_Set.restype = wt.BOOL

    dll.CH347I2C_SetStretch.argtypes = [ctypes.c_ulong, wt.BOOL]
    dll.CH347I2C_SetStretch.restype = wt.BOOL

    dll.CH347I2C_SetDelaymS.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
    dll.CH347I2C_SetDelaymS.restype = wt.BOOL

    dll.CH347StreamI2C.argtypes = [
        ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p,
        ctypes.c_ulong, ctypes.c_void_p,
    ]
    dll.CH347StreamI2C.restype = wt.BOOL

    # -- GPIO --
    dll.CH347GPIO_Get.argtypes = [
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ubyte),
        ctypes.POINTER(ctypes.c_ubyte),
    ]
    dll.CH347GPIO_Get.restype = wt.BOOL

    dll.CH347GPIO_Set.argtypes = [
        ctypes.c_ulong, ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_ubyte,
    ]
    dll.CH347GPIO_Set.restype = wt.BOOL

    # -- EEPROM --
    dll.CH347ReadEEPROM.argtypes = [
        ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong,
        ctypes.c_ulong, ctypes.POINTER(ctypes.c_ubyte),
    ]
    dll.CH347ReadEEPROM.restype = wt.BOOL

    dll.CH347WriteEEPROM.argtypes = [
        ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong,
        ctypes.c_ulong, ctypes.POINTER(ctypes.c_ubyte),
    ]
    dll.CH347WriteEEPROM.restype = wt.BOOL

    # -- JTAG --
    dll.CH347Jtag_INIT.argtypes = [ctypes.c_ulong, ctypes.c_ubyte]
    dll.CH347Jtag_INIT.restype = wt.BOOL

    dll.CH347Jtag_GetCfg.argtypes = [ctypes.c_ulong, ctypes.POINTER(ctypes.c_ubyte)]
    dll.CH347Jtag_GetCfg.restype = wt.BOOL

    dll.CH347Jtag_WriteRead.argtypes = [
        ctypes.c_ulong, wt.BOOL, ctypes.c_ulong, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p,
    ]
    dll.CH347Jtag_WriteRead.restype = wt.BOOL

    dll.CH347Jtag_ByteWriteDR.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    dll.CH347Jtag_ByteWriteDR.restype = wt.BOOL

    dll.CH347Jtag_ByteReadDR.argtypes = [
        ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p,
    ]
    dll.CH347Jtag_ByteReadDR.restype = wt.BOOL

    dll.CH347Jtag_ByteWriteIR.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    dll.CH347Jtag_ByteWriteIR.restype = wt.BOOL

    dll.CH347Jtag_ByteReadIR.argtypes = [
        ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p,
    ]
    dll.CH347Jtag_ByteReadIR.restype = wt.BOOL


# ------------------- Device Management Helpers --------------------

def enumerate_devices() -> List[dict]:
    """Enumerate all CH347 devices visible through the vendor driver.

    Returns a list of dicts with keys:
        index, chip_type, chip_mode, func_type, device_id,
        usb_speed, firmware_ver, func_desc, product, manufacturer
    """
    dll = get_dll()
    devices = []
    info = DeviceInfo()

    for idx in range(16):
        handle = dll.CH347OpenDevice(idx)
        if handle == INVALID_HANDLE_VALUE:
            continue
        try:
            if dll.CH347GetDeviceInfor(idx, ctypes.byref(info)):
                chip_type = dll.CH347GetChipType(idx)
                devices.append({
                    "index": idx,
                    "chip_type": chip_type,
                    "chip_mode": info.ChipMode,
                    "func_type": info.FuncType,
                    "device_id": info.DeviceID.decode("utf-8", errors="replace").strip("\x00"),
                    "usb_speed": ["FS", "HS", "SS"][info.UsbSpeedType] if info.UsbSpeedType < 3 else "?",
                    "firmware_ver": info.FirewareVer,
                    "func_desc": info.FuncDescStr.decode("utf-8", errors="replace").strip("\x00"),
                    "product": info.ProductString.decode("utf-8", errors="replace").strip("\x00"),
                    "manufacturer": info.ManufacturerString.decode("utf-8", errors="replace").strip("\x00"),
                    "if_num": info.CH347IfNum,
                })
        finally:
            dll.CH347CloseDevice(idx)

    return devices


def open_device(index: int) -> int:
    """Open a CH347 device by index. Returns the index on success.

    Raises OSError if the device cannot be opened.
    """
    dll = get_dll()
    handle = dll.CH347OpenDevice(index)
    if handle == INVALID_HANDLE_VALUE:
        raise OSError(f"CH347OpenDevice({index}) failed - device not found or busy")
    dll.CH347SetTimeout(index, 500, 500)
    return index


def close_device(index: int) -> None:
    """Close a previously opened CH347 device."""
    try:
        dll = get_dll()
        dll.CH347CloseDevice(index)
    except OSError:
        pass


# ------------------------ SPI Primitives --------------------------

def spi_init(index: int, mode: int = 0, clock: int = 1,
             byte_order: int = 1, cs: int = 0,
             auto_deassert_cs: bool = True) -> bool:
    """Initialise the SPI controller on the given device index.

    Args:
        index: Device index (from open_device).
        mode: SPI mode 0-3.
        clock: Clock divider 0=60MHz ... 7=468.75KHz.
        byte_order: 0=LSB first, 1=MSB first.
        cs: Chip select 0=CS1, 1=CS2.
        auto_deassert_cs: Automatically release CS after each transfer.

    Returns:
        True on success.
    """
    dll = get_dll()
    cfg = SpiConfig()
    cfg.iMode = mode & 0x03
    cfg.iClock = clock & 0x07
    cfg.iByteOrder = byte_order & 0x01
    cfg.iSpiWriteReadInterval = 0
    cfg.iSpiOutDefaultData = 0xFF
    cfg.iChipSelect = (cs & 0x01) | 0x80  # bit7=1 enables CS control
    cfg.CS1Polarity = 0  # active-low
    cfg.CS2Polarity = 0
    cfg.iIsAutoDeativeCS = 1 if auto_deassert_cs else 0
    cfg.iActiveDelay = 0
    cfg.iDelayDeactive = 0
    return bool(dll.CH347SPI_Init(index, ctypes.byref(cfg)))


def spi_set_frequency(index: int, freq_hz: int) -> bool:
    """Set SPI clock frequency in Hz. Call spi_init() again after this."""
    dll = get_dll()
    return bool(dll.CH347SPI_SetFrequency(index, freq_hz))


def spi_set_databits(index: int, bits_16: bool = False) -> bool:
    """Set SPI data width (8 or 16 bit). CH347F only for 16-bit."""
    dll = get_dll()
    return bool(dll.CH347SPI_SetDataBits(index, 1 if bits_16 else 0))


def spi_write_read(index: int, data: bytes, chip_select: int = 0x80) -> bytes:
    """Full-duplex SPI transfer via CH347SPI_WriteRead.

    Writes *data* on MOSI while simultaneously capturing MISO into the
    same buffer.  Returns the received bytes (same length as *data*).

    Args:
        index: Device index.
        data: Bytes to clock out.
        chip_select: CS control byte (0x80 = use CS per init config).

    Returns:
        Received bytes from MISO.
    """
    dll = get_dll()
    length = len(data)
    buf = (ctypes.c_ubyte * length)(*data)
    ok = dll.CH347SPI_WriteRead(index, chip_select, length, buf)
    if not ok:
        raise OSError("CH347SPI_WriteRead failed")
    return bytes(buf)


def spi_stream4(index: int, data: bytes, chip_select: int = 0x80) -> bytes:
    """Full-duplex SPI4 stream via CH347StreamSPI4."""
    dll = get_dll()
    length = len(data)
    buf = (ctypes.c_ubyte * length)(*data)
    ok = dll.CH347StreamSPI4(index, chip_select, length, buf)
    if not ok:
        raise OSError("CH347StreamSPI4 failed")
    return bytes(buf)


def spi_write(index: int, data: bytes, chip_select: int = 0x80,
              write_step: int = 512) -> bool:
    """SPI write-only via CH347SPI_Write (TX data, ignore MISO)."""
    dll = get_dll()
    length = len(data)
    buf = (ctypes.c_ubyte * length)(*data)
    ok = dll.CH347SPI_Write(index, chip_select, length, write_step, buf)
    if not ok:
        raise OSError("CH347SPI_Write failed")
    return True


def spi_read(index: int, cmd_bytes: bytes, read_length: int,
             chip_select: int = 0x80) -> bytes:
    """SPI read via CH347SPI_Read: send command, then read data.

    Args:
        index: Device index.
        cmd_bytes: Command/address bytes to send first.
        read_length: Number of bytes to read back.
        chip_select: CS control byte.

    Returns:
        Read data bytes.
    """
    dll = get_dll()
    total = len(cmd_bytes) + read_length
    buf = (ctypes.c_ubyte * total)(*cmd_bytes, *([0xFF] * read_length))
    out_len = ctypes.c_ulong(len(cmd_bytes))
    in_len = ctypes.c_ulong(read_length)
    ok = dll.CH347SPI_Read(index, chip_select, out_len.value, ctypes.byref(in_len), buf)
    if not ok:
        raise OSError("CH347SPI_Read failed")
    return bytes(buf[:in_len.value])


# ------------------------ I2C Primitives --------------------------

def i2c_set(index: int, mode: int = 1) -> bool:
    """Configure I2C speed.

    mode bits 1-0: 00=20KHz, 01=100KHz, 10=400KHz, 11=750KHz
    """
    dll = get_dll()
    return bool(dll.CH347I2C_Set(index, mode & 0x03))


def i2c_set_stretch(index: int, enable: bool = True) -> bool:
    """Enable/disable I2C clock stretching."""
    dll = get_dll()
    return bool(dll.CH347I2C_SetStretch(index, 1 if enable else 0))


def i2c_set_delay(index: int, delay_ms: int) -> bool:
    """Set I2C inter-operation delay in milliseconds."""
    dll = get_dll()
    return bool(dll.CH347I2C_SetDelaymS(index, delay_ms))


def i2c_stream(index: int, write_data: bytes,
               read_length: int = 0) -> bytes:
    """Perform an I2C stream transaction via CH347StreamI2C.

    The first byte of *write_data* must be the I2C device address with
    R/W bit (e.g. 0xA0 for write to 0x50, or 0xA1 for read).

    Args:
        index: Device index.
        write_data: Bytes to write (address + optional register/data).
        read_length: Number of bytes to read back (0 for write-only).

    Returns:
        Read data bytes (empty if read_length == 0).
    """
    dll = get_dll()
    w_len = len(write_data)
    w_buf = (ctypes.c_ubyte * max(w_len, 1))(*write_data)

    if read_length > 0:
        r_buf = (ctypes.c_ubyte * read_length)()
    else:
        r_buf = None

    ok = dll.CH347StreamI2C(index, w_len, w_buf, read_length, r_buf)
    if not ok:
        raise OSError("CH347StreamI2C failed")

    return bytes(r_buf) if r_buf is not None else b""


# ------------------------ GPIO Primitives -------------------------

def gpio_get(index: int) -> Tuple[int, int]:
    """Read GPIO direction and pin levels.

    Returns:
        (direction_byte, data_byte) where each bit 0-7 maps to GPIO0-7.
        direction: 0 = input, 1 = output.
        data: 0 = low, 1 = high.
    """
    dll = get_dll()
    dir_byte = ctypes.c_ubyte(0)
    data_byte = ctypes.c_ubyte(0)
    ok = dll.CH347GPIO_Get(index, ctypes.byref(dir_byte), ctypes.byref(data_byte))
    if not ok:
        raise OSError("CH347GPIO_Get failed")
    return dir_byte.value, data_byte.value


def gpio_set(index: int, enable_mask: int, direction: int, data: int) -> bool:
    """Set GPIO direction and output levels.

    Args:
        index: Device index.
        enable_mask: Bitmask of GPIO pins to configure (bits 0-7 -> GPIO0-7).
        direction: Direction bits (0=input, 1=output) for enabled pins.
        data: Output data bits (0=low, 1=high) for pins configured as output.

    Returns:
        True on success.
    """
    dll = get_dll()
    ok = dll.CH347GPIO_Set(index, enable_mask & 0xFF, direction & 0xFF, data & 0xFF)
    if not ok:
        raise OSError("CH347GPIO_Set failed")
    return True


# ------------------------ EEPROM Primitives -----------------------

def eeprom_read(index: int, eeprom_type: int, addr: int, length: int) -> bytes:
    """Read data from I2C EEPROM.

    Args:
        index: Device index.
        eeprom_type: EEPROM_24C01 ... EEPROM_24C4096 constant.
        addr: Starting byte address inside the EEPROM.
        length: Number of bytes to read.

    Returns:
        Read data bytes.
    """
    dll = get_dll()
    buf = (ctypes.c_ubyte * length)()
    ok = dll.CH347ReadEEPROM(index, eeprom_type, addr, length, buf)
    if not ok:
        raise OSError("CH347ReadEEPROM failed")
    return bytes(buf)


def eeprom_write(index: int, eeprom_type: int, addr: int, data: bytes) -> bool:
    """Write data to I2C EEPROM.

    Args:
        index: Device index.
        eeprom_type: EEPROM_24C01 ... EEPROM_24C4096 constant.
        addr: Starting byte address inside the EEPROM.
        data: Data bytes to write.

    Returns:
        True on success.
    """
    dll = get_dll()
    length = len(data)
    buf = (ctypes.c_ubyte * length)(*data)
    ok = dll.CH347WriteEEPROM(index, eeprom_type, addr, length, buf)
    if not ok:
        raise OSError("CH347WriteEEPROM failed")
    return True
