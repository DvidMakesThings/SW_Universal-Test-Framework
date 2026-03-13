#!/usr/bin/env python3
"""Waveshare CH347 — SWD instruction coverage test.

Exercises every SWD TestAction against an STM32F103C8T6 (Blue Pill):

    waveshare.swd.scan          — DAP discovery via ``dap info``
    waveshare.swd.read_idcode   — Read SWD DPIDR
    waveshare.swd.reset_halt    — Halt the target
    waveshare.swd.read_memory   — Read target memory / registers
    waveshare.swd.write_memory  — Write target SRAM
    waveshare.swd.flash_image   — Erase + program + verify firmware
    waveshare.swd.flash_verify  — Standalone flash verification
    waveshare.swd.run_target_command — Arbitrary OpenOCD target command

Hardware setup (Mode 3: UART + JTAG/SWD + I2C):

    CH347 adapter           STM32F103 (Blue Pill)
    ─────────────           ─────────────────────
    TMS  ──────────────────  SWDIO  (PA13)
    TCK  ──────────────────  SWCLK  (PA14)
    GND  ──────────────────  GND
    (optional) 3V3 ────────  3V3    (if target not self-powered)

All target-specific parameters are read from hardware_config.py.
"""

import os
import sys

from UTFW.core import run_test_with_teardown
from UTFW.core.utilities import get_hwconfig
from UTFW.modules.ext_tools import waveshare


class tc_waveshare_stm32_swd:
    """SWD instruction coverage test for STM32F103C8T6 via Waveshare CH347."""

    def __init__(self):
        pass

    def pre(self):
        """Pre-step: Ensure the target is running before the test.

        Connects to the target, halts it (no-op if already halted),
        then resumes execution.  This clears stale debug state from
        prior sessions without needing SRST or SYSRESETREQ.
        """
        hw = get_hwconfig()

        return [
            waveshare.swd.run_target_command(
                name="Halt and resume target",
                target_cfg=hw.SWD_TARGET_CFG,
                commands=["halt", "resume"],
            ),
        ]

    def setup(self):
        hw = get_hwconfig()
        fw = os.path.join(os.path.dirname(__file__), hw.STM32F1_TEST_FIRMWARE)

        return [
            # ── 1. scan ──────────────────────────────────────────────
            waveshare.swd.scan(
                name="SWD scan — find target",
                target_cfg=hw.SWD_TARGET_CFG,
                expected_count=hw.SWD_EXPECTED_DEVICE_COUNT,
            ),

            # ── 2. read_idcode ───────────────────────────────────────
            waveshare.swd.read_idcode(
                name="Read SWD DPIDR",
                target_cfg=hw.SWD_TARGET_CFG,
                expected_idcode=hw.SWD_EXPECTED_DPIDR,
            ),

            # ── 3. reset_halt ────────────────────────────────────────
            waveshare.swd.reset_halt(
                name="Halt target",
                target_cfg=hw.SWD_TARGET_CFG,
            ),

            # ── 4. read_memory (DBGMCU_IDCODE) ──────────────────────
            waveshare.swd.read_memory(
                name="Read DBGMCU_IDCODE register",
                target_cfg=hw.SWD_TARGET_CFG,
                address=hw.STM32F1_DBGMCU_IDCODE_ADDR,
                length=1,
                width=32,
                expected=hw.STM32F1_EXPECTED_DEVID,
            ),

            # ── 5. read_memory (flash size) ──────────────────────────
            waveshare.swd.read_memory(
                name="Read flash size register",
                target_cfg=hw.SWD_TARGET_CFG,
                address=hw.STM32F1_FLASH_SIZE_ADDR,
                length=1,
                width=16,
            ),

            # ── 6. write_memory (SRAM scratch) ──────────────────────
            waveshare.swd.write_memory(
                name="Write test pattern to SRAM",
                target_cfg=hw.SWD_TARGET_CFG,
                address=hw.STM32F1_SRAM_SCRATCH_ADDR,
                values=[0xDEADBEEF, 0xCAFEBABE],
                width=32,
            ),

            # ── 7. read_memory (verify SRAM write-back) ─────────────
            waveshare.swd.read_memory(
                name="Read back SRAM — verify write",
                target_cfg=hw.SWD_TARGET_CFG,
                address=hw.STM32F1_SRAM_SCRATCH_ADDR,
                length=2,
                width=32,
                expected="deadbeef",
            ),

            # ── 8. flash_image ───────────────────────────────────────
            waveshare.swd.flash_image(
                name="Flash Blinky firmware",
                image=fw,
                target_cfg=hw.SWD_TARGET_CFG,
                verify=True,
                erase=True,
                reset_after=False,
            ),

            # ── 9. flash_verify ──────────────────────────────────────
            waveshare.swd.flash_verify(
                name="Verify flash contents",
                image=fw,
                target_cfg=hw.SWD_TARGET_CFG,
            ),

            # ── 10. run_target_command ───────────────────────────────
            waveshare.swd.run_target_command(
                name="Run target command — read CPU registers",
                target_cfg=hw.SWD_TARGET_CFG,
                commands=["halt", "reg"],
                expected_output="xpsr",
            ),
        ]

    def teardown(self):
        """Teardown: Hardware-reset the target via TRST (GPIO5).

        The CH347 TRST pin is GPIO5 (Pin9), wired to the Blue Pill's
        NRST.  Pulsing it low via the GPIO DLL directly bypasses
        OpenOCD entirely — no transport or init needed.
        """
        hw = get_hwconfig()

        return [
            # Assert TRST (drive GPIO5 low → NRST low)
            waveshare.gpio.set_pin(
                name="Assert TRST (GPIO5 LOW → NRST LOW)",
                dev_index=hw.CH347_DEV_INDEX,
                pin=hw.CH347_TRST_PIN,
                direction=1,
                level=0,
            ),
            # Deassert TRST (drive GPIO5 high → NRST released)
            waveshare.gpio.set_pin(
                name="Deassert TRST (GPIO5 HIGH → NRST released)",
                dev_index=hw.CH347_DEV_INDEX,
                pin=hw.CH347_TRST_PIN,
                direction=1,
                level=1,
            ),
        ]


def main():
    test_instance = tc_waveshare_stm32_swd()
    return run_test_with_teardown(
        test_class_instance=test_instance,
        test_name="tc_waveshare_stm32_swd",
        reports_dir="report_tc_waveshare_stm32_swd",
    )


if __name__ == "__main__":
    sys.exit(main())
