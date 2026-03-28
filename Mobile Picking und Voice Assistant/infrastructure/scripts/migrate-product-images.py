"""
Migriert Produktbilder von einer Odoo-Instanz zur anderen.

Quelle:  localhost:8070  (Bilder vorhanden)
Ziel:    localhost:8069  (Bilder fehlen)

Matching: default_code (intern. Referenz) → Name (case-insensitiv)

Verwendung:
    python migrate-product-images.py
    python migrate-product-images.py --src-port 8070 --dst-port 8069
"""
import argparse
import sys
from xmlrpc.client import ServerProxy


def connect(url: str, db: str, user: str, password: str):
    common = ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(db, user, password, {})
    if not uid:
        print(f"FEHLER: Authentifizierung fehlgeschlagen bei {url}")
        sys.exit(1)
    models = ServerProxy(f"{url}/xmlrpc/2/object")

    def execute(model, method, *args, **kwargs):
        return models.execute_kw(db, uid, password, model, method, list(args), kwargs)

    return execute


def main():
    parser = argparse.ArgumentParser(description="Odoo Produkt-Bilder Migration")
    parser.add_argument("--src-port", type=int, default=8070, help="Quell-Port (mit Bildern)")
    parser.add_argument("--dst-port", type=int, default=8069, help="Ziel-Port (Bilder fehlen)")
    parser.add_argument("--src-db", default="test", help="DB-Name auf dem Quell-Server")
    parser.add_argument("--dst-db", default="masterfischer", help="DB-Name auf dem Ziel-Server")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--password", default="Admin")
    args = parser.parse_args()

    src_url = f"http://localhost:{args.src_port}"
    dst_url = f"http://localhost:{args.dst_port}"

    print(f"Verbinde Quelle:  {src_url} (db={args.src_db}) ...")
    src = connect(src_url, args.src_db, args.user, args.password)
    print(f"Verbinde Ziel:    {dst_url} (db={args.dst_db}) ...")
    dst = connect(dst_url, args.dst_db, args.user, args.password)

    # Alle Produkte aus der Quelle laden (id, name, default_code, image_1920)
    print("\nLade Produkte aus Quelle ...")
    src_products = src(
        "product.template", "search_read",
        [],
        fields=["id", "name", "default_code", "image_1920"],
        limit=0,
    )
    print(f"  {len(src_products)} Produkte gefunden")

    with_image = [p for p in src_products if p.get("image_1920")]
    print(f"  {len(with_image)} davon haben ein Bild")

    if not with_image:
        print("Keine Bilder vorhanden — nichts zu tun.")
        return

    # Alle Ziel-Produkte einmal laden für schnelles Lookup
    print("\nLade Produkte aus Ziel ...")
    dst_products = dst(
        "product.template", "search_read",
        [],
        fields=["id", "name", "default_code"],
        limit=0,
    )
    print(f"  {len(dst_products)} Produkte gefunden")

    # Lookup-Tabellen aufbauen
    by_code = {p["default_code"]: p["id"] for p in dst_products if p.get("default_code")}
    by_name = {p["name"].lower(): p["id"] for p in dst_products if p.get("name")}

    updated = 0
    skipped = 0
    errors = 0

    print("\nMigriere Bilder ...")
    for src_p in with_image:
        code = src_p.get("default_code") or ""
        name = src_p.get("name") or ""

        # Match: default_code zuerst, dann Name
        dst_id = None
        match_by = None
        if code and code in by_code:
            dst_id = by_code[code]
            match_by = f"code={code}"
        elif name.lower() in by_name:
            dst_id = by_name[name.lower()]
            match_by = f"name={name}"

        if dst_id is None:
            print(f"  SKIP  '{name}' (code={code!r}) — kein Match im Ziel")
            skipped += 1
            continue

        try:
            dst("product.template", "write", [dst_id], {"image_1920": src_p["image_1920"]})
            print(f"  OK    '{name}' -> Ziel-ID {dst_id} (via {match_by})")
            updated += 1
        except Exception as exc:
            print(f"  ERR   '{name}': {exc}", flush=True)
            errors += 1

    print(f"\n{'='*50}")
    print(f"  Aktualisiert: {updated}")
    print(f"  Uebersprungen: {skipped}")
    print(f"  Fehler:        {errors}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
