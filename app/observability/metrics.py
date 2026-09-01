"""Prometheus 业务指标定义。

约定：指标 label 只使用低基数取值（stage/status/intent/kind），
绝不允许把用户问题、tenant/user 原文、Token、SQL 参数作为 label。
"""
from prometheus_client import Counter, Histogram

# 请求与错误
chat_requests_total = Counter(
    "chat_requests_total", "Chat 请求总数", ["stage", "status"])

# 意图分类分布
chat_intent_total = Counter(
    "chat_intent_total", "意图分类计数", ["intent"])

# RAG 检索与引用
rag_retrieval_total = Counter(
    "rag_retrieval_total", "RAG 检索次数", ["status"])
rag_retrieved_items = Histogram(
    "rag_retrieved_items", "RAG 单次召回的候选数量",
    buckets=[1, 2, 3, 5, 8, 10, 15, 20, 50])

# LLM 调用
llm_requests_total = Counter(
    "llm_requests_total", "LLM 调用次数", ["kind", "status"])
llm_duration_seconds = Histogram(
    "llm_duration_seconds", "LLM 调用耗时（秒）", ["kind"])

# NL2SQL
nl2sql_total = Counter(
    "nl2sql_total", "NL2SQL 查询次数", ["status"])

# SOP
sop_total = Counter(
    "sop_total", "SOP 步骤处理次数", ["status"])

# 限流
rate_limited_total = Counter(
    "rate_limited_total", "被限流拒绝的请求次数", ["scope"])

# 依赖故障
dependency_failures_total = Counter(
    "dependency_failures_total", "外部依赖调用失败次数", ["dependency", "kind"])
