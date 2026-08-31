"""Composition root 的配置加载与生产依赖校验。

只负责从环境读取配置、加载 .env、校验配置组合是否完整，
不实例化任何适配器或应用对象。装配由 container 完成。
"""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

from ..domain.exceptions import ValidationError


class ConfigurationError(ValidationError):
    """生产依赖配置不完整或互相矛盾。"""


def load_env() -> None:
    """从项目根目录显式加载环境变量，避免依赖调用栈推断路径。"""
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    load_dotenv(os.path.join(project_root, ".env"))


@dataclass(frozen=True)
class IngestionSettings:
    """从环境读取并校验后的摄入配置。"""
    embedding_dim: int
    has_embedding_key: bool      # 是否配置了 SILICONFLOW_API_KEY
    has_milvus: bool             # 是否配置了 MILVUS_HOST
    has_es: bool                 # 是否配置了 ES_HOST
    has_mysql: bool              # 是否配置了 MYSQL_HOST


def read_settings() -> IngestionSettings:
    """读取并校验环境变量，返回稳定的配置值对象。"""
    try:
        embedding_dim = int(os.getenv("EMBEDDING_DIM", "4096"))
    except ValueError as exc:
        raise ConfigurationError("EMBEDDING_DIM 必须为整数") from exc
    if embedding_dim <= 0:
        raise ConfigurationError("EMBEDDING_DIM 必须为正数")
    return IngestionSettings(
        embedding_dim=embedding_dim,
        has_embedding_key=bool(os.getenv("SILICONFLOW_API_KEY")),
        has_milvus=bool(os.getenv("MILVUS_HOST")),
        has_es=bool(os.getenv("ES_HOST")),
        has_mysql=bool(os.getenv("MYSQL_HOST")),
    )


def validate_composition(mode: str, settings: IngestionSettings, *,
                         embedder, vectors, metadata) -> None:
    """校验注入依赖与真实配置必须成组出现，避免'看似成功但数据没有保存'。

    允许在 test/offline 模式下用自定义依赖或 no-op 实现。
    """
    effective_embedder = embedder is not None or settings.has_embedding_key
    effective_vectors = vectors is not None or settings.has_milvus
    effective_lexical = settings.has_es
    if mode == "production" and not (effective_embedder and effective_vectors):
        raise ConfigurationError("生产模式必须配置真实 Embedding 与向量库")
    if effective_embedder != effective_vectors:
        raise ConfigurationError("Embedding 与向量库必须同时配置")
    if effective_vectors and not effective_lexical:
        raise ConfigurationError("启用向量库时必须同时配置全文检索(ES_HOST)")
    if effective_embedder and not (metadata is not None or settings.has_mysql):
        raise ConfigurationError("Embedding、向量库与元数据存储必须同时配置")
    if (settings.has_embedding_key or settings.has_milvus) and (
            settings.has_embedding_key != settings.has_milvus):
        raise ConfigurationError("SILICONFLOW_API_KEY 与 MILVUS_HOST 必须同时配置")
