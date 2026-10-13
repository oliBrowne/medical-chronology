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
