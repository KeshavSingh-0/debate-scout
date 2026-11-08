from pathlib import Path

from app import pairing_parser

EXAMPLE_PDF = Path(__file__).resolve().parent.parent / "example" / "tabroom.pdf"


def test_vs_pairing_splits_school_and_code(monkeypatch):
    monkeypatch.setattr(pairing_parser, "_parse_entry_table", lambda path: None)
    lines = ["Round 3", "Georgetown KM vs Michigan State FM (Aff)"]
    monkeypatch.setattr(pairing_parser, "_extract_lines", lambda path: lines)

    entries = pairing_parser.parse_pairings_pdf("fake.pdf")
    by_code = {e.team_code: e for e in entries}

    assert len(entries) == 2
    assert by_code["Georgetown KM"].school_name == "Georgetown"
    assert by_code["Georgetown KM"].opponent_team_code == "Michigan State FM"
    assert by_code["Georgetown KM"].opponent_school == "Michigan State"
    assert by_code["Georgetown KM"].round_label == "Round 3"

    assert by_code["Michigan State FM"].opponent_team_code == "Georgetown KM"


def test_entry_list_without_opponents(monkeypatch):
    monkeypatch.setattr(pairing_parser, "_parse_entry_table", lambda path: None)
    lines = ["Georgetown KM", "Michigan State FM"]
    monkeypatch.setattr(pairing_parser, "_extract_lines", lambda path: lines)

    entries = pairing_parser.parse_pairings_pdf("fake.pdf")

    assert len(entries) == 2
    assert all(e.opponent_school is None for e in entries)
    assert all(e.debaters == [] for e in entries)


def test_dedupes_repeated_entries(monkeypatch):
    monkeypatch.setattr(pairing_parser, "_parse_entry_table", lambda path: None)
    lines = ["Georgetown KM", "Georgetown KM", "Georgetown KM vs Michigan FM"]
    monkeypatch.setattr(pairing_parser, "_extract_lines", lambda path: lines)

    entries = pairing_parser.parse_pairings_pdf("fake.pdf")

    codes = [e.team_code for e in entries]
    assert codes.count("Georgetown KM") == 1


def test_real_tabroom_entry_list_table():
    """Ground-truth test against a real Tabroom 'fieldsort' entry-list PDF."""
    entries = pairing_parser.parse_pairings_pdf(str(EXAMPLE_PDF))
    by_school = {}
    for e in entries:
        by_school.setdefault(e.school_name, []).append(e)

    assert len(entries) > 100
    assert "Kentucky" in by_school

    kentucky_cv = next(e for e in by_school["Kentucky"] if e.debaters == ["Coale", "Villarreal"])
    assert kentucky_cv.team_code == "Kentucky CV"

    # The tournament's own entry code ("Kentucky CV") deliberately does NOT
    # match opencaselist's team code for the same team ("Kentucky CoVi") --
    # debater last names are the key that matches across both systems.
    assert kentucky_cv.team_code != "Kentucky CoVi"
