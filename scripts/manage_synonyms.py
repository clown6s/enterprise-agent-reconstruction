"""Elasticsearch 同义词集管理脚本。

使用方式：
1. 修改下方「执行配置」中的 ACTION 和参数。
2. 执行：.venv/Scripts/python.exe scripts/manage_synonyms.py

每个 API 都对应一个独立方法；参数集中写在文件顶部，便于单独填写和执行。
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ingestion.bootstrap.container import build_ingestion

# ==================== 执行配置：按需填写 ====================
# 可选：list_sets、get_set、create_set、update_set、delete_set、
#       list_rules、add_rule、update_rule、delete_rule、reload、seed
ACTION = "list_sets"

SET_ID = "enterprise-retrieval-synonyms"
RULE_ID = "填写规则 id"
RULE_SYNONYMS = "填写口语 => 正式词1,正式词2"
RULES = [
    # {"id": "rule-id", "synonyms": "口语 => 正式词1,正式词2"},
]

INITIAL_RULES = [
    {"id": "be-hit", "synonyms": "被人打了 => 殴打他人,故意伤害,人身伤害"},
    {"id": "hit-me", "synonyms": "别人打我 => 殴打他人,故意伤害"},
    {"id": "beaten", "synonyms": "被打 => 殴打他人,故意伤害"},
    {"id": "report-useful", "synonyms": "报警有用吗 => 报警,报案,公安机关"},
    {"id": "seek-rights", "synonyms": "怎么维权 => 法律救济,赔偿责任,法律责任"},
]
# =========================================================


def _get_adapter():
    service = build_ingestion()
    if service.synonyms is None:
        raise RuntimeError("ES 未配置（ES_HOST 缺失），无法管理同义词。")
    return service.synonyms


def list_sets(synonyms) -> None:
    """查询全部同义词集及其内部规则详情。"""
    for item in synonyms.list_sets():
        set_id = item.get("synonyms_set")
        print(f"== 同义词集：{set_id}（{item.get('count')} 条规则）==")
        rules = synonyms.get_set(set_id).get("synonyms_set", [])
        for rule in rules:
            print(f"  {rule.get('id')}: {rule.get('synonyms')}")
        print()


def get_set(synonyms, set_id: str) -> None:
    """查询单个同义词集。"""
    print(json.dumps(synonyms.get_set(set_id), ensure_ascii=False, indent=2))


def create_set(synonyms, set_id: str, rules: list[dict] | None = None) -> None:
    """创建同义词集。"""
    synonyms.create_set(rules=rules or [], set_id=set_id)
    print(f"已创建同义词集：{set_id}")


def update_set(synonyms, set_id: str, rules: list[dict]) -> None:
    """整体替换单个同义词集的规则。"""
    synonyms.update_set(set_id, rules)
    print(f"已修改同义词集：{set_id}")


def delete_set(synonyms, set_id: str) -> None:
    """删除单个同义词集。"""
    synonyms.delete_set(set_id)
    print(f"已删除同义词集：{set_id}")


def list_rules(synonyms) -> None:
    """查询默认同义词集内的全部规则。"""
    for rule in synonyms.list_rules():
        print(f"{rule.get('id')}: {rule.get('synonyms')}")


def add_rule(synonyms, rule_id: str, rule_synonyms: str) -> None:
    """新增一条规则。"""
    synonyms.add_rule(rule_id, rule_synonyms)
    print(f"已新增规则：{rule_id}")


def update_rule(synonyms, rule_id: str, rule_synonyms: str) -> None:
    """修改一条规则。"""
    synonyms.update_rule(rule_id, rule_synonyms)
    print(f"已修改规则：{rule_id}")


def delete_rule(synonyms, rule_id: str) -> None:
    """删除一条规则。"""
    synonyms.delete_rule(rule_id)
    print(f"已删除规则：{rule_id}")


def reload(synonyms) -> None:
    """重新加载查询 analyzer。"""
    synonyms.reload()
    print("已重载查询 analyzer。")


def seed(synonyms) -> None:
    """写入预置规则；已存在的规则会跳过。"""
    for rule in INITIAL_RULES:
        try:
            add_rule(synonyms, rule["id"], rule["synonyms"])
        except ValueError as exc:
            print(f"跳过 {rule['id']}：{exc}")


def main() -> int:
    synonyms = _get_adapter()
    if ACTION == "list_sets":
        list_sets(synonyms)
    elif ACTION == "get_set":
        get_set(synonyms, SET_ID)
    elif ACTION == "create_set":
        create_set(synonyms, SET_ID, RULES)
    elif ACTION == "update_set":
        update_set(synonyms, SET_ID, RULES)
    elif ACTION == "delete_set":
        delete_set(synonyms, SET_ID)
    elif ACTION == "list_rules":
        list_rules(synonyms)
    elif ACTION == "add_rule":
        add_rule(synonyms, RULE_ID, RULE_SYNONYMS)
    elif ACTION == "update_rule":
        update_rule(synonyms, RULE_ID, RULE_SYNONYMS)
    elif ACTION == "delete_rule":
        delete_rule(synonyms, RULE_ID)
    elif ACTION == "reload":
        reload(synonyms)
    elif ACTION == "seed":
        seed(synonyms)
    else:
        raise ValueError(f"不支持的 ACTION：{ACTION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
