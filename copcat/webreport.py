"""HTML report: index dashboard with a D3 cluster collusion graph, plus a
side-by-side Diff Explainer page for every flagged pair.

Everything is generated as self-contained static files (only the D3 library
loads from CDN). Designed to be readable by department committees:
normalized AST variable mapping tables show exactly how student A's
`total_copies` corresponds to student B's `tCop`.
"""

import difflib
import html
import os
import re
import time

from .lexing import TOKEN_RE
from .forensics import scan_source

_IDENT_RE = re.compile(r"^[A-Za-z_]\w*$")
_KEYWORDS = {"if", "else", "elif", "for", "while", "return", "def", "class",
             "import", "from", "in", "not", "and", "or", "True", "False",
             "None", "print", "self", "int", "str", "float", "len", "range"}

_D3_CDN = "https://cdn.jsdelivr.net/npm/d3@7"

_CSS = """
body { font-family: 'Segoe UI', Arial, sans-serif; margin: 0; background: #f5f6fa; color: #1e272e; }
header { background: #1e272e; color: #fff; padding: 18px 28px; }
header h1 { margin: 0; font-size: 22px; }
header .sub { color: #9aa4ad; font-size: 13px; margin-top: 4px; }
main { padding: 20px 28px; max-width: 1280px; margin: 0 auto; }
h2 { font-size: 17px; border-bottom: 2px solid #dcdde1; padding-bottom: 6px; margin-top: 34px; }
table { border-collapse: collapse; width: 100%; background: #fff; font-size: 13px; }
th, td { border: 1px solid #dcdde1; padding: 6px 10px; text-align: left; }
th { background: #ecf0f1; }
tr:hover td { background: #f7f9ff; }
.flag-HIGH_PROBABILITY_PLAGIARISM { color: #fff; background: #c0392b; font-weight: 600; padding: 2px 8px; border-radius: 3px; }
.flag-SUSPICIOUS { color: #fff; background: #e67e22; font-weight: 600; padding: 2px 8px; border-radius: 3px; }
.flag-CLEAN { color: #27ae60; font-weight: 600; }
a { color: #2980b9; text-decoration: none; }
a:hover { text-decoration: underline; }
.badge { display: inline-block; background: #ecf0f1; border-radius: 10px; padding: 1px 9px; margin: 1px; font-size: 12px; }
.evidence { background: #fff8e1; border-left: 4px solid #f39c12; padding: 8px 12px; margin: 6px 0; font-size: 13px; }
.collide { background: #fdecea; border-left: 4px solid #c0392b; padding: 8px 12px; margin: 6px 0; font-size: 13px; }
.note { color: #636e72; font-size: 12px; }
/* diff explainer */
.diffwrap { border: 1px solid #dcdde1; max-height: 70vh; overflow: auto; background: #fff; }
table.diff { font-family: Consolas, 'Courier New', monospace; font-size: 12px; width: 100%; table-layout: fixed; }
table.diff td { border: none; padding: 1px 8px; white-space: pre-wrap; word-break: break-all; vertical-align: top; }
table.diff td.ln { width: 44px; color: #95a5a6; text-align: right; user-select: none; }
table.diff td.eq { background: #eafaf1; }
table.diff td.ne { background: #fdedec; }
table.diff td.empty { background: #f4f4f4; }
table.diff tr:hover td { outline: 1px solid #bbb; }
.maptbl td:first-child { font-family: Consolas, monospace; color: #8e44ad; }
.maptbl td:nth-child(2) { color: #95a5a6; }
.maptbl td:nth-child(3) { font-family: Consolas, monospace; color: #16a085; }
.lit { font-family: Consolas, monospace; font-size: 12px; background: #fff; }
"""

_JS_GRAPH = """
const svg = d3.select("#graph"), width = +svg.attr("width"), height = +svg.attr("height");
svg.call(d3.zoom().scaleExtent([0.2, 5]).on("zoom", (ev) => g.attr("transform", ev.transform)));
const g = svg.append("g");
const links = GRAPH_DATA.links.map(d => ({...d}));
const nodes = GRAPH_DATA.nodes.map(d => ({...d}));
const sim = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(links).id(d => d.id).distance(d => 170 - 120 * (d.pct / 100)).strength(0.6))
    .force("charge", d3.forceManyBody().strength(-450))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("collide", d3.forceCollide(d => 14 + 3 * d.degree));
const link = g.append("g").selectAll("line").data(links).join("line")
    .attr("stroke", d => d.flag === "HIGH_PROBABILITY_PLAGIARISM" ? "#c0392b" : "#e67e22")
    .attr("stroke-width", d => 1 + 4 * (d.pct / 100))
    .attr("stroke-opacity", 0.65);
const edgeLbl = g.append("g").selectAll("text").data(links).join("text")
    .text(d => d.pct.toFixed(0) + "%").attr("font-size", 10).attr("fill", "#636e72")
    .attr("text-anchor", "middle");
const node = g.append("g").selectAll("g").data(nodes).join("g")
    .attr("cursor", "pointer")
    .call(d3.drag().on("start", (ev, d) => { if (!ev.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
                  .on("drag", (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
                  .on("end", (ev, d) => { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));
node.append("circle").attr("r", d => 10 + 2.2 * d.degree)
    .attr("fill", d => CLUSTER_COLORS[d.group % CLUSTER_COLORS.length])
    .attr("stroke", "#2c3e50").attr("stroke-width", 1.5);
node.append("text").text(d => d.id).attr("font-size", 12).attr("text-anchor", "middle")
    .attr("dy", d => -(14 + 2.2 * d.degree));
node.append("title").text(d => d.title);
sim.on("tick", () => {
    link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
    edgeLbl.attr("x", d => (d.source.x + d.target.x) / 2).attr("y", d => (d.source.y + d.target.y) / 2);
    node.attr("transform", d => "translate(" + d.x + "," + d.y + ")");
});
"""


def _esc(text):
    return html.escape(str(text), quote=True)


def _flag_span(flag):
    return '<span class="flag-{}">{}</span>'.format(_esc(flag), _esc(flag))


def _diff_rows(lines_a, lines_b, max_rows=1400):
    """(html_rows, n_equal, n_total) from SequenceMatcher opcodes."""
    sm = difflib.SequenceMatcher(None, lines_a, lines_b, autojunk=False)
    rows, eq, tot = [], 0, 0
    truncated = False
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tot > max_rows:
            truncated = True
            break
        if tag == "equal":
            for k in range(i2 - i1):
                tot += 1
                eq += 1
                rows.append('<tr><td class="ln">{}</td><td class="eq">{}</td>'
                            '<td class="ln">{}</td><td class="eq">{}</td></tr>'
                            .format(i1 + k + 1, _esc(lines_a[i1 + k]),
                                    j1 + k + 1, _esc(lines_b[j1 + k])))
        elif tag == "replace":
            span = max(i2 - i1, j2 - j1)
            for k in range(span):
                tot += 1
                la = _esc(lines_a[i1 + k]) if i1 + k < i2 else ""
                lb = _esc(lines_b[j1 + k]) if j1 + k < j2 else ""
                na = i1 + k + 1 if i1 + k < i2 else ""
                nb = j1 + k + 1 if j1 + k < j2 else ""
                cls_a = "ne" if la else "empty"
                cls_b = "ne" if lb else "empty"
                rows.append('<tr><td class="ln">{}</td><td class="{}">{}</td>'
                            '<td class="ln">{}</td><td class="{}">{}</td></tr>'
                            .format(na, cls_a, la, nb, cls_b, lb))
        elif tag == "delete":
            for k in range(i2 - i1):
                tot += 1
                rows.append('<tr><td class="ln">{}</td><td class="ne">{}</td>'
                            '<td class="ln"></td><td class="empty"></td></tr>'
                            .format(i1 + k + 1, _esc(lines_a[i1 + k])))
        elif tag == "insert":
            for k in range(j2 - j1):
                tot += 1
                rows.append('<tr><td class="ln"></td><td class="empty"></td>'
                            '<td class="ln">{}</td><td class="ne">{}</td></tr>'
                            .format(j1 + k + 1, _esc(lines_b[j1 + k])))
    return "\n".join(rows), eq, tot, truncated


def _rename_evidence(lines_a, lines_b, limit=40):
    """True positional rename evidence: identifier swaps inside near-matched
    line pairs. Returns (html_table, n_rows, top_pairs).

    A line pair that matches except for one swapped identifier is the classic
    renamed-variable fingerprint (A's `total_copies` at the exact position
    where B has `tCop`).
    """
    counts = {}
    sm = difflib.SequenceMatcher(None, lines_a, lines_b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "replace" or (i2 - i1) != (j2 - j1):
            continue
        for k in range(i2 - i1):
            ta = TOKEN_RE.findall(lines_a[i1 + k])
            tb = TOKEN_RE.findall(lines_b[j1 + k])
            if abs(len(ta) - len(tb)) > 2:
                continue
            smt = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
            for t2, x1, x2, y1, y2 in smt.get_opcodes():
                if (t2 == "replace" and (x2 - x1) == 1 and (y2 - y1) == 1):
                    x, y = ta[x1], tb[y1]
                    if (x != y and _IDENT_RE.match(x) and _IDENT_RE.match(y)
                            and x not in _KEYWORDS and y not in _KEYWORDS):
                        counts[(x, y)] = counts.get((x, y), 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    rows = "".join(
        "<tr><td>{}</td><td>&harr;</td><td>{}</td><td>{}</td></tr>"
        .format(_esc(a), _esc(b), n) for (a, b), n in top)
    tbl = ""
    if rows:
        tbl = ('<table class="maptbl"><tr><th>Student A identifier</th><th></th>'
               '<th>Student B identifier</th><th>lines</th></tr>\n' + rows
               + "\n</table>\n")
    return tbl, len(counts), top


def write_diff(path, sub_a, sub_b, pair, cfg):
    rows_html, eq, tot, truncated = _diff_rows(sub_a.effective_lines, sub_b.effective_lines)
    map_tbl, n_maps, _top = _rename_evidence(sub_a.effective_lines, sub_b.effective_lines)
    shared_lits = sorted(set(sub_a.string_words) & set(sub_b.string_words))
    lit_html = " ".join('<span class="badge lit">{}</span>'.format(_esc(w))
                        for w in shared_lits[:40])
    if len(shared_lits) > 40:
        lit_html += ' <span class="note">… +{} more</span>'.format(len(shared_lits) - 40)
    s = pair.scores
    chan = ("<span class='badge'>source {}</span> <span class='badge'>token {}</span>"
            " <span class='badge'>ast {}</span> <span class='badge'>shadow {}</span>"
            " <span class='badge'>comment {}</span> <span class='badge'>string {}</span>"
            .format(*[_esc("{:.1f}%".format(100 * s[k][0]))
                      for k in ("source", "token", "ast", "shadow", "comment", "string")]))
    ev_html = "".join('<div class="evidence">{}</div>'.format(_esc(e))
                      for e in pair.evidence)
    title = "CopCat diff: {} vs {}".format(sub_a.roll, sub_b.roll)
    page = ("<!DOCTYPE html><html><head><meta charset='utf-8'><title>" + _esc(title) +
            "</title><style>" + _CSS + "</style></head><body>"
            "<header><h1>" + _esc(title) + "</h1><div class='sub'>" +
            _flag_span(pair.flag) + " &nbsp; blended <b>{:.1f}%</b> &nbsp;|&nbsp; ".format(100 * pair.blended) +
            chan + "</div></header><main>"
            + "".join('<div class="evidence">' + _esc(e) + "</div>" for e in pair.evidence)
            + "<h2>Renamed-identifier evidence (" + str(n_maps) + " swaps found)</h2>"
            + (map_tbl or "<p class='note'>No positional identifier swaps detected — identical naming, or files too dissimilar to align.</p>")
            + "<h2>Shared string literals (" + str(len(shared_lits)) + " words)</h2>"
            + (lit_html or "<p class='note'>None.</p>")
            + "<h2>Side-by-side diff — {} matching of {} lines{}</h2>".format(eq, tot, " (truncated)" if truncated else "")
            + "<div class='diffwrap'><table class='diff'>"
              "<tr><th style='width:44px'>A#</th><th style='width:auto'>" + _esc(sub_a.roll) +
              "</th><th style='width:44px'>B#</th><th style='width:auto'>" + _esc(sub_b.roll) +
              "</th></tr>" + rows_html + "</table></div>"
            "<p class='note'>Generated by CopCat — green = identical line, red = differs, "
            "both columns scroll together.</p>"
            "</main></body></html>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)


def _graph_data(subs, pairs, clusters):
    cluster_of = {}
    for gi, members in enumerate(clusters, 1):
        for roll in members:
            cluster_of[roll] = gi
    edges = [p for p in pairs if p.blended >= 0.45]   # display cut for the graph
    deg = {}
    for p in edges:
        deg[p.roll_a] = deg.get(p.roll_a, 0) + 1
        deg[p.roll_b] = deg.get(p.roll_b, 0) + 1
    nodes, seen = [], set()
    for p in edges:
        for roll in (p.roll_a, p.roll_b):
            if roll in seen:
                continue
            seen.add(roll)
            nodes.append({
                "id": roll,
                "degree": deg.get(roll, 1),
                "group": cluster_of.get(roll, 0),
                "title": roll,
            })
    links = [{"source": p.roll_a, "target": p.roll_b,
              "pct": round(100 * p.blended, 1),
              "flag": p.flag,
              "title": "{} vs {}: {:.1f}%".format(p.roll_a, p.roll_b, 100 * p.blended)}
             for p in edges]
    return nodes, links


def write_html_report(path, subs, pairs, clusters, cfg,
                      forensics=None, collisions=None):
    out_dir = os.path.dirname(os.path.abspath(path))
    diff_dir = os.path.join(out_dir, "diffs")
    os.makedirs(diff_dir, exist_ok=True)

    flagged = [p for p in pairs if p.blended >= cfg.suspicious or p.evidence]
    sub_by_roll = {s.roll: s for s in subs}

    # per-pair diff pages
    links_rows = []
    for p in flagged:
        sa, sb = sub_by_roll.get(p.roll_a), sub_by_roll.get(p.roll_b)
        if not sa or not sb:
            continue
        fname = "diffs/{}__vs__{}.html".format(p.roll_a, p.roll_b)
        write_diff(os.path.join(out_dir, fname), sa, sb, p, cfg)
        s = p.scores
        ev_html = "<br/>".join(_esc(e) for e in p.evidence)
        links_rows.append(
            "<tr><td>{}</td><td><a href='{}'>{} vs {}</a></td><td>{:.1f}%</td>"
            "<td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>"
            .format(_flag_span(p.flag), _esc(fname), _esc(p.roll_a),
                    _esc(p.roll_b), 100 * p.blended,
                    _esc("{:.0f}%".format(100 * s["source"][0])),
                    _esc("{:.0f}%".format(100 * s["token"][0])),
                    _esc("{:.0f}%".format(100 * s["ast"][0])),
                    _esc("{:.0f}%".format(100 * s["shadow"][0])),
                    _esc("{:.0f}%".format(100 * s["string"][0])),
                    ev_html))

    # evasion candidates
    ev_rows = []
    for s in subs:
        total = max(s.n_comment_lines, 1)
        ratio = s.code_like_comment_lines / total
        if ratio >= cfg.evasion_ratio and len(s.shadow_tokens) >= cfg.evasion_min_shadow:
            ev_rows.append("<tr><td>{}</td><td>{:.0%}</td><td>{}</td><td>{}</td></tr>"
                           .format(_esc(s.roll), ratio, len(s.shadow_tokens),
                                   "mostly commented out" if s.notes else ""))

    # forensics
    coll_html = ""
    if collisions:
        coll_html = "".join(
            "<div class='collide'>{} <code>{}</code> shared by: {}</div>"
            .format(_esc(kind), _esc(nid), _esc(", ".join(rolls)))
            for kind, nid, rolls in collisions)

    nodes, links = _graph_data(subs, pairs, clusters)
    graph_payload = ("const GRAPH_DATA = {nodes: " + str(nodes).replace("'", '"')
                     .replace('"id":', '"id":') + ", links: " +
                     str(links).replace("'", '"') + "};")
    palette = 'const CLUSTER_COLORS = ["#95a5a6", "#2980b9", "#8e44ad", "#16a085", "#d35400", "#2c3e50", "#c0392b"];'

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    page = ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<title>CopCat audit report</title><style>" + _CSS + "</style>"
            "<script src='" + _D3_CDN + "'></script></head><body>"
            "<header><h1>CopCat &mdash; audit report</h1>"
            "<div class='sub'>generated " + _esc(now) + " &middot; "
            + str(len(subs)) + " submissions &middot; " + str(len(pairs))
            + " pairs &middot; SUS&gt;" + "{:.0f}%".format(100 * cfg.suspicious)
            + " HIGH&gt;" + "{:.0f}%".format(100 * cfg.high)
            + " &middot; starter subtraction: " + _esc(", ".join(cfg.starters) or "none")
            + "</div></header><main>")

    page += "<h2>Collusion graph (flagged pairs, colored by cluster)</h2>"
    page += ("<svg id='graph' width='1200' height='640' style='background:#fff;"
             "border:1px solid #dcdde1'></svg>"
             "<p class='note'>Node size = number of flagged partners &middot; edge "
             "thickness = blended similarity &middot; drag nodes, scroll to zoom. "
             "Requires internet for the D3 library.</p>"
             "<script>" + graph_payload + "\n" + palette + "\n" + _JS_GRAPH + "</script>")

    page += "<h2>Flagged pairs ({} )</h2>".format(len(flagged))
    if links_rows:
        page += ("<table><tr><th>flag</th><th>pair (click for diff explainer)</th>"
                 "<th>blended</th><th>source</th><th>token</th><th>ast</th>"
                 "<th>shadow</th><th>string</th><th>evidence</th></tr>\n"
                 + "\n".join(links_rows) + "</table>")
    else:
        page += "<p class='note'>No pairs crossed the suspicion threshold.</p>"

    page += "<h2>Evasion candidates (commented-out code)</h2>"
    if ev_rows:
        page += ("<table><tr><th>roll</th><th>code-like comments</th>"
                 "<th>folded shadow tokens</th><th>note</th></tr>\n"
                 + "\n".join(ev_rows) + "</table>")
    else:
        page += "<p class='note'>None.</p>"

    if forensics:
        page += "<h2>Forensics (provenance)</h2>"
        if collisions:
            page += coll_html
        else:
            page += "<p class='note'>No notebook/drive IDs shared between students.</p>"
        prov = [(roll, info) for roll, info in sorted(forensics.items())
                if info["colab_ids"] or info["ipython_artifacts"]]
        if prov:
            page += ("<table><tr><th>roll</th><th>colab notebook id</th>"
                     "<th>notes</th></tr>\n")
            for roll, info in prov:
                page += ("<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                    _esc(roll),
                    _esc(", ".join(info["colab_ids"]) or "-"),
                    _esc("IPython artifacts" if info["ipython_artifacts"] else "")))
            page += "</table>"

    page += ("<p class='note'>CopCat deterministic audit — no AI involved. "
             "Similarity alone cannot prove collusion; review channel breakdowns, "
             "variable mappings and shared literals before acting.</p>")
    page += "</main></body></html>"

    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)
