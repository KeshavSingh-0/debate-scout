from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AffRecord, JobStatus, Team, Tournament


def get_or_create_tournament(db: Session, name: str, section: str, caselist_slug: str) -> Tournament:
    tournament = db.scalar(select(Tournament).where(Tournament.name == name))
    if tournament is None:
        tournament = Tournament(name=name, section=section, caselist_slug=caselist_slug)
        db.add(tournament)
        db.commit()
        db.refresh(tournament)
    return tournament


def get_or_create_team(
    db: Session,
    tournament: Tournament,
    school_name: str,
    team_code: str,
    debaters: list[str],
    opponent_school: str | None,
    opponent_team_code: str | None,
    round_label: str | None,
) -> tuple[Team, bool]:
    """Returns (team, created). Updates matchup context if the team already existed."""
    debaters_str = " & ".join(debaters)
    team = db.scalar(
        select(Team).where(
            Team.tournament_id == tournament.id,
            Team.school_name == school_name,
            Team.team_code == team_code,
        )
    )
    if team is not None:
        team.debaters = debaters_str
        team.opponent_school = opponent_school
        team.opponent_team_code = opponent_team_code
        team.round_label = round_label
        db.commit()
        return team, False

    team = Team(
        tournament_id=tournament.id,
        school_name=school_name,
        team_code=team_code,
        debaters=debaters_str,
        opponent_school=opponent_school,
        opponent_team_code=opponent_team_code,
        round_label=round_label,
    )
    db.add(team)
    db.commit()
    db.refresh(team)
    return team, True


def has_completed_aff_record(db: Session, team: Team) -> bool:
    """True if this team already has a DONE aff record -- used to skip re-scraping
    on re-upload so new entries don't restart the whole tournament."""
    record = db.scalar(
        select(AffRecord).where(AffRecord.team_id == team.id, AffRecord.status == JobStatus.DONE.value)
    )
    return record is not None


def create_aff_record(db: Session, team: Team) -> AffRecord:
    record = AffRecord(team_id=team.id, status=JobStatus.QUEUED.value)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def update_aff_record(db: Session, record: AffRecord, **fields) -> AffRecord:
    for key, value in fields.items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record


def latest_aff_record(db: Session, team: Team) -> AffRecord | None:
    return db.scalar(
        select(AffRecord).where(AffRecord.team_id == team.id).order_by(AffRecord.id.desc())
    )


def tournament_by_id(db: Session, tournament_id: int) -> Tournament | None:
    return db.get(Tournament, tournament_id)


def all_tournaments(db: Session) -> list[Tournament]:
    return list(db.scalars(select(Tournament).order_by(Tournament.created_at.desc())))
