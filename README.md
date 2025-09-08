# Universal Test Framework (UTFW)

A Python framework for hardware device testing currently under active development. 
Designed to simplify testing across different communication protocols used in hardware 
testing.

## Overview

UTFW aims to provide a flexible, modular approach to hardware testing. This project is in 
the early development stages, and the features and APIs are subject to change as the 
framework evolves.

The framework is being built to support:

- Serial/UART communication with logging capabilities
- SNMP operations for network device management
- Network connectivity and HTTP testing
- Structured test organization
- Sub-step execution for complex test flows
- Test reporting functionality
- Hardware instrumentation integration

## Installation

> **Note:** As this project is under development, installation processes may change.

### Current Setup (Windows)

1. Clone the repository:
   ```
   git clone https://github.com/DvidMakesThings/SW_Universal-Test-Framework.git
   cd SW_Universal-Test-Framework
   ```

2. For development, use the bootstrap script:
   ```
   setup_utfw_env.bat
   ```

This performs an editable install, allowing you to modify the source code without reinstalling.

## Current Modules

UTFW is being organized into modules that focus on different testing domains:

- **Core**: Basic test framework structure
- **Serial**: UART/Serial communication helpers
- **SNMP**: Network management tools
- **Network**: Basic network connectivity testing
- **Validation**: Test verification utilities
- **FX2LA**: Logic analyzer integration (experimental)
- **Reporting**: Test result logging

## Basic Usage Examples

> **Note:** These examples are simplified illustrations of intended functionality. 
The actual API may change during development.

```python
# Example structure of a potential test case
from UTFW import TestFramework, Serial, Network

class DeviceTest:
    def test_01_connectivity(self):
        """Test basic connectivity."""
        # This is a conceptual example of how tests might be structured
        return [
            Network.ping_host("Ping device", "192.168.1.100"),
            Serial.send_command("Check status", "/dev/ttyUSB0", "status")
        ]
    
    def teardown(self):
        """Cleanup operations."""
        pass

# Concept for test execution
from UTFW import run_test_with_teardown
run_test_with_teardown(DeviceTest(), "Basic_Test")
```

## Project Status

This project is in **active development** with the following status:

- Core framework design: In progress
- Module implementation: Partial
- Documentation: Early stage
- Testing: Ongoing
- Stability: Experimental

Breaking changes are expected as the framework evolves.

## Contributing

Contributions are welcome! As this is an early-stage project, please reach out before 
making substantial changes:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/concept`)
3. Commit your changes (`git commit -m 'Add concept'`)
4. Push to the branch (`git push origin feature/concept`)
5. Open a Pull Request with a detailed description

## License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.
See the [LICENSE](LICENSE) file for details.

### What this license means:

- ✅ **You can** freely use, modify, and distribute this software
- ✅ **You can** use this project for personal, educational, or internal purposes
- ✅ **You can** contribute improvements back to this project

- ⚠️ **You must** share any modifications you make if you distribute the software
- ⚠️ **You must** release the source code if you run a modified version on a server that others interact with
- ⚠️ **You must** keep all copyright notices intact

- ❌ **You cannot** incorporate this code into proprietary software without sharing your source code
- ❌ **You cannot** use this project in a commercial product without either complying with AGPL or obtaining a different license

### Commercial & Enterprise Use

Dual licensing options are available for commercial and enterprise users who require different terms. Please contact me through any of the channels listed in the [Contact](#contact) section to discuss commercial licensing arrangements.

## Contact

For questions or feedback:
- **Email:** [dvidmakesthings@gmail.com](mailto:dvidmakesthings@gmail.com)
- **GitHub:** [DvidMakesThings](https://github.com/DvidMakesThings)

## Acknowledgments

- Built with Python 3.9+
- Inspired by the need for a more flexible approach to hardware testing