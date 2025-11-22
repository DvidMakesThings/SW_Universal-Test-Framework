"""
UTFW/modules/network/__init__.py

UTFW Network Module
===================

High-level network TestAction factories.

Provides:
- ICMP ping
- HTTP GET/POST
- Web form submission testing
- Endpoint validation & connectivity checks
- PCAP generation & analysis

Author: DvidMakesThings
"""

from .network import *
from .pcapgen import *
from .pcap_analyze import *

__all__ = [
    # Exceptions
    "NetworkTestError",

    # Core network functions (duplicated ping_host is intentional for compatibility)
    "ping_host",
    "http_get",
    "http_post",
    "test_connectivity",
    "test_http_endpoint",
    "test_web_form_submission",
    "test_outlet_control_via_web",
    "test_network_config_via_web",

    # PCAP generation
    "pcap_create",
    "pcap_from_spec_action",

    # PCAP analysis
    "read_PCAPFrames",
    "analyze_PCAP",
    "pcap_checkFrames",

    # PCAP capture
    "CapturePcap",
    "Ping",
]
