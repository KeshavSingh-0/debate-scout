from __future__ import annotations

import asyncio
import logging
import shutil
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import crud, export
from .config import settings
from .db import get_session, init_db
from .debug_log import get_all_text, get_new_lines
from .logging_config import setup_logging
from .pairing_parser import parse_pairings_pdf
from .pipeline import run_tournament_pipeline
from .schemas import ProgressEvent, StageEvent, TeamStatus, TournamentSummary

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Debate Scout")
app.mount("/static", StaticFiles(directory="static"), name="static")

_background_tasks: set[asyncio.Task] = set()


class ConnectionManager:
    def __init__(self) -> None:
        self.active: dict[int, list[WebSocket]] = {}

    async def connect(self, tournament_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.setdefault(tournament_id, []).append(websocket)

    def disconnect(self, tournament_id: int, websocket: WebSocket) -> None:
        connections = self.active.get(tournament_id, [])
        if websocket in connections:
            connections.remove(websocket)

    async def broadcast(self, tournament_id: int, payload: dict) -> None:
        for websocket in list(self.active.get(tournament_id, [])):
            try:
                await websocket.send_json(payload)
            except Exception:
                self.disconnect(tournament_id, websocket)


manager = ConnectionManager()


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    logger.info("Debate Scout started (log level=%s)", settings.log_level)


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse("static/index.html")


def _tournament_summary(tournament_id: int) -> TournamentSummary:
    db = get_session()
    try:
        tournament = crud.tournament_by_id(db, tournament_id)
        if tournament is None:
            raise HTTPException(status_code=404, detail="Tournament not found")
        teams = []
        for team in tournament.teams:
            record = crud.latest_aff_record(db, team)
            teams.append(
                TeamStatus(
                    team_id=team.id,
                    school_name=team.school_name,
                    team_code=team.team_code,
                    debaters=team.debaters,
                    opponent_school=team.opponent_school,
                    opponent_team_code=team.opponent_team_code,
                    round_label=team.round_label,
                    status=record.status if record else "not_started",
                    error_message=record.error_message if record else None,
                    aff_type=record.aff_type if record else None,
                    aff_type_confidence=record.aff_type_confidence if record else None,
                    country=record.country if record else None,
                    country_confidence=record.country_confidence if record else None,
                    source_title=record.source_title if record else None,
                    source_url=record.source_url if record else None,
                )
            )
        return TournamentSummary(
            id=tournament.id,
            name=tournament.name,
            section=tournament.section,
            caselist_slug=tournament.caselist_slug,
            teams=teams,
        )
    finally:
        db.close()


@app.get("/api/tournaments")
def list_tournaments() -> list[TournamentSummary]:
    db = get_session()
    try:
        tournaments = crud.all_tournaments(db)
        ids = [t.id for t in tournaments]
    finally:
        db.close()
    return [_tournament_summary(tid) for tid in ids]


@app.get("/api/tournaments/{tournament_id}")
def get_tournament(tournament_id: int) -> TournamentSummary:
    return _tournament_summary(tournament_id)


@app.get("/api/tournaments/{tournament_id}/export.csv")
def export_csv(tournament_id: int):
    db = get_session()
    try:
        tournament = crud.tournament_by_id(db, tournament_id)
        if tournament is None:
            raise HTTPException(status_code=404, detail="Tournament not found")
        content = export.tournament_to_delimited(tournament, delimiter=",")
    finally:
        db.close()
    filename = f"{tournament.name.replace(' ', '_')}_scouting.csv"
    return PlainTextResponse(
        content, media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.get("/api/tournaments/{tournament_id}/export.tsv")
def export_tsv(tournament_id: int) -> PlainTextResponse:
    db = get_session()
    try:
        tournament = crud.tournament_by_id(db, tournament_id)
        if tournament is None:
            raise HTTPException(status_code=404, detail="Tournament not found")
        content = export.tournament_to_delimited(tournament, delimiter="\t")
    finally:
        db.close()
    return PlainTextResponse(content, media_type="text/plain")


@app.get("/api/tournaments/{tournament_id}/logs")
def get_debug_logs(tournament_id: int) -> PlainTextResponse:
    """Full debug-level log for this tournament's most recent run(s) --
    what the UI's "Copy debug logs" button fetches. Always full detail,
    independent of the server's own LOG_LEVEL (see debug_log.py)."""
    return PlainTextResponse(get_all_text(tournament_id) or "No logs yet for this tournament.")


@app.post("/api/tournaments/upload")
async def upload_tournament(
    tournament_name: str = Form(...),
    section: str = Form(...),
    caselist_slug: str = Form(...),
    opencaselist_username: str = Form(...),
    opencaselist_password: str = Form(...),
    jev_api_key: str = Form(...),
    pairings_pdf: UploadFile = File(...),
) -> dict:
    upload_path = settings.upload_path / f"{uuid.uuid4().hex}_{pairings_pdf.filename}"
    with upload_path.open("wb") as out_file:
        shutil.copyfileobj(pairings_pdf.file, out_file)

    logger.info("Uploaded pairings PDF %r (%s)", pairings_pdf.filename, upload_path)

    entries = parse_pairings_pdf(str(upload_path))
    logger.info("Parsed %d school/team entries from %r", len(entries), pairings_pdf.filename)
    if not entries:
        logger.warning("No entries found in %r -- rejecting upload", pairings_pdf.filename)
        raise HTTPException(
            status_code=422,
            detail="Could not find any school/team entries in that PDF. Double-check it's a pairings "
            "or entry list document.",
        )

    db = get_session()
    try:
        tournament = crud.get_or_create_tournament(db, tournament_name, section, caselist_slug)
        tournament_id = tournament.id
    finally:
        db.close()

    logger.info(
        "Starting run for tournament_id=%s name=%r section=%r caselist_slug=%r entries=%d",
        tournament_id,
        tournament_name,
        section,
        caselist_slug,
        len(entries),
    )

    log_cursor = 0

    async def flush_logs() -> None:
        nonlocal log_cursor
        lines, log_cursor = get_new_lines(tournament_id, since=log_cursor)
        if lines:
            await manager.broadcast(tournament_id, {"type": "log", "tournament_id": tournament_id, "lines": lines})

    async def on_progress(event: ProgressEvent) -> None:
        logger.debug("team_id=%s status=%s detail=%s", event.team_id, event.status, event.detail)
        await manager.broadcast(tournament_id, {"type": "team", **event.model_dump()})
        await flush_logs()

    async def on_stage(event: StageEvent) -> None:
        logger.info("tournament_id=%s stage=%s status=%s detail=%s", tournament_id, event.stage, event.status, event.detail)
        await manager.broadcast(tournament_id, {"type": "stage", **event.model_dump()})
        await flush_logs()

    async def run() -> None:
        try:
            await run_tournament_pipeline(
                tournament_id=tournament_id,
                entries=entries,
                caselist_slug=caselist_slug,
                opencaselist_username=opencaselist_username,
                opencaselist_password=opencaselist_password,
                jev_api_key=jev_api_key,
                on_progress=on_progress,
                on_stage=on_stage,
            )
            logger.info("Run finished for tournament_id=%s", tournament_id)
        except Exception:
            # Safety net: anything that escapes run_tournament_pipeline's own
            # error handling would otherwise just vanish into asyncio's
            # default (log-only) exception handler. Log the full traceback
            # and surface it in the UI instead of leaving the run looking
            # like it's silently stuck.
            logger.exception("Unhandled error running tournament_id=%s", tournament_id)
            await on_stage(
                StageEvent(
                    tournament_id=tournament_id,
                    stage="scraping",
                    status="error",
                    detail="Unexpected server error -- check the server logs for a traceback.",
                )
            )
        finally:
            await flush_logs()
            upload_path.unlink(missing_ok=True)

    task = asyncio.create_task(run())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {"tournament_id": tournament_id, "entries_found": len(entries)}


@app.websocket("/ws/{tournament_id}")
async def websocket_endpoint(websocket: WebSocket, tournament_id: int) -> None:
    await manager.connect(tournament_id, websocket)
    logger.debug("WebSocket connected for tournament_id=%s", tournament_id)
    try:
        snapshot = _tournament_summary(tournament_id)
        await websocket.send_json({"type": "snapshot", "data": snapshot.model_dump()})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(tournament_id, websocket)
        logger.debug("WebSocket disconnected for tournament_id=%s", tournament_id)
