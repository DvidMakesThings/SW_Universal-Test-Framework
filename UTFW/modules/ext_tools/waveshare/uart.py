# uart.py
"""
UTFW Waveshare UART Module
===========================
High-level UART/serial test functions and TestAction factories for the
Waveshare USB TO UART/I2C/SPI/JTAG adapter (WCH CH347 chipset).

This module provides UART communication capabilities through the CH347
adapter's serial interface. It differs from the built-in UTFW Serial module
in that it targets the Waveshare/CH347 hardware specifically, providing
device-aware connection handling and adapter identification.

All communication is logged using the UTFW logging system with detailed
TX/RX dumps including hex previews.

The module includes TestAction factories for common UART operations, making
it easy to build complex test scenarios using the STE (Sub-step Test Executor)
system.

Usage:
    import UTFW
    waveshare = UTFW.modules.ext_tools.waveshare

    action = waveshare.uart.send_receive(
        "Query firmware version", "COM3", "SYSINFO"
    )

Author: DvidMakesThings
"""

import time
from typing import Optional, Dict, List, Any

from ....core.logger import get_active_logger
from ....core.core import TestAction
from ._base import WaveshareError, _format_hex_dump, _ensure_pyserial

DEBUG = False  # Set to True to enable debug prints

# Global response caching for validation chaining
_LAST_RESPONSE: Optional[str] = None


class WaveshareUARTError(WaveshareError):
    """Exception raised when Waveshare UART communication or validation fails.

    This exception is raised by UART test functions when communication
    errors occur, validation fails, or other serial-related operations
    through the CH347 adapter cannot be completed.

    Args:
        message (str): Description of the error that occurred.
    """
    pass


def _set_last_response(text: str) -> None:
    """Store the last response for use in validation functions.

    Args:
        text (str): Response text to cache.
    """
    global _LAST_RESPONSE
    _LAST_RESPONSE = text


def _use_response(explicit: str) -> str:
    """Get response text, either explicit or from cache.

    Args:
        explicit (str): Explicitly provided response text.

    Returns:
        str: Response text to use for validation.

    Raises:
        WaveshareUARTError: If no response is available.
    """
    if explicit:
        return explicit
    if _LAST_RESPONSE:
        return _LAST_RESPONSE
    raise WaveshareUARTError(
        "No response available. Provide `response` explicitly or call send_and_receive() first."
    )


# ======================== Core UART Functions ========================

def open_connection(port: str, baudrate: int = 115200, timeout: float = 2.0,
                    databits: int = 8, parity: str = "N", stopbits: float = 1,
                    byte_timeout: Optional[float] = None):
    """Open a UART connection through the Waveshare CH347 adapter.

    Opens the serial port exposed by the CH347 adapter with the specified
    parameters and configures it for reliable communication.

    Args:
        port (str): Serial port identifier (e.g., "COM3", "/dev/ttyUSB0").
        baudrate (int, optional): Communication baud rate. Defaults to 115200.
        timeout (float, optional): Read timeout in seconds. Defaults to 2.0.
        databits (int, optional): Data bits per frame (5, 6, 7, 8).
            Defaults to 8.
        parity (str, optional): Parity mode -- "N" (none), "O" (odd), "E" (even),
            "M" (mark), "S" (space). Defaults to "N".
        stopbits (float, optional): Stop bits -- 1, 1.5, or 2.
            Defaults to 1.
        byte_timeout (float, optional): Inter-byte timeout in seconds.
            If None, defaults to pyserial behaviour (no inter-byte timeout).

    Returns:
        serial.Serial: Configured and opened serial port object.

    Raises:
        WaveshareUARTError: If the port cannot be opened or configured.
    """
    _ensure_pyserial()
    import serial as pyserial

    # Map parity string to pyserial constants
    _PARITY_MAP = {
        "N": pyserial.PARITY_NONE,
        "O": pyserial.PARITY_ODD,
        "E": pyserial.PARITY_EVEN,
        "M": pyserial.PARITY_MARK,
        "S": pyserial.PARITY_SPACE,
    }

    # Map stopbits to pyserial constants
    _STOPBITS_MAP = {
        1: pyserial.STOPBITS_ONE,
        1.5: pyserial.STOPBITS_ONE_POINT_FIVE,
        2: pyserial.STOPBITS_TWO,
    }

    # Map databits to pyserial constants
    _BYTESIZE_MAP = {
        5: pyserial.FIVEBITS,
        6: pyserial.SIXBITS,
        7: pyserial.SEVENBITS,
        8: pyserial.EIGHTBITS,
    }

    parity_const = _PARITY_MAP.get(parity.upper())
    if parity_const is None:
        raise WaveshareUARTError(
            f"Invalid parity '{parity}'. Must be one of: N, O, E, M, S"
        )

    stopbits_const = _STOPBITS_MAP.get(stopbits)
    if stopbits_const is None:
        raise WaveshareUARTError(
            f"Invalid stopbits {stopbits}. Must be one of: 1, 1.5, 2"
        )

    bytesize_const = _BYTESIZE_MAP.get(databits)
    if bytesize_const is None:
        raise WaveshareUARTError(
            f"Invalid databits {databits}. Must be one of: 5, 6, 7, 8"
        )

    logger = get_active_logger()

    if logger:
        logger.info("=" * 80)
        logger.info("[WAVESHARE UART] OPENING CONNECTION")
        logger.info("=" * 80)
        logger.info(f"  Port:          {port}")
        logger.info(f"  Baudrate:      {baudrate}")
        logger.info(f"  Data bits:     {databits}")
        logger.info(f"  Parity:        {parity.upper()}")
        logger.info(f"  Stop bits:     {stopbits}")
        logger.info(f"  Timeout:       {timeout}s")
        logger.info(f"  Byte Timeout:  {byte_timeout}s" if byte_timeout else "  Byte Timeout:  None")
        logger.info(f"  Write Timeout: 2.0s")
        logger.info(f"  Flow Control:  None (xonxoff=False, rtscts=False, dsrdtr=False)")

    try:
        ser = pyserial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=bytesize_const,
            parity=parity_const,
            stopbits=stopbits_const,
            timeout=timeout,
            write_timeout=2.0,
            inter_byte_timeout=byte_timeout,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False
        )

        if logger:
            logger.info(f"[OK] Port {port} opened successfully")
            logger.info("  Stabilizing connection (100ms delay)...")

        time.sleep(0.1)

        if logger:
            logger.info("  Resetting input and output buffers...")
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        if logger:
            logger.info(f"[OK] Connection ready and buffers cleared")
            logger.info("-" * 80)

        return ser

    except FileNotFoundError as e:
        error_msg = f"Serial port {port} not found. Please verify the Waveshare adapter is connected."
        if logger:
            logger.error("=" * 80)
            logger.error("[WAVESHARE UART ERROR] PORT NOT FOUND")
            logger.error("=" * 80)
            logger.error(f"  Port:      {port}")
            logger.error(f"  Exception: {type(e).__name__}: {e}")
            logger.error("-" * 80)
        raise WaveshareUARTError(error_msg)

    except PermissionError as e:
        error_msg = f"Permission denied accessing port {port}. Port may be in use by another process."
        if logger:
            logger.error("=" * 80)
            logger.error("[WAVESHARE UART ERROR] PERMISSION DENIED")
            logger.error("=" * 80)
            logger.error(f"  Port:      {port}")
            logger.error(f"  Exception: {type(e).__name__}: {e}")
            logger.error("  Hint:      Port may be in use by another process")
            logger.error("-" * 80)
        raise WaveshareUARTError(error_msg)

    except Exception as e:
        error_msg = f"Failed to open serial port {port}: {type(e).__name__}: {e}"
        if logger:
            logger.error("=" * 80)
            logger.error("[WAVESHARE UART ERROR] CONNECTION FAILED")
            logger.error("=" * 80)
            logger.error(f"  Port:      {port}")
            logger.error(f"  Baudrate:  {baudrate}")
            logger.error(f"  Exception: {type(e).__name__}: {e}")
            logger.error("-" * 80)
        raise WaveshareUARTError(error_msg)


def close_connection(ser) -> None:
    """Close a previously opened UART connection.

    Args:
        ser: Serial port object returned by open_connection().
    """
    logger = get_active_logger()
    try:
        if logger:
            logger.info("[WAVESHARE UART] Closing connection...")
        ser.close()
        if logger:
            logger.info(f"[OK] Port closed")
    except Exception as e:
        if logger:
            logger.error(f"[WAVESHARE UART ERROR] Failed to close port: {e}")


def send_command(port: str, command: str, baudrate: int = 115200,
                 timeout: float = 2.0) -> str:
    """Send a command via the Waveshare UART and return the complete response.

    Opens a serial connection through the CH347 adapter, sends the specified
    command, waits for and captures the response, then closes the connection.
    All TX/RX data is logged with hex dumps.

    Args:
        port (str): Serial port identifier (e.g., "COM3", "/dev/ttyUSB0").
        command (str): Command string to send (CR+LF will be appended).
        baudrate (int, optional): Communication baud rate. Defaults to 115200.
        timeout (float, optional): Response timeout in seconds. Defaults to 2.0.

    Returns:
        str: Complete response received from the device.

    Raises:
        WaveshareUARTError: If communication fails or times out.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE UART] SEND COMMAND")
        logger.info("=" * 80)
        logger.info(f"  Command: '{command}'")
        logger.info(f"  Port:    {port}")
        logger.info("")

    ser = open_connection(port, baudrate, timeout)

    try:
        payload = (command.strip() + "\r\n")
        cmd_bytes = payload.encode('utf-8')

        if logger:
            logger.info("[WAVESHARE UART TX] TRANSMITTING")
            logger.info("-" * 80)
            logger.info(f"  Command:  '{command.strip()}'")
            logger.info(f"  Length:   {len(cmd_bytes)} bytes (including CR+LF)")
            logger.info("")
            logger.info("  Hex Dump:")
            for line in _format_hex_dump(cmd_bytes).split('\n'):
                logger.info(f"    {line}")

        bytes_written = ser.write(cmd_bytes)
        ser.flush()

        if logger:
            logger.info("")
            logger.info(f"[OK] Transmitted {bytes_written} bytes")
            logger.info("  Waiting 50ms for device processing...")
            logger.info("")

        time.sleep(0.05)

        response_bytes = bytearray()
        start_time = time.time()
        last_data_time = start_time
        chunk_count = 0

        if logger:
            logger.info("[WAVESHARE UART RX] RECEIVING RESPONSE")
            logger.info("-" * 80)
            logger.info(f"  Timeout: {timeout}s")
            logger.info("")

        while (time.time() - start_time) < timeout:
            if ser.in_waiting > 0:
                chunk = ser.read(ser.in_waiting)
                chunk_count += 1
                response_bytes.extend(chunk)
                last_data_time = time.time()
                elapsed = time.time() - start_time

                if logger:
                    logger.info(
                        f"  Chunk #{chunk_count}: {len(chunk)} bytes | "
                        f"Elapsed: {elapsed:.3f}s | Total: {len(response_bytes)} bytes"
                    )

            elif (time.time() - last_data_time) > 0.5:
                if logger:
                    logger.info("")
                    logger.info("  No data for 500ms, response complete")
                break

            time.sleep(0.01)

        total_time = time.time() - start_time

        if logger:
            logger.info("")
            logger.info(f"[OK] Response Complete:")
            logger.info(f"    Total Bytes:    {len(response_bytes)}")
            logger.info(f"    Chunks:         {chunk_count}")
            logger.info(f"    Total Time:     {total_time:.3f}s")
            logger.info("")

        text = response_bytes.decode('utf-8', errors='ignore')

        if logger:
            logger.info("  Decoded Text:")
            logger.info("  " + "-" * 78)
            visible_text = text.replace("\r", "\\r").replace("\n", "\\n\n  ")
            logger.info(f"  {visible_text}")
            logger.info("  " + "-" * 78)
            logger.info("")
            logger.info("  Hex Dump:")
            for line in _format_hex_dump(response_bytes).split('\n'):
                logger.info(f"    {line}")
            logger.info("")

        _set_last_response(text)
        return text

    except WaveshareUARTError:
        raise
    except Exception as e:
        if logger:
            logger.error("")
            logger.error("=" * 80)
            logger.error("[WAVESHARE UART ERROR] COMMUNICATION EXCEPTION")
            logger.error("=" * 80)
            logger.error(f"  Type:    {type(e).__name__}")
            logger.error(f"  Message: {e}")
            logger.error(f"  Port:    {port}")
            logger.error(f"  Command: '{command}'")
            logger.error("-" * 80)
        raise WaveshareUARTError(f"Communication error on {port}: {type(e).__name__}: {e}")

    finally:
        try:
            ser.close()
            if logger:
                logger.info(f"[OK] Port {port} closed")
                logger.info("=" * 80)
                logger.info("")
        except Exception as e:
            if logger:
                logger.error(f"[WAVESHARE UART ERROR] Failed to close port {port}: {e}")


def send_raw(port: str, data: bytes, baudrate: int = 115200,
             timeout: float = 2.0) -> bytes:
    """Send raw bytes via the Waveshare UART and return the raw response.

    Unlike send_command(), this function does not append CR+LF and returns
    raw bytes instead of decoded text. Useful for binary protocols.

    Args:
        port (str): Serial port identifier.
        data (bytes): Raw bytes to transmit.
        baudrate (int, optional): Communication baud rate. Defaults to 115200.
        timeout (float, optional): Response timeout in seconds. Defaults to 2.0.

    Returns:
        bytes: Raw response bytes.

    Raises:
        WaveshareUARTError: If communication fails.
    """
    logger = get_active_logger()

    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[WAVESHARE UART] SEND RAW DATA")
        logger.info("=" * 80)
        logger.info(f"  Port:    {port}")
        logger.info(f"  Length:  {len(data)} bytes")
        logger.info("")
        logger.info("  TX Hex Dump:")
        for line in _format_hex_dump(data).split('\n'):
            logger.info(f"    {line}")
        logger.info("")

    ser = open_connection(port, baudrate, timeout)

    try:
        bytes_written = ser.write(data)
        ser.flush()

        if logger:
            logger.info(f"[OK] Transmitted {bytes_written} bytes")
            logger.info("")

        time.sleep(0.05)

        response_bytes = bytearray()
        start_time = time.time()
        last_data_time = start_time

        while (time.time() - start_time) < timeout:
            if ser.in_waiting > 0:
                chunk = ser.read(ser.in_waiting)
                response_bytes.extend(chunk)
                last_data_time = time.time()
            elif (time.time() - last_data_time) > 0.5:
                break
            time.sleep(0.01)

        if logger:
            logger.info(f"[OK] Received {len(response_bytes)} bytes")
            logger.info("")
            logger.info("  RX Hex Dump:")
            for line in _format_hex_dump(bytes(response_bytes)).split('\n'):
                logger.info(f"    {line}")
            logger.info("")

        return bytes(response_bytes)

    except WaveshareUARTError:
        raise
    except Exception as e:
        if logger:
            logger.error(f"[WAVESHARE UART ERROR] Raw send failed: {type(e).__name__}: {e}")
        raise WaveshareUARTError(f"Raw communication error on {port}: {type(e).__name__}: {e}")

    finally:
        try:
            ser.close()
        except Exception:
            pass


def loopback(
        name: str,
        port: str,
        payload: bytes,
        expected: Optional[bytes] = None,
        baudrate: int = 115200,
        timeout: float = 2.0,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that validates UART loopback on the same adapter.

    This action is intended for a physical jumper test where UART TX and RX are
    tied together (for example UART0-TX <-> UART1-RX and UART1-TX <-> UART0-RX,
    depending on adapter mode/wiring). It sends raw bytes and verifies the echo.

    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier.
        payload (bytes): Raw bytes to transmit.
        expected (Optional[bytes], optional): Expected echo bytes. If None,
            payload is used as the expected value.
        baudrate (int, optional): Baud rate. Defaults to 115200.
        timeout (float, optional): Response timeout in seconds. Defaults to 2.0.
        negative_test (bool, optional): Mark as negative test. Defaults to False.

    Returns:
        TestAction: TestAction that returns the received bytes.
    """

    expected_bytes = payload if expected is None else expected

    def execute():
        logger = get_active_logger()

        if logger:
            logger.info("")
            logger.info("=" * 80)
            logger.info("[WAVESHARE UART] LOOPBACK TEST")
            logger.info("=" * 80)
            logger.info(f"  Port:     {port}")
            logger.info(f"  Baudrate: {baudrate}")
            logger.info(f"  TX Size:  {len(payload)} bytes")
            logger.info(f"  Timeout:  {timeout}s")
            logger.info("")

        rx = send_raw(port=port, data=payload, baudrate=baudrate, timeout=timeout)

        if rx != expected_bytes:
            if logger:
                logger.error("")
                logger.error("=" * 80)
                logger.error("[WAVESHARE UART] LOOPBACK VALIDATION FAILED")
                logger.error("=" * 80)
                logger.error(f"  Expected ({len(expected_bytes)}B): {expected_bytes.hex(' ').upper()}")
                logger.error(f"  Actual   ({len(rx)}B): {rx.hex(' ').upper()}")
                logger.error("-" * 80)
            raise WaveshareUARTError(
                "UART loopback mismatch: "
                f"expected {expected_bytes.hex(' ').upper()}, got {rx.hex(' ').upper()}"
            )

        if logger:
            logger.info(f"  Loopback verified ({len(rx)} bytes)")
            logger.info("=" * 80)
            logger.info("")

        return rx

    metadata = {
        'display_command': f"UART loopback {len(payload)}B",
        'display_expected': expected_bytes.hex(' ').upper(),
    }

    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def cross_loopback(
        name: str,
        tx_port: str,
        rx_port: str,
        payload: bytes,
        expected: Optional[bytes] = None,
        baudrate: int = 115200,
        timeout: float = 2.0,
        databits: int = 8,
        parity: str = "N",
        stopbits: float = 1,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that validates cross-port UART loopback.

    Hardware setup: TX of *tx_port* wired to RX of *rx_port*.
    Opens both ports, transmits on tx_port, and reads from rx_port.

    Args:
        name: Human-readable name for the test action.
        tx_port: Serial port used for transmitting (e.g. "COM12").
        rx_port: Serial port used for receiving  (e.g. "COM13").
        payload: Raw bytes to transmit.
        expected: Expected bytes on rx_port.  Defaults to *payload*.
        baudrate: Baud rate for both ports.  Defaults to 115200.
        timeout: Receive timeout in seconds.  Defaults to 2.0.
        databits: Data bits per frame (5-8).  Defaults to 8.
        parity: Parity mode ("N","O","E","M","S"). Defaults to "N".
        stopbits: Stop bits (1, 1.5, 2). Defaults to 1.
        negative_test: Mark as negative test.

    Returns:
        TestAction that returns the received bytes.
    """

    expected_bytes = payload if expected is None else expected

    def execute():
        logger = get_active_logger()

        if logger:
            logger.info("")
            logger.info("=" * 80)
            logger.info("[WAVESHARE UART] CROSS-PORT LOOPBACK TEST")
            logger.info("=" * 80)
            logger.info(f"  TX Port:  {tx_port}")
            logger.info(f"  RX Port:  {rx_port}")
            logger.info(f"  Baudrate: {baudrate}")
            logger.info(f"  Config:   {databits}{parity}{stopbits}")
            logger.info(f"  TX Size:  {len(payload)} bytes")
            logger.info(f"  Timeout:  {timeout}s")
            logger.info("")

        # Open receiver first so it is ready before we transmit
        ser_rx = open_connection(rx_port, baudrate, timeout,
                                databits=databits, parity=parity,
                                stopbits=stopbits)
        ser_tx = open_connection(tx_port, baudrate, timeout,
                                databits=databits, parity=parity,
                                stopbits=stopbits)

        try:
            # Transmit
            bytes_written = ser_tx.write(payload)
            ser_tx.flush()

            if logger:
                logger.info(f"  [OK] Transmitted {bytes_written} bytes on {tx_port}")
                logger.info("    Hex Dump:")
                for line in _format_hex_dump(payload).split('\n'):
                    logger.info(f"      {line}")
                logger.info("")

            # Receive
            rx_buf = bytearray()
            start = time.time()
            last_data = start

            while (time.time() - start) < timeout:
                if ser_rx.in_waiting > 0:
                    chunk = ser_rx.read(ser_rx.in_waiting)
                    rx_buf.extend(chunk)
                    last_data = time.time()
                    if len(rx_buf) >= len(expected_bytes):
                        break
                elif (time.time() - last_data) > 0.5:
                    break
                time.sleep(0.01)

            rx = bytes(rx_buf)

            if logger:
                logger.info(f"  [OK] Received {len(rx)} bytes on {rx_port}")
                logger.info("    Hex Dump:")
                for line in _format_hex_dump(rx).split('\n'):
                    logger.info(f"      {line}")
                logger.info("")

            if rx != expected_bytes:
                if logger:
                    logger.error("=" * 80)
                    logger.error("[WAVESHARE UART] CROSS-LOOPBACK VALIDATION FAILED")
                    logger.error("=" * 80)
                    logger.error(f"  Expected ({len(expected_bytes)}B): {expected_bytes.hex(' ').upper()}")
                    logger.error(f"  Actual   ({len(rx)}B): {rx.hex(' ').upper()}")
                    logger.error("-" * 80)
                raise WaveshareUARTError(
                    f"Cross-loopback mismatch ({tx_port}->{rx_port}): "
                    f"expected {expected_bytes.hex(' ').upper()}, "
                    f"got {rx.hex(' ').upper()}"
                )

            if logger:
                logger.info(f"  [OK] Cross-loopback verified ({len(rx)} bytes, {tx_port}->{rx_port})")
                logger.info("=" * 80)
                logger.info("")

            return rx

        finally:
            try:
                ser_tx.close()
            except Exception:
                pass
            try:
                ser_rx.close()
            except Exception:
                pass

    metadata = {
        'display_command': f"UART cross-loopback {tx_port}->{rx_port} [{len(payload)}B]",
        'display_expected': expected_bytes.hex(' ').upper(),
    }

    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


# ======================== TestAction Factories ========================

def send(
        name: str,
        port: str,
        command: str,
        baudrate: int = 115200,
        timeout: float = 2.0,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that sends a UART command via the Waveshare adapter.

    This TestAction factory creates an action that sends a command and
    caches the response for subsequent validation actions.

    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier (e.g., "COM3").
        command (str): Command string to send (CR+LF appended automatically).
        baudrate (int, optional): Baud rate. Defaults to 115200.
        timeout (float, optional): Response timeout in seconds. Defaults to 2.0.
        negative_test (bool, optional): Mark as negative test. Defaults to False.

    Returns:
        TestAction: TestAction that returns the response string.

    Raises:
        WaveshareUARTError: When executed, if communication fails.

    Example:
        >>> action = waveshare.uart.send("Get info", "COM3", "SYSINFO")
    """

    def execute():
        return send_command(port, command, baudrate, timeout)

    metadata = {
        'display_command': f"UART TX: {command}",
        'display_expected': '',
        'sent': command,
    }

    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def send_receive(
        name: str,
        port: str,
        command: str,
        expected_token: Optional[str] = None,
        baudrate: int = 115200,
        timeout: float = 2.0,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that sends a UART command and validates the response.

    This TestAction factory creates an action that sends a command, receives
    the response, and optionally validates that the response contains the
    expected token.

    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier.
        command (str): Command string to send.
        expected_token (Optional[str], optional): Token that must be present
            in the response for validation. If None, no validation performed.
        baudrate (int, optional): Baud rate. Defaults to 115200.
        timeout (float, optional): Response timeout. Defaults to 2.0.
        negative_test (bool, optional): Mark as negative test. Defaults to False.

    Returns:
        TestAction: TestAction that returns the response string.

    Raises:
        WaveshareUARTError: When executed, if communication or validation fails.

    Example:
        >>> action = waveshare.uart.send_receive(
        ...     "Verify firmware", "COM3", "SYSINFO", expected_token="FW"
        ... )
    """

    def execute():
        logger = get_active_logger()
        response = send_command(port, command, baudrate, timeout)

        if expected_token is not None:
            if expected_token not in response:
                if logger:
                    logger.error("")
                    logger.error("=" * 80)
                    logger.error("[WAVESHARE UART] VALIDATION FAILED")
                    logger.error("=" * 80)
                    logger.error(f"  Command:  '{command}'")
                    logger.error(f"  Expected: '{expected_token}'")
                    logger.error(f"  Response: '{response[:200]}'")
                    logger.error("-" * 80)
                raise WaveshareUARTError(
                    f"Expected token '{expected_token}' not found in response to '{command}'"
                )

            if logger:
                logger.info(f"[OK] Token '{expected_token}' found in response")

        return response

    metadata = {
        'display_command': f"UART TX: {command}",
        'display_expected': expected_token or '',
        'sent': command,
    }

    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)


def detect(
        name: str,
        port: str,
        baudrate: int = 115200,
        negative_test: bool = False
) -> TestAction:
    """Create a TestAction that detects if a Waveshare adapter is present on a port.

    This TestAction factory creates an action that attempts to open the
    serial port and verifies basic connectivity. Useful as a first test
    step to confirm adapter presence.

    Args:
        name (str): Human-readable name for the test action.
        port (str): Serial port identifier to probe.
        baudrate (int, optional): Baud rate. Defaults to 115200.
        negative_test (bool, optional): Mark as negative test. Defaults to False.

    Returns:
        TestAction: TestAction that returns True if the adapter responds.

    Raises:
        WaveshareUARTError: When executed, if the adapter is not detected.

    Example:
        >>> action = waveshare.uart.detect("Detect adapter", "COM3")
    """

    def execute():
        logger = get_active_logger()

        if logger:
            logger.info("")
            logger.info("=" * 80)
            logger.info("[WAVESHARE UART] DETECT ADAPTER")
            logger.info("=" * 80)
            logger.info(f"  Port:     {port}")
            logger.info(f"  Baudrate: {baudrate}")
            logger.info("")

        ser = open_connection(port, baudrate, timeout=1.0)
        try:
            if logger:
                logger.info(f"[OK] Waveshare adapter detected on {port}")
                logger.info("=" * 80)
                logger.info("")
            return True
        finally:
            try:
                ser.close()
            except Exception:
                pass

    metadata = {
        'display_command': f"Detect adapter on {port}",
        'display_expected': 'Adapter present',
    }

    return TestAction(name, execute, negative_test=negative_test, metadata=metadata)
