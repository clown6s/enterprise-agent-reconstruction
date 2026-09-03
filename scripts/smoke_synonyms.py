"""同义词集「增删改查 + reload」冒烟脚本，连真实 ES。

用专属 TEST_RULE_ID 做全套操作，结束后删除该规则，绝不碰业务规则。
    .venv/Scripts/python.exe scripts/smoke_synonyms.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ingestion.adapters.elasticsearch_synonyms import ElasticsearchSynonyms
from app.ingestion.bootstrap.container import build_ingestion
from app.ingestion.bootstrap.logging import setup_logging

TEST_RULE_ID = "_smoke_test_rule"
TEST_SYNONYMS = "冒烟测试词 => 测试词A,测试词B"


def _fail(msg):
    print(f"[FAIL] {msg}")
    return 1


def main() -> int:
    setup_logging()
    service = build_ingestion()
    synonyms: ElasticsearchSynonyms = service.synonyms
    if synonyms is None:
        return _fail("ES 未配置，无法测试")

    # 0. 确保同义词集存在；若缺失则重建空集（不影响已入库文档）
    try:
        synonyms.list_rules()
    except Exception:
        synonyms.create_set([])
    # 1. 清理上次失败残留
    try:
        synonyms.delete_rule(TEST_RULE_ID)
    except KeyError:
        pass

    # 1. 创建
    synonyms.add_rule(TEST_RULE_ID, TEST_SYNONYMS)
    rules = synonyms.list_rules()
    if not any(r.get("id") == TEST_RULE_ID for r in rules):
        return _fail("新增失败")
    print("[OK] 新增")

    # 2. 更新
    synonyms.update_rule(TEST_RULE_ID, "冒烟测试词 => 测试词X")
    rules = synonyms.list_rules()
    rule = next((r for r in rules if r.get("id") == TEST_RULE_ID), None)
    if not rule or rule.get("synonyms") != "冒烟测试词 => 测试词X":
        return _fail("更新失败")
    print("[OK] 更新")

    # 3. 重载
    synonyms.reload()
    print("[OK] reload")

    # 4. 再次读取（列表）
    synonyms.list_rules()
    print("[OK] 再次读取")

    # 5. 删除
    synonyms.delete_rule(TEST_RULE_ID)
    rules = synonyms.list_rules()
    if any(r.get("id") == TEST_RULE_ID for r in rules):
        return _fail("删除失败")
    print("[OK] 删除")

    print("全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())