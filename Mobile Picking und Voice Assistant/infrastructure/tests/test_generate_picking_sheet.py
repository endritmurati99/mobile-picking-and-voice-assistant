import importlib.util
from datetime import date
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate-picking-sheet.py"


def load_module():
    spec = importlib.util.spec_from_file_location("generate_picking_sheet", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_resolve_docker_command_uses_windows_path():
    module = load_module()

    assert module.resolve_docker_command(
        "nt", lambda name: r"C:\\Program Files\\Docker\\Docker\\resources\\bin\\docker.exe"
    ) == r"C:\\Program Files\\Docker\\Docker\\resources\\bin\\docker.exe"


def test_to_windows_path_keeps_native_windows_path():
    module = load_module()

    assert module.to_windows_path(Path("docs/testing/handy-start.pdf")).startswith("C:\\")


def test_resolve_chrome_command_uses_windows_path():
    module = load_module()

    assert module.resolve_chrome_command(
        "nt", lambda name: r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
    ) == r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"


def test_sheet_date_is_the_generation_date():
    module = load_module()

    assert module.SHEET_DATE == date.today().strftime("%d.%m.%Y")


def test_api_base_uses_the_printed_pwa_origin():
    module = load_module()

    assert module.API_BASE == module.PWA_URL.rstrip("/") + "/api"
    assert module.ORIGIN == module.PWA_URL.rstrip("/")


def test_stops_from_picking_keeps_route_order_and_barcodes():
    module = load_module()

    stops = module.stops_from_picking({
        "move_lines": [
            {"location_src_short": "Regal B-02", "product_barcode": "6023350", "product_name": "Brick", "quantity_demand": 2},
            {"location_src_short": "Regal C-01", "product_barcode": "6171865", "product_name": "Plate", "quantity_demand": 1},
        ]
    })

    assert stops == [
        {"location": "Regal B-02", "barcode": "6023350", "product": "Brick", "split": "2 Stück"},
        {"location": "Regal C-01", "barcode": "6171865", "product": "Plate", "split": "1 Stück"},
    ]


def test_build_single_picking_html_has_no_carton_labels():
    module = load_module()
    barcode = '<img class="code" src="data:image/png;base64,test">'

    document = module.build_single_picking_html(
        {"name": "WH/OUT/00066", "move_lines": [{}, {}]},
        [{"location": "Regal B-02", "barcode": "6023350", "product": "Brick", "split": "2 Stück"}],
        [{"barcode": "6171865", "product": "Falscher Artikel"}],
        {"6023350": (barcode, 40), "6171865": (barcode, 40)},
    )

    assert "WH/OUT/00066" in document
    assert "Menge für diesen Auftrag" in document
    assert "Kartonetiketten" not in document


def test_cluster_sheet_paginates_four_cartons_without_hidden_overflow():
    module = load_module()
    barcode = '<img class="code" src="data:image/png;base64,test">'
    stops = [
        {"location": f"Regal {index}", "barcode": str(index), "product": f"Produkt {index}", "split": "1 Stück"}
        for index in range(1, 10)
    ]
    cartons = [
        {"label": f"Karton {index}", "order": f"L1/OUT/{index:05d}", "value": f"CLUSTER-B{index}"}
        for index in range(1, 5)
    ]
    values = [stop["barcode"] for stop in stops] + [carton["value"] for carton in cartons] + ["999"]
    document = module.build_html(
        {"name": "BATCH/OUT/00014", "lines": [{}] * 22},
        stops,
        cartons,
        [{"barcode": "999", "product": "Kontrollprodukt"}],
        {value: (barcode, 40) for value in values},
    )

    assert document.count('class="sheet"') == 5
    assert "Kartonetiketten (4 Stück)" in document
    assert "Seite 5 von 5" in document
