"""Minimal client for TypeSafe's Jev decision model.

Standard library only, so it runs without installing the TypeSafe SDK.
API reference: https://docs.typesafe.ai/api

Never send real record text unless zero data retention is enabled on the
TypeSafe org (see README, "Patient data").
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

API_URL = "https://api.typesafe.ai/v1/systemone"
# Pin a concrete version for evaluations; "jev-latest" can change underneath us.
DEFAULT_MODEL = "jev-1.13.0"
PRICE_PER_MILLION_INPUT_TOKENS = 0.042  # USD, output tokens are free

PAGE_TYPES: dict[str, str] = {
    "ed_note": "Emergency department visit note or triage record",
    "office_visit": "Clinic, urgent care or specialist visit / progress note",
    "therapy_note": "Physical, occupational or chiropractic therapy note",
    "imaging_report": "Radiology or imaging report (X-ray, CT, MRI, ultrasound)",
    "procedure_report": "Operative, injection or other procedure report",
    "medication_record": "Medication list, prescription or pharmacy record",
    "billing": "Bill, invoice, itemized charges, claim form or ledger",
    "fax_cover": "Fax cover sheet or transmittal page with no clinical content",
    "records_admin": "Records request, certification of records, authorization or other administrative form",
    "lab_result": "Laboratory or pathology result (blood work, urinalysis, cultures)",
    "ems_report": "Ambulance or EMS patient care report",
    "patient_form": "Form filled in by or for the patient: intake questionnaire, pain diagram, employer injury report, work-status or disability form",
    "legal_correspondence": "Letter or filing from an attorney, insurer or court (demand letter, subpoena, claim correspondence)",
    "education_handout": "Generic patient-education handout or home-care instructions not specific to this patient",
    "other": "None of the above, or unclear",
}

# The first ten labels, as used in the first tests; kept so old runs can be
# repeated and compared.
PAGE_TYPES_V1: dict[str, str] = {
    k: v for k, v in PAGE_TYPES.items()
    if k not in {"lab_result", "ems_report", "patient_form", "legal_correspondence", "education_handout"}
}


# The same 15 labels with sharper wording: what each includes and what it does
# not, written from the mix-ups seen in testing (discharge instructions read
# as a handout, a phone note read as "other", a clinical page with a fax
# header line read as a fax cover, a blank page read as records admin).
PAGE_TYPES_DETAILED: dict[str, str] = {
    "ed_note": ("Emergency department record for this patient's visit: triage, ED physician or nurse "
                "note, or ED discharge instructions naming this visit's diagnosis or prescriptions"),
    "office_visit": ("Clinic, urgent care, primary care or specialist visit or progress note, including a "
                     "telephone, portal or nurse-call encounter about this patient's care"),
    "therapy_note": "Physical, occupational or chiropractic therapy evaluation, daily note, flowsheet or plan of care",
    "imaging_report": "Radiology or imaging report (X-ray, CT, MRI, ultrasound) with findings or an impression",
    "procedure_report": ("Operative, injection, nerve block or other procedure report, including the consent "
                         "or anesthesia record for that procedure"),
    "medication_record": ("Medication list, prescription, pharmacy printout or medication administration "
                          "record (MAR)"),
    "billing": ("Bill, invoice, itemized charges, claim form (CMS-1500, UB-04), explanation of benefits or "
                "account ledger: charges and codes, no written clinical notes"),
    "fax_cover": ("Fax cover or transmittal sheet itself: sender, recipient, page count, confidentiality "
                  "notice. Not a clinical page that only has a fax header line printed across the top"),
    "records_admin": ("Administrative page about the records themselves: records request, custodian "
                      "certification or affidavit, HIPAA authorization, release-of-information log, or an "
                      "index of the records produced"),
    "lab_result": "Laboratory or pathology result (blood work, urinalysis, cultures, biopsy)",
    "ems_report": "Ambulance or EMS patient care report",
    "patient_form": ("Form filled in by or for the patient: intake questionnaire, pain diagram, employer "
                     "injury report, work-status or disability form"),
    "legal_correspondence": ("Letter or filing from an attorney, insurer or court (demand letter, subpoena, "
                             "claim correspondence)"),
    "education_handout": ("Generic printed patient-education material (about a condition, exercises, home "
                          "care) that does not mention this patient's visit, diagnosis or prescriptions"),
    "other": "Fits none of the types above: a blank or separator page, an image placeholder, or unreadable text",
}

# Five more labels for pages that kept landing in "other" on the held-out
# pages. None of them is a type that can be held back from the page agent;
# they only give the page agent a better hint. Tests score them as "other".
EXTRA_PAGE_TYPES: dict[str, str] = {
    "inpatient_record": ("Inpatient hospital record: admission history and physical, progress note on the "
                         "ward, hospital course or discharge summary"),
    "flowsheet": "Nursing flowsheet or vital-signs chart: rows of times with blood pressure, pulse, pain score",
    "police_report": "Police, incident or traffic crash report",
    "admin_letter": "Letter or notice about appointments, missed visits, scheduling or an account",
    "blank_or_separator": ("Blank page, separator or cover sheet inside a production, 'continued' page, or a "
                           "page holding only a signature"),
}
PAGE_TYPES_EXTENDED: dict[str, str] = {
    **{k: v for k, v in PAGE_TYPES_DETAILED.items() if k != "other"},
    **EXTRA_PAGE_TYPES,
    "other": "Fits none of the types above, or unreadable text",
}


def load_api_key(env_file: Path | None = None) -> str:
    """Read TYPESAFE_API_KEY from the environment, falling back to a .env file."""
    key = os.environ.get("TYPESAFE_API_KEY")
    if key:
        return key
    env_file = env_file or Path(".env")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "TYPESAFE_API_KEY" and value.strip():
                return value.strip().strip('"').strip("'")
    raise SystemExit("TYPESAFE_API_KEY is not set. Add it to .env (see .env.example).")


def page_type_question(labels: dict[str, str] = PAGE_TYPES) -> dict:
    return {
        "type": "choice",
        "instructions": (
            "This is the text of one page from a set of medical-legal records. "
            "Which kind of page is it?"
        ),
        "criteria": dict(labels),
    }


def ask(state: str | dict, questions: dict, api_key: str,
        model: str = DEFAULT_MODEL, retries: int = 4, timeout: float = 60) -> dict:
    """POST one request to Jev and return the parsed JSON response.

    Retries with exponential backoff on 429 (rate limit) and 529 (overloaded).
    """
    body = json.dumps({"model": model, "state": state, "questions": questions}).encode()
    request = urllib.request.Request(
        API_URL,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as err:
            if err.code in (429, 529) and attempt < retries:
                time.sleep(2 ** (attempt + 1))
                continue
            detail = err.read().decode(errors="replace")[:500]
            raise RuntimeError(f"Jev returned HTTP {err.code}: {detail}") from err
    raise AssertionError("unreachable")


def top_probability(answer: dict) -> float:
    """Probability Jev gave its chosen option (not TypeSafe's `confidence`,
    which is computed from the whole distribution)."""
    probs = answer.get("probabilities")
    if isinstance(probs, dict):
        return float(probs[answer["choice"]])
    if isinstance(probs, list):  # tolerate [{"option": ..., "probability": ...}]
        for item in probs:
            if item.get("option") == answer["choice"]:
                return float(item["probability"])
    raise ValueError(f"Unrecognised probabilities shape: {probs!r}")


def estimated_cost(input_tokens: int) -> float:
    return input_tokens / 1_000_000 * PRICE_PER_MILLION_INPUT_TOKENS
