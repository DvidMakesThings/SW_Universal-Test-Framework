#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UTFW FX2 Logic Analyzer Module
==============================

This module provides test functions and TestAction factories for using
an FX2-based logic analyzer with sigrok/DSView/PulseView to capture
UART, I2C, SPI, and generic logic signals for validation.

All subprocesses and captured output integrate with the UTFW logging
system to provide detailed command execution and signal decode logging.

Author: DvidMakesThings
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from ...core.logger import get_active_logger
from ...core.utilities import sanitize_filename
from ...core.core import TestAction


class FX2TestError(Exception):
    """Exception raised for FX2 logic analyzer errors."""


# ======================== Internal Helpers ========================

def _ensure_reports_dir() -> Path:
    """
    Determine the framework's active Reports/<test_name> directory from the logger.

    Returns:
        Path: Directory where outputs should be stored by default.

    Raises:
        FX2TestError: If no active logger or no log file is present.
    """
    logger = get_active_logger()
    if not logger or not getattr(logger, "log_file", None):
        raise FX2TestError("Active logger not set or no log file. Initialize TestFramework first.")
    return Path(logger.log_file).parent


def _run_sigrok(cmd: List[str], cwd: Optional[str] = None) -> Tuple[int, str, str]:
    """Run a sigrok-related subprocess with logging."""
    logger = get_active_logger()
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, text=True)
        out, err = proc.communicate()
        rc = proc.returncode
    except Exception as e:
        raise FX2TestError(f"Failed to run command {cmd}: {e}")

    if logger:
        logger.subprocess(cmd, rc, out, err, tag="SIGROK")

    return rc, out, err


def _normalize_hex(s: str) -> str:
    """Normalize hex string spacing/casing."""
    return " ".join(x.upper() for x in s.strip().split())


# ======================== UART ========================

def capture_uart_and_check(
    name: str,
    duration_s: float,
    baud: int,
    expected: Optional[str] = None,
    match_mode: str = "contains",
    fmt: str = "ascii",
    hex_strip_00: bool = True,
        negative_test: bool = False
) -> TestAction:
    """
    Capture UART traffic via FX2 and validate.
    """

    def execute():
        logger = get_active_logger()
        tmpdir = tempfile.mkdtemp(prefix="fx2_uart_")
        outfile = Path(tmpdir) / "uart.sr"

        cmd = [
            "sigrok-cli",
            "-d", "fx2lafw",
            "-C", "D0=rx",
            "-p", f"rx_baudrate={baud}",
            "-o", str(outfile),
            "-O", "sr"
        ]
        rc, out, err = _run_sigrok(cmd)
        if rc != 0:
            raise FX2TestError(f"sigrok-cli failed: {err}")

        decode_cmd = [
            "sigrok-cli",
            "-i", str(outfile),
            "-P", f"uart:baudrate={baud}"
        ]
        rc, out, err = _run_sigrok(decode_cmd)
        if rc != 0:
            fallback = decode_cmd[:-1]  # drop -P
            rc, out, err = _run_sigrok(fallback)
            if rc != 0:
                raise FX2TestError(f"UART decode failed: {err}")
            if logger:
                logger.info("UART decode re-run without '-A' due to previous error.")
                logger.subprocess(fallback, rc, out, err, tag="SIGROK-UART")

        ascii_joined = "".join(line for line in out.splitlines() if line.strip())
        hex_joined = " ".join(line.encode("utf-8").hex() for line in out.splitlines())

        if logger:
            a_prev = ascii_joined if len(ascii_joined) <= 200 else ascii_joined[:200] + f". [{len(ascii_joined)-200} more]"
            h_norm = _normalize_hex(hex_joined)
            h_prev = h_norm if len(h_norm) <= 200 else h_norm[:200] + f". [{len(h_norm)-200} more]"
            logger.info(f"[UART] Joined ASCII: {a_prev}")
            logger.info(f"[UART] Joined HEX   : {h_prev}")
            if fmt.lower() == "hex" and hex_strip_00:
                h_no00 = " ".join(b for b in h_norm.split() if b != "00")
                h_prev2 = h_no00 if len(h_no00) <= 200 else h_no00[:200] + f". [{len(h_no00)-200} more]"
                logger.info(f"[UART] HEX (drop 00): {h_prev2}")

        if expected:
            target = ascii_joined if fmt.lower() == "ascii" else hex_joined
            ok = (expected in target) if match_mode == "contains" else (expected == target)
            if not ok:
                raise FX2TestError(f"UART validation failed. Expected {expected} (mode={match_mode}) not found.")
            if logger:
                logger.info(f"[UART] Expected check PASSED (mode={match_mode}).")

        return {"ascii": ascii_joined, "hex": hex_joined}

    return TestAction(name, execute, negative_test=negative_test)


# ======================== I2C ========================

def capture_i2c_and_check(
    name: str,
    duration_s: float,
    expected: Optional[str] = None,
    match_mode: str = "contains",
        negative_test: bool = False
) -> TestAction:
    """
    Capture I2C traffic via FX2 and validate.
    """

    def execute():
        logger = get_active_logger()
        tmpdir = tempfile.mkdtemp(prefix="fx2_i2c_")
        outfile = Path(tmpdir) / "i2c.sr"

        cmd = [
            "sigrok-cli",
            "-d", "fx2lafw",
            "-C", "D0=scl,D1=sda",
            "-o", str(outfile),
            "-O", "sr"
        ]
        rc, out, err = _run_sigrok(cmd)
        if rc != 0:
            raise FX2TestError(f"sigrok-cli failed: {err}")

        decode_cmd = ["sigrok-cli", "-i", str(outfile), "-P", "i2c"]
        rc, out, err = _run_sigrok(decode_cmd)
        if rc != 0:
            fallback = decode_cmd[:-1]
            rc, out, err = _run_sigrok(fallback)
            if rc != 0:
                raise FX2TestError(f"I2C decode failed: {err}")
            if logger:
                logger.info("I2C decode re-run without '-A' due to previous error.")
                logger.subprocess(fallback, rc, out, err, tag="SIGROK-I2C")

        hex_joined = " ".join(line.encode("utf-8").hex() for line in out.splitlines())

        if logger:
            prev = hex_joined if len(hex_joined) <= 200 else hex_joined[:200] + f". [{len(hex_joined)-200} more]"
            logger.info(f"[I2C] HEX: {prev}")

        if expected:
            ok = (expected in hex_joined) if match_mode == "contains" else (expected == hex_joined)
            if not ok:
                raise FX2TestError(f"I2C validation failed. Expected {expected} (mode={match_mode}) not found.")
            if logger:
                logger.info(f"[I2C] Expected check PASSED (mode={match_mode}).")

        return {"hex": hex_joined}

    return TestAction(name, execute, negative_test=negative_test)


# ======================== SPI ========================

def capture_spi_and_check(
    name: str,
    duration_s: float,
    expected: Optional[str] = None,
    match_mode: str = "contains",
    lane: str = "mosi",
    negative_test: bool = False
) -> TestAction:
    """
    Capture SPI traffic via FX2 and validate.
    """

    def execute():
        logger = get_active_logger()
        tmpdir = tempfile.mkdtemp(prefix="fx2_spi_")
        outfile = Path(tmpdir) / "spi.sr"

        cmd = [
            "sigrok-cli",
            "-d", "fx2lafw",
            "-C", "D0=clk,D1=mosi,D2=miso,D3=cs",
            "-o", str(outfile),
            "-O", "sr"
        ]
        rc, out, err = _run_sigrok(cmd)
        if rc != 0:
            raise FX2TestError(f"sigrok-cli failed: {err}")

        decode_cmd = ["sigrok-cli", "-i", str(outfile), "-P", f"spi:{lane}"]
        rc, out, err = _run_sigrok(decode_cmd)
        if rc != 0:
            fallback = decode_cmd[:-1]
            rc, out, err = _run_sigrok(fallback)
            if rc != 0:
                raise FX2TestError(f"SPI decode failed: {err}")
            if logger:
                logger.info("SPI decode re-run without '-A' due to previous error.")
                logger.subprocess(fallback, rc, out, err, tag="SIGROK-SPI")

        hex_joined = " ".join(line.encode("utf-8").hex() for line in out.splitlines())

        if logger:
            prev = hex_joined if len(hex_joined) <= 200 else hex_joined[:200] + f". [{len(hex_joined)-200} more]"
            logger.info(f"[SPI:{lane.upper()}] HEX: {prev}")

        if expected:
            ok = (expected in hex_joined) if match_mode == "contains" else (expected == hex_joined)
            if not ok:
                raise FX2TestError(f"SPI validation failed. Expected {expected} (mode={match_mode}) not found.")
            if logger:
                logger.info(f"[SPI:{lane.upper()}] Expected check PASSED (mode={match_mode}).")

        return {"hex": hex_joined}

    return TestAction(name, execute, negative_test=negative_test)


# ======================== PulseView ========================

def launch_pulseview(name: str, project_file: Optional[str] = None,
negative_test: bool = False) -> TestAction:
    """
    Launch PulseView GUI with optional project file.
    """

    def execute():
        logger = get_active_logger()
        exe = "pulseview"
        cmd = [exe]
        if project_file:
            cmd.append(project_file)

        try:
            subprocess.Popen(cmd)
        except Exception as e:
            raise FX2TestError(f"Failed to launch PulseView: {e}")

        if logger:
            logger.info(f"PulseView resolved: {exe}")

        return True

    return TestAction(name, execute, negative_test=negative_test)


def convert_sr_to_vcd(name: str, sr_file: str, vcd_file: Optional[str] = None,
negative_test: bool = False) -> TestAction:
    """
    Convert .sr file to .vcd file using sigrok-cli.
    """

    def execute():
        logger = get_active_logger()
        if not vcd_file:
            vcd_path = str(Path(sr_file).with_suffix(".vcd"))
        else:
            vcd_path = vcd_file

        cmd = ["sigrok-cli", "-i", sr_file, "-o", vcd_path]
        rc, out, err = _run_sigrok(cmd)
        if rc != 0:
            raise FX2TestError(f"sigrok-cli conversion failed: {err}")

        if logger:
            logger.subprocess(cmd, rc, out, err, tag="SIGROK-CONV")

        return vcd_path

    return TestAction(name, execute, negative_test=negative_test)
