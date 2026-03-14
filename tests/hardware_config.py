"""
Hardware-specific configuration for  device testing
"""

SERIAL_PORT_UART0 = "COM20"
SERIAL_PORT_UART1 = "COM21"

# Serial Configuration
BAUDRATE = 115200
SERIAL_TIMEOUT = 3.0
WRITE_TIMEOUT = 1.0

# ── SWD / Target Configuration ──────────────────────────────────────
SWD_TARGET_CFG = "stm32f1x"                # OpenOCD target config alias
SWD_EXPECTED_DPIDR = "0x1ba01477"           # Cortex-M3 ARM DPIDR
SWD_EXPECTED_DEVICE_COUNT = 1               # Single device on SWD link

# STM32F103 identity registers
STM32F1_EXPECTED_DEVID = "20036410"         # DEV_ID 0x410 = medium-density F103
STM32F1_DBGMCU_IDCODE_ADDR = 0xE0042000
STM32F1_FLASH_SIZE_ADDR = 0x1FFFF7E0

# SRAM scratch area for read/write tests (start of 20 KB SRAM)
STM32F1_SRAM_BASE = 0x20000000
STM32F1_SRAM_SCRATCH_ADDR = 0x20004FF0     # End of SRAM, safe scratch area

# Firmware image for flash tests (relative to test directory)
STM32F1_TEST_FIRMWARE = "STM32F103-BluePill-Blinky.elf"

# CH347 adapter settings
CH347_DEV_INDEX = 0                         # USB device index
CH347_TRST_PIN = 5                          # GPIO5 = TRST (Pin9) → wired to NRST

# ── PU2CANFD / eWald CAN Configuration ──────────────────────────────
# CAN_CHANNEL = "can0"                        # SocketCAN interface (Linux)
CAN_CHANNEL = "PCAN_USBBUS1"                   # PCAN channel (Windows, requires PEAK driver)
CAN_BITRATE = 1000000                          # 1 Mbit/s (matches eWald CONFIG.h)
EWALD_NODE_ID = 0                              # eWald CANopen node ID 