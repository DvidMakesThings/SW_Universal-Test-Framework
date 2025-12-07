"""
UTFW GUI Suite Runner
=====================
Widget for running test suites with sequential test execution.
"""

from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
    QPushButton, QTextEdit, QFrame, QHeaderView, QMessageBox
)
from PySide6.QtCore import Qt, QObject, Signal, Slot
from PySide6.QtGui import QFont, QColor

from .suite_model import TestSuite, SuiteTestEntry
from .model import TestMetadata, discover_tests, build_step_model, run_test_in_thread


class SuiteEventBridge(QObject):
    """Qt signal bridge for thread-safe event handling in suite runner."""
    event_received = Signal(dict)
    log_line_received = Signal(str)
    test_completed = Signal(int, str, str)  # exit_code, error_message, report_path


class SuiteRunnerWidget(QWidget):
    """Widget for running a test suite."""

    def __init__(self, suite: TestSuite, tests_root: Path, hardware_config_path: Optional[Path] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.suite = suite
        self.tests_root = tests_root
        self.hardware_config_path = hardware_config_path
        self.running = False
        self.stop_requested = False
        self.current_test_index = 0
        self.test_results: Dict[str, tuple] = {}  # test_name -> (exit_code, duration, report_path)
        self.all_tests_metadata: List[TestMetadata] = []
        self.current_test_tab = None

        # Event bridge for thread-safe event handling
        self.event_bridge = SuiteEventBridge()
        self.event_bridge.event_received.connect(self._handle_test_event)
        self.event_bridge.log_line_received.connect(self._handle_test_log)
        self.event_bridge.test_completed.connect(self._on_test_complete)

        self._setup_ui()
        self._load_test_metadata()

    def _setup_ui(self):
        """Set up the suite runner UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Status bar at top (matching individual test style)
        self.status_frame = QFrame()
        self.status_frame.setFrameStyle(QFrame.Box | QFrame.Raised)
        self.status_frame.setLineWidth(2)
        self.status_frame.setMaximumHeight(60)
        status_layout = QHBoxLayout(self.status_frame)
        status_layout.setContentsMargins(5, 5, 5, 5)
        status_layout.setSpacing(5)

        self.status_label = QLabel("Ready to run")
        self.status_label.setFont(QFont("Arial", 16, QFont.Bold))
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("padding: 5px;")
        status_layout.addWidget(self.status_label, stretch=1)

        # Run button
        self.run_btn = QPushButton("▶ Run Test")
        self.run_btn.setStyleSheet("""
            QPushButton {
                background-color: #50fa7b;
                color: #000;
                font-weight: bold;
                font-size: 13px;
                padding: 6px 14px;
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
        self.run_btn.setFixedHeight(38)
        self.run_btn.clicked.connect(self.start_suite)
        status_layout.addWidget(self.run_btn)

        # Stop button
        self.stop_btn = QPushButton("■ Stop Run")
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff5555;
                color: #fff;
                font-weight: bold;
                font-size: 13px;
                padding: 6px 14px;
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
        self.stop_btn.setFixedHeight(38)
        self.stop_btn.setEnabled(False)  # Disabled initially
        self.stop_btn.clicked.connect(self.stop_suite)
        status_layout.addWidget(self.stop_btn)

        layout.addWidget(self.status_frame)

        # Suite info below status bar
        suite_info_layout = QHBoxLayout()
        # Build suite info, handle empty description gracefully
        if self.suite.description:
            suite_info = f"<b>{self.suite.name}</b><br>{self.suite.description}"
        else:
            suite_info = f"<b>{self.suite.name}</b>"
        suite_label = QLabel(suite_info)
        suite_label.setWordWrap(True)
        suite_label.setStyleSheet("color: gray; padding: 5px;")
        suite_info_layout.addWidget(suite_label, stretch=1)
        layout.addLayout(suite_info_layout)

        # Tests tree (collapsible and compact)
        tests_header_layout = QHBoxLayout()
        tree_label = QLabel("Tests in Suite:")
        tree_label.setFont(QFont("Arial", 9, QFont.Bold))
        tests_header_layout.addWidget(tree_label)

        self.toggle_tests_btn = QPushButton("▼ Hide")
        self.toggle_tests_btn.setMaximumWidth(80)
        self.toggle_tests_btn.clicked.connect(self._toggle_tests_list)
        tests_header_layout.addWidget(self.toggle_tests_btn)
        tests_header_layout.addStretch()

        layout.addLayout(tests_header_layout)

        self.tests_tree = QTreeWidget()
        self.tests_tree.setHeaderLabels(["Test", "Status", "Duration", "Result"])
        self.tests_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tests_tree.setColumnWidth(1, 120)
        self.tests_tree.setColumnWidth(2, 80)
        self.tests_tree.setColumnWidth(3, 80)
        self.tests_tree.setVisible(True)  # Visible by default
        layout.addWidget(self.tests_tree)

        # Current test details (collapsible)
        self.current_test_container = QWidget()
        self.current_test_layout = QVBoxLayout(self.current_test_container)
        self.current_test_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.current_test_container)

        # Summary (hidden initially)
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setVisible(False)
        layout.addWidget(self.summary_text)

    def _toggle_tests_list(self):
        """Toggle visibility of the tests list."""
        is_visible = self.tests_tree.isVisible()
        self.tests_tree.setVisible(not is_visible)
        self.toggle_tests_btn.setText("▲ Show" if is_visible else "▼ Hide")

    def _load_test_metadata(self):
        """Load metadata for all tests in the suite."""
        available_tests = discover_tests(self.tests_root)
        # Use test ID (directory name like tc_xxx) as key for simpler matching
        test_map_by_id = {t.id: t for t in available_tests}
        test_map_by_path = {t.relative_path: t for t in available_tests}

        for suite_test in self.suite.tests:
            if not suite_test.enabled:
                continue

            test_metadata = None

            # Method 1: Extract test directory name from path and match by ID
            path_parts = Path(suite_test.path).parts
            for part in path_parts:
                if part.startswith('tc_'):
                    if part in test_map_by_id:
                        test_metadata = test_map_by_id[part]
                        break

            # Method 2: Try direct path match after stripping "tests/" prefix
            if not test_metadata:
                test_path = suite_test.path
                if test_path.startswith("tests/"):
                    test_path = test_path[6:]
                if test_path in test_map_by_path:
                    test_metadata = test_map_by_path[test_path]

            if test_metadata:
                self.all_tests_metadata.append(test_metadata)
                item = QTreeWidgetItem([
                    suite_test.name,
                    "PENDING",
                    "",
                    ""
                ])
                item.setForeground(1, QColor(150, 150, 150))
                self.tests_tree.addTopLevelItem(item)

        # Dynamically adjust height based on number of tests
        self._adjust_tree_height()

    def _adjust_tree_height(self):
        """Adjust the tree widget height to fit all tests."""
        if self.tests_tree.topLevelItemCount() == 0:
            return

        # Calculate height: header + (row_height * num_rows) + margins
        header_height = self.tests_tree.header().height()
        row_height = self.tests_tree.sizeHintForRow(0)
        if row_height <= 0:
            row_height = 25  # Default row height

        num_rows = self.tests_tree.topLevelItemCount()
        total_height = header_height + (row_height * num_rows) + 4  # +4 for margins

        # Set reasonable min/max bounds
        min_height = header_height + row_height + 4  # At least one row
        max_height = 400  # Don't let it grow too large

        adjusted_height = max(min_height, min(total_height, max_height))
        self.tests_tree.setMinimumHeight(adjusted_height)
        self.tests_tree.setMaximumHeight(adjusted_height)

    def _adjust_summary_height(self):
        """Adjust the summary text widget height to fit content."""
        # Get the document's ideal height
        doc = self.summary_text.document()
        doc_height = doc.size().height()

        # Add some padding for margins and scrollbar
        content_height = int(doc_height) + 20

        # Set reasonable bounds
        min_height = 150  # Minimum readable height
        max_height = 600  # Don't let it dominate the screen

        adjusted_height = max(min_height, min(content_height, max_height))
        self.summary_text.setMinimumHeight(adjusted_height)
        self.summary_text.setMaximumHeight(adjusted_height)

    def start_suite(self):
        """Start running the test suite."""
        if self.running:
            return

        self.running = True
        self.stop_requested = False
        self.current_test_index = 0
        self.test_results.clear()
        self.summary_text.setVisible(False)
        self.status_label.setText("Running...")
        self.status_label.setStyleSheet(
            "background-color: #ffc107; color: black; padding: 5px; border-radius: 5px;"
        )

        # Update button states
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        # Show the tests tree during execution
        if not self.tests_tree.isVisible():
            self.tests_tree.setVisible(True)
            self.toggle_tests_btn.setText("▼ Hide")

        # Reset all test statuses
        for i in range(self.tests_tree.topLevelItemCount()):
            item = self.tests_tree.topLevelItem(i)
            if item:
                item.setText(1, "PENDING")
                item.setText(2, "")
                item.setText(3, "")
                item.setForeground(1, QColor(150, 150, 150))
                # Clear background
                for col in range(4):
                    item.setBackground(col, QColor(45, 45, 48))

        self._run_next_test()

    def stop_suite(self):
        """Stop the test suite execution.

        The currently running test will complete (including teardown),
        then the suite will stop and show results."""
        if not self.running:
            return

        self.stop_requested = True
        self.status_label.setText("Stopping after current test...")
        self.status_label.setStyleSheet(
            "background-color: #ff9f00; color: black; padding: 5px; border-radius: 5px;"
        )
        self.stop_btn.setEnabled(False)

    def _run_next_test(self):
        """Run the next test in the suite."""
        # Check if stop was requested
        if self.stop_requested:
            self._finish_suite()
            return

        if self.current_test_index >= len(self.all_tests_metadata):
            self._finish_suite()
            return

        test_metadata = self.all_tests_metadata[self.current_test_index]

        # Update tree item with color coding
        item = self.tests_tree.topLevelItem(self.current_test_index)
        if item:
            item.setText(1, "RUNNING")
            item.setForeground(1, QColor(255, 200, 0))
            # Yellow background for running test
            for col in range(4):
                item.setBackground(col, QColor(80, 70, 20))
            self.tests_tree.scrollToItem(item)

        # Import here to avoid circular dependency
        from .main_window import TestTabWidget

        # Clean up previous test tab
        if self.current_test_tab:
            self.current_test_tab.cleanup()

        # Clear previous test from layout
        while self.current_test_layout.count():
            child = self.current_test_layout.takeAt(0)
            if child.widget():
                widget = child.widget()
                widget.setParent(None)
                widget.deleteLater()

        # Create and add new test tab
        self.current_test_tab = TestTabWidget(test_metadata, self.hardware_config_path)
        self.current_test_layout.addWidget(self.current_test_tab)

        # Ensure tests tree remains visible
        self.tests_tree.setVisible(True)

        # Load and run test
        self.current_test_tab.load_steps()
        self.current_test_tab.reset_for_run()

        # Run test in background thread
        from .model import run_test_in_thread

        def on_event(event):
            # Use signal for thread-safe event forwarding
            self.event_bridge.event_received.emit(event)

        def on_log(line):
            # Use signal for thread-safe log forwarding
            self.event_bridge.log_line_received.emit(line)

        def on_complete(exit_code, report_path):
            # Use signal for thread-safe completion handling
            self.event_bridge.test_completed.emit(exit_code, "", report_path)

        run_test_in_thread(
            test_metadata,
            on_event,
            on_log,
            on_complete,
            self.hardware_config_path
        )

    @Slot(dict)
    def _handle_test_event(self, event: dict):
        """Handle test event in GUI thread."""
        if self.current_test_tab:
            self.current_test_tab._handle_event_direct(event)

    @Slot(str)
    def _handle_test_log(self, line: str):
        """Handle log line in GUI thread."""
        if self.current_test_tab:
            self.current_test_tab.append_log(line)

    @Slot(int, str, str)
    def _on_test_complete(self, exit_code: int, error_msg: str, report_path: str):
        """Handle completion of a single test (called via signal from background thread)."""
        test_metadata = self.all_tests_metadata[self.current_test_index]
        item = self.tests_tree.topLevelItem(self.current_test_index)

        # Calculate duration
        duration = 0.0
        if self.current_test_tab and self.current_test_tab.step_durations:
            duration = sum(self.current_test_tab.step_durations.values())

        # Store result
        self.test_results[test_metadata.id] = (exit_code, duration, report_path)

        # Update tree item with color coding
        if item:
            status = "PASS" if exit_code == 0 else "FAIL"
            item.setText(1, status)
            item.setText(2, f"{duration:.2f}s")
            item.setText(3, "✓" if exit_code == 0 else "✗")

            if exit_code == 0:
                # Green for PASS
                item.setForeground(1, QColor(100, 255, 100))
                item.setForeground(3, QColor(100, 255, 100))
                for col in range(4):
                    item.setBackground(col, QColor(20, 60, 20))
            else:
                # Red for FAIL
                item.setForeground(1, QColor(255, 100, 100))
                item.setForeground(3, QColor(255, 100, 100))
                for col in range(4):
                    item.setBackground(col, QColor(60, 20, 20))

        # Ensure tests tree remains visible
        self.tests_tree.setVisible(True)
        self.tests_tree.scrollToItem(item)

        # Move to next test
        self.current_test_index += 1

        # Check if stop was requested
        if self.stop_requested:
            # Mark remaining tests as not run
            for i in range(self.current_test_index, self.tests_tree.topLevelItemCount()):
                remaining_item = self.tests_tree.topLevelItem(i)
                if remaining_item:
                    remaining_item.setText(1, "NOT RUN")
                    remaining_item.setForeground(1, QColor(150, 150, 150))
            self._finish_suite()
        else:
            self._run_next_test()

    def _finish_suite(self):
        """Finish suite execution and show summary."""
        self.running = False

        # Reset button states
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        # Notify parent window that suite is complete
        parent_window = self.parent()
        while parent_window and not hasattr(parent_window, 'running_test'):
            parent_window = parent_window.parent()

        if parent_window and hasattr(parent_window, 'running_test'):
            parent_window.running_test = False
            # Trigger tab changed to update menu states
            if hasattr(parent_window, '_on_tab_changed') and hasattr(parent_window, 'tab_widget'):
                parent_window._on_tab_changed(parent_window.tab_widget.currentIndex())

        # Calculate summary
        total_tests_in_suite = len(self.all_tests_metadata)
        total_tests = len(self.test_results)
        passed_tests = sum(1 for code, _, _ in self.test_results.values() if code == 0)
        failed_tests = total_tests - passed_tests
        total_duration = sum(dur for _, dur, _ in self.test_results.values())

        # Update status
        if self.stop_requested:
            self.status_label.setText(f"⏹ STOPPED ({total_tests}/{total_tests_in_suite} completed)")
            self.status_label.setStyleSheet(
                "background-color: #ff9f00; color: black; padding: 5px; border-radius: 5px;"
            )
        elif failed_tests == 0:
            self.status_label.setText(f"✓ PASSED ({total_tests}/{total_tests})")
            self.status_label.setStyleSheet(
                "background-color: #28a745; color: white; padding: 5px; border-radius: 5px;"
            )
        else:
            self.status_label.setText(f"✗ FAILED ({passed_tests}/{total_tests})")
            self.status_label.setStyleSheet(
                "background-color: #dc3545; color: white; padding: 5px; border-radius: 5px;"
            )

        # Show summary
        summary = f"<h3>Suite Summary: {self.suite.name}</h3>"
        if self.stop_requested:
            not_run = total_tests_in_suite - total_tests
            summary += '<p style="color: #ff9f00;"><b>⚠ Suite was stopped manually</b></p>'
            summary += f"<p><b>Tests in Suite:</b> {total_tests_in_suite}<br>"
            summary += f"<b>Tests Completed:</b> {total_tests}<br>"
            summary += f"<b>Passed:</b> {passed_tests}<br>"
            summary += f"<b>Failed:</b> {failed_tests}<br>"
            summary += f"<b>Not Run:</b> {not_run}<br>"
            summary += f"<b>Total Duration:</b> {total_duration:.2f}s</p>"
        else:
            summary += f"<p><b>Total Tests:</b> {total_tests}<br>"
            summary += f"<b>Passed:</b> {passed_tests}<br>"
            summary += f"<b>Failed:</b> {failed_tests}<br>"
            summary += f"<b>Total Duration:</b> {total_duration:.2f}s</p>"
        summary += "<hr><h4>Test Results:</h4><ul>"

        for test_name, (exit_code, duration, report_path) in self.test_results.items():
            status = "✓ PASS" if exit_code == 0 else "✗ FAIL"
            color = "green" if exit_code == 0 else "red"
            summary += f'<li><span style="color: {color}; font-weight: bold;">{status}</span> '
            summary += f'{test_name} ({duration:.2f}s)</li>'

        summary += "</ul>"

        self.summary_text.setHtml(summary)
        self._adjust_summary_height()  # Dynamically adjust height based on content
        self.summary_text.setVisible(True)

        # Minimize current test
        if self.current_test_tab:
            self.current_test_tab.setVisible(False)

    def get_suite_summary(self) -> str:
        """Get text summary of suite results."""
        if not self.test_results:
            return "No tests run"

        total = len(self.test_results)
        passed = sum(1 for code, _, _ in self.test_results.values() if code == 0)
        failed = total - passed

        return f"{passed}/{total} passed, {failed}/{total} failed"
