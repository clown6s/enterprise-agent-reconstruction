"""面向内存存储的默认种子数据（SOP 与 schema catalog）。"""
from ..domain.models import SopDefinition, SopStep


def default_sops() -> list[SopDefinition]:
    return [
        SopDefinition(
            sop_id="expense_claim", version="v3", title="报销流程",
            scope="费用报销", roles=("employee", "manager", "finance"),
            steps=(
                SopStep("s1", 1, "提交报销申请，附发票和审批单",
                        preconditions=("已发生合规费用",), inputs=("发票", "事由", "金额"),
                        next_steps=("s2",)),
                SopStep("s2", 2, "部门负责人审批",
                        inputs=("审批意见",), next_steps=("s3",)),
                SopStep("s3", 3, "财务复核并打款",
                        inputs=("付款账户",), requires_confirmation=True,
                        warnings=("涉及资金支付",)),
            ),
        ),
        SopDefinition(
            sop_id="procurement", version="v1", title="采购申请流程",
            scope="采购", roles=("requester", "manager", "finance"),
            steps=(
                SopStep("p1", 1, "填写采购申请（品名、数量、预算）",
                        inputs=("品名", "数量", "预算"), next_steps=("p2",)),
                SopStep("p2", 2, "预算负责人审批", inputs=("审批意见",),
                        next_steps=("p3",)),
                SopStep("p3", 3, "下单采购", requires_confirmation=True,
                        warnings=("产生采购支出",)),
            ),
        ),
    ]


def default_schema_domains():
    from ..adapters.memory_schema_catalog import SchemaDomain
    return [
        SchemaDomain(
            name="procurement", description="采购申请数据",
            tables=frozenset({"procurement_requests", "procurement_items"}),
            keywords=("采购", "订单", "请购"),
        ),
        SchemaDomain(
            name="orders", description="订单与销售数据",
            tables=frozenset({"orders", "order_items"}),
            keywords=("订单", "销售", "销售额", "销量"),
        ),
    ]
