"""
UTFW GUI Suite Editor
=====================
Graphical editor for creating and modifying test suite YAML files.
"""

from pathlib import Path
from typing import Optional, List

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTextEdit, QPushButton, QListWidget, QListWidgetItem,
    QComboBox, QSpinBox, QCheckBox, QGroupBox, QMessageBox,
    QFileDialog, QFormLayout, QWidget, QScrollArea
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from .suite_model import TestSuite, SuiteTestEntry, save_suite
from .model import TestMetadata


class SuiteEditorDialog(QDialog):
    """Dialog for creating and editing test suites."""

    def __init__(self, available_tests: List[TestMetadata], suite: Optional[TestSuite] = None,
                 default_save_dir: Optional[Path] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.available_tests = available_tests
        self.suite = suite
        self.default_save_dir = default_save_dir or Path.cwd()
        self.test_entries: List[SuiteTestEntry] = []

        if suite:
            self.test_entries = list(suite.tests)

        self.setWindowTitle("Test Suite Editor")
        self.setMinimumSize(900, 700)

        self._setup_ui()
        self._load_suite_data()

    def _setup_ui(self):
        """Set up the editor UI."""
        layout = QVBoxLayout(self)

        # Suite metadata
        meta_group = QGroupBox("Suite Metadata")
        meta_layout = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g., Smoke Tests")
        meta_layout.addRow("Suite Name:", self.name_edit)

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Brief description of the suite")
        self.description_edit.setMaximumHeight(60)
        meta_layout.addRow("Description:", self.description_edit)

        meta_group.setLayout(meta_layout)
        layout.addWidget(meta_group)

        # Tests section
        tests_group = QGroupBox("Tests in Suite")
        tests_layout = QVBoxLayout()

        # Add test button
        add_btn_layout = QHBoxLayout()
        self.available_tests_combo = QComboBox()
        for test in self.available_tests:
            self.available_tests_combo.addItem(f"{test.id} - {test.description}", test)
        add_btn_layout.addWidget(QLabel("Add Test:"))
        add_btn_layout.addWidget(self.available_tests_combo, stretch=1)

        add_test_btn = QPushButton("Add Test")
        add_test_btn.clicked.connect(self._add_test)
        add_btn_layout.addWidget(add_test_btn)

        tests_layout.addLayout(add_btn_layout)

        # Test list with scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(300)

        self.tests_container = QWidget()
        self.tests_container_layout = QVBoxLayout(self.tests_container)
        self.tests_container_layout.setAlignment(Qt.AlignTop)

        scroll.setWidget(self.tests_container)
        tests_layout.addWidget(scroll)

        tests_group.setLayout(tests_layout)
        layout.addWidget(tests_group, stretch=1)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        save_btn = QPushButton("Save Suite")
        save_btn.clicked.connect(self._save_suite)
        save_btn.setDefault(True)
        button_layout.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    def _load_suite_data(self):
        """Load existing suite data if editing."""
        if self.suite:
            self.name_edit.setText(self.suite.name)
            self.description_edit.setPlainText(self.suite.description)

            for test_entry in self.test_entries:
                self._add_test_widget(test_entry)

    def _add_test(self):
        """Add a new test to the suite."""
        test_metadata = self.available_tests_combo.currentData()
        if not test_metadata:
            return

        # Create new test entry
        test_entry = SuiteTestEntry(
            name=f"{test_metadata.id}",
            path=test_metadata.relative_path,
            enabled=True,
            timeout=300
        )

        self.test_entries.append(test_entry)
        self._add_test_widget(test_entry)

    def _add_test_widget(self, test_entry: SuiteTestEntry):
        """Add a test widget to the UI."""
        test_widget = TestEntryWidget(test_entry, parent=self.tests_container)
        test_widget.remove_requested.connect(lambda: self._remove_test(test_widget, test_entry))
        test_widget.move_up_requested.connect(lambda: self._move_test_up(test_entry))
        test_widget.move_down_requested.connect(lambda: self._move_test_down(test_entry))

        self.tests_container_layout.addWidget(test_widget)

    def _remove_test(self, widget: QWidget, test_entry: SuiteTestEntry):
        """Remove a test from the suite."""
        if test_entry in self.test_entries:
            self.test_entries.remove(test_entry)

        widget.deleteLater()

    def _move_test_up(self, test_entry: SuiteTestEntry):
        """Move test up in the list."""
        idx = self.test_entries.index(test_entry)
        if idx > 0:
            self.test_entries[idx], self.test_entries[idx - 1] = self.test_entries[idx - 1], self.test_entries[idx]
            self._refresh_test_widgets()

    def _move_test_down(self, test_entry: SuiteTestEntry):
        """Move test down in the list."""
        idx = self.test_entries.index(test_entry)
        if idx < len(self.test_entries) - 1:
            self.test_entries[idx], self.test_entries[idx + 1] = self.test_entries[idx + 1], self.test_entries[idx]
            self._refresh_test_widgets()

    def _refresh_test_widgets(self):
        """Refresh all test widgets to match current order."""
        # Clear existing widgets
        while self.tests_container_layout.count():
            child = self.tests_container_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # Re-add in correct order
        for test_entry in self.test_entries:
            self._add_test_widget(test_entry)

    def _save_suite(self):
        """Save the suite to a YAML file."""
        suite_name = self.name_edit.text().strip()
        if not suite_name:
            QMessageBox.warning(self, "Validation Error", "Please enter a suite name.")
            return

        if not self.test_entries:
            QMessageBox.warning(self, "Validation Error", "Please add at least one test to the suite.")
            return

        # Choose save location
        default_filename = suite_name.lower().replace(" ", "_") + ".yaml"
        if self.suite and self.suite.file_path:
            default_path = str(self.suite.file_path)
        else:
            default_path = str(self.default_save_dir / default_filename)

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Test Suite",
            default_path,
            "YAML Files (*.yaml *.yml)"
        )

        if not file_path:
            return

        # Create suite object
        suite = TestSuite(
            name=suite_name,
            description=self.description_edit.toPlainText().strip(),
            tests=self.test_entries,
            file_path=Path(file_path)
        )

        # Save
        if save_suite(suite, Path(file_path)):
            QMessageBox.information(self, "Success", f"Suite saved to {file_path}")
            self.accept()
        else:
            QMessageBox.critical(self, "Error", "Failed to save suite file.")


class TestEntryWidget(QWidget):
    """Widget representing a single test entry in the suite editor."""

    from PySide6.QtCore import Signal
    remove_requested = Signal()
    move_up_requested = Signal()
    move_down_requested = Signal()

    def __init__(self, test_entry: SuiteTestEntry, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.test_entry = test_entry

        self._setup_ui()

    def _setup_ui(self):
        """Set up the test entry widget UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Enable checkbox
        self.enabled_check = QCheckBox()
        self.enabled_check.setChecked(self.test_entry.enabled)
        self.enabled_check.toggled.connect(lambda checked: setattr(self.test_entry, 'enabled', checked))
        layout.addWidget(self.enabled_check)

        # Test name edit
        self.name_edit = QLineEdit(self.test_entry.name)
        self.name_edit.textChanged.connect(lambda text: setattr(self.test_entry, 'name', text))
        layout.addWidget(self.name_edit, stretch=1)

        # Timeout spinner
        layout.addWidget(QLabel("Timeout:"))
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(10, 36000)
        self.timeout_spin.setValue(self.test_entry.timeout)
        self.timeout_spin.setSuffix("s")
        self.timeout_spin.valueChanged.connect(lambda value: setattr(self.test_entry, 'timeout', value))
        layout.addWidget(self.timeout_spin)

        # Move buttons
        move_up_btn = QPushButton("↑")
        move_up_btn.setMaximumWidth(30)
        move_up_btn.clicked.connect(self.move_up_requested.emit)
        layout.addWidget(move_up_btn)

        move_down_btn = QPushButton("↓")
        move_down_btn.setMaximumWidth(30)
        move_down_btn.clicked.connect(self.move_down_requested.emit)
        layout.addWidget(move_down_btn)

        # Remove button
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self.remove_requested.emit)
        layout.addWidget(remove_btn)

        # Style
        self.setStyleSheet("""
            TestEntryWidget {
                background-color: #f0f0f0;
                border: 1px solid #ccc;
                border-radius: 3px;
                margin: 2px;
            }
        """)
