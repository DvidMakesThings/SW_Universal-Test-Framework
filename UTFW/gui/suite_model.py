"""
UTFW GUI Suite Model
====================
Data structures and functions for test suite management.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import yaml


@dataclass
class SuiteTestEntry:
    """Represents a single test entry in a suite."""
    name: str
    path: str
    enabled: bool
    timeout: int


@dataclass
class TestSuite:
    """Represents a test suite with metadata and test list."""
    name: str
    description: str
    tests: List[SuiteTestEntry]
    file_path: Path


def discover_suites(suites_dir: Path) -> List[TestSuite]:
    """Discover all test suites in the given directory.

    Args:
        suites_dir: Directory containing .yaml suite files

    Returns:
        List of discovered test suites
    """
    suites = []

    if not suites_dir.exists() or not suites_dir.is_dir():
        return suites

    for yaml_file in suites_dir.glob("*.yaml"):
        try:
            suite = load_suite(yaml_file)
            if suite:
                suites.append(suite)
        except Exception:
            continue

    return sorted(suites, key=lambda s: s.name)


def load_suite(yaml_path: Path) -> Optional[TestSuite]:
    """Load a test suite from a YAML file.

    Args:
        yaml_path: Path to YAML suite file

    Returns:
        TestSuite object or None if loading fails
    """
    try:
        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f)

        if not data or 'name' not in data or 'tests' not in data:
            return None

        tests = []
        for test_data in data['tests']:
            tests.append(SuiteTestEntry(
                name=test_data.get('name', 'Unnamed'),
                path=test_data.get('path', ''),
                enabled=test_data.get('enabled', True),
                timeout=test_data.get('timeout', 300)
            ))

        return TestSuite(
            name=data['name'],
            description=data.get('description', ''),
            tests=tests,
            file_path=yaml_path
        )
    except Exception:
        return None


def save_suite(suite: TestSuite, yaml_path: Path) -> bool:
    """Save a test suite to a YAML file.

    Args:
        suite: TestSuite to save
        yaml_path: Path where to save the YAML file

    Returns:
        True if successful, False otherwise
    """
    try:
        data = {
            'name': suite.name,
            'description': suite.description,
            'tests': [
                {
                    'name': test.name,
                    'path': test.path,
                    'enabled': test.enabled,
                    'timeout': test.timeout
                }
                for test in suite.tests
            ]
        }

        with open(yaml_path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, indent=2)

        return True
    except Exception:
        return False
