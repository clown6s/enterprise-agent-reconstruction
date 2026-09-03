"""用于认证端点的HTTP适配器."""
from dataclasses import asdict
from typing import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..application.auth_service import AuthService
from ..domain.exceptions import InvalidCredentialsError, InvalidTokenError
from ..domain.models import Principal


class LoginRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


def _principal_payload(principal: Principal) -> dict:
    return {
        "tenant_id": principal.tenant_id,
        "user_id": principal.user_id,
        "username": principal.username,
        "roles": list(principal.roles),
        "department_ids": list(principal.department_ids),
        "permissions": list(principal.permissions),
    }


def create_router(auth: AuthService, principal_provider: Callable[[Request], Principal] | None = None):
    if principal_provider is None:
        raise ValueError("principal_provider 不能为空")
    router = APIRouter(prefix="/auth", tags=["auth"])

    @router.post("/login")
    def login(request: LoginRequest):
        try:
            result = auth.login(request.tenant_id, request.username, request.password)
        except InvalidCredentialsError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="用户名或密码错误") from exc
        return {
            "access_token": result.access_token,
            "refresh_token": result.refresh_token,
            "token_type": "bearer",
            "expires_in": result.expires_in,
            "user": _principal_payload(result.principal),
        }

    @router.post("/refresh")
    def refresh(request: RefreshRequest):
        try:
            result = auth.refresh(request.refresh_token)
        except InvalidTokenError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="刷新令牌无效或已过期") from exc
        return {
            "access_token": result.access_token,
            "refresh_token": result.refresh_token,
            "token_type": "bearer",
            "expires_in": result.expires_in,
            "user": _principal_payload(result.principal),
        }

    @router.get("/me")
    def me(principal: Principal = Depends(principal_provider)):
        return _principal_payload(principal)

    @router.post("/logout")
    def logout(principal: Principal = Depends(principal_provider)):
        auth.logout(principal)
        return {"ok": True}

    return router
