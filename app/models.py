import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Section(str, enum.Enum):
    NDT_CEDA = "NDT-CEDA"
    NSDA_HS_POLICY = "NSDA-HS Policy"


class AffType(str, enum.Enum):
    K_AFF = "K-aff"
    POLICY = "Policy aff"


class Country(str, enum.Enum):
    NIGERIA = "Nigeria"
    JAPAN = "Japan"
    SAUDI_ARABIA = "Saudi Arabia"
    TAIWAN = "Taiwan"
    PHILIPPINES = "Philippines"
    ISRAEL = "Israel"
    UKRAINE = "Ukraine"
    MEXICO = "Mexico"
    ALL_NON_SPECIFIED = "All/Non-Specified"


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    SCRAPING = "scraping"
    PARSING = "parsing"
    CLASSIFYING = "classifying"
    DONE = "done"
    ERROR = "error"
    SKIPPED_CACHED = "skipped_cached"


class Tournament(Base):
    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    section: Mapped[str] = mapped_column(String(64))
    caselist_slug: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    teams: Mapped[list["Team"]] = relationship(back_populates="tournament", cascade="all, delete-orphan")


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("tournament_id", "school_name", "team_code", name="uq_team_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"))
    school_name: Mapped[str] = mapped_column(String(255))
    team_code: Mapped[str] = mapped_column(String(64))
    opponent_school: Mapped[str | None] = mapped_column(String(255), nullable=True)
    opponent_team_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    round_label: Mapped[str | None] = mapped_column(String(64), nullable=True)

    tournament: Mapped["Tournament"] = relationship(back_populates="teams")
    aff_records: Mapped[list["AffRecord"]] = relationship(back_populates="team", cascade="all, delete-orphan")


class AffRecord(Base):
    __tablename__ = "aff_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))

    status: Mapped[str] = mapped_column(String(32), default=JobStatus.QUEUED.value)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    aff_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    aff_type_confidence: Mapped[float | None] = mapped_column(nullable=True)
    country: Mapped[str | None] = mapped_column(String(64), nullable=True)
    country_confidence: Mapped[float | None] = mapped_column(nullable=True)

    condensed_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    team: Mapped["Team"] = relationship(back_populates="aff_records")
