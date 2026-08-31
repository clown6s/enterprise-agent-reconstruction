"""业务异常统一基类。

所有业务/适配器层抛出的异常都应从 :class:`AppError` 派生，这样上层只需
``except AppError`` 即可接住全部业务错误，并由接口层统一翻译成 HTTP 响应。

类型分层用于表达错误的语义，从而让各层（尤其是接口层）能区分：
- :class:`ValidationError`     输入/配置校验失败，永不重试；
- :class:`ProcessingError`     文档解析/处理失败，与外部依赖无关；
- :class:`InfrastructureError` 外部依赖故障（Elasticsearch / Milvus /
  Embedding / MySQL），语义上可重试。

适配器层应把外部依赖抛出的原始异常封装成对应的 :class:`InfrastructureError`
子类，并用 ``from exc`` 保留原始异常链，便于排查根因。
"""


class AppError(Exception):
    """业务异常统一基类。"""


class ValidationError(AppError):
    """输入或配置校验失败。

    与 ``ValueError`` 不同，它语义明确：表示请求/配置本身有问题，
    重试不会成功，接口层应映射为 400。
    """


class ProcessingError(AppError):
    """文档解析或处理阶段的失败，与外部依赖无关。"""


class InfrastructureError(AppError):
    """外部基础设施故障（网络、超时、依赖服务不可用等）。

    语义上属于"可重试"故障，接口层应映射为 503。
    """


class ElasticsearchError(InfrastructureError):
    """Elasticsearch 调用失败（含连接超时）。"""


class MilvusError(InfrastructureError):
    """Milvus 调用失败。"""


class EmbeddingError(InfrastructureError):
    """Embedding 服务（SiliconFlow 等）调用失败。"""


class MetadataStoreError(InfrastructureError):
    """元数据存储（MySQL）调用失败。"""
