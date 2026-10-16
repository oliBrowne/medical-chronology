# Jev slides for Milestone2_Expert_Witness (two slides)

## Slide A: "JEV as a Fast Page Classifier" (existing slide; replace the TODOs)
What Jev is: a typed-decision model. Ask a question with fixed options, get one option + a probability for every option. No free text, no tool loop.
As a classifier, we ask 3 questions per page in one request:
- Page type (20 labels: ED note, office visit, imaging, billing, fax cover, ...)
- Clinical content? (written notes / table of values / none)
- Starts a new document or continues one?
Also picks the best UMLS/SNOMED candidate in normalization.
Speed: ~0.13 s per page. Cost: $0.042 per million input tokens; a 182-page run cost about $0.01 (0.92 calls/page).
Confidence is the routing signal: low probability means the page is read in full.

## Slide B (new, right after it): "Jev as a Page Sorter"
Image: jev-sorter.png (left or top)
Flow: duplicate check -> reuse known forms/bills -> Jev glance (top 25% of page) -> unsure? borrow neighbour or re-ask -> route
Fail-open: a page is skipped only if Jev is confident twice on the FULL page AND code safety nets agree
Results on made-up pages (no patient data sent to Jev):
- Never-tuned set (278 pages): unsure 34 -> 17; 0 clinical pages skipped
- Generated test set (174 pages): unsure 15 -> 1; 0 clinical pages skipped
- End to end (75 PDFs): page agent reads only 48% of the text
Caveat: 0 misses in 63 skips still allows up to ~5%, so a person checks the first real case
