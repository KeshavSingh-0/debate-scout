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
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from . import crud
from .config import settings
from .db import get_session
from .debug_log import current_tournament_id
from .docx_parser import extract_condensed_text as extract_docx_text
from .jev_client import classify_aff, verify_api_key
from .models import AffRecord, JobStatus, Team
from .pairing_parser import PairingEntry
from .pdf_card_parser import extract_condensed_text as extract_pdf_text
from .scraper import OpenCaselistSession, ScrapeError
from .schemas import ProgressEvent, StageEvent

logger = logging.getLogger(__name__)

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
    current_tournament_id.set(tournament_id)

    async def stage(name: str, status: str, detail: str | None = None) -> None:
        await on_stage(StageEvent(tournament_id=tournament_id, stage=name, status=status, detail=detail))

    # Checked up front, before scraping anything: a bad Jev key or a bad
    # opencaselist login would otherwise only surface after wasting time (and,
    # for a bad Jev key, nothing is spent yet either -- this check sends no
    # state or questions, so it costs no Jev tokens).
    logger.info("tournament_id=%s: verifying Jev API key", tournament_id)
    await stage("jev_check", "running")
    try:
        await asyncio.to_thread(verify_api_key, jev_api_key)
    except Exception as exc:
        logger.warning("tournament_id=%s: Jev API key check failed: %s", tournament_id, exc)
        await stage("jev_check", "error", str(exc))
        return
    logger.info("tournament_id=%s: Jev API key OK", tournament_id)
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
                logger.debug("tournament_id=%s: team_id=%s already scouted, skipping", tournament_id, team.id)
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

    logger.info(
        "tournament_id=%s: %d of %d entries need scraping (rest already scouted)",
        tournament_id,
        len(team_jobs),
        len(entries),
    )

    if not team_jobs:
        await stage("scraping", "success", "No new teams to scout -- everything was already scouted")
        return

    download_root = settings.upload_path / f"tournament_{tournament_id}_scrapes"
    semaphore = asyncio.Semaphore(settings.scrape_concurrency)

    logger.info("tournament_id=%s: logging into opencaselist", tournament_id)
    await stage("opencaselist_login", "running")
    try:
        async with OpenCaselistSession(opencaselist_username, opencaselist_password, download_root) as session:
            logger.info("tournament_id=%s: opencaselist login OK", tournament_id)
            await stage("opencaselist_login", "success")
            await stage("scraping", "running", f"0/{len(team_jobs)} scouted")

            async def process(team: Team, record: AffRecord) -> None:
                async with semaphore:
                    await _process_team(
                        tournament_id, team, record, session, caselist_slug, jev_api_key, on_progress
                    )

            await asyncio.gather(*(process(team, record) for team, record in team_jobs))
            logger.info("tournament_id=%s: scraping pass complete", tournament_id)
            await stage("scraping", "success")
    except ScrapeError as exc:
        logger.warning("tournament_id=%s: opencaselist login failed: %s", tournament_id, exc)
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
    team_label = f"{team.school_name} {team.team_code}"
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

        try:
            logger.debug("team_id=%s (%s): scraping", team.id, team_label)
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
                logger.warning("team_id=%s (%s): scrape failed: %s", team.id, team_label, exc)
                await set_status(JobStatus.ERROR.value, error_message=str(exc))
                return
            logger.debug(
                "team_id=%s (%s): scraped %r from %s", team.id, team_label, scraped.title, scraped.source_url
            )

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
                logger.warning("team_id=%s (%s): failed to parse downloaded file: %s", team.id, team_label, exc)
                await set_status(JobStatus.ERROR.value, error_message=f"Could not parse downloaded file: {exc}")
                return
            logger.debug("team_id=%s (%s): condensed to %d chars", team.id, team_label, len(condensed))

            await set_status(JobStatus.CLASSIFYING.value, condensed_text=condensed)
            try:
                result = await asyncio.to_thread(classify_aff, condensed, jev_api_key)
            except Exception as exc:
                logger.warning("team_id=%s (%s): Jev classification failed: %s", team.id, team_label, exc)
                await set_status(JobStatus.ERROR.value, error_message=f"Jev classification failed: {exc}")
                return
            logger.info(
                "team_id=%s (%s): classified aff_type=%s country=%s",
                team.id,
                team_label,
                result.aff_type,
                result.country,
            )

            await set_status(
                JobStatus.DONE.value,
                aff_type=result.aff_type,
                aff_type_confidence=result.aff_type_confidence,
                country=result.country,
                country_confidence=result.country_confidence,
            )
        except Exception:
            # Safety net: an unexpected bug here (as opposed to the specific,
            # already-handled scrape/parse/classify failures above) must not
            # propagate out of asyncio.gather() and tear down the shared
            # browser session for every other team still being scraped.
            logger.exception("team_id=%s (%s): unexpected error", team.id, team_label)
            try:
                await set_status(JobStatus.ERROR.value, error_message="Unexpected server error -- check the server logs.")
            except Exception:
                logger.exception("team_id=%s (%s): also failed to record the error status", team.id, team_label)
    finally:
        db.close()
