"""Self-contained static HTML dashboard for SIMASTER teaching-load reports.

Like ``load.build_report``, this hand-builds the output with plain string
formatting (no templating engine, no new dependency) so it can run fully
offline: a single ``.html`` file with inline CSS/JS and no external assets.
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

from .load import (
    MEETING_WARN_MAX,
    MEETING_WARN_MIN,
    MEETINGS_PER_SEMESTER,
    OK_HIGH_SKS,
    PROGRAM_LEVELS,
    WARN_SKS,
)
from .parse import slugify

DASHBOARD_FILENAME = "index.html"
DEFAULT_CALENDAR_DIR = "assets/calendar"

STATUS_ORDER = ["OVERLOADED", "ABOVE", "OK", "UNDERLOADED", "WARNING", "NO_DATA"]

# A muted, print-report palette rather than flat-UI brights: status still
# maps 1:1 to the six bands, but a text label always accompanies the color
# (badges, card labels), so hue proximity within a family (e.g. the two reds)
# is a cosmetic risk, not a legibility one.
STATUS_COLORS = {
    "OVERLOADED": "#9c3b30",  # brick red
    "ABOVE": "#b07a2e",       # ochre/amber
    "OK": "#3f6b4a",          # forest green
    "UNDERLOADED": "#8a7a2e", # olive/mustard
    "WARNING": "#8c2f2f",     # deep maroon
    "NO_DATA": "#7a746a",     # warm gray
}

# One palette for S1/S2/S3/Profesi used everywhere a level needs a color --
# table badges, the Exhibit 2 cards/charts, and the network -- so the same
# hue means the same level across every exhibit. Validated as a categorical
# palette (distinct hues, CVD-safe adjacent pairs) via the dataviz skill's
# validator; OTHER is deliberately a neutral gray outside that hue set,
# the standard treatment for a catch-all/unclassified bucket.
LEVEL_COLORS = {
    "S1": "#2a78d6",       # blue
    "S2": "#eb6834",       # orange
    "S3": "#1baf7a",       # aqua/green
    "PROFESI": "#eda100",  # gold
    "OTHER": "#6b6357",    # warm gray-brown (deliberately outside the hue set)
}

ACCENT = "#13294b"  # masthead navy

# Column tuples are (key, label, kind), where kind is "text" (left-aligned,
# shown as-is), "num" (centered, shown as-is) or "sks" (centered, rounded to
# 1 decimal for display -- the underlying data keeps full precision for
# sorting/filtering).
LECTURER_COLUMNS = [
    ("dosen", "Lecturer", "text"),
    ("scheduled_sks", "Scheduled SKS", "sks"),
    ("est_sks", "Est. SKS", "sks"),
    ("sks_s1", "SKS S1", "sks"),
    ("sks_s2", "SKS S2", "sks"),
    ("sks_s3", "SKS S3", "sks"),
    ("sks_profesi", "SKS Profesi", "sks"),
    ("sks_unscheduled", "SKS Unsched.", "sks"),
    ("n_classes", "#Classes", "num"),
    ("n_courses", "#Courses", "num"),
    ("status", "Status", "text"),
]

# Appended to LECTURER_COLUMNS only when a calendar dir is configured (see
# render_dashboard's `calendar_dir`) -- the raw href/label pair the
# JS table renderer special-cases to draw a download link instead of text.
ICS_COLUMN = ("ics", "Calendar", "text")

CLASS_COLUMNS = [
    ("dosen", "Lecturer", "text"),
    ("kode", "Kode", "text"),
    ("mata_kuliah", "Mata Kuliah", "text"),
    ("rumpun", "Rumpun/Prodi", "text"),
    ("level", "Level", "text"),
    ("kelas", "Kelas", "text"),
    ("sks", "SKS", "sks"),
    ("class_meetings", "Meetings", "num"),
    ("own_meetings", "Own", "num"),
    ("own_credit", "Credit", "sks"),
    ("est_credit", "Est.", "sks"),
]

# (LECTURERS field, level label) -- the four SKS fields that partition
# scheduled_sks by program level, used to build the stacked-bar visuals.
LEVEL_SKS_FIELDS = [
    ("sks_s1", "S1"),
    ("sks_s2", "S2"),
    ("sks_s3", "S3"),
    ("sks_profesi", "PROFESI"),
]

LECTURERS_CAPTION = (
    "Ranked by Scheduled SKS &mdash; the credit already booked on a room and "
    "time slot this semester. Click a name to filter the class list below to "
    "that lecturer; click any column heading to sort."
)
LEVELS_CAPTION = (
    "Class sessions grouped by program level, detected from each course's "
    "rumpun tag, plus a tally of classes still awaiting a schedule (own_credit "
    "is 0 until then, so they're invisible in the per-level totals above "
    "without this). Click a level tile to filter the class list to that level."
)
LEVEL_CHART_CAPTION = (
    "Total Scheduled vs. Unscheduled SKS by program level across every "
    "listed lecturer, on a shared SKS scale (not a percentage of the "
    "whole)."
)
def _level_bars_caption(ok_high: float, max_sks: float) -> str:
    return (
        "Each lecturer's SKS split by program level, and within each level by "
        "scheduled vs. unscheduled (solid vs. translucent, per the legend "
        "above) &mdash; mirrors the filter/sort applied to Exhibit 1 above. "
        f"The two faint vertical marks are reference points for scale, not a "
        f"verdict: {ok_high:g} (top of the commonly used ideal teaching-only "
        f"range) and {max_sks:g} (a commonly used overall load ceiling). "
        f"Click a bar to filter the class list to that lecturer."
    )
NETWORK_CAPTION = (
    "Lecturers who co-teach the same course (same <strong>kode</strong>, "
    "any kelas), restricted to the lecturers listed elsewhere in this report "
    "(built from the faculty-wide session catalog, which also sees "
    "co-teachers outside that list). Two views of the same data below, "
    "sharing the threshold and search controls here: a <strong>matrix</strong> "
    "(rows/columns are the same lecturers, ordered by number of distinct "
    "scheduled courses; a cell's shade is how many courses that row and "
    "column co-teach together, diagonal blank) &mdash; at this faculty's "
    "density (most lecturers co-teach with many colleagues) a matrix stays "
    "exactly as readable as it is sparse, where a node-link graph just "
    "collapses into a hairball &mdash; and a <strong>diagram</strong> for "
    "exploring one lecturer's immediate connections at a time. Use the "
    "threshold to blank out one-off overlaps, search to highlight a "
    "lecturer, and click a lecturer's name (matrix) or node (diagram) to "
    "filter Exhibit 1 to them."
)
NETWORK_KELAS_CAPTION = (
    "A narrower relationship than the network above: lecturers who co-teach "
    "the same <strong>class section</strong> (same kode <em>and</em> kelas), "
    "weighted by distinct sections shared &mdash; so two lecturers who teach "
    "the same course but never the same section (e.g. different kelas) show "
    "an edge above but not here. Same matrix/diagram views, threshold, "
    "search and click-to-filter behavior as above."
)
NETWORK_DIAGRAM_CAPTION = (
    "Node size is each lecturer's total scheduled SKS (Exhibit 1); node color "
    "is degree centrality &mdash; how many distinct co-teachers they have in "
    "this network, darker meaning more (see the gradient legend above; "
    "program level is in the tooltip instead). A fixed layout, not a running "
    "simulation &mdash; positions are computed once with generous spacing so "
    "nodes don't crowd each other, then held still. Drag a node to see its "
    "neighborhood pull free of the rest of the graph; release it and it "
    "springs back to its regular spot."
)
CLASSES_CAPTION = (
    "Every class session by lecturer &mdash; for a co-taught class, only that "
    "lecturer's own sessions are counted. Sortable and filterable like the "
    "table above."
)
WARNINGS_CAPTION = (
    "Classes whose booked meeting count falls outside the expected "
    f"{MEETING_WARN_MIN}&ndash;{MEETING_WARN_MAX} sessions per semester "
    "&mdash; often a make-up class, a mid-semester schedule change, or an "
    "incomplete booking."
)


def _e(v) -> str:
    return html.escape(str(v), quote=True)


def _json_for_script(data) -> str:
    return json.dumps(data).replace("</", "<\\/")


def _status_css() -> str:
    return "\n".join(
        f".status-{status} {{ --status-color: {color}; }}"
        for status, color in STATUS_COLORS.items()
    )


def _level_css() -> str:
    return "\n".join(
        f".level-{level} {{ --level-color: {color}; }}"
        for level, color in LEVEL_COLORS.items()
    )


def _level_cards(result: dict) -> str:
    # Total SKS per level is the strict credit (own_credit): only classes
    # with a fixed/booked schedule count, same as the lecturers' scheduled_sks.
    totals = {level: {"n": 0, "sks": 0.0} for level in PROGRAM_LEVELS}
    unscheduled_n = 0
    unscheduled_sks = 0.0
    for row in result["classes"]:
        t = totals.setdefault(row["level"], {"n": 0, "sks": 0.0})
        t["n"] += 1
        t["sks"] += row["own_credit"]
        if row["class_meetings"] == 0:
            unscheduled_n += 1
            unscheduled_sks += row["est_credit"]  # own_credit is 0 here, so this is the full gap
    cards = []
    for level in PROGRAM_LEVELS:
        t = totals[level]
        cards.append(
            f'<div class="card level-{level}" '
            f'onclick="classFilterInput.value=\'{level}\';classTable.render();">'
            f'<div class="card-count">{t["n"]}</div>'
            f'<div class="card-label">{_e(level)} &middot; {t["sks"]:g} SKS</div></div>'
        )
    cards.append(
        '<div class="card no-click">'
        f'<div class="card-count">{unscheduled_n}</div>'
        f'<div class="card-label">Unscheduled &middot; {unscheduled_sks:g} SKS</div></div>'
    )
    total_n = sum(t["n"] for t in totals.values())
    total_sks = sum(t["sks"] for t in totals.values())
    cards.append(
        '<div class="card" onclick="classFilterInput.value=\'\';classTable.render();">'
        f'<div class="card-count">{total_n}</div>'
        f'<div class="card-label">TOTAL &middot; {total_sks:g} SKS</div></div>'
    )
    return "\n".join(cards)


def _stat_cards(result: dict) -> str:
    cards = [
        f'<div class="card" data-status="" onclick="filterInput.value=\'\';lecturerTable.render();">'
        f'<div class="card-count">{len(result["lecturers"])}</div>'
        f'<div class="card-label">Total lecturers</div></div>',
        f'<div class="card" data-status="" onclick="document.getElementById(\'warnings\').scrollIntoView();">'
        f'<div class="card-count">{len(result["warnings"])}</div>'
        f'<div class="card-label">Warnings</div></div>',
    ]
    if result.get("neutral"):
        no_data_n = sum(1 for r in result["lecturers"] if r["status"] == "NO_DATA")
        if no_data_n:
            cards.append(
                '<div class="card no-click status-NO_DATA">'
                f'<div class="card-count">{no_data_n}</div>'
                '<div class="card-label">No data</div></div>'
            )
        return "\n".join(cards)

    counts = {status: 0 for status in STATUS_ORDER}
    for row in result["lecturers"]:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    for status in STATUS_ORDER:
        cards.append(
            f'<div class="card status-{status}" '
            f'onclick="filterInput.value=\'{status}\';lecturerTable.render();">'
            f'<div class="card-count">{counts[status]}</div>'
            f'<div class="card-label">{_e(status)}</div></div>'
        )
    return "\n".join(cards)


def _warnings_html(warnings: list[str]) -> str:
    if not warnings:
        return "<li><em>none</em></li>"
    return "\n".join(f"<li>{_e(w)}</li>" for w in warnings)


def _methodology_html(
    warn: float,
    ok_min: float,
    ok_high: float,
    max_sks: float,
    neutral: bool = False,
    has_ics: bool = False,
) -> str:
    """A short prose explainer for how the numbers/bands in this report are derived."""
    intro = f"""
<p>This report is a scheduling reference &mdash; a way for lecturers and
coordinators to see, in one place, who is teaching what and how the credit
(SKS) adds up, so each lecturer can track and plan their own schedule. It
counts each lecturer's <strong>own class sessions only</strong>: on a
co-taught class, credit belongs to whichever lecturer actually leads a given
session, so shared classes are never double-counted.</p>
<p><strong>Scheduled SKS</strong> is the credit already booked on a room and
time slot this semester &mdash; each class contributes its course credit
(SKS) scaled by the share of the semester's {MEETINGS_PER_SEMESTER} meetings
the lecturer actually teaches, and a class with no booked schedule yet
contributes nothing. <strong>Est. SKS</strong> closes that gap by adding
credit for classes still awaiting a schedule (split evenly when more than one
lecturer is assigned to it), estimating the eventual total once every class
is booked; the difference between the two &mdash; shown as <strong>SKS
Unsched.</strong> &mdash; is exposure still sitting in unscheduled classes.</p>
"""
    if neutral:
        status_para = ""
    else:
        status_para = f"""
<p>For reference, this report also bands Scheduled SKS: below {warn:g} is
<strong>WARNING</strong>; {warn:g}&ndash;{ok_min:g} is
<strong>UNDERLOADED</strong>; {ok_min:g}&ndash;{ok_high:g} is
<strong>OK</strong> &mdash; the ideal <em>teaching-only</em> range, since the
official {ok_high:g}-SKS minimum load already folds in research;
{ok_high:g}&ndash;{max_sks:g} is <strong>ABOVE</strong>; and past
{max_sks:g} is <strong>OVERLOADED</strong>, the hard ceiling that itself
still has to cover research, community service and supporting duties on top
of teaching. These bands are a reference only, not a verdict &mdash; reading
the distribution and deciding what, if anything, it calls for is left to the
reader.</p>
"""
    level_para = """
<p>Program level (S1/S2/S3/Profesi) is read from each course's rumpun tag
(a doctoral course code prefix is also recognized as a fallback); S3 credit
is broken out on its own since doctoral supervision carries different
expectations than undergraduate or master's teaching.</p>
"""
    ics_para = ""
    if has_ics:
        ics_para = """
<p>Each lecturer's row in Exhibit 1 has a <strong>Calendar</strong> button
that downloads their own class sessions as a calendar file (.ics). To add it
to Google Calendar: open Google Calendar on the web, click the gear icon
&rarr; <strong>Settings</strong> &rarr; <strong>Import &amp; export</strong>
&rarr; <strong>Import</strong>, choose the downloaded file, pick which
calendar to add it to, then click <strong>Import</strong>. Most other
calendar apps (Outlook, Apple Calendar, etc.) support the same .ics format.
Events are already converted to the correct local time, and re-importing an
updated file after a schedule change replaces the matching events instead of
duplicating them.</p>
"""
    return (intro + status_para + level_para + ics_para).strip()


def _network_legend_html() -> str:
    # Node color in the diagram below is degree centrality (co-teaching
    # connection count), not program level -- see NETWORK_DIAGRAM_CAPTION --
    # so the legend is this one gradient rather than a per-level swatch list.
    return (
        '<span class="legend-item">Fewer connections'
        '<span class="gradient-bar"></span>More connections</span>'
    )


def _network_section(
    network: dict | None,
    *,
    id_prefix: str,
    exhibit_num: int,
    title: str,
    caption: str,
    unit_label: str,
) -> str:
    """Render one network exhibit (matrix + diagram).

    ``id_prefix`` distinguishes multiple network exhibits on the same page
    (e.g. the course-level network uses ``""`` -- so its element ids match
    this dashboard's original, pre-multi-network markup -- and the
    class-section-level one uses ``"kelas"``); ``unit_label`` (singular,
    e.g. "course"/"class section") drives the threshold control's wording,
    with the matching plural/tooltip wording handled client-side.
    """
    if not network or not network["nodes"]:
        return ""
    suffix = f"-{id_prefix}" if id_prefix else ""
    return f"""
<section id="network{suffix}">
  <h2><span class="exhibit-tag">Exhibit {exhibit_num}</span> {title}</h2>
  <p class="caption">{caption}</p>
  <div class="network-controls">
    <input id="network{suffix}-filter" type="search" placeholder="Highlight a lecturer and their co-teachers...">
    <label for="network{suffix}-min-weight">Min. shared {unit_label}s:
      <select id="network{suffix}-min-weight">
        <option value="1">1+</option>
        <option value="2" selected>2+</option>
        <option value="3">3+</option>
        <option value="5">5+</option>
      </select>
    </label>
    <span id="network{suffix}-count" class="filter-count"></span>
  </div>
  <div class="network-legend">{_network_legend_html()}</div>
  <div class="network-body">
    <h3 class="subhead">Diagram</h3>
    <p class="caption">{NETWORK_DIAGRAM_CAPTION}</p>
    <div class="network-diagram-canvas">
      <svg id="network{suffix}-svg" class="network-svg" viewBox="0 0 960 700" xmlns="http://www.w3.org/2000/svg"></svg>
    </div>

    <h3 class="subhead">Matrix</h3>
    <div class="matrix-scroll">
      <table id="network{suffix}-matrix" class="network-matrix">
        <thead><tr id="network{suffix}-matrix-head"></tr></thead>
        <tbody id="network{suffix}-matrix-body"></tbody>
      </table>
    </div>

    <div id="network{suffix}-tooltip" class="network-tooltip" hidden></div>
  </div>
</section>
"""


def _ics_href(calendar_dir: str, dosen: str, semester: str) -> str:
    return f"{calendar_dir.rstrip('/')}/jadwal_{slugify(dosen)}_{semester}.ics"


def render_dashboard(
    result: dict,
    network: dict | None = None,
    class_network: dict | None = None,
    calendar_dir: str | None = DEFAULT_CALENDAR_DIR,
) -> str:
    """Render the full aggregate_loads() result into one HTML document.

    ``network`` (course-level) and ``class_network`` (class-section-level)
    are the optional ``network.build_network()`` results -- see its ``unit``
    parameter; each is independently left out of the page when omitted or
    empty rather than rendered empty.

    ``calendar_dir``, when truthy, adds a per-lecturer "Calendar" column
    linking to ``{calendar_dir}/jadwal_<slug>_<semester>.ics`` -- the same
    filename ``ics.write_ics`` produces -- a path relative to wherever this
    HTML file itself is deployed. Pass ``None``/``""`` to omit the column
    (e.g. when no .ics files are being published alongside the dashboard).
    """
    semester = _e(result.get("semester", ""))
    neutral = bool(result.get("neutral"))
    warn = result.get("warn_sks", WARN_SKS)
    ok_min = result.get("min_sks", 8.0)
    ok_high = result.get("ok_high", OK_HIGH_SKS)
    max_sks = result.get("max_sks", 16.0)
    generated = datetime.now().isoformat(timespec="seconds")

    lecturer_columns = [c for c in LECTURER_COLUMNS if not (neutral and c[0] == "status")]
    lecturers = result["lecturers"]
    if calendar_dir:
        lecturer_columns.append(ICS_COLUMN)
        raw_semester = result.get("semester", "")
        lecturers = [
            {**row, "ics": _ics_href(calendar_dir, row["dosen"], raw_semester)}
            for row in lecturers
        ]

    lecturer_cols_json = _json_for_script([key for key, _, _ in lecturer_columns])
    class_cols_json = _json_for_script([key for key, _, _ in CLASS_COLUMNS])
    lecturer_centered_json = _json_for_script(
        [key for key, _, kind in lecturer_columns if kind in ("num", "sks")]
    )
    class_centered_json = _json_for_script(
        [key for key, _, kind in CLASS_COLUMNS if kind in ("num", "sks")]
    )
    lecturer_sks_json = _json_for_script([key for key, _, kind in lecturer_columns if kind == "sks"])
    class_sks_json = _json_for_script([key for key, _, kind in CLASS_COLUMNS if kind == "sks"])
    lecturers_json = _json_for_script(lecturers)
    classes_json = _json_for_script(result["classes"])
    level_sks_fields_json = _json_for_script(LEVEL_SKS_FIELDS)
    network_json = _json_for_script(network if network else {"nodes": [], "edges": []})
    class_network_json = _json_for_script(class_network if class_network else {"nodes": [], "edges": []})

    exhibit_n = 4
    course_network_section = ""
    class_network_section = ""
    if network and network["nodes"]:
        course_network_section = _network_section(
            network,
            id_prefix="",
            exhibit_num=exhibit_n,
            title="Shared-course network",
            caption=NETWORK_CAPTION,
            unit_label="course",
        )
        exhibit_n += 1
    if class_network and class_network["nodes"]:
        class_network_section = _network_section(
            class_network,
            id_prefix="kelas",
            exhibit_num=exhibit_n,
            title="Shared-class network",
            caption=NETWORK_KELAS_CAPTION,
            unit_label="class section",
        )
        exhibit_n += 1
    network_section = course_network_section + class_network_section
    warnings_exhibit_n = exhibit_n
    methodology_html = _methodology_html(
        warn, ok_min, ok_high, max_sks, neutral=neutral, has_ics=bool(calendar_dir)
    )

    def _th(key, label, kind):
        cls = ' class="num"' if kind in ("num", "sks") else ""
        return f'<th data-key="{key}"{cls}>{_e(label)}</th>'

    lecturer_headers = "\n".join(_th(key, label, kind) for key, label, kind in lecturer_columns)
    class_headers = "\n".join(_th(key, label, kind) for key, label, kind in CLASS_COLUMNS)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Teaching Schedule &mdash; Semester {semester}</title>
<style>
:root {{
  --bg: #f7f5f0;
  --panel: #fffdf9;
  --text: #1a1a1a;
  --muted: #5c5750;
  --border: #ddd8cd;
  --accent: {ACCENT};
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  padding: 2rem 1.5rem;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  line-height: 1.5;
}}
.container {{ max-width: 1200px; margin: 0 auto; }}
header {{ border-bottom: 2px solid var(--accent); padding-bottom: 1rem; margin-bottom: 1.5rem; }}
header .kicker {{
  margin: 0 0 0.4rem;
  color: var(--accent);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}}
header h1 {{
  margin: 0 0 0.4rem;
  font-family: Georgia, Cambria, "Times New Roman", serif;
  font-size: 2.1rem;
  font-weight: 700;
  letter-spacing: -0.01em;
}}
header .dek {{
  margin: 0;
  color: var(--muted);
  font-family: Georgia, Cambria, "Times New Roman", serif;
  font-style: italic;
  font-size: 1.05rem;
}}
h2 {{
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  margin: 0 0 0.35rem;
  font-family: Georgia, Cambria, "Times New Roman", serif;
  font-size: 1.3rem;
  font-weight: 700;
}}
.exhibit-tag {{
  font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--accent);
  white-space: nowrap;
}}
.caption {{
  margin: 0 0 0.9rem;
  color: var(--muted);
  font-size: 0.88rem;
  max-width: 62ch;
}}
.stat-cards {{
  display: flex;
  flex-wrap: wrap;
  gap: 0;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  margin-bottom: 1.5rem;
  padding: 0.9rem 0;
}}
.card {{
  background: transparent;
  border: none;
  border-right: 1px solid var(--border);
  border-radius: 0;
  padding: 0 1.25rem;
  cursor: pointer;
  flex: 1 1 130px;
  text-align: center;
}}
.card:last-child {{ border-right: none; }}
.card.no-click {{ cursor: default; }}
.card.no-click .card-count {{ color: var(--muted); }}
.card-count {{
  font-family: Georgia, Cambria, "Times New Roman", serif;
  font-size: 1.9rem;
  font-weight: 700;
  line-height: 1;
}}
.card.status-OVERLOADED .card-count, .card.status-ABOVE .card-count,
.card.status-OK .card-count, .card.status-UNDERLOADED .card-count,
.card.status-WARNING .card-count, .card.status-NO_DATA .card-count {{
  color: var(--status-color);
}}
.card.level-S1 .card-count, .card.level-S2 .card-count, .card.level-S3 .card-count,
.card.level-PROFESI .card-count, .card.level-OTHER .card-count {{
  color: var(--level-color);
}}
.card-label {{
  margin-top: 0.35rem;
  color: var(--muted);
  font-size: 0.72rem;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}}
section {{
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 2px;
  padding: 1.25rem 1.5rem;
  margin-bottom: 1.5rem;
  overflow-x: auto;
}}
section.methodology {{
  border: none;
  border-left: 3px solid var(--accent);
  border-radius: 0;
  background: transparent;
  padding: 0.1rem 0 0.1rem 1.5rem;
}}
section.methodology p {{
  font-family: Georgia, Cambria, "Times New Roman", serif;
  font-size: 1.02rem;
  line-height: 1.65;
  margin: 0 0 0.9rem;
}}
section.methodology p:last-child {{ margin-bottom: 0; }}
input[type="search"] {{
  display: block;
  width: 100%;
  max-width: 340px;
  padding: 0.4rem 0.1rem;
  border: none;
  border-bottom: 1px solid var(--text);
  border-radius: 0;
  background: transparent;
  font-size: 0.95rem;
  margin-bottom: 0.75rem;
}}
input[type="search"]:focus {{ outline: none; border-bottom: 2px solid var(--accent); }}
.filter-count {{ color: var(--muted); font-size: 0.85rem; margin-left: 0.5rem; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.9rem; }}
.num {{ text-align: center; }}
thead th {{
  position: sticky;
  top: 0;
  background: var(--panel);
  text-align: left;
  border-top: 1px solid var(--text);
  border-bottom: 1px solid var(--text);
  padding: 0.45rem 0.6rem;
  cursor: pointer;
  white-space: nowrap;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--muted);
}}
tbody td {{ padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--border); }}
tbody tr.lecturer-row {{ cursor: pointer; }}
{_status_css()}
{_level_css()}
.badge {{
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
}}
.badge::before {{
  content: "";
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--status-color);
  flex: 0 0 auto;
}}
.badge.level-S1::before, .badge.level-S2::before, .badge.level-S3::before,
.badge.level-PROFESI::before, .badge.level-OTHER::before {{
  background: var(--level-color);
}}
#warnings-list {{ margin: 0; padding-left: 1.25rem; }}
h3.subhead {{
  margin: 1.5rem 0 0.2rem;
  font-family: Georgia, Cambria, "Times New Roman", serif;
  font-size: 1.05rem;
  font-weight: 700;
}}
.level-chart {{ width: 60%; margin-top: 0.5rem; }}
.level-chart-legend {{
  display: flex;
  gap: 1.1rem;
  margin-bottom: 0.5rem;
  font-size: 0.78rem;
  color: var(--muted);
}}
.level-chart-legend .legend-item {{ display: inline-flex; align-items: center; }}
.level-chart-legend .swatch {{
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  margin-right: 0.35rem;
  background: var(--muted);
}}
.level-chart-legend .swatch-scheduled {{ opacity: 1; }}
.level-chart-legend .swatch-unscheduled {{ opacity: 0.4; }}
.level-chart-row {{ display: flex; align-items: center; gap: 0.5rem; height: 28px; }}
.level-chart-label {{
  flex: 0 0 62px;
  font-size: 0.78rem;
  color: var(--muted);
  text-align: right;
}}
.level-chart-track {{ position: relative; flex: 1 1 auto; height: 18px; }}
.level-chart-gridline {{
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--border);
}}
.level-chart-bar {{
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background: var(--level-color);
}}
.unscheduled-seg {{ opacity: 0.4; }}
.level-chart-bar.unscheduled-seg {{ border-left: 2px solid var(--panel); }}
.level-chart-value {{
  flex: 0 0 auto;
  font-size: 0.78rem;
  font-variant-numeric: tabular-nums;
  color: var(--text);
  white-space: nowrap;
}}
.level-chart-axis-row {{ display: flex; gap: 0.5rem; margin-top: 2px; }}
.level-chart-axis-spacer {{ flex: 0 0 62px; }}
.level-chart-axis {{ position: relative; flex: 1 1 auto; height: 14px; }}
.level-chart-axis .tick {{
  position: absolute;
  transform: translateX(-50%);
  font-size: 0.68rem;
  color: var(--muted);
}}
.level-chart-axis .tick.ref-tick {{ color: var(--text); font-weight: 600; }}
.level-bar-track {{
  position: relative;
  display: flex;
  width: 100%;
  height: 1.6rem;
  border-radius: 2px;
  overflow: hidden;
  background: var(--border);
}}
.level-bar-refline {{
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--text);
  opacity: 0.3;
  pointer-events: none;
}}
.level-bar-segment {{
  background: var(--level-color);
  min-width: 0;
}}
.level-bar-segment + .level-bar-segment {{ border-left: 2px solid var(--panel); }}
.level-bars {{ display: flex; flex-direction: column; gap: 0.4rem; margin-top: 0.4rem; }}
.level-bar-row {{
  display: flex;
  align-items: center;
  gap: 0.6rem;
  cursor: pointer;
}}
.level-bar-row .level-bar-label {{
  flex: 0 0 220px;
  font-size: 0.85rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}}
.level-bar-row .level-bar-track {{ flex: 1 1 auto; height: 1.1rem; }}
.level-bar-row.axis-row {{ cursor: default; }}
.show-more-btn {{
  margin-top: 0.6rem;
  padding: 0.45rem 1rem;
  border: 1px solid var(--accent);
  background: transparent;
  color: var(--accent);
  border-radius: 2px;
  font-size: 0.85rem;
  cursor: pointer;
}}
.show-more-btn:hover {{ background: var(--accent); color: #fff; }}
.ics-btn {{
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.2rem 0.55rem;
  border: 1px solid var(--accent);
  border-radius: 3px;
  background: transparent;
  color: var(--accent);
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  text-decoration: none;
  white-space: nowrap;
  cursor: pointer;
}}
.ics-btn:hover {{ background: var(--accent); color: #fff; }}
.network-controls {{
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 1rem;
  margin-bottom: 0.75rem;
}}
.network-controls input[type="search"] {{ margin-bottom: 0; flex: 1 1 260px; }}
.network-controls label {{ font-size: 0.85rem; color: var(--muted); }}
.network-legend {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.9rem;
  margin-bottom: 0.5rem;
  font-size: 0.78rem;
  color: var(--muted);
}}
.network-legend .legend-item {{ display: inline-flex; align-items: center; }}
.network-legend .gradient-bar {{
  display: inline-block;
  width: 110px;
  height: 8px;
  border-radius: 2px;
  margin: 0 0.5rem;
  vertical-align: middle;
  background: linear-gradient(to right, rgb(214, 221, 230), {ACCENT});
}}
.network-body {{ position: relative; }}
.matrix-scroll {{
  overflow: auto;
  max-height: 640px;
  border: 1px solid var(--border);
  background: var(--panel);
}}
.network-matrix {{
  border-collapse: collapse;
  table-layout: fixed;
  width: auto;
  font-size: 0.68rem;
}}
.network-matrix th, .network-matrix td {{ padding: 0; border: 1px solid var(--bg); }}
.network-matrix thead th {{
  position: sticky;
  top: 0;
  background: var(--panel);
  border-top: none;
  cursor: default;
  z-index: 2;
}}
.network-matrix th.corner {{ position: sticky; left: 0; z-index: 3; width: 220px; }}
.network-matrix th.col-head {{
  writing-mode: vertical-rl;
  transform: rotate(180deg);
  width: 15px;
  max-height: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
  font-weight: 400;
  text-transform: none;
  letter-spacing: normal;
  padding-bottom: 0.3rem;
  vertical-align: bottom;
}}
.network-matrix th.row-head {{
  position: sticky;
  left: 0;
  background: var(--panel);
  text-align: right;
  padding-right: 0.4rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 400;
  text-transform: none;
  letter-spacing: normal;
  cursor: pointer;
  z-index: 1;
}}
.network-matrix th.row-head.highlight, .network-matrix th.col-head.highlight {{
  color: var(--accent);
  font-weight: 700;
}}
.network-matrix td.cell {{ width: 15px; height: 15px; }}
.network-matrix td.cell.diagonal {{ background: var(--border); }}
.network-matrix td.cell.has-edge {{ cursor: pointer; }}
.network-matrix td.cell.dimmed {{ opacity: 0.15; }}
.network-diagram-canvas {{ position: relative; }}
.network-svg {{
  width: 100%;
  height: auto;
  background: var(--panel);
  border: 1px solid var(--border);
}}
.network-svg circle.node-dot {{
  fill: #9aa5b1;
  stroke: var(--panel);
  stroke-width: 1px;
  cursor: grab;
  touch-action: none;
  opacity: 0.9;
  transition: opacity 0.15s ease;
}}
.network-svg circle.node-dot:active {{ cursor: grabbing; }}
.network-svg line.network-edge {{
  stroke: var(--muted);
  opacity: 0.35;
  transition: opacity 0.15s ease;
}}
.network-svg .dimmed {{ opacity: 0.08 !important; }}
.network-tooltip {{
  position: absolute;
  pointer-events: none;
  background: var(--text);
  color: var(--bg);
  font-size: 0.78rem;
  padding: 0.4rem 0.55rem;
  border-radius: 3px;
  max-width: 260px;
  z-index: 10;
}}
</style>
</head>
<body>
<div class="container">
<header>
  <p class="kicker">Fakultas Biologi UGM &middot; SIMASTER</p>
  <h1>Teaching Schedule</h1>
  <p class="dek">Semester {semester} &middot; generated {generated} &mdash; a
  scheduling reference to help lecturers and coordinators track and plan
  their schedule.</p>
</header>

<section class="stat-cards">
{_stat_cards(result)}
</section>

<section class="methodology">
  <h2>Methodology</h2>
  {methodology_html}
</section>

<section id="lecturers">
  <h2><span class="exhibit-tag">Exhibit 1</span> Lecturers</h2>
  <p class="caption">{LECTURERS_CAPTION}</p>
  <input id="filter" type="search" placeholder="{'Filter by lecturer...' if neutral else 'Filter by lecturer or status...'}">
  <span id="filter-count" class="filter-count"></span>
  <table id="lecturer-table">
    <thead><tr>
{lecturer_headers}
    </tr></thead>
    <tbody></tbody>
  </table>
</section>

<section id="levels">
  <h2><span class="exhibit-tag">Exhibit 2</span> By program level</h2>
  <p class="caption">{LEVELS_CAPTION}</p>
  <div class="stat-cards">
{_level_cards(result)}
  </div>
  <p class="caption">{LEVEL_CHART_CAPTION}</p>
  <div class="level-chart-legend">
    <span class="legend-item"><span class="swatch swatch-scheduled"></span>Scheduled</span>
    <span class="legend-item"><span class="swatch swatch-unscheduled"></span>Unscheduled</span>
  </div>
  <div id="level-total-bar"></div>
  <h3 class="subhead">By lecturer</h3>
  <p class="caption">{_level_bars_caption(ok_high, max_sks)}</p>
  <div class="level-bars" id="level-bars"></div>
</section>

<section id="classes">
  <h2><span class="exhibit-tag">Exhibit 3</span> Per-class detail</h2>
  <p class="caption">{CLASSES_CAPTION}</p>
  <input id="class-filter" type="search" placeholder="Filter classes (lecturer, kode, rumpun, level...)">
  <span id="class-filter-count" class="filter-count"></span>
  <table id="class-table">
    <thead><tr>
{class_headers}
    </tr></thead>
    <tbody></tbody>
  </table>
  <button id="class-show-more" type="button" class="show-more-btn" hidden></button>
</section>
{network_section}
<section id="warnings">
  <h2><span class="exhibit-tag">Exhibit {warnings_exhibit_n}</span> Warnings ({len(result["warnings"])})</h2>
  <p class="caption">{WARNINGS_CAPTION}</p>
  <ul id="warnings-list">
{_warnings_html(result["warnings"])}
  </ul>
</section>
</div>

<script>
const LECTURERS = {lecturers_json};
const CLASSES = {classes_json};
const LECTURER_COLUMNS = {lecturer_cols_json};
const CLASS_COLUMNS = {class_cols_json};
const LECTURER_CENTERED = {lecturer_centered_json};
const CLASS_CENTERED = {class_centered_json};
const LECTURER_SKS = {lecturer_sks_json};
const CLASS_SKS = {class_sks_json};
const LEVEL_SKS_FIELDS = {level_sks_fields_json};
const NETWORK = {network_json};
const NETWORK_KELAS = {class_network_json};
// The 12/16-SKS reference marks drawn on Exhibit 2's per-lecturer bars --
// ok_high (the top of the ideal teaching-only band) and max_sks (the overall
// ceiling) -- same values the (optional) status bands are drawn from.
const OK_HIGH_SKS = {ok_high:g};
const MAX_SKS = {max_sks:g};

const filterInput = document.getElementById("filter");
const classFilterInput = document.getElementById("class-filter");

// Sequential single-hue heatmap: white at 0 up to a contrast-safe mid step
// at each column's max, so dark table text stays readable (AA-safe through
// this endpoint). Scale is fixed per column from the full dataset, not the
// filtered view, so a cell's shade never shifts as you filter/sort.
const HEATMAP_LOW = [255, 255, 255];
const HEATMAP_HIGH = [150, 168, 194]; // dusty slate-navy, echoes --accent

function heatmapColor(t) {{
  const c = HEATMAP_LOW.map((lo, i) => Math.round(lo + (HEATMAP_HIGH[i] - lo) * t));
  return "rgb(" + c.join(",") + ")";
}}

// Sequential node-fill scale for the network diagram, keyed to each node's
// degree (distinct co-teachers) rather than its program level -- so color
// reads as "how central is this lecturer in the co-teaching network"
// (darker = more connections). A light-slate floor (not white) keeps every
// node visible even at 0 connections; the high end matches --accent, the
// same navy used for emphasis elsewhere on the page. Program level moves to
// the tooltip/title instead of a swatch.
const NODE_COLOR_LOW = [214, 221, 230];
const NODE_COLOR_HIGH = [19, 41, 75];

function nodeColor(t) {{
  const c = NODE_COLOR_LOW.map((lo, i) => Math.round(lo + (NODE_COLOR_HIGH[i] - lo) * t));
  return "rgb(" + c.join(",") + ")";
}}

function columnMaxes(data, keys) {{
  const maxes = {{}};
  for (const key of keys) {{
    maxes[key] = data.reduce((m, r) => Math.max(m, Number(r[key]) || 0), 0);
  }}
  return maxes;
}}

function makeTable(opts) {{
  const {{
    data, columns, tbody, filterInput, countEl, defaultKey, defaultDir = -1, rowClass, onRowClick,
    centeredColumns = [], sksColumns = [], pageSize = null, firstPageSize = null, moreButton = null,
  }} = opts;
  const initialVisible = firstPageSize || pageSize || data.length;
  const state = {{ key: defaultKey, dir: defaultDir, visible: initialVisible }};
  const heatmapMax = columnMaxes(data, centeredColumns);
  // `rows` exposes the currently filtered+sorted row set -- the full match,
  // not just the visible page -- (updated on every render) so other views
  // -- the per-lecturer level bars -- can mirror this table's filter/sort
  // without re-implementing it.
  const table = {{ state, rows: data }};

  function matches(row, q) {{
    if (!q) return true;
    q = q.toLowerCase();
    return columns.some(k => String(row[k]).toLowerCase().includes(q));
  }}

  function render() {{
    const q = filterInput.value.trim();
    let rows = data.filter(r => matches(r, q));
    rows.sort((a, b) => {{
      const av = a[state.key], bv = b[state.key];
      let cmp;
      if (typeof av === "number" && typeof bv === "number") {{
        cmp = av - bv;
      }} else {{
        cmp = String(av).localeCompare(String(bv));
      }}
      return cmp * state.dir;
    }});
    table.rows = rows;
    const shown = pageSize ? rows.slice(0, state.visible) : rows;
    tbody.textContent = "";
    for (const r of shown) {{
      const tr = document.createElement("tr");
      if (rowClass) tr.className = rowClass(r);
      if (onRowClick) tr.addEventListener("click", () => onRowClick(r));
      for (const key of columns) {{
        const td = document.createElement("td");
        if (key === "status" || key === "level") {{
          const span = document.createElement("span");
          span.className = "badge " + key + "-" + r[key];
          span.textContent = r[key];
          td.appendChild(span);
        }} else if (key === "ics") {{
          if (r.ics && r.status !== "NO_DATA") {{
            const a = document.createElement("a");
            a.className = "ics-btn";
            a.href = r.ics;
            a.textContent = "⬇ ICS";
            a.download = "";
            a.addEventListener("click", evt => evt.stopPropagation());
            td.appendChild(a);
          }} else {{
            td.textContent = "—";
          }}
        }} else {{
          td.textContent = sksColumns.includes(key) ? Number(r[key]).toFixed(1) : r[key];
          if (centeredColumns.includes(key)) {{
            td.className = "num";
            const max = heatmapMax[key];
            if (max > 0) td.style.backgroundColor = heatmapColor((Number(r[key]) || 0) / max);
          }}
        }}
        tr.appendChild(td);
      }}
      tbody.appendChild(tr);
    }}
    if (countEl) {{
      countEl.textContent = pageSize
        ? shown.length + " shown / " + rows.length + " matching (" + data.length + " total)"
        : rows.length + " / " + data.length;
    }}
    if (moreButton) {{
      const remaining = rows.length - shown.length;
      moreButton.hidden = remaining <= 0;
      if (remaining > 0) {{
        moreButton.textContent = "Show " + Math.min(remaining, pageSize) + " more (" + remaining + " remaining)";
      }}
    }}
  }}

  // Collapses back to the first page -- call before render() on any filter
  // or sort change, so "show more" state doesn't carry over into a
  // different row set where it would no longer mean the same thing.
  function resetPage() {{ state.visible = initialVisible; }}
  function showMore() {{
    state.visible += pageSize;
    render();
  }}

  table.render = render;
  table.resetPage = resetPage;
  table.showMore = showMore;
  return table;
}}

const lecturerTable = makeTable({{
  data: LECTURERS,
  columns: LECTURER_COLUMNS,
  tbody: document.querySelector("#lecturer-table tbody"),
  filterInput: filterInput,
  countEl: document.getElementById("filter-count"),
  defaultKey: "dosen",
  defaultDir: 1,
  rowClass: r => "status-" + r.status + " lecturer-row",
  onRowClick: r => {{ classFilterInput.value = r.dosen; classTable.render(); }},
  centeredColumns: LECTURER_CENTERED,
  sksColumns: LECTURER_SKS,
}});

const CLASS_TABLE_FIRST_PAGE = 25;
const CLASS_TABLE_PAGE_SIZE = 100;

const classTable = makeTable({{
  data: CLASSES,
  columns: CLASS_COLUMNS,
  tbody: document.querySelector("#class-table tbody"),
  filterInput: classFilterInput,
  countEl: document.getElementById("class-filter-count"),
  defaultKey: "dosen",
  rowClass: r => "level-" + r.level,
  centeredColumns: CLASS_CENTERED,
  sksColumns: CLASS_SKS,
  firstPageSize: CLASS_TABLE_FIRST_PAGE,
  pageSize: CLASS_TABLE_PAGE_SIZE,
  moreButton: document.getElementById("class-show-more"),
}});

function wireSort(tableId, table, onRender, onBeforeRender) {{
  document.querySelectorAll("#" + tableId + " th[data-key]").forEach(th => {{
    th.addEventListener("click", () => {{
      const key = th.dataset.key;
      table.state.dir = (table.state.key === key) ? -table.state.dir : 1;
      table.state.key = key;
      if (onBeforeRender) onBeforeRender();
      table.render();
      if (onRender) onRender();
    }});
  }});
}}

// Round a positive value up to a "nice" axis maximum (1/2/5/10 x a power of
// ten), so the axis ticks land on clean numbers rather than the raw total.
function niceMax(v) {{
  if (v <= 0) return 10;
  const magnitude = Math.pow(10, Math.floor(Math.log10(v)));
  const residual = v / magnitude;
  let niceResidual;
  if (residual <= 1) niceResidual = 1;
  else if (residual <= 2) niceResidual = 2;
  else if (residual <= 5) niceResidual = 5;
  else niceResidual = 10;
  return niceResidual * magnitude;
}}

// Faculty-wide bar chart -- one stacked bar per level (scheduled +
// unscheduled) on a shared, quantitative SKS axis (not a 100%-stacked
// percentage), always the full CLASSES set (not filtered), so it stays a
// fixed reference regardless of Exhibit 1/3's current filter/sort. `est_credit
// - own_credit` is the unscheduled portion of a class's credit: 0 for a
// scheduled class (the two are equal), the full course SKS for one still
// awaiting a schedule -- see load.compute_lecturer_load. Track/axis widths
// are percentages of the 60%-width chart container, so this stays
// responsive; the row's own SKS value is a direct label (never just a
// tooltip), since a light categorical hue is illegible as text.
function renderTotalBar() {{
  const container = document.getElementById("level-total-bar");
  if (!container) return;
  const totals = {{}};
  LEVEL_SKS_FIELDS.forEach(([, label]) => {{ totals[label] = {{ scheduled: 0, unscheduled: 0 }}; }});
  for (const r of CLASSES) {{
    const t = totals[r.level];
    if (!t) continue; // OTHER isn't one of the four tracked levels
    const own = Number(r.own_credit) || 0;
    const est = Number(r.est_credit) || 0;
    t.scheduled += own;
    t.unscheduled += Math.max(est - own, 0);
  }}
  const domainMax = niceMax(Math.max(
    ...LEVEL_SKS_FIELDS.map(([, label]) => totals[label].scheduled + totals[label].unscheduled), 0
  ));
  container.textContent = "";

  const chart = document.createElement("div");
  chart.className = "level-chart";

  LEVEL_SKS_FIELDS.forEach(([, label]) => {{
    const {{ scheduled, unscheduled }} = totals[label];
    const row = document.createElement("div");
    row.className = "level-chart-row";

    const lab = document.createElement("div");
    lab.className = "level-chart-label";
    lab.textContent = label;
    row.appendChild(lab);

    const track = document.createElement("div");
    track.className = "level-chart-track";
    [0, 0.5, 1].forEach(f => {{
      const gridline = document.createElement("div");
      gridline.className = "level-chart-gridline";
      gridline.style.left = (f * 100) + "%";
      track.appendChild(gridline);
    }});
    const schedPct = domainMax > 0 ? (scheduled / domainMax) * 100 : 0;
    const unschedPct = domainMax > 0 ? (unscheduled / domainMax) * 100 : 0;
    const schedBar = document.createElement("div");
    schedBar.className = "level-chart-bar level-" + label;
    schedBar.style.left = "0%";
    schedBar.style.width = schedPct + "%";
    schedBar.title = label + " scheduled: " + scheduled.toFixed(1) + " SKS";
    if (unscheduled <= 0) schedBar.style.borderRadius = "0 4px 4px 0";
    track.appendChild(schedBar);
    if (unscheduled > 0) {{
      const unschedBar = document.createElement("div");
      unschedBar.className = "level-chart-bar level-" + label + " unscheduled-seg";
      unschedBar.style.left = schedPct + "%";
      unschedBar.style.width = unschedPct + "%";
      unschedBar.style.borderRadius = "0 4px 4px 0";
      unschedBar.title = label + " unscheduled: " + unscheduled.toFixed(1) + " SKS";
      track.appendChild(unschedBar);
    }}
    row.appendChild(track);

    const val = document.createElement("div");
    val.className = "level-chart-value";
    val.textContent = (scheduled + unscheduled).toFixed(1) + " SKS";
    row.appendChild(val);

    chart.appendChild(row);
  }});

  const axisRow = document.createElement("div");
  axisRow.className = "level-chart-axis-row";
  const spacer = document.createElement("div");
  spacer.className = "level-chart-axis-spacer";
  axisRow.appendChild(spacer);
  const axis = document.createElement("div");
  axis.className = "level-chart-axis";
  [0, 0.5, 1].forEach(f => {{
    const tick = document.createElement("span");
    tick.className = "tick";
    tick.style.left = (f * 100) + "%";
    tick.textContent = (domainMax * f).toFixed(0);
    axis.appendChild(tick);
  }});
  axisRow.appendChild(axis);
  chart.appendChild(axisRow);

  container.appendChild(chart);
}}

// Per-lecturer stacked bars: mirrors lecturerTable's current filter/sort
// (via its exposed `rows`) rather than a second independent filter, so this
// list and Exhibit 1's table never fall out of sync. Segment width is a
// quantitative share of a *fixed* scale (LECTURERS' max est_sks -- scheduled
// + unscheduled -- not each row's own total), so two lecturers' bars are
// directly comparable by length, not just by their internal S1/S2/S3/Profesi
// proportions -- and the scale stays put across filter/sort so a bar's
// length never shifts as you filter. Colors reuse the same `level-*`
// LEVEL_COLORS classes as every other exhibit -- table badges, cards, the
// Exhibit 2 total chart, and the network -- so a level's hue means the same
// thing everywhere (solid = scheduled, translucent = unscheduled, same as
// the total chart above).
//
// LECTURERS only carries each lecturer's *scheduled* per-level total
// (sks_s1..sks_profesi); the unscheduled split isn't in that summary, so
// it's derived here from CLASSES the same way the Exhibit 2 total chart
// derives it (est_credit - own_credit per row), grouped by dosen once up
// front rather than re-scanning CLASSES for every row.
const CLASS_LEVEL_BY_DOSEN = (() => {{
  const tracked = new Set(LEVEL_SKS_FIELDS.map(([, label]) => label));
  const byDosen = {{}};
  for (const r of CLASSES) {{
    if (!tracked.has(r.level)) continue; // OTHER isn't one of the four tracked levels
    const byLevel = byDosen[r.dosen] || (byDosen[r.dosen] = {{}});
    const t = byLevel[r.level] || (byLevel[r.level] = {{ scheduled: 0, unscheduled: 0 }});
    const own = Number(r.own_credit) || 0;
    const est = Number(r.est_credit) || 0;
    t.scheduled += own;
    t.unscheduled += Math.max(est - own, 0);
  }}
  return byDosen;
}})();

const LEVEL_BARS_DOMAIN_MAX = niceMax(
  Math.max(...LECTURERS.map(r => Number(r.est_sks) || 0), 0)
);

// Reference marks for the 12/16-SKS landmarks, in domain-% terms -- skipped
// individually if past the current chart's max so a landmark never renders
// off-scale. Drawn as a subtle vertical line on every row's own track (not
// one continuous overlay) so each lecturer's bar can be read against the
// same two landmarks at a glance, without implying a verdict.
function levelBarsRefMarks() {{
  return [OK_HIGH_SKS, MAX_SKS]
    .filter(v => LEVEL_BARS_DOMAIN_MAX > 0 && v > 0 && v <= LEVEL_BARS_DOMAIN_MAX)
    .map(v => ({{ value: v, pct: (v / LEVEL_BARS_DOMAIN_MAX) * 100 }}));
}}

function renderLevelBars() {{
  const container = document.getElementById("level-bars");
  if (!container) return;
  container.textContent = "";
  const refMarks = levelBarsRefMarks();

  const axisRow = document.createElement("div");
  axisRow.className = "level-bar-row axis-row";
  const axisLabel = document.createElement("div");
  axisLabel.className = "level-bar-label";
  axisRow.appendChild(axisLabel);
  const axis = document.createElement("div");
  axis.className = "level-chart-axis";
  [0, 0.5, 1].forEach(f => {{
    const tick = document.createElement("span");
    tick.className = "tick";
    tick.style.left = (f * 100) + "%";
    tick.textContent = (LEVEL_BARS_DOMAIN_MAX * f).toFixed(0) + (f === 1 ? " SKS" : "");
    axis.appendChild(tick);
  }});
  refMarks.forEach(({{ value, pct }}) => {{
    const tick = document.createElement("span");
    tick.className = "tick ref-tick";
    tick.style.left = pct + "%";
    tick.textContent = value.toFixed(0);
    axis.appendChild(tick);
  }});
  axisRow.appendChild(axis);
  container.appendChild(axisRow);

  for (const r of lecturerTable.rows) {{
    const row = document.createElement("div");
    row.className = "level-bar-row";
    row.addEventListener("click", () => {{ classFilterInput.value = r.dosen; classTable.render(); }});
    const label = document.createElement("div");
    label.className = "level-bar-label";
    label.textContent = r.dosen;
    row.appendChild(label);
    const track = document.createElement("div");
    track.className = "level-bar-track";
    const byLevel = CLASS_LEVEL_BY_DOSEN[r.dosen] || {{}};
    for (const [, label2] of LEVEL_SKS_FIELDS) {{
      const t = byLevel[label2] || {{ scheduled: 0, unscheduled: 0 }};
      const pct = v => (LEVEL_BARS_DOMAIN_MAX > 0 ? v / LEVEL_BARS_DOMAIN_MAX * 100 : 0);
      if (t.scheduled > 0) {{
        const seg = document.createElement("div");
        seg.className = "level-bar-segment level-" + label2;
        seg.style.width = pct(t.scheduled) + "%";
        seg.title = label2 + " scheduled: " + t.scheduled.toFixed(1) + " SKS";
        track.appendChild(seg);
      }}
      if (t.unscheduled > 0) {{
        const seg = document.createElement("div");
        seg.className = "level-bar-segment level-" + label2 + " unscheduled-seg";
        seg.style.width = pct(t.unscheduled) + "%";
        seg.title = label2 + " unscheduled: " + t.unscheduled.toFixed(1) + " SKS";
        track.appendChild(seg);
      }}
    }}
    refMarks.forEach(({{ pct }}) => {{
      const line = document.createElement("div");
      line.className = "level-bar-refline";
      line.style.left = pct + "%";
      track.appendChild(line);
    }});
    row.appendChild(track);
    container.appendChild(row);
  }}
}}

wireSort("lecturer-table", lecturerTable, renderLevelBars);
wireSort("class-table", classTable, null, () => classTable.resetPage());
filterInput.addEventListener("input", () => {{ lecturerTable.render(); renderLevelBars(); }});
classFilterInput.addEventListener("input", () => {{ classTable.resetPage(); classTable.render(); }});
document.getElementById("class-show-more").addEventListener("click", () => classTable.showMore());

lecturerTable.render();
classTable.render();
renderTotalBar();
renderLevelBars();

// --- Exhibit 4: shared-course network -------------------------------------
//
// A co-teaching *matrix*, not a node-link diagram: a live force simulation
// was tried first, but at this faculty's actual density (most lecturers
// co-teach with a large fraction of their colleagues -- see the caption)
// almost every node pulls on almost every other node, so the physics just
// settles into a dense, uninformative blob no matter how it's tuned. A
// matrix's readability doesn't degrade with density the way a node-link
// layout's does -- this is a well-established result in graph-drawing
// research (readability studies comparing the two consistently favor the
// matrix past a moderate edge density) -- and it's also simpler and fully
// static: no physics, no drag, no overlap to avoid, just a deterministic
// grid. Reuses heatmapColor() (the same sequential shading already used for
// the lecturer/class table cells) for one consistent "shade = magnitude"
// language across the dashboard.
// ``idSuffix`` picks which network's DOM elements to wire up (""  for the
// course-level network, "-kelas" for the class-section-level one -- see
// _network_section's matching id scheme); ``data`` is that network's
// {{nodes, edges}}; ``unitLabel`` (singular, e.g. "course"/"class section")
// drives this instance's tooltip/title wording.
function initNetwork(idSuffix, data, unitLabel) {{
  const head = document.getElementById("network" + idSuffix + "-matrix-head");
  const body = document.getElementById("network" + idSuffix + "-matrix-body");
  if (!head || !body || !data.nodes.length) return;

  const tooltip = document.getElementById("network" + idSuffix + "-tooltip");
  const canvas = document.querySelector("#network" + idSuffix + " .network-body");

  function unitWord(count) {{ return unitLabel + (count === 1 ? "" : "s"); }}
  function sharedText(weight) {{ return weight + " shared " + unitWord(weight); }}

  // Tooltip content is built from lecturer/course names embedded as JSON
  // data (not markup), so escape before using innerHTML -- same reasoning
  // as html.escape() on the Python side for static copy.
  function escapeHtml(s) {{
    return String(s).replace(/[&<>"']/g, c => ({{
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }})[c]);
  }}

  function showTooltip(evt, html) {{
    tooltip.innerHTML = html;
    tooltip.hidden = false;
    const rect = canvas.getBoundingClientRect();
    tooltip.style.left = (evt.clientX - rect.left + 12) + "px";
    tooltip.style.top = (evt.clientY - rect.top + 12) + "px";
  }}
  function hideTooltip() {{ tooltip.hidden = true; }}

  function filterToLecturer(node) {{
    filterInput.value = node.id;
    lecturerTable.render();
    renderLevelBars();
    document.getElementById("lecturers").scrollIntoView({{ behavior: "smooth" }});
  }}

  // Rows/columns are the same lecturer set in the same order -- already
  // sorted by count (desc) by build_network(), reused as-is.
  const nodes = data.nodes;
  const n = nodes.length;
  const indexById = new Map(nodes.map((node, i) => [node.id, i]));
  const matrix = Array.from({{ length: n }}, () => new Array(n).fill(null));
  for (const e of data.edges) {{
    const i = indexById.get(e.source), j = indexById.get(e.target);
    if (i == null || j == null) continue;
    matrix[i][j] = e;
    matrix[j][i] = e; // symmetric: co-teaching has no direction
  }}
  const maxWeight = data.edges.reduce((m, e) => Math.max(m, e.weight), 1);

  // Degree centrality (distinct co-teachers, not edge weight) drives node
  // color in the diagram below -- computed once from the full edge set, so
  // it doesn't shift as the threshold/search controls dim things in place.
  const degreeById = new Map(nodes.map(node => [node.id, 0]));
  for (const e of data.edges) {{
    degreeById.set(e.source, (degreeById.get(e.source) || 0) + 1);
    degreeById.set(e.target, (degreeById.get(e.target) || 0) + 1);
  }}
  const maxDegree = Math.max(1, ...nodes.map(node => degreeById.get(node.id) || 0));

  const corner = document.createElement("th");
  corner.className = "corner";
  head.appendChild(corner);
  const colEls = nodes.map(node => {{
    const th = document.createElement("th");
    th.className = "col-head";
    th.textContent = node.id;
    th.title = node.id + " — " + node.count + " " + unitWord(node.count);
    head.appendChild(th);
    return th;
  }});

  const rowHeadEls = [];
  const cellEls = []; // el/i/j/edge per cell
  for (let i = 0; i < n; i++) {{
    const node = nodes[i];
    const tr = document.createElement("tr");
    const rowHead = document.createElement("th");
    rowHead.className = "row-head";
    rowHead.textContent = node.id;
    rowHead.title = node.id + " — " + node.count + " " + unitWord(node.count);
    rowHead.addEventListener("click", () => filterToLecturer(node));
    tr.appendChild(rowHead);
    rowHeadEls.push(rowHead);

    for (let j = 0; j < n; j++) {{
      const td = document.createElement("td");
      td.className = "cell";
      if (i === j) {{
        td.classList.add("diagonal");
      }} else {{
        const edge = matrix[i][j];
        if (edge) {{
          td.addEventListener("mouseenter", evt => {{
            if (!td.classList.contains("has-edge")) return; // below the current threshold
            showTooltip(evt,
              "<strong>" + escapeHtml(nodes[i].id) + " ↔ " + escapeHtml(nodes[j].id) + "</strong><br>" +
              sharedText(edge.weight) + ": " +
              escapeHtml(edge.courses.join(", ")));
          }});
          td.addEventListener("mouseleave", hideTooltip);
          td.addEventListener("click", () => {{
            if (td.classList.contains("has-edge")) filterToLecturer(nodes[i]);
          }});
        }}
      }}
      tr.appendChild(td);
      cellEls.push({{ el: td, i, j, edge: matrix[i][j] }});
    }}
    body.appendChild(tr);
  }}

  // ---- Diagram: a one-shot layout, not a running simulation. Positions are
  // computed once (a standard Fruchterman-Reingold pass, then several
  // collision-resolution passes with generous padding so nodes always have
  // visible breathing room) and then held fixed -- dragging only ever moves
  // the one node being dragged, never re-simulates the graph, and releasing
  // it springs *that node* back to its resting spot rather than leaving it
  // wherever it was dropped.
  const svg = document.getElementById("network" + idSuffix + "-svg");
  const diagramNodeEls = [];
  const diagramEdgeEls = [];

  if (svg) {{
    const svgNS = "http://www.w3.org/2000/svg";
    const W = 960, H = 700, PAD = 40;
    // Sized by scheduled SKS (each lecturer's actual teaching load) rather
    // than by co-teaching count, so the diagram visually tracks the same
    // "how loaded is this person" question as Exhibit 1.
    const maxSks = nodes.reduce((m, node) => Math.max(m, node.sks || 0), 0) || 1;
    // Wider min/max spread than a plain sqrt(share) encoding so the smallest
    // and largest loads read as visibly different sizes at a glance, not
    // just on close inspection.
    const nodeRadius = sks => 4 + Math.sqrt(Math.max(sks, 0) / maxSks) * 28;
    const radiusById = new Map(nodes.map(node => [node.id, nodeRadius(node.sks || 0)]));

    const home = {{}};
    nodes.forEach((node, i) => {{
      const angle = (2 * Math.PI * i) / n;
      const r = Math.min(W, H) / 2 - PAD - 20;
      home[node.id] = {{ x: W / 2 + r * Math.cos(angle), y: H / 2 + r * Math.sin(angle) }};
    }});
    const k = Math.sqrt((W * H) / Math.max(n, 1)) * 1.3; // larger than a typical FR `k` -- more breathing room
    const ITER = 400;
    for (let iter = 0; iter < ITER; iter++) {{
      const temp = 1 - iter / ITER;
      const disp = {{}};
      nodes.forEach(node => disp[node.id] = {{ x: 0, y: 0 }});
      for (let i = 0; i < n; i++) {{
        for (let j = i + 1; j < n; j++) {{
          const a = nodes[i], b = nodes[j];
          let dx = home[a.id].x - home[b.id].x;
          let dy = home[a.id].y - home[b.id].y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
          const force = (k * k) / dist;
          dx = (dx / dist) * force; dy = (dy / dist) * force;
          disp[a.id].x += dx; disp[a.id].y += dy;
          disp[b.id].x -= dx; disp[b.id].y -= dy;
        }}
      }}
      for (const e of data.edges) {{
        const a = home[e.source], b = home[e.target];
        if (!a || !b) continue;
        let dx = a.x - b.x, dy = a.y - b.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const force = (dist * dist) / k;
        dx = (dx / dist) * force; dy = (dy / dist) * force;
        disp[e.source].x -= dx; disp[e.source].y -= dy;
        disp[e.target].x += dx; disp[e.target].y += dy;
      }}
      nodes.forEach(node => {{
        const p = home[node.id];
        const d = disp[node.id];
        const dist = Math.sqrt(d.x * d.x + d.y * d.y) || 0.01;
        const cap = 40 * temp + 1;
        const limited = Math.min(dist, cap);
        p.x += (d.x / dist) * limited;
        p.y += (d.y / dist) * limited;
        p.x += (W / 2 - p.x) * 0.01;
        p.y += (H / 2 - p.y) * 0.01;
        p.x = Math.max(PAD, Math.min(W - PAD, p.x));
        p.y = Math.max(PAD, Math.min(H - PAD, p.y));
      }});
    }}
    // Minimum gap is between node *edges*, not centers, so it scales with
    // each pair's actual radii -- "enough space" regardless of node size.
    const SPACING_PAD = 20;
    for (let pass = 0; pass < 10; pass++) {{
      for (let i = 0; i < n; i++) {{
        for (let j = i + 1; j < n; j++) {{
          const a = nodes[i], b = nodes[j];
          const pa = home[a.id], pb = home[b.id];
          const dx = pb.x - pa.x, dy = pb.y - pa.y;
          const minDist = radiusById.get(a.id) + radiusById.get(b.id) + SPACING_PAD;
          const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
          if (dist < minDist) {{
            const overlap = (minDist - dist) / 2;
            const ux = dx / dist, uy = dy / dist;
            pa.x -= ux * overlap; pa.y -= uy * overlap;
            pb.x += ux * overlap; pb.y += uy * overlap;
            pa.x = Math.max(PAD, Math.min(W - PAD, pa.x));
            pa.y = Math.max(PAD, Math.min(H - PAD, pa.y));
            pb.x = Math.max(PAD, Math.min(W - PAD, pb.x));
            pb.y = Math.max(PAD, Math.min(H - PAD, pb.y));
          }}
        }}
      }}
    }}

    const diagramStates = nodes.map(node => ({{
      node, home: home[node.id], x: home[node.id].x, y: home[node.id].y,
      vx: 0, vy: 0, radius: radiusById.get(node.id), animId: null, edges: [],
    }}));
    const stateById = new Map(diagramStates.map(st => [st.node.id, st]));

    for (const e of data.edges) {{
      const a = stateById.get(e.source), b = stateById.get(e.target);
      if (!a || !b) continue;
      const line = document.createElementNS(svgNS, "line");
      line.setAttribute("x1", a.x); line.setAttribute("y1", a.y);
      line.setAttribute("x2", b.x); line.setAttribute("y2", b.y);
      line.setAttribute("stroke-width", Math.min(1 + e.weight * 1.2, 6));
      line.classList.add("network-edge");
      line.addEventListener("mouseenter", evt => showTooltip(evt,
        "<strong>" + escapeHtml(e.source) + " ↔ " + escapeHtml(e.target) + "</strong><br>" +
        sharedText(e.weight) + ": " + escapeHtml(e.courses.join(", "))));
      line.addEventListener("mouseleave", hideTooltip);
      svg.appendChild(line);
      const rec = {{ el: line, edge: e, a, b }};
      diagramEdgeEls.push(rec);
      a.edges.push(rec); b.edges.push(rec);
    }}

    function positionNode(st) {{
      st.el.setAttribute("cx", st.x);
      st.el.setAttribute("cy", st.y);
      for (const rec of st.edges) {{
        rec.el.setAttribute("x1", rec.a.x); rec.el.setAttribute("y1", rec.a.y);
        rec.el.setAttribute("x2", rec.b.x); rec.el.setAttribute("y2", rec.b.y);
      }}
    }}

    for (const st of diagramStates) {{
      const circle = document.createElementNS(svgNS, "circle");
      circle.setAttribute("cx", st.x);
      circle.setAttribute("cy", st.y);
      circle.setAttribute("r", st.radius);
      circle.classList.add("node-dot");
      const degree = degreeById.get(st.node.id) || 0;
      circle.style.fill = nodeColor(maxDegree > 0 ? degree / maxDegree : 0);
      const connWord = degree === 1 ? "connection" : "connections";
      const title = document.createElementNS(svgNS, "title");
      title.textContent = st.node.id + " — " + (st.node.sks || 0).toFixed(1) + " scheduled SKS, " +
        st.node.count + " " + unitWord(st.node.count) + " (" + st.node.level + "), " +
        degree + " co-teaching " + connWord;
      circle.appendChild(title);
      circle.addEventListener("mouseenter", evt => showTooltip(evt,
        "<strong>" + escapeHtml(st.node.id) + "</strong><br>" + (st.node.sks || 0).toFixed(1) +
        " scheduled SKS · " + st.node.count + " " + unitWord(st.node.count) + " · " +
        escapeHtml(st.node.level) + " · " + degree + " " + connWord));
      circle.addEventListener("mouseleave", hideTooltip);
      svg.appendChild(circle);
      st.el = circle;
      diagramNodeEls.push({{ el: circle, node: st.node, st }});
    }}

    // Pointer directly drives the dragged node; every other node stays
    // exactly where the layout put it -- no graph-wide re-simulation.
    let dragging = null;
    let dragMoved = false;
    const SPRING_K = 0.12, DAMPING = 0.72;

    function toSvgPoint(evt) {{
      try {{
        const pt = svg.createSVGPoint();
        pt.x = evt.clientX;
        pt.y = evt.clientY;
        const ctm = svg.getScreenCTM();
        if (ctm) return pt.matrixTransform(ctm.inverse());
      }} catch (err) {{ /* fall through to the bounding-rect approximation */ }}
      const rect = svg.getBoundingClientRect();
      const scaleX = W / (rect.width || W);
      const scaleY = H / (rect.height || H);
      return {{ x: (evt.clientX - rect.left) * scaleX, y: (evt.clientY - rect.top) * scaleY }};
    }}

    // A small, bounded spring animation that eases *this one node* back to
    // its resting spot on release -- not a simulation of the whole graph,
    // just a return trip, so it starts and stops with the drag.
    function springBack(st) {{
      if (st.animId != null) cancelAnimationFrame(st.animId);
      st.vx = 0; st.vy = 0;
      function step() {{
        const dx = st.home.x - st.x, dy = st.home.y - st.y;
        st.vx = (st.vx + dx * SPRING_K) * DAMPING;
        st.vy = (st.vy + dy * SPRING_K) * DAMPING;
        st.x += st.vx; st.y += st.vy;
        const settled = Math.abs(dx) < 0.4 && Math.abs(dy) < 0.4 &&
          Math.abs(st.vx) < 0.05 && Math.abs(st.vy) < 0.05;
        if (settled) {{
          st.x = st.home.x; st.y = st.home.y;
          positionNode(st);
          st.animId = null;
          return;
        }}
        positionNode(st);
        st.animId = requestAnimationFrame(step);
      }}
      st.animId = requestAnimationFrame(step);
    }}

    diagramNodeEls.forEach(({{ el, st }}) => {{
      el.addEventListener("pointerdown", evt => {{
        if (st.animId != null) {{ cancelAnimationFrame(st.animId); st.animId = null; }}
        dragging = st;
        dragMoved = false;
        // Best-effort: dragging still works via the svg-level move/up
        // listeners below if pointer capture on an SVG element throws.
        try {{ el.setPointerCapture(evt.pointerId); }} catch (err) {{ /* unsupported */ }}
      }});
    }});
    svg.addEventListener("pointermove", evt => {{
      if (!dragging) return;
      dragMoved = true;
      const p = toSvgPoint(evt);
      dragging.x = Math.max(PAD, Math.min(W - PAD, p.x));
      dragging.y = Math.max(PAD, Math.min(H - PAD, p.y));
      positionNode(dragging);
    }});
    svg.addEventListener("pointerup", () => {{
      if (dragging) springBack(dragging);
      dragging = null;
    }});

    diagramNodeEls.forEach(({{ el, node }}) => {{
      el.addEventListener("click", () => {{
        if (dragMoved) return; // a drag, not a click -- don't also filter
        filterToLecturer(node);
      }});
    }});
  }}

  const minWeightSelect = document.getElementById("network" + idSuffix + "-min-weight");
  const searchInput = document.getElementById("network" + idSuffix + "-filter");
  const countEl = document.getElementById("network" + idSuffix + "-count");

  function update() {{
    const minWeight = Number(minWeightSelect.value);
    const q = searchInput.value.trim().toLowerCase();
    let matchedIdx = null;
    if (q) {{
      matchedIdx = new Set();
      nodes.forEach((node, i) => {{ if (node.id.toLowerCase().includes(q)) matchedIdx.add(i); }});
    }}

    let visibleLinks = 0;
    for (const {{ el, i, j, edge }} of cellEls) {{
      if (i === j) continue;
      const passesWeight = !!edge && edge.weight >= minWeight;
      el.style.backgroundColor = passesWeight ? heatmapColor(edge.weight / maxWeight) : "";
      el.classList.toggle("has-edge", passesWeight);
      const searchOk = !matchedIdx || matchedIdx.has(i) || matchedIdx.has(j);
      el.classList.toggle("dimmed", !searchOk);
      if (passesWeight && searchOk) visibleLinks++;
    }}
    rowHeadEls.forEach((el, i) => el.classList.toggle("highlight", !!matchedIdx && matchedIdx.has(i)));
    colEls.forEach((el, i) => el.classList.toggle("highlight", !!matchedIdx && matchedIdx.has(i)));

    // Same threshold/search state, applied to the diagram too -- filtering
    // only ever toggles this class, never touches a node's position. An
    // edge stays visible if *either* end matches (mirrors the matrix: a
    // matched lecturer's whole row/column of connections shows, not just
    // pairs where both people match); a node stays visible if it's matched
    // or the far end of one of those now-visible edges, so a highlighted
    // edge never points at a dimmed node.
    let diagramMatchedIdx = matchedIdx;
    if (matchedIdx) {{
      diagramMatchedIdx = new Set(matchedIdx);
      for (const e of data.edges) {{
        if (e.weight < minWeight) continue;
        const i = indexById.get(e.source), j = indexById.get(e.target);
        if (matchedIdx.has(i)) diagramMatchedIdx.add(j);
        if (matchedIdx.has(j)) diagramMatchedIdx.add(i);
      }}
    }}
    for (const {{ el, edge }} of diagramEdgeEls) {{
      const i = indexById.get(edge.source), j = indexById.get(edge.target);
      const searchOk = !matchedIdx || matchedIdx.has(i) || matchedIdx.has(j);
      el.classList.toggle("dimmed", !(edge.weight >= minWeight && searchOk));
    }}
    for (const {{ el, node }} of diagramNodeEls) {{
      const i = indexById.get(node.id);
      el.classList.toggle("dimmed", !(!diagramMatchedIdx || diagramMatchedIdx.has(i)));
    }}

    if (countEl) {{
      // Each undirected link occupies two symmetric cells (i,j) and (j,i).
      countEl.textContent = n + " lecturers · " + (visibleLinks / 2) + " links shown";
    }}
  }}

  minWeightSelect.addEventListener("change", update);
  searchInput.addEventListener("input", update);
  update();
}}

initNetwork("", NETWORK, "course");
initNetwork("-kelas", NETWORK_KELAS, "class section");
</script>
</body>
</html>
"""


def write_dashboard(
    result: dict,
    outdir=".",
    network: dict | None = None,
    class_network: dict | None = None,
    calendar_dir: str | None = DEFAULT_CALENDAR_DIR,
    filename: str = DASHBOARD_FILENAME,
) -> Path:
    """Write the dashboard HTML to ``outdir/<filename>`` (default: index.html)."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / filename
    path.write_text(
        render_dashboard(result, network, class_network, calendar_dir=calendar_dir),
        encoding="utf-8",
    )
    return path
