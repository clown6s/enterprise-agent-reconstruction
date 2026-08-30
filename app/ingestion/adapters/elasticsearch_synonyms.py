"""Elasticsearch Synonyms Set management adapter."""
from typing import Any

try:
    from elasticsearch import Elasticsearch
except ImportError:  # 允许未安装 ES 客户端时运行不启用 ES 的测试/命令。
    Elasticsearch = None


class ElasticsearchSynonyms:
    """Manage an Elasticsearch synonym set without exposing client details."""

    def __init__(self, *, host: str, index: str, synonyms_set: str = "enterprise-retrieval-synonyms",
                 username: str = "", password: str = "", cert_fingerprint: str = "",
                 timeout: float = 10.0, client=None):
        if not host or not index or not synonyms_set:
            raise ValueError("ES host、index 和 synonyms_set 不能为空")
        self._index = index
        self._set = synonyms_set
        if client is not None:
            self._client = client
        else:
            if Elasticsearch is None:
                raise RuntimeError("未安装 elasticsearch 客户端")
            kwargs: dict[str, Any] = {"request_timeout": timeout}
            if username or password:
                if not username or not password:
                    raise ValueError("ES 用户名和密码必须同时配置")
                kwargs["basic_auth"] = (username, password)
            if cert_fingerprint:
                kwargs["ssl_assert_fingerprint"] = cert_fingerprint
            self._client = Elasticsearch(host, **kwargs)
        self._client.info()

    def list_sets(self) -> list[dict]:
        """查询全部 Synonyms Set。"""
        response = self._client.synonyms.get_synonyms_sets()
        body = response.body if hasattr(response, "body") else response
        return list(body.get("results", []))

    def get_set(self, set_id: str | None = None) -> dict:
        """查询单个 Synonyms Set。"""
        response = self._client.synonyms.get_synonym(id=set_id or self._set)
        return response.body if hasattr(response, "body") else dict(response)

    def delete_set(self, set_id: str | None = None) -> None:
        """删除单个 Synonyms Set。"""
        self._client.synonyms.delete_synonym(id=set_id or self._set)

    def update_set(self, set_id: str, rules: list[dict]) -> None:
        """整体修改单个 Synonyms Set。"""
        self._validate_rules(rules)
        self._client.synonyms.put_synonym(id=set_id, synonyms_set=rules)
        if set_id == self._set:
            self.reload()

    def list_rules(self) -> list[dict]:
        return list(self.get_set().get("synonyms_set", []))

    def create_set(self, rules: list[dict] | None = None, set_id: str | None = None) -> None:
        """创建同义词集；已存在时由 ES 返回冲突错误。"""
        rules = rules or []
        self._validate_rules(rules)
        self._client.synonyms.put_synonym(id=set_id or self._set, synonyms_set=rules)

    def replace_all(self, rules: list[dict]) -> None:
        self._validate_rules(rules)
        self._client.synonyms.put_synonym(id=self._set, synonyms_set=rules)
        self.reload()

    def add_rule(self, rule_id: str, synonyms: str) -> None:
        rules = self.list_rules()
        if any(rule.get("id") == rule_id for rule in rules):
            raise ValueError(f"同义词规则已存在: {rule_id}")
        rules.append({"id": rule_id, "synonyms": synonyms})
        self.replace_all(rules)

    def update_rule(self, rule_id: str, synonyms: str) -> None:
        rules = self.list_rules()
        for rule in rules:
            if rule.get("id") == rule_id:
                rule["synonyms"] = synonyms
                self.replace_all(rules)
                return
        raise KeyError(f"同义词规则不存在: {rule_id}")

    def delete_rule(self, rule_id: str) -> None:
        rules = self.list_rules()
        updated = [rule for rule in rules if rule.get("id") != rule_id]
        if len(updated) == len(rules):
            raise KeyError(f"同义词规则不存在: {rule_id}")
        self.replace_all(updated)

    def reload(self, index: str | None = None) -> None:
        target = index or self._index
        self._client.indices.reload_search_analyzers(index=target)

    @staticmethod
    def _validate_rules(rules: list[dict]) -> None:
        if not isinstance(rules, list):
            raise ValueError("rules 必须是列表")
        ids = set()
        for rule in rules:
            if not isinstance(rule, dict) or not rule.get("id") or not rule.get("synonyms"):
                raise ValueError("每条规则必须包含非空 id 和 synonyms")
            if rule["id"] in ids:
                raise ValueError(f"同义词规则 id 重复: {rule['id']}")
            ids.add(rule["id"])
