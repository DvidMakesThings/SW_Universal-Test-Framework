# generate_test_report.py
# -*- coding: utf-8 -*-
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
STEP_START_RE = re.compile(r"^\[(STEP\s+[^\]]+)\]\s*(.*)$")
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

    def close_with_status(self):
        # Determine status from contained events
        st = "PASS"
        for ev in self.lines:
            if ev.tag == "FAIL":
                st = "FAIL"
                break
        self.status = st


@dataclass
class ReportModel:
    log_path: Path
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    steps: List[TestStep] = field(default_factory=list)
    other_events: List[LogEvent] = field(default_factory=list)
    overall: str = "UNKNOWN"
    meta: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------- Parsing ------------------------------------

def _discover_images_and_artifacts(reports_dir: Path, out_html: Path) -> Tuple[Optional[Path], Optional[Path], Dict[str, List[Path]]]:
    """
    Find EEPROM logs and collect images to embed in the HTML.

    Returns:
        (eeprom_ascii, eeprom_raw, images) where images is a dict with keys:
            "step2", "step3", "step4", "step5", "overall", "general"
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

    img_exts = {".png", ".jpg", ".jpeg", ".svg"}
    found: set[Path] = set()

    # 1) Scan the report directory recursively for images
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
    if not images:
        return ""
    rows = ["<div class='img-grid'>"]
    for p in images:
        try:
            rel = os.path.relpath(str(p), str(base_dir))
        except Exception:
            rel = str(p)
        cap = html.escape(p.name)
        rows.append(
            f"<figure><img src='{html.escape(rel)}' alt='{cap}' /><figcaption>{cap}</figcaption></figure>"
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
    Return the raw [STEP ...] tag (e.g., 'STEP 3.2/3.3') from the first line if present,
    otherwise fall back to the name.
    """
    if step.lines and step.lines[0].tag and step.lines[0].tag.startswith("STEP"):
        return step.lines[0].tag
    return step.name

def _parse_step_number_parts(step_tag: str) -> Tuple[str, bool, str]:
    """
    From a tag like 'STEP 3', 'STEP 3.2', or 'STEP 3.2/3.3' extract:
      - base step index as string (e.g., '3')
      - is_substep: True if any dot exists after the base index
      - raw numeric token after 'STEP ' (e.g., '3', '3.2', '3.2/3.3')
    """
    m = re.search(r"STEP\s+([0-9][0-9]*(?:[./][0-9][0-9]*(?:\.[0-9]+)?)?(?:/[0-9][0-9]*(?:\.[0-9]+)?)*)", step_tag)
    token = m.group(1) if m else ""
    base = token.split("/")[0].split(".")[0] if token else ""
    is_sub = "." in token
    return base, is_sub, token

def render_html(model: "ReportModel", out_html: Path) -> None:
    # ---- Build groups: only display STEPS; nest SUBSTEPS as dropdowns ----
    # Preserve encounter order
    groups_order: List[str] = []
    groups: Dict[str, Dict[str, Any]] = {}
    # Each entry:
    # {
    #   "title": str,                  # derived from first top-level or substep
    #   "top": Optional[TestStep],     # the [STEP N] unit, if present
    #   "subs": List[TestStep],        # any [STEP N.x] units in order
    #   "status": "PASS"/"FAIL"/"UNKNOWN",
    # }

    for s in model.steps:
        tag = _extract_step_tag(s)
        base, is_sub, token = _parse_step_number_parts(tag)
        if base not in groups:
            groups[base] = {"title": "", "top": None, "subs": [], "status": "UNKNOWN"}
            groups_order.append(base)

        if is_sub:
            groups[base]["subs"].append(s)
            if not groups[base]["title"]:
                # Title from first substep: "STEP {base} – {desc...}"
                # Try to reuse the step name but normalize to base index
                desc = s.name
                groups[base]["title"] = re.sub(r"STEP\s+[^\]]+", f"STEP {base}", desc, count=1)
        else:
            groups[base]["top"] = s
            groups[base]["title"] = s.name

    # Compute grouped status
    def _combine_status(vals: List[str]) -> str:
        out = "UNKNOWN"
        seen_pass = False
        for v in vals:
            v = (v or "UNKNOWN").upper()
            if v == "FAIL":
                return "FAIL"
            if v == "PASS":
                seen_pass = True
        return "PASS" if seen_pass else out

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

    reports_dir = out_html.parent
    eeprom_ascii, eeprom_raw, images = _discover_images_and_artifacts(reports_dir, out_html)

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
    details{border:1px solid #2a2f37;border-radius:12px;margin-bottom:12px;overflow:hidden}
    summary{padding:12px 14px;background:#151a21;cursor:pointer;font-weight:600}
    .content{padding:12px 14px;background:#11161b}
    .step-title{display:flex;justify-content:space-between;align-items:center}
    .status{padding:3px 8px;border-radius:12px;border:1px solid #2a2f37;font-size:12px}
    .status.pass{border-color:#1e7f45;color:#d7ffe6;background:#0e2017}
    .status.fail{border-color:#a23b3b;color:#ffe1e1;background:#210e0e}
    .status.unknown{border-color:#6b7280;background:#1b2028}
    pre{background:#0b0f14;border:1px solid #2a2f37;border-radius:8px;padding:10px;overflow:auto}
    table{width:100%;border-collapse:collapse;margin-top:8px}
    th,td{border-bottom:1px solid #1f2530;padding:8px 6px;text-align:left;font-size:13px}
    th{color:#a6adbb;font-weight:600;background:#131820}
    .kv{display:grid;grid-template-columns:180px 1fr;gap:8px}
    a{color:#9ad0ff;text-decoration:none}
    a:hover{text-decoration:underline}
    .img-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;margin-top:10px}
    .img-grid figure{margin:0;padding:8px;background:#0b0f14;border:1px solid #2a2f37;border-radius:8px}
    .img-grid img{max-width:100%;height:auto;display:block;border-radius:6px}
    .img-grid figcaption{font-size:12px;color:#a6adbb;margin-top:6px}
    .substeps{margin-top:10px}
    .substeps details{margin-bottom:8px}
    """

    def _color_class_local(status: str) -> str:
        s = (status or "").upper()
        if s == "PASS":
            return "pass"
        if s == "FAIL":
            return "fail"
        return "unknown"

    html_lines: List[str] = []
    html_lines.append("<!DOCTYPE html><html><head><meta charset='utf-8'>")
    html_lines.append("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    html_lines.append(f"<title>ENERGIS Test Report - {html.escape(model.overall)}</title>")
    html_lines.append(f"<style>{css}</style></head><body>")

    # Header
    html_lines.append("<header>")
    html_lines.append("<h1>ENERGIS Test Report</h1>")
    html_lines.append("<div class='meta'>")
    html_lines.append(f"Overall: <b class='chip {_color_class_local(model.overall)}'>{html.escape(model.overall)}</b> &nbsp;")
    if model.started_at:
        html_lines.append(f"Started: {html.escape(model.started_at)} &nbsp;")
    if model.finished_at:
        html_lines.append(f"Finished: {html.escape(model.finished_at)} &nbsp;")
    html_lines.append("</div>")
    html_lines.append("</header>")

    # Summary chips (based on groups)
    html_lines.append("<main>")
    html_lines.append("<section class='summary'>")
    html_lines.append(f"<div class='chip pass'>Passed steps: {passed}</div>")
    html_lines.append(f"<div class='chip fail'>Failed steps: {failed}</div>")
    html_lines.append(f"<div class='chip unknown'>Unknown steps: {unknown}</div>")
    html_lines.append(f"<div class='chip'>Total steps: {total}</div>")
    html_lines.append("</section>")

    # Meta
    html_lines.append("<section>")
    html_lines.append("<h3>Environment</h3>")
    html_lines.append("<div class='kv'>")
    for k in ["hostname", "os", "python", "generated_at", "log_file"]:
        if k in model.meta:
            html_lines.append(f"<div>{html.escape(k.capitalize())}</div><div>{html.escape(str(model.meta[k]))}</div>")
    html_lines.append("</div>")
    html_lines.append("</section>")

    # Steps (groups) with nested substeps as dropdowns
    html_lines.append("<section>")
    html_lines.append("<h3>Steps</h3>")

    # Helper to attach images by base index (2,3,4,5 mapping preserved)
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
        html_lines.append("<details open>" if g["status"] != "PASS" else "<details>")
        html_lines.append("<summary>")
        html_lines.append(f"<div class='step-title'><div>{title}</div><div class='status {st_cls}'>{html.escape(g['status'])}</div></div>")
        html_lines.append("</summary>")
        html_lines.append("<div class='content'>")

        # Times table (aggregate from top + substeps)
        started_candidates = []
        finished_candidates = []
        for unit in ([g["top"]] if g["top"] else []) + g["subs"]:
            if unit and unit.started_at:
                started_candidates.append(unit.started_at)
            if unit and unit.finished_at:
                finished_candidates.append(unit.finished_at)
        agg_start = started_candidates[0] if started_candidates else "-"
        agg_finish = finished_candidates[-1] if finished_candidates else "-"

        html_lines.append("<table>")
        html_lines.append("<tr><th>Started</th><th>Finished</th></tr>")
        html_lines.append(f"<tr><td>{html.escape(agg_start)}</td><td>{html.escape(agg_finish)}</td></tr>")
        html_lines.append("</table>")

        # Plots attached by base index
        step_imgs = _images_for_base(base)
        if step_imgs:
            html_lines.append("<h4>Plots</h4>")
            html_lines.append(_render_img_grid(step_imgs, out_html.parent))

        # Substeps dropdowns
        if g["subs"]:
            html_lines.append("<div class='substeps'>")
            html_lines.append("<h4>Substeps</h4>")
            for sub in g["subs"]:
                sub_title = html.escape(sub.name)
                sub_cls = _color_class_local(sub.status)
                html_lines.append("<details>")
                html_lines.append("<summary>")
                html_lines.append(f"<div class='step-title'><div>{sub_title}</div><div class='status {sub_cls}'>{html.escape(sub.status)}</div></div>")
                html_lines.append("</summary>")
                html_lines.append("<div class='content'>")
                # Times
                html_lines.append("<table>")
                html_lines.append("<tr><th>Started</th><th>Finished</th></tr>")
                html_lines.append(f"<tr><td>{html.escape(sub.started_at or '-')}</td><td>{html.escape(sub.finished_at or '-')}</td></tr>")
                html_lines.append("</table>")
                # Log
                html_lines.append("<h4>Log</h4>")
                html_lines.append("<pre>")
                for ev in sub.lines:
                    html_lines.append(html.escape(ev.raw))
                html_lines.append("</pre>")
                html_lines.append("</div>")  # sub .content
                html_lines.append("</details>")
            html_lines.append("</div>")  # .substeps

        # Optional: top-level step log as an extra dropdown (if it has its own lines)
        if g["top"] and len(g["top"].lines) > 1:
            html_lines.append("<details>")
            html_lines.append("<summary><div class='step-title'><div>Step Log</div><div class='status unknown'>DETAIL</div></div></summary>")
            html_lines.append("<div class='content'>")
            html_lines.append("<h4>Log</h4>")
            html_lines.append("<pre>")
            for ev in g["top"].lines:
                html_lines.append(html.escape(ev.raw))
            html_lines.append("</pre>")
            html_lines.append("</div>")
            html_lines.append("</details>")

        html_lines.append("</div>")  # .content
        html_lines.append("</details>")
    html_lines.append("</section>")

    # Fallback: if there are "overall" images not used yet, add them
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
        html_lines.append("<h3>Images & Artifacts</h3>")
        html_lines.append(_render_img_grid(general_imgs, out_html.parent))
        html_lines.append("</section>")

    # EEPROM artifacts
    if eeprom_ascii or eeprom_raw:
        html_lines.append("<section>")
        html_lines.append("<h3>EEPROM Artifacts</h3>")
        html_lines.append("<ul>")
        if eeprom_ascii:
            rel = os.path.relpath(str(eeprom_ascii), str(out_html.parent))
            html_lines.append(f"<li><a href='{html.escape(rel)}' target='_blank'>ASCII dump</a></li>")
        if eeprom_raw:
            rel = os.path.relpath(str(eeprom_raw), str(out_html.parent))
            html_lines.append(f"<li><a href='{html.escape(rel)}' target='_blank'>Hex dump</a></li>")
        html_lines.append("</ul>")
        html_lines.append("</section>")

    html_lines.append("</main>")
    html_lines.append("</body></html>")

    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text("\n".join(html_lines), encoding="utf-8")
    
# ------------------------------- JUnit XML (opt) -------------------------------

def render_junit_xml(model: ReportModel, out_xml: Path) -> None:
    """
    Write a minimal JUnit XML so CI systems can ingest the step results.
    """
    total = len(model.steps)
    failures = sum(1 for s in model.steps if s.status == "FAIL")
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
    lines.append(f'<testsuite name="ENERGIS UART Functional Test Suite" tests="{total}" failures="{failures}" time="{time_placeholder}">')

    for idx, s in enumerate(model.steps, 1):
        case_name = s.name or f"Step {idx}"
        lines.append(f'  <testcase classname="ENERGIS.UART" name="{x(case_name)}" time="{time_placeholder}">')
        if s.status == "FAIL":
            # Include last FAIL line or a generic message
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
