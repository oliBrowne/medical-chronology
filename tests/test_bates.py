import pytest

from chronology.bates import find_stamps, parse_filename


@pytest.mark.parametrize(
    "name, prefix, start, end, label0",
    [
        ("DOE 000001-55 - Hospital records.pdf", "DOE", 1, 55, "DOE 000001"),
        ("DOE 000018-1021 - Hospital recs.pdf", "DOE", 18, 1021, "DOE 000018"),
        ("Roe 002888-002894   2024.03.07 TO 2024.05.01-REHAB-BR-$1,000.pdf", "Roe", 2888, 2894, "Roe 002888"),
        ("DOE 006966 - EMS form.pdf", "DOE", 6966, 6966, "DOE 006966"),
        ("DOE 007018 - films 1 RAD0001-20250101T000000Z-3-002.zip", "DOE", 7018, 7018, "DOE 007018"),
        ("A.B 000001-4 - Crash Report-123456789.pdf", "A.B", 1, 4, "A.B 000001"),
    ],
)
def test_parse_filename(name, prefix, start, end, label0):
    r = parse_filename(name)
    assert (r.prefix, r.start, r.end) == (prefix, start, end)
    assert r.label(0) == label0
    assert r.label(r.page_count - 1).endswith(f"{end:06d}")


@pytest.mark.parametrize(
    "name",
    [
        "Complaint - endorsed20250707.PDF",
        "Response to Interrogatories - Set One.pdf",
        "2.16.840.1.114151-001.15297321144003390955",
    ],
)
def test_parse_filename_without_bates(name):
    assert parse_filename(name) is None


def test_label_out_of_range():
    r = parse_filename("DOE 000001-55 - x.pdf")
    with pytest.raises(IndexError):
        r.label(55)


def test_end_before_start_is_an_error():
    with pytest.raises(ValueError):
        parse_filename("DOE 000100-50 - x.pdf")


def test_find_stamps():
    text = "CONSULTATION NOTES\n...\nDOE 000003\nPrint Dt/Tm: 1/2/2025 MRN: 1234567"
    assert find_stamps(text, "DOE") == [3]
    assert find_stamps("doe000004 and DOE 000005", "DOE") == [4, 5]
    assert find_stamps("MRN 1234567", "DOE") == []
