"""Orchestrates one tournament run: for every (school, team) entry parsed
from the uploaded pairings PDF, skip it if already scouted, otherwise
scrape -> condense -> classify -> store, reporting progress as it goes.

Runs scrapes concurrently (bounded by settings.scrape_concurrency) inside a
single opencaselist login session, so re-uploading a pairings PDF with a few
new entries added only processes the new teams, not the whole tournament
again.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from . import crud
from .config import settings
from .db import get_session
from .docx_parser import extract_condensed_text as extract_docx_text
from .jev_client import classify_aff, verify_api_key
from .models import AffRecord, JobStatus, Team
from .pairing_parser import PairingEntry
from .pdf_card_parser import extract_condensed_text as extract_pdf_text
from .scraper import OpenCaselistSession, ScrapeError
from .schemas import ProgressEvent, StageEvent

ProgressCallback = Callable[[ProgressEvent], Awaitable[None]]
StageCallback = Callable[[StageEvent], Awaitable[None]]


async def run_tournament_pipeline(
    tournament_id: int,
    entries: list[PairingEntry],
    caselist_slug: str,
    opencaselist_username: str,
    opencaselist_password: str,
    jev_api_key: str,
    on_progress: ProgressCallback,
    on_stage: StageCallback,
) -> None:
    async def stage(name: str, status: str, detail: str | None = None) -> None:
        await on_stage(StageEvent(tournament_id=tournament_id, stage=name, status=status, detail=detail))

    # Checked up front, before scraping anything: a bad Jev key or a bad
    # opencaselist login would otherwise only surface after wasting time (and,
    # for a bad Jev key, nothing is spent yet either -- this check sends no
    # state or questions, so it costs no Jev tokens).
    await stage("jev_check", "running")
    try:
        await asyncio.to_thread(verify_api_key, jev_api_key)
    except Exception as exc:
        await stage("jev_check", "error", str(exc))
        return
    await stage("jev_check", "success")

    team_jobs: list[tuple[Team, AffRecord]] = []

    db = get_session()
    try:
        tournament = crud.tournament_by_id(db, tournament_id)
        if tournament is None:
            raise ValueError(f"Tournament {tournament_id} not found")

        for entry in entries:
            team, _created = crud.get_or_create_team(
                db,
                tournament,
                entry.school_name,
                entry.team_code,
                entry.debaters,
                entry.opponent_school,
                entry.opponent_team_code,
                entry.round_label,
            )
            if crud.has_completed_aff_record(db, team):
                await on_progress(
                    ProgressEvent(
                        tournament_id=tournament_id,
                        team_id=team.id,
                        status=JobStatus.SKIPPED_CACHED.value,
                        detail="Already scouted in an earlier run",
                    )
                )
                continue
            record = crud.create_aff_record(db, team)
            team_jobs.append((team, record))
    finally:
        db.close()

    if not team_jobs:
        await stage("scraping", "success", "No new teams to scout -- everything was already scouted")
        return

    download_root = settings.upload_path / f"tournament_{tournament_id}_scrapes"
    semaphore = asyncio.Semaphore(settings.scrape_concurrency)

    await stage("opencaselist_login", "running")
    try:
        async with OpenCaselistSession(opencaselist_username, opencaselist_password, download_root) as session:
            await stage("opencaselist_login", "success")
            await stage("scraping", "running", f"0/{len(team_jobs)} scouted")

            async def process(team: Team, record: AffRecord) -> None:
                async with semaphore:
                    await _process_team(
                        tournament_id, team, record, session, caselist_slug, jev_api_key, on_progress
                    )

            await asyncio.gather(*(process(team, record) for team, record in team_jobs))
            await stage("scraping", "success")
    except ScrapeError as exc:
        await stage("opencaselist_login", "error", str(exc))
        return


async def _process_team(
    tournament_id: int,
    team: Team,
    record: AffRecord,
    session: OpenCaselistSession,
    caselist_slug: str,
    jev_api_key: str,
    on_progress: ProgressCallback,
) -> None:
    db = get_session()
    try:

        async def set_status(status: str, **fields) -> None:
            fresh = db.get(AffRecord, record.id)
            crud.update_aff_record(db, fresh, status=status, **fields)
            await on_progress(
                ProgressEvent(
                    tournament_id=tournament_id,
                    team_id=team.id,
                    status=status,
                    detail=fields.get("error_message"),
                )
            )

        await set_status(JobStatus.SCRAPING.value)
        try:
            debaters = [name.strip() for name in team.debaters.split("&") if name.strip()]
            scraped = await session.scrape_team_aff(
                caselist_slug=caselist_slug,
                school_name=team.school_name,
                team_code=team.team_code,
                debaters=debaters,
            )
        except ScrapeError as exc:
            await set_status(JobStatus.ERROR.value, error_message=str(exc))
            return

        await set_status(
            JobStatus.PARSING.value, source_title=scraped.title, source_url=scraped.source_url
        )
        try:
            path = Path(scraped.local_path)
            if path.suffix.lower() == ".docx":
                condensed = extract_docx_text(scraped.local_path)
            elif path.suffix.lower() == ".pdf":
                condensed = extract_pdf_text(scraped.local_path)
            else:
                raise ValueError(f"Unsupported file type: {path.suffix}")
        except Exception as exc:
            await set_status(JobStatus.ERROR.value, error_message=f"Could not parse downloaded file: {exc}")
            return

        await set_status(JobStatus.CLASSIFYING.value, condensed_text=condensed)
        try:
            result = await asyncio.to_thread(classify_aff, condensed, jev_api_key)
        except Exception as exc:
            await set_status(JobStatus.ERROR.value, error_message=f"Jev classification failed: {exc}")
            return

        await set_status(
            JobStatus.DONE.value,
            aff_type=result.aff_type,
            aff_type_confidence=result.aff_type_confidence,
            country=result.country,
            country_confidence=result.country_confidence,
        )
    finally:
        db.close()
