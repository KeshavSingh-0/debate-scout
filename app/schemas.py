from pydantic import BaseModel


class StartRunRequest(BaseModel):
    tournament_name: str
    section: str  # "NDT-CEDA" or "NSDA-HS Policy"
    caselist_slug: str  # e.g. "ndtceda25" or "hspolicy25" — the opencaselist URL segment
    opencaselist_username: str
    opencaselist_password: str
    jev_api_key: str


class TeamStatus(BaseModel):
    team_id: int
    school_name: str
    team_code: str
    opponent_school: str | None
    opponent_team_code: str | None
    round_label: str | None
    status: str
    error_message: str | None
    aff_type: str | None
    aff_type_confidence: float | None
    country: str | None
    country_confidence: float | None
    source_title: str | None
    source_url: str | None


class TournamentSummary(BaseModel):
    id: int
    name: str
    section: str
    caselist_slug: str
    teams: list[TeamStatus]


class ProgressEvent(BaseModel):
    tournament_id: int
    team_id: int
    status: str
    detail: str | None = None
