# failure_memory.py
"""
UTFW Failure Memory Module
===========================
Universal failure memory testing capabilities for devices with event logging systems.

This module provides comprehensive failure memory testing functionality with detailed
logging integration. It supports reading, decoding, clearing, and validating failure
memory entries from devices that implement error/warning logging systems.

The module is designed to be device-agnostic while providing specific support for
16-bit error code schemes (0xMSCC format: Module, Severity, File ID, Error ID).

Features:
    - Read ERROR and WARNING logs over UART
    - Decode 16-bit error codes with detailed information
    - Clear failure memory regions
    - Validate error/warning presence and absence
    - Generate failure events for testing
    - Comprehensive logging with hex dumps and decoded entries

TestAction Factories:
    - read_failure_log: Read and parse ERROR or WARNING logs
    - clear_failure_log: Clear ERROR or WARNING memory regions
    - verify_error_present: Verify specific error codes exist
    - verify_log_empty: Verify log is empty
    - generate_test_error: Trigger errors by sending invalid commands
    - decode_and_report: Full decode with detailed reporting

Author: DvidMakesThings
"""

import re
import time
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any, Union

from ...core.logger import get_active_logger
from ...core.core import TestAction

# Import error code decoding tables
from ._error_tables import MODULE_NAMES, SEVERITY_NAMES, FID_NAMES
from ._code_descriptions import EID_NAMES

DEBUG = False  # Set to True for debug prints

# Constants for failure memory
EVENT_LOG_BLOCK_SIZE = 0x0200  # 512 bytes per log region
FAILURE_MEM_TIMEOUT = 5.0      # Default timeout for reading dumps


class FailureMemoryError(Exception):
    """Exception raised when failure memory operations fail.
    
    This exception is raised by failure memory test functions when communication
    errors occur, validation fails, decoding errors happen, or other failure
    memory operations cannot be completed successfully.
    
    Args:
        message (str): Description of the error that occurred.
    """
    pass


# ======================== Core Helper Functions ========================

def _ensure_pyserial():
    """Ensure pyserial is installed, raise clear error if not."""
    try:
        import serial
    except ImportError:
        raise FailureMemoryError(
            "pyserial package is required for failure memory testing.\n"
            "Install with: pip install pyserial"
        )


def _format_hex_dump(data: bytes, bytes_per_line: int = 16) -> str:
    """Format binary data as a detailed hex dump with ASCII preview.
    
    Args:
        data (bytes): Binary data to format.
        bytes_per_line (int, optional): Number of bytes per line. Defaults to 16.
        
    Returns:
        str: Formatted hex dump string.
    """
    if not data:
        return "[empty]"
    
    lines = []
    for i in range(0, len(data), bytes_per_line):
        chunk = data[i:i + bytes_per_line]
        hex_part = ' '.join(f'{b:02X}' for b in chunk)
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        lines.append(f"  {i:04X}  {hex_part:<{bytes_per_line*3}}  |{ascii_part}|")
    
    return '\n'.join(lines)


def _open_serial_connection(port: str, baudrate: int, timeout: float):
    """Open a serial connection with comprehensive logging.
    
    Args:
        port (str): Serial port identifier.
        baudrate (int): Communication baud rate.
        timeout (float): Read timeout in seconds.
        
    Returns:
        Serial object: Opened serial connection.
        
    Raises:
        FailureMemoryError: If port cannot be opened.
    """
    _ensure_pyserial()
    import serial
    
    logger = get_active_logger()
    
    try:
        if logger:
            logger.info(f"[FAILMEM] Opening serial port: {port}")
            logger.info(f"[FAILMEM]   Baudrate: {baudrate}, Timeout: {timeout}s")
        
        ser = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
        
        # Clear any pending data
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        
        if logger:
            logger.info(f"[FAILMEM] Port {port} opened successfully")
            logger.info(f"[FAILMEM] Buffers cleared and ready")
        
        return ser
        
    except Exception as e:
        if logger:
            logger.error(f"[FAILMEM ERROR] Failed to open port {port}")
            logger.error(f"[FAILMEM ERROR]   Type: {type(e).__name__}")
            logger.error(f"[FAILMEM ERROR]   Message: {e}")
        raise FailureMemoryError(f"Cannot open serial port {port}: {type(e).__name__}: {e}")


def decode_error_code(code: int) -> Dict[str, Any]:
    """Decode a 16-bit error code into structured fields.
    
    Decodes error codes in the format 0xMSCC where:
    - M (bits 15..12): Module ID
    - S (bits 11..8): Severity level
    - C (bits 7..4): File ID within module
    - C (bits 3..0): Error ID within file
    
    Args:
        code (int): 16-bit error code to decode.
        
    Returns:
        Dict[str, Any]: Dictionary containing:
            - code: Original error code
            - module: Module ID (0-F)
            - module_name: Human-readable module name
            - severity: Severity level (0-F)
            - severity_name: Human-readable severity
            - fid: File ID (0-F)
            - fid_name: Human-readable file name
            - eid: Error ID (0-F)
            - description: Detailed description from EID_NAMES
    """
    logger = get_active_logger()
    
    # Extract bitfields
    module = (code >> 12) & 0xF
    severity = (code >> 8) & 0xF
    fid = (code >> 4) & 0xF
    eid = code & 0xF
    
    # Look up names
    module_name = MODULE_NAMES.get(module, f"UNKNOWN(0x{module:X})")
    severity_name = SEVERITY_NAMES.get(severity, f"0x{severity:X}")
    fid_name = FID_NAMES.get(module, {}).get(fid, f"FID 0x{fid:X}")
    
    # Look up description from EID_NAMES (includes severity in the lookup chain)
    eid_desc = EID_NAMES.get(module, {}).get(fid, {}).get(severity, {}).get(eid, "")
    description = f"{module_name}: {eid_desc}" if eid_desc else ""
    
    if logger and DEBUG:
        logger.debug(f"[FAILMEM DECODE] Code 0x{code:04X}:")
        logger.debug(f"[FAILMEM DECODE]   Module: 0x{module:X} ({module_name})")
        logger.debug(f"[FAILMEM DECODE]   Severity: 0x{severity:X} ({severity_name})")
        logger.debug(f"[FAILMEM DECODE]   File ID: 0x{fid:X} ({fid_name})")
        logger.debug(f"[FAILMEM DECODE]   Error ID: 0x{eid:X}")
        logger.debug(f"[FAILMEM DECODE]   Description: {description}")
    
    return {
        "code": code,
        "module": module,
        "module_name": module_name,
        "severity": severity,
        "severity_name": severity_name,
        "fid": fid,
        "fid_name": fid_name,
        "eid": eid,
        "description": description,
    }


def extract_eeprom_bytes_from_dump(dump_text: str) -> List[int]:
    """Extract EEPROM bytes from a dump text.
    
    Parses dump text looking for lines in format:
        0xNNNN HH HH HH ... (address followed by hex bytes)
    
    Args:
        dump_text (str): Raw dump text from device.
        
    Returns:
        List[int]: List of byte values extracted from dump.
    """
    logger = get_active_logger()
    
    if logger:
        logger.info(f"[FAILMEM] Extracting EEPROM bytes from dump")
        logger.info(f"[FAILMEM]   Dump text length: {len(dump_text)} chars")
    
    bytes_out = []
    line_count = 0
    
    for line in dump_text.splitlines():
        line = line.strip()
        if not (line.startswith("0x") or line.startswith("0X")):
            continue
        
        line_count += 1
        parts = line.split()
        # parts[0] is the address, skip it
        for token in parts[1:]:
            if re.fullmatch(r"[0-9A-Fa-f]{2}", token):
                bytes_out.append(int(token, 16))
    
    if logger:
        logger.info(f"[FAILMEM] Extraction complete:")
        logger.info(f"[FAILMEM]   Lines processed: {line_count}")
        logger.info(f"[FAILMEM]   Bytes extracted: {len(bytes_out)}")
    
    # Truncate to expected block size if needed
    if len(bytes_out) > EVENT_LOG_BLOCK_SIZE:
        if logger:
            logger.warn(f"[FAILMEM] Truncating from {len(bytes_out)} to {EVENT_LOG_BLOCK_SIZE} bytes")
        bytes_out = bytes_out[:EVENT_LOG_BLOCK_SIZE]
    
    return bytes_out


def decode_event_log_region(byte_values: List[int]) -> Tuple[int, List[int]]:
    """Decode an event log region into pointer and ordered error codes.
    
    The log region layout (from event_log.c):
        [0..1]: uint16_t write pointer (little-endian)
        [2..]: entries, 2 bytes each, BIG-endian 16-bit error codes
        
    The ring buffer is ordered from oldest to newest, with the pointer
    indicating where the next write will occur.
    
    Args:
        byte_values (List[int]): Raw bytes from EEPROM dump.
        
    Returns:
        Tuple[int, List[int]]: (pointer, ordered_codes)
            - pointer: Next write index
            - ordered_codes: List of error codes from oldest to newest,
              excluding 0xFFFF and 0x0000
    """
    logger = get_active_logger()
    
    if logger:
        logger.info(f"[FAILMEM] Decoding event log region")
        logger.info(f"[FAILMEM]   Input bytes: {len(byte_values)}")
    
    if len(byte_values) < 4:
        if logger:
            logger.warn(f"[FAILMEM] Insufficient bytes for event log (need >= 4, got {len(byte_values)})")
        return 0, []
    
    # Extract pointer (little-endian at bytes 0-1)
    ptr = byte_values[0] | (byte_values[1] << 8)
    
    if logger:
        logger.info(f"[FAILMEM] Write pointer: {ptr} (0x{ptr:04X})")
    
    # Extract error code entries (big-endian, starting at byte 2)
    entries_raw = []
    for i in range(2, len(byte_values), 2):
        if i + 1 >= len(byte_values):
            break
        hi = byte_values[i]
        lo = byte_values[i + 1]
        code = (hi << 8) | lo
        entries_raw.append(code)
    
    max_entries = len(entries_raw)
    if max_entries == 0:
        if logger:
            logger.info(f"[FAILMEM] No entries found in log region")
        return ptr, []
    
    if logger:
        logger.info(f"[FAILMEM] Raw entries: {max_entries}")
    
    # Validate pointer
    if ptr >= max_entries:
        if logger:
            logger.warn(f"[FAILMEM] Pointer {ptr} >= max_entries {max_entries}, resetting to 0")
        ptr = 0
    
    # Reorder from oldest to newest, filtering empty entries
    ordered = []
    for idx in range(max_entries):
        j = (ptr + idx) % max_entries
        code = entries_raw[j]
        if code in (0xFFFF, 0x0000):
            continue
        ordered.append(code)
    
    if logger:
        logger.info(f"[FAILMEM] Decoded {len(ordered)} valid entries (oldest→newest)")
        if ordered:
            logger.info(f"[FAILMEM] First entry: 0x{ordered[0]:04X}")
            logger.info(f"[FAILMEM] Last entry: 0x{ordered[-1]:04X}")
    
    return ptr, ordered


def read_failure_memory_uart(
    port: str,
    command: str,
    baudrate: int = 115200,
    timeout: float = FAILURE_MEM_TIMEOUT
) -> Tuple[str, List[int], int, List[int]]:
    """Read failure memory via UART and decode the contents.
    
    Sends a command (e.g., "read_error" or "read_warning") to the device,
    reads the EEPROM dump until EE_DUMP_END marker, extracts bytes, and
    decodes the event log structure.
    
    Args:
        port (str): Serial port identifier.
        command (str): Command to send (e.g., "read_error", "read_warning").
        baudrate (int, optional): Communication baud rate. Defaults to 115200.
        timeout (float, optional): Read timeout in seconds. Defaults to FAILURE_MEM_TIMEOUT.
        
    Returns:
        Tuple containing:
            - dump_text (str): Raw dump text received
            - byte_values (List[int]): Extracted byte values
            - pointer (int): Write pointer from log
            - error_codes (List[int]): Decoded error codes (oldest→newest)
            
    Raises:
        FailureMemoryError: If communication fails or dump is invalid.
    """
    logger = get_active_logger()
    
    if logger:
        logger.info(f"[FAILMEM] read_failure_memory_uart() called")
        logger.info(f"[FAILMEM]   Port: {port}, Command: '{command}'")
        logger.info(f"[FAILMEM]   Baudrate: {baudrate}, Timeout: {timeout}s")
    
    ser = _open_serial_connection(port, baudrate, timeout)
    
    try:
        # Send command
        payload = (command.strip() + "\r\n")
        cmd_bytes = payload.encode('utf-8')
        
        if logger:
            logger.info(f"[FAILMEM TX] Sending command: '{command.strip()}'")
            logger.info(f"[FAILMEM TX] Payload length: {len(cmd_bytes)} bytes")
            logger.info(f"[FAILMEM TX] Hex dump:")
            logger.info(_format_hex_dump(cmd_bytes))
        
        bytes_written = ser.write(cmd_bytes)
        ser.flush()
        
        if logger:
            logger.info(f"[FAILMEM TX] Wrote {bytes_written} bytes to port")
            logger.info(f"[FAILMEM RX] Waiting for dump data...")
        
        # Read response until EE_DUMP_END
        response_bytes = bytearray()
        start_time = time.time()
        chunk_count = 0
        found_end_marker = False
        
        while (time.time() - start_time) < timeout:
            if ser.in_waiting > 0:
                chunk = ser.read(ser.in_waiting)
                chunk_count += 1
                response_bytes.extend(chunk)
                elapsed = time.time() - start_time
                
                if logger:
                    logger.info(f"[FAILMEM RX] Chunk #{chunk_count}: {len(chunk)} bytes "
                              f"(elapsed: {elapsed:.3f}s, total: {len(response_bytes)} bytes)")
                
                # Check for end marker
                text_so_far = response_bytes.decode('utf-8', errors='ignore')
                if "EE_DUMP_END" in text_so_far:
                    found_end_marker = True
                    if logger:
                        logger.info(f"[FAILMEM RX] Found EE_DUMP_END marker, waiting 200ms for final data...")
                    time.sleep(0.2)  # Grace period for any trailing data
                    
                    # Read any remaining data
                    if ser.in_waiting > 0:
                        final_chunk = ser.read(ser.in_waiting)
                        response_bytes.extend(final_chunk)
                        if logger:
                            logger.info(f"[FAILMEM RX] Final chunk: {len(final_chunk)} bytes")
                    break
            
            time.sleep(0.01)
        
        total_time = time.time() - start_time
        
        if not found_end_marker:
            if logger:
                logger.warn(f"[FAILMEM RX] No EE_DUMP_END marker found within timeout")
        
        if logger:
            logger.info(f"[FAILMEM RX] Read complete:")
            logger.info(f"[FAILMEM RX]   Total bytes: {len(response_bytes)}")
            logger.info(f"[FAILMEM RX]   Chunks: {chunk_count}")
            logger.info(f"[FAILMEM RX]   Duration: {total_time:.3f}s")
            logger.info(f"[FAILMEM RX]   End marker found: {found_end_marker}")
        
        # Decode response
        dump_text = response_bytes.decode('utf-8', errors='ignore')
        
        if logger:
            logger.info(f"[FAILMEM RX] Decoded text length: {len(dump_text)} characters")
            # Log first 200 chars
            preview = dump_text[:200].replace("\r", "\\r").replace("\n", "\\n\n  ")
            logger.info(f"[FAILMEM RX] Text preview (first 200 chars):\n  {preview}")
        
        # Extract and decode bytes
        byte_values = extract_eeprom_bytes_from_dump(dump_text)
        
        if not byte_values:
            if logger:
                logger.warn(f"[FAILMEM] No valid EEPROM bytes extracted from dump")
            return dump_text, [], 0, []
        
        # Decode event log structure
        pointer, error_codes = decode_event_log_region(byte_values)
        
        if logger:
            logger.info(f"[FAILMEM] Final decode results:")
            logger.info(f"[FAILMEM]   Bytes extracted: {len(byte_values)}")
            logger.info(f"[FAILMEM]   Write pointer: {pointer}")
            logger.info(f"[FAILMEM]   Error codes found: {len(error_codes)}")
        
        return dump_text, byte_values, pointer, error_codes
        
    except Exception as e:
        if logger:
            logger.error(f"[FAILMEM ERROR] Exception during read:")
            logger.error(f"[FAILMEM ERROR]   Type: {type(e).__name__}")
            logger.error(f"[FAILMEM ERROR]   Message: {e}")
        raise FailureMemoryError(f"Failed to read failure memory: {type(e).__name__}: {e}")
        
    finally:
        try:
            if logger:
                logger.info(f"[FAILMEM] Closing port {port}")
            ser.close()
            if logger:
                logger.info(f"[FAILMEM] Port closed successfully")
        except Exception as e:
            if logger:
                logger.error(f"[FAILMEM ERROR] Failed to close port: {e}")


def clear_failure_memory_uart(
    port: str,
    log_type: str,
    baudrate: int = 115200,
    timeout: float = 2.0
) -> str:
    """Clear failure memory via UART.
    
    Sends a clear command (CLEAR_ERROR or CLEAR_WARNING) to the device
    and verifies the response.
    
    Args:
        port (str): Serial port identifier.
        log_type (str): Type of log to clear ("ERROR" or "WARNING").
        baudrate (int, optional): Communication baud rate. Defaults to 115200.
        timeout (float, optional): Response timeout. Defaults to 2.0.
        
    Returns:
        str: Response text from device.
        
    Raises:
        FailureMemoryError: If communication fails or clear is not acknowledged.
    """
    logger = get_active_logger()
    
    # Validate log type and construct command
    log_type = log_type.upper()
    if log_type not in ("ERROR", "WARNING"):
        raise FailureMemoryError(f"Invalid log_type '{log_type}', must be 'ERROR' or 'WARNING'")
    
    command = f"CLEAR_{log_type}"
    
    if logger:
        logger.info(f"[FAILMEM] clear_failure_memory_uart() called")
        logger.info(f"[FAILMEM]   Port: {port}, Command: '{command}'")
        logger.info(f"[FAILMEM]   Baudrate: {baudrate}, Timeout: {timeout}s")
    
    ser = _open_serial_connection(port, baudrate, timeout)
    
    try:
        # Send clear command
        payload = (command.strip() + "\r\n")
        cmd_bytes = payload.encode('utf-8')
        
        if logger:
            logger.info(f"[FAILMEM TX] Sending clear command: '{command}'")
            logger.info(f"[FAILMEM TX] Hex dump:")
            logger.info(_format_hex_dump(cmd_bytes))
        
        bytes_written = ser.write(cmd_bytes)
        ser.flush()
        
        if logger:
            logger.info(f"[FAILMEM TX] Wrote {bytes_written} bytes")
            logger.info(f"[FAILMEM RX] Waiting for response...")
        
        # Wait a moment for device to process
        time.sleep(0.1)
        
        # Read response
        response_bytes = bytearray()
        start_time = time.time()
        
        while (time.time() - start_time) < timeout:
            if ser.in_waiting > 0:
                chunk = ser.read(ser.in_waiting)
                response_bytes.extend(chunk)
                time.sleep(0.05)  # Small delay to collect all data
            else:
                if len(response_bytes) > 0:
                    # Got some data and no more coming
                    break
            time.sleep(0.01)
        
        response_text = response_bytes.decode('utf-8', errors='ignore')
        
        if logger:
            logger.info(f"[FAILMEM RX] Response received ({len(response_bytes)} bytes):")
            preview = response_text.replace("\r", "\\r").replace("\n", "\\n\n  ")
            logger.info(f"  {preview}")
        
        return response_text
        
    except Exception as e:
        if logger:
            logger.error(f"[FAILMEM ERROR] Exception during clear:")
            logger.error(f"[FAILMEM ERROR]   Type: {type(e).__name__}")
            logger.error(f"[FAILMEM ERROR]   Message: {e}")
        raise FailureMemoryError(f"Failed to clear {log_type} memory: {type(e).__name__}: {e}")
        
    finally:
        try:
            ser.close()
            if logger:
                logger.info(f"[FAILMEM] Port {port} closed")
        except Exception as e:
            if logger:
                logger.error(f"[FAILMEM ERROR] Failed to close port: {e}")


# ======================== TestAction Factories ========================

def read_failure_log(
    name: str,
    port: str,
    log_type: str = "ERROR",
    baudrate: int = 115200,
    timeout: float = FAILURE_MEM_TIMEOUT,
    negative_test: bool = False
) -> TestAction:
    """Create a TestAction that reads and decodes a failure log.
    
    This TestAction factory creates an action that reads either ERROR or WARNING
    logs from a device via UART, extracts the EEPROM dump, decodes error codes,
    and provides comprehensive logging of the process and results.
    
    The action reads the failure memory, parses the ring buffer structure,
    and returns the decoded error codes in chronological order (oldest→newest).
    
    Args:
        name (str): Human-readable name for the test step shown in reports.
        port (str): Serial port identifier (e.g., "COM3", "/dev/ttyUSB0").
        log_type (str, optional): Type of log to read ("ERROR" or "WARNING").
            Defaults to "ERROR".
        baudrate (int, optional): Serial communication baud rate. Defaults to 115200.
        timeout (float, optional): Maximum time to wait for dump in seconds.
            Defaults to FAILURE_MEM_TIMEOUT.
        negative_test (bool, optional): If True, test expects failure. Defaults to False.
        
    Returns:
        TestAction: TestAction that returns a dictionary with:
            - dump_text (str): Raw dump text
            - byte_values (List[int]): Extracted bytes
            - pointer (int): Write pointer
            - error_codes (List[int]): Decoded error codes
            - decoded (List[Dict]): Detailed decode info for each code
            
    Raises:
        FailureMemoryError: When executed, raises if read or decode fails.
        
    Example:
        >>> read_action = read_failure_log(
        ...     "Read ERROR log", "COM3", log_type="ERROR"
        ... )
        >>> result = read_action.execute()  # Returns dict with error codes
        >>> # Use in STE: STE(read_action, next_action, ...)
    """
    def execute():
        logger = get_active_logger()
        
        # Validate log type
        log_type_upper = log_type.upper()
        if log_type_upper not in ("ERROR", "WARNING"):
            raise FailureMemoryError(
                f"Invalid log_type '{log_type}', must be 'ERROR' or 'WARNING'"
            )
        
        # Construct read command
        command = f"read_{log_type.lower()}"
        
        if logger:
            logger.info(f"[FAILMEM TEST] {name}")
            logger.info(f"[FAILMEM TEST] Reading {log_type_upper} log from {port}")
        
        # Read and decode
        dump_text, byte_values, pointer, error_codes = read_failure_memory_uart(
            port, command, baudrate, timeout
        )
        
        # Decode all error codes
        decoded = [decode_error_code(code) for code in error_codes]
        
        if logger:
            logger.info(f"[FAILMEM TEST] Read complete:")
            logger.info(f"[FAILMEM TEST]   Log type: {log_type_upper}")
            logger.info(f"[FAILMEM TEST]   Entries found: {len(error_codes)}")
            logger.info(f"[FAILMEM TEST]   Write pointer: {pointer}")
            
            if error_codes:
                logger.info(f"[FAILMEM TEST] Decoded entries (oldest→newest):")
                for idx, info in enumerate(decoded):
                    desc_str = f" - {info['description']}" if info['description'] else ""
                    logger.info(
                        f"[FAILMEM TEST]   {idx+1}. 0x{info['code']:04X} - "
                        f"[{info['severity_name']}] {info['module_name']}/{info['fid_name']} "
                        f"EID=0x{info['eid']:X}{desc_str}"
                    )
            else:
                logger.info(f"[FAILMEM TEST] {log_type_upper} log is empty")
        
        return {
            "dump_text": dump_text,
            "byte_values": byte_values,
            "pointer": pointer,
            "error_codes": error_codes,
            "decoded": decoded,
        }

    metadata = {'sent': f"read_{log_type.lower()} (read {log_type.upper()} log)"}
    return TestAction(name, execute, metadata=metadata, negative_test=negative_test)


def clear_failure_log(
    name: str,
    port: str,
    log_type: str = "ERROR",
    baudrate: int = 115200,
    timeout: float = 2.0,
    negative_test: bool = False
) -> TestAction:
    """Create a TestAction that clears a failure log.
    
    This TestAction factory creates an action that sends a clear command
    (CLEAR_ERROR or CLEAR_WARNING) to the device and verifies the operation.
    
    Args:
        name (str): Human-readable name for the test step.
        port (str): Serial port identifier.
        log_type (str, optional): Type of log to clear ("ERROR" or "WARNING").
            Defaults to "ERROR".
        baudrate (int, optional): Serial communication baud rate. Defaults to 115200.
        timeout (float, optional): Response timeout in seconds. Defaults to 2.0.
        negative_test (bool, optional): If True, test expects failure. Defaults to False.
        
    Returns:
        TestAction: TestAction that returns the response text from the device.
        
    Raises:
        FailureMemoryError: When executed, raises if clear fails.
        
    Example:
        >>> clear_action = clear_failure_log(
        ...     "Clear ERROR log", "COM3", log_type="ERROR"
        ... )
        >>> clear_action.execute()  # Clears the log
    """
    def execute():
        logger = get_active_logger()
        
        log_type_upper = log_type.upper()
        
        if logger:
            logger.info(f"[FAILMEM TEST] {name}")
            logger.info(f"[FAILMEM TEST] Clearing {log_type_upper} log on {port}")
        
        response = clear_failure_memory_uart(port, log_type_upper, baudrate, timeout)
        
        if logger:
            logger.info(f"[FAILMEM TEST] Clear {log_type_upper} log complete")

        return response

    metadata = {'sent': f"CLEAR_{log_type.upper()}"}
    return TestAction(name, execute, metadata=metadata, negative_test=negative_test)


def verify_error_present(
    name: str,
    port: str,
    expected_codes: Union[int, List[int]],
    log_type: str = "ERROR",
    baudrate: int = 115200,
    timeout: float = FAILURE_MEM_TIMEOUT,
    negative_test: bool = False
) -> TestAction:
    """Create a TestAction that verifies error code(s) are present in the log.
    
    This TestAction factory creates an action that reads the failure log and
    verifies that expected error code(s) exist. Useful for validating that
    expected errors have been logged.
    
    Args:
        name (str): Human-readable name for the test step.
        port (str): Serial port identifier.
        expected_codes (Union[int, List[int]]): Single error code or list of error codes
            to look for (e.g., 0x2F13 or [0x2F13, 0x8009]).
        log_type (str, optional): Log to check ("ERROR" or "WARNING"). Defaults to "ERROR".
        baudrate (int, optional): Serial communication baud rate. Defaults to 115200.
        timeout (float, optional): Read timeout in seconds. Defaults to FAILURE_MEM_TIMEOUT.
        negative_test (bool, optional): If True, test expects failure. Defaults to False.
        
    Returns:
        TestAction: TestAction that returns True if all codes are found.
        
    Raises:
        FailureMemoryError: When executed, raises if any code is not found.
        
    Example:
        >>> # Single code
        >>> verify_action = verify_error_present(
        ...     "Verify error 0x2F13 present", "COM3",
        ...     expected_codes=0x2F13, log_type="ERROR"
        ... )
        >>> # Multiple codes
        >>> verify_action = verify_error_present(
        ...     "Verify errors present", "COM3",
        ...     expected_codes=[0x2F13, 0x8009], log_type="ERROR"
        ... )
    """
    def execute():
        logger = get_active_logger()
        
        log_type_upper = log_type.upper()
        
        # Normalize to list
        codes_to_check = [expected_codes] if isinstance(expected_codes, int) else expected_codes
        
        if logger:
            logger.info(f"[FAILMEM TEST] {name}")
            logger.info(f"[FAILMEM TEST] Verifying {len(codes_to_check)} code(s) in {log_type_upper} log")
            for code in codes_to_check:
                logger.info(f"[FAILMEM TEST]   - 0x{code:04X}")
        
        # Read the log
        _, _, _, error_codes = read_failure_memory_uart(
            port, f"read_{log_type.lower()}", baudrate, timeout
        )
        
        # Check which codes are present and which are missing
        found_codes = []
        missing_codes = []
        
        for code in codes_to_check:
            if code in error_codes:
                count = error_codes.count(code)
                found_codes.append((code, count))
                if logger:
                    logger.info(f"[FAILMEM TEST] ✓ Code 0x{code:04X} found ({count} occurrences)")
            else:
                missing_codes.append(code)
                if logger:
                    logger.error(f"[FAILMEM TEST] ✗ Code 0x{code:04X} not found")
        
        # If any codes are missing, fail
        if missing_codes:
            actual_codes_str = ', '.join([f"0x{c:04X}" for c in error_codes])
            missing_codes_str = ', '.join([f"0x{c:04X}" for c in missing_codes])
            error_msg = (
                f"Missing {len(missing_codes)} expected code(s) in {log_type_upper} log: {missing_codes_str}. "
                f"Found {len(error_codes)} entries: {actual_codes_str if actual_codes_str else 'none'}"
            )
            raise FailureMemoryError(error_msg)

        return True

    codes_list = [expected_codes] if isinstance(expected_codes, int) else expected_codes
    codes_str = ', '.join([f"0x{c:04X}" for c in codes_list])
    metadata = {'sent': f"read_{log_type.lower()} (verify codes: {codes_str})"}
    return TestAction(name, execute, metadata=metadata, negative_test=negative_test)


def verify_log_empty(
    name: str,
    port: str,
    log_type: str = "ERROR",
    baudrate: int = 115200,
    timeout: float = FAILURE_MEM_TIMEOUT,
    negative_test: bool = False
) -> TestAction:
    """Create a TestAction that verifies a failure log is empty.
    
    This TestAction factory creates an action that reads the failure log and
    verifies no error codes are present. Useful after clearing logs or for
    validating clean device state.
    
    Args:
        name (str): Human-readable name for the test step.
        port (str): Serial port identifier.
        log_type (str, optional): Log to check ("ERROR" or "WARNING"). Defaults to "ERROR".
        baudrate (int, optional): Serial communication baud rate. Defaults to 115200.
        timeout (float, optional): Read timeout in seconds. Defaults to FAILURE_MEM_TIMEOUT.
        negative_test (bool, optional): If True, test expects failure. Defaults to False.
        
    Returns:
        TestAction: TestAction that returns True if log is empty.
        
    Raises:
        FailureMemoryError: When executed, raises if log contains entries.
        
    Example:
        >>> verify_action = verify_log_empty(
        ...     "Verify ERROR log empty", "COM3", log_type="ERROR"
        ... )
        >>> verify_action.execute()  # Returns True if empty
    """
    def execute():
        logger = get_active_logger()
        
        log_type_upper = log_type.upper()
        
        if logger:
            logger.info(f"[FAILMEM TEST] {name}")
            logger.info(f"[FAILMEM TEST] Verifying {log_type_upper} log is empty")
        
        # Read the log
        _, _, _, error_codes = read_failure_memory_uart(
            port, f"read_{log_type.lower()}", baudrate, timeout
        )
        
        if len(error_codes) == 0:
            if logger:
                logger.info(f"[FAILMEM TEST] ✓ {log_type_upper} log is empty")
            return True
        else:
            # Decode entries for better error message
            decoded = [decode_error_code(c) for c in error_codes]
            entries_str = ", ".join([
                f"0x{info['code']:04X}[{info['severity_name']}]"
                for info in decoded
            ])
            error_msg = (
                f"{log_type_upper} log is not empty. "
                f"Found {len(error_codes)} entries: {entries_str}"
            )
            if logger:
                logger.error(f"[FAILMEM TEST] ✗ {error_msg}")
            raise FailureMemoryError(error_msg)

    metadata = {'sent': f"read_{log_type.lower()} (verify empty)"}
    return TestAction(name, execute, metadata=metadata, negative_test=negative_test)