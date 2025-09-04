# reporting.py
"""
Test Reporting System

Author: DvidMakesThings
"""

import time
import sys
import os
import inspect
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable, Union

# Import TestStep from core module
from .core import TestStep
from .substep import SubStepExecutor
from UTFW import REPORT_HELPER


# ------------------------ Active reporter hook (added) ------------------------

_ACTIVE_REPORTER: Optional["TestReporter"] = None

def set_active_reporter(reporter: Optional["TestReporter"]) -> None:
    """Set the active TestReporter so other modules (Serial/SNMP/Network) can log."""
    global _ACTIVE_REPORTER
    _ACTIVE_REPORTER = reporter

def get_active_reporter() -> Optional["TestReporter"]:
    """Get the active TestReporter if set."""
    return _ACTIVE_REPORTER


def _find_testcases_root() -> Path:
    """Return nearest 'TestCases' directory based on call stack or CWD.

    Walks the call stack frames and their parents to locate a folder named
    'TestCases'. If none is found, searches upward from the current working
    directory. Falls back to CWD if not found.

    Returns:
        Absolute Path to the detected 'TestCases' directory (or CWD fallback).
    """
    for frame in inspect.stack():
        try:
            p = Path(frame.filename).resolve()
        except Exception:
            continue
        for anc in (p, *p.parents):
            if anc.name.lower() == "testcases":
                return anc
    cwd = Path.cwd().resolve()
    for anc in (cwd, *cwd.parents):
        if anc.name.lower() == "testcases":
            return anc
    return cwd


def _now_ts() -> str:
    """Return current timestamp in '%Y-%m-%d %H:%M:%S' format."""
    return time.strftime("%Y-%m-%d %H:%M:%S")


class TestReporter:
    """Structured test logger with detailed helpers.

    Provides timestamped logging to file and stdout with convenience methods for:
    - Serial TX/RX with printable preview and optional hex dump
    - Serial open/close events
    - Subprocess invocation logging (command, rc, stdout/stderr)
    - SNMP GET/SET logging
    - Standard PASS/FAIL/INFO/WARN/ERROR/DEBUG lines

    Args:
        test_name: Logical test suite name used for filenames and folder name.
        reports_dir: Optional base directory for reports. If None, uses
            '<TestCases>/Reports/<test_name>/'. If provided, final path becomes
            '<reports_dir>/<test_name>/'.
        rx_preview_max: Maximum characters shown from RX text preview.
        tx_preview_max: Maximum characters shown from TX text preview.
        hex_dump: If True, also log a formatted hex dump for TX/RX payloads.
        hex_width: Number of bytes per row in the hex dump.
    """

    def __init__(
        self,
        test_name: str,
        reports_dir: Optional[str] = None,
        *,
        rx_preview_max: int = 2048,
        tx_preview_max: int = 1024,
        hex_dump: bool = True,
        hex_width: int = 16,
    ):
        self.test_name = test_name

        base_reports = Path(reports_dir) if reports_dir else (_find_testcases_root() / "Reports")
        self.reports_dir = base_reports / test_name
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        self.log_file = self.reports_dir / f"{test_name}_results.log"
        self._fh = open(self.log_file, "w", encoding="utf-8")

        self.rx_preview_max = int(rx_preview_max)
        self.tx_preview_max = int(tx_preview_max)
        self.hex_dump_enabled = bool(hex_dump)
        self.hex_width = int(hex_width)

        self.test_start_time: Optional[str] = None
        self.test_end_time: Optional[str] = None

    # ------------------------ core IO ------------------------

    def _write_line(self, message: str) -> None:
        line = f"[{_now_ts()}] {message}"
        print(line)
        try:
            self._fh.write(line + "\n")
            self._fh.flush()
        except Exception:
            pass

    def close(self) -> None:
        """Close the log file handle."""
        try:
            if self._fh:
                self._fh.close()
        except Exception:
            pass

    # ------------------------ formatting ------------------------

    @staticmethod
    def _printable_preview(data: Union[bytes, str], max_len: int) -> str:
        """Return a sanitized, human-readable preview of bytes or text.

        Args:
            data: Bytes or string to preview.
            max_len: Maximum characters to include in the preview.

        Returns:
            Preview string with CR/LF/TAB visualized and truncated if needed.
        """
        if isinstance(data, bytes):
            text = data.decode("utf-8", errors="replace")
        else:
            text = data
        text = text.replace("\r", "\\r").replace("\t", "\\t")
        # Visualize newlines but keep readable
        text = text.replace("\n", "\\n\n")
        if len(text) > max_len:
            return text[:max_len] + f"... [truncated {len(text) - max_len} chars]"
        return text

    def _hexdump(self, b: bytes) -> str:
        """Return a classic hex+ASCII dump for bytes.

        Args:
            b: Byte buffer.

        Returns:
            Multiline string with offset, hex, and ASCII columns.
        """
        if not self.hex_dump_enabled or not b:
            return ""
        out = []
        w = self.hex_width
        for i in range(0, len(b), w):
            chunk = b[i : i + w]
            hexp = " ".join(f"{x:02X}" for x in chunk)
            asci = "".join(chr(x) if 32 <= x < 127 else "." for x in chunk)
            out.append(f"{i:04X}: {hexp:<{w*3-1}}  {asci}")
        return "\n".join(out)

    # ------------------------ test lifecycle ------------------------

    def log_test_start(self, test_name: str) -> None:
        """Mark test suite start in the log."""
        self.test_start_time = _now_ts()
        self._write_line(f"===== {test_name}: START =====")

    def log_test_end(self, result: str) -> None:
        """Mark test suite end in the log."""
        self.test_end_time = _now_ts()
        self._write_line(f"===== RESULT: {result} =====")

    def log_step_start(self, step_id: str, description: str) -> None:
        """Log test step start line."""
        self._write_line(f"[{step_id}] {description}")

    def log_step_end(self, step_id: str) -> None:
        """Optional step end marker (not timed)."""
        # Reserved for future timing if needed
        pass

    # ------------------------ standard levels ------------------------

    def log_pass(self, message: str) -> None:
        """Log a PASS result line."""
        self._write_line(f"[PASS] {message}")

    def log_fail(self, message: str) -> None:
        """Log a FAIL result line."""
        self._write_line(f"[FAIL] {message}")

    def log_info(self, message: str) -> None:
        """Log an INFO line."""
        self._write_line(f"[INFO] {message}")

    def log_warn(self, message: str) -> None:
        """Log a WARN line."""
        self._write_line(f"[WARN] {message}")

    def log_error(self, message: str) -> None:
        """Log an ERROR line."""
        self._write_line(f"[ERROR] {message}")

    def log_debug(self, message: str) -> None:
        """Log a DEBUG line."""
        self._write_line(f"[DEBUG] {message}")

    # ------------------------ serial helpers ------------------------

    def log_serial_open(self, port: str, baud: int) -> None:
        """Log serial port open event."""
        self._write_line(f"[SERIAL OPEN] port={port} baud={baud}")

    def log_serial_close(self, port: str) -> None:
        """Log serial port close event."""
        self._write_line(f"[SERIAL CLOSE] port={port}")

    def log_serial_tx(self, data: Union[bytes, str]) -> None:
        """Log TX payload with preview and optional hex dump.

        Args:
            data: Bytes or text sent to serial port.
        """
        if isinstance(data, str):
            b = data.encode("utf-8", errors="replace")
        else:
            b = data
        preview = self._printable_preview(b, self.tx_preview_max)
        self._write_line(f"[TX] bytes={len(b)}")
        self._write_line(preview)
        if self.hex_dump_enabled and b:
            self._write_line("[TX_HEX]\n" + self._hexdump(b))

    def log_serial_rx(self, data: Union[bytes, str], note: str = "") -> None:
        """Log RX payload with preview and optional hex dump.

        Args:
            data: Bytes or text received from serial port.
            note: Optional tag (e.g., 'reconnect').
        """
        if isinstance(data, str):
            b = data.encode("utf-8", errors="replace")
        else:
            b = data
        prefix = f"[RX] {note} " if note else "[RX] "
        preview = self._printable_preview(b, self.rx_preview_max)
        self._write_line(f"{prefix}bytes={len(b)}")
        self._write_line(preview)
        if self.hex_dump_enabled and b:
            self._write_line("[RX_HEX]\n" + self._hexdump(b))

    # ------------------------ subprocess helpers ------------------------

    def log_subprocess(
        self,
        cmd: Union[str, List[str]],
        returncode: int,
        stdout: str,
        stderr: str,
        tag: str = "SUBPROC",
    ) -> None:
        """Log a subprocess invocation result.

        Args:
            cmd: Executed command (string or argv list).
            returncode: Process return code.
            stdout: Captured standard output.
            stderr: Captured standard error.
            tag: Optional tag label (e.g., 'PING').
        """
        if isinstance(cmd, list):
            cmd_str = " ".join(_shell_quote(x) for x in cmd)
        else:
            cmd_str = cmd
        self._write_line(f"[{tag}] cmd={cmd_str}")
        self._write_line(f"[{tag}] rc={returncode}")
        if stdout:
            o = stdout if len(stdout) <= 4000 else (stdout[:4000] + f"... [truncated {len(stdout)-4000} chars]")
            self._write_line(f"[{tag} OUT]\n{o}")
        if stderr:
            e = stderr if len(stderr) <= 4000 else (stderr[:4000] + f"... [truncated {len(stderr)-4000} chars]")
            self._write_line(f"[{tag} ERR]\n{e}")

    # ------------------------ SNMP helpers ------------------------

    def log_snmp_get(self, ip: str, oid: str, value: Optional[str], note: str = "") -> None:
        """Log SNMP GET outcome."""
        more = f" ({note})" if note else ""
        val = "None" if value is None else repr(value)
        self._write_line(f"[SNMP GET] {ip} {oid} -> {val}{more}")

    def log_snmp_set(self, ip: str, oid: str, value: Union[int, str], ok: bool, note: str = "") -> None:
        """Log SNMP SET outcome."""
        more = f" ({note})" if note else ""
        self._write_line(f"[SNMP SET] {ip} {oid} = {value!r} -> {'OK' if ok else 'FAIL'}{more}")

    # ------------------------ reports ------------------------

    def generate_reports(self) -> Dict[str, Path]:
        """Generate HTML and JUnit XML reports using the optional helper.

        Returns:
            Mapping with 'html' and/or 'junit' report file paths if generated.
        """
        self.close()  # ensure file is flushed and closed
        reports: Dict[str, Path] = {}
        try:
            if REPORT_HELPER:
                model = REPORT_HELPER.parse_log(self.log_file)
                html_path = self.reports_dir / f"{self.test_name}_report.html"
                REPORT_HELPER.render_html(model, html_path)
                reports["html"] = html_path

                xml_path = self.reports_dir / f"{self.test_name}_report.xml"
                REPORT_HELPER.render_junit_xml(model, xml_path)
                reports["junit"] = xml_path

                print(f"[INFO] HTML test report generated at: {html_path}")
                print(f"[INFO] JUnit test report generated at: {xml_path}")
            else:
                print("[WARN] Could not generate HTML/JUnit report automatically: helper not found")
        except Exception as e:
            print(f"[WARN] Could not generate HTML/JUnit report automatically: {e}")
        return reports


def _shell_quote(s: str) -> str:
    """Return a shell-friendly representation of a string for logging only.

    On Windows, wrap in double quotes if it contains spaces or quotes; escape
    embedded quotes with backslashes. On POSIX, use shlex.quote where available.

    Args:
        s: Raw token.

    Returns:
        Quoted token suitable for display in logs.
    """
    try:
        platform = os.name
    except Exception:
        platform = "nt"
    if platform == "nt":
        if (' ' in s) or ('"' in s):
            return '"' + s.replace('"', '\\"') + '"'
        return s
    try:
        import shlex
        return shlex.quote(s)
    except Exception:
        if "'" not in s:
            return "'" + s + "'"
        return "'" + s.replace("'", "'\"'\"'") + "'"


class TestFramework:
    """Simplified test framework with automatic execution and detailed logging.

    Manages:
      - Step auto-numbering
      - Per-step logging via TestReporter
      - Result aggregation and report generation
    """

    def __init__(self, test_name: str, reports_dir: Optional[str] = None):
        self.test_name = test_name
        self.current_step = 0
        self.test_steps: List[TestStep] = []
        self.overall_result = "UNKNOWN"

        # Create reporter (detailed)
        self.reporter = TestReporter(
            test_name=test_name,
            reports_dir=reports_dir,
            rx_preview_max=2048,
            tx_preview_max=1024,
            hex_dump=True,
            hex_width=16,
        )
        # Make it globally visible so Serial/SNMP/etc. can log details
        set_active_reporter(self.reporter)

    def _auto_add_step(self, func: Callable) -> TestStep:
        """Create a TestStep with a readable title derived from the function name."""
        self.current_step += 1
        func_name = getattr(func, "__name__", f"Test Function {self.current_step}")
        readable_name = func_name.replace("_", " ").replace("test ", "").title()
        step = TestStep(name=readable_name, step_number=f"STEP {self.current_step}")
        self.test_steps.append(step)
        return step

    def execute_step(self, step: TestStep, func: Callable, *args, **kwargs) -> Any:
        """Execute a test step with automatic logging and sub-steps support.

        Args:
            step: TestStep metadata (name/number).
            func: Callable taking a SubStepExecutor as first argument.

        Returns:
            Whatever the step function returns.

        Raises:
            Propagates exceptions from the step function.
        """
        step.start_time = _now_ts()
        self.reporter.log_step_start(step.step_number, f"{step.name}")
        try:
            sub_executor = SubStepExecutor(step.step_number, self.reporter)
            result = func(sub_executor, *args, **kwargs)
            step.status = "PASS"
            self.reporter.log_pass(f"{step.step_number} completed successfully")
            return result
        except Exception as e:
            step.status = "FAIL"
            self.reporter.log_fail(f"{step.step_number} failed: {str(e)}")
            raise
        finally:
            step.end_time = _now_ts()
            self.reporter.log_step_end(step.step_number)

    def run_test_class(self, test_class_instance) -> str:
        """Run all test methods on a test class instance.

        Discovers methods starting with 'test_' unless the instance provides
        'get_test_functions()'.
        """
        self.reporter.log_test_start(self.test_name)
        try:
            if hasattr(test_class_instance, "get_test_functions"):
                test_functions = test_class_instance.get_test_functions()
            else:
                test_functions = [
                    getattr(test_class_instance, m)
                    for m in dir(test_class_instance)
                    if m.startswith("test_") and callable(getattr(test_class_instance, m))
                ]

            for test_func in test_functions:
                step = self._auto_add_step(test_func)
                try:
                    self.execute_step(step, test_func)
                except Exception as e:
                    self.reporter.log_error(f"Test step {step.step_number} failed: {str(e)}")

            failed = [s for s in self.test_steps if s.status == "FAIL"]
            self.overall_result = "FAIL" if failed else "PASS"
        except Exception as e:
            self.overall_result = "FAIL"
            self.reporter.log_error(f"Test suite failed: {str(e)}")
        finally:
            self.reporter.log_test_end(self.overall_result)
        return self.overall_result

    def generate_reports(self) -> Dict[str, Path]:
        """Generate HTML and JUnit XML reports using the optional helper."""
        return self.reporter.generate_reports()

    def cleanup(self) -> None:
        """Close the reporter and release resources."""
        try:
            self.reporter.close()
        finally:
            # Clear global reporter
            set_active_reporter(None)


def run_test_with_teardown(test_class_instance, test_name: str, reports_dir: Optional[str] = None) -> int:
    """Universal test runner with automatic teardown.

    Creates a TestFramework, runs the provided test_class_instance, generates
    reports, and returns 0 for PASS or 1 for FAIL.

    Args:
        test_class_instance: Test class instance with 'test_*' methods or
            'get_test_functions()' method.
        test_name: Logical test suite name used for folder/file naming.
        reports_dir: Optional custom base directory for reports. If omitted,
            uses '<TestCases>/Reports/<test_name>/'.

    Returns:
        0 if test suite PASS, otherwise 1.
    """
    framework = TestFramework(test_name, reports_dir)
    try:
        result = framework.run_test_class(test_class_instance)
        framework.generate_reports()
        return 0 if result == "PASS" else 1
    finally:
        framework.cleanup()
