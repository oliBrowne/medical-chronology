"""Page agent: one page in, verified findings out.

The model reads one page and lists what it states: the dates it prints (with
what each date is), and findings with an exact quote. It does not interpret,
grade, or connect pages. Code does the rest:

- the submit tool rejects any quote or date text that is not on the page, so
  the model has to correct it before the answer is accepted;
- each accepted quote becomes an ``EvidenceSpan`` copied from the page itself,
  so it is verbatim by construction;
- dates are resolved by ``resolve_date`` (never by the model), using the
  page's service date as the anchor for dates with no year.

Which date wins as a visit's event date across pages is decided later, in
``stages/timeline.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chronology.agents.loop import AgentResult, run_agent
from chronology.llm import ollama
from chronology.schemas import EvidenceSpan, Finding, Page
from chronology.stages.flags import flag_findings, uncovered_lines
from chronology.stages.tables import vital_findings, vital_table_rows
from chronology.tools.quotes import find_quotes
from chronology.tools.registry import Tool, ToolBox, object_schema
from chronology.tools.resolve_date import resolve_date

DATE_ROLES = ("service_date", "incident_date", "prepared_date", "signature", "print",
              "certification", "dob", "mentioned_event", "other")
CATEGORIES = ("symptom", "exam_finding", "vital", "imaging", "diagnosis", "procedure",
              "medication", "referral", "plan", "history")
ASSERTIONS = ("present", "absent", "possible", "historical")
SUBJECTS = ("patient", "other")
MAX_QUOTE_CHARS = 120

SYSTEM_PROMPT = f"""You read one page from a medical-legal record and list what it states. \
You do not interpret, diagnose, grade severity, or infer causes. Some pages are an attorney's \
case summary: list each factual statement in it the same way (incident facts, claimed injuries, \
history, treatment, questions).

Work in this order, then call submit_page:

1. DATES. List every date printed on the page. Each date is an object with the fields date and role. Copy only the date text exactly as \
printed (e.g. "03/14/2024", or "5/13" if the page prints no year), not the sentence around it. \
Label each with its role: {", ".join(DATE_ROLES)}.
   - service_date: the date the patient was seen or the service was done ("Date of Service", \
"Visit Date", "Exam Date", or a plain "Date:" in the header).
   - incident_date: on a police, crash, store incident report or case summary, the date the \
incident happened ("Date of Crash", "Date of Incident").
   - prepared_date: on a case summary or letter, the date it was prepared ("Date Prepared").
   - signature: when someone signed or e-signed. print: when the page was printed. \
certification: when the record was certified. dob: date of birth.
   - mentioned_event: a date of something described in the text (an earlier visit, an injury).
   - Never treat a signature, print or certification date as the service date.

2. FINDINGS. Each finding is ONE fact with an exact quote, put in its body field: a contiguous \
piece of the page, copied character for character, one sentence or less. Do not paraphrase or join pieces. Cover \
complaints, exam findings, imaging results, diagnoses, procedures, medications, referrals and plans.
   - category: one of {", ".join(CATEGORIES)}.
   - assertion is about the thing the quote describes, NOT about whether the sentence is true. \
Ask: does the page say the thing exists?
       present: the page says it exists or was done (a symptom, a fracture, a measured value, a \
normal result, a medication taken, a procedure performed). "R wrist: Normal", "sensation intact" \
and "cap refill normal" are present: they report a normal result.
       absent: the page says it does NOT exist. "Denies LOC", "No numbness or weakness", \
"No TTP thoracic or lumbar spine", "SLR neg bilat", "no radiation", "no interval displacement" \
and "NKDA" are all absent, even though each sentence is itself a true statement. "None" under \
PMH, Medications or Allergies is absent.
       possible: uncertain ("r/o", "possible", "?"). historical: it happened in the past or \
is prior history.
   - subject: patient, or other if it is about someone else.
   - body_site: the body part as the page writes it, including side words ("left wrist"); \
leave empty if none.
   - date_text: only if the finding names its own date, copied as printed; otherwise leave empty.
   - Every denial or negative statement is its own finding with assertion absent, including each \
item in a list: "Denies head strike, denies LOC, denies back pain" is three findings, with the \
quotes "Denies head strike", "denies LOC" and "denies back pain". "No TTP lumbar spine" and \
"SLR neg" are absent too. Only an explicit negation word makes a finding absent (denies, no, \
not, neg, negative, without). A finding that reports reduced function or a measured limit is \
present, not absent: "flexion limited to 60 deg", "ROM limited by pain", "decreased swelling", \
"mild stiffness" are all present.
   - Copy pain scores, grades and words like "mild" exactly inside the quote; never rate them.
   - Account for every line of the page. Normal and negative results and routine items are \
findings too, so do not skip them: "R wrist: Normal", "NAD", "A&O x3", "sensation intact", \
"NKDA" and "Allergies: none" each get a finding. Vital signs written in a sentence or line \
(blood pressure, heart rate, temperature, SpO2) use the category vital. Vital signs in a table \
are recorded separately by the system: do not list them. For any other table, the quote is a \
whole row exactly as it appears, including the | characters.
   - Before you submit, go through the page from top to bottom and check that every line is \
covered by a finding, a date, or the header. Add any that are missing.

3. facility and provider: copy from the page header if present.

Call submit_page with everything. It keeps every valid item and lists the ones it rejected. If \
any were rejected, call it again with ONLY corrected versions of the rejected items; do not \
resend items that were accepted."""


@dataclass
class PageExtraction:
    page: Page
    status: str  # "finished", "max_steps" or "no_tool_call"
    facility: str | None = None
    provider: str | None = None
    dates: list[dict[str, Any]] = field(default_factory=list)  # text, role, iso, precision, time
    spans: list[EvidenceSpan] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)  # items for the review queue
    flags: dict[str, list[dict[str, str]]] = field(default_factory=dict)  # by finding_id
    uncovered: list[dict[str, Any]] = field(default_factory=list)  # page lines no finding covers
    steps: int = 0
    seconds: float = 0.0  # wall-clock time for this page, set by the pipeline
    trace: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self, include_trace: bool = False) -> dict[str, Any]:
        """Plain JSON-ready dict: each finding joined to its exact quote and location."""
        spans = {s.span_id: s for s in self.spans}
        findings = []
        for f in self.findings:
            span = spans[f.span_ids[0]]
            findings.append({**f.model_dump(), "flags": self.flags.get(f.finding_id, []),
                             "quote": span.quote, "bates_label": span.bates_label,
                             "char_start": span.char_start, "char_end": span.char_end})
        out = {"doc_id": self.page.doc_id, "page_index": self.page.page_index,
               "bates_label": self.page.bates_label, "status": self.status,
               "facility": self.facility, "provider": self.provider, "dates": self.dates,
               "findings": findings, "uncovered_lines": self.uncovered,
               "unresolved": self.unresolved, "steps": self.steps,
               "seconds": round(self.seconds, 1)}
        if include_trace:
            out["trace"] = self.trace
        return out


def _submit_schema() -> dict[str, Any]:
    return object_schema(
        {
            "facility": {"type": "string"},
            "provider": {"type": "string"},
            "dates": {
                "type": "array",
                "items": object_schema(
                    {"date": {"type": "string"}, "role": {"type": "string", "enum": list(DATE_ROLES)}},
                    ["date", "role"],
                ),
            },
            "findings": {
                "type": "array",
                "items": object_schema(
                    {
                        "body": {"type": "string"},  # the exact quote; stored as `quote`
                        "category": {"type": "string", "enum": list(CATEGORIES)},
                        "assertion": {"type": "string", "enum": list(ASSERTIONS)},
                        "subject": {"type": "string", "enum": list(SUBJECTS)},
                        "body_site": {"type": "string"},
                        "date_text": {"type": "string"},
                    },
                    ["body", "category", "assertion"],
                ),
            },
        },
        ["dates", "findings"],
    )


@dataclass
class _Submission:
    """Everything the model has submitted that passed validation, across calls.

    A rejected item never costs the valid ones: they are kept here, and only
    the rejected ones have to be sent again. A later item with the same body
    and category replaces the earlier one (a correction).
    """

    facility: str | None = None
    provider: str | None = None
    dates: dict[tuple[str, str], dict] = field(default_factory=dict)  # (date, role)
    findings: dict[tuple[str, str], dict] = field(default_factory=dict)  # (body, category)
    rejected: list[str] = field(default_factory=list)  # from the latest call only

    def payload(self) -> dict[str, Any]:
        return {"facility": self.facility, "provider": self.provider,
                "dates": list(self.dates.values()), "findings": list(self.findings.values())}


def _date_error(page: Page, d: dict) -> str | None:
    missing = [k for k in ("date", "role") if not d.get(k)]
    if missing:
        return f"missing {missing}; each date has exactly the fields date and role"
    if d["role"] not in DATE_ROLES:
        return f"role must be one of {DATE_ROLES}"
    if not find_quotes(page.text, d["date"]):
        return f"{d['date']!r} is not on the page"
    return None


def _finding_error(page: Page, f: dict) -> str | None:
    missing = [k for k in ("body", "category", "assertion") if not f.get(k)]
    if missing:
        return (f"missing {missing}; the fields are body, category, assertion, subject, "
                f"body_site, date_text")
    errors: list[str] = []
    if f["category"] not in CATEGORIES:
        errors.append(f"category must be one of {CATEGORIES}")
    if f["assertion"] not in ASSERTIONS:
        errors.append(f"assertion must be one of {ASSERTIONS}")
    if f.get("subject", "patient") not in SUBJECTS:
        errors.append(f"subject must be one of {SUBJECTS}")
    if len(f["body"]) > MAX_QUOTE_CHARS:
        errors.append(f"body is over {MAX_QUOTE_CHARS} characters; split it into separate "
                      f"findings, one fact each")
    elif not find_quotes(page.text, f["body"]):
        errors.append("body is not on the page, copy it exactly as written")
    if f.get("date_text") and not find_quotes(page.text, f["date_text"]):
        errors.append(f"date_text {f['date_text']!r} is not on the page")
    return "; ".join(errors) or None


def _submit_tool(page: Page, state: _Submission) -> Tool:
    def submit_page(facility: str | None = None, provider: str | None = None,
                    dates: list[dict] | None = None, findings: list[dict] | None = None) -> dict:
        state.facility = facility or state.facility
        state.provider = provider or state.provider
        rejected: list[str] = []
        for i, d in enumerate(dates or []):
            error = _date_error(page, d)
            if error:
                rejected.append(f"dates[{i}] {str(d.get('date'))[:30]!r}: {error}")
            else:
                state.dates[(d["date"], d["role"])] = d
        for i, f in enumerate(findings or []):
            error = _finding_error(page, f)
            if error:
                rejected.append(f"findings[{i}] {str(f.get('body'))[:40]!r}: {error}")
            else:
                state.findings[(f["body"], f["category"])] = f
        state.rejected = rejected
        if rejected:
            raise ValueError(
                f"{len(state.dates)} dates and {len(state.findings)} findings accepted and kept. "
                f"{len(rejected)} rejected; send ONLY corrected versions of these: "
                + "; ".join(rejected))
        return {"accepted": True, "dates": len(state.dates), "findings": len(state.findings)}

    return Tool(
        name="submit_page",
        description=("Submit dates and findings for this page. Valid items are kept; rejected "
                     "ones are listed so you can resend corrected versions."),
        parameters=_submit_schema(),
        fn=submit_page,
    )


def _assemble(page: Page, payload: dict[str, Any],
              skip: list[tuple[int, int]] = ()) -> PageExtraction:
    """Turn the accepted submission into spans and findings. No model involved.

    ``skip`` holds character ranges the system records itself (vital-sign table
    rows); any model finding that overlaps one is dropped, and the table
    findings are added in its place.
    """
    out = PageExtraction(page=page, status="finished", facility=payload.get("facility") or None,
                         provider=payload.get("provider") or None)

    # Dates the page prints with a year first; then dates mentioned in the text,
    # which may omit the year ("5/13"), are anchored on the service date.
    entries = payload.get("dates") or []
    resolved: dict[int, dict] = {i: resolve_date(d["date"]) for i, d in enumerate(entries)
                                 if d["role"] not in ("mentioned_event", "other")}
    service = None  # the page's event date: its service date, else (incident reports) its incident date
    for role in ("service_date", "incident_date"):
        service = next((resolved[i]["iso"] for i, d in enumerate(entries)
                        if d["role"] == role and i in resolved
                        and resolved[i]["precision"] == "day"), None)
        if service:
            break
    for i, d in enumerate(entries):
        if i not in resolved:
            resolved[i] = resolve_date(d["date"], anchor=service)
    for i, d in enumerate(entries):
        r = resolved[i]
        out.dates.append({"text": d["date"], "role": d["role"],
                          "iso": r["iso"], "precision": r["precision"], "time": r["time"]})
        if r["iso"] is None:
            out.unresolved.append(f"date {d['date']!r} ({d['role']}): {r['error']}")
    signature = next((d["iso"] for d in out.dates
                      if d["role"] == "signature" and d["iso"]), None)
    if service is None:
        out.unresolved.append("no resolvable service date on this page")

    prefix = f"{page.doc_id}:p{page.page_index}"
    used: set[tuple[int, int]] = set()
    for f in payload.get("findings") or []:
        matches = find_quotes(page.text, f["body"])
        start, end = next((m for m in matches if m not in used), matches[0])
        used.add((start, end))
        if any(s < end and e > start for s, e in skip):
            continue  # a table row the system records itself
        n = len(out.findings)
        span = EvidenceSpan(span_id=f"{prefix}:s{n}", doc_id=page.doc_id,
                            page_index=page.page_index, bates_label=page.bates_label,
                            char_start=start, char_end=end, quote=page.text[start:end])

        # A finding that names its own date (the model's date_text, or a
        # mentioned-event date that appears inside the quote) is dated by it.
        date_text = f.get("date_text") or next(
            (d["text"] for d in out.dates
             if d["role"] == "mentioned_event" and d["text"] in span.quote), None)
        event_date = service
        if date_text:
            own = resolve_date(date_text, anchor=service)
            event_date = own["iso"]
            if own["iso"] is None:
                out.unresolved.append(f"finding {n} date {date_text!r}: {own['error']}")

        out.spans.append(span)
        out.findings.append(Finding(
            finding_id=f"{prefix}:f{n}", span_ids=[span.span_id], category=f["category"],
            original_phrase=span.quote, assertion=f["assertion"],
            subject=f.get("subject") or "patient", body_site=f.get("body_site") or None,
            event_date=event_date, document_date=signature))

    table_spans, table_findings = vital_findings(page, service, signature)
    out.spans += table_spans
    out.findings += table_findings
    order = sorted(range(len(out.spans)), key=lambda i: out.spans[i].char_start)
    out.spans = [out.spans[i] for i in order]  # every finding has exactly one span,
    out.findings = [out.findings[i] for i in order]  # so the two lists reorder together
    return out


def extract_page(page: Page, *, chat_fn=ollama.chat, model: str = ollama.DEFAULT_MODEL,
                 max_steps: int = 8, think: str | None = "low") -> PageExtraction:
    """Run the page agent on one page."""
    # One tool: submit_page checks every quote and date against the page itself,
    # so a separate verify tool only cost the model steps (it checked quotes one
    # by one and ran out of steps before submitting).
    state = _Submission()
    toolbox = ToolBox([_submit_tool(page, state)])
    task = (f"Page {page.bates_label or page.page_index} "
            f"({page.page_type or 'type unknown'}):\n\n{page.text}")
    result: AgentResult = run_agent(
        SYSTEM_PROMPT, task, toolbox, finish_tool="submit_page", max_steps=max_steps,
        chat_fn=chat_fn, model=model, think=think)

    if result.status != "finished" and not state.dates and not state.findings:
        return PageExtraction(page=page, status=result.status, steps=result.steps,
                              trace=result.trace,
                              unresolved=[f"page agent did not finish ({result.status})"])

    # Whatever was accepted is kept, even if the model never got every item
    # through. The page is "partial" and the leftovers go to the review queue.
    out = _assemble(page, state.payload(),
                    skip=[(row.start, row.end) for row in vital_table_rows(page.text)])
    if result.status != "finished":
        out.status = "partial"
        out.unresolved.append(f"page agent did not finish ({result.status}); "
                              f"kept the {len(out.findings)} findings accepted so far")
        out.unresolved += [f"rejected and not corrected: {r}" for r in state.rejected]
    out.flags = flag_findings(out.findings, out.spans, page)
    out.uncovered = uncovered_lines(page, out.spans, out.dates, out.facility)
    out.steps, out.trace = result.steps, result.trace
    return out
