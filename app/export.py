"""Spreadsheet-ready export of a tournament's scouting results.

TSV (tab-separated) pastes directly into a Google Sheets or Excel cell
selection -- that's the "paste and go" format. CSV is offered as a
downloadable file for the same data.
"""

from __future__ import annotations

import csv
import io

from . import crud
from .db import get_session
from .models import Tournament

COLUMNS = [
    "School",
    "Team",
    "Opponent School",
    "Opponent Team",
    "Round",
    "Status",
    "Aff Type",
    "Aff Type Confidence",
    "Country",
    "Country Confidence",
    "Source Title",
    "Source URL",
]


def _rows_for_tournament(tournament: Tournament) -> list[list[str]]:
    db = get_session()
    try:
        rows = []
        for team in tournament.teams:
            record = crud.latest_aff_record(db, team)
            rows.append(
                [
                    team.school_name,
                    team.team_code,
                    team.opponent_school or "",
                    team.opponent_team_code or "",
                    team.round_label or "",
                    record.status if record else "not started",
                    (record.aff_type or "") if record else "",
                    f"{record.aff_type_confidence:.2f}" if record and record.aff_type_confidence is not None else "",
                    (record.country or "") if record else "",
                    f"{record.country_confidence:.2f}" if record and record.country_confidence is not None else "",
                    (record.source_title or "") if record else "",
                    (record.source_url or "") if record else "",
                ]
            )
        return rows
    finally:
        db.close()


def tournament_to_delimited(tournament: Tournament, delimiter: str = "\t") -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\n")
    writer.writerow(COLUMNS)
    writer.writerows(_rows_for_tournament(tournament))
    return buffer.getvalue()
