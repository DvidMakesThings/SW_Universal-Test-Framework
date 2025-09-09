"""
UTFW Utilities Module
=====================
Common utility functions for universal testing

Author: DvidMakesThings
"""

import time
import json
from pathlib import Path
from typing import Dict, Any, Optional, List


class UtilitiesError(Exception):
    """Utilities specific error"""
    pass


def load_config_file(config_path: str) -> Dict[str, Any]:
    """
    Load configuration from JSON file
    
    Args:
        config_path: Path to JSON configuration file
        
    Returns:
        Configuration dictionary
        
    Raises:
        UtilitiesError: If file loading fails
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


def save_config_file(config: Dict[str, Any], config_path: str):
    """
    Save configuration to JSON file
    
    Args:
        config: Configuration dictionary
        config_path: Path to save JSON file
        
    Raises:
        UtilitiesError: If file saving fails
    """
    try:
        path = Path(config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        raise UtilitiesError(f"Failed to save configuration file {config_path}: {e}")


def create_default_config(config_path: str, defaults: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create default configuration file if it doesn't exist
    
    Args:
        config_path: Path to configuration file
        defaults: Default configuration values
        
    Returns:
        Configuration dictionary (loaded or created)
    """
    path = Path(config_path)
    
    if path.exists():
        return load_config_file(config_path)
    else:
        save_config_file(defaults, config_path)
        return defaults


def format_duration(start_time: str, end_time: str) -> str:
    """
    Format duration between two timestamp strings
    
    Args:
        start_time: Start timestamp (YYYY-MM-DD HH:MM:SS)
        end_time: End timestamp (YYYY-MM-DD HH:MM:SS)
        
    Returns:
        Formatted duration string
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
    """
    Sanitize filename for cross-platform compatibility
    
    Args:
        filename: Original filename
        
    Returns:
        Sanitized filename
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


def wait_for_condition(condition_func, timeout: float = 10.0, interval: float = 0.5) -> bool:
    """
    Wait for a condition function to return True
    
    Args:
        condition_func: Function that returns boolean
        timeout: Maximum wait time in seconds
        interval: Check interval in seconds
        
    Returns:
        True if condition met, False if timeout
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
    """
    Extract numeric value from text
    
    Args:
        text: Text containing numeric value
        pattern: Optional regex pattern to extract specific part
        
    Returns:
        Numeric value or None if not found
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
    """
    Capture & parse EEPROM dump via the helper tool.

    Invokes UTFW/tools/eeprom_dump_helper.py:
        python eeprom_dump_helper.py -p <port> -b <baudrate> -o eeprom_dump -v

    Output files are written into the SAME directory used by the active TestReporter
    (i.e., the 'reports_dir' you passed to run_test_with_teardown), with NO extra
    subfolders. If 'save_to_dir' is provided, that directory is used instead.

    Args:
        port (str): Serial port (e.g., "COM10", "/dev/ttyACM0").
        baudrate (int): Serial baud rate.
        save_to_dir (str, optional): Override output directory.

    Returns:
        Dict[str, str]: {'raw': <raw_text>, 'ascii': <ascii_text>}

    Raises:
        UtilitiesError: if the helper is missing or the subprocess fails.
    """
    try:
        import sys
        import subprocess
        from pathlib import Path
        from .reporting import get_active_reporter

        # Resolve output directory:
        if save_to_dir:
            output_dir = Path(save_to_dir)
        else:
            rep = get_active_reporter()
            if not rep:
                raise UtilitiesError("No active reporter; cannot resolve reports directory.")
            # EXACTLY the reporter directory (e.g., "report_tc_serial_utfw"), no extra subfolders
            output_dir = rep.reports_dir

        output_dir.mkdir(parents=True, exist_ok=True)

        # Locate helper
        helper_script = Path(__file__).parent.parent / "UTFW" / "tools" / "eeprom_dump_helper.py"
        if not helper_script.exists():
            raise UtilitiesError(f"EEPROM dump helper not found at: {helper_script}")

        # Build command (pass --outdir explicitly; do not use cwd tricks)
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

        # Read generated files (exact filenames from helper)
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
    """
    Create example hardware configuration file
    
    Args:
        config_path: Path where to create the config file
        
    Returns:
        Example configuration dictionary
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

# Add to UTFW/utilities.py

def hwcfg_from_cli(argv: Optional[List[str]] = None) -> Optional[str]:
    """Parse a hardware config path from command-line arguments.

    Supports the following syntaxes:
      * `--hwcfg C:\\path\\hardware_config.py`
      * `--hwcfg=C:\\path\\hardware_config.py`
      * `--hwcfg C:\\path\\to\\folder` (resolves to `folder/hardware_config.py`)

    If `argv` is not provided, `sys.argv[1:]` is used.

    Args:
        argv: Optional list of CLI tokens to parse instead of `sys.argv[1:]`.

    Returns:
        The resolved absolute or relative path to `hardware_config.py`, or `None`
        if `--hwcfg` was not present.

    Raises:
        None
    """
    import sys
    from pathlib import Path

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
    """Load a project-specific `hardware_config.py` module.

    If `hwcfg` is a directory, this function attempts to load
    `<directory>/hardware_config.py`. If `hwcfg` is `None`, the function tries
    to auto-discover `<project>/TestCases/hardware_config.py` by walking up from
    the calling test file (`tc_*.py`) or the current working directory.

    Args:
        hwcfg: Path to `hardware_config.py` or to its containing folder. If
            `None`, the file is auto-discovered under a `TestCases` directory.

    Returns:
        The imported `hardware_config` module object.

    Raises:
        FileNotFoundError: If the resolved `hardware_config.py` cannot be found.
        ImportError: If the module cannot be loaded from the resolved path.
    """
    import inspect
    import importlib.util
    import sys
    from pathlib import Path

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
    """Load `hardware_config.py` using `--hwcfg` CLI if provided, else auto-discover.

    This is a convenience wrapper combining `hwcfg_from_cli` and
    `load_hardware_config`.

    Args:
        argv: Optional list of CLI tokens to parse instead of `sys.argv[1:]`.

    Returns:
        The imported `hardware_config` module object.

    Raises:
        FileNotFoundError: If the resolved `hardware_config.py` cannot be found.
        ImportError: If the module cannot be loaded from the resolved path.
    """
    path = hwcfg_from_cli(argv)
    return load_hardware_config(path)
