# Sample parsed inputs: case 3 (fictional, messy dates)

`case_2` with its dates deliberately damaged, to test what the pipeline does when dates are not clean. Same patient, providers and clinical text as `case_2`, so the findings answer key in `../case_2/expected_output.json` still applies. Only `medical_records.md` is included; there is no case summary or incident report.

| Page | What was done to its dates |
|---|---|
| BELL 000101 | Letter O for 0 in the service date, lowercase L for 1 in the DOB, a space before a separator, a two-digit year |
| BELL 000102 | Service date blank; signature written `5-16-2024` |
| BELL 000103 | Service date in long form (`June 20, 2024`); an unlabeled fax stamp |
| BELL 000104 | New page: the rest of the 06/20 visit, with no date at all, plus a form revision stamp (`03/04/24`) |
| BELL 000105 | Service date missing its year (`02/11`) |

`expected_output.json` lists each corruption and what the pipeline should do with it. The rule it tests: fix what can be fixed in code and flag it, show candidates without silently adopting them, and never drop a finding because its page has no usable date.
