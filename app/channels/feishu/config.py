"""飞书渠道配置；不在此创建 SDK 客户端。"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class FeishuSettings:
    enabled: bool = False
    app_id: str = ""
    app_secret: str = ""
    tenant_id: str = ""
    http_timeout: float = 10.0
    retry_max: int = 3
    require_mention: bool = True
    allow_sop_action: bool = False

    @property
    def usable(self) -> bool:
        return self.enabled and bool(self.app_id and self.app_secret)


def read_settings() -> FeishuSettings:
    return FeishuSettings(
        enabled=os.getenv("FEISHU_ENABLED", "false").lower() == "true",
        app_id=os.getenv("FEISHU_APP_ID", ""),
        app_secret=os.getenv("FEISHU_APP_SECRET", ""),
        tenant_id=os.getenv("FEISHU_TENANT_ID", ""),
        http_timeout=float(os.getenv("FEISHU_HTTP_TIMEOUT", "10")),
        retry_max=max(0, int(os.getenv("FEISHU_EVENT_RETRY_MAX", "3"))),
        require_mention=os.getenv("FEISHU_GROUP_REQUIRE_MENTION", "true").lower() == "true",
        allow_sop_action=os.getenv("FEISHU_ALLOW_SOP_ACTION", "false").lower() == "true",
    )
