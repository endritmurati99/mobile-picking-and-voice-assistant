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


def test_heavy_shipment_belongs_to_a_de_customer():
    """Die n8n-Versandregel prueft das Zielland vor dem Gewicht: ein Auftrag
    ueber 2 kg fuer einen AT/CH-Kunden wuerde nie den Gewichtszweig zeigen,
    weil er vorher in den Laenderzweig faellt. Der > 2 kg Demo-Auftrag muss
    also einem DE-Kunden gehoeren.
    """
    seed = _load_seed()
    customers = seed.build_demo_customers()
    weights_by_code = {}
    for product in seed.build_demo_cluster_products():
        weights_by_code[product["barcode"]] = product.get("weight", 0)
        weights_by_code[product["default_code"]] = product.get("weight", 0)

    found_de_heavy_order = False
    for order in seed.build_demo_customer_order_plan():
        quantities = order.get("quantities", {})
        total = sum(
            weights_by_code.get(code, 0) * quantities.get(code, 4)
            for code in order["products"]
        )
        if total > 2.0:
            customer = customers[order["customer_index"]]
            assert customer["country_code"] == "DE", (
                f"{order['origin']} ist > 2 kg, aber Kunde "
                f"{customer['name']} ist {customer['country_code']}, nicht DE"
            )
            found_de_heavy_order = True

    assert found_de_heavy_order


def test_order_plan_has_an_order_for_the_ch_customer():
    """Fuer den UPS-Zweig (Drittland CH) braucht es ein Vorfuehrbeispiel."""
    seed = _load_seed()
    customers = seed.build_demo_customers()
    ch_indices = {i for i, c in enumerate(customers) if c["country_code"] == "CH"}
    assert ch_indices

    orders_for_ch = [
        order
        for order in seed.build_demo_customer_order_plan()
        if order["customer_index"] in ch_indices
    ]
    assert orders_for_ch


def test_planned_quantities_fit_the_seeded_stock():
    """Jede geplante Menge je Produkt darf die eingebuchte Bestandsmenge nicht
    ueberschreiten, sonst reserviert Odoo weniger als bestellt und die
    Versandgewicht-Demonstration (z. B. > 2 kg) greift live nicht.
    """
    seed = _load_seed()
    stock_by_code = seed.build_demo_cluster_stock_quantities()

    consumed_by_code = {}
    for order in seed.build_demo_customer_order_plan():
        quantities = order.get("quantities", {})
        for code in order["products"]:
            qty = quantities.get(code, 4)
            consumed_by_code[code] = consumed_by_code.get(code, 0) + qty

    for code, consumed in consumed_by_code.items():
        seeded = stock_by_code.get(code, 0)
        assert consumed <= seeded, (
            f"Produkt {code}: geplant {consumed} Stk., aber nur "
            f"{seeded} Stk. eingebucht"
        )
