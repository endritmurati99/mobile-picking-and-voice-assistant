import importlib.util
from pathlib import Path


def load_seed_module():
    script_path = Path(__file__).resolve().parents[1] / ".." / "infrastructure" / "scripts" / "seed-odoo.py"
    spec = importlib.util.spec_from_file_location("seed_odoo", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_execute_argument_normalizer_promotes_trailing_keyword_dict():
    seed_odoo = load_seed_module()

    args, kwargs = seed_odoo._normalize_execute_args(
        ([], {"fields": ["id", "name"], "limit": 1}),
        {},
    )

    assert args == [[]]
    assert kwargs == {"fields": ["id", "name"], "limit": 1}


def test_execute_argument_normalizer_keeps_create_values_positional():
    seed_odoo = load_seed_module()

    args, kwargs = seed_odoo._normalize_execute_args(
        ({"name": "Regal A-01", "barcode": "LOC-A01"},),
        {},
    )

    assert args == [{"name": "Regal A-01", "barcode": "LOC-A01"}]
    assert kwargs == {}
