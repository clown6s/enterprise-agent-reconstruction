"""FastAPI 的认证依赖映射，与领域层分离."""
from typing import Callable

from fastapi import Depends, HTTPException, Request, status

from ..application.auth_service import AuthService
from ..domain.exceptions import InsufficientPermissionError, InvalidTokenError, TokenExpiredError
from ..domain.models import Principal

_BEARER = "bearer "


def bearer_token_from(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith(_BEARER):
        return None
    return header[len(_BEARER):].strip() or None


def make_principal_provider(auth: AuthService,
                            required_permission: str | None = None
                            ) -> Callable[[Request], Principal]:
    """Return a FastAPI dependency that resolves a verified principal.

    ``required_permission`` optional: when set, enforces authorization and
    returns 403 if the user lacks it.
    """
    def provider(request: Request) -> Principal:
        token = bearer_token_from(request)
        if not token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="缺少访问令牌")
        try:
            principal = auth.verify_access(token)
        except TokenExpiredError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="令牌已过期") from exc
        except InvalidTokenError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="令牌无效或已吊销") from exc
        if required_permission is not None and not principal.can(required_permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="无权执行该操作")
        return principal
    return provider