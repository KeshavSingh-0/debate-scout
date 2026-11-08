"""Parses an uploaded tournament PDF (pairings sheet or entry list) into a flat
list of (school, team code) entries worth scouting.

Policy/LD-style team codes are conventionally "<school> <debater initials>",
e.g. "Georgetown KM" or "Wake Forest EFM" -- a school name followed by 1-4
trailing capital letters. We lean on that convention to split a team code
back into a school name, since tournament documents rarely label the two
separately.

Two input shapes are supported, auto-detected per PDF:

1. Pairing sheets: lines containing "vs" / "v." between two team codes,
   optionally with an "Aff"/"Neg" tag and a "Round N" heading above them.
2. Entry lists: one team code per line (optionally grouped under a school
   heading), with no opponent given.

This is necessarily a best-effort, format-tolerant parser since tournament
PDFs aren't standardized. If a real sample export doesn't parse cleanly,
the regexes below are the first place to adjust.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pdfplumber

_ROUND_RE = re.compile(r"round\s+(\w+)", re.IGNORECASE)
_VS_RE = re.compile(r"\s+(?:vs\.?|v\.)\s+", re.IGNORECASE)
_SIDE_TAG_RE = re.compile(r"\(?\b(aff(?:irmative)?|neg(?:ative)?)\b\)?\.?", re.IGNORECASE)
_TEAM_CODE_RE = re.compile(r"^(?P<school>[A-Za-z][A-Za-z.&'\- ]*?)\s+(?P<code>[A-Z]{1,4})$")
_NOISE_RE = re.compile(r"^(page \d+|round \w+:?|pairings?|entries|schematic)\s*$", re.IGNORECASE)


@dataclass
class PairingEntry:
    school_name: str
    team_code: str
    opponent_school: str | None = None
    opponent_team_code: str | None = None
    round_label: str | None = None


def _clean_side(text: str) -> str:
    text = _SIDE_TAG_RE.sub("", text)
    return text.strip(" -\t")


def _split_school_and_code(raw: str) -> tuple[str, str]:
    raw = raw.strip()
    match = _TEAM_CODE_RE.match(raw)
    if match:
        return match.group("school").strip(), raw
    return raw, raw


def _extract_lines(pdf_path: str) -> list[str]:
    lines: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines.extend(line.strip() for line in text.splitlines() if line.strip())
    return lines


def parse_pairings_pdf(pdf_path: str) -> list[PairingEntry]:
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

            entries.append(PairingEntry(left_school, left_code, right_school, right_code, current_round))
            entries.append(PairingEntry(right_school, right_code, left_school, left_code, current_round))
            continue

        match = _TEAM_CODE_RE.match(line)
        if match:
            entries.append(PairingEntry(match.group("school").strip(), line.strip(), None, None, current_round))

    return _dedupe(entries)


def _dedupe(entries: list[PairingEntry]) -> list[PairingEntry]:
    seen: dict[tuple[str, str], PairingEntry] = {}
    for entry in entries:
        key = (entry.school_name.lower(), entry.team_code.lower())
        if key not in seen:
            seen[key] = entry
    return list(seen.values())
