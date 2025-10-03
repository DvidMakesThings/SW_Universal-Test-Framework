#!/usr/bin/env python3
"""
Test Suite Runner for UTFW Framework
=====================================
Executes multiple tests based on YAML/JSON configuration files.
Supports regression testing, nightly builds, and custom test suites.
"""

import sys
import argparse
import json
import subprocess
import html
import hashlib
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import importlib.util

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


class TestSuiteRunner:
    """Manages execution of multiple test cases based on configuration."""

    def _generate_session_id(self) -> str:
        """Generate a unique session ID for the test suite run."""
        timestamp = str(time.time())
        combined = f"suite_{timestamp}"
        hash_obj = hashlib.md5(combined.encode())
        return hash_obj.hexdigest()[:8]

    def __init__(self, config_path: Path, reports_dir: Optional[Path] = None, hwcfg_path: Optional[Path] = None):
        self.config_path = config_path
        self.config = self._load_config()
        self.reports_dir = reports_dir or Path("_SoftwareTest/Reports")
        self.hwcfg_path = hwcfg_path
        self.results: List[Dict[str, Any]] = []
        self.suite_session_id = self._generate_session_id()

    def _load_config(self) -> Dict[str, Any]:
        """Load test suite configuration from YAML or JSON file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        content = self.config_path.read_text(encoding='utf-8')

        if self.config_path.suffix in ['.yaml', '.yml']:
            if not YAML_AVAILABLE:
                raise ImportError("PyYAML is required for YAML configs. Install with: pip install pyyaml")
            return yaml.safe_load(content)
        elif self.config_path.suffix == '.json':
            return json.loads(content)
        else:
            raise ValueError(f"Unsupported config format: {self.config_path.suffix}. Use .yaml, .yml, or .json")

    def _resolve_test_path(self, test_spec: Dict[str, Any]) -> Path:
        """Resolve test file path from test specification."""
        if 'path' in test_spec:
            return Path(test_spec['path'])
        elif 'module' in test_spec:
            # Convert module path to file path (e.g., tests.tc_serial.tc_serial_utfw -> tests/tc_serial/tc_serial_utfw.py)
            module_path = test_spec['module'].replace('.', '/')
            return Path(f"{module_path}.py")
        else:
            raise ValueError(f"Test spec missing 'path' or 'module': {test_spec}")

    def _run_single_test(self, test_spec: Dict[str, Any], suite_name: str) -> Dict[str, Any]:
        """Execute a single test and return results."""
        test_name = test_spec.get('name', 'Unknown Test')
        test_path = self._resolve_test_path(test_spec)

        if not test_path.exists():
            return {
                'name': test_name,
                'path': str(test_path),
                'status': 'SKIPPED',
                'reason': f'Test file not found: {test_path}',
                'duration': 0
            }

        print(f"\n{'='*80}")
        print(f"Running: {test_name}")
        print(f"File: {test_path}")
        print(f"{'='*80}\n")

        start_time = datetime.now()

        try:
            # Build command with optional hwcfg argument
            cmd = [sys.executable, str(test_path)]
            if self.hwcfg_path:
                cmd.extend(['--hwcfg', str(self.hwcfg_path)])

            # Set environment variable for reports directory
            import os
            env = os.environ.copy()
            env['UTFW_REPORTS_DIR'] = str(self.reports_dir.absolute())

            # Run test as subprocess
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
                timeout=test_spec.get('timeout', 600)  # Default 10 min timeout
            )

            duration = (datetime.now() - start_time).total_seconds()

            # Determine status from exit code
            if result.returncode == 0:
                status = 'PASS'
            else:
                status = 'FAIL'

            return {
                'name': test_name,
                'path': str(test_path),
                'status': status,
                'exit_code': result.returncode,
                'duration': duration,
                'stdout': result.stdout,
                'stderr': result.stderr
            }

        except subprocess.TimeoutExpired:
            duration = (datetime.now() - start_time).total_seconds()
            return {
                'name': test_name,
                'path': str(test_path),
                'status': 'TIMEOUT',
                'duration': duration,
                'reason': f"Test exceeded timeout of {test_spec.get('timeout', 600)}s"
            }
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            return {
                'name': test_name,
                'path': str(test_path),
                'status': 'ERROR',
                'duration': duration,
                'reason': str(e)
            }

    def run_suite(self) -> bool:
        """Execute all tests in the suite and generate summary report."""
        suite_name = self.config.get('name', 'Test Suite')
        description = self.config.get('description', '')
        tests = self.config.get('tests', [])

        # Create reports directory before running any tests
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n{'#'*80}")
        print(f"# Test Suite: {suite_name}")
        if description:
            print(f"# Description: {description}")
        print(f"# Total Tests: {len(tests)}")
        print(f"# Reports Directory: {self.reports_dir.absolute()}")
        print(f"# Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'#'*80}\n")

        suite_start = datetime.now()

        # Run each test
        for idx, test_spec in enumerate(tests, 1):
            print(f"\n[{idx}/{len(tests)}] ", end='')

            # Check if test is enabled
            if not test_spec.get('enabled', True):
                test_name = test_spec.get('name', 'Unknown')
                print(f"SKIPPED: {test_name} (disabled in config)")
                self.results.append({
                    'name': test_name,
                    'status': 'SKIPPED',
                    'reason': 'Disabled in configuration',
                    'duration': 0
                })
                continue

            result = self._run_single_test(test_spec, suite_name)
            self.results.append(result)

        suite_duration = (datetime.now() - suite_start).total_seconds()

        # Generate summary
        self._print_summary(suite_name, suite_duration)
        self._save_summary_report(suite_name, suite_duration)
        self._generate_html_report(suite_name, suite_start, suite_duration)
        self._generate_junit_xml(suite_name, suite_duration)

        # Return True if all tests passed
        return all(r['status'] == 'PASS' for r in self.results)

    def _print_summary(self, suite_name: str, duration: float):
        """Print test suite summary to console."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r['status'] == 'PASS')
        failed = sum(1 for r in self.results if r['status'] == 'FAIL')
        skipped = sum(1 for r in self.results if r['status'] == 'SKIPPED')
        timeout = sum(1 for r in self.results if r['status'] == 'TIMEOUT')
        error = sum(1 for r in self.results if r['status'] == 'ERROR')

        print(f"\n\n{'='*80}")
        print(f"TEST SUITE SUMMARY: {suite_name}")
        print(f"{'='*80}")
        print(f"Total Duration: {duration:.2f}s")
        print(f"Total Tests:    {total}")
        print(f"  ✓ Passed:     {passed}")
        print(f"  ✗ Failed:     {failed}")
        print(f"  ⊗ Timeout:    {timeout}")
        print(f"  ! Error:      {error}")
        print(f"  - Skipped:    {skipped}")
        print(f"{'='*80}\n")

        # Print failed tests details
        if failed > 0 or timeout > 0 or error > 0:
            print("\nFAILED TESTS:")
            print("-" * 80)
            for result in self.results:
                if result['status'] in ['FAIL', 'TIMEOUT', 'ERROR']:
                    print(f"  [{result['status']}] {result['name']}")
                    print(f"    Path: {result['path']}")
                    if 'reason' in result:
                        print(f"    Reason: {result['reason']}")
                    if 'exit_code' in result:
                        print(f"    Exit Code: {result['exit_code']}")
                    print()

    def _save_summary_report(self, suite_name: str, duration: float):
        """Save test suite summary report to JSON file."""
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_file = self.reports_dir / f"test_suite_{suite_name.replace(' ', '_')}_{timestamp}.json"

        report_data = {
            'suite_name': suite_name,
            'description': self.config.get('description', ''),
            'started_at': datetime.now().isoformat(),
            'duration': duration,
            'total_tests': len(self.results),
            'passed': sum(1 for r in self.results if r['status'] == 'PASS'),
            'failed': sum(1 for r in self.results if r['status'] == 'FAIL'),
            'skipped': sum(1 for r in self.results if r['status'] == 'SKIPPED'),
            'timeout': sum(1 for r in self.results if r['status'] == 'TIMEOUT'),
            'error': sum(1 for r in self.results if r['status'] == 'ERROR'),
            'results': self.results
        }

        report_file.write_text(json.dumps(report_data, indent=2), encoding='utf-8')
        print(f"[INFO] JSON summary report saved to: {report_file}")

    def _generate_html_report(self, suite_name: str, start_time: datetime, duration: float):
        """Generate HTML report for the test suite."""
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_file = self.reports_dir / f"test_suite_{suite_name.replace(' ', '_')}_{timestamp}.html"

        total = len(self.results)
        passed = sum(1 for r in self.results if r['status'] == 'PASS')
        failed = sum(1 for r in self.results if r['status'] == 'FAIL')
        skipped = sum(1 for r in self.results if r['status'] == 'SKIPPED')
        timeout = sum(1 for r in self.results if r['status'] == 'TIMEOUT')
        error = sum(1 for r in self.results if r['status'] == 'ERROR')

        overall_status = 'PASS' if failed == 0 and timeout == 0 and error == 0 else 'FAIL'

        css = """
        body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif;background:#0f1216;color:#e7eaf0;margin:0}
        header{padding:20px;background:#151a21;border-bottom:1px solid #2a2f37}
        h1{margin:0;font-size:20px}
        .meta{font-size:12px;color:#a6adbb;margin-top:6px}
        .summary{display:flex;gap:16px;flex-wrap:wrap;margin:16px 0}
        .chip{padding:8px 12px;border-radius:20px;border:1px solid #2a2f37;background:#151a21}
        .chip.pass{border-color:#1e7f45;color:#d7ffe6;background:#0e2017}
        .chip.fail{border-color:#a23b3b;color:#ffe1e1;background:#210e0e}
        .chip.unknown{border-color:#6b7280;color:#e7eaf0;background:#1b2028}
        main{padding:20px}
        table{width:100%;border-collapse:collapse;margin-top:8px}
        th,td{border-bottom:1px solid #1f2530;padding:8px 6px;text-align:left;font-size:13px}
        th{color:#a6adbb;font-weight:600;background:#131820}
        tr.pass{background:#0e2017}
        tr.fail{background:#210e0e}
        tr.timeout{background:#332200}
        tr.error{background:#330033}
        tr.skipped{background:#1b2028}
        .status{padding:3px 8px;border-radius:12px;border:1px solid #2a2f37;font-size:12px;font-weight:600}
        .status.pass{border-color:#1e7f45;color:#d7ffe6;background:#0e2017}
        .status.fail{border-color:#a23b3b;color:#ffe1e1;background:#210e0e}
        .status.timeout{border-color:#a8770f;color:#fff4cc;background:#332200}
        .status.error{border-color:#a23ba2;color:#ffe1ff;background:#330033}
        .status.skipped{border-color:#6b7280;color:#e7eaf0;background:#1b2028}
        .kv{display:grid;grid-template-columns:180px 1fr;gap:8px;margin-top:10px}
        pre{background:#0b0f14;border:1px solid #2a2f37;border-radius:8px;padding:10px;overflow:auto;font-size:12px;max-height:300px}
        details{margin-top:8px}
        summary{cursor:pointer;font-weight:600;color:#9ad0ff}
        """

        html_lines = []
        html_lines.append("<!DOCTYPE html><html><head><meta charset='utf-8'>")
        html_lines.append("<meta name='viewport' content='width=device-width, initial-scale=1'>")
        html_lines.append(f"<title>Test Suite Report - {html.escape(suite_name)}</title>")
        html_lines.append(f"<style>{css}</style></head><body>")

        # Header
        html_lines.append("<header>")
        html_lines.append(f"<h1>Test Suite: {html.escape(suite_name)}</h1>")
        html_lines.append("<div class='meta'>")
        status_class = 'pass' if overall_status == 'PASS' else 'fail'
        html_lines.append(f"Overall: <b class='chip {status_class}'>{html.escape(overall_status)}</b> &nbsp;")
        html_lines.append(f"Started: {html.escape(start_time.strftime('%Y-%m-%d %H:%M:%S'))} &nbsp;")
        html_lines.append(f"Duration: {duration:.2f}s &nbsp;")
        html_lines.append(f"Session ID: {html.escape(self.suite_session_id)} &nbsp;")
        if self.config.get('description'):
            html_lines.append(f"<br>{html.escape(self.config['description'])}")
        html_lines.append("</div>")
        html_lines.append("</header>")

        # Summary
        html_lines.append("<main>")
        html_lines.append("<section class='summary'>")
        html_lines.append(f"<div class='chip pass'>Passed: {passed}</div>")
        html_lines.append(f"<div class='chip fail'>Failed: {failed}</div>")
        html_lines.append(f"<div class='chip timeout'>Timeout: {timeout}</div>")
        html_lines.append(f"<div class='chip error'>Error: {error}</div>")
        html_lines.append(f"<div class='chip skipped'>Skipped: {skipped}</div>")
        html_lines.append(f"<div class='chip'>Total: {total}</div>")
        html_lines.append("</section>")

        # Test Results Table
        html_lines.append("<section>")
        html_lines.append("<h3>Test Results</h3>")
        html_lines.append("<table>")
        html_lines.append("<tr><th>#</th><th>Test Name</th><th>Status</th><th>Duration</th><th>Details</th></tr>")

        for idx, result in enumerate(self.results, 1):
            status = result['status']
            status_class = status.lower()
            duration_str = f"{result.get('duration', 0):.2f}s"

            html_lines.append(f"<tr class='{status_class}'>")
            html_lines.append(f"<td>{idx}</td>")
            html_lines.append(f"<td>{html.escape(result['name'])}</td>")
            html_lines.append(f"<td><span class='status {status_class}'>{html.escape(status)}</span></td>")
            html_lines.append(f"<td>{duration_str}</td>")
            html_lines.append("<td>")

            # Add details based on status
            if 'reason' in result:
                html_lines.append(html.escape(result['reason']))
            elif 'exit_code' in result and result['exit_code'] != 0:
                html_lines.append(f"Exit code: {result['exit_code']}")

            # Add expandable stdout/stderr for failed tests
            if status in ['FAIL', 'ERROR', 'TIMEOUT'] and ('stdout' in result or 'stderr' in result):
                html_lines.append("<details>")
                html_lines.append("<summary>View Output</summary>")
                if result.get('stdout'):
                    html_lines.append("<h4>Standard Output</h4>")
                    html_lines.append(f"<pre>{html.escape(result['stdout'][-2000:])}</pre>")  # Last 2000 chars
                if result.get('stderr'):
                    html_lines.append("<h4>Standard Error</h4>")
                    html_lines.append(f"<pre>{html.escape(result['stderr'][-2000:])}</pre>")
                html_lines.append("</details>")

            html_lines.append("</td>")
            html_lines.append("</tr>")

        html_lines.append("</table>")
        html_lines.append("</section>")

        # Environment info
        html_lines.append("<section>")
        html_lines.append("<h3>Environment</h3>")
        html_lines.append("<div class='kv'>")
        import socket
        import platform
        html_lines.append(f"<div>Session ID</div><div><code>{html.escape(self.suite_session_id)}</code></div>")
        html_lines.append(f"<div>Hostname</div><div>{html.escape(socket.gethostname())}</div>")
        html_lines.append(f"<div>OS</div><div>{html.escape(platform.system())} {html.escape(platform.release())}</div>")
        html_lines.append(f"<div>Python</div><div>{html.escape(sys.version.split()[0])}</div>")
        html_lines.append(f"<div>Config</div><div>{html.escape(str(self.config_path))}</div>")
        html_lines.append(f"<div>Reports Dir</div><div>{html.escape(str(self.reports_dir.absolute()))}</div>")
        html_lines.append("</div>")
        html_lines.append("</section>")

        html_lines.append("</main>")
        html_lines.append("</body></html>")

        report_file.write_text("\n".join(html_lines), encoding='utf-8')
        print(f"[INFO] HTML test report generated at: {report_file}")

    def _generate_junit_xml(self, suite_name: str, duration: float):
        """Generate JUnit XML report for the test suite."""
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_file = self.reports_dir / f"test_suite_{suite_name.replace(' ', '_')}_{timestamp}.xml"

        total = len(self.results)
        failures = sum(1 for r in self.results if r['status'] in ['FAIL', 'TIMEOUT', 'ERROR'])
        skipped = sum(1 for r in self.results if r['status'] == 'SKIPPED')

        def xml_escape(s: str) -> str:
            return (s.replace("&", "&amp;")
                     .replace("<", "&lt;")
                     .replace(">", "&gt;")
                     .replace('"', "&quot;")
                     .replace("'", "&apos;"))

        lines = []
        lines.append('<?xml version="1.0" encoding="UTF-8"?>')
        lines.append(f'<testsuite name="{xml_escape(suite_name)}" tests="{total}" failures="{failures}" skipped="{skipped}" time="{duration:.3f}" session_id="{xml_escape(self.suite_session_id)}">')

        for result in self.results:
            test_name = result['name']
            test_duration = result.get('duration', 0)
            status = result['status']

            lines.append(f'  <testcase classname="TestSuite" name="{xml_escape(test_name)}" time="{test_duration:.3f}">')

            if status == 'FAIL':
                message = result.get('reason', 'Test failed')
                if 'exit_code' in result:
                    message += f" (exit code: {result['exit_code']})"
                lines.append(f'    <failure message="{xml_escape(message)}"/>')
            elif status == 'TIMEOUT':
                message = result.get('reason', 'Test timeout')
                lines.append(f'    <failure message="{xml_escape(message)}" type="timeout"/>')
            elif status == 'ERROR':
                message = result.get('reason', 'Test error')
                lines.append(f'    <error message="{xml_escape(message)}"/>')
            elif status == 'SKIPPED':
                message = result.get('reason', 'Test skipped')
                lines.append(f'    <skipped message="{xml_escape(message)}"/>')

            lines.append('  </testcase>')

        lines.append('</testsuite>')

        report_file.write_text("\n".join(lines), encoding='utf-8')
        print(f"[INFO] JUnit XML report generated at: {report_file}")


def main():
    parser = argparse.ArgumentParser(
        description='UTFW Test Suite Runner - Execute multiple tests from configuration',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run regression test suite
  python run_test_suite.py --config test_suites/regression.yaml

  # Run nightly tests with custom reports directory
  python run_test_suite.py --config test_suites/nightly.yaml --reports-dir ./nightly_reports

  # Run quick smoke tests
  python run_test_suite.py --config test_suites/smoke.json
        """
    )
    parser.add_argument(
        '--config', '-c',
        required=True,
        type=Path,
        help='Path to test suite configuration file (YAML or JSON)'
    )
    parser.add_argument(
        '--reports-dir', '-r',
        type=Path,
        default=Path('_SoftwareTest/Reports'),
        help='Directory for test reports (default: _SoftwareTest/Reports)'
    )
    parser.add_argument(
        '--hwcfg',
        type=Path,
        help='Path to hardware configuration file (passed to all tests)'
    )

    args = parser.parse_args()

    try:
        runner = TestSuiteRunner(args.config, args.reports_dir, args.hwcfg)
        success = runner.run_suite()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()
