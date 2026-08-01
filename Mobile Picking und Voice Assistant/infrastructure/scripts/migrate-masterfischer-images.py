"""Migriere die Produktbilder aus v18 `masterfischer` nach v19.

Ergaenzung zu migrate-masterfischer-to-o19.py: die ORM-Produktmigration kopierte
Name/SKU/Barcode/Preis, aber NICHT die Bilder. Die liegen nicht in einer Spalte,
sondern als ir.attachment im Filestore
(/var/lib/odoo/filestore/masterfischer/<store_fname>). Dieses Skript liest die
Bilddateien und setzt `image_1920` auf den passenden v19-Produkten -- Odoo
generiert die kleineren Groessen (1024/512/256/128) daraus selbst neu.

Laeuft in der v19-Shell (liest v18 per psycopg2 + Filestore-Datei):

    odoo shell --no-http -d masterfischer_o19 --db_host=db --db_user=odoo \
        --db_password="$PASSWORD" < migrate-masterfischer-images.py
"""
import base64
import os

import psycopg2

env = env  # noqa: F821

FILESTORE = "/var/lib/odoo/filestore/masterfischer"

src = psycopg2.connect(host="db", dbname="masterfischer", user="odoo",
                       password=os.environ["PASSWORD"])
cur = src.cursor()
cur.execute(
    """
    select pp.default_code, a.store_fname
    from ir_attachment a
    join product_product pp on pp.product_tmpl_id = a.res_id
    where a.res_model = 'product.template' and a.res_field = 'image_1920'
      and a.store_fname is not null and pp.default_code is not null
    """
)
rows = cur.fetchall()
src.close()
print(f"IMG: {len(rows)} Bild-Attachments in v18 gefunden", flush=True)

Product = env["product.product"].sudo()
done = missing_file = missing_prod = 0
for default_code, store_fname in rows:
    path = os.path.join(FILESTORE, store_fname)
    if not os.path.exists(path):
        missing_file += 1
        continue
    product = Product.search([("default_code", "=", default_code)], limit=1)
    if not product:
        missing_prod += 1
        continue
    with open(path, "rb") as handle:
        product.image_1920 = base64.b64encode(handle.read())
    done += 1

env.cr.commit()
print(f"IMG: {done} Bilder gesetzt, {missing_file} Datei fehlt, "
      f"{missing_prod} Produkt fehlt", flush=True)
print("IMG: FERTIG", flush=True)
