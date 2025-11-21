"""UTFW Metrics Package
=======================

Public re-export layer for the metrics testing utilities. Provides
structured Prometheus-style metrics validation helpers plus TestAction
factories used by test cases (e.g. `tc_metrics`).

Author: DvidMakesThings
"""

from .metrics import (
    # Exceptions
    MetricsTestError,

    # Core parsing & low-level helpers
    fetch_metrics,
    parse_metrics,
    get_metric_value,
    validate_metric_exists,
    validate_metric_value,
    validate_metric_range,
    compare_metrics,
    get_all_labels_for_metric,

    # TestAction factories
    check_metric_exists,
    check_metric_value,
    check_metric_range,
    check_metrics_comparison,
    read_metric,
    check_all_channels_state,
    wait_for_metric_condition,
)
__all__ = [
    # Exceptions
    "MetricsTestError",

    # Core metrics functions
    "fetch_metrics",
    "parse_metrics",
    "get_metric_value",
    "validate_metric_exists",
    "validate_metric_value",
    "validate_metric_range",
    "compare_metrics",
    "get_all_labels_for_metric",

    # TestAction factories
    "check_metric_exists",
    "check_metric_value",
    "check_metric_range",
    "check_metrics_comparison",
    "read_metric",
    "check_all_channels_state",
    "wait_for_metric_condition",
]