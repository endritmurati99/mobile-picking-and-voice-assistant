"""Liste der verfuegbaren Odoo-Instanzen (nur Namen, keine Secrets)."""
from fastapi import APIRouter

from app.config import get_instance_registry

router = APIRouter()


@router.get("/instances")
def list_instances() -> list[dict[str, str]]:
    return [
        {"name": profile.name, "display_name": profile.display_name}
        for profile in get_instance_registry().values()
    ]
