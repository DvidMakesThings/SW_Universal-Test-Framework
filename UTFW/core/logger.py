"""
UTFW Universal Logger Module
============================

A comprehensive logging system that provides structured, timestamped logging
with support for various log levels, serial communication logging, subprocess
logging, SNMP operations, and test reporting integration.

This logger is designed to be universal across all UTFW modules and provides:
- Multiple log levels (DEBUG, INFO, WARN, ERROR, PASS, FAIL)
- Serial TX/RX logging with hex dumps and printable previews
- Subprocess execution logging
- SNMP operation logging
- File and console output
- Configurable formatting and output options
- Thread-safe operations

Author: DvidMakesThings
"""

import time
import sys
import os
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List, Union, TextIO
from dataclasses import dataclass
from enum import Enum


class LogLevel(Enum):
    """Enumeration of available log levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    PASS = "PASS"
    FAIL = "FAIL"
    STEP = "STEP"
    RESULT = "RESULT"


@dataclass
class LogConfig:
    """Configuration class for logger settings.
    
    Attributes:
        rx_preview_max (int): Maximum characters shown from RX text preview.
        tx_preview_max (int): Maximum characters shown from TX text preview.
        hex_dump (bool): If True, also log a formatted hex dump for TX/RX payloads.
        hex_width (int): Number of bytes per row in the hex dump.
        console_output (bool): Enable/disable console output.
        file_output (bool): Enable/disable file output.
        timestamp_format (str): Format string for timestamps.
    """
    rx_preview_max: int = 2048
    tx_preview_max: int = 1024
    hex_dump: bool = True
    hex_width: int = 16
    console_output: bool = True
    file_output: bool = True
    timestamp_format: str = "%Y-%m-%d %H:%M:%S"


class UniversalLogger:
    """Universal logger for the UTFW framework.
    
    This logger provides comprehensive logging capabilities for all UTFW modules
    including serial communication, SNMP operations, subprocess execution, and
    general test logging. It supports both file and console output with
    configurable formatting options.
    
    The logger is thread-safe and can be used across multiple modules
    simultaneously. It maintains a global instance that can be accessed
    by all framework components.
    
    Args:
        name (str): Logger instance name (typically test name).
        log_file (Optional[Path]): Path to log file. If None, no file logging.
        config (Optional[LogConfig]): Logger configuration. Uses defaults if None.
    
    Example:
        >>> logger = UniversalLogger("test_serial", Path("test.log"))
        >>> logger.info("Starting test")
        >>> logger.serial_tx(b"HELP\\r\\n")
        >>> logger.serial_rx(b"Available commands...")
        >>> logger.pass_("Test completed successfully")
    """
    
    def __init__(self, name: str, log_file: Optional[Path] = None, 
                 config: Optional[LogConfig] = None):
        self.name = name
        self.config = config or LogConfig()
        self.log_file = log_file
        self._file_handle: Optional[TextIO] = None
        self._lock = threading.Lock()
        
        # Open file handle if file logging is enabled
        if self.config.file_output and self.log_file:
            self._open_file()
    
    def _open_file(self) -> None:
        """Open the log file for writing.
        
        Creates parent directories if they don't exist and opens the file
        in write mode with UTF-8 encoding.
        
        Raises:
            IOError: If the file cannot be opened for writing.
        """
        if not self.log_file:
            return
            
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            self._file_handle = open(self.log_file, "w", encoding="utf-8")
        except Exception as e:
            print(f"Warning: Could not open log file {self.log_file}: {e}", file=sys.stderr)
            self._file_handle = None
    
    def _get_timestamp(self) -> str:
        """Get current timestamp formatted according to config.
        
        Returns:
            str: Formatted timestamp string.
        """
        return time.strftime(self.config.timestamp_format)
    
    def _write_line(self, message: str) -> None:
        """Write a timestamped line to both console and file.
        
        This method is thread-safe and handles both console and file output
        based on the logger configuration.
        
        Args:
            message (str): The message to log (without timestamp).
        """
        timestamped_line = f"[{self._get_timestamp()}] {message}"
        
        with self._lock:
            # Console output
            if self.config.console_output:
                print(timestamped_line)
            
            # File output
            if self.config.file_output and self._file_handle:
                try:
                    self._file_handle.write(timestamped_line + "\n")
                    self._file_handle.flush()
                except Exception as e:
                    print(f"Warning: Could not write to log file: {e}", file=sys.stderr)
    
    def _log(self, level: LogLevel, message: str) -> None:
        """Internal logging method with level formatting.
        
        Args:
            level (LogLevel): The log level for this message.
            message (str): The message to log.
        """
        formatted_message = f"[{level.value}] {message}"
        self._write_line(formatted_message)
    
    # ======================== Generic Log ========================

    def log(self, message: str, level: Optional[Union[str, LogLevel]] = None, tag: Optional[str] = None) -> None:
        """Generic logging entry point usable from any module.
        
        This is a convenience wrapper to ensure modules can always emit a line
        into the report without picking a specific helper. When `level` is not
        provided, INFO is used. Optional `tag` is prefixed inside the message.
        
        Args:
            message (str): The message to log.
            level (Optional[Union[str, LogLevel]]): One of LogLevel or a string
                like "debug|info|warn|error|pass|fail|step|result" (case-insensitive).
                Defaults to INFO when omitted/unknown.
            tag (Optional[str]): Extra categorization tag, e.g. "PCAPGEN", "TSHARK".
        """
        self._log(LogLevel.INFO, message)

    # ======================== Standard Log Levels ========================
    
    def debug(self, message: str) -> None:
        """Log a DEBUG level message.
        
        Debug messages are typically used for detailed diagnostic information
        that is only of interest when diagnosing problems.
        
        Args:
            message (str): The debug message to log.
        """
        self._log(LogLevel.DEBUG, message)
    
    def info(self, message: str) -> None:
        """Log an INFO level message.
        
        Info messages are used for general information about the test
        execution and normal operation flow.
        
        Args:
            message (str): The information message to log.
        """
        self._log(LogLevel.INFO, message)
    
    def warn(self, message: str) -> None:
        """Log a WARN level message.
        
        Warning messages indicate something unexpected happened, but the
        test can continue. These should be investigated but don't necessarily
        indicate test failure.
        
        Args:
            message (str): The warning message to log.
        """
        self._log(LogLevel.WARN, message)
    
    def error(self, message: str) -> None:
        """Log an ERROR level message.
        
        Error messages indicate a serious problem that prevented some
        operation from completing successfully. These typically indicate
        test failures or system issues.
        
        Args:
            message (str): The error message to log.
        """
        self._log(LogLevel.ERROR, message)
    
    def pass_(self, message: str) -> None:
        """Log a PASS result message.
        
        Pass messages indicate successful completion of a test step or
        validation. These are used for test result reporting.
        
        Args:
            message (str): The pass result message to log.
        """
        self._log(LogLevel.PASS, message)
    
    def fail(self, message: str) -> None:
        """Log a FAIL result message.
        
        Fail messages indicate unsuccessful completion of a test step or
        validation failure. These are used for test result reporting.
        
        Args:
            message (str): The fail result message to log.
        """
        self._log(LogLevel.FAIL, message)
    
    # ======================== Test Lifecycle Logging ========================
    
    def test_start(self, test_name: str) -> None:
        """Log the start of a test suite.
        
        This method should be called at the beginning of test execution
        to mark the start of the test suite in the log.
        
        Args:
            test_name (str): Name of the test suite being started.
        """
        self._write_line(f"===== {test_name}: START =====")
    
    def test_end(self, result: str) -> None:
        """Log the end of a test suite with overall result.
        
        This method should be called at the end of test execution to
        mark the completion and overall result of the test suite.
        
        Args:
            result (str): Overall test result (typically "PASS" or "FAIL").
        """
        self._write_line(f"===== RESULT: {result} =====")
    
    def step_start(self, step_id: str, description: str) -> None:
        """Log the start of a test step.
        
        This method marks the beginning of a specific test step with
        its identifier and description.
        
        Args:
            step_id (str): Unique identifier for the test step (e.g., "STEP 1").
            description (str): Human-readable description of what the step does.
        """
        self._write_line(f"[{step_id}] {description}")
    
    def step_end(self, step_id: str) -> None:
        """Log the end of a test step.
        
        This method can be used to mark the completion of a test step.
        Currently a placeholder for future timing functionality.
        
        Args:
            step_id (str): Unique identifier for the test step that ended.
        """
        # Reserved for future timing implementation
        pass
    
    # ======================== Serial Communication Logging ========================
    
    def _printable_preview(self, data: Union[bytes, str], max_len: int) -> str:
        """Return a sanitized, human-readable preview of bytes or text.
        
        This method converts binary data or text into a readable format
        by replacing control characters with their escape sequences and
        truncating if necessary.
        
        Args:
            data (Union[bytes, str]): The data to preview.
            max_len (int): Maximum length of the preview.
        
        Returns:
            str: Human-readable preview of the data.
        """
        if isinstance(data, bytes):
            text = data.decode("utf-8", errors="replace")
        else:
            text = data
        
        # Replace control characters with visible representations
        text = text.replace("\r", "\\r").replace("\t", "\\t")
        text = text.replace("\n", "\\n\n")  # Keep newlines readable
        
        if len(text) > max_len:
            return text[:max_len] + f"... [truncated {len(text) - max_len} chars]"
        return text
    
    def _hexdump(self, data: bytes) -> str:
        """Generate a formatted hex dump of binary data.
        
        Creates a classic hex dump format with offset, hex bytes, and ASCII
        representation columns.
        
        Args:
            data (bytes): Binary data to dump.
        
        Returns:
            str: Formatted hex dump string, empty if hex dumps are disabled.
        """
        if not self.config.hex_dump or not data:
            return ""
        
        lines = []
        width = self.config.hex_width
        
        for i in range(0, len(data), width):
            chunk = data[i:i + width]
            hex_part = " ".join(f"{x:02X}" for x in chunk)
            ascii_part = "".join(chr(x) if 32 <= x < 127 else "." for x in chunk)
            lines.append(f"{i:04X}: {hex_part:<{width*3-1}}  {ascii_part}")
        
        return "\n".join(lines)
    
    def serial_open(self, port: str, baud: int) -> None:
        """Log serial port open event.
        
        This method should be called when a serial port is successfully
        opened to document the connection parameters.
        
        Args:
            port (str): Serial port identifier (e.g., "COM3", "/dev/ttyUSB0").
            baud (int): Baud rate used for the connection.
        """
        self._write_line(f"[SERIAL OPEN] port={port} baud={baud}")
    
    def serial_close(self, port: str) -> None:
        """Log serial port close event.
        
        This method should be called when a serial port is closed to
        document the disconnection.
        
        Args:
            port (str): Serial port identifier that was closed.
        """
        self._write_line(f"[SERIAL CLOSE] port={port}")
    
    def serial_tx(self, data: Union[bytes, str]) -> None:
        """Log transmitted serial data with preview and optional hex dump.
        
        This method logs data sent over a serial connection, providing
        both a human-readable preview and an optional hex dump for
        detailed analysis.
        
        Args:
            data (Union[bytes, str]): Data transmitted over serial port.
        """
        if isinstance(data, str):
            data_bytes = data.encode("utf-8", errors="replace")
        else:
            data_bytes = data
        
        preview = self._printable_preview(data_bytes, self.config.tx_preview_max)
        self._write_line(f"[TX] bytes={len(data_bytes)}")
        self._write_line(preview)
        
        if self.config.hex_dump and data_bytes:
            hex_dump = self._hexdump(data_bytes)
            if hex_dump:
                self._write_line("[TX_HEX]\n" + hex_dump)
    
    def serial_rx(self, data: Union[bytes, str], note: str = "") -> None:
        """Log received serial data with preview and optional hex dump.
        
        This method logs data received from a serial connection, providing
        both a human-readable preview and an optional hex dump for
        detailed analysis.
        
        Args:
            data (Union[bytes, str]): Data received from serial port.
            note (str, optional): Additional note or context for the reception.
        """
        if isinstance(data, str):
            data_bytes = data.encode("utf-8", errors="replace")
        else:
            data_bytes = data
        
        prefix = f"[RX] {note} " if note else "[RX] "
        preview = self._printable_preview(data_bytes, self.config.rx_preview_max)
        self._write_line(f"{prefix}bytes={len(data_bytes)}")
        self._write_line(preview)
        
        if self.config.hex_dump and data_bytes:
            hex_dump = self._hexdump(data_bytes)
            if hex_dump:
                self._write_line("[RX_HEX]\n" + hex_dump)
    
    # ======================== Subprocess Logging ========================
    
    def subprocess(self, cmd: Union[str, List[str]], returncode: int, 
                  stdout: str, stderr: str, tag: str = "SUBPROC") -> None:
        """Log subprocess execution results.
        
        This method logs the complete details of a subprocess execution
        including the command, return code, and captured output streams.
        
        Args:
            cmd (Union[str, List[str]]): Command that was executed.
            returncode (int): Process return code.
            stdout (str): Captured standard output.
            stderr (str): Captured standard error.
            tag (str, optional): Tag to categorize the subprocess (default: "SUBPROC").
        """
        if isinstance(cmd, list):
            cmd_str = " ".join(self._shell_quote(x) for x in cmd)
        else:
            cmd_str = cmd
        
        self._write_line(f"[{tag}] cmd={cmd_str}")
        self._write_line(f"[{tag}] rc={returncode}")
        
        if stdout:
            truncated_stdout = stdout if len(stdout) <= 4000 else (
                stdout[:4000] + f"... [truncated {len(stdout)-4000} chars]"
            )
            self._write_line(f"[{tag} OUT]\n{truncated_stdout}")
        
        if stderr:
            truncated_stderr = stderr if len(stderr) <= 4000 else (
                stderr[:4000] + f"... [truncated {len(stderr)-4000} chars]"
            )
            self._write_line(f"[{tag} ERR]\n{truncated_stderr}")
    
    def _shell_quote(self, s: str) -> str:
        """Quote a string for safe shell representation in logs.
        
        This method provides shell-safe quoting for logging purposes only.
        It handles both Windows and POSIX-style quoting.
        
        Args:
            s (str): String to quote.
        
        Returns:
            str: Shell-quoted string suitable for display in logs.
        """
        try:
            platform = os.name
        except Exception:
            platform = "nt"
        
        if platform == "nt":  # Windows
            if (' ' in s) or ('"' in s):
                return '"' + s.replace('"', '\\"') + '"'
            return s
        else:  # POSIX
            try:
                import shlex
                return shlex.quote(s)
            except Exception:
                if "'" not in s:
                    return "'" + s + "'"
                return "'" + s.replace("'", "'\"'\"'") + "'"
    
    # ======================== SNMP Operation Logging ========================
    
    def snmp_get(self, ip: str, oid: str, value: Optional[str], note: str = "") -> None:
        """Log SNMP GET operation result.
        
        This method logs the details and result of an SNMP GET operation
        including the target device, OID, and retrieved value.
        
        Args:
            ip (str): IP address of the SNMP device.
            oid (str): SNMP OID that was queried.
            value (Optional[str]): Retrieved value, or None if the operation failed.
            note (str, optional): Additional context or notes about the operation.
        """
        note_part = f" ({note})" if note else ""
        value_str = "None" if value is None else repr(value)
        self._write_line(f"[SNMP GET] {ip} {oid} -> {value_str}{note_part}")
    
    def snmp_set(self, ip: str, oid: str, value: Union[int, str], 
                success: bool, note: str = "") -> None:
        """Log SNMP SET operation result.
        
        This method logs the details and result of an SNMP SET operation
        including the target device, OID, value, and success status.
        
        Args:
            ip (str): IP address of the SNMP device.
            oid (str): SNMP OID that was modified.
            value (Union[int, str]): Value that was set.
            success (bool): Whether the SET operation succeeded.
            note (str, optional): Additional context or notes about the operation.
        """
        note_part = f" ({note})" if note else ""
        status = "OK" if success else "FAIL"
        self._write_line(f"[SNMP SET] {ip} {oid} = {value!r} -> {status}{note_part}")
    
    # ======================== Resource Management ========================
    
    def close(self) -> None:
        """Close the logger and release resources.
        
        This method should be called when the logger is no longer needed
        to ensure proper cleanup of file handles and other resources.
        """
        with self._lock:
            if self._file_handle:
                try:
                    self._file_handle.close()
                except Exception:
                    pass
                finally:
                    self._file_handle = None
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with automatic cleanup."""
        self.close()


# ======================== Global Logger Management ========================

_ACTIVE_LOGGER: Optional[UniversalLogger] = None
_LOGGER_LOCK = threading.Lock()


def set_active_logger(logger: Optional[UniversalLogger]) -> None:
    """Set the active logger instance for global access.
    
    This function allows modules throughout the framework to access
    a shared logger instance without explicit passing.
    
    Args:
        logger (Optional[UniversalLogger]): Logger instance to set as active,
            or None to clear the active logger.
    """
    global _ACTIVE_LOGGER
    with _LOGGER_LOCK:
        _ACTIVE_LOGGER = logger


def get_active_logger() -> Optional[UniversalLogger]:
    """Get the currently active logger instance.
    
    This function provides access to the globally active logger instance
    that can be used by any module in the framework.
    
    Returns:
        Optional[UniversalLogger]: The active logger instance, or None if
            no logger is currently active.
    """
    with _LOGGER_LOCK:
        return _ACTIVE_LOGGER


def create_logger(name: str, log_file: Optional[Path] = None, 
                 config: Optional[LogConfig] = None) -> UniversalLogger:
    """Create a new logger instance with the specified configuration.
    
    This is a convenience function for creating logger instances with
    common configurations.
    
    Args:
        name (str): Name for the logger instance.
        log_file (Optional[Path]): Path to the log file, or None for console-only.
        config (Optional[LogConfig]): Logger configuration, or None for defaults.
    
    Returns:
        UniversalLogger: Configured logger instance.
    
    Example:
        >>> logger = create_logger("test_snmp", Path("snmp_test.log"))
        >>> set_active_logger(logger)
        >>> logger.info("Test started")
    """
    return UniversalLogger(name, log_file, config)