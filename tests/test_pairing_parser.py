from app import pairing_parser


def test_vs_pairing_splits_school_and_code(monkeypatch):
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
    lines = ["Georgetown KM", "Michigan State FM"]
    monkeypatch.setattr(pairing_parser, "_extract_lines", lambda path: lines)

    entries = pairing_parser.parse_pairings_pdf("fake.pdf")

    assert len(entries) == 2
    assert all(e.opponent_school is None for e in entries)


def test_dedupes_repeated_entries(monkeypatch):
    lines = ["Georgetown KM", "Georgetown KM", "Georgetown KM vs Michigan FM"]
    monkeypatch.setattr(pairing_parser, "_extract_lines", lambda path: lines)

    entries = pairing_parser.parse_pairings_pdf("fake.pdf")

    codes = [e.team_code for e in entries]
    assert codes.count("Georgetown KM") == 1
