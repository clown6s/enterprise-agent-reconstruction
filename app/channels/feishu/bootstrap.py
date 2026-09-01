"""飞书渠道组合根；只在需要时装配，未启用不建任何客户端。"""
from .cards import FeishuCardRenderer
from .channel import FeishuChannel
from .client import FeishuApiClient
from .config import read_settings
from .delivery import MysqlFeishuDeliveryStore
from .idempotency import MysqlFeishuIdempotencyStore
from .identity import MysqlFeishuIdentityResolver
from app.chat.adapters.mysql_pool import MysqlPool
from app.chat.bootstrap.config import read_storage_settings


def build_feishu_channel(chat_service) -> FeishuChannel | None:
    """按配置构建飞书渠道；不可用时返回 None，不影响主服务。"""
    settings = read_settings()
    if not settings.usable:
        return None
    storage = read_storage_settings()
    pool = MysqlPool(
        host=storage.mysql_host, port=storage.mysql_port,
        user=storage.mysql_user, password=storage.mysql_password,
        database=storage.mysql_database,
    )
    client = FeishuApiClient(
        app_id=settings.app_id, app_secret=settings.app_secret,
        timeout=settings.http_timeout, max_retries=settings.retry_max,
    )
    return FeishuChannel(
        settings=settings, chat_service=chat_service, client=client,
        identity=MysqlFeishuIdentityResolver(pool),
        idempotency=MysqlFeishuIdempotencyStore(pool),
        card_renderer=FeishuCardRenderer(),
        owned_resources=(pool,),
    )
