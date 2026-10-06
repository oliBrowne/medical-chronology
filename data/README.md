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
