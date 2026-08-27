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

DASHBOARD_FILENAME = "load_dashboard.html"

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

LEVEL_COLORS = {
    "S1": "#2b4a73",   # steel navy
    "S2": "#5c3a5c",   # plum
    "S3": "#2f6b63",   # teal
    "PROFESI": "#8a4a2c",  # rust
    "OTHER": "#6b6357",    # warm gray-brown
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
    ("is_s3", "S3", "text"),
]

LECTURERS_CAPTION = (
    "Ranked by Scheduled SKS &mdash; the credit already booked on a room and "
    "time slot this semester. Click a name to filter the class list below to "
    "that lecturer; click any column heading to sort."
)
LEVELS_CAPTION = (
    "Class sessions grouped by program level, detected from each course's "
    "rumpun tag. Click a tile to filter the class list to that level."
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
    for row in result["classes"]:
        t = totals.setdefault(row["level"], {"n": 0, "sks": 0.0})
        t["n"] += 1
        t["sks"] += row["own_credit"]
    cards = []
    for level in PROGRAM_LEVELS:
        t = totals[level]
        cards.append(
            f'<div class="card level-{level}" '
            f'onclick="classFilterInput.value=\'{level}\';classTable.render();">'
            f'<div class="card-count">{t["n"]}</div>'
            f'<div class="card-label">{_e(level)} &middot; {t["sks"]:g} SKS</div></div>'
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
    counts = {status: 0 for status in STATUS_ORDER}
    for row in result["lecturers"]:
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    cards = [
        f'<div class="card" data-status="" onclick="filterInput.value=\'\';lecturerTable.render();">'
        f'<div class="card-count">{len(result["lecturers"])}</div>'
        f'<div class="card-label">Total lecturers</div></div>',
        f'<div class="card" data-status="" onclick="document.getElementById(\'warnings\').scrollIntoView();">'
        f'<div class="card-count">{len(result["warnings"])}</div>'
        f'<div class="card-label">Warnings</div></div>',
    ]
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


def _methodology_html(warn: float, ok_min: float, ok_high: float, max_sks: float) -> str:
    """A short prose explainer for how the numbers/bands in this report are derived."""
    return f"""
<p>This report counts each lecturer's <strong>own class sessions only</strong>:
on a co-taught class, credit belongs to whichever lecturer actually leads a
given session, so shared classes are never double-counted.</p>
<p><strong>Scheduled SKS</strong> is the credit already booked on a room and
time slot this semester &mdash; each class contributes its course credit
(SKS) scaled by the share of the semester's {MEETINGS_PER_SEMESTER} meetings
the lecturer actually teaches, and a class with no booked schedule yet
contributes nothing. <strong>Est. SKS</strong> closes that gap by adding the
full course credit for classes still awaiting a schedule, estimating the
lecturer's eventual load once every class is booked; the difference between
the two &mdash; shown as <strong>SKS Unsched.</strong> &mdash; is exposure
still sitting in unscheduled classes.</p>
<p>Status bands are drawn on Scheduled SKS: below {warn:g} is
<strong>WARNING</strong>; {warn:g}&ndash;{ok_min:g} is
<strong>UNDERLOADED</strong>; {ok_min:g}&ndash;{ok_high:g} is
<strong>OK</strong> &mdash; the ideal <em>teaching-only</em> range, since the
official {ok_high:g}-SKS minimum load already folds in research;
{ok_high:g}&ndash;{max_sks:g} is <strong>ABOVE</strong>; and past
{max_sks:g} is <strong>OVERLOADED</strong>, the hard ceiling that itself
still has to cover research, community service and supporting duties on top
of teaching.</p>
<p>Program level (S1/S2/S3/Profesi) is read from each course's rumpun tag
(a doctoral course code prefix is also recognized as a fallback); S3 credit
is broken out on its own since doctoral supervision carries different
expectations than undergraduate or master's teaching.</p>
""".strip()


def render_dashboard(result: dict) -> str:
    """Render the full aggregate_loads() result into one HTML document."""
    semester = _e(result.get("semester", ""))
    warn = result.get("warn_sks", WARN_SKS)
    ok_min = result.get("min_sks", 8.0)
    ok_high = result.get("ok_high", OK_HIGH_SKS)
    max_sks = result.get("max_sks", 16.0)
    generated = datetime.now().isoformat(timespec="seconds")

    lecturer_cols_json = _json_for_script([key for key, _, _ in LECTURER_COLUMNS])
    class_cols_json = _json_for_script([key for key, _, _ in CLASS_COLUMNS])
    lecturer_centered_json = _json_for_script(
        [key for key, _, kind in LECTURER_COLUMNS if kind in ("num", "sks")]
    )
    class_centered_json = _json_for_script(
        [key for key, _, kind in CLASS_COLUMNS if kind in ("num", "sks")]
    )
    lecturer_sks_json = _json_for_script([key for key, _, kind in LECTURER_COLUMNS if kind == "sks"])
    class_sks_json = _json_for_script([key for key, _, kind in CLASS_COLUMNS if kind == "sks"])
    lecturers_json = _json_for_script(result["lecturers"])
    classes_json = _json_for_script(result["classes"])
    methodology_html = _methodology_html(warn, ok_min, ok_high, max_sks)

    def _th(key, label, kind):
        cls = ' class="num"' if kind in ("num", "sks") else ""
        return f'<th data-key="{key}"{cls}>{_e(label)}</th>'

    lecturer_headers = "\n".join(_th(key, label, kind) for key, label, kind in LECTURER_COLUMNS)
    class_headers = "\n".join(_th(key, label, kind) for key, label, kind in CLASS_COLUMNS)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Teaching Load Report &mdash; Semester {semester}</title>
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
</style>
</head>
<body>
<div class="container">
<header>
  <p class="kicker">Fakultas Biologi UGM &middot; SIMASTER</p>
  <h1>Teaching Load Report</h1>
  <p class="dek">Semester {semester} &middot; generated {generated}</p>
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
  <input id="filter" type="search" placeholder="Filter by lecturer or status...">
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
</section>

<section id="warnings">
  <h2><span class="exhibit-tag">Exhibit 4</span> Warnings ({len(result["warnings"])})</h2>
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

function columnMaxes(data, keys) {{
  const maxes = {{}};
  for (const key of keys) {{
    maxes[key] = data.reduce((m, r) => Math.max(m, Number(r[key]) || 0), 0);
  }}
  return maxes;
}}

function makeTable(opts) {{
  const {{
    data, columns, tbody, filterInput, countEl, defaultKey, rowClass, onRowClick,
    centeredColumns = [], sksColumns = [],
  }} = opts;
  const state = {{ key: defaultKey, dir: -1 }};
  const heatmapMax = columnMaxes(data, centeredColumns);

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
    tbody.textContent = "";
    for (const r of rows) {{
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
    if (countEl) countEl.textContent = rows.length + " / " + data.length;
  }}

  return {{ state, render }};
}}

const lecturerTable = makeTable({{
  data: LECTURERS,
  columns: LECTURER_COLUMNS,
  tbody: document.querySelector("#lecturer-table tbody"),
  filterInput: filterInput,
  countEl: document.getElementById("filter-count"),
  defaultKey: "scheduled_sks",
  rowClass: r => "status-" + r.status + " lecturer-row",
  onRowClick: r => {{ classFilterInput.value = r.dosen; classTable.render(); }},
  centeredColumns: LECTURER_CENTERED,
  sksColumns: LECTURER_SKS,
}});

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
}});

function wireSort(tableId, table) {{
  document.querySelectorAll("#" + tableId + " th[data-key]").forEach(th => {{
    th.addEventListener("click", () => {{
      const key = th.dataset.key;
      table.state.dir = (table.state.key === key) ? -table.state.dir : 1;
      table.state.key = key;
      table.render();
    }});
  }});
}}

wireSort("lecturer-table", lecturerTable);
wireSort("class-table", classTable);
filterInput.addEventListener("input", () => lecturerTable.render());
classFilterInput.addEventListener("input", () => classTable.render());

lecturerTable.render();
classTable.render();
</script>
</body>
</html>
"""


def write_dashboard(result: dict, outdir=".") -> Path:
    """Write the dashboard HTML to ``outdir/load_dashboard.html``."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / DASHBOARD_FILENAME
    path.write_text(render_dashboard(result), encoding="utf-8")
    return path
