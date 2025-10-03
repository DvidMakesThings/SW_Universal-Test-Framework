"""
UTFW Utilities Module
=====================
Common utility functions for universal testing

This module provides a collection of utility functions that are commonly
needed across different test modules. It includes configuration management,
file operations, timing utilities, data parsing, and hardware configuration
loading capabilities.

Author: DvidMakesThings
"""

import time
import json
import os
import sys
import importlib.util
import inspect
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable

# Global context for storing test execution context (e.g., reports directory)
_test_context = {
    'reports_dir': None
}


class UtilitiesError(Exception):
    """Exception raised by utility functions when operations fail.
    
    This exception is used throughout the utilities module to indicate
    various types of failures such as file I/O errors, configuration
    parsing errors, or invalid parameters.
    
    Args:
        message (str): Description of the error that occurred.
    """
    pass


def load_config_file(config_path: str) -> Dict[str, Any]:
    """Load configuration from a JSON file.
    
    This function reads and parses a JSON configuration file, providing
    detailed error messages for common failure scenarios.
    
    Args:
        config_path (str): Path to the JSON configuration file to load.
        
    Returns:
        Dict[str, Any]: Parsed configuration data as a dictionary.
        
    Raises:
        UtilitiesError: If the file cannot be found, contains invalid JSON,
            or cannot be read for any other reason.
    
    Example:
        >>> config = load_config_file("test_config.json")
        >>> print(config["network"]["ip"])
        192.168.1.100
    """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        raise UtilitiesError(f"Configuration file not found: {config_path}")
    except json.JSONDecodeError as e:
        raise UtilitiesError(f"Invalid JSON in configuration file {config_path}: {e}")
    except Exception as e:
        raise UtilitiesError(f"Failed to load configuration file {config_path}: {e}")


def save_config_file(config: Dict[str, Any], config_path: str) -> None:
    """Save configuration to a JSON file.
    
    This function writes configuration data to a JSON file, creating
    parent directories as needed and formatting the JSON for readability.
    
    Args:
        config (Dict[str, Any]): Configuration data to save.
        config_path (str): Path where the JSON file should be saved.
        
    Raises:
        UtilitiesError: If the file cannot be written or directories
            cannot be created.
    
    Example:
        >>> config = {"network": {"ip": "192.168.1.100"}}
        >>> save_config_file(config, "test_config.json")
    """
    try:
        path = Path(config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        raise UtilitiesError(f"Failed to save configuration file {config_path}: {e}")


def create_default_config(config_path: str, defaults: Dict[str, Any]) -> Dict[str, Any]:
    """Create a default configuration file if it doesn't exist.
    
    This function checks if a configuration file exists, and if not,
    creates it with the provided default values. If the file already
    exists, it loads and returns the existing configuration.
    
    Args:
        config_path (str): Path to the configuration file.
        defaults (Dict[str, Any]): Default configuration values to use
            if the file doesn't exist.
        
    Returns:
        Dict[str, Any]: Configuration dictionary (either loaded from
            existing file or the provided defaults).
    
    Example:
        >>> defaults = {"network": {"ip": "192.168.1.1"}}
        >>> config = create_default_config("config.json", defaults)
    """
    path = Path(config_path)
    
    if path.exists():
        return load_config_file(config_path)
    else:
        save_config_file(defaults, config_path)
        return defaults


def format_duration(start_time: str, end_time: str) -> str:
    """Format duration between two timestamp strings.
    
    This function calculates the duration between two timestamps and
    formats it as a human-readable string with appropriate units.
    
    Args:
        start_time (str): Start timestamp in "YYYY-MM-DD HH:MM:SS" format.
        end_time (str): End timestamp in "YYYY-MM-DD HH:MM:SS" format.
        
    Returns:
        str: Formatted duration string (e.g., "2h 15m 30s", "45m 12s", "23s").
    
    Example:
        >>> duration = format_duration("2023-01-01 10:00:00", "2023-01-01 10:05:30")
        >>> print(duration)
        5m 30s
    """
    try:
        start = time.strptime(start_time, "%Y-%m-%d %H:%M:%S")
        end = time.strptime(end_time, "%Y-%m-%d %H:%M:%S")
        
        start_seconds = time.mktime(start)
        end_seconds = time.mktime(end)
        
        duration = int(end_seconds - start_seconds)
        
        hours = duration // 3600
        minutes = (duration % 3600) // 60
        seconds = duration % 60
        
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"
            
    except Exception:
        return "Unknown"


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename for cross-platform compatibility.
    
    This function removes or replaces characters that are invalid in
    filenames on various operating systems, ensuring the resulting
    filename is safe to use across platforms.
    
    Args:
        filename (str): Original filename to sanitize.
        
    Returns:
        str: Sanitized filename safe for use on all platforms.
    
    Example:
        >>> safe_name = sanitize_filename("test<file>name.txt")
        >>> print(safe_name)
        test_file_name.txt
    """
    # Remove or replace invalid characters
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    
    # Remove leading/trailing spaces and dots
    filename = filename.strip(' .')
    
    # Limit length
    if len(filename) > 200:
        filename = filename[:200]
    
    return filename


def wait_for_condition(condition_func: Callable[[], bool], timeout: float = 10.0, 
                      interval: float = 0.5) -> bool:
    """Wait for a condition function to return True within a timeout.
    
    This function repeatedly calls a condition function until it returns
    True or the timeout is reached. It's useful for waiting for system
    states to change or for asynchronous operations to complete.
    
    Args:
        condition_func (Callable[[], bool]): Function that returns True when
            the desired condition is met. Should not take any arguments.
        timeout (float, optional): Maximum time to wait in seconds. Defaults to 10.0.
        interval (float, optional): Time between condition checks in seconds.
            Defaults to 0.5.
        
    Returns:
        bool: True if the condition was met within the timeout, False otherwise.
    
    Example:
        >>> def device_ready():
        ...     return check_device_status() == "READY"
        >>> if wait_for_condition(device_ready, timeout=30.0):
        ...     print("Device is ready")
        ... else:
        ...     print("Timeout waiting for device")
    """
    deadline = time.time() + timeout
    
    while time.time() < deadline:
        try:
            if condition_func():
                return True
        except Exception:
            pass
        time.sleep(interval)
    
    return False


def extract_numeric_value(text: str, pattern: Optional[str] = None) -> Optional[float]:
    """Extract the first numeric value from text.
    
    This function searches for numeric values in text and returns the first
    one found. It can optionally use a custom regex pattern to extract
    specific parts of the text before looking for numbers.
    
    Args:
        text (str): Text containing a numeric value.
        pattern (Optional[str]): Optional regex pattern to extract a specific
            part of the text before looking for numbers. If provided, the
            first capture group (or entire match if no groups) is used.
        
    Returns:
        Optional[float]: The first numeric value found, or None if no
            valid number is found.
    
    Example:
        >>> extract_numeric_value("Voltage: 3.3V")
        3.3
        >>> extract_numeric_value("Temperature: 25.5°C", r"Temperature: ([\d.]+)")
        25.5
        >>> extract_numeric_value("No numbers here")
        None
    """
    import re
    
    if pattern:
        match = re.search(pattern, text)
        if match:
            text = match.group(1) if match.groups() else match.group(0)
    
    # Try to extract first number found
    number_match = re.search(r'[-+]?\d*\.?\d+', text)
    if number_match:
        try:
            return float(number_match.group(0))
        except ValueError:
            pass
    
    return None


def parse_eeprom_data(port: str, baudrate: int, save_to_dir: Optional[str] = None) -> Dict[str, str]:
    """Capture and parse EEPROM dump data via the helper tool.
    
    This function invokes the EEPROM dump helper tool to capture raw EEPROM
    data from a device via serial communication and parse it into both raw
    and ASCII-formatted outputs.
    
    The helper tool (UTFW/tools/eeprom_dump_helper.py) is executed as a
    subprocess with the specified parameters. Output files are written to
    the same directory used by the active TestReporter, or to the specified
    directory if provided.
    
    Args:
        port (str): Serial port identifier (e.g., "COM10", "/dev/ttyACM0").
        baudrate (int): Serial communication baud rate.
        save_to_dir (Optional[str]): Override output directory. If None,
            uses the active TestReporter's reports directory.
        
    Returns:
        Dict[str, str]: Dictionary containing 'raw' and 'ascii' keys with
            the corresponding EEPROM dump data as strings.
        
    Raises:
        UtilitiesError: If the helper tool is missing, the subprocess fails,
            or no output files are generated.
    
    Example:
        >>> eeprom_data = parse_eeprom_data("COM10", 115200)
        >>> print(len(eeprom_data['raw']))
        1024
        >>> print("Device Serial" in eeprom_data['ascii'])
        True
    """
    try:
        import subprocess
        from ..core.logger import get_active_logger

        # Resolve output directory
        if save_to_dir:
            output_dir = Path(save_to_dir)
        else:
            logger = get_active_logger()
            if not logger:
                raise UtilitiesError("No active logger; cannot resolve reports directory.")
            # Use the logger's associated file directory
            if hasattr(logger, 'log_file') and logger.log_file:
                output_dir = logger.log_file.parent
            else:
                raise UtilitiesError("Active logger has no associated log file directory.")

        output_dir.mkdir(parents=True, exist_ok=True)

        # Locate helper script
        helper_script = Path(__file__).parent.parent / "tools" / "eeprom_dump_helper.py"
        if not helper_script.exists():
            raise UtilitiesError(f"EEPROM dump helper not found at: {helper_script}")

        # Build and execute command
        cmd = [
            sys.executable, str(helper_script),
            "-p", str(port),
            "-b", str(baudrate),
            "-o", "eeprom_dump",
            "--outdir", str(output_dir),
            "-v",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise UtilitiesError(
                "EEPROM helper failed:\n"
                f"  CMD : {' '.join(cmd)}\n"
                f"  STDOUT:\n{result.stdout}\n"
                f"  STDERR:\n{result.stderr}"
            )

        # Read generated files
        raw_file = output_dir / "eeprom_dump_raw.log"
        ascii_file = output_dir / "eeprom_dump_ascii.log"

        raw_data = raw_file.read_text(encoding="utf-8") if raw_file.exists() else ""
        ascii_data = ascii_file.read_text(encoding="utf-8") if ascii_file.exists() else ""

        if not raw_data and not ascii_data:
            raise UtilitiesError(f"EEPROM helper succeeded but no outputs found in {output_dir}")

        return {"raw": raw_data, "ascii": ascii_data}

    except UtilitiesError:
        raise
    except Exception as e:
        raise UtilitiesError(f"EEPROM parsing failed: {e}")


def create_example_hardware_config(config_path: str) -> Dict[str, Any]:
    """Create an example hardware configuration file.
    
    This function generates a comprehensive example configuration file
    that demonstrates the expected structure and values for hardware
    test configurations. It includes network settings, serial parameters,
    SNMP OIDs, validation rules, and other common test parameters.
    
    Args:
        config_path (str): Path where the example configuration file
            should be created.
        
    Returns:
        Dict[str, Any]: The example configuration dictionary that was
            written to the file.
    
    Example:
        >>> config = create_example_hardware_config("hardware_config.json")
        >>> print(config["network"]["baseline_ip"])
        192.168.0.11
    """
    example_config = {
        "network": {
            "baseline_ip": "192.168.0.11",
            "base_url": "http://192.168.0.11",
            "snmp_community": "public"
        },
        "serial": {
            "port": "COM3",
            "baudrate": 115200
        },
        "commands": {
            "help": "HELP",
            "sysinfo": "SYSINFO",
            "netinfo": "NETINFO",
            "reboot": "REBOOT",
            "rfs": "RFS",
            "dump_eeprom": "DUMP_EEPROM",
            "set_ip": "SET_IP",
            "set_gw": "SET_GW",
            "set_sn": "SET_SN",
            "set_dns": "SET_DNS"
        },
        "snmp": {
            "enterprise_oid": "1.3.6.1.4.1.19865",
            "outlet_base_oid": "1.3.6.1.4.1.19865.2",
            "all_on_oid": "1.3.6.1.4.1.19865.2.10.0",
            "all_off_oid": "1.3.6.1.4.1.19865.2.9.0",
            "network_oids": {
                "ip": "1.3.6.1.4.1.19865.4.1.0",
                "sn": "1.3.6.1.4.1.19865.4.2.0",
                "gw": "1.3.6.1.4.1.19865.4.3.0",
                "dns": "1.3.6.1.4.1.19865.4.4.0"
            },
            "system_oids": {
                "sys_descr": "1.3.6.1.2.1.1.1.0",
                "sys_uptime": "1.3.6.1.2.1.1.3.0",
                "sys_contact": "1.3.6.1.2.1.1.4.0",
                "sys_name": "1.3.6.1.2.1.1.5.0",
                "sys_location": "1.3.6.1.2.1.1.6.0"
            }
        },
        "validation": {
            "help_tokens": [
                "HELP", "SYSINFO", "REBOOT", "BOOTSEL", "CONFIG_NETWORK",
                "SET_IP", "SET_DNS", "SET_GW", "SET_SN", "NETINFO", "SET_CH",
                "READ_HLW8032", "DUMP_EEPROM", "RFS"
            ],
            "firmware_regex": r"^\d+\.\d+\.\d+(?:[-+].*)?$",
            "core_voltage_range": [0.9, 1.5],
            "frequencies": {
                "sys_hz_min": 100000000,
                "usb_hz_expect": 48000000,
                "per_hz_expect": 48000000,
                "adc_hz_expect": 48000000
            },
            "system_info": {
                "sys_descr": "ENERGIS 8 CHANNEL MANAGED PDU",
                "sys_contact": "dvidmakesthings@gmail.com",
                "sys_location": "Wien"
            },
            "network_expected": {
                "ip": "192.168.0.11",
                "sn": "255.255.255.0",
                "gw": "192.168.0.1",
                "dns": "8.8.8.8"
            }
        }
    }
    
    save_config_file(example_config, config_path)
    return example_config


def hwcfg_from_cli(argv: Optional[List[str]] = None) -> Optional[str]:
    """Parse a hardware config path from command-line arguments.
    
    This function searches command-line arguments for hardware configuration
    path specifications and returns the resolved path. It supports multiple
    argument formats and can resolve directory paths to hardware_config.py files.
    
    Supported argument formats:
    - `--hwcfg /path/to/hardware_config.py`
    - `--hwcfg=/path/to/hardware_config.py`
    - `--hwcfg /path/to/directory` (resolves to directory/hardware_config.py)
    
    Args:
        argv (Optional[List[str]]): List of command-line arguments to parse.
            If None, uses sys.argv[1:].
        
    Returns:
        Optional[str]: Resolved path to hardware_config.py, or None if
            --hwcfg argument is not present.
    
    Example:
        >>> # Command line: python test.py --hwcfg /path/to/config
        >>> config_path = hwcfg_from_cli()
        >>> print(config_path)
        /path/to/config/hardware_config.py
    """
    args = list(argv) if argv is not None else sys.argv[1:]
    for i, tok in enumerate(args):
        if tok == "--hwcfg":
            if i + 1 < len(args):
                p = Path(args[i + 1])
                if p.is_dir():
                    p = p / "hardware_config.py"
                return str(p)
        if tok.startswith("--hwcfg="):
            p = Path(tok.split("=", 1)[1])
            if p.is_dir():
                p = p / "hardware_config.py"
            return str(p)
    return None


def load_hardware_config(hwcfg: Optional[str] = None):
    """Load a project-specific hardware_config.py module.
    
    This function dynamically loads a hardware configuration module from
    a Python file. It can auto-discover the configuration file by searching
    for TestCases directories in the project structure, or load from a
    specified path.
    
    The loaded module is added to sys.modules to make subsequent imports
    of 'hardware_config' use the same module instance.
    
    Args:
        hwcfg (Optional[str]): Path to hardware_config.py or its containing
            directory. If None, auto-discovers the file by searching for
            TestCases/hardware_config.py in the project structure.
        
    Returns:
        module: The imported hardware_config module object.
        
    Raises:
        FileNotFoundError: If the hardware_config.py file cannot be found.
        ImportError: If the module cannot be loaded from the resolved path.
    
    Example:
        >>> hw_config = load_hardware_config("/path/to/TestCases")
        >>> print(hw_config.DEVICE_IP)
        192.168.1.100
        >>> # Now 'import hardware_config' will use the same module
    """
    def _find_default() -> Path:
        # Prefer a nearby TestCases folder relative to the calling test file (tc_*.py)
        for frame in inspect.stack():
            try:
                fpath = Path(frame.filename).resolve()
            except Exception:
                continue
            for anc in (fpath, *fpath.parents):
                if anc.name.lower() == "testcases":
                    candidate = anc / "hardware_config.py"
                    if candidate.exists():
                        return candidate
        # Fallback: search from CWD upward for TestCases/hardware_config.py
        cwd = Path.cwd().resolve()
        for anc in (cwd, *cwd.parents):
            tc = anc / "TestCases" / "hardware_config.py"
            if tc.exists():
                return tc
        return cwd / "hardware_config.py"  # last-resort guess

    path = Path(hwcfg) if hwcfg else _find_default()
    if path.is_dir():
        path = path / "hardware_config.py"
    if not path.exists():
        raise FileNotFoundError(f"hardware_config.py not found at: {path}")

    mod_name = "hardware_config"
    spec = importlib.util.spec_from_file_location(mod_name, str(path))
    if not spec or not spec.loader:
        raise ImportError(f"Failed to create import spec for: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    # Make subsequent `import hardware_config` reuse this module
    sys.modules[mod_name] = mod
    return mod


def get_hwconfig(argv: Optional[List[str]] = None):
    """Load hardware_config.py using --hwcfg CLI argument or auto-discovery.
    
    This is a convenience function that combines hwcfg_from_cli() and
    load_hardware_config() to provide a simple way to load hardware
    configuration from command-line arguments or auto-discovery.
    
    Args:
        argv (Optional[List[str]]): List of command-line arguments to parse.
            If None, uses sys.argv[1:].
        
    Returns:
        module: The imported hardware_config module object.
        
    Raises:
        FileNotFoundError: If the hardware_config.py file cannot be found.
        ImportError: If the module cannot be loaded from the resolved path.
    
    Example:
        >>> # Command line: python test.py --hwcfg /path/to/config
        >>> hw_config = get_hwconfig()
        >>> print(hw_config.DEVICE_IP)
        192.168.1.100
    """
    path = hwcfg_from_cli(argv)
    return load_hardware_config(path)


def set_reports_dir(reports_dir: str):
    """Set the current test's reports directory in the global context.

    This function is called by the test framework to make the reports directory
    available to test code. Tests can retrieve it using get_reports_dir().

    Args:
        reports_dir (str): Path to the reports directory for the current test.
    """
    _test_context['reports_dir'] = reports_dir


def get_reports_dir() -> Optional[str]:
    """Get the current test's reports directory.

    This function allows test code to access the reports directory that was
    configured by the framework. This is useful for tests that need to generate
    output files in the correct location.

    Returns:
        Optional[str]: Path to the reports directory, or None if not set.

    Example:
        >>> from UTFW.core import get_reports_dir
        >>> reports_dir = get_reports_dir()
        >>> output_file = Path(reports_dir) / "capture.pcap"
    """
    return _test_context['reports_dir']