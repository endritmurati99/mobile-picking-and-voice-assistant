import importlib.util
import hashlib
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reconcile-odoo-lego.py"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "lego-catalog-o19.json"


def load_module():
    if not SCRIPT.exists():
        raise AssertionError(f"missing reconciliation tool: {SCRIPT}")
    spec = importlib.util.spec_from_file_location("reconcile_odoo_lego", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeSession:
    def __init__(self, before, after=None, db_name="masterfischer_o19"):
        self.db_name = db_name
        self.before = before
        self.after = after
        self.events = []

    def snapshot(self):
        self.events.append("snapshot")
        return self.after if "apply" in self.events else self.before

    def apply(self, plan):
        self.events.append("apply")

    def commit(self):
        self.events.append("commit")

    def rollback(self):
        self.events.append("rollback")


def product(tool, token, code, name, *, active=True):
    return tool.ProductState(
        token=token,
        code=code,
        name=name,
        barcode=code or "",
        active=active,
        product_type="consu",
        sale_ok=True,
        purchase_ok=True,
        tracking="none",
        list_price=1.0,
        standard_price=0.0,
        is_storable=True,
        image_1920="",
        ai_reference_description="",
        ai_reference_image_sha1="",
        ai_reference_reviewed=False,
    )


def snapshot(tool, products, **overrides):
    values = {
        "products": tuple(products),
        "templates": len(products),
        "nonlego_pickings": 0,
        "nonlego_picking_states": (),
        "mixed_pickings": 0,
        "nonlego_moves": 0,
        "nonlego_move_lines": 0,
        "nonlego_quants": 0,
        "restricted_dependencies": (),
        "protected_history": (0, 0, 0),
        "fk_inventory": (),
        "deleted_fk_residue": (),
    }
    values.update(overrides)
    return tool.Snapshot(**values)


class ReconcileOdooLegoTests(unittest.TestCase):
    def test_dry_run_is_default_and_never_mutates(self):
        tool = load_module()
        catalog = (
            tool.CatalogItem("100", "Brick red"),
            tool.CatalogItem("200", "Plate blue"),
        )
        before = snapshot(
            tool,
            [
                product(tool, "keep", "100", "Brick red", active=False),
                product(tool, "demo", "200", "Demo Plate blue", active=False),
                product(tool, "mechanic", "SCR-M8", "Screw"),
            ],
            nonlego_pickings=2,
            nonlego_picking_states=(("assigned", 1), ("cancel", 1)),
            nonlego_moves=4,
            nonlego_move_lines=2,
            nonlego_quants=3,
        )
        session = FakeSession(before)

        result = tool.reconcile(session, catalog=catalog)

        self.assertEqual(result.mode, "dry-run")
        self.assertEqual(result.plan.delete_tokens, ("demo", "mechanic"))
        self.assertEqual(result.plan.update_tokens, ("keep",))
        self.assertEqual(tuple(item.code for item in result.plan.create_items), ("200",))
        self.assertEqual(session.events, ["snapshot", "rollback"])
    def test_apply_commits_only_after_exact_postconditions(self):
        tool = load_module()
        catalog = (
            tool.CatalogItem("100", "Brick red"),
            tool.CatalogItem("200", "Plate blue"),
        )
        before = snapshot(
            tool,
            [product(tool, "old", "OLD", "Old product")],
            nonlego_moves=1,
            nonlego_quants=1,
            protected_history=(3, 7, 7),
        )
        after = snapshot(
            tool,
            [
                product(tool, "new-100", "100", "Brick red"),
                product(tool, "new-200", "200", "Plate blue"),
            ],
            protected_history=(3, 7, 7),
        )
        session = FakeSession(before, after)

        result = tool.reconcile(session, catalog=catalog, apply=True)

        self.assertEqual(result.mode, "apply")
        self.assertTrue(result.changed)
        self.assertEqual(session.events, ["snapshot", "apply", "snapshot", "commit"])
    def test_apply_rolls_back_when_postconditions_are_not_exact(self):
        tool = load_module()
        catalog = (tool.CatalogItem("100", "Brick red"),)
        before = snapshot(tool, [product(tool, "old", "OLD", "Old product")])
        still_wrong = snapshot(tool, [product(tool, "old", "OLD", "Old product")])
        session = FakeSession(before, still_wrong)

        with self.assertRaisesRegex(tool.SafetyError, "postcondition"):
            tool.reconcile(session, catalog=catalog, apply=True)

        self.assertEqual(session.events, ["snapshot", "apply", "snapshot", "rollback"])

    def test_catalog_parity_includes_storable_media_and_reference_fields(self):
        tool = load_module()
        catalog = (tool.CatalogItem(
            "100", "Brick red", image_1920="aW1hZ2U=", is_storable=True,
            ai_reference_description="red toy brick",
            ai_reference_image_sha1="0e76292794888d4f1c5f7473298f01f2d0e3e2e9",
            ai_reference_reviewed=True,
        ),)
        wrong = product(tool, "lego", "100", "Brick red")._replace(is_storable=False)
        session = FakeSession(snapshot(tool, [wrong]))

        result = tool.reconcile(session, catalog=catalog)

        self.assertEqual(result.plan.update_tokens, ("lego",))

    def test_reconciliation_refuses_every_database_outside_the_two_targets(self):
        tool = load_module()
        catalog = (tool.CatalogItem("100", "Brick red"),)
        session = FakeSession(
            snapshot(tool, [product(tool, "lego", "100", "Brick red")]),
            db_name="masterfischer_o19_trial",
        )

        with self.assertRaisesRegex(tool.SafetyError, "database"):
            tool.reconcile(session, catalog=catalog)

        self.assertEqual(session.events, ["rollback"])

    def test_same_history_counts_with_changed_content_roll_back(self):
        tool = load_module()
        catalog = (tool.CatalogItem("100", "Brick red"),)
        before = snapshot(
            tool, [product(tool, "lego", "100", "Brick red", active=False)],
            protected_history="sha256:before",
        )
        after = snapshot(
            tool, [product(tool, "lego", "100", "Brick red")],
            protected_history="sha256:after",
        )
        session = FakeSession(before, after)

        with self.assertRaisesRegex(tool.SafetyError, "history changed"):
            tool.reconcile(session, catalog=catalog, apply=True)

        self.assertEqual(session.events[-1], "rollback")

    def test_unknown_restricting_fk_dependency_fails_closed(self):
        tool = load_module()
        inventory = (
            tool.ForeignKeyState(
                "product_product", "stock_move", "product_id", "r", 4,
                inside_deletion=True,
            ),
            tool.ForeignKeyState("product_product", "unknown_table", "product_id", "r", 1),
            tool.ForeignKeyState("product_product", "safe_rel", "product_id", "c", 2),
        )

        self.assertEqual(
            tool.unsafe_fk_dependencies(inventory),
            (("unknown_table.product_id", 1), ("safe_rel.product_id", 2)),
        )

    def test_deleted_target_set_covers_the_complete_stock_graph(self):
        tool = load_module()

        self.assertEqual(
            tool.DELETED_TARGET_TABLES,
            {
                "product_product", "product_template", "stock_picking",
                "stock_move", "stock_move_line", "stock_quant",
            },
        )

    def test_template_count_uses_all_templates_not_only_product_variants(self):
        tool = load_module()

        class Templates:
            def sudo(self):
                return self

            def with_context(self, **context):
                self.context = context
                return self

            def search_count(self, domain):
                self.domain = domain
                return 71

        templates = Templates()
        session = object.__new__(tool.OdooSession)
        session.env = {"product.template": templates}

        self.assertEqual(session._template_count(), 71)
        self.assertEqual(templates.domain, [])
        self.assertEqual(templates.context, {"active_test": False})

    def test_apply_rerun_is_a_verified_no_op(self):
        tool = load_module()
        catalog = (tool.CatalogItem("100", "Brick red"),)
        final = snapshot(tool, [product(tool, "lego", "100", "Brick red")])
        session = FakeSession(final, final)

        result = tool.reconcile(session, catalog=catalog, apply=True)

        self.assertFalse(result.changed)
        self.assertEqual(session.events, ["snapshot", "snapshot", "commit"])
    def test_mixed_picking_fails_closed_to_preserve_lego_history(self):
        tool = load_module()
        catalog = (tool.CatalogItem("100", "Brick red"),)
        before = snapshot(
            tool,
            [
                product(tool, "lego", "100", "Brick red"),
                product(tool, "old", "OLD", "Old product"),
            ],
            mixed_pickings=1,
        )
        session = FakeSession(before)

        with self.assertRaisesRegex(tool.SafetyError, "mixed"):
            tool.reconcile(session, catalog=catalog, apply=True)

        self.assertEqual(session.events, ["snapshot", "rollback"])
    def test_allowlist_is_the_stable_47_sku_catalog(self):
        tool = load_module()
        expected = {
            "173057", "184779", "237828", "274816", "301121", "301124",
            "324876", "343701", "343721", "343724", "4100853", "4159527",
            "4166960", "4183780", "4185178", "419375", "4216758", "4250172",
            "4250173", "4648231", "4648234", "4652854", "498235", "518295",
            "6004979", "6023350", "6059082", "6096680", "6101121", "6135522",
            "6138111", "6167549", "6171865", "619287", "6214736", "6256703",
            "6269088", "6286339", "6294208", "6294237", "6294241", "6294939",
            "6294943", "6346241", "6380873", "834593", "926404",
        }

        self.assertEqual({item.code for item in tool.LEGO_CATALOG}, expected)
        self.assertEqual(len(tool.LEGO_CATALOG), len(expected))
        self.assertEqual(len(expected), 47)

    def test_exported_fixture_contains_full_lager1_catalog_values(self):
        tool = load_module()
        catalog = tool.load_catalog(FIXTURE)
        by_code = {item.code: item for item in catalog}

        self.assertEqual(len(catalog), 47)
        self.assertEqual(
            hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
            "9c03764e44ff7750b6888920b3de3dc600ea1557517d2627859864977271a223",
        )
        self.assertTrue(all(item.is_storable for item in catalog))
        self.assertTrue(all(item.image_1920 for item in catalog))
        self.assertEqual(sum(bool(item.ai_reference_description) for item in catalog), 19)
        self.assertEqual(by_code["6023350"].name, "Brick 2x2x2 R=15 gelb")
        self.assertEqual(
            by_code["6023350"].ai_reference_description,
            "building block, yellow, rectangular prism with rounded top",
        )
        self.assertEqual(
            by_code["6023350"].ai_reference_image_sha1,
            "820181dc97cf5e189c47fa1c1e0816ad140e024a",
        )


if __name__ == "__main__":
    unittest.main()
