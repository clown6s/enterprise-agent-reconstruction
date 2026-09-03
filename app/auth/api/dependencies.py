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


def make_principal_provider(auth_provider: Callable[[], AuthService],
                            required_permission: str | None = None
                            ) -> Callable[[Request], Principal]:
    """返回一个解析已验证主体的 FastAPI 依赖。

    ``required_permission`` 可选：设置后强制授权，用户缺少权限时返回 403。
    """
    def provider(request: Request) -> Principal:
        token = bearer_token_from(request)
        if not token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="缺少访问令牌")
        try:
            principal = auth_provider().verify_access(token)
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