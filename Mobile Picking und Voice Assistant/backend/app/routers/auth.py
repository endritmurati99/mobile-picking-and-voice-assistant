from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from app.config import get_instance_registry, settings
from app.dependencies import get_current_principal, get_session_service
from app.models.auth import (
    CsrfResponse,
    PickerSessionLoginRequest,
    PickerSessionResponse,
    Principal,
    PrincipalResponse,
)
from app.services.auth_sessions import (
    AuthenticationFailed,
    CsrfFailed,
    SessionService,
    request_source_ip,
)

router = APIRouter(prefix="/auth")


@router.get("/instances")
def list_auth_instances() -> list[dict[str, str]]:
    return [
        {"name": profile.name, "display_name": profile.display_name}
        for profile in get_instance_registry().values()
    ]


@router.post("/picker-session", response_model=PickerSessionResponse)
async def create_picker_session(
    body: PickerSessionLoginRequest,
    request: Request,
    response: Response,
    service: SessionService = Depends(get_session_service),
):
    try:
        created = await service.create_session(
            body,
            source_ip=request_source_ip(
                request,
                {item.strip() for item in settings.trusted_caddy_peers.split(",")},
            ),
            origin=request.headers.get("Origin"),
        )
    except (AuthenticationFailed, CsrfFailed) as exc:
        raise HTTPException(status_code=401, detail="Anmeldung fehlgeschlagen.") from exc
    response.set_cookie(
        key=settings.session_cookie_name,
        value=created.cookie_token,
        max_age=settings.session_max_age_seconds,
        secure=True,
        httponly=True,
        samesite="strict",
        path="/api",
    )
    return PickerSessionResponse(
        principal=PrincipalResponse.from_principal(created.principal),
        csrf_token=created.csrf_token,
    )


@router.get("/me", response_model=PrincipalResponse)
def get_me(principal: Principal = Depends(get_current_principal)):
    return PrincipalResponse.from_principal(principal)


@router.post("/csrf", response_model=CsrfResponse)
async def rotate_csrf(
    request: Request,
    principal: Principal = Depends(get_current_principal),
    service: SessionService = Depends(get_session_service),
):
    try:
        return CsrfResponse(
            csrf_token=await service.rotate_csrf(
                principal, request.headers.get("Origin")
            )
        )
    except (AuthenticationFailed, CsrfFailed) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    principal: Principal = Depends(get_current_principal),
    service: SessionService = Depends(get_session_service),
):
    try:
        await service.validate_csrf(
            principal, x_csrf_token, request.headers.get("Origin")
        )
    except CsrfFailed as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    await service.revoke(principal)
    response.delete_cookie(settings.session_cookie_name, path="/api")
