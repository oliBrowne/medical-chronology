"""Generate a few hundred made-up record pages, split into tune and test halves.

Hand-written test pages are few (137) and some were seen while tuning. This
generator writes many more from templates with random details, grouped the way
productions are: a *file* (one PDF) holds one or more *documents*, each of one
or more pages. Every page carries its truth labels by construction:

    id, doc (the file: the unit triage works in), seq (page in the file),
    document (the document id), starts (does this page start a document),
    label (page type, one of jev.PAGE_TYPES), clinical (yes / no),
    category (the template), text

Patient: TESTPATIENT, ALEX. Clinics, providers and firms are "Example ...",
"Sample ..." or "Northside ...". No real names, places or record text.

Traps are mixed in on purpose: clinical comments on fax covers, diagnosis
codes on bills, legal letters that describe injuries, continuation pages with
no header, generic handouts, blank and separator pages, Bates stamps, fax
transmission lines and "Page k of n" counters.

    python scripts/jev/make_pages.py            # writes generated_tune.json and generated_test.json
    python scripts/jev/make_pages.py --seed 11 --files 160

The split is by file, so no document is in both halves.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

HERE = Path(__file__).parent
P = "TESTPATIENT, ALEX"

CLINICS = ["Example Family Medicine", "Sample Orthopedics", "Northside Spine Center", "Example Urgent Care",
           "Sample Neurology Associates", "Example Community Hospital", "Northside Physical Therapy",
           "Sample Chiropractic", "Example Imaging Center", "Northside Pain Management"]
DOCTORS = ["Dr. Example", "Dr. Sample", "Dr. Northside", "Dr. Example-Lee", "Dr. Sample-Ortiz"]
COMPLAINTS = [("neck pain", "cervical strain", "S13.4XXA"), ("low back pain", "lumbar strain", "S39.012A"),
              ("right shoulder pain", "shoulder sprain", "S43.401A"), ("headaches", "post-traumatic headache", "G44.309"),
              ("left knee pain", "knee contusion", "S80.02XA"), ("mid back pain", "thoracic strain", "S29.012A"),
              ("numbness in the left hand", "cervical radiculopathy", "M54.12")]
MEDS = [("ibuprofen", "600 mg"), ("naproxen", "500 mg"), ("cyclobenzaprine", "10 mg"), ("meloxicam", "15 mg"),
        ("gabapentin", "300 mg"), ("acetaminophen", "1000 mg"), ("tramadol", "50 mg"), ("methocarbamol", "750 mg")]
CPTS = [("99203", "New patient visit", 210), ("99213", "Established visit", 145), ("99214", "Established visit, moderate", 205),
        ("97110", "Therapeutic exercise", 48), ("97140", "Manual therapy", 52), ("72141", "MRI cervical spine", 1850),
        ("72100", "X-ray lumbar spine", 165), ("20552", "Trigger point injection", 260), ("98941", "Chiropractic adjustment", 75)]
LABS = [("WBC", "K/uL", 4.0, 10.5), ("Hemoglobin", "g/dL", 12.0, 16.0), ("Platelets", "K/uL", 150, 400),
        ("Sodium", "mmol/L", 135, 145), ("Potassium", "mmol/L", 3.5, 5.1), ("Glucose", "mg/dL", 70, 99),
        ("Creatinine", "mg/dL", 0.6, 1.2)]


class Gen:
    def __init__(self, rng: random.Random):
        self.r = rng

    # small helpers
    def date(self) -> str:
        return f"{self.r.randint(1, 12):02d}/{self.r.randint(1, 28):02d}/2024"

    def pick(self, xs):
        return self.r.choice(xs)

    def complaint(self):
        return self.pick(COMPLAINTS)

    def pain(self) -> int:
        return self.r.randint(3, 9)

    # each template returns a list of (label, clinical, category, text) pages
    def ed_visit(self):
        c, dx, _ = self.complaint()
        d = self.date()
        p1 = (f"{self.pick(CLINICS).upper()} - EMERGENCY DEPARTMENT\nTRIAGE AND PHYSICIAN NOTE\nPatient: {P}   Arrival {d} "
              f"{self.r.randint(10, 23)}:{self.r.randint(10, 59)}\nChief complaint: {c} after a motor vehicle collision.\n"
              f"Pain {self.pain()}/10. BP {self.r.randint(118, 150)}/{self.r.randint(70, 95)} HR {self.r.randint(70, 105)}.")
        pages = [("ed_note", "yes", "ed_note", p1)]
        if self.r.random() < 0.6:   # continuation page, no header
            med, dose = self.pick(MEDS)
            pages.append(("ed_note", "yes", "ed_continuation",
                          f"exam shows tenderness without deformity, neurovascularly intact. Imaging not indicated.\n"
                          f"Assessment: {dx}. Plan: {med} {dose}, ice, follow up with primary care in one week.\n"
                          f"Return for new weakness or numbness. Discharged in stable condition."))
        return pages

    def ed_discharge(self):
        c, dx, _ = self.complaint()
        med, dose = self.pick(MEDS)
        return [("ed_note", "yes", "ed_discharge_instructions",
                 f"DISCHARGE INSTRUCTIONS\nPatient: {P}\nYou were seen today for {c}. Diagnosis: {dx}.\n"
                 f"Take {med} {dose} as directed. Follow up in 3-5 days. Return if symptoms worsen.")]

    def office_visit(self):
        c, dx, _ = self.complaint()
        d = self.date()
        p1 = (f"{self.pick(CLINICS)}\nPROGRESS NOTE   {d}\nPatient: {P}\nS: follow-up for {c}, pain {self.pain()}/10, "
              f"{self.pick(['improving', 'unchanged', 'worse at night', 'better with therapy'])}.\n"
              f"O: {self.pick(['paraspinal tenderness', 'reduced range of motion', 'positive Spurling test', 'normal strength'])}.\n"
              f"A: {dx}.")
        pages = [("office_visit", "yes", "office_visit", p1)]
        if self.r.random() < 0.4:
            pages.append(("office_visit", "yes", "office_continuation",
                          f"P: continue home exercises, {self.pick(MEDS)[0]} as needed, physical therapy twice weekly.\n"
                          f"Work status: modified duty. Return in {self.r.randint(2, 6)} weeks.\nSigned {self.pick(DOCTORS)}"))
        return pages

    def phone_note(self):
        return [("office_visit", "yes", "telephone_encounter",
                 f"TELEPHONE ENCOUNTER   {self.date()}\nPatient {P} called reporting {self.complaint()[0]} is "
                 f"{self.pick(['worse', 'about the same', 'flaring after work'])}. Advised ice and to keep the appointment.")]

    def therapy(self):
        # one visit note per document: consecutive daily notes are separate documents
        c = self.complaint()[0]
        pages = []
        for i in range(1):
            pages.append(("therapy_note", "yes", "therapy_note",
                          f"{self.pick(['NORTHSIDE PHYSICAL THERAPY', 'SAMPLE CHIROPRACTIC'])} - DAILY NOTE\n"
                          f"Patient: {P}   Date: {self.date()}   Visit {i + 3}\nComplaint: {c}, pain {self.pain()}/10.\n"
                          f"Treatment: {self.pick(['97110 exercise 20 min', 'manual therapy 15 min', 'adjustment C5-C6'])}."))
        return pages

    def imaging(self):
        region = self.pick(["CERVICAL SPINE", "LUMBAR SPINE", "RIGHT SHOULDER", "LEFT KNEE"])
        p1 = (f"{self.pick(['MRI', 'X-RAY', 'CT'])} {region}\nPatient: {P}   Exam date {self.date()}\n"
              f"Findings: {self.pick(['mild disc bulge without stenosis', 'no fracture or dislocation', 'small joint effusion', 'straightening of the normal lordosis'])}.")
        pages = [("imaging_report", "yes", "imaging_report", p1)]
        if self.r.random() < 0.3:
            pages.append(("imaging_report", "yes", "imaging_impression_page",
                          f"IMPRESSION:\n1. {self.pick(['No acute abnormality.', 'Mild degenerative change.', 'Muscle spasm likely.'])}\n"
                          f"Electronically signed by {self.pick(DOCTORS)}, Radiology"))
        return pages

    def procedure(self):
        return [("procedure_report", "yes", "procedure_report",
                 f"PROCEDURE NOTE\nPatient: {P}   Date: {self.date()}\nProcedure: "
                 f"{self.pick(['trigger point injection, right trapezius', 'cervical epidural steroid injection C6-C7', 'medial branch block L4-L5'])}.\n"
                 f"Medication: {self.pick(['triamcinolone 40 mg', 'lidocaine 1% 3 mL'])}. Complications: none.")]

    def medication(self):
        rows = "\n".join(f"{self.date()}  {m} {d}  #{self.r.choice([20, 30, 60])}" for m, d in self.r.sample(MEDS, 3))
        return [("medication_record", "yes", "medication_list", f"PHARMACY FILL HISTORY  {P}\n{rows}")]

    def labs(self):
        rows = []
        for name, unit, lo, hi in self.r.sample(LABS, 4):
            v = round(self.r.uniform(lo * 0.8, hi * 1.2), 1)
            flag = " (H)" if v > hi else " (L)" if v < lo else ""
            rows.append(f"{name} {v} {unit}{flag}  ref {lo}-{hi}")
        return [("lab_result", "yes", "lab_result", f"LABORATORY REPORT  {P}  Collected {self.date()}\n" + "\n".join(rows))]

    def bill(self):
        n = self.r.randint(1, 3)
        with_dx = self.r.random() < 0.4
        pages = []
        for i in range(n):
            lines = [f"{self.date()}  {c}  {desc}  ${amt:,.2f}" for c, desc, amt in self.r.sample(CPTS, 3)]
            head = f"{self.pick(CLINICS).upper()} - PATIENT STATEMENT" + (" (continued)" if i else "")
            body = "\n".join(lines)
            clinical = "no"
            if with_dx and i == 0:
                body = f"Diagnosis: {self.complaint()[2]}\n" + body
                clinical = "yes"
            pages.append(("billing", clinical, "billing_dx" if clinical == "yes" else "billing",
                          f"{head}\nAccount {self.r.randint(10000, 99999)}   Guarantor {P}\n{body}\nAmount due ${self.r.randint(40, 900)}.00"))
        return pages

    def eob(self):
        return [("billing", "no", "eob",
                 f"EXPLANATION OF BENEFITS - THIS IS NOT A BILL\nMember {P}   Claim {self.r.randint(100, 999)}-{self.r.randint(1000, 9999)}\n"
                 f"Service {self.date()}  Billed ${self.r.randint(100, 900)}.00  Plan paid ${self.r.randint(50, 400)}.00")]

    def fax_cover(self):
        clinical = self.r.random() < 0.45
        lines = [self.pick(["FAX COVER SHEET", "FACSIMILE TRANSMITTAL", "FAX"]),
                 f"To: {self.pick(['Records Dept', 'Example Law Group', 'Dr. Example'])}   Fax 555-01{self.r.randint(10, 99)}",
                 f"From: {self.pick(CLINICS)}   Pages: {self.r.randint(2, 30)}"]
        if clinical:
            lines.append(f"Comments: {self.pick(['pt called with new numbness in L hand', 'patient reports pain worse since injection', 'please note MRI ordered for radiating pain'])}.")
        lines.append("CONFIDENTIALITY NOTICE: intended only for the named recipient.")
        return [("fax_cover", "yes" if clinical else "no", "fax_clinical_comment" if clinical else "fax_cover", "\n".join(lines))]

    def records_admin(self):
        kind = self.pick(["cert", "auth", "request", "index"])
        text = {
            "cert": f"CERTIFICATION OF RECORDS\nI certify that the attached {self.r.randint(10, 300)} pages are true copies kept in the regular course of business.\nCustodian of Records",
            "auth": f"AUTHORIZATION FOR RELEASE OF INFORMATION\nPatient: {P}\nI authorize release of all records to Example Law Group. Expires one year from signature.",
            "request": f"REQUEST FOR MEDICAL RECORDS\nRe: {P}\nPlease produce all records and billing from 01/01/2019 to present. Fee enclosed.",
            "index": "RECORDS PRODUCED - INDEX\n1. Office notes pp. 1-20\n2. Imaging pp. 21-25\n3. Billing pp. 26-40",
        }[kind]
        return [("records_admin", "no", f"records_{kind}", text)]

    def legal(self):
        clinical = self.r.random() < 0.4
        if clinical:
            c, dx, _ = self.complaint()
            text = (f"Example Law Group\nRe: our client {P}\nDear Adjuster,\nAs a result of the collision our client suffered {dx} "
                    f"with ongoing {c}, treated with physical therapy and medication. We demand the policy limits.")
        else:
            text = (f"Example Law Group\nRe: {P}, claim {self.r.randint(1000, 9999)}\nDear Counsel,\nPlease confirm receipt of the "
                    f"enclosed notice of representation and direct all future correspondence to this office.")
        return [("legal_correspondence", "yes" if clinical else "no", "legal_injuries" if clinical else "legal_letter", text)]

    def handout(self):
        topic = self.pick(["NECK STRAIN", "LOW BACK PAIN", "USING ICE AND HEAT", "HOME EXERCISES FOR YOUR BACK"])
        return [("education_handout", "no", "handout",
                 f"{topic}: WHAT TO KNOW\nMost people improve within a few weeks. Stay gently active. Use ice for 15 minutes at a time.\n"
                 f"Call your doctor if you develop weakness or numbness.")]

    def ems(self):
        return [("ems_report", "yes", "ems_report",
                 f"EMS PATIENT CARE REPORT\nPatient {P}   Incident {self.date()}\nCC: {self.complaint()[0]} after MVC. "
                 f"GCS 15. BP {self.r.randint(120, 150)}/{self.r.randint(70, 90)}. C-collar applied, transported.")]

    def patient_form(self):
        return [("patient_form", "yes", "intake_form",
                 f"NEW PATIENT QUESTIONNAIRE\nName: {P}\nReason for visit: {self.complaint()[0]}\nPain today (0-10): {self.pain()}\n"
                 f"Prior injuries: [ ] none [x] {self.pick(['back strain 2017', 'knee surgery 2015'])}")]

    def inpatient(self):
        c, dx, _ = self.complaint()
        return [("other", "yes", "inpatient_summary",
                 f"DISCHARGE SUMMARY\nPatient: {P}   Admitted {self.date()}   Discharged {self.date()}\n"
                 f"Hospital course: admitted for {dx} and pain control after a collision. Improved, discharged home.")]

    def flowsheet(self):
        rows = "\n".join(f"{h:02d}00  {self.r.randint(115, 145)}/{self.r.randint(70, 90)}  {self.r.randint(65, 100)}  {self.pain()}"
                         for h in (8, 12, 16))
        return [("other", "yes", "flowsheet", f"VITAL SIGNS FLOWSHEET  {P}\nTime  BP  HR  Pain\n{rows}")]

    def police(self):
        return [("other", "yes", "police_report",
                 f"TRAFFIC CRASH REPORT  Case {self.r.randint(10, 99)}-{self.r.randint(1000, 9999)}\nDriver 2 {P} complained of "
                 f"{self.complaint()[0]} at the scene and was transported by EMS.")]

    def appointment(self):
        return [("other", "no", "appointment_letter",
                 f"{self.pick(CLINICS)}\n{P}\nThis is a reminder of your appointment on {self.date()} at 10:30 AM. "
                 f"Please bring your insurance card.")]

    def blank(self):
        return [("other", "no", "blank", self.pick(["THIS PAGE INTENTIONALLY LEFT BLANK", "*** DOCUMENTS FOLLOW ***",
                                                    "- continued on next page -"]))]


TEMPLATES = {  # template -> relative weight
    "ed_visit": 6, "ed_discharge": 2, "office_visit": 8, "phone_note": 2, "therapy": 8, "imaging": 4, "procedure": 2,
    "medication": 3, "labs": 3, "bill": 6, "eob": 2, "fax_cover": 5, "records_admin": 4, "legal": 3, "handout": 2,
    "ems": 1, "patient_form": 2, "inpatient": 2, "flowsheet": 1, "police": 1, "appointment": 1, "blank": 2,
}


def make_file(g: Gen, file_id: str) -> list[dict]:
    """One PDF: 1-4 documents, stamps and counters added like a production."""
    names, weights = zip(*TEMPLATES.items())
    pages = []
    bates = g.r.randint(1, 900000)
    faxed = g.r.random() < 0.3
    for d in range(g.r.choices([1, 2, 3, 4], [4, 3, 2, 1])[0]):
        tmpl = g.r.choices(names, weights)[0]
        doc_pages = getattr(g, tmpl)()
        counted = len(doc_pages) > 1 and g.r.random() < 0.4
        for k, (label, clinical, category, text) in enumerate(doc_pages):
            if counted:
                text += f"\nPage {k + 1} of {len(doc_pages)}"
            if faxed:
                text = (f"{g.date()} {g.r.randint(8, 17):02d}:{g.r.randint(0, 59):02d} FROM 555-01{g.r.randint(10, 99)} "
                        f"P.{len(pages) + 1:03d}\n" + text)
            if g.r.random() < 0.5:
                text += f"\nTEST {bates + len(pages):06d}"
            pages.append({"id": f"{file_id}-p{len(pages) + 1:02d}", "doc": file_id, "seq": len(pages) + 1,
                          "document": f"{file_id}-d{d + 1}", "starts": k == 0, "label": label,
                          "clinical": clinical, "category": category, "text": text})
    return pages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=2024)
    parser.add_argument("--files", type=int, default=150)
    args = parser.parse_args()
    g = Gen(random.Random(args.seed))
    files = [make_file(g, f"gen{i + 1:03d}") for i in range(args.files)]
    order = list(range(len(files)))
    random.Random(args.seed + 1).shuffle(order)
    halves = {"tune": sorted(order[: len(order) // 2]), "test": sorted(order[len(order) // 2:])}
    for name, idx in halves.items():
        pages = [p for i in idx for p in files[i]]
        out = HERE / f"generated_{name}.json"
        out.write_text("[\n" + ",\n".join("  " + json.dumps(p) for p in pages) + "\n]\n", newline="\n")
        clinical = sum(p["clinical"] == "yes" for p in pages)
        print(f"{out.name}: {len(pages)} pages in {len(idx)} files, "
              f"{sum(p['starts'] for p in pages)} documents, {clinical} clinical")


if __name__ == "__main__":
    main()
