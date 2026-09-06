"""不依赖基础设施的确定性、可解释意图路由。"""
import re

from ..domain.models import ChatMessage, Intent, IntentDecision
from .ports import IntentClassifier


# 权重是证据，不是权限。执行层会自行进行检查。
_TERMS = {
    Intent.NL2SQL: (
        ("统计", 3), ("查询", 2), ("查一下", 2), ("看一下", 1), ("多少", 3),
        ("几笔", 3), ("几单", 3), ("总数", 3), ("合计", 3), ("总额", 3),
        ("占比", 3), ("平均", 2), ("最大", 2), ("最小", 2), ("最高", 2),
        ("最低", 2), ("同比", 3), ("环比", 3), ("趋势", 2), ("排名", 3),
        ("排行", 3), ("本月", 2), ("上月", 2), ("上个月", 2), ("今年", 2),
        ("去年", 2), ("最近", 1), ("近", 1), ("列出", 2), ("明细", 2),
        ("金额", 2), ("总金额", 3), ("销售额", 3), ("数量", 2), ("数据", 1),
        ("报表", 2), ("记录", 1),
    ),
    Intent.SOP: (
        ("流程", 3), ("步骤", 3), ("怎么操作", 3), ("如何操作", 3),
        ("怎么办", 3), ("怎么做", 2), ("如何做", 2), ("下一步", 4),
        ("接下来", 3), ("审批", 2), ("办理", 2), ("申请", 1), ("提交", 2),
        ("需要什么材料", 3), ("需要哪些材料", 3), ("材料", 1), ("已完成", 2),
        ("完成后", 2), ("卡在", 3), ("操作指南", 3), ("作业指导", 3),
        ("检查清单", 2), ("执行规范", 2),
    ),
    Intent.KNOWLEDGE_QA: (
        ("是什么", 2), ("什么是", 2), ("为什么", 2), ("定义", 2),
        ("标准", 2), ("规定", 2), ("制度", 2), ("要求", 1), ("区别", 2),
        ("差异", 2), ("依据", 2), ("说明", 1), ("含义", 2), ("介绍", 1),
        ("作用", 1), ("原理", 2), ("解释", 2), ("背景", 1), ("规范", 2),
        ("为什么要", 2), ("如何理解", 2), ("能否说明", 2),
        ("是做什么的", 2), ("是干什么的", 2), ("是什么功能", 2), ("有什么作用", 2),
        ("有什么用途", 2), ("主要用来", 1), ("用来干嘛", 2), ("指什么", 2),
        ("统称什么", 2), ("统称", 1), ("叫什么", 2), ("称作", 2), ("称为", 2),
        ("称为什么", 2), ("是什么名字", 2), ("术语", 1), ("这个叫什么", 2),
        ("基本特征", 2), ("特征", 2), ("特点", 2), ("表现", 2), ("典型表现", 2),
        ("临床表现", 2), ("标志", 2), ("本质", 2), ("核心特征", 2),
    ),
}

_PROCESS_RE = re.compile(r"流程|步骤|审批|办理|提交|下一步|接下来|材料|操作指南|作业指导")
_SOP_ACTION_RE = re.compile(r"(?:提交|办理|审批|操作|申请|执行).{0,12}(?:流程|步骤|申请|审批|表单|系统|手续)|(?:流程|步骤).{0,12}(?:怎么|如何|办理|操作|提交)")
_DATA_RE = re.compile(
    r"统计|查询|查一下|多少|几(?:笔|单|个|件)|总数|合计|总额|金额|占比|平均|"
    r"同比|环比|排名|排行|本月|上月|今年|去年|最近|趋势|明细|报表|数据"
)


def query_signals(query: str) -> dict:
    """提取路由审计用的三类信号，避免编排层重复维护同一套规则。"""
    return {
        "knowledge_concept": bool(_KNOWLEDGE_CONCEPT_RE.search(query or "")),
        "business_domain": bool(_BUSINESS_DOMAIN_RE.search(query or "")),
        "data_operation": bool(_DATA_OPERATION_RE.search(query or "")),
    }
_NUMBER_RE = re.compile(r"(?:\d+(?:\.\d+)?|[一二两三四五六七八九十百千万亿]+)\s*(?:万|元|个|笔|单|件|天|月|年|%)")
# “怎么做/如何做”也常用于技术知识问答（例如“怎么做日志脱敏”）。
# 只有业务办理/审批类对象才应保留 SOP 倾向。
_KNOWLEDGE_ACTION_RE = re.compile(
    r"日志脱敏|脱敏|隐私保护|加密|解密|哈希|散列|权限校验|鉴权|认证|"
    r"提示词|向量|嵌入|索引|检索|模型|训练|部署|配置|调优|解析|架构|"
    r"代码|接口|API|算法|原理|机制|设计|开发|实现|排查|监控|日志"
)
_BUSINESS_SOP_RE = re.compile(
    r"采购申请|报销|审批|请假|入职|离职|合同|付款|开票|用印|流程|表单|"
    r"办理|提交|申请|手续|业务"
)

# 解释、定义和技术原理问题优先于“查询/统计/多少”等泛化数据词。
# 这些词只提供语义证据，不能单独授予进入数据库查询链路的资格。
_KNOWLEDGE_CONCEPT_RE = re.compile(
    r"是什么|什么是|为什么|有何区别|有什么区别|区别|差异|如何理解|"
    r"定义|含义|原理|机制|解释|叫什么|统称|称作|称为|怎么实现|如何实现|"
    r"向量|嵌入|表示|上下文|模型|算法|数据结构|普查"
)
# 业务域词必须与数据操作或事实指标同时出现，泛化数据词本身不足以路由到 SQL。
_BUSINESS_DOMAIN_RE = re.compile(
    r"订单|采购|请购|销售|报销|合同|客户|库存|供应商|发票|付款|项目"
)
_DATA_OPERATION_RE = re.compile(
    r"统计|查询|查一下|列出|明细|报表|合计|总额|金额|数量|销量|"
    r"占比|平均|最大|最小|最高|最低|同比|环比|趋势|排名|排行|"
    r"多少|几(?:笔|单|个|件)|本月|上月|上个月|今年|去年|最近|近"
)

# 一句话要够格作为
# 真正的拆分/混合请求，SOP 与 NL2SQL 都必须跨过此门槛；仅凭偶发关键字是不够的。
_MIX_FLOOR = 3.0


class RuleIntentRouter:
    """低成本路由明显请求，并在意图不明确时请求澄清。"""

    def __init__(self, *, min_confidence: float = 0.55, ambiguity_gap: float = 0.2):
        self.min_confidence = min_confidence
        self.ambiguity_gap = ambiguity_gap

    def route(self, query: str, history: list[ChatMessage] | None = None) -> IntentDecision:
        if not isinstance(query, str) or not query.strip():
            return IntentDecision(Intent.CLARIFICATION, 1.0, "问题为空", needs_clarification=True)
        query = query.strip()
        scores = {intent: self._term_score(query, terms) for intent, terms in _TERMS.items()}
        evidence = {intent: [] for intent in _TERMS}
        for intent, terms in _TERMS.items():
            evidence[intent].extend(term for term, _ in terms if term in query)

        # 结构信号能捕捉关键字列表中未出现的自然改写表达。
        if _PROCESS_RE.search(query):
            scores[Intent.SOP] += 1.5
            evidence[Intent.SOP].append("process_pattern")
        if _SOP_ACTION_RE.search(query):
            scores[Intent.SOP] += 2.0
            evidence[Intent.SOP].append("sop_action_pattern")
        if _DATA_RE.search(query):
            scores[Intent.NL2SQL] += 1.5
            evidence[Intent.NL2SQL].append("data_pattern")
        if _NUMBER_RE.search(query):
            scores[Intent.NL2SQL] += 2.0
            evidence[Intent.NL2SQL].append("numeric_or_time_pattern")

        # “怎么做/如何做”需要结合宾语判断：技术对象是知识问答，
        # 业务办理对象才是 SOP，不能只凭疑问句式路由。
        if (re.search(r"怎么做|如何做|怎么实现|如何实现", query)
                and _KNOWLEDGE_ACTION_RE.search(query)
                and not _BUSINESS_SOP_RE.search(query)):
            scores[Intent.KNOWLEDGE_QA] += 3.0
            scores[Intent.SOP] = max(0.0, scores[Intent.SOP] - 2.0)
            evidence[Intent.KNOWLEDGE_QA].append("knowledge_action_pattern")

        # 知识/技术概念问题优先于泛化的数据词。即使问题含有“统计、多少、
        # 数据”等词，只要没有明确的业务数据对象，就不能进入 NL2SQL。
        signals = query_signals(query)
        knowledge_concept = signals["knowledge_concept"]
        business_domain = signals["business_domain"]
        data_operation = signals["data_operation"]
        if knowledge_concept and not (business_domain and data_operation):
            evidence[Intent.KNOWLEDGE_QA].append("knowledge_concept_pattern")
            return IntentDecision(Intent.KNOWLEDGE_QA, 0.95, "概念或技术知识问题")
        # 命名/概念识别优先于描述中的流程词。比如“下一步该做什么，
        # 这个循环叫什么”是在问术语，不是在请求执行 SOP。
        naming_markers = ("叫什么", "统称", "称作", "称为", "术语",
                          "是什么名字", "指什么")
        operation_markers = ("怎么操作", "如何操作", "怎么办理", "提交什么",
                             "怎么提交", "如何办理")
        if (any(marker in query for marker in naming_markers)
                and not any(marker in query for marker in operation_markers)):
            evidence[Intent.KNOWLEDGE_QA].append("naming_pattern")
            return IntentDecision(
                Intent.KNOWLEDGE_QA, 1.0, "命名型知识问题")

        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        top_intent, top_score = ordered[0]
        if not top_score:
            previous = self._previous_intent(history)
            if previous is not None and any(word in query for word in ("那", "继续", "下一步", "多少")):
                return IntentDecision(previous, 0.65, "沿用会话意图")
            return IntentDecision(Intent.CLARIFICATION, 0.0, "无明确意图", needs_clarification=True)

        total = sum(scores.values())
        confidence = top_score / total if total else 0.0

        # 一句话中的流程 + 数据请求是相互独立的任务——但只有
        # 当二者都携带*专用*信号时。纯粹的 SOP 中出现一个裸数字（“五万”）
        # 并不是真正的 NL2SQL 证据，绝不能触发拆分。
        sop_dedicated = bool(evidence[Intent.SOP])
        nl2sql_dedicated = "data_pattern" in evidence[Intent.NL2SQL] or any(
            t in query for t in ("统计", "查询", "多少", "几笔", "几单", "合计",
                                 "金额", "占比", "排名", "明细", "报表"))
        # “怎么做”类语句即使带少量技术词，也多数是知识问答，不构成 SOP+NL2SQL 拆分。
        if any(t in query for t in ("怎么做", "怎么实现", "如何实现", "如何做")):
            evidence[Intent.KNOWLEDGE_QA].append("howto_fallback")
            scores[Intent.KNOWLEDGE_QA] += 1.5
        if (scores[Intent.SOP] >= _MIX_FLOOR and scores[Intent.NL2SQL] >= _MIX_FLOOR
                and sop_dedicated and nl2sql_dedicated
                and scores[Intent.KNOWLEDGE_QA] < _MIX_FLOOR):
            return IntentDecision(Intent.MIXED, confidence, "同时含流程与数据查询信号")
        if confidence < self.min_confidence:
            return IntentDecision(Intent.CLARIFICATION, confidence, "意图置信度不足", needs_clarification=True)
        reason = "规则与结构信号命中: " + ",".join(evidence[top_intent][:6])
        return IntentDecision(top_intent, confidence, reason)

    @staticmethod
    def _term_score(query: str, terms: tuple[tuple[str, int], ...]) -> float:
        return float(sum(weight for term, weight in terms if term in query))

    @staticmethod
    def _previous_intent(history: list[ChatMessage] | None) -> Intent | None:
        if not history:
            return None
        for message in reversed(history):
            if message.role == "assistant":
                for intent in Intent:
                    if f"mode={intent.value}" in message.content:
                        return intent
        return None


class HybridIntentRouter:
    """规则优先、语义模型兜底的路由器。"""

    def __init__(self, rules: RuleIntentRouter, classifier: IntentClassifier | None = None):
        self.rules = rules
        self.classifier = classifier

    def route(self, query: str, history: list[ChatMessage] | None = None) -> IntentDecision:
        rule = self.rules.route(query, history)
        # 规则给出明确单一结论时不调用模型，控制成本和延迟。
        if (rule.intent == Intent.KNOWLEDGE_QA
                or (("怎么" in query or "如何" in query)
                    and _KNOWLEDGE_ACTION_RE.search(query))):
            return IntentDecision(Intent.KNOWLEDGE_QA, 0.9, "技术知识问题")
        if (self.classifier is None or rule.intent not in
                (Intent.CLARIFICATION, Intent.MIXED) and rule.confidence >= self.rules.min_confidence):
            return rule
        if self.classifier is None:
            return rule
        semantic = self.classifier.classify(query, history)
        if semantic.intent == Intent.CLARIFICATION or semantic.confidence < self.classifier.min_confidence:
            return rule if rule.intent not in (Intent.CLARIFICATION, Intent.MIXED) else semantic
        return semantic
