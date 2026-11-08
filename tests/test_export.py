from app import crud, export
from app.db import get_session


def test_export_includes_team_and_classification():
    db = get_session()
    tournament = crud.get_or_create_tournament(db, "Test Tourney", "NDT-CEDA", "ndtceda99")
    team, _created = crud.get_or_create_team(
        db, tournament, "Georgetown", "Georgetown KM", ["Keeler", "Marsh"], "Michigan", "Michigan FM", "Round 3"
    )
    record = crud.create_aff_record(db, team)
    crud.update_aff_record(
        db,
        record,
        status="done",
        aff_type="Policy aff",
        aff_type_confidence=0.91,
        country="Japan",
        country_confidence=0.77,
        source_title="1AC v6",
        source_url="https://example.com/file",
    )
    db.close()

    db2 = get_session()
    reloaded = crud.tournament_by_id(db2, tournament.id)
    tsv = export.tournament_to_delimited(reloaded, delimiter="\t")
    db2.close()

    assert "Georgetown\tGeorgetown KM" in tsv
    assert "Policy aff" in tsv
    assert "91%" not in tsv  # confidence stored as a decimal, not pre-formatted as %
    assert "0.91" in tsv
    assert "Japan" in tsv
