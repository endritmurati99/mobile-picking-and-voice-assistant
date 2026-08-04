import hashlib
import json

from odoo.tests.common import TransactionCase


class TestQualityEventBuilder(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param(
            "picking_assistant.instance_name", "local"
        )
        self.alert = self.env["quality.alert.custom"].create(
            {"description": "Karton zerdrueckt", "priority": "2"}
        )

    def _built(self):
        return self.env["quality.alert.event.builder"].build(self.alert)

    def test_fingerprint_is_sha256_of_the_stored_bytes(self):
        built = self._built()
        expected = hashlib.sha256(built["envelope_text"].encode("utf-8")).hexdigest()
        self.assertEqual(built["payload_fingerprint"], expected)

    def test_envelope_is_canonical_json(self):
        text = self._built()["envelope_text"]
        parsed = json.loads(text)
        self.assertEqual(
            text,
            json.dumps(
                parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ),
        )

    def test_envelope_carries_the_configured_instance(self):
        envelope = json.loads(self._built()["envelope_text"])
        self.assertEqual(envelope["source"]["odoo_instance"], "local")
        self.assertEqual(envelope["source"]["service"], "picking-assistant-api")
        self.assertEqual(envelope["event_name"], "quality.assessment.requested.v1")
        self.assertEqual(envelope["schema_version"], "v2")

    def test_aggregate_points_at_the_alert(self):
        envelope = json.loads(self._built()["envelope_text"])
        self.assertEqual(envelope["aggregate"]["model"], "quality.alert.custom")
        self.assertEqual(envelope["aggregate"]["id"], self.alert.id)
        self.assertEqual(envelope["aggregate"]["revision"], 1)

    def test_payload_carries_five_generations_of_callback_ids(self):
        payload = json.loads(self._built()["envelope_text"])["payload"]
        ids = payload["callback_ids_by_generation"]
        self.assertEqual(sorted(ids), ["1", "2", "3", "4", "5"])
        terminals = [entry["terminal"] for entry in ids.values()]
        self.assertEqual(len(set(terminals)), 5)

    def test_payload_carries_the_job_id_the_acceptance_needs(self):
        built = self._built()
        payload = json.loads(built["envelope_text"])["payload"]
        self.assertEqual(payload["job_id"], built["job_id"])

    def test_two_builds_use_distinct_event_ids(self):
        self.assertNotEqual(self._built()["event_id"], self._built()["event_id"])
