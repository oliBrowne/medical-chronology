"""Render a chronology bundle as ``timeline.html``.

One self-contained file: no external scripts, fonts or styles, so it opens
offline and prints cleanly (filters are hidden in print). It is always light,
whatever the system colour scheme. Every quote is shown
exactly as stored, every Bates label links to its page in the source PDF, and
anything the bundle check found wrong is shown, never hidden.

Clicking a Bates label opens a floating window on the same page with the full
text of the cited page, the quote highlighted at its cited characters, and the
PDF page itself. Ctrl/Cmd-click still opens the PDF in a new tab.

Layout follows the chrono timeline:

    2024-03-14        ED note · Mountain View Regional ED
    day of incident   [cervical spine] [diagnosis] [ICD10CM S16.1XXA]
                      ┃ Assessment: Cervical strain.
                      [SYN 000001]
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
from urllib.parse import quote as urlquote

from chronology.output import dates
from chronology.output.bundle import BundleIndex, ChronologyBundle, index_bundle
from chronology.schemas import ChronologyEvent, EvidenceSpan, Finding

OCR_WARN_BELOW = 0.80  # OCR confidence under this gets a warning chip

_ASSERTION_BADGE = {
    "absent": ("Denied / absent", "absent"),
    "possible": ("Possible", "possible"),
    "historical": ("Historical", "historical"),
}


def e(text: object) -> str:
    return html.escape(str(text), quote=True)


def pretty(label: str | None) -> str:
    return (label or "").replace("_", " ")


def doc_title(path: str) -> str:
    """'SYN 000001-000003 - Mountain View Regional ED.pdf' -> 'Mountain View Regional ED'."""
    stem = Path(path).stem
    return stem.split(" - ", 1)[1] if " - " in stem else stem


# --- links -------------------------------------------------------------------

def page_href(doc_path: str, page_index: int, case_dir: Path | None, out_dir: Path) -> str | None:
    """Link to one page of a source PDF, relative to the output folder.

    Falls back to an absolute file:// URL when no relative path exists (a
    different drive on Windows). None when the PDF is not on disk.
    """
    if case_dir is None:
        return None
    pdf = (case_dir / doc_path).resolve()
    if not pdf.is_file():
        return None
    try:
        href = urlquote(Path(os.path.relpath(pdf, out_dir.resolve())).as_posix())
    except ValueError:
        href = pdf.as_uri()
    return f"{href}#page={page_index + 1}"


def locator_text(span: EvidenceSpan, ix: BundleIndex) -> str:
    if span.bates_label:
        return span.bates_label
    doc = ix.documents.get(span.doc_id)
    name = doc_title(doc.path) if doc else span.doc_id
    return f"Unstamped · {name} p.{span.page_index + 1}"


# --- pieces ------------------------------------------------------------------

def chip(text: str, cls: str = "", title: str = "") -> str:
    t = f' title="{e(title)}"' if title else ""
    return f'<span class="chip {cls}"{t}>{e(text)}</span>'


def mapping_chip(fid: str, ix: BundleIndex) -> str:
    m = ix.mappings.get(fid)
    if m is None:
        return ""
    tip = " · ".join(x for x in [
        f"CUI {m.cui}" if m.cui else "",
        f"UMLS {m.umls_release}" if m.umls_release else "",
        f"{m.iterations} lookup step{'s' if m.iterations != 1 else ''}" if m.iterations else "",
        m.rationale or "",
    ] if x)
    if m.status == "mapped":
        code = " ".join(x for x in [m.source_vocab, m.source_code] if x) or m.cui or "mapped"
        return chip(code, "code", tip)
    if m.status == "needs_review":
        cands = f": {', '.join(m.candidates)}" if m.candidates else ""
        return chip(f"concept needs review{cands}", "warn", tip)
    return chip("no concept found", "warn", tip)


def span_block(span_id: str, ix: BundleIndex, case_dir: Path | None, out_dir: Path) -> str:
    span = ix.spans.get(span_id)
    if span is None:
        return f'<div class="error">Missing span {e(span_id)}: this finding cannot be traced.</div>'
    ok = ix.verified.get(span_id, False)
    page = ix.pages.get((span.doc_id, span.page_index))
    doc = ix.documents.get(span.doc_id)
    href = page_href(doc.path, span.page_index, case_dir, out_dir) if doc else None
    loc = locator_text(span, ix)
    ctx = f' data-ctx="{e(span_id)}" aria-haspopup="dialog"' if page is not None else ""
    if href:
        bates = (f'<a class="bates" href="{e(href)}" target="_blank" rel="noopener"{ctx}'
                 f' title="Show this page here (Ctrl-click opens the PDF in a new tab)">{e(loc)}</a>')
    elif page is not None:
        bates = (f'<button type="button" class="bates nolink"{ctx}'
                 f' title="Source PDF not found; shows the page text">{e(loc)}</button>')
    else:
        bates = f'<span class="bates nolink" title="Source PDF not found">{e(loc)}</span>'
    extra = []
    if not ok:
        extra.append(chip("quote not verified verbatim", "bad",
                          "; ".join(p.message for p in ix.problems_for(span_id))))
    elif any(p.kind == "bates_mismatch" for p in ix.problems_for(span_id)):
        extra.append(chip("Bates label disagrees with page", "bad"))
    if page is not None and page.text_source == "ocr":
        conf = page.ocr_confidence
        low = conf is not None and conf < OCR_WARN_BELOW
        extra.append(chip(f"OCR {round(conf * 100)}%" if conf is not None else "OCR",
                          "warn" if low else "", "Text read by OCR; check the page image"))
    if not span.bates_label:
        extra.append(chip("no Bates stamp", "warn"))
    return (f'<pre class="quote{"" if ok else " unverified"}" data-span="{e(span_id)}">'
            f"{e(span.quote)}</pre>"
            f'<div class="locators">{bates}{"".join(extra)}</div>')


def finding_block(fid: str, event: ChronologyEvent, ix: BundleIndex,
                  case_dir: Path | None, out_dir: Path) -> str:
    f = ix.findings.get(fid)
    if f is None:
        return f'<div class="error">Missing finding {e(fid)}.</div>'
    first = ix.spans.get(f.span_ids[0])
    page = ix.pages.get((first.doc_id, first.page_index)) if first else None
    doc = ix.documents.get(first.doc_id) if first else None
    source = " · ".join(x for x in [
        pretty(page.page_type) if page else "",
        doc_title(doc.path) if doc else "",
    ] if x)
    if f.document_date and f.document_date != event.date:
        source += f" · written {dates.display(f.document_date)}"
    if f.event_date and f.event_date != event.date:
        source += f" · dated {dates.display(f.event_date)}"
    chips = []
    if f.body_site:
        chips.append(chip(pretty(f.body_site), "site"))
    chips.append(chip(pretty(f.category), "type"))
    if f.assertion in _ASSERTION_BADGE:
        label, cls = _ASSERTION_BADGE[f.assertion]
        chips.append(chip(label, cls))
    if f.subject == "other":
        chips.append(chip("about someone else", "other"))
    chips.append(mapping_chip(fid, ix))
    conflict = " conflicting" if fid in event.conflicts else ""
    spans = "".join(span_block(sid, ix, case_dir, out_dir) for sid in f.span_ids)
    return (f'<div class="finding{conflict}">'
            f'<div class="source">{e(source)}</div>'
            f'<div class="chips">{"".join(chips)}</div>{spans}</div>')


def needs_attention(event: ChronologyEvent, ix: BundleIndex) -> bool:
    if event.conflicts or ix.problems_for(event.event_id):
        return True
    if dates.precision(event.date) != "day":
        return True
    for fid in event.finding_ids:
        f = ix.findings.get(fid)
        if f is None or ix.problems_for(fid):
            return True
        m = ix.mappings.get(fid)
        if m is not None and m.status != "mapped":
            return True
        for sid in f.span_ids:
            span = ix.spans.get(sid)
            if span is None or not ix.verified.get(sid) or not span.bates_label:
                return True
            page = ix.pages.get((span.doc_id, span.page_index))
            if page and page.text_source == "ocr" and (page.ocr_confidence or 0) < OCR_WARN_BELOW:
                return True
    return False


def event_dates(event: ChronologyEvent, ix: BundleIndex) -> list[str]:
    out = []
    for fid in event.finding_ids:
        f = ix.findings.get(fid)
        if f and (f.event_date or f.document_date):
            out.append(f.event_date or f.document_date)
    return sorted(set(out), key=dates.sort_key)


def entry(event: ChronologyEvent, ix: BundleIndex, index_iso: str | None,
          injuries: dict[str, list[str]], case_dir: Path | None, out_dir: Path) -> str:
    findings = [ix.findings[f] for f in event.finding_ids if f in ix.findings]
    head = []
    if event.conflicts:
        head.append(chip("conflicting findings, not resolved", "bad"))
    elif len(event.finding_ids) > 1:
        series = event_dates(event, ix)
        span = f" ({dates.display(series[0])} → {dates.display(series[-1])})" if len(series) > 1 else ""
        head.append(chip(f"documented ×{len(event.finding_ids)}{span}", "repeat"))
    if event.review_status != "pending":
        head.append(chip(f"review: {event.review_status}", event.review_status))
    for p in ix.problems_for(event.event_id):
        head.append(f'<div class="error">{e(p.message)}</div>')

    sites = {f.body_site for f in findings if f.body_site}
    inj = [i for i, s in injuries.items() if sites & set(s)]
    text = " ".join(
        [f.original_phrase for f in findings] + [f.category for f in findings]
        + [s for s in sites] + [ix.spans[s].quote for f in findings for s in f.span_ids if s in ix.spans]
    ).lower()
    data = {
        "type": " ".join(sorted({f.category for f in findings})),
        "site": "|".join(sorted(sites)),
        "assertion": " ".join(sorted({f.assertion for f in findings})),
        "injury": " ".join(inj),
        "attention": "1" if needs_attention(event, ix) else "0",
        "text": text,
    }
    attrs = " ".join(f'data-{k}="{e(v)}"' for k, v in data.items())
    prec = dates.precision(event.date)
    when = e(dates.display(event.date))
    if prec in ("month", "year"):
        when += f'<span class="prec">{prec} only</span>'
    rel = e(dates.relative(event.date, index_iso))
    body = "".join(finding_block(fid, event, ix, case_dir, out_dir) for fid in event.finding_ids)
    return (f'<article class="entry{" rejected" if event.review_status == "rejected" else ""}"'
            f' id="{e(event.event_id)}" {attrs}>'
            f'<div class="when"><div class="date">{when}</div><div class="rel">{rel}</div></div>'
            f'<div class="what">{"".join(head)}{body}</div></article>')


def _first_locator(event: ChronologyEvent, ix: BundleIndex) -> str:
    for fid in event.finding_ids:
        f = ix.findings.get(fid)
        for sid in (f.span_ids if f else []):
            s = ix.spans.get(sid)
            if s:
                return s.bates_label or f"~{s.doc_id}:{s.page_index:05d}"
    return "~"


def context_data(ix: BundleIndex, case_dir: Path | None, out_dir: Path) -> str:
    """Page text and span positions for the floating page window, as JSON.

    Safe to put inside <script type="application/json">: every "<" is
    escaped, so the text can never close the script element.
    """
    pages = {}
    for (doc_id, pi), p in ix.pages.items():
        doc = ix.documents.get(doc_id)
        title = doc_title(doc.path) if doc else doc_id
        pages[f"{doc_id}:{pi}"] = {
            "text": p.text,
            "label": p.bates_label or f"Unstamped · {title} p.{pi + 1}",
            "title": title,
            "type": pretty(p.page_type),
            "page": pi + 1,
            "pages": doc.page_count if doc else None,
            "ocr": (p.ocr_confidence if p.ocr_confidence is not None else -1)
                   if p.text_source == "ocr" else None,
            "href": page_href(doc.path, pi, case_dir, out_dir) if doc else None,
        }
    spans = {s.span_id: {"page": f"{s.doc_id}:{s.page_index}", "start": s.char_start,
                         "end": s.char_end, "ok": ix.verified.get(s.span_id, False)}
             for s in ix.spans.values()}
    return json.dumps({"pages": pages, "spans": spans}, ensure_ascii=False).replace("<", "\\u003c")


# --- the page ----------------------------------------------------------------

def render(bundle: ChronologyBundle, *, case_dir: Path | None, out_dir: Path) -> str:
    ix = index_bundle(bundle)
    idx = bundle.index_event
    index_iso = idx.date if idx else None
    injuries = {i.id: i.body_sites for i in bundle.claimed_injuries}

    dated = [ev for ev in bundle.events if dates.precision(ev.date) != "unknown"]
    undated = [ev for ev in bundle.events if dates.precision(ev.date) == "unknown"]
    dated.sort(key=lambda ev: (dates.sort_key(ev.date), _first_locator(ev, ix)))
    undated.sort(key=lambda ev: _first_locator(ev, ix))

    rows, placed = [], idx is None
    for ev in dated:
        if not placed and dates.sort_key(ev.date) >= index_iso:
            rows.append(incident_bar(idx))
            placed = True
        rows.append(entry(ev, ix, index_iso, injuries, case_dir, out_dir))
    if not placed:
        rows.append(incident_bar(idx))
    if undated:
        rows.append('<h2 class="group" id="undated">Date unknown</h2>'
                    '<p class="note">No event date was found for these. They are kept, not guessed.</p>')
        rows.extend(entry(ev, ix, index_iso, injuries, case_dir, out_dir) for ev in undated)

    types = sorted({f.category for f in bundle.findings})
    sites = sorted({f.body_site for f in bundle.findings if f.body_site})
    assertions = [a for a in ("present", "absent", "possible", "historical")
                  if any(f.assertion == a for f in bundle.findings)]

    def options(values, label=pretty):
        return "".join(f'<option value="{e(v)}">{e(label(v))}</option>' for v in values)

    problems = ix.problems
    if problems:
        # point each problem at the timeline entry it belongs to
        owner: dict[str, str] = {}
        for ev in bundle.events:
            owner[ev.event_id] = ev.event_id
            for fid in ev.finding_ids:
                owner.setdefault(fid, ev.event_id)
                for sid in (ix.findings[fid].span_ids if fid in ix.findings else []):
                    owner.setdefault(sid, ev.event_id)

        def item(p) -> str:
            span = ix.spans.get(p.ref)
            where = locator_text(span, ix) if span else p.ref
            ev = owner.get(p.ref)
            label = f'<a href="#{e(ev)}">{e(where)}</a>' if ev else f"<code>{e(where)}</code>"
            return f"<li>{label}: {e(p.message)}</li>"

        items = "".join(item(p) for p in problems)
        problem_box = (f'<section class="problems"><strong>{len(problems)} problem'
                       f'{"s" if len(problems) != 1 else ""} in this output.</strong> '
                       f"Check these before relying on it.<ul>{items}</ul></section>")
    else:
        problem_box = ""

    n_quotes = len(bundle.spans)
    n_ok = sum(1 for v in ix.verified.values() if v)
    injuries_html = "".join(f"<li>{e(i.label)}</li>" for i in bundle.claimed_injuries)
    incident_line = ""
    if idx:
        when = idx.date + (f" {idx.time}" if idx.time else "")
        incident_line = f'<p class="incident-line"><b>Incident</b> {e(when)} · {e(idx.description)}</p>'

    return PAGE.format(
        title=e(f"Chronology · {bundle.case_id}"),
        case_id=e(bundle.case_id),
        incident_line=incident_line,
        injuries=f'<ul class="injuries">{injuries_html}</ul>' if injuries_html else "",
        meta=e(f"Generated {bundle.generated_at} · pipeline {bundle.pipeline_version} · "
               f"{len(bundle.events)} events · {len(bundle.findings)} findings · "
               f"{n_ok} of {n_quotes} quotes verified verbatim"),
        problems=problem_box,
        injury_options=options([i.id for i in bundle.claimed_injuries],
                               lambda v: next(i.label for i in bundle.claimed_injuries if i.id == v)),
        type_options=options(types),
        site_options=options(sites),
        assertion_options=options(assertions, lambda a: "denied / absent" if a == "absent" else a),
        rows="\n".join(rows),
        total=len(bundle.events),
        context=context_data(ix, case_dir, out_dir),
        css=CSS,
        js=JS,
    )


def incident_bar(idx) -> str:
    when = idx.date + (f" {idx.time}" if idx.time else "")
    return (f'<div class="incident" id="incident" role="separator">'
            f'<span class="tag">Incident</span><span class="iwhen">{e(when)}</span>'
            f'<span class="idesc">{e(idx.description)}</span></div>')


def write_outputs(bundle: ChronologyBundle, *, case_dir: Path | None, out_dir: Path) -> dict[str, Path]:
    """Write timeline.html and timeline.json (the bundle it was drawn from)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "timeline.html"
    json_path = out_dir / "timeline.json"
    # newline="\n": on Windows write_text would otherwise turn \n into \r\n
    html_path.write_text(render(bundle, case_dir=case_dir, out_dir=out_dir),
                         encoding="utf-8", newline="\n")
    json_path.write_text(bundle.model_dump_json(indent=2) + "\n",
                         encoding="utf-8", newline="\n")
    return {"html": html_path, "json": json_path}


CSS = """
:root{--bg:#fbfaf8;--panel:#fff;--ink:#1f2328;--muted:#646b73;--line:#e3e0da;
--quote-bg:#f3f2ef;--accent:#2457a6;--site-bg:#e7eefa;--site-ink:#1d4687;
--warn-bg:#fdf2dc;--warn-ink:#7a4d00;--bad-bg:#fbe5e3;--bad-ink:#a1251b;--bad:#c4372b;
--absent-bg:#ece6f7;--absent-ink:#4a2a8a;--ok-bg:#e3f2e6;--ok-ink:#1e6b33;
--incident-bg:#fff1d6;--incident-line:#d48a00;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;--mark-bg:#ffe08a;--mark-ink:#1f2328;
--shadow:0 12px 40px rgba(0,0,0,.18),0 2px 8px rgba(0,0,0,.08);color-scheme:light}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 var(--sans)}
header,main,.filters-inner{max-width:1040px;margin:0 auto;padding:0 20px}
header{padding-top:28px;padding-bottom:8px}
h1{font-size:22px;margin:0 0 4px;letter-spacing:-.01em}
.case{color:var(--muted);font-weight:500}
.incident-line{margin:6px 0}
.injuries{margin:4px 0 8px;padding-left:20px;color:var(--ink)}
.meta{color:var(--muted);font-size:13px;margin:6px 0 0}
.problems{background:var(--bad-bg);color:var(--bad-ink);border:1px solid var(--bad);
border-radius:8px;padding:10px 14px;margin:14px 0 0;font-size:14px}
.problems ul{margin:6px 0 0;padding-left:18px}
.filters{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);
padding:10px 0;margin-top:12px}
.filters-inner{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;font-size:13px}
.filters label{display:flex;gap:6px;align-items:center;color:var(--muted)}
.filters select,.filters input[type=search]{font:inherit;color:var(--ink);background:var(--panel);
border:1px solid var(--line);border-radius:6px;padding:4px 8px}
.filters input[type=search]{min-width:200px}
.count{margin-left:auto;color:var(--muted)}
main{padding-bottom:60px}
.entry{display:grid;grid-template-columns:150px 1fr;gap:18px;padding:16px 0;border-bottom:1px solid var(--line)}
.entry.rejected .what{opacity:.6}
.when .date{font-weight:600;font-variant-numeric:tabular-nums}
.when .prec{display:block;font-size:11px;font-weight:500;color:var(--warn-ink);text-transform:uppercase;letter-spacing:.04em}
.when .rel{color:var(--muted);font-size:13px}
.finding+.finding{margin-top:14px;padding-top:12px;border-top:1px dashed var(--line)}
.finding.conflicting{border-left:3px solid var(--bad);padding-left:12px}
.source{color:var(--muted);font-size:13px;margin-bottom:4px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px}
.chip{display:inline-block;font-size:12px;line-height:1.5;padding:1px 8px;border-radius:999px;
background:var(--quote-bg);color:var(--ink);border:1px solid var(--line)}
.chip.site{background:var(--site-bg);color:var(--site-ink);border-color:transparent}
.chip.type{font-weight:700}
.chip.code{font-family:var(--mono);font-size:11.5px}
.chip.absent{background:var(--absent-bg);color:var(--absent-ink);border-color:var(--absent-ink);font-weight:700}
.chip.historical,.chip.possible,.chip.other{background:var(--panel);border-style:dashed;font-weight:600}
.chip.warn{background:var(--warn-bg);color:var(--warn-ink);border-color:transparent}
.chip.bad{background:var(--bad-bg);color:var(--bad-ink);border-color:var(--bad);font-weight:600}
.chip.repeat{background:var(--panel)}
.chip.approved{background:var(--ok-bg);color:var(--ok-ink);border-color:transparent}
.chip.rejected{background:var(--bad-bg);color:var(--bad-ink);border-color:transparent}
.what>.chip{margin:0 6px 8px 0}
pre.quote{font:13px/1.5 var(--mono);white-space:pre-wrap;word-break:break-word;margin:0 0 6px;
background:var(--quote-bg);border-left:3px solid var(--muted);padding:6px 10px;border-radius:0 6px 6px 0}
pre.quote.unverified{border:2px solid var(--bad);border-left-width:4px}
.locators{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:4px}
.bates{font:600 12px var(--mono);padding:2px 8px;border-radius:6px;border:1px solid var(--accent);
color:var(--accent);text-decoration:none;background:var(--panel)}
a.bates:hover,a.bates:focus,a.bates[aria-expanded=true]{background:var(--accent);color:var(--panel)}
.bates.nolink{border-color:var(--line);color:var(--muted)}
button.bates{cursor:pointer}
button.bates:hover,button.bates:focus,button.bates[aria-expanded=true]{border-color:var(--muted);color:var(--ink)}
.ctx{position:fixed;z-index:10;top:72px;right:24px;width:min(580px,calc(100vw - 32px));
height:min(70vh,640px);min-width:300px;min-height:220px;max-width:calc(100vw - 16px);max-height:calc(100vh - 16px);
display:flex;flex-direction:column;background:var(--panel);color:var(--ink);border:1px solid var(--line);
border-radius:10px;box-shadow:var(--shadow);resize:both;overflow:hidden}
.ctx[hidden]{display:none}
.ctx-head{display:flex;gap:10px;align-items:flex-start;padding:10px 12px 8px;border-bottom:1px solid var(--line);
cursor:move;user-select:none;touch-action:none}
.ctx-head>div{flex:1;min-width:0}
.ctx-title{font:600 13px var(--mono);color:var(--accent)}
.ctx-sub{color:var(--muted);font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ctx-bar{display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding:6px 12px;border-bottom:1px solid var(--line);font-size:12.5px}
.ctx button,.ctx-bar a{font:inherit;font-size:12.5px;color:var(--ink);background:var(--panel);border:1px solid var(--line);
border-radius:6px;padding:2px 9px;cursor:pointer;text-decoration:none}
.ctx button:hover:not(:disabled),.ctx-bar a:hover{border-color:var(--accent);color:var(--accent)}
.ctx button:disabled{opacity:.45;cursor:default}
.ctx button[aria-pressed=true]{background:var(--accent);border-color:var(--accent);color:var(--panel)}
.ctx-head .ctx-x{border:0;font-size:20px;line-height:1;padding:0 4px;color:var(--muted)}
.ctx-tabs{display:inline-flex;gap:4px;margin-left:auto}
.ctx-warn{margin:8px 12px 0;padding:6px 10px;border-radius:6px;font-size:12.5px;background:var(--warn-bg);color:var(--warn-ink)}
.ctx-warn.bad{background:var(--bad-bg);color:var(--bad-ink)}
.ctx-warn[hidden]{display:none}
.ctx:focus{outline:none}
.ctx-body{position:relative;flex:1;overflow:auto;margin:0;padding:12px 14px;font:13px/1.55 var(--mono);white-space:pre-wrap;word-break:break-word}
.ctx-body:focus{outline:none}
.ctx-body mark{background:var(--mark-bg);color:var(--mark-ink);border-radius:2px;box-shadow:0 0 0 2px var(--mark-bg)}
.ctx-pdf{flex:1;display:flex;min-height:0}
.ctx-pdf[hidden]{display:none}
.ctx-pdf object{flex:1;width:100%;height:100%;border:0}
.ctx-pdf p{margin:12px 14px;color:var(--muted);font-size:13px}
@media (max-width:640px){.ctx{top:auto!important;left:0!important;right:0;bottom:0;width:100%!important;max-width:100%;
height:62vh!important;border-radius:12px 12px 0 0;resize:none}.ctx-head{cursor:default}}
.incident{display:flex;flex-wrap:wrap;gap:10px;align-items:baseline;margin:14px 0;padding:10px 14px;
background:var(--incident-bg);border-left:5px solid var(--incident-line);border-radius:6px}
.incident .tag{font-weight:800;text-transform:uppercase;letter-spacing:.06em;font-size:12px;color:var(--warn-ink)}
.incident .iwhen{font-weight:700;font-variant-numeric:tabular-nums}
.group{font-size:16px;margin:32px 0 0;padding-top:12px;border-top:2px solid var(--ink)}
.note{color:var(--muted);font-size:13px;margin:4px 0 0}
.error{color:var(--bad-ink);background:var(--bad-bg);border-radius:6px;padding:4px 8px;margin:4px 0;font-size:13px}
.hidden{display:none}
@media (max-width:640px){.entry{grid-template-columns:1fr;gap:4px}.when{display:flex;gap:10px;align-items:baseline}}
@media print{.filters,.ctx{display:none}body{background:#fff;color:#000}.entry{break-inside:avoid}
.bates{border-color:#000;color:#000}}
"""

JS = """
(function(){
  var f={injury:document.getElementById('f-injury'),type:document.getElementById('f-type'),
    site:document.getElementById('f-site'),assertion:document.getElementById('f-assertion'),
    q:document.getElementById('f-q'),attn:document.getElementById('f-attn')};
  var entries=[].slice.call(document.querySelectorAll('.entry'));
  var count=document.getElementById('count');
  function has(list,v,sep){return !v||(' '+list.split(sep).join(' ')+' ').indexOf(' '+v+' ')>=0;}
  function apply(){
    var q=f.q.value.trim().toLowerCase(),shown=0;
    entries.forEach(function(el){
      var d=el.dataset,ok=has(d.injury,f.injury.value,' ')&&has(d.type,f.type.value,' ')
        &&(!f.site.value||d.site.split('|').indexOf(f.site.value)>=0)
        &&has(d.assertion,f.assertion.value,' ')&&(!q||d.text.indexOf(q)>=0)
        &&(!f.attn.checked||d.attention==='1');
      el.classList.toggle('hidden',!ok);if(ok)shown++;
    });
    count.textContent=shown+' of '+entries.length+' events shown';
  }
  ['injury','type','site','assertion','attn'].forEach(function(k){f[k].addEventListener('change',apply);});
  f.q.addEventListener('input',apply);apply();
})();
(function(){
  var data=JSON.parse(document.getElementById('ctx-data').textContent);
  function $(id){return document.getElementById(id);}
  var box=$('ctx'),head=$('ctx-head'),title=$('ctx-title'),sub=$('ctx-sub'),warn=$('ctx-warn'),
    body=$('ctx-body'),pdf=$('ctx-pdf'),prev=$('ctx-prev'),next=$('ctx-next'),
    tText=$('ctx-t-text'),tPdf=$('ctx-t-pdf'),open=$('ctx-open');
  var trigger=null,cur=null,span=null,mode='text',drag=null;
  function step(k,d){var i=k.lastIndexOf(':');return k.slice(0,i)+':'+(+k.slice(i+1)+d);}
  function setMode(m){
    mode=m;
    tText.setAttribute('aria-pressed',String(m==='text'));tPdf.setAttribute('aria-pressed',String(m==='pdf'));
    body.hidden=m!=='text';pdf.hidden=m!=='pdf';pdf.textContent='';
    if(m==='pdf'){
      var o=document.createElement('object');o.type='application/pdf';o.data=data.pages[cur].href;
      var fb=document.createElement('p');
      fb.textContent='This browser cannot show the PDF here. Use "Open in new tab" instead.';
      o.appendChild(fb);pdf.appendChild(o);
    }
  }
  function show(k){
    var p=data.pages[k];if(!p)return;
    cur=k;
    title.textContent=p.label;
    sub.textContent=[p.title,p.type,'page '+p.page+(p.pages?' of '+p.pages:'')].filter(Boolean).join(' \\u00b7 ');
    body.textContent='';
    var here=span&&span.page===k,hit=null,msgs=[];
    if(here){
      var a=Math.max(0,Math.min(span.start,p.text.length)),b=Math.max(a,Math.min(span.end,p.text.length));
      hit=document.createElement('mark');hit.textContent=p.text.slice(a,b);
      body.appendChild(document.createTextNode(p.text.slice(0,a)));body.appendChild(hit);
      body.appendChild(document.createTextNode(p.text.slice(b)));
      if(!span.ok)msgs.push('This quote did not match the page text at its cited characters. '
        +'The highlight shows what is actually there.');
    }else body.textContent=p.text;
    if(p.ocr!==null)msgs.push('Text read by OCR'+(p.ocr>=0?' ('+Math.round(p.ocr*100)+'% confidence)':'')
      +'; check it against the PDF.');
    warn.textContent=msgs.join(' ');warn.hidden=!msgs.length;
    warn.className='ctx-warn'+(here&&!span.ok?' bad':'');
    prev.disabled=!data.pages[step(k,-1)];next.disabled=!data.pages[step(k,1)];
    tPdf.disabled=!p.href;open.hidden=!p.href;if(p.href)open.href=p.href;
    setMode(p.href?mode:'text');
    body.scrollTop=hit?Math.max(0,hit.offsetTop-body.clientHeight/3):0;
  }
  function openFor(t){
    var s=data.spans[t.getAttribute('data-ctx')];if(!s)return;
    if(trigger)trigger.setAttribute('aria-expanded','false');
    trigger=t;t.setAttribute('aria-expanded','true');span=s;
    var first=box.hidden&&!box.style.left;
    box.hidden=false;
    if(first){var r=box.getBoundingClientRect();box.style.left=r.left+'px';box.style.right='auto';}
    show(s.page);
    box.focus({preventScroll:true});
  }
  function close(){
    if(box.hidden)return;
    box.hidden=true;pdf.textContent='';
    if(trigger){trigger.setAttribute('aria-expanded','false');trigger.focus({preventScroll:true});trigger=null;}
  }
  document.addEventListener('click',function(ev){
    var t=ev.target.closest&&ev.target.closest('[data-ctx]');
    if(!t||ev.button!==0||ev.ctrlKey||ev.metaKey||ev.shiftKey||ev.altKey)return;
    ev.preventDefault();
    if(t===trigger&&!box.hidden)close();else openFor(t);
  });
  document.addEventListener('keydown',function(ev){
    if(ev.key==='Escape'&&!box.hidden){ev.preventDefault();close();}
  });
  $('ctx-close').addEventListener('click',close);
  prev.addEventListener('click',function(){show(step(cur,-1));});
  next.addEventListener('click',function(){show(step(cur,1));});
  tText.addEventListener('click',function(){setMode('text');show(cur);});
  tPdf.addEventListener('click',function(){setMode('pdf');});
  head.addEventListener('pointerdown',function(ev){
    if(ev.button!==0||ev.target.closest('button')||window.matchMedia('(max-width:640px)').matches)return;
    var r=box.getBoundingClientRect();drag={x:ev.clientX-r.left,y:ev.clientY-r.top};
    head.setPointerCapture(ev.pointerId);
  });
  head.addEventListener('pointermove',function(ev){
    if(!drag)return;
    box.style.left=Math.min(Math.max(0,ev.clientX-drag.x),window.innerWidth-80)+'px';
    box.style.top=Math.min(Math.max(0,ev.clientY-drag.y),window.innerHeight-40)+'px';
  });
  head.addEventListener('pointerup',function(){drag=null;});
  head.addEventListener('pointercancel',function(){drag=null;});
})();
"""

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>{css}</style></head>
<body>
<header>
<h1>Chronology of care <span class="case">· {case_id}</span></h1>
{incident_line}{injuries}
<p class="meta">{meta}</p>
{problems}
</header>
<nav class="filters" aria-label="Filters"><div class="filters-inner">
<label>Injury <select id="f-injury"><option value="">All</option>{injury_options}</select></label>
<label>Type <select id="f-type"><option value="">All</option>{type_options}</select></label>
<label>Body site <select id="f-site"><option value="">All</option>{site_options}</select></label>
<label>Assertion <select id="f-assertion"><option value="">All</option>{assertion_options}</select></label>
<label><input type="search" id="f-q" placeholder="Search quotes and terms" aria-label="Search"></label>
<label><input type="checkbox" id="f-attn"> Needs attention only</label>
<span class="count" id="count">{total} events</span>
</div></nav>
<main>
{rows}
</main>
<aside class="ctx" id="ctx" role="dialog" aria-modal="false" aria-labelledby="ctx-title" tabindex="-1" hidden>
<div class="ctx-head" id="ctx-head"><div><div class="ctx-title" id="ctx-title"></div>
<div class="ctx-sub" id="ctx-sub"></div></div>
<button type="button" class="ctx-x" id="ctx-close" aria-label="Close" title="Close (Esc)">&times;</button></div>
<div class="ctx-bar">
<button type="button" id="ctx-prev">&lsaquo; Prev page</button>
<button type="button" id="ctx-next">Next page &rsaquo;</button>
<span class="ctx-tabs"><button type="button" id="ctx-t-text" aria-pressed="true">Text</button>
<button type="button" id="ctx-t-pdf" aria-pressed="false">PDF</button>
<a id="ctx-open" target="_blank" rel="noopener">Open in new tab &#8599;</a></span>
</div>
<div class="ctx-warn" id="ctx-warn" role="note" hidden></div>
<pre class="ctx-body" id="ctx-body" tabindex="0"></pre>
<div class="ctx-pdf" id="ctx-pdf" hidden></div>
</aside>
<script type="application/json" id="ctx-data">{context}</script>
<script>{js}</script>
</body></html>
"""
