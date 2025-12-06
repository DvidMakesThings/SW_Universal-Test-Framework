"""
NOP Module - No Operation / Wait Utilities
==========================================

Provides timing control and wait operations for test sequences.
"""

import time
from UTFW.core.core import TestAction
from UTFW.core.logger import get_active_logger


def NOP(name: str, duration_ms: int) -> TestAction:
    """
    No Operation - Wait for a specified duration.

    Used when a delay is necessary between test steps, such as waiting
    for hardware to stabilize, signals to propagate, or operations to complete.

    Logs a message every second during the wait and calculates the exact
    duration at the end.

    Args:
        name: Descriptive name for this wait operation
        duration_ms: Wait duration in milliseconds

    Returns:
        TestAction: Action that performs the wait operation

    Example:
        NOP.NOP(
            name="Wait for device to stabilize",
            duration_ms=5000
        )
    """
    def execute():
        logger = get_active_logger()
        start_time = time.time()
        target_duration_s = duration_ms / 1000.0
        elapsed = 0

        logger.info(f"Starting NOP wait for {duration_ms}ms")

        while elapsed < target_duration_s:
            time.sleep(min(1.0, target_duration_s - elapsed))
            elapsed = time.time() - start_time
            if elapsed < target_duration_s:
                logger.info(f"NOP waiting... {elapsed:.1f}s elapsed")

        actual_duration_ms = (time.time() - start_time) * 1000.0
        logger.info(f"NOP wait complete. Actual duration: {actual_duration_ms:.2f}ms")

        return {
            "success": True,
            "message": f"Waited {actual_duration_ms:.2f}ms (target: {duration_ms}ms)"
        }

    metadata = {'sent': f"Wait {duration_ms}ms"}
    return TestAction(
        name=name,
        execute_func=execute,
        metadata=metadata
    )
