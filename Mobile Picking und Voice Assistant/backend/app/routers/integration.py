from fastapi import APIRouter, Depends

from app.dependencies import require_n8n_callback_secret
from app.schemas.obsidian import ObsidianLogRequest
from app.services.integration_log import write_daily_note_log


router = APIRouter(prefix="/integration", tags=["integration"])


@router.post("/log", dependencies=[Depends(require_n8n_callback_secret)])
async def log_integration_event(request: ObsidianLogRequest):
    return write_daily_note_log(request)
