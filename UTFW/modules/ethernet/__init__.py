"""
UTFW Ethernet Module
====================

Advanced HTTP and web testing utilities for the UTFW framework.

This module provides comprehensive HTTP testing capabilities including:
- Advanced HTTP operations with detailed logging and dumping
- Request pacing and rate limiting for hardware safety
- Comprehensive response validation and content checking
- ETag validation and conditional requests
- Link crawling and asset verification
- Tolerance for connection drops during device reboots

All functions integrate with the UTFW logging system and return TestAction
instances for use in test steps or STE groups.

Author: DvidMakesThings
"""

from .ethernet import *

__all__ = [
    # Exceptions
    "EthernetTestError",
    
    # TestAction factories
    "ping_action",
    "http_get_action", 
    "http_post_form_action",
    "http_post_json_action",
    "expect_header_prefix_action",
    "etag_roundtrip_action",
    "crawl_links_action",
    "expect_status_action",
    "wait_http_ready_action",
]