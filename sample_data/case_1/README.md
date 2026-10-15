# Sample parsed inputs (fictional)

Everything here is made up: the patient, the providers, the case. The files look like marker output: Markdown, tables, `{n}----` page breaks, and a Bates number at the bottom of each medical-records page.

| File | Input type | What's in it |
|---|---|---|
| `case_summary.md` | Case summary | What the attorney claims: injuries, history, treatment, money, questions for the reviewing physician |
| `incident_report.md` | Incident report | Police crash report and EMS refusal: mechanism, time, what was said at the scene |
| `medical_records.md` | Medical records | 9 encounters, 2022–2024, from 6 providers, one per Bates page, not in date order |
| `expected_output.json` | Answer key | The visits, example findings, and 12 planted problems the pipeline should catch |

## Planted problems

- **Prior injury:** a 2022 chiropractor visit for neck and back pain, which the case summary and the PT note both deny.
- **Late-appearing injury:** back pain is denied on the day of the crash and first recorded 14 days later, after the patient helped a friend move.
- **Left/right conflicts:**
  - The police and EMS record the left shoulder; the ER records the right.
  - One orthopedics note gives the right shoulder in the exam but the left in its diagnosis.
- **Wear-and-tear findings:** degenerative (age-related) changes on the neck MRI and the shoulder images.
- **Gap in care:** 91 days with no treatment (June to September 2024).
- **Case summary wrong:** it says she went by ambulance (she refused) and had back pain at the ER (she denied it).
- **Copy-pasted text:** identical assessment text in two PT notes.
- **Wrong dates on the page:** print, e-signature and certification dates that aren't the visit date.
