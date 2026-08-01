"""Zwei-Datenbank-Isolation gegen echte Odoo-19-Datenbanken.

Diese Tests koennen gegen Mocks nicht bestehen: sie behaupten, dass zwei
Datenbanken mit ABSICHTLICH identischen numerischen IDs sich nicht gegenseitig
beeinflussen. Ein Mock hat keine zwei Datenbanken, und ein `local`-Fallback
wuerde beide Behauptungen trivial erfuellen -- deshalb weigert sich
`conftest.py`, ohne explizit benannte Datenbanken ueberhaupt zu starten.
"""
import pytest


@pytest.mark.foundation_live
@pytest.mark.asyncio
async def test_same_numeric_ids_never_cross_instance(
    live_config, signed_callback, odoo_probe
):
    """Gleiche Aggregat-ID in beiden Datenbanken, verschiedene Job-UUIDs.

    Der Seed legt das absichtlich so an: waeren die numerischen IDs
    verschieden, koennte ein Routing-Fehler unentdeckt bleiben, weil die
    falsche Datenbank die ID gar nicht kennt.
    """
    seeded_a = await odoo_probe(live_config["ODOO19_LIVE_DB_A"], "seeded")
    seeded_b = await odoo_probe(live_config["ODOO19_LIVE_DB_B"], "seeded")
    assert seeded_a["aggregate_id"] == seeded_b["aggregate_id"]
    assert seeded_a["job_id"] != seeded_b["job_id"]

    response = await signed_callback(
        instance=seeded_a["instance"],
        job_id=seeded_a["job_id"],
        source_event_id=seeded_a["event_id"],
        aggregate_id=seeded_a["aggregate_id"],
    )
    assert response.status_code == 200, response.text

    after_a = await odoo_probe(live_config["ODOO19_LIVE_DB_A"], seeded_a["job_id"])
    after_b = await odoo_probe(live_config["ODOO19_LIVE_DB_B"], seeded_b["job_id"])
    assert after_a["state"] == "succeeded"
    # Der eigentliche Beweis: B wurde NICHT angefasst.
    assert after_b["state"] == "queued"


@pytest.mark.foundation_live
@pytest.mark.asyncio
async def test_unknown_signed_instance_has_no_local_fallback(
    signed_callback, all_database_write_counts
):
    """Ein signierter Callback fuer eine unbekannte Instanz landet NIRGENDS.

    `get_callback_odoo_client` loest den Namen ausschliesslich aus dem
    signierten Body auf und prueft ihn gegen das Register. Ein `local`-Default
    waere hier genau der Fehler: die Signatur ist gueltig, also wuerde der
    Callback in irgendeiner Datenbank wirksam. Die Vorher/Nachher-Zaehler ueber
    BEIDE Datenbanken sind die Messung -- ein 403 allein bewiese nur, was der
    Client sieht, nicht, was der Server geschrieben hat.
    """
    before = await all_database_write_counts()
    response = await signed_callback(
        instance="unknown",
        job_id="c5ee6068-a8f3-4902-a882-2c17de2dfed1",
    )
    assert response.status_code == 403, response.text
    assert await all_database_write_counts() == before
