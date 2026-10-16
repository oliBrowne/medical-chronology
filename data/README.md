# data/

Put case records here **on your own machine only**. Everything in this folder
except this README is ignored by git, and CI fails if a PDF, ZIP, DOCX or
DICOM file is ever committed anywhere in the repo.

Suggested local layout, mirroring the shared Dropbox `Data` folder:

```
data/
  <case-name>/
    <PREFIX> 000001-000055 - <source> records.pdf
    ...
```

The pipeline reads Bates ranges from these filenames (see
`src/chronology/bates.py`), so keep the original Dropbox filenames.

Do not paste record text into issues, PRs, commit messages or notebooks that
get committed.

## umls/

`data/umls/snomed_<release>.sqlite` is the local SNOMED CT search index, built
from your own UMLS download with `python scripts/umls/build_snomed_index.py
<umls-<release>-metathesaurus-full.zip>`. It is licensed UMLS content: keep it
here (gitignored), never commit or share it; each person builds their own.
