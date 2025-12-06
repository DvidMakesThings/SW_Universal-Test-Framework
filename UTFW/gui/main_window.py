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

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QTreeWidget, QTreeWidgetItem, QTableWidget,
    QTableWidgetItem, QTextEdit, QLabel, QFileDialog, QHeaderView,
    QGroupBox, QToolBar, QMessageBox, QTabWidget, QRadioButton, QFrame
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer, Slot
from PySide6.QtGui import QColor, QFont, QAction, QTextCursor, QIcon

from .model import (
    discover_tests, build_step_model, run_test_in_thread,
    TestMetadata, TestStepModel, StepInfo
)


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
        self.error_messages: List[str] = []
        self.report_path: Optional[str] = None

        # Timer for updating running step durations
        self.duration_timer = QTimer(self)
        self.duration_timer.timeout.connect(self._update_durations)
        self.duration_timer.setInterval(100)  # Update every 100ms

        self._setup_ui()

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
        status_layout.addWidget(self.status_label)

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
        self.steps_table.setColumnCount(7)
        self.steps_table.setHorizontalHeaderLabels([
            "Phase", "Step ID", "Description", "Negative", "Expected", "Result", "Duration"
        ])
        self.steps_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.steps_table.horizontalHeader().setStretchLastSection(False)
        self.steps_table.setColumnWidth(0, 100)
        self.steps_table.setColumnWidth(1, 100)
        self.steps_table.setColumnWidth(2, 500)
        self.steps_table.setColumnWidth(3, 80)
        self.steps_table.setColumnWidth(4, 200)
        self.steps_table.setColumnWidth(5, 80)
        self.steps_table.setColumnWidth(6, 100)
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

            negative_text = "Yes" if step.negative else "No"
            self.steps_table.setItem(idx, 3, QTableWidgetItem(negative_text))

            expected_text = self._format_expected(step.metadata)
            self.steps_table.setItem(idx, 4, QTableWidgetItem(expected_text))

            result_item = QTableWidgetItem(StepStatus.PENDING.value)
            self.steps_table.setItem(idx, 5, result_item)

            self.steps_table.setItem(idx, 6, QTableWidgetItem(""))

            self.step_status[step.step_label] = StepStatus.PENDING

    def _format_expected(self, metadata: Dict[str, Any]) -> str:
        """Format expected values from metadata."""
        parts = []

        if "expected_state" in metadata:
            state = "ON" if metadata['expected_state'] else "OFF"
            parts.append(f"State: {state}")

        # Check for expected value (either "expected" or "expected_value")
        expected_key = None
        if "expected" in metadata and "expected_state" not in metadata:
            expected_key = "expected"
        elif "expected_value" in metadata and "expected_state" not in metadata:
            expected_key = "expected_value"

        if expected_key:
            expected_val = metadata[expected_key]
            # Format lists nicely
            if isinstance(expected_val, list):
                if len(expected_val) <= 4:
                    parts.append(f"= {expected_val}")
                else:
                    parts.append(f"= [{len(expected_val)} items]")
            else:
                parts.append(f"= {expected_val}")

        if "min_val" in metadata and "max_val" in metadata:
            parts.append(f"[{metadata['min_val']}, {metadata['max_val']}]")
        elif "min_val" in metadata:
            parts.append(f">= {metadata['min_val']}")
        elif "max_val" in metadata:
            parts.append(f"<= {metadata['max_val']}")

        # Extract expected values from command strings
        if "command" in metadata and not parts:
            command = str(metadata['command'])
            # For CONFIG_NETWORK commands, extract the network parameters
            if "CONFIG_NETWORK" in command:
                # Format: CONFIG_NETWORK IP$SUBNET$GATEWAY$DNS
                params = command.replace("CONFIG_NETWORK ", "").split("$")
                if len(params) >= 1:
                    parts.append(f"IP: {params[0]}")
            # For SET_CH commands, extract channel and state
            elif "SET_CH" in command:
                parts_cmd = command.split()
                if len(parts_cmd) >= 3:
                    parts.append(f"CH{parts_cmd[1]}: {parts_cmd[2]}")

        # Show expected_value if present (for validate_tokens and similar)
        if "expected_value" in metadata:
            parts.append(f"= {metadata['expected_value']}")

        # Show tokens if present
        if "tokens" in metadata:
            tokens = metadata['tokens']
            if isinstance(tokens, list) and len(tokens) <= 3:
                tokens_str = ", ".join(str(t) for t in tokens)
                parts.append(f"Tokens: {tokens_str}")

        return ", ".join(parts) if parts else "-"

    def update_step_status(self, step_id: str, status: StepStatus):
        """Update a step's status and color."""
        if not self.model or step_id not in self.step_status:
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

        self._update_table_display()

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

        all_steps = (
            self.model.pre_steps +
            self.model.main_steps +
            self.model.post_steps +
            self.model.teardown_steps
        )

        running_row = None

        for idx, step in enumerate(all_steps):
            status = self.step_status.get(step.step_label, StepStatus.PENDING)
            result_item = self.steps_table.item(idx, 5)
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
            duration_item = self.steps_table.item(idx, 6)

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
        """Append a log line."""
        self.log_output.append(line)
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_output.setTextCursor(cursor)

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

        self.status_label.setText("Running...")
        self.status_label.setStyleSheet(
            "background-color: #ffc107; color: black; padding: 10px; border-radius: 5px;"
        )

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
                duration_item = self.steps_table.item(idx, 6)
                if duration_item:
                    duration_item.setText("-")

        self._update_table_display()


class MainWindow(QMainWindow):
    """Main window for UTFW GUI."""

    def __init__(self, default_test_root: Optional[Path] = None):
        super().__init__()

        self.test_root: Optional[Path] = default_test_root
        self.hardware_config_path: Optional[Path] = None
        self.tests: List[TestMetadata] = []
        self.test_tabs: Dict[str, TestTabWidget] = {}
        self.running_test: bool = False

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

        # Tab widget as main content
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self._close_test_tab)
        layout.addWidget(self.tab_widget)

        # Create test list tab (always first)
        self._create_test_list_tab()

        # Toolbar
        self._create_toolbar()

        # Status bar
        self.statusBar().showMessage("Ready")

        # Add permanent hardware config label to status bar
        self.hwconfig_label = QLabel("HW Config: None")
        self.statusBar().addPermanentWidget(self.hwconfig_label)

    def _create_toolbar(self):
        """Create the toolbar."""
        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(toolbar)

        select_root_action = QAction("Select Test Root", self)
        select_root_action.triggered.connect(self._select_test_root)
        toolbar.addAction(select_root_action)

        select_hwconfig_action = QAction("Select Hardware Config", self)
        select_hwconfig_action.triggered.connect(self._select_hardware_config)
        toolbar.addAction(select_hwconfig_action)

        refresh_action = QAction("Refresh Tests", self)
        refresh_action.triggered.connect(self._refresh_tests)
        toolbar.addAction(refresh_action)

        toolbar.addSeparator()

        # Run test action with play icon
        self.run_action = QAction("▶ Run Selected Test", self)
        self.run_action.triggered.connect(self._run_selected_test)
        self.run_action.setEnabled(False)
        toolbar.addAction(self.run_action)

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

        self.test_tree = QTreeWidget()
        self.test_tree.setHeaderLabel("Test")
        self.test_tree.itemDoubleClicked.connect(self._on_test_double_clicked)
        layout.addWidget(self.test_tree)

        help_label = QLabel("Double-click a test to open it in a new tab")
        help_label.setStyleSheet("color: gray; font-style: italic; padding: 5px;")
        layout.addWidget(help_label)

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

        self.statusBar().showMessage("Discovering tests...")

        try:
            self.tests = discover_tests(self.test_root)
            self._populate_test_tree()
            self.test_info_label.setText(f"Found {len(self.tests)} test(s) in {self.test_root}")
            self.statusBar().showMessage(f"Found {len(self.tests)} tests")
        except Exception as e:
            self.statusBar().showMessage(f"Error discovering tests: {e}")
            QMessageBox.warning(self, "Discovery Error", f"Failed to discover tests:\n{e}")

    def _populate_test_tree(self):
        """Populate the test tree with discovered tests."""
        self.test_tree.clear()

        for test in self.tests:
            item = QTreeWidgetItem([test.id])
            item.setData(0, Qt.UserRole, test)
            item.setToolTip(0, f"{test.description}\n{test.relative_path}")
            self.test_tree.addTopLevelItem(item)

    def _on_test_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle double-click on test to open in new tab."""
        test = item.data(0, Qt.UserRole)
        if not test:
            return

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

    def _close_test_tab(self, index: int):
        """Close a test tab."""
        if index == 0:  # Don't close the test list tab
            return

        widget = self.tab_widget.widget(index)
        if isinstance(widget, TestTabWidget):
            test_id = widget.test.id
            if test_id in self.test_tabs:
                del self.test_tabs[test_id]

        self.tab_widget.removeTab(index)

        # Disable run button if no test tabs open
        if len(self.test_tabs) == 0:
            self.run_action.setEnabled(False)

    def _run_selected_test(self):
        """Run the currently selected test tab."""
        current_widget = self.tab_widget.currentWidget()

        if not isinstance(current_widget, TestTabWidget):
            QMessageBox.information(self, "No Test Selected", "Please select a test tab to run.")
            return

        if self.running_test:
            return

        self.running_test = True
        self.run_action.setEnabled(False)

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
        self.run_action.setEnabled(True)

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
