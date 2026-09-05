"""Legt Kommissionierauftraege aus den Bausatz-Rezepten an.

Aufruf (im jeweiligen Odoo-Container):

    odoo shell -c /etc/odoo/odoo.conf -d <db> --db_password="$PASSWORD" \
        --no-http < infrastructure/scripts/seed-auftraege.py

Das aeltere seed-odoo.py liest die Zusammensetzung aus `mrp.bom`. Das Modul
`mrp` ist in den Lagerdatenbanken NICHT installiert (`mrp_bom` existiert dort
nicht), deshalb stehen die Rezepte hier als Literal. Quelle: die elf
Stuecklisten aus `masterfischer_o19_trial`, am 2026-09-05 ausgelesen.

Ein Auftrag ist IMMER genau ein Bausatz. Mehrere Bausaetze in einem Auftrag
("Sparkasse x2") sind hier bewusst nicht vorgesehen: dieser Fall gehoert dem
Cluster-Picking, nicht dem Einzelauftrag.

Die Datenbank entscheidet ueber Anzahl und Mischung: jedes Lager bekommt eine
andere Auftragszahl, andere Kunden und einen eigenen Zufallsstartwert, damit
beim Umschalten in der PWA sofort sichtbar ist, in welchem Lager man steht.
"""

import random
from datetime import date, timedelta

# Bausatz -> [(Artikelnummer, Menge je Bausatz)]
REZEPTE = {
    "Blume": [("4183780", 5), ("4185178", 3), ("4648231", 4), ("6294237", 2), ("6294939", 2)],
    "Burger": [("301121", 2), ("4185178", 2), ("6171865", 2), ("6380873", 2)],
    "Ente Henri": [("343724", 1), ("4250173", 1), ("4648234", 1), ("6023350", 1), ("6167549", 1), ("6171865", 1)],
    "Erwin": [("4166960", 2), ("6294208", 1)],
    "Helikopter": [("4216758", 1), ("6059082", 1), ("6269088", 1), ("6286339", 1), ("6294943", 1), ("6346241", 2)],
    "Krebs Max": [("4166960", 1), ("4652854", 1), ("6023350", 2), ("6059082", 1), ("6096680", 2), ("6171865", 2)],
    "LKW": [("4166960", 2), ("4652854", 1), ("6059082", 1), ("6286339", 1)],
    "Papagei Moritz": [("343701", 3), ("343721", 4), ("343724", 7), ("4185178", 4), ("6023350", 2), ("6101121", 2), ("6380873", 1)],
    "Sparkasse": [("4250172", 4), ("6059082", 5), ("6096680", 4), ("6101121", 8), ("6256703", 3)],
    "Wal": [("4166960", 1), ("4216758", 1), ("4652854", 1), ("6138111", 1), ("6294208", 1), ("6294241", 2)],
    "Windkraft": [("343701", 1), ("6096680", 2), ("6269088", 1)],
}

LAGER = {
    "lager1": {
        "anzahl": 80,
        "kunden": [
            "Meyer Spielwaren KG",
            "Fischer Techniklabor AG",
            "ACME Demo GmbH",
            "FH Demo Logistik",
            "Zuerich Modellbau AG",   # CH -- Drittland fuer die Versandstrecke
            "Alpin Spielwaren GmbH",  # AT
        ],
        "startwert": 20260905,
        "bestand_je_platz": 400,
    },
    "lager2": {
        "anzahl": 100,
        "kunden": [
            "Fischer Techniklabor AG",
            "ACME Demo GmbH",
            "Meyer Spielwaren KG",
            "FH Demo Logistik",
        ],
        "startwert": 777,
        "bestand_je_platz": 900,
    },
}

# Anteil dringender Auftraege (Stern in Odoo).
DRINGEND_ANTEIL = 0.2
# Termine streuen von gestern bis in zehn Tage.
TERMIN_VON, TERMIN_BIS = -1, 10


def lager_einstellungen(dbname):
    if dbname not in LAGER:
        raise SystemExit(f"Keine Einstellungen fuer Datenbank {dbname!r} hinterlegt.")
    return LAGER[dbname]


def artikel_nach_code(env, codes):
    produkte = env["product.product"].search([("default_code", "in", sorted(codes))])
    treffer = {p.default_code: p for p in produkte}
    fehlend = sorted(codes - treffer.keys())
    if fehlend:
        raise SystemExit(f"Artikel fehlen in dieser Datenbank: {fehlend}")
    return treffer


def kunden_nach_name(env, namen):
    partner = env["res.partner"].search([("name", "in", sorted(set(namen)))])
    treffer = {p.name: p for p in partner}
    fehlend = sorted(set(namen) - treffer.keys())
    if fehlend:
        raise SystemExit(f"Kunden fehlen in dieser Datenbank: {fehlend}")
    return treffer


def bestand_auffuellen(env, artikel, menge):
    """Hebt jeden vorhandenen Lagerplatz-Bestand auf mindestens `menge`.

    Ohne genug Bestand bleibt ein Auftrag nach `action_assign` auf
    "confirmed" stehen und ist in der PWA nicht kommissionierbar. Neue
    Lagerplaetze legt das hier bewusst NICHT an -- die Platzstruktur ist
    Sache des Lagers, nicht dieses Skripts.
    """
    quants = env["stock.quant"].search([
        ("product_id", "in", [p.id for p in artikel.values()]),
        ("location_id.usage", "=", "internal"),
    ])
    zu_heben = quants.filtered(lambda q: q.quantity < menge)
    for quant in zu_heben:
        quant.inventory_quantity = menge
    if zu_heben:
        zu_heben.action_apply_inventory()
    return len(zu_heben)


def plan_bauen(einstellungen):
    """Erzeugt die Auftragsliste: ein Bausatz je Auftrag, gestreute Termine."""
    zufall = random.Random(einstellungen["startwert"])
    bausaetze = sorted(REZEPTE)
    kunden = einstellungen["kunden"]
    plan = []

    for lauf in range(einstellungen["anzahl"]):
        # Erst jeden Bausatz einmal, danach zufaellig -- so kommt garantiert
        # jedes der elf Endprodukte vor, auch bei kleiner Auftragszahl.
        bausatz = bausaetze[lauf] if lauf < len(bausaetze) else zufall.choice(bausaetze)
        plan.append({
            "bausatz": bausatz,
            "kunde": kunden[lauf % len(kunden)],
            "prioritaet": "1" if zufall.random() < DRINGEND_ANTEIL else "0",
            "versatz": zufall.randint(TERMIN_VON, TERMIN_BIS),
        })
    return plan


def main(env):
    einstellungen = lager_einstellungen(env.cr.dbname)
    plan = plan_bauen(einstellungen)

    typ = env["stock.picking.type"].search([("code", "=", "outgoing")], limit=1)
    if not typ:
        raise SystemExit("Kein Lieferauftrags-Typ (outgoing) gefunden.")

    quelle = typ.default_location_src_id or env["stock.location"].search(
        [("usage", "=", "internal")], limit=1
    )
    ziel = typ.default_location_dest_id or env["stock.location"].search(
        [("usage", "=", "customer")], limit=1
    )

    codes = {code for rezept in REZEPTE.values() for code, _ in rezept}
    artikel = artikel_nach_code(env, codes)
    kunden = kunden_nach_name(env, einstellungen["kunden"])

    angehoben = bestand_auffuellen(env, artikel, einstellungen["bestand_je_platz"])
    print(f"Bestand auf {einstellungen['bestand_je_platz']} gehoben: {angehoben} Lagerplaetze")

    heute = date.today()
    angelegt = env["stock.picking"]

    for eintrag in plan:
        zeilen = [
            # Odoo 19 hat `name` an stock.move gestrichen; die Bezeichnung
            # kommt aus dem Artikel.
            (0, 0, {
                "product_id": artikel[code].id,
                "product_uom_qty": menge,
                "product_uom": artikel[code].uom_id.id,
                "location_id": quelle.id,
                "location_dest_id": ziel.id,
            })
            for code, menge in REZEPTE[eintrag["bausatz"]]
        ]

        picking = env["stock.picking"].create({
            "picking_type_id": typ.id,
            "location_id": quelle.id,
            "location_dest_id": ziel.id,
            "partner_id": kunden[eintrag["kunde"]].id,
            "origin": eintrag["bausatz"],
            "priority": eintrag["prioritaet"],
            "scheduled_date": f"{heute + timedelta(days=eintrag['versatz'])} 08:00:00",
            # Odoo 19 kennt kein `move_ids_without_package` mehr.
            "move_ids": zeilen,
        })
        picking.action_confirm()
        # Ohne Reservierung bleibt der Auftrag auf "confirmed" stehen und taucht
        # in der PWA nicht als kommissionierbar auf.
        picking.action_assign()
        angelegt |= picking

    env.cr.commit()

    nach_zustand = {}
    nach_bausatz = {}
    for p in angelegt:
        nach_zustand[p.state] = nach_zustand.get(p.state, 0) + 1
        nach_bausatz[p.origin] = nach_bausatz.get(p.origin, 0) + 1

    print(f"Datenbank: {env.cr.dbname}")
    print(f"angelegt: {len(angelegt)} Auftraege | Zustaende: {nach_zustand}")
    print(f"dringend: {len(angelegt.filtered(lambda p: p.priority == '1'))}")
    for bausatz in sorted(nach_bausatz):
        print(f"  {bausatz}: {nach_bausatz[bausatz]}")


main(env)  # noqa: F821 -- `env` stellt die Odoo-Shell bereit
