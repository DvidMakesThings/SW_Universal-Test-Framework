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
from UTFW.tools import generate_test_report as REPORT_HELPER

# Use the universal logger so helpers (pcapgen/pcap_analyze/etc.) can emit details
from .logger import (
    create_logger,
    set_active_logger,
    get_active_logger,
    LogConfig,
    UniversalLogger,
)

# ------------------------ Active reporter hook (local helper) ------------------------

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

    Provides timestamped logging with convenience methods for:
    - Serial TX/RX with printable preview and optional hex dump
    - Serial open/close events
    - Subprocess invocation logging (command, rc, stdout/stderr)
    - SNMP GET/SET logging
    - Standard PASS/FAIL/INFO/WARN/ERROR/DEBUG lines

    Internally delegates all I/O to the universal logger, and registers it
    as the active logger so helper modules can call get_active_logger().log(...)
    and get_active_logger().subprocess(...).
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
        session_id: Optional[str] = None,
    ):
        self.test_name = test_name
        self.session_id = session_id

        base_reports = Path(reports_dir) if reports_dir else (_find_testcases_root() / "Reports")
        self.reports_dir = base_reports
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        self.log_file = self.reports_dir / f"{test_name}_results.log"

        # Create the universal logger and register globally
        self._ulog: UniversalLogger = create_logger(
            name=test_name,
            log_file=self.log_file,
            config=LogConfig(
                rx_preview_max=rx_preview_max,
                tx_preview_max=tx_preview_max,
                hex_dump=hex_dump,
                hex_width=hex_width,
                console_output=True,
                file_output=True,
            ),
        )
        set_active_logger(self._ulog)

        self.rx_preview_max = int(rx_preview_max)
        self.tx_preview_max = int(tx_preview_max)
        self.hex_dump_enabled = bool(hex_dump)
        self.hex_width = int(hex_width)

        self.test_start_time: Optional[str] = None
        self.test_end_time: Optional[str] = None

    # ------------------------ core IO ------------------------

    def _write_line(self, message: str) -> None:
        # Preserve original formatting (no extra [INFO]) by writing a raw line via the universal logger
        self._ulog._write_line(message)  # internal call is OK inside the framework

    def close(self) -> None:
        """Close the log file handle."""
        try:
            self._ulog.close()
        except Exception:
            pass

    # ------------------------ formatting ------------------------

    @staticmethod
    def _printable_preview(data: Union[bytes, str], max_len: int) -> str:
        """Return a sanitized, human-readable preview of bytes or text."""
        if isinstance(data, bytes):
            text = data.decode("utf-8", errors="replace")
        else:
            text = data
        text = text.replace("\r", "\\r").replace("\t", "\\t")
        text = text.replace("\n", "\\n\n")
        if len(text) > max_len:
            return text[:max_len] + f"... [truncated {len(text) - max_len} chars]"
        return text

    def _hexdump(self, b: bytes) -> str:
        """Return a classic hex+ASCII dump for bytes."""
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

    def _cleanup_old_pcap_files(self) -> None:
        """Delete all PCAP files in the reports directory from previous test runs."""
        import glob
        pcap_pattern = str(self.reports_dir / "*.pcap")
        for pcap_file in glob.glob(pcap_pattern):
            try:
                import os
                os.remove(pcap_file)
                self._ulog.info(f"Cleaned up old PCAP file: {pcap_file}")
            except Exception as e:
                self._ulog.warn(f"Failed to clean up PCAP file {pcap_file}: {e}")

    def log_test_start(self, test_name: str) -> None:
        """Mark test suite start in the log."""
        self.test_start_time = _now_ts()
        # Preserve exact header format used across the framework:
        self._ulog._write_line(f"===== {test_name}: START =====")
        # Log the session ID for traceability
        if self.session_id:
            self._ulog.info(f"Test Session ID: {self.session_id}")

        # Clean up old PCAP files from previous test runs
        self._cleanup_old_pcap_files()

    def log_test_end(self, test_name: str, result: str) -> None:
        """Mark test suite end in the log."""
        self.test_end_time = _now_ts()
        self._ulog._write_line(f"===== {test_name}: RESULT: {result} =====")

    def log_step_start(self, step_id: str, description: str, negative_test: bool = False) -> None:
        """Log test step start line."""
        # Use the universal logger's standardized step format
        if negative_test:
            self._ulog.step_start(step_id, f"[NEGATIVE TEST] {description}")
        else:
            self._ulog.step_start(step_id, description)

    def log_step_end(self, step_id: str) -> None:
        """Optional step end marker (not timed)."""
        # Reserved for future timing if needed
        pass

    # ------------------------ standard levels ------------------------

    def log_pass(self, message: str) -> None:
        """Log a PASS result line."""
        self._ulog.pass_(message)

    def log_fail(self, message: str) -> None:
        """Log a FAIL result line."""
        self._ulog.fail(message)

    def log_info(self, message: str) -> None:
        """Log an INFO line."""
        self._ulog.info(message)

    def log_warn(self, message: str) -> None:
        """Log a WARN line."""
        self._ulog.warn(message)

    def log_error(self, message: str) -> None:
        """Log an ERROR line."""
        self._ulog.error(message)

    def log_debug(self, message: str) -> None:
        """Log a DEBUG line."""
        self._ulog.debug(message)

    # ------------------------ compatibility for helper modules ------------------------
    # These delegate to the universal logger (which already defines them)

    def log(self, message: str, tag: Optional[str] = None) -> None:
        """Generic detail logger expected by helper modules."""
        # Tag is handled at message level in universal logger if needed; we just pass through
        self._ulog.log(message)

    def subprocess(
        self,
        cmd: Union[str, List[str]],
        returncode: int,
        stdout: str,
        stderr: str,
        tag: str = "SUBPROC",
    ) -> None:
        """Forward subprocess logging to the universal logger."""
        self._ulog.subprocess(cmd, returncode, stdout, stderr, tag=tag)

    # ------------------------ subprocess helpers (detailed) ------------------------

    def log_subprocess(
        self,
        cmd: Union[str, List[str]],
        returncode: int,
        stdout: str,
        stderr: str,
        tag: str = "SUBPROC",
    ) -> None:
        """Log a subprocess invocation result."""
        self._ulog.subprocess(cmd, returncode, stdout, stderr, tag=tag)

    # ------------------------ reports ------------------------

    def generate_reports(self) -> Dict[str, Path]:
        """Generate HTML and JUnit XML reports using the optional helper."""
        # Ensure file is flushed/closed before parsing
        self.close()
        reports: Dict[str, Path] = {}
        try:
            if REPORT_HELPER:
                model = REPORT_HELPER.parse_log(self.log_file)
                # Add session ID to the model
                if self.session_id:
                    model.session_id = self.session_id
                # Pass negative test info to report generator
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
    """Return a shell-friendly representation of a string for logging only."""
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
        # Make it globally visible so Serial/SNMP/etc. can log details via reporter if needed
        set_active_reporter(self.reporter)
        # Active universal logger is already set by TestReporter.__init__()

    def _auto_add_step(self, func: Callable) -> TestStep:
        """Create a TestStep with a readable title derived from the function name."""
        self.current_step += 1
        func_name = getattr(func, "__name__", f"Test Function {self.current_step}")
        readable_name = func_name.replace("_", " ").replace("test ", "").title()
        step = TestStep(name=readable_name, step_number=f"STEP {self.current_step}")
        self.test_steps.append(step)
        return step

    def execute_step(self, step: TestStep, func: Callable, *args, **kwargs) -> Any:
        """Execute a test step with automatic logging and sub-steps support."""
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
        """Run all test methods on a test class instance."""
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
            self.reporter.log_test_end(self.test_name, self.overall_result)
        return self.overall_result

    def generate_reports(self) -> Dict[str, Path]:
        """Generate HTML and JUnit XML reports using the optional helper."""
        return self.reporter.generate_reports()

    def cleanup(self) -> None:
        """Close the reporter and release resources."""
        try:
            self.reporter.close()
        finally:
            # Clear global reporters
            set_active_reporter(None)
            set_active_logger(None)


def run_test_with_teardown(test_class_instance, test_name: str, reports_dir: Optional[str] = None) -> int:
    """Universal test runner with automatic teardown.

    Creates a TestFramework, runs the provided test_class_instance, generates
    reports, and returns 0 for PASS or 1 for FAIL.

    Args:
        test_class_instance: Test class instance with setup() method
        test_name: Test name for reports
        reports_dir: Reports directory name relative to test script location.
                     Can be overridden by test suite via UTFW_SUITE_REPORTS_DIR environment variable.
                     If None, defaults to "report_{test_name}".
    """
    import os
    import inspect
    from pathlib import Path

    # Check if running as part of a test suite with -r argument
    suite_reports_base = os.environ.get('UTFW_SUITE_REPORTS_DIR')
    if suite_reports_base:
        # Suite runner specified a reports directory - use it as absolute path
        final_reports_dir = str(Path(suite_reports_base) / f"report_{test_name}")
    else:
        # Not in suite mode - make reports_dir relative to the test script's location
        # Get the caller's file path (the test script that called run_test_with_teardown)
        caller_frame = inspect.stack()[1]
        caller_file = caller_frame.filename
        test_script_dir = Path(caller_file).parent

        if reports_dir is None:
            # No explicit reports_dir - use default
            final_reports_dir = str(test_script_dir / f"report_{test_name}")
        else:
            # Use provided reports_dir relative to test script location
            final_reports_dir = str(test_script_dir / reports_dir)

    # Make reports directory available to test code via get_reports_dir()
    from .utilities import set_reports_dir
    set_reports_dir(final_reports_dir)

    framework = TestFramework(test_name, final_reports_dir)
    try:
        result = framework.run_test_class(test_class_instance)
        framework.generate_reports()
        return 0 if result == "PASS" else 1
    finally:
        framework.cleanup()
