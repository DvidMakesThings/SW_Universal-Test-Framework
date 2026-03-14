# generate_test_report.py

"""
================================================================================
ENERGIS UART Test Report Generator
--------------------------------------------------------------------------------
Purpose:
    Convert the plain-text execution log produced by `_SoftwareTest/tc_serial.py`
    into a structured, human-friendly HTML report and (optionally) a JUnit XML
    artifact for CI systems.

Inputs:
    - The test execution log (default: _SoftwareTest/Reports/tc_serial_results.log)

Outputs (defaults under _SoftwareTest/Reports):
    - tc_serial_report.html : Styled, interactive HTML report
    - tc_serial_report.xml  : JUnit XML (optional via --junit)

Usage:
    python generate_test_report.py \
        --log _SoftwareTest/Reports/tc_serial_results.log \
        --out-html _SoftwareTest/Reports/tc_serial_report.html \
        --junit _SoftwareTest/Reports/tc_serial_report.xml

Notes:
    - No external deps; pure Python 3.
    - The parser expects lines in the form:
        [YYYY-mm-dd HH:MM:SS] <LEVEL/TEXT>
      e.g.:
        [2025-08-22 22:48:30] [STEP 1] HELP
        [2025-08-22 22:48:34] [PASS] HELP command lists all required tokens.
        [2025-08-22 22:48:39] ===== RESULT: PASS =====
    - It will group events into "steps" and compute pass/fail statistics.

Author: DvidMakesThings
================================================================================
"""

from __future__ import annotations

import argparse
import html
import json
import os
import platform
import re
import socket
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple


# ------------------------------- Data Structures -------------------------------

TIMESTAMP_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+(.*)$")
STEP_START_RE = re.compile(r"^\[((?:PRE-STEP|STEP|POST-STEP|TEARDOWN)(?:\s+[^\]]+)?)\]\s*(.*)$")
LEVEL_TAG_RE = re.compile(r"^\[([A-Z]+)\]\s*(.*)$")
RESULT_RE = re.compile(r"^=+\s+RESULT:\s+(PASS|FAIL)\s+=+$", re.I)

@dataclass
class LogEvent:
    ts: str
    raw: str
    tag: Optional[str] = None     # e.g., STEP 1, PASS, FAIL, INFO, WARN
    text: str = ""


@dataclass
class TestStep:
    name: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    lines: List[LogEvent] = field(default_factory=list)
    status: str = "UNKNOWN"  # PASS/FAIL/UNKNOWN
    is_negative_test: bool = False

    def close_with_status(self):
        # Determine status from contained events
        has_fail = False
        has_pass = False

        for ev in self.lines:
            if ev.tag == "FAIL":
                has_fail = True
            elif ev.tag == "PASS":
                has_pass = True

        # Priority: FAIL > PASS
        if has_fail:
            self.status = "FAIL"
        elif has_pass:
            self.status = "PASS"
        else:
            self.status = "UNKNOWN"


@dataclass
class ReportModel:
    log_path: Path
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    steps: List[TestStep] = field(default_factory=list)
    other_events: List[LogEvent] = field(default_factory=list)
    overall: str = "UNKNOWN"
    meta: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None


# ---------------------------------- Parsing ------------------------------------
def _rel_href(target: Path, base_dir: Path) -> str:
    """
    Return a POSIX-style relative path from base_dir to target.
    Falls back to filename if a relative path cannot be computed (e.g., different drive).
    """
    try:
        rel = target.resolve().relative_to(base_dir.resolve())
    except Exception:
        try:
            rel = Path(os.path.relpath(str(target), str(base_dir)))
        except Exception:
            rel = Path(target.name)
    return rel.as_posix()

def _discover_images_and_artifacts(reports_dir: Path, out_html: Path) -> Tuple[Optional[Path], Optional[Path], Dict[str, List[Path]]]:
    """
    Find EEPROM logs and collect images/pcaps to embed or link in the HTML.

    Returns:
        (eeprom_ascii, eeprom_raw, images) where images is a dict with keys:
            "step2", "step3", "step4", "step5", "overall", "general"

    Notes:
        Besides image files (png/jpg/jpeg/svg), this also collects packet capture
        files (.pcap, .pcapng) so they can be linked from the report.
    """
    # EEPROM (unchanged)
    eeprom_dir = reports_dir / "EEPROM"
    eeprom_ascii = None
    eeprom_raw = None
    if eeprom_dir.exists():
        for p in list(eeprom_dir.glob("eeprom_dump_ascii.*")) + [eeprom_dir / "eeprom_dump_ascii.log"]:
            if p.exists():
                eeprom_ascii = p
                break
        for p in list(eeprom_dir.glob("eeprom_dump_raw.*")) + [eeprom_dir / "eeprom_dump_raw.log"]:
            if p.exists():
                eeprom_raw = p
                break

    # Nested helper
    def _add_img(path: Path, bag: set) -> None:
        try:
            if path.exists() and path.is_file():
                bag.add(path.resolve())
        except Exception:
            pass

    # Include common image types + packet capture artifacts
    img_exts = {".png", ".jpg", ".jpeg", ".svg", ".pcap", ".pcapng"}
    found: set[Path] = set()

    # 1) Scan the report directory recursively for images/pcaps
    for ext in img_exts:
        for p in reports_dir.rglob(f"*{ext}"):
            _add_img(p, found)

    # 2) Include any images referenced by *_summary.json -> "plots"
    for js in reports_dir.rglob("*_summary.json"):
        try:
            data = json.loads(js.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        plots = data.get("plots", {})
        for _, v in plots.items():
            if not v:
                continue
            p = Path(v)
            if not p.exists():
                p = (js.parent / v)
            _add_img(p, found)

    # Categorize
    images: Dict[str, List[Path]] = {
        "step2": [], "step3": [], "step4": [], "step5": [], "overall": [], "general": []
    }
    for p in sorted(found):
        name = p.name.lower()
        if ("step5" in name) or ("overall_" in name and "step" not in name):
            images["step5" if "step5" in name else "overall"].append(p)
        elif ("step4" in name) or ("thermal" in name and "stress" in name):
            images["step4"].append(p)
        elif ("step3" in name) or ("stress" in name):
            images["step3"].append(p)
        elif ("step2" in name) or ("stability" in name):
            images["step2"].append(p)
        elif "overall" in name:
            images["overall"].append(p)
        else:
            images["general"].append(p)

    return eeprom_ascii, eeprom_raw, images


def _render_img_grid(images: List[Path], base_dir: Path) -> str:
    """
    Render a grid of visual artifacts. Image files are shown as thumbnails;
    non-image artifacts (e.g., .pcap/.pcapng) are rendered as clickable links.
    """
    if not images:
        return ""
    image_exts = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp"}
    rows = ["<div class='img-grid'>"]
    for p in images:
        try:
            rel = _rel_href(p, base_dir)
        except Exception:
            rel = p.name
        cap = html.escape(p.name)
        ext = p.suffix.lower()
        if ext in image_exts:
            # Clickable thumbnail
            rows.append(
                f"<figure><a href='{html.escape(rel)}' target='_blank'>"
                f"<img src='{html.escape(rel)}' alt='{cap}' /></a>"
                f"<figcaption>{cap}</figcaption></figure>"
            )
        else:
            # Non-image artifact (e.g., PCAP/PCAPNG) – render as link card
            rows.append(
                f"<figure>"
                f"<a href='{html.escape(rel)}' target='_blank' class='file-link'>📄 {cap}</a>"
                f"<figcaption>{cap}</figcaption>"
                f"</figure>"
            )
    rows.append("</div>")
    return "\n".join(rows)



def parse_log(log_path: Path) -> ReportModel:
    model = ReportModel(log_path=log_path)
    current_step: Optional[TestStep] = None

    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()

    if lines:
        m0 = TIMESTAMP_RE.match(lines[0])
        if m0:
            model.started_at = m0.group(1)

    for ln in lines:
        tm = TIMESTAMP_RE.match(ln)
        if not tm:
            # malformed; keep as-is
            ev = LogEvent(ts="", raw=ln, text=ln)
            (current_step.lines if current_step else model.other_events).append(ev)
            continue

        ts, rest = tm.group(1), tm.group(2)

        # Detect RESULT line
        rm = RESULT_RE.search(rest)
        if rm:
            model.overall = rm.group(1).upper()
            model.finished_at = ts
            ev = LogEvent(ts=ts, raw=ln, tag="RESULT", text=model.overall)
            (current_step.lines if current_step else model.other_events).append(ev)
            continue

        # Detect a step header like: [STEP 3.2/3.3] Change IP ...
        sm = STEP_START_RE.match(rest)
        if sm:
            # Close previous step (if any)
            if current_step:
                current_step.finished_at = ts
                current_step.close_with_status()
                model.steps.append(current_step)
                current_step = None
            step_name = sm.group(1)
            desc = sm.group(2)
            current_step = TestStep(name=f"{step_name} {desc}".strip(), started_at=ts)
            ev = LogEvent(ts=ts, raw=ln, tag=step_name, text=desc)
            current_step.lines.append(ev)
            continue

        # Otherwise parse as [LEVEL] text  OR plain text
        lv = LEVEL_TAG_RE.match(rest)
        if lv:
            tag = lv.group(1).upper()
            text = lv.group(2)
        else:
            tag = None
            text = rest

        ev = LogEvent(ts=ts, raw=ln, tag=tag, text=text)

        # Extract session ID from lines like: [INFO] Test Session ID: abc123
        if tag == "INFO" and not model.session_id:
            sid_m = re.match(r"Test Session ID:\s*(\S+)", text)
            if sid_m:
                model.session_id = sid_m.group(1)

        if current_step:
            current_step.lines.append(ev)
        else:
            model.other_events.append(ev)

    # Close last step
    if current_step:
        current_step.finished_at = model.finished_at or (current_step.lines[-1].ts if current_step.lines else None)
        current_step.close_with_status()
        model.steps.append(current_step)

    # If overall unknown, infer: FAIL if any step FAIL, else PASS if any PASS present
    if model.overall == "UNKNOWN":
        if any(s.status == "FAIL" for s in model.steps):
            model.overall = "FAIL"
        elif any(s.status == "PASS" for s in model.steps):
            model.overall = "PASS"

    # Environment meta
    model.meta = {
        "hostname": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()} ({platform.version()})",
        "python": sys.version.replace("\n", " "),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "log_file": str(log_path),
    }
    return model


# --------------------------------- Rendering -----------------------------------

def _color_class(status: str) -> str:
    s = status.upper()
    if s == "PASS":
        return "pass"
    if s == "FAIL":
        return "fail"
    return "unknown"

def _extract_step_tag(step: TestStep) -> str:
    """
    Return the raw step tag (e.g., 'STEP 3.2/3.3', 'PRE-STEP 1', 'TEARDOWN 1.1')
    from the first line if present, otherwise fall back to the name.
    """
    if step.lines and step.lines[0].tag:
        tag = step.lines[0].tag
        if tag.startswith(("STEP", "PRE-STEP", "POST-STEP", "TEARDOWN")):
            return tag
    return step.name

def _parse_step_number_parts(step_tag: str) -> Tuple[str, bool, str]:
    """
    From a tag like 'STEP 3', 'STEP 3.2', 'PRE-STEP 1', 'POST-STEP 2', 'TEARDOWN 1.1' extract:
      - base step index as string WITH prefix (e.g., 'STEP 3', 'PRE-STEP 1', 'TEARDOWN 1.1')
      - is_substep: True if any dot exists AND it's a regular STEP (not PRE/POST/TEARDOWN)
      - raw numeric token (e.g., '3', '3.2', '1.1')

    Special handling:
      - PRE-STEP, POST-STEP, and TEARDOWN steps are NEVER treated as substeps
      - They always display as separate top-level items in the report
    """
    # Match any of: STEP, PRE-STEP, POST-STEP, TEARDOWN followed by number
    m = re.search(r"((?:PRE-STEP|POST-STEP|TEARDOWN|STEP)\s+[0-9][0-9]*(?:[./][0-9][0-9]*(?:\.[0-9]+)?)?(?:/[0-9][0-9]*(?:\.[0-9]+)?)*)", step_tag)
    if m:
        full_token = m.group(1)  # e.g., "STEP 3.2", "PRE-STEP 1", "TEARDOWN 1.1"

        # Extract just the numeric part
        num_m = re.search(r"([0-9][0-9]*(?:[./][0-9][0-9]*(?:\.[0-9]+)?)?(?:/[0-9][0-9]*(?:\.[0-9]+)?)*)", full_token)
        token = num_m.group(1) if num_m else ""

        # For PRE-STEP, POST-STEP, and TEARDOWN, use the full tag as base (never group)
        if full_token.startswith(("PRE-STEP", "POST-STEP", "TEARDOWN")):
            # Return full tag as base so each appears as a separate top-level item
            return full_token, False, token  # is_sub=False to prevent grouping

        # For regular STEP, use standard grouping behavior
        base_num = token.split("/")[0].split(".")[0] if token else ""
        is_sub = "." in token
        base = f"STEP {base_num}" if base_num else full_token
        return base, is_sub, token

    return "", False, ""

def _escape_log_line(raw: str) -> str:
    """HTML-escape a log line and wrap known tags in colored spans."""
    escaped = html.escape(raw)
    # Colorize [PASS], [FAIL], [INFO], [WARN], [ERROR], [DEBUG], [SKIP] tags
    escaped = re.sub(
        r"\[(PASS)\]",
        r"<span class='log-pass'>[\1]</span>",
        escaped,
    )
    escaped = re.sub(
        r"\[(FAIL)\]",
        r"<span class='log-fail'>[\1]</span>",
        escaped,
    )
    escaped = re.sub(
        r"\[(ERROR)\]",
        r"<span class='log-fail'>[\1]</span>",
        escaped,
    )
    escaped = re.sub(
        r"\[(WARN)\]",
        r"<span class='log-warn'>[\1]</span>",
        escaped,
    )
    escaped = re.sub(
        r"\[(INFO)\]",
        r"<span class='log-info'>[\1]</span>",
        escaped,
    )
    escaped = re.sub(
        r"\[(DEBUG)\]",
        r"<span class='log-debug'>[\1]</span>",
        escaped,
    )
    escaped = re.sub(
        r"\[(SKIP)\]",
        r"<span class='log-skip'>[\1]</span>",
        escaped,
    )
    # Dim timestamps
    escaped = re.sub(
        r"^(\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\])",
        r"<span class='log-ts'>\1</span>",
        escaped,
    )
    # Highlight RESULT lines
    escaped = re.sub(
        r"(=+ RESULT: (?:PASS|FAIL) =+)",
        r"<span class='log-result'>\1</span>",
        escaped,
    )
    return escaped


def render_html(model: "ReportModel", out_html: Path) -> None:
    # ---- Build groups: only display STEPS; nest SUBSTEPS as dropdowns ----
    # Preserve encounter order
    groups_order: List[str] = []
    groups: Dict[str, Dict[str, Any]] = {}

    for s in model.steps:
        tag = _extract_step_tag(s)
        base, is_sub, token = _parse_step_number_parts(tag)
        if base not in groups:
            groups[base] = {"title": "", "top": None, "subs": [], "status": "UNKNOWN"}
            groups_order.append(base)

        if is_sub:
            groups[base]["subs"].append(s)
            if not groups[base]["title"]:
                desc = s.name
                groups[base]["title"] = re.sub(r"STEP\s+[^\]]+", f"STEP {base}", desc, count=1)
        else:
            groups[base]["top"] = s
            groups[base]["title"] = s.name

    # Compute grouped status
    def _combine_status(vals: List[str]) -> str:
        for v in vals:
            v = (v or "UNKNOWN").upper()
            if v == "FAIL":
                return "FAIL"
        for v in vals:
            v = (v or "UNKNOWN").upper()
            if v == "PASS":
                return "PASS"
        return "UNKNOWN"

    for base in groups_order:
        g = groups[base]
        statuses = []
        if g["top"]:
            statuses.append(g["top"].status)
        statuses.extend([x.status for x in g["subs"]])
        g["status"] = _combine_status(statuses)
        if not g["title"]:
            g["title"] = f"STEP {base}"

    # Stats based on groups (not raw steps)
    total = len(groups_order)
    passed = sum(1 for b in groups_order if groups[b]["status"] == "PASS")
    failed = sum(1 for b in groups_order if groups[b]["status"] == "FAIL")
    unknown = total - passed - failed
    pass_pct = round(passed / total * 100) if total else 0
    fail_pct = round(failed / total * 100) if total else 0
    unknown_pct = 100 - pass_pct - fail_pct if total else 0

    reports_dir = out_html.parent
    eeprom_ascii, eeprom_raw, images = _discover_images_and_artifacts(reports_dir, out_html)

    # Derive test name from log file name (strip _results.log / .log)
    test_name = model.log_path.stem
    for suffix in ("_results", "_result", "_report"):
        test_name = test_name.replace(suffix, "")
    test_name = test_name.replace("_", " ").title()

    css = """
    *,*::before,*::after{box-sizing:border-box}
    :root{
      --bg-primary:#f8f9fc;--bg-secondary:#ffffff;--bg-card:#ffffff;--bg-card-hover:#f3f4f8;
      --bg-surface:#e8eaef;--border:#d4d8e0;--border-light:#c4c8d0;
      --text-primary:#1a1d26;--text-secondary:#4b5264;--text-muted:#7a8194;
      --accent:#4361ee;--accent-dim:#8da0f5;
      --green:#059669;--green-bg:rgba(5,150,105,0.08);--green-border:rgba(5,150,105,0.25);
      --red:#dc2626;--red-bg:rgba(220,38,38,0.06);--red-border:rgba(220,38,38,0.22);
      --amber:#d97706;--amber-bg:rgba(217,119,6,0.06);--amber-border:rgba(217,119,6,0.22);
      --blue:#2563eb;--blue-bg:rgba(37,99,235,0.05);
      --purple:#7c3aed;--purple-bg:rgba(124,58,237,0.06);--purple-border:rgba(124,58,237,0.2);
      --gray:#6b7280;
      --radius:10px;--radius-lg:14px;
      --font-mono:'SF Mono','Cascadia Code','Fira Code',Consolas,monospace;
    }
    body{font-family:'Inter',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
         background:var(--bg-primary);color:var(--text-primary);margin:0;line-height:1.6;
         -webkit-font-smoothing:antialiased}

    /* ── Header ── */
    .report-header{background:var(--bg-secondary);border-bottom:1px solid var(--border);padding:0}
    .header-inner{max-width:1200px;margin:0 auto;padding:28px 32px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:20px}
    .header-left{display:flex;flex-direction:column;gap:6px}
    .header-left h1{margin:0;font-size:22px;font-weight:700;letter-spacing:-0.3px;color:var(--text-primary)}
    .header-subtitle{font-size:13px;color:var(--text-secondary);display:flex;gap:16px;flex-wrap:wrap;align-items:center}
    .header-subtitle span{display:inline-flex;align-items:center;gap:5px}
    .header-subtitle .dot{width:3px;height:3px;border-radius:50%;background:var(--text-muted);display:inline-block}
    .overall-badge{display:flex;align-items:center;gap:10px;padding:12px 22px;border-radius:var(--radius-lg);font-size:15px;font-weight:700;letter-spacing:0.5px;text-transform:uppercase}
    .overall-badge.pass{background:var(--green-bg);border:1.5px solid var(--green-border);color:var(--green)}
    .overall-badge.fail{background:var(--red-bg);border:1.5px solid var(--red-border);color:var(--red)}
    .overall-badge.unknown{background:var(--amber-bg);border:1.5px solid var(--amber-border);color:var(--amber)}
    .overall-badge .badge-icon{font-size:20px}

    /* ── Main layout ── */
    main{max-width:1200px;margin:0 auto;padding:24px 32px 48px}
    section{margin-bottom:28px}
    section>h3{font-size:13px;text-transform:uppercase;letter-spacing:1.2px;color:var(--text-muted);margin:0 0 14px;font-weight:600}

    /* ── Dashboard cards ── */
    .dashboard{display:flex;flex-direction:column;gap:20px;margin-bottom:28px}

    .stats-card{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-lg);padding:24px;display:flex;flex-direction:column;gap:18px}
    .stat-row{display:flex;gap:12px;flex-wrap:wrap}
    .stat-item{flex:1;min-width:100px;padding:14px 16px;border-radius:var(--radius);background:var(--bg-secondary);border:1px solid var(--border);text-align:center}
    .stat-item .stat-value{font-size:28px;font-weight:700;line-height:1;margin-bottom:4px;font-family:var(--font-mono)}
    .stat-item .stat-label{font-size:11px;text-transform:uppercase;letter-spacing:0.8px;color:var(--text-secondary)}
    .stat-item.pass .stat-value{color:var(--green)}
    .stat-item.fail .stat-value{color:var(--red)}
    .stat-item.unknown .stat-value{color:var(--amber)}
    .stat-item.total .stat-value{color:var(--accent)}

    /* Progress bar */
    .progress-bar{height:10px;border-radius:6px;background:var(--bg-surface);overflow:hidden;display:flex}
    .progress-bar .seg-pass{background:var(--green);transition:width 0.5s}
    .progress-bar .seg-fail{background:var(--red);transition:width 0.5s}
    .progress-bar .seg-unknown{background:var(--amber);transition:width 0.5s}
    .progress-legend{display:flex;gap:16px;font-size:12px;color:var(--text-secondary);margin-top:6px}
    .progress-legend span{display:inline-flex;align-items:center;gap:5px}
    .progress-legend .swatch{width:10px;height:10px;border-radius:3px;display:inline-block}

    /* Environment card */
    .env-card{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-lg);padding:24px}
    .env-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
    .env-item{padding:10px 14px;border-radius:var(--radius);background:var(--bg-secondary);border:1px solid var(--border)}
    .env-item .env-label{font-size:10px;text-transform:uppercase;letter-spacing:0.8px;color:var(--text-muted);margin-bottom:3px}
    .env-item .env-value{font-size:13px;color:var(--text-primary);word-break:break-all;font-family:var(--font-mono)}

    /* ── Step cards ── */
    details.step-card{border:1px solid var(--border);border-radius:var(--radius-lg);margin-bottom:10px;overflow:hidden;background:var(--bg-card);transition:border-color 0.2s}
    details.step-card[open]{border-color:var(--border-light)}
    details.step-card>summary{padding:14px 18px;background:var(--bg-card);cursor:pointer;font-weight:600;font-size:14px;list-style:none;transition:background 0.15s}
    details.step-card>summary::-webkit-details-marker{display:none}
    details.step-card>summary::before{content:'';display:inline-block;width:6px;height:6px;border-right:2px solid var(--text-muted);border-bottom:2px solid var(--text-muted);transform:rotate(-45deg);margin-right:12px;transition:transform 0.2s;flex-shrink:0}
    details.step-card[open]>summary::before{transform:rotate(45deg)}
    details.step-card>summary:hover{background:var(--bg-card-hover)}
    .step-header{display:flex;justify-content:space-between;align-items:center;width:100%}
    .step-header .step-name{display:flex;align-items:center;gap:8px;min-width:0}
    .step-header .step-name .step-num{font-family:var(--font-mono);font-size:12px;color:var(--text-muted);white-space:nowrap}
    .step-header .step-right{display:flex;align-items:center;gap:10px;flex-shrink:0}
    .step-header .step-time{font-size:11px;color:var(--text-muted);font-family:var(--font-mono)}
    .badge{padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600;letter-spacing:0.4px;text-transform:uppercase}
    .badge.pass{background:var(--green-bg);border:1px solid var(--green-border);color:var(--green)}
    .badge.fail{background:var(--red-bg);border:1px solid var(--red-border);color:var(--red)}
    .badge.unknown{background:var(--amber-bg);border:1px solid var(--amber-border);color:var(--amber)}
    .badge.detail{background:var(--blue-bg);border:1px solid var(--border);color:var(--blue)}

    /* Step type left-border accents */
    details.step-card.pre-step{border-left:3px solid var(--purple)}
    details.step-card.post-step{border-left:3px solid var(--green)}
    details.step-card.teardown{border-left:3px solid var(--amber)}

    .step-content{padding:16px 18px;background:var(--bg-secondary);border-top:1px solid var(--border)}
    .step-meta{display:flex;gap:24px;font-size:12px;color:var(--text-secondary);margin-bottom:14px;flex-wrap:wrap}
    .step-meta span{display:inline-flex;align-items:center;gap:5px}

    /* ── Substeps ── */
    .substeps{margin-top:14px}
    .substeps h4{font-size:12px;text-transform:uppercase;letter-spacing:0.8px;color:var(--text-muted);margin:0 0 10px;font-weight:600}
    .substeps details.step-card{background:var(--bg-primary);border-color:var(--border)}
    .substeps details.step-card>summary{background:var(--bg-primary);font-size:13px;padding:10px 14px}
    .substeps details.step-card>summary:hover{background:var(--bg-secondary)}
    .substeps .step-content{background:var(--bg-card)}

    /* ── Log output ── */
    .log-output{background:var(--bg-primary);border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px;overflow-x:auto;
                font-family:var(--font-mono);font-size:12px;line-height:1.7;color:var(--text-secondary);margin-top:10px;max-height:600px;overflow-y:auto}
    .log-output .log-ts{color:var(--text-muted)}
    .log-output .log-pass{color:var(--green);font-weight:600}
    .log-output .log-fail{color:var(--red);font-weight:600}
    .log-output .log-warn{color:var(--amber);font-weight:600}
    .log-output .log-info{color:var(--blue)}
    .log-output .log-debug{color:var(--text-muted)}
    .log-output .log-skip{color:var(--purple)}
    .log-output .log-result{color:var(--accent);font-weight:700}

    /* ── Tables (timing) ── */
    table{width:100%;border-collapse:collapse;margin:0}
    th,td{padding:8px 12px;text-align:left;font-size:13px}
    th{color:var(--text-muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:0.6px;border-bottom:1px solid var(--border)}
    td{color:var(--text-primary);border-bottom:1px solid var(--border);font-family:var(--font-mono);font-size:12px}

    /* ── Image grid ── */
    .img-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;margin-top:12px}
    .img-grid figure{margin:0;padding:10px;background:var(--bg-secondary);border:1px solid var(--border);border-radius:var(--radius);transition:border-color 0.2s}
    .img-grid figure:hover{border-color:var(--border-light)}
    .img-grid img{max-width:100%;height:auto;display:block;border-radius:6px}
    .img-grid figcaption{font-size:11px;color:var(--text-muted);margin-top:8px;font-family:var(--font-mono)}

    /* ── Links & lists ── */
    a{color:var(--accent);text-decoration:none;transition:color 0.15s}
    a:hover{color:#8aa4ff;text-decoration:underline}
    ul{padding-left:20px}
    li{margin-bottom:6px;font-size:13px}
    .file-link{display:inline-flex;align-items:center;gap:6px;padding:8px 14px;background:var(--bg-secondary);border:1px solid var(--border);border-radius:var(--radius);font-size:13px;transition:background 0.15s}
    .file-link:hover{background:var(--bg-surface);text-decoration:none}

    /* ── Footer ── */
    .report-footer{text-align:center;padding:20px 32px;font-size:11px;color:var(--text-muted);border-top:1px solid var(--border);margin-top:20px}

    /* ── Dark mode ── */
    body.dark{
      --bg-primary:#0c0e12;--bg-secondary:#12151b;--bg-card:#161a22;--bg-card-hover:#1a1f28;
      --bg-surface:#1e2330;--border:#252a35;--border-light:#2f3542;
      --text-primary:#e8ecf4;--text-secondary:#8b95a8;--text-muted:#5e667a;
      --accent:#6c8aff;--accent-dim:#3d4f8a;
      --green:#34d399;--green-bg:rgba(52,211,153,0.08);--green-border:rgba(52,211,153,0.25);
      --red:#f87171;--red-bg:rgba(248,113,113,0.08);--red-border:rgba(248,113,113,0.25);
      --amber:#fbbf24;--amber-bg:rgba(251,191,36,0.08);--amber-border:rgba(251,191,36,0.25);
      --blue:#60a5fa;--blue-bg:rgba(96,165,250,0.06);
      --purple:#a78bfa;--purple-bg:rgba(167,139,250,0.08);--purple-border:rgba(167,139,250,0.25);
      --gray:#6b7280;
    }
    body.dark .log-output .log-debug{color:#5e667a}

    /* ── Theme toggle ── */
    .theme-toggle{background:var(--bg-surface);border:1px solid var(--border);border-radius:8px;padding:7px 10px;cursor:pointer;color:var(--text-secondary);font-size:16px;line-height:1;display:flex;align-items:center;gap:6px;transition:background 0.15s,border-color 0.15s}
    .theme-toggle:hover{background:var(--bg-card-hover);border-color:var(--border-light)}
    .theme-toggle .toggle-label{font-size:11px;text-transform:uppercase;letter-spacing:0.5px}
    .header-right{display:flex;align-items:center;gap:14px}

    /* ── Print styles ── */
    @media print{
      .theme-toggle{display:none}
      body{-webkit-print-color-adjust:exact;print-color-adjust:exact}
      .log-output{max-height:none}
      details.step-card{break-inside:avoid}
    }
    """

    def _color_class_local(status: str) -> str:
        s = (status or "").upper()
        if s == "PASS":
            return "pass"
        if s == "FAIL":
            return "fail"
        return "unknown"

    def _step_type_class(title: str) -> str:
        title_upper = title.upper()
        if "PRE-STEP" in title_upper:
            return "pre-step"
        elif "POST-STEP" in title_upper:
            return "post-step"
        elif "TEARDOWN" in title_upper:
            return "teardown"
        return ""

    def _badge_icon(status: str) -> str:
        s = (status or "").upper()
        if s == "PASS":
            return "&#10003;"  # checkmark
        if s == "FAIL":
            return "&#10007;"  # X mark
        return "&#8226;"  # bullet

    html_lines: List[str] = []
    html_lines.append("<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>")
    html_lines.append("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    html_lines.append(f"<title>{html.escape(test_name)} &mdash; {html.escape(model.overall)}</title>")
    html_lines.append(f"<style>{css}</style></head><body>")

    # ── Header ──
    html_lines.append("<div class='report-header'><div class='header-inner'>")
    html_lines.append("<div class='header-left'>")
    html_lines.append(f"<h1>{html.escape(test_name)}</h1>")
    html_lines.append("<div class='header-subtitle'>")
    if model.session_id:
        html_lines.append(f"<span>Session <code>{html.escape(model.session_id)}</code></span><span class='dot'></span>")
    if model.started_at:
        html_lines.append(f"<span>{html.escape(model.started_at)}</span>")
    if model.started_at and model.finished_at:
        html_lines.append(f"<span class='dot'></span><span>{html.escape(model.finished_at)}</span>")
    html_lines.append("</div></div>")
    html_lines.append("<div class='header-right'>")
    overall_cls = _color_class_local(model.overall)
    html_lines.append(f"<div class='overall-badge {overall_cls}'><span class='badge-icon'>{_badge_icon(model.overall)}</span>{html.escape(model.overall)}</div>")
    html_lines.append("<button class='theme-toggle' onclick='toggleTheme()' title='Toggle light/dark mode'>")
    html_lines.append("<span class='toggle-icon'>&#9788;</span><span class='toggle-label'>Theme</span></button>")
    html_lines.append("</div>")
    html_lines.append("</div></div>")

    # ── Main ──
    html_lines.append("<main>")

    # ── Dashboard: stats + environment side by side ──
    html_lines.append("<div class='dashboard'>")

    # Stats card
    html_lines.append("<div class='stats-card'>")
    html_lines.append("<div class='stat-row'>")
    html_lines.append(f"<div class='stat-item pass'><div class='stat-value'>{passed}</div><div class='stat-label'>Passed</div></div>")
    html_lines.append(f"<div class='stat-item fail'><div class='stat-value'>{failed}</div><div class='stat-label'>Failed</div></div>")
    html_lines.append(f"<div class='stat-item unknown'><div class='stat-value'>{unknown}</div><div class='stat-label'>Unknown</div></div>")
    html_lines.append(f"<div class='stat-item total'><div class='stat-value'>{total}</div><div class='stat-label'>Total</div></div>")
    html_lines.append("</div>")
    # Progress bar
    html_lines.append("<div class='progress-bar'>")
    html_lines.append(f"<div class='seg-pass' style='width:{pass_pct}%'></div>")
    html_lines.append(f"<div class='seg-fail' style='width:{fail_pct}%'></div>")
    html_lines.append(f"<div class='seg-unknown' style='width:{unknown_pct}%'></div>")
    html_lines.append("</div>")
    html_lines.append("<div class='progress-legend'>")
    html_lines.append(f"<span><span class='swatch' style='background:var(--green)'></span>Pass {pass_pct}%</span>")
    html_lines.append(f"<span><span class='swatch' style='background:var(--red)'></span>Fail {fail_pct}%</span>")
    if unknown:
        html_lines.append(f"<span><span class='swatch' style='background:var(--amber)'></span>Unknown {unknown_pct}%</span>")
    html_lines.append("</div>")
    html_lines.append("</div>")

    # Environment card
    html_lines.append("<div class='env-card'>")
    html_lines.append("<div class='env-grid'>")
    env_labels = {
        "hostname": "Host",
        "os": "Operating System",
        "python": "Python",
        "generated_at": "Report Generated",
        "log_file": "Log File",
    }
    if model.session_id:
        html_lines.append(f"<div class='env-item'><div class='env-label'>Session ID</div><div class='env-value'>{html.escape(model.session_id)}</div></div>")
    for k, label in env_labels.items():
        if k in model.meta:
            html_lines.append(f"<div class='env-item'><div class='env-label'>{html.escape(label)}</div><div class='env-value'>{html.escape(str(model.meta[k]))}</div></div>")
    html_lines.append("</div></div>")
    html_lines.append("</div>")  # .dashboard

    # ── Steps ──
    html_lines.append("<section>")
    html_lines.append("<h3>Test Steps</h3>")

    def _images_for_base(base_idx: str) -> List[Path]:
        try:
            n = int(base_idx)
        except Exception:
            n = None
        if n == 2:
            return images.get("step2", [])
        if n == 3:
            return images.get("step3", [])
        if n == 4:
            return images.get("step4", [])
        if n == 5:
            return images.get("step5", []) or images.get("overall", [])
        return []

    for base in groups_order:
        g = groups[base]
        st_cls = _color_class_local(g["status"])
        title = html.escape(g["title"])
        step_type_cls = _step_type_class(g["title"])
        cls_parts = ["step-card"]
        if step_type_cls:
            cls_parts.append(step_type_cls)
        cls_attr = f" class='{' '.join(cls_parts)}'"
        open_attr = " open" if g["status"] != "PASS" else ""
        html_lines.append(f"<details{cls_attr}{open_attr}>")
        html_lines.append("<summary>")
        html_lines.append(f"<div class='step-header'><div class='step-name'>{title}</div>")
        html_lines.append(f"<div class='step-right'>")

        # Times
        started_candidates = []
        finished_candidates = []
        for unit in ([g["top"]] if g["top"] else []) + g["subs"]:
            if unit and unit.started_at:
                started_candidates.append(unit.started_at)
            if unit and unit.finished_at:
                finished_candidates.append(unit.finished_at)
        agg_start = started_candidates[0] if started_candidates else ""
        agg_finish = finished_candidates[-1] if finished_candidates else ""
        if agg_start:
            # Show just the time portion
            time_part = agg_start.split(" ")[-1] if " " in agg_start else agg_start
            html_lines.append(f"<span class='step-time'>{html.escape(time_part)}</span>")

        html_lines.append(f"<span class='badge {st_cls}'>{html.escape(g['status'])}</span>")
        html_lines.append("</div></div>")
        html_lines.append("</summary>")
        html_lines.append("<div class='step-content'>")

        # Step meta line
        html_lines.append("<div class='step-meta'>")
        if agg_start:
            html_lines.append(f"<span>Started: {html.escape(agg_start)}</span>")
        if agg_finish:
            html_lines.append(f"<span>Finished: {html.escape(agg_finish)}</span>")
        sub_count = len(g["subs"])
        if sub_count:
            html_lines.append(f"<span>{sub_count} substep{'s' if sub_count != 1 else ''}</span>")
        html_lines.append("</div>")

        # Plots attached by base index
        step_imgs = _images_for_base(base)
        if step_imgs:
            html_lines.append(_render_img_grid(step_imgs, out_html.parent))

        # Substeps dropdowns
        if g["subs"]:
            html_lines.append("<div class='substeps'>")
            html_lines.append("<h4>Substeps</h4>")
            for sub in g["subs"]:
                sub_title = html.escape(sub.name)
                sub_cls = _color_class_local(sub.status)
                sub_time = sub.started_at.split(" ")[-1] if sub.started_at and " " in sub.started_at else ""
                html_lines.append("<details class='step-card'>")
                html_lines.append("<summary>")
                html_lines.append(f"<div class='step-header'><div class='step-name'>{sub_title}</div>")
                html_lines.append(f"<div class='step-right'>")
                if sub_time:
                    html_lines.append(f"<span class='step-time'>{html.escape(sub_time)}</span>")
                html_lines.append(f"<span class='badge {sub_cls}'>{html.escape(sub.status)}</span>")
                html_lines.append("</div></div>")
                html_lines.append("</summary>")
                html_lines.append("<div class='step-content'>")
                html_lines.append("<div class='step-meta'>")
                if sub.started_at:
                    html_lines.append(f"<span>Started: {html.escape(sub.started_at)}</span>")
                if sub.finished_at:
                    html_lines.append(f"<span>Finished: {html.escape(sub.finished_at)}</span>")
                html_lines.append("</div>")
                # Log with color-coded lines
                html_lines.append("<div class='log-output'>")
                for ev in sub.lines:
                    html_lines.append(_escape_log_line(ev.raw) + "<br>")
                html_lines.append("</div>")
                html_lines.append("</div>")
                html_lines.append("</details>")
            html_lines.append("</div>")

        # Top-level step log
        if g["top"] and len(g["top"].lines) > 1:
            html_lines.append("<details class='step-card'>")
            html_lines.append("<summary><div class='step-header'><div class='step-name'>Step Log</div>")
            html_lines.append("<div class='step-right'><span class='badge detail'>DETAIL</span></div></div></summary>")
            html_lines.append("<div class='step-content'>")
            html_lines.append("<div class='log-output'>")
            for ev in g["top"].lines:
                html_lines.append(_escape_log_line(ev.raw) + "<br>")
            html_lines.append("</div>")
            html_lines.append("</div>")
            html_lines.append("</details>")

        html_lines.append("</div>")
        html_lines.append("</details>")
    html_lines.append("</section>")

    # Overall images
    remaining_overall = images.get("overall", [])
    if remaining_overall:
        html_lines.append("<section>")
        html_lines.append("<h3>Overall Plots</h3>")
        html_lines.append(_render_img_grid(remaining_overall, out_html.parent))
        html_lines.append("</section>")

    # General images
    general_imgs = images.get("general", [])
    if general_imgs:
        html_lines.append("<section>")
        html_lines.append("<h3>Images &amp; Artifacts</h3>")
        html_lines.append(_render_img_grid(general_imgs, out_html.parent))
        html_lines.append("</section>")

    # EEPROM artifacts
    if eeprom_ascii or eeprom_raw:
        html_lines.append("<section>")
        html_lines.append("<h3>EEPROM Artifacts</h3>")
        html_lines.append("<ul>")
        if eeprom_ascii:
            rel = _rel_href(eeprom_ascii, out_html.parent)
            html_lines.append(f"<li><a href='{html.escape(rel)}' target='_blank'>ASCII dump</a></li>")
        if eeprom_raw:
            rel = _rel_href(eeprom_raw, out_html.parent)
            html_lines.append(f"<li><a href='{html.escape(rel)}' target='_blank'>Hex dump</a></li>")
        html_lines.append("</ul>")
        html_lines.append("</section>")

    # PCAP artifacts
    pcap_files = images.get("pcap", [])
    if pcap_files:
        html_lines.append("<section>")
        html_lines.append("<h3>PCAP Artifacts</h3>")
        html_lines.append("<ul>")
        for p in pcap_files:
            rel = _rel_href(p, out_html.parent)
            html_lines.append(
                f"<li><a href='{html.escape(rel)}' target='_blank'>{p.name}</a></li>"
            )
        html_lines.append("</ul>")
        html_lines.append("</section>")

    # ── Footer ──
    generated = model.meta.get("generated_at", "")
    html_lines.append(f"<div class='report-footer'>Generated by UTFW Report Engine &mdash; {html.escape(generated)}</div>")

    html_lines.append("</main>")
    html_lines.append("<script>")
    html_lines.append("function toggleTheme(){")
    html_lines.append("  document.body.classList.toggle('dark');")
    html_lines.append("  var icon=document.querySelector('.toggle-icon');")
    html_lines.append("  var isDark=document.body.classList.contains('dark');")
    html_lines.append("  icon.innerHTML=isDark?'\u2606':'\u263E';")
    html_lines.append("  try{localStorage.setItem('utfw-theme',isDark?'dark':'light')}catch(e){}")
    html_lines.append("}")
    html_lines.append("(function(){")
    html_lines.append("  try{if(localStorage.getItem('utfw-theme')==='dark'){")
    html_lines.append("    document.body.classList.add('dark');")
    html_lines.append("    var i=document.querySelector('.toggle-icon');if(i)i.innerHTML='\u2606';")
    html_lines.append("  }}catch(e){}")
    html_lines.append("})();")
    html_lines.append("</script>")
    html_lines.append("</body></html>")

    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text("\n".join(html_lines), encoding="utf-8")
 
# ------------------------------- JUnit XML (opt) -------------------------------

def render_junit_xml(model: ReportModel, out_xml: Path) -> None:
    """
    Write a minimal JUnit XML so CI systems can ingest the step results.

    Negative tests:
    """
    total = len(model.steps)
    failures = sum(1 for s in model.steps if s.status == "FAIL")
    skipped = 0
    time_placeholder = "0.0"

    # Escape for XML
    def x(s: str) -> str:
        return (s.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;")
                 .replace('"', "&quot;")
                 .replace("'", "&apos;"))

    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')

    # Build testsuite element with optional session_id property
    testsuite_attrs = f'name="ENERGIS Functional Test" tests="{total}" failures="{failures}" skipped="{skipped}" time="{time_placeholder}"'
    if model.session_id:
        testsuite_attrs += f' session_id="{x(model.session_id)}"'
    lines.append(f'<testsuite {testsuite_attrs}>')

    for idx, s in enumerate(model.steps, 1):
        case_name = s.name or f"Step {idx}"
        lines.append(f'  <testcase classname="UTFW" name="{x(case_name)}" time="{time_placeholder}">')

        if s.status == "FAIL":
            msg = "Step failed"
            for ev in reversed(s.lines):
                if ev.tag == "FAIL":
                    msg = ev.text or ev.raw
                    break
            lines.append(f'    <failure message="{x(msg)}"/>')

        lines.append('  </testcase>')

    lines.append("</testsuite>")

    out_xml.parent.mkdir(parents=True, exist_ok=True)
    out_xml.write_text("\n".join(lines), encoding="utf-8")


# ------------------------------------ Main -------------------------------------

def main():
    ap = argparse.ArgumentParser(description="ENERGIS UART Test Report Generator")
    ap.add_argument("--log", default=str(Path("_SoftwareTest/Reports/tc_serial_results.log")),
                    help="Path to tc_serial results log")
    ap.add_argument("--out-html", default=str(Path("_SoftwareTest/Reports/tc_serial_report.html")),
                    help="Output HTML report path")
    ap.add_argument("--junit", default=None,
                    help="Optional JUnit XML output path (e.g., _SoftwareTest/Reports/tc_serial_report.xml)")
    args = ap.parse_args()

    log_path = Path(args.log)
    if not log_path.exists():
        print(f"ERROR: Log file not found: {log_path}", file=sys.stderr)
        sys.exit(2)

    model = parse_log(log_path)

    out_html = Path(args.out_html)
    render_html(model, out_html)
    print(f"[OK] HTML report written to: {out_html}")

    if args.junit:
        out_xml = Path(args.junit)
        render_junit_xml(model, out_xml)
        print(f"[OK] JUnit XML written to: {out_xml}")

if __name__ == "__main__":
    main()
