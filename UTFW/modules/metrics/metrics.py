"""
UTFW Metrics Module
===================
High-level metrics test functions and TestAction factories for universal testing.

This module provides comprehensive Prometheus-style metrics testing capabilities
with detailed logging integration. It supports fetching, parsing, and validating
metrics from HTTP endpoints that expose metrics in Prometheus text format.

The module includes TestAction factories for common metrics operations, making
it easy to build complex test scenarios using the STE (Sub-step Test Executor)
system. All operations are logged using the UTFW logging system for detailed
test documentation and debugging.

Supported metrics types:
- Gauge: Instantaneous measurements that can go up or down
- Counter: Cumulative values that only increase
- Histogram: Sampling observations (not fully parsed)
- Summary: Sampling observations with quantiles (not fully parsed)

Author: DvidMakesThings
"""

import urllib.request
import urllib.error
import re
from typing import Dict, Any, Optional, List, Tuple, Union

from ...core.core import TestAction
from ...core.logger import get_active_logger


class MetricsTestError(Exception):
    """Exception raised when metrics operations or validations fail.
    
    This exception is raised by metrics test functions when HTTP requests fail,
    parsing errors occur, validation fails, or other metrics-related operations
    cannot be completed successfully.
    
    Args:
        message (str): Description of the error that occurred.
    """
    pass


def _parse_prometheus_line(line: str) -> Optional[Tuple[str, Dict[str, str], str]]:
    """Parse a single Prometheus metric line into components.
    
    This internal function parses a Prometheus metric line in the format:
    metric_name{label1="value1",label2="value2"} metric_value
    or
    metric_name metric_value
    
    Args:
        line (str): Single line from Prometheus metrics output.
    
    Returns:
        Optional[Tuple[str, Dict[str, str], str]]: Tuple of 
            (metric_name, labels_dict, value) if parsable, None otherwise.
            Labels dict is empty if no labels present.
    """
    logger = get_active_logger()
    
    # Skip comments and empty lines
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    
    # Pattern to match: metric_name{labels} value or metric_name value
    # This handles both labeled and unlabeled metrics
    match = re.match(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)\s*(?:\{([^}]+)\})?\s+(.+)$', line)
    
    if not match:
        if logger:
            logger.info(f"[METRICS] Could not parse line: '{line}'")
        return None
    
    metric_name = match.group(1)
    labels_str = match.group(2)
    value = match.group(3)
    
    # Parse labels if present
    labels = {}
    if labels_str:
        # Parse label pairs: key="value"
        label_pattern = r'([a-zA-Z_][a-zA-Z0-9_]*)="([^"]*)"'
        for label_match in re.finditer(label_pattern, labels_str):
            labels[label_match.group(1)] = label_match.group(2)
    
    return (metric_name, labels, value)


def fetch_metrics(url: str, timeout: float = 5.0) -> str:
    """Fetch metrics from an HTTP endpoint with logging.
    
    This function retrieves metrics from an HTTP endpoint (typically /metrics)
    and returns the raw text response. It logs all request details and response
    information using the UTFW logging system.
    
    Args:
        url (str): Full URL to the metrics endpoint 
            (e.g., "http://192.168.0.11/metrics").
        timeout (float, optional): Request timeout in seconds. Defaults to 5.0.
    
    Returns:
        str: Raw metrics text from the endpoint.
    
    Raises:
        MetricsTestError: If the HTTP request fails or times out.
    """
    logger = get_active_logger()
    
    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[METRICS] FETCH METRICS")
        logger.info("=" * 80)
        logger.info(f"  URL:     {url}")
        logger.info(f"  Timeout: {timeout}s")
        logger.info("")
    
    try:
        req = urllib.request.Request(url)
        
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = response.getcode()
            content = response.read().decode("utf-8")
            
            if logger:
                line_count = len(content.split('\n'))
                logger.info(f"✓ Metrics received")
                logger.info("-" * 80)
                logger.info(f"  Status:  {status_code}")
                logger.info(f"  Size:    {len(content)} bytes")
                logger.info(f"  Lines:   {line_count}")
                logger.info("")
                
                # Log preview of content
                preview_lines = content.split('\n')[:10]
                logger.info("  Content Preview:")
                for line in preview_lines:
                    if line.strip():
                        logger.info(f"    {line}")
                if line_count > 10:
                    logger.info(f"    ... [{line_count - 10} more lines]")
                logger.info("")
                logger.info("=" * 80)
                logger.info("")
            
            if status_code != 200:
                raise MetricsTestError(f"HTTP GET {url} returned status {status_code}")
            
            return content
    
    except urllib.error.HTTPError as e:
        if logger:
            logger.error("")
            logger.error("✗ HTTP Error")
            logger.error("-" * 80)
            logger.error(f"  Status: {e.code}")
            logger.error(f"  Reason: {e.reason}")
            logger.error(f"  URL:    {url}")
            logger.error("")
            logger.error("=" * 80)
            logger.error("")
        raise MetricsTestError(f"HTTP request failed: {e.code} {e.reason}")
    
    except urllib.error.URLError as e:
        if logger:
            logger.error("")
            logger.error("✗ URL Error")
            logger.error("-" * 80)
            logger.error(f"  Reason: {e.reason}")
            logger.error(f"  URL:    {url}")
            logger.error("")
            logger.error("=" * 80)
            logger.error("")
        raise MetricsTestError(f"URL error: {e.reason}")
    
    except Exception as e:
        if logger:
            logger.error("")
            logger.error("✗ Exception")
            logger.error("-" * 80)
            logger.error(f"  Type:    {type(e).__name__}")
            logger.error(f"  Message: {e}")
            logger.error(f"  URL:     {url}")
            logger.error("")
            logger.error("=" * 80)
            logger.error("")
        raise MetricsTestError(f"Failed to fetch metrics: {type(e).__name__}: {e}")


def parse_metrics(metrics_text: str) -> Dict[str, List[Tuple[Dict[str, str], str]]]:
    """Parse Prometheus-formatted metrics text into structured data.
    
    This function parses Prometheus metrics text format and returns a structured
    dictionary. Each metric name maps to a list of (labels, value) tuples,
    allowing for multiple instances of the same metric with different labels.
    
    Args:
        metrics_text (str): Raw metrics text in Prometheus format.
    
    Returns:
        Dict[str, List[Tuple[Dict[str, str], str]]]: Dictionary where keys are
            metric names and values are lists of (labels_dict, value) tuples.
            For metrics without labels, labels_dict will be empty.
    
    Example:
        >>> text = '''
        ... temperature_celsius 25.5
        ... channel_voltage{ch="1"} 12.0
        ... channel_voltage{ch="2"} 11.9
        ... '''
        >>> metrics = parse_metrics(text)
        >>> metrics['temperature_celsius']
        [({}, '25.5')]
        >>> metrics['channel_voltage']
        [({'ch': '1'}, '12.0'), ({'ch': '2'}, '11.9')]
    """
    logger = get_active_logger()
    
    if logger:
        logger.info("[METRICS] Parsing metrics")
        logger.info(f"  Size: {len(metrics_text)} chars")
    
    metrics: Dict[str, List[Tuple[Dict[str, str], str]]] = {}
    
    for line in metrics_text.split('\n'):
        parsed = _parse_prometheus_line(line)
        if parsed:
            metric_name, labels, value = parsed
            
            if metric_name not in metrics:
                metrics[metric_name] = []
            
            metrics[metric_name].append((labels, value))
    
    if logger:
        logger.info(f"[METRICS] Parsed {len(metrics)} unique metric names")
        for metric_name in sorted(metrics.keys()):
            instance_count = len(metrics[metric_name])
            logger.info(f"[METRICS]   {metric_name}: {instance_count} instance(s)")
    
    return metrics


def get_metric_value(
    metrics: Dict[str, List[Tuple[Dict[str, str], str]]],
    metric_name: str,
    labels: Optional[Dict[str, str]] = None
) -> Optional[str]:
    """Extract a specific metric value from parsed metrics.
    
    This function retrieves the value of a specific metric, optionally filtered
    by label values. If labels are provided, only metrics matching all specified
    labels will be considered.
    
    Args:
        metrics (Dict[str, List[Tuple[Dict[str, str], str]]]): Parsed metrics
            dictionary from parse_metrics().
        metric_name (str): Name of the metric to retrieve.
        labels (Optional[Dict[str, str]], optional): Label filters to match.
            Only metrics with matching labels are considered. Defaults to None
            (match metrics with no labels or return first instance).
    
    Returns:
        Optional[str]: Metric value as string if found, None otherwise.
    
    Example:
        >>> value = get_metric_value(metrics, "temperature_celsius")
        >>> voltage = get_metric_value(metrics, "channel_voltage", {"ch": "1"})
    """
    logger = get_active_logger()
    
    if logger:
        logger.info(f"[METRICS] get_metric_value() called")
        logger.info(f"[METRICS]   Metric: {metric_name}")
        if labels:
            logger.info(f"[METRICS]   Labels: {labels}")
    
    if metric_name not in metrics:
        if logger:
            logger.info(f"[METRICS] Metric '{metric_name}' not found")
        return None
    
    instances = metrics[metric_name]
    
    # If no label filter, return first instance (or first without labels)
    if labels is None:
        # Prefer metrics without labels
        for instance_labels, value in instances:
            if not instance_labels:
                if logger:
                    logger.info(f"[METRICS] Found unlabeled instance: {value}")
                return value
        # If all have labels, return first
        if instances:
            value = instances[0][1]
            if logger:
                logger.info(f"[METRICS] Returning first instance: {value}")
            return value
        return None
    
    # Filter by labels
    for instance_labels, value in instances:
        if all(instance_labels.get(k) == v for k, v in labels.items()):
            if logger:
                logger.info(f"[METRICS] Found matching instance: {value}")
            return value
    
    if logger:
        logger.info(f"[METRICS] No instance matching labels {labels}")
    
    return None


def validate_metric_exists(
    url: str,
    metric_name: str,
    labels: Optional[Dict[str, str]] = None,
    timeout: float = 5.0
) -> bool:
    """Validate that a specific metric exists at the endpoint.
    
    This function fetches and parses metrics from a URL and validates that
    a specific metric (optionally with specific labels) exists in the output.
    
    Args:
        url (str): Metrics endpoint URL.
        metric_name (str): Name of the metric to check.
        labels (Optional[Dict[str, str]], optional): Label filters. Defaults to None.
        timeout (float, optional): Request timeout in seconds. Defaults to 5.0.
    
    Returns:
        bool: True if the metric exists, False otherwise.
    
    Raises:
        MetricsTestError: If fetching or parsing metrics fails.
    """
    logger = get_active_logger()
    
    if logger:
        logger.info(f"[METRICS] validate_metric_exists() called")
        logger.info(f"[METRICS]   Metric: {metric_name}, Labels: {labels}")
    
    metrics_text = fetch_metrics(url, timeout)
    metrics = parse_metrics(metrics_text)
    value = get_metric_value(metrics, metric_name, labels)
    
    exists = value is not None
    
    if logger:
        if exists:
            logger.info(f"[METRICS]  Metric '{metric_name}' exists with value: {value}")
        else:
            logger.info(f"[METRICS] âœ— Metric '{metric_name}' not found")
    
    return exists


def validate_metric_value(
    url: str,
    metric_name: str,
    expected_value: str,
    labels: Optional[Dict[str, str]] = None,
    timeout: float = 5.0
) -> bool:
    """Validate that a metric has an expected value.
    
    This function fetches metrics and validates that a specific metric has
    the expected string value. String comparison is case-sensitive.
    
    Args:
        url (str): Metrics endpoint URL.
        metric_name (str): Name of the metric to check.
        expected_value (str): Expected value as string.
        labels (Optional[Dict[str, str]], optional): Label filters. Defaults to None.
        timeout (float, optional): Request timeout in seconds. Defaults to 5.0.
    
    Returns:
        bool: True if the metric exists and has the expected value.
    
    Raises:
        MetricsTestError: If fetching/parsing fails or metric doesn't exist.
    """
    logger = get_active_logger()
    
    if logger:
        logger.info(f"[METRICS] validate_metric_value() called")
        logger.info(f"[METRICS]   Metric: {metric_name}")
        logger.info(f"[METRICS]   Expected: {expected_value}")
        if labels:
            logger.info(f"[METRICS]   Labels: {labels}")
    
    metrics_text = fetch_metrics(url, timeout)
    metrics = parse_metrics(metrics_text)
    value = get_metric_value(metrics, metric_name, labels)
    
    if value is None:
        if logger:
            logger.error(f"[METRICS ERROR] Metric '{metric_name}' not found")
        raise MetricsTestError(f"Metric '{metric_name}' not found")
    
    matches = value == expected_value
    
    if logger:
        if matches:
            logger.info(f"[METRICS]  Metric value matches: {value}")
        else:
            logger.error(f"[METRICS ERROR] Value mismatch: expected '{expected_value}', got '{value}'")
    
    return matches


def validate_metric_range(
    url: str,
    metric_name: str,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    labels: Optional[Dict[str, str]] = None,
    timeout: float = 5.0
) -> float:
    """Validate that a numeric metric falls within a specified range.
    
    This function fetches metrics and validates that a numeric metric value
    falls within the specified minimum and maximum bounds (inclusive). At least
    one of min_value or max_value must be specified.
    
    Args:
        url (str): Metrics endpoint URL.
        metric_name (str): Name of the metric to check.
        min_value (Optional[float], optional): Minimum acceptable value (inclusive).
            Defaults to None (no lower bound).
        max_value (Optional[float], optional): Maximum acceptable value (inclusive).
            Defaults to None (no upper bound).
        labels (Optional[Dict[str, str]], optional): Label filters. Defaults to None.
        timeout (float, optional): Request timeout in seconds. Defaults to 5.0.
    
    Returns:
        float: The actual metric value if validation passes.
    
    Raises:
        MetricsTestError: If fetching/parsing fails, metric doesn't exist,
            cannot be parsed as float, or is out of range.
    """
    logger = get_active_logger()
    
    if logger:
        logger.info("")
        logger.info("=" * 80)
        logger.info("[METRICS] VALIDATE METRIC RANGE")
        logger.info("=" * 80)
        logger.info(f"  Metric: {metric_name}")
        if labels:
            logger.info(f"  Labels: {labels}")
        if min_value is not None and max_value is not None:
            logger.info(f"  Range:  {min_value} {max_value}")
        elif min_value is not None:
            logger.info(f"  Min:    {min_value}")
        elif max_value is not None:
            logger.info(f"  Max:    {max_value}")
        logger.info("")
    
    if min_value is None and max_value is None:
        raise MetricsTestError("At least one of min_value or max_value must be specified")
    
    metrics_text = fetch_metrics(url, timeout)
    metrics = parse_metrics(metrics_text)
    value_str = get_metric_value(metrics, metric_name, labels)
    
    if value_str is None:
        if logger:
            logger.error("")
            logger.error("✗ Metric not found")
            logger.error("-" * 80)
            logger.error(f"  Metric: {metric_name}")
            if labels:
                logger.error(f"  Labels: {labels}")
            logger.error("")
            logger.error("=" * 80)
            logger.error("")
        raise MetricsTestError(f"Metric '{metric_name}' not found")
    
    try:
        value = float(value_str)
    except ValueError as e:
        if logger:
            logger.error("")
            logger.error("✗ Cannot parse as float")
            logger.error("-" * 80)
            logger.error(f"  Value:   {value_str}")
            logger.error(f"  Error:   {e}")
            logger.error("")
            logger.error("=" * 80)
            logger.error("")
        raise MetricsTestError(f"Cannot parse metric value '{value_str}' as float")
    
    # Validate range
    if min_value is not None and value < min_value:
        if logger:
            logger.error(f"[METRICS ERROR] Value {value} below minimum {min_value}")
        raise MetricsTestError(
            f"Metric '{metric_name}' value {value} is below minimum {min_value}"
        )
    
    if max_value is not None and value > max_value:
        if logger:
            logger.error(f"[METRICS ERROR] Value {value} above maximum {max_value}")
        raise MetricsTestError(
            f"Metric '{metric_name}' value {value} is above maximum {max_value}"
        )
    
    if logger:
        range_str = ""
        if min_value is not None and max_value is not None:
            range_str = f" (range: {min_value}-{max_value})"
        elif min_value is not None:
            range_str = f" (min: {min_value})"
        elif max_value is not None:
            range_str = f" (max: {max_value})"
        logger.info(f"[METRICS]  Value {value} within range{range_str}")
    
    return value


def compare_metrics(
    url: str,
    metric1_name: str,
    metric2_name: str,
    comparison: str = "equal",
    metric1_labels: Optional[Dict[str, str]] = None,
    metric2_labels: Optional[Dict[str, str]] = None,
    tolerance: float = 0.0,
    timeout: float = 5.0
) -> Tuple[float, float]:
    """Compare two numeric metrics against each other.
    
    This function fetches metrics and compares two numeric values using the
    specified comparison operation. Useful for validating relationships between
    metrics or checking consistency.
    
    Args:
        url (str): Metrics endpoint URL.
        metric1_name (str): Name of the first metric.
        metric2_name (str): Name of the second metric.
        comparison (str, optional): Comparison operation. One of:
            - "equal": metric1 == metric2 (within tolerance)
            - "greater": metric1 > metric2
            - "less": metric1 < metric2
            - "greater_equal": metric1 >= metric2
            - "less_equal": metric1 <= metric2
            Defaults to "equal".
        metric1_labels (Optional[Dict[str, str]], optional): Labels for first metric.
        metric2_labels (Optional[Dict[str, str]], optional): Labels for second metric.
        tolerance (float, optional): Tolerance for "equal" comparison. 
            Defaults to 0.0 (exact match).
        timeout (float, optional): Request timeout in seconds. Defaults to 5.0.
    
    Returns:
        Tuple[float, float]: Tuple of (metric1_value, metric2_value).
    
    Raises:
        MetricsTestError: If fetching/parsing fails, metrics don't exist,
            cannot be parsed as floats, or comparison fails.
    """
    logger = get_active_logger()
    
    if logger:
        logger.info(f"[METRICS] compare_metrics() called")
        logger.info(f"[METRICS]   Metric1: {metric1_name}, Metric2: {metric2_name}")
        logger.info(f"[METRICS]   Comparison: {comparison}, Tolerance: {tolerance}")
    
    valid_comparisons = ["equal", "greater", "less", "greater_equal", "less_equal"]
    if comparison not in valid_comparisons:
        raise MetricsTestError(
            f"Invalid comparison '{comparison}'. Must be one of: {valid_comparisons}"
        )
    
    metrics_text = fetch_metrics(url, timeout)
    metrics = parse_metrics(metrics_text)
    
    # Get first metric
    value1_str = get_metric_value(metrics, metric1_name, metric1_labels)
    if value1_str is None:
        raise MetricsTestError(f"Metric '{metric1_name}' not found")
    
    try:
        value1 = float(value1_str)
    except ValueError:
        raise MetricsTestError(
            f"Cannot parse metric '{metric1_name}' value '{value1_str}' as float"
        )
    
    # Get second metric
    value2_str = get_metric_value(metrics, metric2_name, metric2_labels)
    if value2_str is None:
        raise MetricsTestError(f"Metric '{metric2_name}' not found")
    
    try:
        value2 = float(value2_str)
    except ValueError:
        raise MetricsTestError(
            f"Cannot parse metric '{metric2_name}' value '{value2_str}' as float"
        )
    
    if logger:
        logger.info(f"[METRICS]   Value1: {value1}, Value2: {value2}")
    
    # Perform comparison
    result = False
    if comparison == "equal":
        result = abs(value1 - value2) <= tolerance
    elif comparison == "greater":
        result = value1 > value2
    elif comparison == "less":
        result = value1 < value2
    elif comparison == "greater_equal":
        result = value1 >= value2
    elif comparison == "less_equal":
        result = value1 <= value2
    
    if not result:
        if logger:
            logger.error(
                f"[METRICS ERROR] Comparison failed: {value1} {comparison} {value2}"
            )
        raise MetricsTestError(
            f"Comparison failed: {metric1_name}={value1} {comparison} "
            f"{metric2_name}={value2}"
        )
    
    if logger:
        logger.info(f"[METRICS]  Comparison passed: {value1} {comparison} {value2}")
    
    return (value1, value2)


def get_all_labels_for_metric(
    url: str,
    metric_name: str,
    timeout: float = 5.0
) -> List[Dict[str, str]]:
    """Get all label combinations for a specific metric.
    
    This function fetches metrics and returns a list of all label dictionaries
    for instances of the specified metric. Useful for discovering available
    channels, instances, or other labeled variations of a metric.
    
    Args:
        url (str): Metrics endpoint URL.
        metric_name (str): Name of the metric to query.
        timeout (float, optional): Request timeout in seconds. Defaults to 5.0.
    
    Returns:
        List[Dict[str, str]]: List of label dictionaries, one for each instance
            of the metric. Empty list if metric not found.
    
    Example:
        >>> labels = get_all_labels_for_metric(url, "channel_voltage")
        >>> # Returns: [{'ch': '1'}, {'ch': '2'}, {'ch': '3'}, ...]
    """
    logger = get_active_logger()
    
    if logger:
        logger.info(f"[METRICS] get_all_labels_for_metric() called")
        logger.info(f"[METRICS]   Metric: {metric_name}")
    
    metrics_text = fetch_metrics(url, timeout)
    metrics = parse_metrics(metrics_text)
    
    if metric_name not in metrics:
        if logger:
            logger.info(f"[METRICS] Metric '{metric_name}' not found")
        return []
    
    labels_list = [labels for labels, value in metrics[metric_name]]
    
    if logger:
        logger.info(f"[METRICS] Found {len(labels_list)} instance(s) of '{metric_name}'")
        for i, labels in enumerate(labels_list, 1):
            logger.info(f"[METRICS]   Instance {i}: {labels}")
    
    return labels_list


# ============================================================================
# TestAction Factories
# ============================================================================


def check_metric_exists(
    name: str,
    url: str,
    metric_name: str,
    labels: Optional[Dict[str, str]] = None,
    timeout: float = 5.0,
    negative_test: bool = False
) -> TestAction:
    """Create a TestAction that validates a metric exists.
    
    This TestAction factory creates an action that fetches and parses metrics
    from a URL and validates that a specific metric (optionally with specific
    labels) exists in the output. The action fails if the metric is not found.
    
    Args:
        name (str): Human-readable name for the test action.
        url (str): Metrics endpoint URL (e.g., "http://192.168.0.11/metrics").
        metric_name (str): Name of the metric to check for existence.
        labels (Optional[Dict[str, str]], optional): Label filters to match
            specific metric instances. Defaults to None (any instance).
        timeout (float, optional): HTTP request timeout in seconds. Defaults to 5.0.
        negative_test (bool, optional): If True, expect the test to fail.
            Defaults to False.
    
    Returns:
        TestAction: TestAction that returns True when the metric exists.
    
    Raises:
        MetricsTestError: When executed, raises this exception if the metric
            is not found or if fetching/parsing fails.
    
    Example:
        >>> # Check for a simple metric
        >>> action1 = check_metric_exists(
        ...     "Verify uptime metric exists",
        ...     "http://192.168.0.11/metrics",
        ...     "energis_uptime_seconds_total"
        ... )
        >>> 
        >>> # Check for a labeled metric
        >>> action2 = check_metric_exists(
        ...     "Verify channel 1 voltage metric exists",
        ...     "http://192.168.0.11/metrics",
        ...     "energis_channel_voltage_volts",
        ...     labels={"ch": "1"}
        ... )
    """
    def execute():
        if not validate_metric_exists(url, metric_name, labels, timeout):
            labels_str = f" with labels {labels}" if labels else ""
            raise MetricsTestError(f"Metric '{metric_name}'{labels_str} not found")
        return True

    labels_desc = f" {labels}" if labels else ""
    metadata = {'sent': f"GET {url} (check metric: {metric_name}{labels_desc})"}
    return TestAction(name, execute, metadata=metadata, negative_test=negative_test)


def check_metric_value(
    name: str,
    url: str,
    metric_name: str,
    expected_value: str,
    labels: Optional[Dict[str, str]] = None,
    timeout: float = 5.0,
    negative_test: bool = False
) -> TestAction:
    """Create a TestAction that validates a metric has an expected value.
    
    This TestAction factory creates an action that fetches metrics and validates
    that a specific metric has the expected string value. Comparison is
    case-sensitive and exact.
    
    Args:
        name (str): Human-readable name for the test action.
        url (str): Metrics endpoint URL.
        metric_name (str): Name of the metric to validate.
        expected_value (str): Expected value as string (will be compared exactly).
        labels (Optional[Dict[str, str]], optional): Label filters. Defaults to None.
        timeout (float, optional): HTTP request timeout in seconds. Defaults to 5.0.
        negative_test (bool, optional): If True, expect the test to fail.
            Defaults to False.
    
    Returns:
        TestAction: TestAction that returns True when the metric value matches.
    
    Raises:
        MetricsTestError: When executed, raises this exception if the metric
            is not found, value doesn't match, or if fetching/parsing fails.
    
    Example:
        >>> # Validate boolean/state metric
        >>> action1 = check_metric_value(
        ...     "Verify temperature calibration enabled",
        ...     "http://192.168.0.11/metrics",
        ...     "energis_temp_calibrated",
        ...     "1"
        ... )
        >>> 
        >>> # Validate channel state
        >>> action2 = check_metric_value(
        ...     "Verify channel 1 is OFF",
        ...     "http://192.168.0.11/metrics",
        ...     "energis_channel_state",
        ...     "0",
        ...     labels={"ch": "1"}
        ... )
    """
    def execute():
        if not validate_metric_value(url, metric_name, expected_value, labels, timeout):
            labels_str = f" with labels {labels}" if labels else ""
            raise MetricsTestError(
                f"Metric '{metric_name}'{labels_str} value does not match expected"
            )
        return True

    labels_desc = f" {labels}" if labels else ""
    metadata = {'sent': f"GET {url} (check {metric_name}{labels_desc}={expected_value})"}
    return TestAction(name, execute, metadata=metadata, negative_test=negative_test)


def check_metric_range(
    name: str,
    url: str,
    metric_name: str,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    labels: Optional[Dict[str, str]] = None,
    timeout: float = 5.0,
    negative_test: bool = False
) -> TestAction:
    """Create a TestAction that validates a numeric metric is within range.
    
    This TestAction factory creates an action that fetches metrics and validates
    that a numeric metric value falls within the specified minimum and maximum
    bounds (inclusive). At least one of min_value or max_value must be specified.
    
    Args:
        name (str): Human-readable name for the test action.
        url (str): Metrics endpoint URL.
        metric_name (str): Name of the metric to validate.
        min_value (Optional[float], optional): Minimum acceptable value (inclusive).
            Defaults to None (no lower bound).
        max_value (Optional[float], optional): Maximum acceptable value (inclusive).
            Defaults to None (no upper bound).
        labels (Optional[Dict[str, str]], optional): Label filters. Defaults to None.
        timeout (float, optional): HTTP request timeout in seconds. Defaults to 5.0.
        negative_test (bool, optional): If True, expect the test to fail.
            Defaults to False.
    
    Returns:
        TestAction: TestAction that returns the metric value if validation passes.
    
    Raises:
        MetricsTestError: When executed, raises this exception if the metric
            is not found, out of range, cannot be parsed as float, or if
            fetching/parsing fails.
    
    Example:
        >>> # Validate temperature in range
        >>> action1 = check_metric_range(
        ...     "Check internal temperature",
        ...     "http://192.168.0.11/metrics",
        ...     "energis_internal_temperature_celsius",
        ...     min_value=20.0,
        ...     max_value=35.0
        ... )
        >>> 
        >>> # Validate voltage with only minimum
        >>> action2 = check_metric_range(
        ...     "Check USB voltage above 4.5V",
        ...     "http://192.168.0.11/metrics",
        ...     "energis_vusb_volts",
        ...     min_value=4.5
        ... )
        >>> 
        >>> # Validate channel voltage
        >>> action3 = check_metric_range(
        ...     "Check channel 1 voltage nominal",
        ...     "http://192.168.0.11/metrics",
        ...     "energis_channel_voltage_volts",
        ...     min_value=11.5,
        ...     max_value=12.5,
        ...     labels={"ch": "1"}
        ... )
    """
    def execute():
        value = validate_metric_range(
            url, metric_name, min_value, max_value, labels, timeout
        )
        return value

    labels_desc = f" {labels}" if labels else ""
    range_desc = ""
    if min_value is not None and max_value is not None:
        range_desc = f" in [{min_value}, {max_value}]"
    elif min_value is not None:
        range_desc = f" >= {min_value}"
    elif max_value is not None:
        range_desc = f" <= {max_value}"
    metadata = {'sent': f"GET {url} (check {metric_name}{labels_desc}{range_desc})"}
    return TestAction(name, execute, metadata=metadata, negative_test=negative_test)


def check_metrics_comparison(
    name: str,
    url: str,
    metric1_name: str,
    metric2_name: str,
    comparison: str = "equal",
    metric1_labels: Optional[Dict[str, str]] = None,
    metric2_labels: Optional[Dict[str, str]] = None,
    tolerance: float = 0.0,
    timeout: float = 5.0,
    negative_test: bool = False
) -> TestAction:
    """Create a TestAction that compares two metrics against each other.
    
    This TestAction factory creates an action that fetches metrics and compares
    two numeric values using the specified comparison operation. Useful for
    validating relationships between metrics or checking consistency.
    
    Args:
        name (str): Human-readable name for the test action.
        url (str): Metrics endpoint URL.
        metric1_name (str): Name of the first metric.
        metric2_name (str): Name of the second metric.
        comparison (str, optional): Comparison operation. One of:
            - "equal": metric1 == metric2 (within tolerance)
            - "greater": metric1 > metric2
            - "less": metric1 < metric2
            - "greater_equal": metric1 >= metric2
            - "less_equal": metric1 <= metric2
            Defaults to "equal".
        metric1_labels (Optional[Dict[str, str]], optional): Labels for first metric.
        metric2_labels (Optional[Dict[str, str]], optional): Labels for second metric.
        tolerance (float, optional): Tolerance for "equal" comparison.
            Defaults to 0.0 (exact match).
        timeout (float, optional): HTTP request timeout in seconds. Defaults to 5.0.
        negative_test (bool, optional): If True, expect the test to fail.
            Defaults to False.
    
    Returns:
        TestAction: TestAction that returns a tuple of (value1, value2) if
            comparison passes.
    
    Raises:
        MetricsTestError: When executed, raises this exception if metrics
            are not found, cannot be parsed, comparison fails, or if
            fetching/parsing fails.
    
    Example:
        >>> # Compare two voltages are approximately equal
        >>> action1 = check_metrics_comparison(
        ...     "Verify CH1 and CH2 voltages match",
        ...     "http://192.168.0.11/metrics",
        ...     "energis_channel_voltage_volts",
        ...     "energis_channel_voltage_volts",
        ...     comparison="equal",
        ...     metric1_labels={"ch": "1"},
        ...     metric2_labels={"ch": "2"},
        ...     tolerance=0.1
        ... )
        >>> 
        >>> # Verify supply voltage is greater than USB voltage
        >>> action2 = check_metrics_comparison(
        ...     "Verify supply voltage > USB voltage",
        ...     "http://192.168.0.11/metrics",
        ...     "energis_vsupply_volts",
        ...     "energis_vusb_volts",
        ...     comparison="greater"
        ... )
    """
    def execute():
        values = compare_metrics(
            url, metric1_name, metric2_name, comparison,
            metric1_labels, metric2_labels, tolerance, timeout
        )
        return values

    m1_labels = f"{metric1_labels}" if metric1_labels else ""
    m2_labels = f"{metric2_labels}" if metric2_labels else ""
    metadata = {'sent': f"GET {url} (compare {metric1_name}{m1_labels} {comparison} {metric2_name}{m2_labels})"}
    return TestAction(name, execute, metadata=metadata, negative_test=negative_test)


def read_metric(
    name: str,
    url: str,
    metric_name: str,
    labels: Optional[Dict[str, str]] = None,
    timeout: float = 5.0,
    negative_test: bool = False
) -> TestAction:
    """Create a TestAction that reads and logs a metric value.
    
    This TestAction factory creates an action that fetches metrics and reads
    a specific metric value, logging it for documentation purposes. This is
    useful for recording metric values during tests without performing validation.
    
    Args:
        name (str): Human-readable name for the test action.
        url (str): Metrics endpoint URL.
        metric_name (str): Name of the metric to read.
        labels (Optional[Dict[str, str]], optional): Label filters. Defaults to None.
        timeout (float, optional): HTTP request timeout in seconds. Defaults to 5.0.
        negative_test (bool, optional): If True, expect the test to fail.
            Defaults to False.
    
    Returns:
        TestAction: TestAction that returns the metric value as string.
    
    Raises:
        MetricsTestError: When executed, raises this exception if the metric
            is not found or if fetching/parsing fails.
    
    Example:
        >>> # Read and log uptime
        >>> action1 = read_metric(
        ...     "Record system uptime",
        ...     "http://192.168.0.11/metrics",
        ...     "energis_uptime_seconds_total"
        ... )
        >>> 
        >>> # Read channel power
        >>> action2 = read_metric(
        ...     "Record channel 1 power consumption",
        ...     "http://192.168.0.11/metrics",
        ...     "energis_channel_power_watts",
        ...     labels={"ch": "1"}
        ... )
    """
    def execute():
        logger = get_active_logger()
        metrics_text = fetch_metrics(url, timeout)
        metrics = parse_metrics(metrics_text)
        value = get_metric_value(metrics, metric_name, labels)
        
        if value is None:
            labels_str = f" with labels {labels}" if labels else ""
            raise MetricsTestError(f"Metric '{metric_name}'{labels_str} not found")
        
        if logger:
            labels_str = f" {labels}" if labels else ""
            logger.info(f"[METRICS] Read metric '{metric_name}'{labels_str}: {value}")


        return value

    labels_desc = f" {labels}" if labels else ""
    metadata = {'sent': f"GET {url} (read {metric_name}{labels_desc})"}
    return TestAction(name, execute, metadata=metadata, negative_test=negative_test)


def check_all_channels_state(
    name: str,
    url: str,
    expected_state: int,
    channel_count: int = 8,
    metric_name: str = "energis_channel_state",
    timeout: float = 5.0,
    negative_test: bool = False
) -> TestAction:
    """Create a TestAction that validates all channels have a specific state.
    
    This TestAction factory creates an action that validates all channels
    (or a specified number of channels) have the expected state value. This is
    useful for verifying that all channels are in a known state (e.g., all OFF).
    
    Args:
        name (str): Human-readable name for the test action.
        url (str): Metrics endpoint URL.
        expected_state (int): Expected state value (typically 0 for OFF, 1 for ON).
        channel_count (int, optional): Number of channels to check. Defaults to 8.
        metric_name (str, optional): Name of the channel state metric.
            Defaults to "energis_channel_state".
        timeout (float, optional): HTTP request timeout in seconds. Defaults to 5.0.
        negative_test (bool, optional): If True, expect the test to fail.
            Defaults to False.
    
    Returns:
        TestAction: TestAction that returns True when all channels match
            the expected state.
    
    Raises:
        MetricsTestError: When executed, raises this exception if any channel
            doesn't match the expected state, if metrics are not found, or if
            fetching/parsing fails.
    
    Example:
        >>> # Verify all channels are OFF
        >>> action1 = check_all_channels_state(
        ...     "Verify all channels OFF",
        ...     "http://192.168.0.11/metrics",
        ...     expected_state=0
        ... )
        >>> 
        >>> # Verify all channels are ON
        >>> action2 = check_all_channels_state(
        ...     "Verify all channels ON",
        ...     "http://192.168.0.11/metrics",
        ...     expected_state=1
        ... )
    """
    def execute():
        logger = get_active_logger()
        metrics_text = fetch_metrics(url, timeout)
        metrics = parse_metrics(metrics_text)
        
        expected_str = str(expected_state)
        failed_channels = []
        
        for ch in range(1, channel_count + 1):
            value = get_metric_value(metrics, metric_name, {"ch": str(ch)})
            
            if value is None:
                failed_channels.append(f"CH{ch} (not found)")
            elif value != expected_str:
                failed_channels.append(f"CH{ch} (state={value})")
        
        if failed_channels:
            if logger:
                logger.error(
                    f"[METRICS ERROR] Channels not in expected state {expected_state}: "
                    f"{', '.join(failed_channels)}"
                )
            raise MetricsTestError(
                f"Channels not in expected state {expected_state}: "
                f"{', '.join(failed_channels)}"
            )
        
        if logger:
            logger.info(
                f"[METRICS]  All {channel_count} channels in state {expected_state}"
            )


        return True

    state_desc = "ON" if expected_state == 1 else "OFF" if expected_state == 0 else str(expected_state)
    metadata = {'sent': f"GET {url} (check all {channel_count} channels {state_desc})"}
    return TestAction(name, execute, metadata=metadata, negative_test=negative_test)


def wait_for_metric_condition(
    name: str,
    url: str,
    metric_name: str,
    condition: str,
    target_value: Union[str, float],
    labels: Optional[Dict[str, str]] = None,
    timeout: float = 30.0,
    poll_interval: float = 1.0,
    request_timeout: float = 5.0,
    negative_test: bool = False
) -> TestAction:
    """Create a TestAction that waits for a metric to meet a condition.
    
    This TestAction factory creates an action that polls a metrics endpoint
    until a specific metric meets the specified condition, or until a timeout
    occurs. This is useful for waiting for state changes or value convergence.
    
    Args:
        name (str): Human-readable name for the test action.
        url (str): Metrics endpoint URL.
        metric_name (str): Name of the metric to monitor.
        condition (str): Condition to wait for. One of:
            - "equals": metric == target_value (string comparison)
            - "not_equals": metric != target_value (string comparison)
            - "greater": metric > target_value (numeric)
            - "less": metric < target_value (numeric)
            - "greater_equal": metric >= target_value (numeric)
            - "less_equal": metric <= target_value (numeric)
        target_value (Union[str, float]): Target value to compare against.
        labels (Optional[Dict[str, str]], optional): Label filters. Defaults to None.
        timeout (float, optional): Maximum time to wait in seconds. Defaults to 30.0.
        poll_interval (float, optional): Time between polls in seconds. Defaults to 1.0.
        request_timeout (float, optional): HTTP request timeout for each poll.
            Defaults to 5.0.
        negative_test (bool, optional): If True, expect the test to fail.
            Defaults to False.
    
    Returns:
        TestAction: TestAction that returns the final metric value when
            condition is met.
    
    Raises:
        MetricsTestError: When executed, raises this exception if the condition
            is not met within the timeout period, or if fetching/parsing fails.
    
    Example:
        >>> # Wait for uptime to exceed 10 seconds
        >>> action1 = wait_for_metric_condition(
        ...     "Wait for device boot complete",
        ...     "http://192.168.0.11/metrics",
        ...     "energis_uptime_seconds_total",
        ...     condition="greater",
        ...     target_value=10.0,
        ...     timeout=60.0
        ... )
        >>> 
        >>> # Wait for channel to turn ON
        >>> action2 = wait_for_metric_condition(
        ...     "Wait for channel 1 ON",
        ...     "http://192.168.0.11/metrics",
        ...     "energis_channel_state",
        ...     condition="equals",
        ...     target_value="1",
        ...     labels={"ch": "1"},
        ...     timeout=10.0
        ... )
    """
    import time
    
    def execute():
        logger = get_active_logger()
        
        if logger:
            logger.info("")
            logger.info("=" * 80)
            logger.info("[METRICS] WAIT FOR CONDITION")
            logger.info("=" * 80)
            logger.info(f"  Metric:    {metric_name}")
            if labels:
                logger.info(f"  Labels:    {labels}")
            logger.info(f"  Condition: {condition}")
            logger.info(f"  Target:    {target_value}")
            logger.info(f"  Timeout:   {timeout}s")
            logger.info(f"  Poll:      {poll_interval}s")
            logger.info("")
        
        valid_conditions = [
            "equals", "not_equals", "greater", "less", "greater_equal", "less_equal"
        ]
        if condition not in valid_conditions:
            raise MetricsTestError(
                f"Invalid condition '{condition}'. Must be one of: {valid_conditions}"
            )
        
        start_time = time.time()
        poll_count = 0
        
        while True:
            poll_count += 1
            elapsed = time.time() - start_time
            
            if elapsed > timeout:
                if logger:
                    logger.error("")
                    logger.error(f"✗ Timeout after {elapsed:.1f}s ({poll_count} polls)")
                    logger.error("-" * 80)
                    logger.error(f"  Metric:    {metric_name}")
                    logger.error(f"  Condition: {condition}")
                    logger.error(f"  Target:    {target_value}")
                    logger.error("")
                    logger.error("=" * 80)
                    logger.error("")
                raise MetricsTestError(
                    f"Timeout waiting for {metric_name} {condition} {target_value} "
                    f"(waited {elapsed:.1f}s)"
                )
            
            try:
                metrics_text = fetch_metrics(url, request_timeout)
                metrics = parse_metrics(metrics_text)
                value_str = get_metric_value(metrics, metric_name, labels)
                
                if value_str is None:
                    if logger:
                        logger.info(
                            f"[METRICS] Poll {poll_count}: Metric not found, retrying..."
                        )
                    time.sleep(poll_interval)
                    continue
                
                # Check condition
                condition_met = False
                
                if condition in ["equals", "not_equals"]:
                    # String comparison
                    if condition == "equals":
                        condition_met = value_str == str(target_value)
                    else:
                        condition_met = value_str != str(target_value)
                else:
                    # Numeric comparison
                    try:
                        value = float(value_str)
                        target = float(target_value)
                        
                        if condition == "greater":
                            condition_met = value > target
                        elif condition == "less":
                            condition_met = value < target
                        elif condition == "greater_equal":
                            condition_met = value >= target
                        elif condition == "less_equal":
                            condition_met = value <= target
                    except ValueError:
                        if logger:
                            logger.error(
                                f"[METRICS ERROR] Cannot parse values as numeric: "
                                f"'{value_str}', '{target_value}'"
                            )
                        raise MetricsTestError(
                            f"Cannot perform numeric comparison on non-numeric values"
                        )
                
                if condition_met:
                    if logger:
                        logger.info(
                            f"[METRICS]  Condition met after {elapsed:.1f}s "
                            f"({poll_count} polls): {value_str} {condition} {target_value}"
                        )
                    return value_str
                
                if logger and poll_count % 5 == 0:
                    # Log progress every 5 polls
                    logger.info(
                        f"[METRICS] Poll {poll_count}: Current value {value_str}, "
                        f"waiting for {condition} {target_value}... ({elapsed:.1f}s elapsed)"
                    )
                
                time.sleep(poll_interval)
            
            except MetricsTestError:
                # Re-raise metrics errors
                raise
            except Exception as e:
                if logger:
                    logger.error(f"[METRICS ERROR] Poll {poll_count} failed: {e}")
                time.sleep(poll_interval)

    labels_desc = f" {labels}" if labels else ""
    metadata = {'sent': f"GET {url} (wait for {metric_name}{labels_desc} {condition} {target_value})"}
    return TestAction(name, execute, metadata=metadata, negative_test=negative_test)