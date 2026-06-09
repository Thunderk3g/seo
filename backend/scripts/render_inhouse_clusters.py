"""Render the in-house cross-page content-segregation report.

Reads backend/data/inhouse_content/clusters.json (authored by the Claude-Code
content segmenter — no embeddings, no env LLM) and writes report.html next to
it. Bajaj-blue palette; GSC-style layout only.

    python backend/scripts/render_inhouse_clusters.py
"""
import json
import html
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "inhouse_content"
SRC = DATA / "clusters.json"
OUT = DATA / "report.html"

DCLASS = {0: "d0", 1: "d1", 2: "d2", 3: "d3"}
DLABEL = {0: "—", 1: "1", 2: "2", 3: "3"}


def esc(s):
    return html.escape(str(s or ""))


def main():
    d = json.loads(SRC.read_text(encoding="utf-8"))
    pages = d["pages"]
    clusters = d["clusters"]
    pkeys = [p["key"] for p in pages]

    spotlights = [c for c in clusters if c.get("cross_page_spotlight")]
    warnings = [c for c in clusters if c.get("is_warning")]

    # coverage: how many pages cover each cluster at depth>=1
    def covered(c):
        return sum(1 for k in pkeys if c["depth"].get(k, 0) >= 1)

    parts = []
    parts.append(f"""<!doctype html><html><head><meta charset='utf-8'>
<title>In-House Content Segregation — {esc(d['brand'])}</title><style>
*{{box-sizing:border-box}} body{{font-family:Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#0f172a;max-width:1180px;margin:0 auto;padding:16px 26px;line-height:1.5}}
h1{{font-size:24px;border-bottom:3px solid #1e3a8a;padding-bottom:6px;color:#1e3a8a}}
h2{{font-size:18px;margin-top:30px;border-bottom:1px solid #cbd5e1;padding-bottom:4px;color:#1e3a8a}}
.kpis{{display:flex;flex-wrap:wrap;gap:12px;margin:14px 0}}
.kpi{{flex:1 1 150px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:12px 14px}}
.kpi .n{{font-size:24px;font-weight:700;color:#1e3a8a}}.kpi .l{{font-size:12px;color:#475569}}
table{{border-collapse:collapse;width:100%;font-size:12.5px;margin:6px 0}}
th,td{{border:1px solid #cbd5e1;padding:5px 8px;text-align:left;vertical-align:top}}
th{{background:#eef2ff;color:#1e3a8a}}.matrix td{{text-align:center;font-weight:700}}
.matrix td.topic{{text-align:left;font-weight:600}}
.d0{{background:#f1f5f9;color:#94a3b8}}.d1{{background:#fef3c7}}.d2{{background:#dbeafe}}.d3{{background:#dcfce7;color:#166534}}
.cl{{border:1px solid #e2e8f0;border-radius:10px;padding:10px 14px;margin:12px 0;background:#fbfdff}}
.cl h3{{color:#1e3a8a;margin:0 0 6px}}
.spot{{border-left:4px solid #1e3a8a;background:#eff6ff}}
.warn{{border-left:4px solid #f59e0b;background:#fffbeb}}
.ev{{font-size:12px;color:#334155;margin:2px 0}}
.ev b{{color:#1e3a8a}}
.badge{{display:inline-block;font-size:10px;font-weight:700;padding:1px 7px;border-radius:5px;margin-left:6px;background:#dbeafe;color:#1e40af}}
.mono{{font-family:monospace;font-size:11px}}
ul.ins li{{margin:5px 0;font-size:13.5px}}
small{{color:#64748b}}
</style></head><body>""")

    parts.append(f"<h1>In-House Content Segregation — {esc(d['brand'])}</h1>")
    parts.append(f"<small>{esc(d['generated_for'])} · pages analysed: {len(pages)} · "
                 f"topic clusters: {len(clusters)}</small>")

    # KPIs
    total_words = sum(p["words"] for p in pages)
    parts.append("<div class='kpis'>")
    for n, l in [(len(pages), "Pages"), (len(clusters), "Topic clusters"),
                 (len(spotlights), "Cross-page topics"),
                 (f"{total_words:,}", "Total words"),
                 (len(warnings), "Duplicate-content flags")]:
        parts.append(f"<div class='kpi'><div class='n'>{n}</div><div class='l'>{esc(l)}</div></div>")
    parts.append("</div>")

    # Matrix
    parts.append("<h2>Cluster coverage map</h2>"
                 "<small>Depth per page: <b>3</b> pillar · <b>2</b> standard · <b>1</b> mention · <b>—</b> absent. "
                 "Read a row to see every page that covers a topic and how deeply.</small>")
    parts.append("<table class='matrix'><thead><tr><th>Topic cluster</th><th>Pages</th>")
    for p in pages:
        parts.append(f"<th>{esc(p['name'])}<br><small>{p['words']//1000}k</small></th>")
    parts.append("</tr></thead><tbody>")
    for c in clusters:
        nm = esc(c["name"])
        if c.get("cross_page_spotlight"):
            nm += "<span class='badge'>cross-page</span>"
        parts.append(f"<tr><td class='topic'>{nm}</td><td style='text-align:center'>{covered(c)}/{len(pages)}</td>")
        for k in pkeys:
            v = c["depth"].get(k, 0)
            parts.append(f"<td class='{DCLASS[v]}'>{DLABEL[v]}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")

    # Spotlights (the user's examples: ULIP + tax spread across pages)
    parts.append("<h2>Cross-page spotlights</h2>")
    for c in spotlights + warnings:
        cls = "spot" if c.get("cross_page_spotlight") else "warn"
        parts.append(f"<div class='cl {cls}'><h3>{esc(c['name'])} — on {covered(c)}/{len(pages)} pages</h3>")
        # pages sorted by depth desc
        ranked = sorted(pages, key=lambda p: -c["depth"].get(p["key"], 0))
        for p in ranked:
            v = c["depth"].get(p["key"], 0)
            if v == 0:
                continue
            ev = c.get("evidence", {}).get(p["key"], [])
            evs = ("; ".join(esc(e) for e in ev)) if ev else "(brief mention)"
            parts.append(f"<div class='ev'><b>[depth {v}] {esc(p['name'])}</b> — {evs} "
                         f"<span class='mono'>{esc(p['url'])}</span></div>")
        parts.append("</div>")

    # All clusters detail
    parts.append("<h2>All topic clusters — who covers what</h2>")
    for c in clusters:
        if c.get("cross_page_spotlight") or c.get("is_warning"):
            continue
        parts.append(f"<div class='cl'><h3>{esc(c['name'])} — {covered(c)}/{len(pages)} pages</h3>")
        ranked = sorted(pages, key=lambda p: -c["depth"].get(p["key"], 0))
        for p in ranked:
            v = c["depth"].get(p["key"], 0)
            if v == 0:
                continue
            ev = c.get("evidence", {}).get(p["key"], [])
            evs = ("; ".join(esc(e) for e in ev)) if ev else "(brief mention)"
            parts.append(f"<div class='ev'><b>[depth {v}] {esc(p['name'])}</b> — {evs}</div>")
        parts.append("</div>")

    # Insights
    parts.append("<h2>Key findings</h2><ul class='ins'>")
    for i in d.get("insights", []):
        parts.append(f"<li>{esc(i)}</li>")
    parts.append("</ul>")

    parts.append("</body></html>")
    OUT.write_text("".join(parts), encoding="utf-8")
    print(f"wrote {OUT}  ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
