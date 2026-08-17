from dataclasses import dataclass
from datetime import datetime
from typing import FrozenSet
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PickerSessionLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    login: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=1024)
    device_id: UUID
    odoo_instance: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")

    @field_validator("odoo_instance")
    @classmethod
    def normalize_instance(cls, value: str) -> str:
        return value.lower()


class InstanceSwitchRequest(BaseModel):
    """Der Lagerwechsel kennt nur ein Feld -- alles andere steht in der Sitzung.

    Kein `login`, kein `device_id`: beides aus dem Cookie zu nehmen ist nicht
    nur kuerzer, es ist der Punkt. Ein Client, der hier einen Anmeldenamen
    mitschicken duerfte, koennte sich in ein fremdes Konto wechseln.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    odoo_instance: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")

    @field_validator("odoo_instance")
    @classmethod
    def normalize_instance(cls, value: str) -> str:
        return value.lower()


@dataclass(frozen=True)
class SessionTokenHint:
    version: str
    odoo_instance: str
    token_hash: str


@dataclass(frozen=True)
class Principal:
    picker_user_id: int
    picker_name: str
    device_id: str
    odoo_instance: str
    roles: FrozenSet[str]
    session_id: str
    expires_at: datetime


class PrincipalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    picker_user_id: int
    picker_name: str
    device_id: str
    odoo_instance: str
    roles: list[str]
    session_id: UUID
    expires_at: datetime

    @classmethod
    def from_principal(cls, principal: Principal) -> "PrincipalResponse":
        return cls(
            picker_user_id=principal.picker_user_id,
            picker_name=principal.picker_name,
            device_id=principal.device_id,
            odoo_instance=principal.odoo_instance,
            roles=sorted(principal.roles),
            session_id=principal.session_id,
            expires_at=principal.expires_at,
        )


class PickerSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    principal: PrincipalResponse
    csrf_token: str = Field(min_length=43, max_length=128)


class CsrfResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csrf_token: str = Field(min_length=43, max_length=128)
