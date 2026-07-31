from fastapi import APIRouter

router = APIRouter()


# Task 16: der einzige pre-auth Health-Endpunkt. Er heisst `/health/live`, nicht
# `/health`, damit Readiness/Diagnose spaeter unter dem internen Router landen
# koennen, ohne dass ein generischer `/health`-Name schon vergeben ist.
@router.get("/health/live")
async def liveness():
    return {"status": "ok", "service": "picking-assistant-backend"}
