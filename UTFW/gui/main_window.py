"""
UTFW GUI Main Window
====================
PySide6-based graphical user interface for UTFW test framework.

This module provides the main window and all GUI components. It is completely
isolated from the core framework and only imported when the GUI is used.
"""

from pathlib import Path
from typing import Dict, Any, Optional, List
from enum import Enum
from datetime import datetime
import webbrowser
import json

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QTreeWidget, QTreeWidgetItem, QTableWidget,
    QTableWidgetItem, QTextEdit, QLabel, QFileDialog, QHeaderView,
    QGroupBox, QToolBar, QMessageBox, QTabWidget, QRadioButton, QFrame, QMenuBar, QMenu
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer, Slot, QSettings
from PySide6.QtGui import QColor, QFont, QAction, QTextCursor, QIcon

from .model import (
    discover_tests, build_step_model, run_test_in_thread,
    TestMetadata, TestStepModel, StepInfo
)
from .suite_model import discover_suites, TestSuite
from .suite_runner import SuiteRunnerWidget
from .suite_editor import SuiteEditorDialog


class StepStatus(Enum):
    """Status of a test step."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASS = "PASS"
    FAIL = "FAIL"


class EventBridge(QObject):
    """Qt signal bridge for thread-safe event handling."""
    event_received = Signal(dict)
    log_line_received = Signal(str)
    test_finished = Signal(int, str, str)  # exit_code, error_message, report_path


class TestTabWidget(QWidget):
    """Widget representing a single test execution tab."""

    def __init__(self, test: TestMetadata, hardware_config_path: Optional[Path] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.test = test
        self.hardware_config_path = hardware_config_path
        self.model: Optional[TestStepModel] = None
        self.step_status: Dict[str, StepStatus] = {}
        self.step_start_times: Dict[str, datetime] = {}
        self.step_durations: Dict[str, float] = {}
        self.running = False
        self.stop_requested = False
        self.error_messages: List[str] = []
        self.report_path: Optional[str] = None
        self.is_cleaning_up = False  # Flag to prevent updates during cleanup

        # Performance optimization: batch log updates
        self.pending_logs: List[str] = []
        self.log_batch_timer = QTimer(self)
        self.log_batch_timer.timeout.connect(self._flush_pending_logs)
        self.log_batch_timer.setInterval(100)  # Flush logs every 100ms

        # Performance optimization: throttle table updates
        self.needs_table_update = False
        self.table_update_timer = QTimer(self)
        self.table_update_timer.timeout.connect(self._process_table_update)
        self.table_update_timer.setInterval(200)  # Update table every 200ms

        # Timer for updating running step durations
        self.duration_timer = QTimer(self)
        self.duration_timer.timeout.connect(self._update_durations)
        self.duration_timer.setInterval(500)  # Update every 500ms (reduced frequency for performance)

        self._setup_ui()

    def cleanup(self):
        """Stop all timers and prepare for deletion."""
        self.is_cleaning_up = True
        self.log_batch_timer.stop()
        self.table_update_timer.stop()
        self.duration_timer.stop()

    def _setup_ui(self):
        """Set up the test tab UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Status bar at top
        self.status_frame = QFrame()
        self.status_frame.setFrameStyle(QFrame.Box | QFrame.Raised)
        self.status_frame.setLineWidth(2)
        status_layout = QHBoxLayout(self.status_frame)

        self.status_label = QLabel("Ready to run")
        self.status_label.setFont(QFont("Arial", 16, QFont.Bold))
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("padding: 10px;")
        status_layout.addWidget(self.status_label, stretch=1)

        # Run button
        self.run_btn = QPushButton("▶ Run Test")
        self.run_btn.setStyleSheet("""
            QPushButton {
                background-color: #50fa7b;
                color: #000;
                font-weight: bold;
                font-size: 14px;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #5fff8a;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #888;
            }
        """)
        self.run_btn.setMinimumHeight(40)
        self.run_btn.clicked.connect(self.run_test)
        status_layout.addWidget(self.run_btn)

        # Stop button
        self.stop_btn = QPushButton("■ Stop Run")
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff5555;
                color: #fff;
                font-weight: bold;
                font-size: 14px;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #ff6666;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #888;
            }
        """)
        self.stop_btn.setMinimumHeight(40)
        self.stop_btn.setEnabled(False)  # Disabled initially
        self.stop_btn.clicked.connect(self.stop_test)
        status_layout.addWidget(self.stop_btn)

        layout.addWidget(self.status_frame)

        # Test info and View Report button
        info_layout = QHBoxLayout()
        info_label = QLabel(f"<b>{self.test.id}</b><br>{self.test.description}")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: gray; padding: 5px;")
        info_layout.addWidget(info_label, stretch=1)

        self.view_report_btn = QPushButton("View HTML Report")
        self.view_report_btn.setEnabled(False)
        self.view_report_btn.clicked.connect(self._open_report)
        info_layout.addWidget(self.view_report_btn)

        layout.addLayout(info_layout)

        # Steps table
        self.steps_table = QTableWidget()
        self.steps_table.setColumnCount(8)
        self.steps_table.setHorizontalHeaderLabels([
            "Phase", "Step ID", "Description", "Sent", "Negative", "Expected", "Result", "Duration"
        ])
        self.steps_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.steps_table.horizontalHeader().setStretchLastSection(False)
        self.steps_table.setColumnWidth(0, 100)   # Phase
        self.steps_table.setColumnWidth(1, 100)   # Step ID
        self.steps_table.setColumnWidth(2, 400)   # Description (reduced from 500)
        self.steps_table.setColumnWidth(3, 400)   # Sent (NEW)
        self.steps_table.setColumnWidth(4, 80)    # Negative
        self.steps_table.setColumnWidth(5, 200)   # Expected
        self.steps_table.setColumnWidth(6, 80)    # Result
        self.steps_table.setColumnWidth(7, 100)   # Duration
        layout.addWidget(self.steps_table, stretch=1)

        # Log toggle button
        log_controls = QHBoxLayout()
        self.show_logs_btn = QRadioButton("Show Logs")
        self.show_logs_btn.setChecked(False)
        self.show_logs_btn.toggled.connect(self._toggle_logs)
        log_controls.addWidget(self.show_logs_btn)
        log_controls.addStretch()
        layout.addLayout(log_controls)

        # Log output (hidden by default)
        self.log_group = QGroupBox("Log Output")
        self.log_group.setVisible(False)
        log_layout = QVBoxLayout(self.log_group)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setFont(QFont("Courier New", 9))
        self.log_output.setMaximumHeight(250)
        log_layout.addWidget(self.log_output)

        layout.addWidget(self.log_group)

        # Error section (hidden by default)
        self.error_group = QGroupBox("Error Details")
        self.error_group.setVisible(False)
        self.error_group.setStyleSheet("QGroupBox { border: 2px solid red; color: red; font-weight: bold; }")
        error_layout = QVBoxLayout(self.error_group)

        self.error_display = QTextEdit()
        self.error_display.setReadOnly(True)
        self.error_display.setFont(QFont("Courier New", 10))
        self.error_display.setMaximumHeight(200)
        error_layout.addWidget(self.error_display)

        layout.addWidget(self.error_group)

    def _toggle_logs(self, checked: bool):
        """Toggle log output visibility."""
        self.log_group.setVisible(checked)

    def _handle_event_direct(self, event: Dict[str, Any]):
        """Handle reporter event directly (for suite runner)."""
        if self.is_cleaning_up:
            return  # Ignore events during cleanup

        event_type = event.get("type")

        if event_type == "step_start":
            step_id = event.get("step_id", "")
            self.update_step_status(step_id, StepStatus.RUNNING)

        elif event_type == "log_message":
            level = event.get("level", "")
            message = event.get("message", "")

            # Extract step ID from message
            import re
            match = re.match(r"((?:PRE-STEP|STEP|POST-STEP|TEARDOWN)\s+[\d.]+)", message)
            if match:
                step_id = match.group(1)
                if level == "PASS":
                    self.update_step_status(step_id, StepStatus.PASS)
                elif level == "FAIL":
                    self.update_step_status(step_id, StepStatus.FAIL)
                    self.error_messages.append(message)

    def load_steps(self):
        """Load and display test steps."""
        if self.model:
            return

        try:
            # Load test module and build step model
            import importlib.util
            import os

            original_cwd = Path.cwd()
            test_dir = self.test.module_path.parent
            test_root_dir = test_dir.parent

            os.chdir(test_root_dir)

            try:
                spec = importlib.util.spec_from_file_location(self.test.id, self.test.module_path)
                if not spec or not spec.loader:
                    raise Exception("Failed to load module")

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                test_cls = getattr(module, self.test.class_name)
                self.model = build_step_model(test_cls, hwconfig_path=self.hardware_config_path)

                self._display_steps()
            finally:
                os.chdir(original_cwd)

        except Exception as e:
            QMessageBox.warning(self, "Load Error", f"Failed to load test:\n{e}")

    def _display_steps(self):
        """Display test steps in the table."""
        if not self.model:
            return

        self.steps_table.setRowCount(0)
        self.step_status.clear()

        all_steps = (
            self.model.pre_steps +
            self.model.main_steps +
            self.model.post_steps +
            self.model.teardown_steps
        )

        self.steps_table.setRowCount(len(all_steps))

        for idx, step in enumerate(all_steps):
            # Display "TEST" for STEP phase, but keep everything else the same
            display_phase = "TEST" if step.phase == "STEP" else step.phase
            self.steps_table.setItem(idx, 0, QTableWidgetItem(display_phase))
            self.steps_table.setItem(idx, 1, QTableWidgetItem(step.step_label))

            desc_item = QTableWidgetItem(step.name)
            if step.parent_label:
                desc_item.setText("  → " + step.name)
            self.steps_table.setItem(idx, 2, desc_item)

            # Sent column (UNIVERSAL - uses 'sent' metadata field)
            sent_text = step.metadata.get('sent', '')
            self.steps_table.setItem(idx, 3, QTableWidgetItem(sent_text))

            negative_text = "Yes" if step.negative else "No"
            self.steps_table.setItem(idx, 4, QTableWidgetItem(negative_text))

            # Expected column (UNIVERSAL - no hardcoding!)
            expected_text = step.metadata.get('display_expected', '')
            self.steps_table.setItem(idx, 5, QTableWidgetItem(expected_text))

            result_item = QTableWidgetItem(StepStatus.PENDING.value)
            self.steps_table.setItem(idx, 6, result_item)

            self.steps_table.setItem(idx, 7, QTableWidgetItem(""))

            self.step_status[step.step_label] = StepStatus.PENDING

    def update_step_status(self, step_id: str, status: StepStatus):
        """Update a step's status and color (throttled for performance)."""
        if self.is_cleaning_up or not self.model or step_id not in self.step_status:
            return

        self.step_status[step_id] = status

        # Track timing
        if status == StepStatus.RUNNING:
            self.step_start_times[step_id] = datetime.now()
            if not self.duration_timer.isActive():
                self.duration_timer.start()
        elif status in (StepStatus.PASS, StepStatus.FAIL):
            if step_id in self.step_start_times:
                duration = (datetime.now() - self.step_start_times[step_id]).total_seconds()
                self.step_durations[step_id] = duration

            # Check if this step completion should trigger parent completion
            self._check_parent_completion(step_id, status)

        # Throttle table updates for performance
        self.needs_table_update = True
        if not self.table_update_timer.isActive():
            self.table_update_timer.start()

    def _process_table_update(self):
        """Process pending table updates (throttled)."""
        if self.needs_table_update:
            self._update_table_display()
            self.needs_table_update = False
        else:
            self.table_update_timer.stop()

    def _check_parent_completion(self, completed_step_id: str, completed_status: StepStatus):
        """Check if completing a substep should mark its parent as complete."""
        if not self.model:
            return

        all_steps = (
            self.model.pre_steps +
            self.model.main_steps +
            self.model.post_steps +
            self.model.teardown_steps
        )

        # Find the parent of the completed step
        parent_label = None
        for step in all_steps:
            if step.step_label == completed_step_id and step.parent_label:
                parent_label = step.parent_label
                break

        if not parent_label:
            return

        # Get all substeps of this parent
        substeps = [s for s in all_steps if s.parent_label == parent_label]
        if not substeps:
            return

        # If this substep failed, immediately mark parent as FAIL and stop timer
        if completed_status == StepStatus.FAIL:
            self.step_status[parent_label] = StepStatus.FAIL
            if parent_label in self.step_start_times:
                duration = (datetime.now() - self.step_start_times[parent_label]).total_seconds()
                self.step_durations[parent_label] = duration
            return

        # For PASS status, check if all substeps are complete
        all_complete = True
        for substep in substeps:
            substep_status = self.step_status.get(substep.step_label, StepStatus.PENDING)
            if substep_status == StepStatus.PENDING or substep_status == StepStatus.RUNNING:
                all_complete = False
                break

        # If all substeps are complete and none failed, mark parent as PASS
        if all_complete:
            self.step_status[parent_label] = StepStatus.PASS

            # Calculate parent duration from start to last substep completion
            if parent_label in self.step_start_times:
                duration = (datetime.now() - self.step_start_times[parent_label]).total_seconds()
                self.step_durations[parent_label] = duration

    def _update_table_display(self):
        """Update the table display with current step statuses."""
        if not self.model:
            return

        # Block signals during bulk update for performance
        self.steps_table.blockSignals(True)

        all_steps = (
            self.model.pre_steps +
            self.model.main_steps +
            self.model.post_steps +
            self.model.teardown_steps
        )

        running_row = None

        for idx, step in enumerate(all_steps):
            status = self.step_status.get(step.step_label, StepStatus.PENDING)
            result_item = self.steps_table.item(idx, 6)  # Result column is now at index 6
            if result_item:
                result_item.setText(status.value)

                # Color the entire row with proper contrast
                if status == StepStatus.PASS:
                    bg_color = QColor(40, 180, 40)
                    text_color = QColor(255, 255, 255)
                elif status == StepStatus.FAIL:
                    bg_color = QColor(200, 50, 50)
                    text_color = QColor(255, 255, 255)
                elif status == StepStatus.RUNNING:
                    bg_color = QColor(200, 160, 0)
                    text_color = QColor(0, 0, 0)
                    running_row = idx
                else:
                    bg_color = QColor(50, 50, 50)
                    text_color = QColor(200, 200, 200)

                for col in range(self.steps_table.columnCount()):
                    item = self.steps_table.item(idx, col)
                    if item:
                        item.setBackground(bg_color)
                        item.setForeground(text_color)

        # Auto-scroll to the currently running step
        if running_row is not None:
            self.steps_table.scrollToItem(
                self.steps_table.item(running_row, 0),
                QTableWidget.ScrollHint.PositionAtCenter
            )

        # Unblock signals after bulk update
        self.steps_table.blockSignals(False)

    def _update_durations(self):
        """Update duration display for running and completed steps."""
        if not self.model:
            return

        all_steps = (
            self.model.pre_steps +
            self.model.main_steps +
            self.model.post_steps +
            self.model.teardown_steps
        )

        has_running = False
        for idx, step in enumerate(all_steps):
            status = self.step_status.get(step.step_label, StepStatus.PENDING)
            duration_item = self.steps_table.item(idx, 7)  # Duration column is now at index 7

            if duration_item:
                if status == StepStatus.RUNNING and step.step_label in self.step_start_times:
                    # Update running duration
                    elapsed = (datetime.now() - self.step_start_times[step.step_label]).total_seconds()
                    duration_item.setText(self._format_duration(elapsed))
                    has_running = True
                elif step.step_label in self.step_durations:
                    # Show final duration
                    duration_item.setText(self._format_duration(self.step_durations[step.step_label]))

        # Stop timer if no running steps
        if not has_running:
            self.duration_timer.stop()

    def _format_duration(self, seconds: float) -> str:
        """Format duration in human-readable format."""
        if seconds < 1:
            return f"{seconds*1000:.0f}ms"
        elif seconds < 60:
            return f"{seconds:.2f}s"
        else:
            mins = int(seconds // 60)
            secs = seconds % 60
            return f"{mins}m {secs:.1f}s"

    def _open_report(self):
        """Open the HTML report in browser."""
        if self.report_path and Path(self.report_path).exists():
            webbrowser.open(f"file://{self.report_path}")
        else:
            QMessageBox.warning(self, "Report Not Found", "The HTML report file was not found.")

    def append_log(self, line: str):
        """Append a log line with performance optimization (batched)."""
        if self.is_cleaning_up:
            return  # Ignore logs during cleanup

        # Batch logs to reduce GUI overhead
        self.pending_logs.append(line)

        # Start timer if not already running
        if not self.log_batch_timer.isActive():
            self.log_batch_timer.start()

    def _flush_pending_logs(self):
        """Flush batched log lines to display."""
        if not self.pending_logs:
            self.log_batch_timer.stop()
            return

        MAX_LOG_LINES = 1000

        # Process all pending logs at once
        text_to_add = '\n'.join(self.pending_logs) + '\n'
        self.pending_logs.clear()

        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text_to_add)

        # Trim old lines if exceeding maximum
        doc = self.log_output.document()
        if doc.blockCount() > MAX_LOG_LINES:
            cursor.movePosition(QTextCursor.Start)
            cursor.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor, doc.blockCount() - MAX_LOG_LINES)
            cursor.removeSelectedText()

        # Auto-scroll only if log is visible
        if self.log_group.isVisible():
            self.log_output.verticalScrollBar().setValue(
                self.log_output.verticalScrollBar().maximum()
            )

    def set_test_status(self, passed: bool, error_msg: str = ""):
        """Set the overall test status."""
        if passed:
            self.status_label.setText("✓ PASS")
            self.status_label.setStyleSheet(
                "background-color: #28a745; color: white; padding: 10px; border-radius: 5px;"
            )
            self.error_group.setVisible(False)
        else:
            self.status_label.setText("✗ FAIL")
            self.status_label.setStyleSheet(
                "background-color: #dc3545; color: white; padding: 10px; border-radius: 5px;"
            )

            if error_msg:
                self.error_display.setPlainText(error_msg)
                self.error_group.setVisible(True)

    def reset_for_run(self):
        """Reset the tab for a new test run."""
        self.log_output.clear()
        self.error_messages.clear()
        self.error_group.setVisible(False)
        self.step_start_times.clear()
        self.step_durations.clear()
        self.report_path = None
        self.view_report_btn.setEnabled(False)
        self.duration_timer.stop()
        self.stop_requested = False
        self.running = True

        self.status_label.setText("Running...")
        self.status_label.setStyleSheet(
            "background-color: #ffc107; color: black; padding: 10px; border-radius: 5px;"
        )

        # Update button states
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        for step_label in self.step_status:
            self.step_status[step_label] = StepStatus.PENDING

        # Clear durations from table
        if self.model:
            all_steps = (
                self.model.pre_steps +
                self.model.main_steps +
                self.model.post_steps +
                self.model.teardown_steps
            )
            for idx in range(len(all_steps)):
                duration_item = self.steps_table.item(idx, 7)  # Duration column is now at index 7
                if duration_item:
                    duration_item.setText("-")

        self._update_table_display()

    def run_test(self):
        """Run this test from the test tab."""
        if self.running:
            return

        # Find the parent MainWindow and trigger the run
        parent_window = self.parent()
        while parent_window and not isinstance(parent_window, QMainWindow):
            parent_window = parent_window.parent()

        if parent_window and hasattr(parent_window, '_run_test_tab'):
            self.stop_requested = False
            self.running = True
            self.run_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            parent_window._run_test_tab(self)

    def stop_test(self):
        """Stop this test execution.

        The currently running step will complete, then teardown will run
        and the test will be marked as failed."""
        if not self.running:
            return

        self.stop_requested = True
        self.status_label.setText("Stopping after current step...")
        self.status_label.setStyleSheet(
            "background-color: #ff9f00; color: black; padding: 10px; border-radius: 5px;"
        )
        self.stop_btn.setEnabled(False)

    def _finish_test(self, exit_code: int, report_path: str):
        """Finish test execution and reset button states."""
        self.running = False
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        if self.stop_requested and exit_code != 0:
            # Mark as stopped if it was stopped and failed
            self.status_label.setText("⏹ Test Stopped")
            self.status_label.setStyleSheet(
                "background-color: #ff9f00; color: black; padding: 10px; border-radius: 5px;"
            )


class MainWindow(QMainWindow):
    """Main window for UTFW GUI."""

    def __init__(self, default_test_root: Optional[Path] = None):
        super().__init__()

        self.test_root: Optional[Path] = default_test_root
        self.hardware_config_path: Optional[Path] = None
        self.tests: List[TestMetadata] = []
        self.suites: List[TestSuite] = []
        self.test_tabs: Dict[str, TestTabWidget] = {}
        self.suite_tabs: Dict[str, SuiteRunnerWidget] = {}
        self.running_test: bool = False

        # Settings
        self.settings = QSettings("UTFW", "TestRunner")
        self.reports_dir = Path(self.settings.value("reports_dir", "Reports"))

        # Event bridge for thread safety
        self.event_bridge = EventBridge()
        self.event_bridge.event_received.connect(self._handle_event)
        self.event_bridge.log_line_received.connect(self._handle_log_line)
        self.event_bridge.test_finished.connect(self._handle_test_finished)

        self.setWindowTitle("UTFW Test Runner")
        self.resize(1600, 1000)  # Larger default size

        self._setup_ui()

        if self.test_root and self.test_root.exists():
            self._refresh_tests()

    def _setup_ui(self):
        """Set up the user interface."""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # Menu bar (create BEFORE tab widget to ensure actions exist)
        self._create_menu_bar()

        # Tab widget as main content
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self._close_test_tab)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tab_widget)

        # Create test list tab (always first)
        self._create_test_list_tab()

        # Status bar
        self.statusBar().showMessage("Ready")

        # Add permanent hardware config label to status bar
        self.hwconfig_label = QLabel("HW Config: None")
        self.statusBar().addPermanentWidget(self.hwconfig_label)

        self.reports_label = QLabel(f"Reports: {self.reports_dir}")
        self.statusBar().addPermanentWidget(self.reports_label)

    def _create_menu_bar(self):
        """Create the menu bar with File, Edit, Run, and Options menus."""
        menubar = self.menuBar()

        # File Menu
        file_menu = menubar.addMenu("&File")

        select_root_action = QAction("Select Test &Root...", self)
        select_root_action.triggered.connect(self._select_test_root)
        file_menu.addAction(select_root_action)

        select_hwconfig_action = QAction("Select &Hardware Config...", self)
        select_hwconfig_action.triggered.connect(self._select_hardware_config)
        file_menu.addAction(select_hwconfig_action)

        file_menu.addSeparator()

        refresh_action = QAction("Re&fresh Tests", self)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self._refresh_tests)
        file_menu.addAction(refresh_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Edit Menu
        edit_menu = menubar.addMenu("&Edit")

        self.new_suite_action = QAction("&New Suite...", self)
        self.new_suite_action.triggered.connect(self._create_new_suite)
        self.new_suite_action.setEnabled(False)
        edit_menu.addAction(self.new_suite_action)

        self.edit_suite_action = QAction("&Edit Suite...", self)
        self.edit_suite_action.triggered.connect(self._edit_selected_suite)
        self.edit_suite_action.setEnabled(False)
        edit_menu.addAction(self.edit_suite_action)

        # Run Menu
        run_menu = menubar.addMenu("&Run")

        self.run_action = QAction("Run Selected &Test", self)
        self.run_action.setShortcut("F9")
        self.run_action.triggered.connect(self._run_selected_test)
        self.run_action.setEnabled(False)
        run_menu.addAction(self.run_action)

        self.run_suite_action = QAction("Run Selected &Suite", self)
        self.run_suite_action.setShortcut("Ctrl+F9")
        self.run_suite_action.triggered.connect(self._run_selected_suite)
        self.run_suite_action.setEnabled(False)
        run_menu.addAction(self.run_suite_action)

        run_menu.addSeparator()

        self.generate_report_action = QAction("&Generate Suite Report...", self)
        self.generate_report_action.triggered.connect(self._generate_suite_report)
        self.generate_report_action.setEnabled(False)
        run_menu.addAction(self.generate_report_action)

        # Options Menu
        options_menu = menubar.addMenu("&Options")

        set_reports_dir_action = QAction("Set &Reports Directory...", self)
        set_reports_dir_action.triggered.connect(self._set_reports_directory)
        options_menu.addAction(set_reports_dir_action)

    def _create_test_list_tab(self):
        """Create the test list tab."""
        list_widget = QWidget()
        layout = QVBoxLayout(list_widget)

        title = QLabel("Available Tests")
        title.setStyleSheet("font-weight: bold; font-size: 14px; padding: 5px;")
        layout.addWidget(title)

        self.test_info_label = QLabel("")
        self.test_info_label.setWordWrap(True)
        self.test_info_label.setStyleSheet("color: gray; font-size: 10px; padding: 5px;")
        layout.addWidget(self.test_info_label)

        # Create tab widget for suites and tests
        self.list_tabs = QTabWidget()
        layout.addWidget(self.list_tabs)

        # Suites tab
        suites_widget = QWidget()
        suites_layout = QVBoxLayout(suites_widget)
        suites_layout.setContentsMargins(0, 0, 0, 0)

        self.suites_tree = QTreeWidget()
        self.suites_tree.setHeaderLabel("Test Suites")
        self.suites_tree.itemDoubleClicked.connect(self._on_test_double_clicked)
        self.suites_tree.itemSelectionChanged.connect(self._on_suite_selection_changed)
        suites_layout.addWidget(self.suites_tree)

        suite_help = QLabel("Double-click a suite to open it")
        suite_help.setStyleSheet("color: gray; font-style: italic; padding: 5px;")
        suites_layout.addWidget(suite_help)

        self.list_tabs.addTab(suites_widget, "Test Suites")

        # Individual tests tab
        tests_widget = QWidget()
        tests_layout = QVBoxLayout(tests_widget)
        tests_layout.setContentsMargins(0, 0, 0, 0)

        self.test_tree = QTreeWidget()
        self.test_tree.setHeaderLabel("Individual Tests")
        self.test_tree.itemDoubleClicked.connect(self._on_test_double_clicked)
        tests_layout.addWidget(self.test_tree)

        test_help = QLabel("Double-click a test to open it")
        test_help.setStyleSheet("color: gray; font-style: italic; padding: 5px;")
        tests_layout.addWidget(test_help)

        self.list_tabs.addTab(tests_widget, "Individual Tests")

        self.tab_widget.addTab(list_widget, "Test List")

    def _select_test_root(self):
        """Open dialog to select test root directory."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Test Root Directory",
            str(self.test_root) if self.test_root else ""
        )

        if directory:
            self.test_root = Path(directory)
            hwconfig = self.test_root / "hardware_config.py"
            if hwconfig.exists():
                self.hardware_config_path = hwconfig
                self.hwconfig_label.setText(f"HW Config: {hwconfig.name}")
                self.statusBar().showMessage(f"Found hardware config: {hwconfig}")
            self._refresh_tests()

    def _select_hardware_config(self):
        """Open dialog to select hardware_config.py file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Hardware Config File",
            str(self.test_root) if self.test_root else "",
            "Python Files (*.py);;All Files (*)"
        )

        if file_path:
            self.hardware_config_path = Path(file_path)
            self.hwconfig_label.setText(f"HW Config: {Path(file_path).name}")
            self.statusBar().showMessage(f"Hardware config set: {file_path}")

            # Reload all open test tabs with new hardware config
            for test_tab in self.test_tabs.values():
                test_tab.hardware_config_path = self.hardware_config_path
                test_tab.model = None  # Clear model to force reload
                test_tab.load_steps()

    def _refresh_tests(self):
        """Refresh the test list."""
        if not self.test_root or not self.test_root.exists():
            self.statusBar().showMessage("No test root selected")
            return

        # Auto-load hardware_config.py if it exists and not already loaded
        if not self.hardware_config_path:
            hwconfig = self.test_root / "hardware_config.py"
            if hwconfig.exists():
                self.hardware_config_path = hwconfig
                self.hwconfig_label.setText(f"HW Config: {hwconfig.name}")
                self.statusBar().showMessage(f"Auto-loaded hardware config: {hwconfig.name}")

        self.statusBar().showMessage("Discovering tests and suites...")

        try:
            self.tests = discover_tests(self.test_root)

            # Discover suites from test_suites directory
            suites_dir = self.test_root.parent / "test_suites"
            self.suites = discover_suites(suites_dir)

            self._populate_test_tree()
            self.test_info_label.setText(
                f"Found {len(self.tests)} test(s) and {len(self.suites)} suite(s) in {self.test_root}"
            )
            self.statusBar().showMessage(f"Found {len(self.tests)} tests and {len(self.suites)} suites")

            # Enable new suite action if tests are available
            self.new_suite_action.setEnabled(len(self.tests) > 0)
        except Exception as e:
            self.statusBar().showMessage(f"Error discovering tests: {e}")
            QMessageBox.warning(self, "Discovery Error", f"Failed to discover tests:\n{e}")

    def _populate_test_tree(self):
        """Populate the test tree with discovered tests and suites."""
        # Clear both trees
        self.suites_tree.clear()
        self.test_tree.clear()

        # Populate suites tree
        for suite in self.suites:
            item = QTreeWidgetItem([f"📋 {suite.name}"])
            item.setData(0, Qt.UserRole, suite)
            item.setToolTip(0, f"{suite.description}\n{len(suite.tests)} tests")

            # Add child items for each test in the suite
            for suite_test in suite.tests:
                if suite_test.enabled:
                    child_item = QTreeWidgetItem([suite_test.name])
                    child_item.setData(0, Qt.UserRole, suite_test)
                    item.addChild(child_item)

            self.suites_tree.addTopLevelItem(item)

        # Populate individual tests tree
        for test in self.tests:
            item = QTreeWidgetItem([test.id])
            item.setData(0, Qt.UserRole, test)
            item.setToolTip(0, f"{test.description}\n{test.relative_path}")
            self.test_tree.addTopLevelItem(item)

    def _on_test_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle double-click on test/suite to open in new tab."""
        data = item.data(0, Qt.UserRole)
        if not data:
            return

        # Check if it's a suite
        if isinstance(data, TestSuite):
            self._open_suite_tab(data)
        elif isinstance(data, TestMetadata):
            self._open_test_tab(data)

    def _open_test_tab(self, test: TestMetadata):
        """Open a test in a new tab."""
        # Check if already open
        if test.id in self.test_tabs:
            existing_tab = self.test_tabs[test.id]
            index = self.tab_widget.indexOf(existing_tab)
            self.tab_widget.setCurrentIndex(index)
            return

        # Create new test tab
        test_tab = TestTabWidget(test, self.hardware_config_path, self)
        test_tab.load_steps()

        self.test_tabs[test.id] = test_tab
        tab_index = self.tab_widget.addTab(test_tab, test.id)
        self.tab_widget.setCurrentIndex(tab_index)

        # Enable run button
        self.run_action.setEnabled(not self.running_test)
        self.statusBar().showMessage(f"Opened test: {test.id}")

    def _open_suite_tab(self, suite: TestSuite):
        """Open a suite in a new tab."""
        # Check if already open
        if suite.name in self.suite_tabs:
            existing_tab = self.suite_tabs[suite.name]
            index = self.tab_widget.indexOf(existing_tab)
            self.tab_widget.setCurrentIndex(index)
            return

        # Create new suite tab
        suite_tab = SuiteRunnerWidget(suite, self.test_root, self.hardware_config_path, self)

        self.suite_tabs[suite.name] = suite_tab
        tab_index = self.tab_widget.addTab(suite_tab, f"📋 {suite.name}")
        self.tab_widget.setCurrentIndex(tab_index)

        # Enable run suite button
        self.run_suite_action.setEnabled(not self.running_test)
        self.statusBar().showMessage(f"Opened suite: {suite.name}")

    def _close_test_tab(self, index: int):
        """Close a test or suite tab."""
        if index == 0:  # Don't close the test list tab
            return

        widget = self.tab_widget.widget(index)
        if isinstance(widget, TestTabWidget):
            test_id = widget.test.id
            if test_id in self.test_tabs:
                del self.test_tabs[test_id]
        elif isinstance(widget, SuiteRunnerWidget):
            suite_name = widget.suite.name
            if suite_name in self.suite_tabs:
                del self.suite_tabs[suite_name]

        self.tab_widget.removeTab(index)

        # Disable run buttons if no tabs open
        if len(self.test_tabs) == 0:
            self.run_action.setEnabled(False)
        if len(self.suite_tabs) == 0:
            self.run_suite_action.setEnabled(False)

    def _run_selected_test(self):
        """Run the currently selected test tab."""
        current_widget = self.tab_widget.currentWidget()

        if not isinstance(current_widget, TestTabWidget) or self.running_test:
            return

        self.running_test = True
        self.run_action.setEnabled(False)
        self.run_suite_action.setEnabled(False)

        current_widget.reset_for_run()
        self.statusBar().showMessage(f"Running test: {current_widget.test.id}")

        # Run test in background thread
        run_test_in_thread(
            current_widget.test,
            self.event_bridge.event_received.emit,
            self.event_bridge.log_line_received.emit,
            lambda exit_code, report_path: self.event_bridge.test_finished.emit(exit_code, "", report_path),
            self.hardware_config_path
        )

    def _run_test_tab(self, test_widget: TestTabWidget):
        """Run a specific test tab (called from the tab's run button)."""
        if self.running_test:
            return

        self.running_test = True
        self.run_action.setEnabled(False)
        self.run_suite_action.setEnabled(False)

        test_widget.reset_for_run()
        self.statusBar().showMessage(f"Running test: {test_widget.test.id}")

        # Run test in background thread
        run_test_in_thread(
            test_widget.test,
            self.event_bridge.event_received.emit,
            self.event_bridge.log_line_received.emit,
            lambda exit_code, report_path: self.event_bridge.test_finished.emit(exit_code, "", report_path),
            self.hardware_config_path
        )

    @Slot(dict)
    def _handle_event(self, event: Dict[str, Any]):
        """Handle a reporter event (thread-safe)."""
        current_widget = self.tab_widget.currentWidget()
        if not isinstance(current_widget, TestTabWidget):
            return

        event_type = event.get("type")

        if event_type == "step_start":
            step_id = event.get("step_id", "")
            current_widget.update_step_status(step_id, StepStatus.RUNNING)

        elif event_type == "log_message":
            level = event.get("level", "")
            message = event.get("message", "")

            # Extract step ID from message
            import re
            match = re.match(r"((?:PRE-STEP|STEP|POST-STEP|TEARDOWN)\s+[\d.]+)", message)
            if match:
                step_id = match.group(1)
                if level == "PASS":
                    current_widget.update_step_status(step_id, StepStatus.PASS)
                elif level == "FAIL":
                    current_widget.update_step_status(step_id, StepStatus.FAIL)
                    current_widget.error_messages.append(message)

    @Slot(str)
    def _handle_log_line(self, line: str):
        """Handle a log line (thread-safe)."""
        current_widget = self.tab_widget.currentWidget()
        if isinstance(current_widget, TestTabWidget):
            current_widget.append_log(line)

    @Slot(int, str, str)
    def _handle_test_finished(self, exit_code: int, error_msg: str, report_path: str):
        """Handle test completion (thread-safe)."""
        self.running_test = False

        current_widget = self.tab_widget.currentWidget()
        if isinstance(current_widget, TestTabWidget):
            passed = exit_code == 0
            error_text = "\n".join(current_widget.error_messages) if current_widget.error_messages else error_msg
            current_widget.set_test_status(passed, error_text)

            # Set report path and enable button
            if report_path:
                current_widget.report_path = report_path
                current_widget.view_report_btn.setEnabled(True)

            result_text = "PASS" if passed else "FAIL"
            self.statusBar().showMessage(f"Test finished: {result_text}")

            # Finish test and reset button states
            current_widget._finish_test(exit_code, report_path)

        # Re-enable run actions based on current tab
        self._on_tab_changed(self.tab_widget.currentIndex())

    def _run_selected_suite(self):
        """Run the currently selected suite tab."""
        current_widget = self.tab_widget.currentWidget()

        if not isinstance(current_widget, SuiteRunnerWidget) or self.running_test:
            return

        self.running_test = True
        self.run_suite_action.setEnabled(False)
        self.run_action.setEnabled(False)
        self.generate_report_action.setEnabled(False)

        current_widget.start_suite()
        self.statusBar().showMessage(f"Running suite: {current_widget.suite.name}")

    def _create_new_suite(self):
        """Create a new test suite."""
        if not self.test_root or not self.tests:
            return

        suites_dir = self.test_root.parent / "test_suites"
        suites_dir.mkdir(parents=True, exist_ok=True)

        dialog = SuiteEditorDialog(self.tests, default_save_dir=suites_dir, parent=self)
        if dialog.exec():
            self._refresh_tests()

    def _edit_selected_suite(self):
        """Edit the selected suite."""
        # Get selected item from suites tree
        current_item = self.suites_tree.currentItem()
        if not current_item:
            return

        data = current_item.data(0, Qt.UserRole)
        if not isinstance(data, TestSuite):
            return

        suites_dir = self.test_root.parent / "test_suites" if self.test_root else Path.cwd()

        dialog = SuiteEditorDialog(self.tests, suite=data, default_save_dir=suites_dir, parent=self)
        if dialog.exec():
            self._refresh_tests()

    def _on_suite_selection_changed(self):
        """Handle suite selection change."""
        current_item = self.suites_tree.currentItem()
        if current_item:
            data = current_item.data(0, Qt.UserRole)
            self.edit_suite_action.setEnabled(isinstance(data, TestSuite))
        else:
            self.edit_suite_action.setEnabled(False)

    def _on_tab_changed(self, index: int):
        """Handle tab change to update menu item states."""
        if index < 0:
            self.run_action.setEnabled(False)
            self.run_suite_action.setEnabled(False)
            self.generate_report_action.setEnabled(False)
            return

        current_widget = self.tab_widget.widget(index)

        # Enable/disable run actions based on tab type
        if isinstance(current_widget, TestTabWidget):
            self.run_action.setEnabled(not self.running_test)
            self.run_suite_action.setEnabled(False)
            self.generate_report_action.setEnabled(False)
        elif isinstance(current_widget, SuiteRunnerWidget):
            self.run_action.setEnabled(False)
            self.run_suite_action.setEnabled(not self.running_test)
            self.generate_report_action.setEnabled(not current_widget.running)
        else:
            self.run_action.setEnabled(False)
            self.run_suite_action.setEnabled(False)
            self.generate_report_action.setEnabled(False)

    def _set_reports_directory(self):
        """Set the reports directory."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Reports Directory",
            str(self.reports_dir)
        )

        if directory:
            self.reports_dir = Path(directory)
            self.settings.setValue("reports_dir", str(self.reports_dir))
            self.reports_label.setText(f"Reports: {self.reports_dir}")
            self.statusBar().showMessage(f"Reports directory set to: {self.reports_dir}")

    def _generate_suite_report(self):
        """Generate comprehensive suite report."""
        current_widget = self.tab_widget.currentWidget()

        if not isinstance(current_widget, SuiteRunnerWidget):
            return

        if not current_widget.test_results:
            QMessageBox.information(self, "No Results", "No test results available. Please run the suite first.")
            return

        suite_name = current_widget.suite.name
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_base = f"test_suite_{suite_name.replace(' ', '_')}_{timestamp}"

        try:
            # Ensure reports directory exists
            self.reports_dir.mkdir(parents=True, exist_ok=True)

            # Generate HTML report
            html_path = self.reports_dir / f"{report_base}.html"
            self._generate_html_suite_report(current_widget, html_path)

            # Generate JSON report
            json_path = self.reports_dir / f"{report_base}.json"
            self._generate_json_suite_report(current_widget, json_path)

            # Generate JUnit XML report
            xml_path = self.reports_dir / f"{report_base}.xml"
            self._generate_junit_suite_report(current_widget, xml_path)

            QMessageBox.information(
                self,
                "Reports Generated",
                f"Suite reports generated:\n\nHTML: {html_path.name}\nJSON: {json_path.name}\nXML: {xml_path.name}"
            )

            # Offer to open HTML report
            reply = QMessageBox.question(
                self,
                "Open Report",
                "Would you like to open the HTML report?",
                QMessageBox.Yes | QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                webbrowser.open(f"file://{html_path}")

        except Exception as e:
            QMessageBox.critical(self, "Report Generation Failed", f"Failed to generate reports:\n{e}")

    def _generate_html_suite_report(self, suite_widget: SuiteRunnerWidget, output_path: Path):
        """Generate HTML report for suite."""
        import html
        import socket
        import platform
        import sys

        suite = suite_widget.suite
        results = []

        for test_metadata in suite_widget.all_tests_metadata:
            test_id = test_metadata.id
            if test_id in suite_widget.test_results:
                exit_code, duration, report_path = suite_widget.test_results[test_id]
                results.append({
                    'name': test_metadata.id,
                    'path': str(test_metadata.relative_path),
                    'status': 'PASS' if exit_code == 0 else 'FAIL',
                    'exit_code': exit_code,
                    'duration': duration
                })

        total = len(results)
        passed = sum(1 for r in results if r['status'] == 'PASS')
        failed = sum(1 for r in results if r['status'] == 'FAIL')
        total_duration = sum(r['duration'] for r in results)
        overall_status = 'PASS' if failed == 0 else 'FAIL'

        session_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        start_time = datetime.now()

        css = """
        body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif;background:#0f1216;color:#e7eaf0;margin:0}
        header{padding:20px;background:#151a21;border-bottom:1px solid #2a2f37}
        h1{margin:0;font-size:20px}
        .meta{font-size:12px;color:#a6adbb;margin-top:6px}
        .summary{display:flex;gap:16px;flex-wrap:wrap;margin:16px 0}
        .chip{padding:8px 12px;border-radius:20px;border:1px solid #2a2f37;background:#151a21}
        .chip.pass{border-color:#1e7f45;color:#d7ffe6;background:#0e2017}
        .chip.fail{border-color:#a23b3b;color:#ffe1e1;background:#210e0e}
        main{padding:20px}
        table{width:100%;border-collapse:collapse;margin-top:8px}
        th,td{border-bottom:1px solid #1f2530;padding:8px 6px;text-align:left;font-size:13px}
        th{color:#a6adbb;font-weight:600;background:#131820}
        tr.pass{background:#0e2017}
        tr.fail{background:#210e0e}
        .status{padding:3px 8px;border-radius:12px;border:1px solid #2a2f37;font-size:12px;font-weight:600}
        .status.pass{border-color:#1e7f45;color:#d7ffe6;background:#0e2017}
        .status.fail{border-color:#a23b3b;color:#ffe1e1;background:#210e0e}
        .kv{display:grid;grid-template-columns:180px 1fr;gap:8px;margin-top:10px}
        """

        html_lines = []
        html_lines.append("<!DOCTYPE html><html><head><meta charset='utf-8'>")
        html_lines.append("<meta name='viewport' content='width=device-width, initial-scale=1'>")
        html_lines.append(f"<title>Test Suite Report - {html.escape(suite.name)}</title>")
        html_lines.append(f"<style>{css}</style></head><body>")

        # Header
        html_lines.append("<header>")
        html_lines.append(f"<h1>Test Suite: {html.escape(suite.name)}</h1>")
        html_lines.append("<div class='meta'>")
        status_class = 'pass' if overall_status == 'PASS' else 'fail'
        html_lines.append(f"Overall: <b class='chip {status_class}'>{html.escape(overall_status)}</b> &nbsp;")
        html_lines.append(f"Started: {html.escape(start_time.strftime('%Y-%m-%d %H:%M:%S'))} &nbsp;")
        html_lines.append(f"Duration: {total_duration:.2f}s &nbsp;")
        html_lines.append(f"Session ID: {html.escape(session_id)} &nbsp;")
        if suite.description:
            html_lines.append(f"<br>{html.escape(suite.description)}")
        html_lines.append("</div>")
        html_lines.append("</header>")

        # Summary
        html_lines.append("<main>")
        html_lines.append("<section class='summary'>")
        html_lines.append(f"<div class='chip pass'>Passed: {passed}</div>")
        html_lines.append(f"<div class='chip fail'>Failed: {failed}</div>")
        html_lines.append(f"<div class='chip'>Total: {total}</div>")
        html_lines.append("</section>")

        # Test Results Table
        html_lines.append("<section>")
        html_lines.append("<h3>Test Results</h3>")
        html_lines.append("<table>")
        html_lines.append("<tr><th>#</th><th>Test Name</th><th>Status</th><th>Duration</th></tr>")

        for idx, result in enumerate(results, 1):
            status = result['status']
            status_class = status.lower()
            duration_str = f"{result.get('duration', 0):.2f}s"

            html_lines.append(f"<tr class='{status_class}'>")
            html_lines.append(f"<td>{idx}</td>")
            html_lines.append(f"<td>{html.escape(result['name'])}</td>")
            html_lines.append(f"<td><span class='status {status_class}'>{html.escape(status)}</span></td>")
            html_lines.append(f"<td>{duration_str}</td>")
            html_lines.append("</tr>")

        html_lines.append("</table>")
        html_lines.append("</section>")

        # Environment info
        html_lines.append("<section>")
        html_lines.append("<h3>Environment</h3>")
        html_lines.append("<div class='kv'>")
        html_lines.append(f"<div>Session ID</div><div><code>{html.escape(session_id)}</code></div>")
        html_lines.append(f"<div>Hostname</div><div>{html.escape(socket.gethostname())}</div>")
        html_lines.append(f"<div>OS</div><div>{html.escape(platform.system())} {html.escape(platform.release())}</div>")
        html_lines.append(f"<div>Python</div><div>{html.escape(sys.version.split()[0])}</div>")
        html_lines.append(f"<div>Suite</div><div>{html.escape(suite.name)}</div>")
        html_lines.append(f"<div>Reports Dir</div><div>{html.escape(str(self.reports_dir.absolute()))}</div>")
        html_lines.append("</div>")
        html_lines.append("</section>")

        html_lines.append("</main>")
        html_lines.append("</body></html>")

        output_path.write_text("\n".join(html_lines), encoding='utf-8')

    def _generate_json_suite_report(self, suite_widget: SuiteRunnerWidget, output_path: Path):
        """Generate JSON report for suite."""
        suite = suite_widget.suite
        results = []

        for test_metadata in suite_widget.all_tests_metadata:
            test_id = test_metadata.id
            if test_id in suite_widget.test_results:
                exit_code, duration, report_path = suite_widget.test_results[test_id]
                results.append({
                    'name': test_metadata.id,
                    'path': str(test_metadata.relative_path),
                    'status': 'PASS' if exit_code == 0 else 'FAIL',
                    'exit_code': exit_code,
                    'duration': duration
                })

        total_tests = len(results)
        passed = sum(1 for r in results if r['status'] == 'PASS')
        failed = total_tests - passed
        total_duration = sum(r['duration'] for r in results)

        report_data = {
            'suite_name': suite.name,
            'description': suite.description,
            'started_at': datetime.now().isoformat(),
            'duration': total_duration,
            'total_tests': total_tests,
            'passed': passed,
            'failed': failed,
            'skipped': 0,
            'timeout': 0,
            'error': 0,
            'results': results
        }

        output_path.write_text(json.dumps(report_data, indent=2), encoding='utf-8')

    def _generate_junit_suite_report(self, suite_widget: SuiteRunnerWidget, output_path: Path):
        """Generate JUnit XML report for suite."""
        suite = suite_widget.suite
        results = []

        for test_metadata in suite_widget.all_tests_metadata:
            test_id = test_metadata.id
            if test_id in suite_widget.test_results:
                exit_code, duration, report_path = suite_widget.test_results[test_id]
                results.append({
                    'name': test_metadata.id,
                    'status': 'PASS' if exit_code == 0 else 'FAIL',
                    'exit_code': exit_code,
                    'duration': duration
                })

        total = len(results)
        failures = sum(1 for r in results if r['status'] == 'FAIL')
        total_duration = sum(r['duration'] for r in results)

        def xml_escape(s: str) -> str:
            return (s.replace("&", "&amp;")
                     .replace("<", "&lt;")
                     .replace(">", "&gt;")
                     .replace('"', "&quot;")
                     .replace("'", "&apos;"))

        lines = []
        lines.append('<?xml version="1.0" encoding="UTF-8"?>')
        lines.append(f'<testsuite name="{xml_escape(suite.name)}" tests="{total}" failures="{failures}" skipped="0" time="{total_duration:.3f}">')

        for result in results:
            test_name = result['name']
            test_duration = result.get('duration', 0)
            status = result['status']

            lines.append(f'  <testcase classname="TestSuite" name="{xml_escape(test_name)}" time="{test_duration:.3f}">')

            if status == 'FAIL':
                message = f"Test failed (exit code: {result['exit_code']})"
                lines.append(f'    <failure message="{xml_escape(message)}"/>')

            lines.append('  </testcase>')

        lines.append('</testsuite>')

        output_path.write_text("\n".join(lines), encoding='utf-8')
