# Jev slides for Milestone2_Expert_Witness

## Slide A: fill in the TODOs on "JEV as a Fast Page Classifier"
Speed: ~0.13 s per page; one request asks 3 typed questions (page type, clinical content, new document?)
Cost: $0.042 per million input tokens; 182-page end-to-end run cost about $0.01 (0.92 calls/page)
Reads less: Jev sees only the top 25% of each page; full page re-checked before anything is skipped

## Slide B (new, right after it): "Testing the Page Sorter"
Image: jev-sorter-slide.png (left or top)
Fail-open: a page is skipped only if Jev is confident twice AND code safety nets agree
Tested on 760+ made-up pages (no patient data sent to Jev)
Never-tuned set (278 pages): unsure pages 34 -> 17; 0 clinical pages skipped
Generated test set (174 pages): unsure 15 -> 1; 0 clinical pages skipped
End to end (75 PDFs): page agent reads 48% of the text
Caveat: 0 misses in 63 skips still allows up to ~5%, so a person checks the first real case
