"""Parses an uploaded tournament PDF into a flat list of (school, team)
entries worth scouting.

Ground-truthed against a real Tabroom "fieldsort" export (the tournament's
full entry list): it's a genuine PDF table with columns Institution |
Location | Debaters | Entry Code | Mode | Record, which pdfplumber's
extract_tables() parses cleanly. That's tried first.

Critically, a tournament's own entry code (e.g. "Kentucky CV", one letter
per debater) does NOT match opencaselist's own team code for the same team
(e.g. "Kentucky CoVi", two letters per debater) -- the two systems code
teams differently. What *does* match on both is the debaters' last names,
so that's what's carried forward as the real lookup key; team_code is kept
only as a human-readable label for the UI/export.

If a PDF doesn't parse as that table (a different export format), this
falls back to a line-based heuristic for "Team A vs Team B" pairing sheets
or plain entry lists, without debater names -- the scraper falls back to
matching by team_code substring in that case, which is less reliable but
better than nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pdfplumber

_ROUND_RE = re.compile(r"round\s+(\w+)", re.IGNORECASE)
_VS_RE = re.compile(r"\s+(?:vs\.?|v\.)\s+", re.IGNORECASE)
_SIDE_TAG_RE = re.compile(r"\(?\b(aff(?:irmative)?|neg(?:ative)?)\b\)?\.?", re.IGNORECASE)
_TEAM_CODE_RE = re.compile(r"^(?P<school>[A-Za-z][A-Za-z.&'\- ]*?)\s+(?P<code>[A-Za-z]{2,4})$")
_NOISE_RE = re.compile(r"^(page \d+|round \w+:?|pairings?|entries|schematic)\s*$", re.IGNORECASE)


@dataclass
class PairingEntry:
    school_name: str
    team_code: str
    debaters: list[str] = field(default_factory=list)
    opponent_school: str | None = None
    opponent_team_code: str | None = None
    round_label: str | None = None


def _dedupe(entries: list[PairingEntry]) -> list[PairingEntry]:
    seen: dict[tuple[str, str], PairingEntry] = {}
    for entry in entries:
        key = (entry.school_name.lower(), entry.team_code.lower())
        if key not in seen:
            seen[key] = entry
    return list(seen.values())


def _parse_entry_table(pdf_path: str) -> list[PairingEntry] | None:
    """Tries to read a Tabroom-style entry-list table. Returns None if no
    table with an "Institution" column is found anywhere in the PDF."""
    entries: list[PairingEntry] = []
    found_table = False

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if not table or not table[0]:
                    continue
                header = " ".join((cell or "") for cell in table[0]).lower()
                if "institution" not in header:
                    continue
                found_table = True

                for row in table[1:]:
                    if not row or len(row) < 4:
                        continue
                    school_raw, _location, debaters_raw, code_raw = row[0], row[1], row[2], row[3]
                    if not school_raw or not debaters_raw:
                        continue

                    school_name = re.sub(r"\s+", " ", school_raw).strip()
                    debaters_clean = re.sub(r"\s+", " ", debaters_raw).strip()
                    debaters = [name.strip() for name in re.split(r"\s*&\s*", debaters_clean) if name.strip()]
                    if not debaters:
                        continue

                    team_code = re.sub(r"\s+", " ", (code_raw or "").strip())
                    if not team_code:
                        team_code = f"{school_name} {' & '.join(debaters)}"

                    entries.append(PairingEntry(school_name, team_code, debaters))

    return _dedupe(entries) if found_table else None


def _extract_lines(pdf_path: str) -> list[str]:
    lines: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines.extend(line.strip() for line in text.splitlines() if line.strip())
    return lines


def _clean_side(text: str) -> str:
    text = _SIDE_TAG_RE.sub("", text)
    return text.strip(" -\t")


def _split_school_and_code(raw: str) -> tuple[str, str]:
    raw = raw.strip()
    match = _TEAM_CODE_RE.match(raw)
    if match:
        return match.group("school").strip(), raw
    return raw, raw


def _parse_line_based(pdf_path: str) -> list[PairingEntry]:
    """Fallback for PDFs that aren't a parseable entry-list table: handles
    "Team A vs Team B" pairing sheets and plain one-code-per-line entry
    lists. No debater names are available here, so the scraper falls back
    to matching by team_code substring for these entries."""
    lines = _extract_lines(pdf_path)
    entries: list[PairingEntry] = []
    current_round: str | None = None

    for line in lines:
        if _NOISE_RE.match(line):
            round_match = _ROUND_RE.search(line)
            if round_match:
                current_round = f"Round {round_match.group(1)}"
            continue

        round_match = _ROUND_RE.search(line)
        if round_match and _VS_RE.search(line) is None and len(line) < 40:
            current_round = f"Round {round_match.group(1)}"
            continue

        if _VS_RE.search(line):
            left_raw, right_raw = _VS_RE.split(line, maxsplit=1)
            left, right = _clean_side(left_raw), _clean_side(right_raw)
            left_school, left_code = _split_school_and_code(left)
            right_school, right_code = _split_school_and_code(right)

            entries.append(PairingEntry(left_school, left_code, [], right_school, right_code, current_round))
            entries.append(PairingEntry(right_school, right_code, [], left_school, left_code, current_round))
            continue

        match = _TEAM_CODE_RE.match(line)
        if match:
            entries.append(PairingEntry(match.group("school").strip(), line.strip(), [], None, None, current_round))

    return _dedupe(entries)


def parse_pairings_pdf(pdf_path: str) -> list[PairingEntry]:
    table_entries = _parse_entry_table(pdf_path)
    if table_entries:
        return table_entries
    return _parse_line_based(pdf_path)
