import pytest
from unittest.mock import AsyncMock

from app.services.mobile_workflow import (
    ClaimConflictError,
    IdempotencyReservation,
    MobileWorkflowService,
    PickerIdentity,
    WriteRequestContext,
)


@pytest.fixture
def odoo():
    return AsyncMock()


@pytest.fixture
def service(odoo):
    return MobileWorkflowService(odoo)


class TestMobileWorkflowService:
    @pytest.mark.anyio
    async def test_list_pickers_returns_sorted_active_users(self, service, odoo):
        odoo.search_read.return_value = [
            {"id": 5, "name": "Zoe"},
            {"id": 3, "name": "Anna"},
        ]

        result = await service.list_pickers()

        assert result == [
            {"id": 3, "name": "Anna"},
            {"id": 5, "name": "Zoe"},
        ]

    def test_build_request_fingerprint_is_stable(self, service):
        fingerprint_a = service.build_request_fingerprint({"b": 2, "a": 1})
        fingerprint_b = service.build_request_fingerprint({"a": 1, "b": 2})

        assert fingerprint_a == fingerprint_b

    @pytest.mark.anyio
    async def test_resolve_identity_loads_picker_name(self, service, odoo):
        odoo.search_read.return_value = [{"id": 8, "name": "Lea Lager"}]

        result = await service.resolve_identity(PickerIdentity(user_id=8, device_id="scanner-1"))

        assert result.user_id == 8
        assert result.device_id == "scanner-1"
        assert result.picker_name == "Lea Lager"

    @pytest.mark.anyio
    async def test_claim_picking_raises_on_conflict(self, service, odoo):
        odoo.execute_kw.return_value = {
            "conflict": True,
            "claimed_by_name": "Andere Person",
            "claim_expires_at": "2026-03-24 10:02:00",
        }

        with pytest.raises(ClaimConflictError) as exc:
            await service.claim_picking(44, PickerIdentity(user_id=7, device_id="scanner-2"))

        assert exc.value.detail["claimed_by_name"] == "Andere Person"

    @pytest.mark.anyio
    async def test_begin_idempotent_request_is_disabled_without_key(self, service):
        reservation = await service.begin_idempotent_request(
            "pickings.confirm-line",
            WriteRequestContext(),
            "abc123",
            picking_id=10,
        )

        assert reservation.status == "disabled"
        assert reservation.entry_id is None

    @pytest.mark.anyio
    async def test_begin_idempotent_request_maps_completed_replay(self, service, odoo):
        odoo.execute_kw.return_value = {
            "status": "replay",
            "entry_id": 12,
            "status_code": 200,
            "response_payload": {"success": True, "message": "Bereits verarbeitet."},
        }

        reservation = await service.begin_idempotent_request(
            "pickings.confirm-line",
            WriteRequestContext(
                idempotency_key="abc-1",
                identity=PickerIdentity(user_id=9, device_id="scanner-9"),
            ),
            "fingerprint-1",
            picking_id=55,
        )

        assert reservation.status == "replay"
        assert reservation.entry_id == 12
        assert reservation.response_payload == {"success": True, "message": "Bereits verarbeitet."}
        assert reservation.should_replay is True

    @pytest.mark.anyio
    async def test_finalize_idempotent_request_persists_completed_response(self, service, odoo):
        reservation = IdempotencyReservation(status="reserved", entry_id=21)

        await service.finalize_idempotent_request(
            reservation,
            {"success": True},
            201,
        )

        odoo.execute_kw.assert_awaited_once_with(
            "picking.assistant.idempotency",
            "api_finalize_request",
            [21, {"success": True}, 201],
        )

    @pytest.mark.anyio
    async def test_abort_idempotent_request_skips_inactive_reservation(self, service, odoo):
        await service.abort_idempotent_request(IdempotencyReservation(status="disabled"))

        odoo.execute_kw.assert_not_awaited()
