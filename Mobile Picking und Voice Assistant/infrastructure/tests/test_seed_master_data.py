"""Tests fuer Stammdaten im Seed-Skript: Produktgewichte und Auslandskunden.

Das Versandlabel-Feature braucht pro Produkt ein Gewicht (fuer die
Gesamtgewichts-Berechnung) und Kunden in DE, AT und CH (fuer die
Laenderzweig-Logik der Versandregel in n8n).
"""
import importlib.util
from pathlib import Path


def _load_seed():
    path = Path(__file__).resolve().parents[1] / "scripts" / "seed-odoo.py"
    spec = importlib.util.spec_from_file_location("seed_odoo", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_demo_product_has_a_weight():
    seed = _load_seed()
    for product in seed.build_demo_cluster_products():
        assert product.get("weight", 0) > 0, product["name"]


def test_demo_customers_cover_inland_eu_and_third_country():
    seed = _load_seed()
    codes = {c["country_code"] for c in seed.build_demo_customers()}
    assert {"DE", "AT", "CH"} <= codes


def test_demo_customers_have_no_duplicate_emails():
    seed = _load_seed()
    emails = [c["email"] for c in seed.build_demo_customers()]
    assert len(emails) == len(set(emails))


def test_at_and_ch_customers_have_full_address():
    seed = _load_seed()
    for customer in seed.build_demo_customers():
        if customer["country_code"] in {"AT", "CH"}:
            assert customer.get("street"), customer["name"]
            assert customer.get("zip"), customer["name"]
            assert customer.get("city"), customer["name"]


def test_order_plan_has_a_heavy_shipment_over_two_kg():
    seed = _load_seed()
    weights_by_code = {}
    for product in seed.build_demo_cluster_products():
        weights_by_code[product["barcode"]] = product.get("weight", 0)
        weights_by_code[product["default_code"]] = product.get("weight", 0)

    # Der Seed setzt pro Bewegung standardmaessig eine Menge von 4, sofern
    # ein Auftrag keine eigene Mengenangabe (`quantities`) mitbringt.
    heaviest = 0.0
    for order in seed.build_demo_customer_order_plan():
        quantities = order.get("quantities", {})
        total = 0.0
        for code in order["products"]:
            qty = quantities.get(code, 4)
            total += weights_by_code.get(code, 0) * qty
        heaviest = max(heaviest, total)

    assert heaviest > 2.0
