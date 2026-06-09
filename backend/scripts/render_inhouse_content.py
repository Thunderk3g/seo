"""Render the in-house content-segregation report WITH FULL CONTENT.

For each topic cluster (Term, ULIP, Tax, ...) it pulls the actual page
sections that belong to that topic — across every Bajaj page — and renders
them as collapsible <details> blocks (click the arrow to open), showing the
heading outline + the real section text. Mirrors the look of the
content-gap report's "Page structure" panel. Bajaj-blue palette.

Inputs (both in backend/data/inhouse_content/):
  corpus_full.json  — every page's sections with FULL text
  clusters_v2.json  — Claude-Code section→cluster assignment

    python backend/scripts/render_inhouse_content.py
"""
import json
import html
import re
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "inhouse_content"
OUT = DATA / "report_content.html"


def esc(s):
    return html.escape(str(s or ""))


def norm(s):
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def main():
    corpus = json.loads((DATA / "corpus_full.json").read_text(encoding="utf-8"))
    spec = json.loads((DATA / "clusters_v2.json").read_text(encoding="utf-8"))
    by_key = {p["key"]: p for p in corpus}

    def sections_for(member):
        """Return the list of sections of a page that belong to a cluster."""
        page = by_key.get(member["page"])
        if not page:
            return []
        if member.get("mode") == "all":
            return page["sections"]
        wants = [norm(h) for h in member.get("headings", [])]
        out = []
        for s in page["sections"]:
            hn = norm(s["h"])
            if any(w in hn or hn in w for w in wants):
                out.append(s)
        return out

    P = []
    P.append(f"""<!doctype html><html><head><meta charset='utf-8'>
<title>In-House Content by Topic — {esc(spec['brand'])}</title><style>
*{{box-sizing:border-box}} body{{font-family:Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#0f172a;max-width:1100px;margin:0 auto;padding:16px 26px;line-height:1.55}}
h1{{font-size:24px;border-bottom:3px solid #1e3a8a;padding-bottom:6px;color:#1e3a8a}}
h2.cluster{{font-size:19px;margin-top:34px;border-bottom:2px solid #1e3a8a;padding-bottom:4px;color:#1e3a8a}}
.intro{{font-size:13px;color:#475569;margin:4px 0 10px}}
.toc{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;font-size:13px;margin:12px 0}}
.toc a{{color:#1e40af;margin-right:14px;text-decoration:none;display:inline-block;margin-bottom:4px}}
details.page{{border:1px solid #e2e8f0;border-left:4px solid #1e3a8a;border-radius:8px;padding:8px 12px;margin:8px 0;background:#fbfdff}}
details.page>summary{{cursor:pointer;font-weight:700;color:#1e3a8a;font-size:14px}}
details.page>summary small{{color:#64748b;font-weight:400;margin-left:8px}}
.srow{{margin:8px 0 10px;border-left:2px solid #e2e8f0;padding-left:10px}}
.tag{{display:inline-block;min-width:26px;font-family:monospace;font-size:10px;font-weight:700;color:#fff;background:#1e3a8a;border-radius:4px;padding:1px 5px;text-align:center;margin-right:6px}}
.sh{{font-weight:700;color:#0f172a}}
.sc{{color:#334155;margin:3px 0 0;white-space:pre-wrap;font-size:12.5px}}
.s1 .sh{{font-size:16px}}.s2{{margin-left:14px}}.s3{{margin-left:30px}}.s0 .sh{{font-style:italic;color:#64748b}}
.chip{{display:inline-block;font-size:11px;font-weight:700;padding:1px 7px;border-radius:5px;background:#dbeafe;color:#1e40af;margin-left:6px}}
.mono{{font-family:monospace;font-size:11px;color:#64748b}}
.empty{{color:#94a3b8;font-size:12px}}
</style></head><body>""")

    P.append(f"<h1>In-House Content by Topic — {esc(spec['brand'])}</h1>")
    P.append(f"<div class='intro'>{esc(spec['note'])}</div>")

    # TOC
    P.append("<div class='toc'><b>Topics:</b> ")
    for c in spec["clusters"]:
        P.append(f"<a href='#{esc(c['id'])}'>{esc(c['name'])}</a>")
    P.append("</div>")

    for c in spec["clusters"]:
        # gather (page, sections) with content
        blocks = []
        total_w = 0
        for m in c["members"]:
            secs = sections_for(m)
            secs = [s for s in secs if (s.get("text") or s.get("h"))]
            if secs:
                blocks.append((by_key[m["page"]], secs))
                total_w += sum(s.get("w", 0) for s in secs)
        npages = len(blocks)
        nsec = sum(len(s) for _, s in blocks)
        P.append(f"<h2 class='cluster' id='{esc(c['id'])}'>{esc(c['name'])}"
                 f"<span class='chip'>{npages} pages · {nsec} sections · {total_w:,} words</span></h2>")
        P.append(f"<div class='intro'>{esc(c.get('intro',''))}</div>")
        if not blocks:
            P.append("<div class='empty'>No matching sections.</div>")
            continue
        # deepest page first
        blocks.sort(key=lambda b: -sum(s.get("w", 0) for s in b[1]))
        for page, secs in blocks:
            w = sum(s.get("w", 0) for s in secs)
            P.append(f"<details class='page'><summary>{esc(page['name'])}"
                     f"<small>{len(secs)} sections · {w:,} words · "
                     f"<span class='mono'>{esc(page['url'])}</span></small></summary>")
            for s in secs:
                lvl = s.get("lvl", 2)
                cls = f"s{lvl if lvl in (0,1,2,3) else 2}"
                tag = "INTRO" if lvl == 0 else f"H{lvl}"
                P.append(f"<div class='srow {cls}'>"
                         f"<span class='tag'>{esc(tag)}</span>"
                         f"<span class='sh'>{esc(s['h']) or '(untitled)'}</span>"
                         f" <small class='mono'>{s.get('w',0)}w</small>")
                if s.get("text"):
                    P.append(f"<div class='sc'>{esc(s['text'])}</div>")
                P.append("</div>")
            P.append("</details>")

    P.append("</body></html>")
    OUT.write_text("".join(P), encoding="utf-8")
    print(f"wrote {OUT}  ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
