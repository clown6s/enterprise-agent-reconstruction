"""依赖就绪检查，结果只暴露安全状态，不暴露连接细节。"""
from collections.abc import Callable
import socket
from urllib.parse import urlparse


class CompositeHealthChecker:
    """执行注入的检查函数；每个检查互相隔离，单项失败不泄露异常。"""
    def __init__(self, checks: dict[str, Callable[[], bool | str]]):
        self._checks = dict(checks)

    def statuses(self) -> dict[str, str]:
        result = {}
        for name, checker in self._checks.items():
            try:
                value = checker()
                result[name] = value if value in {"ok", "unavailable", "not_configured"} \
                    else ("ok" if bool(value) else "unavailable")
            except Exception:
                result[name] = "unavailable"
        return result

    def check(self) -> bool:
        return all(value == "ok" for value in self.statuses().values())


def configured(value: str | None) -> Callable[[], str]:
    """返回配置状态；只用于尚未创建客户端的依赖。"""
    return lambda: "ok" if value and value.strip() else "not_configured"


def tcp_endpoint(url: str, port: int, *, timeout: float = 1.5) -> Callable[[], str]:
    """检查 TCP 端口是否可达；只返回状态，不返回地址或异常详情。"""
    def check():
        host = urlparse(url).hostname if "://" in url else url
        if not host:
            return "not_configured"
        try:
            with socket.create_connection((host, int(port)), timeout=timeout):
                return "ok"
        except OSError:
            return "unavailable"
    return check


def ping(client) -> Callable[[], str]:
    """对已有客户端执行轻量 ping；客户端不具备 ping 时报告未配置。"""
    def check():
        method = getattr(client, "ping", None)
        if not callable(method):
            return "not_configured"
        return "ok" if bool(method()) else "unavailable"
    return check
