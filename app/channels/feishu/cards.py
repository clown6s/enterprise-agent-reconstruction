"""飞书卡片渲染器：只负责展示，不决定业务状态或权限。"""
from dataclasses import asdict
import json


class FeishuCardRenderer:
    """把 ChatResult 转成可发送的 interactive card。"""

    def render(self, result, *, action_id: str | None = None) -> str:
        mode = getattr(result.mode, "value", str(result.mode))
        elements = [{"tag": "markdown", "content": result.answer[:6000]}]
        if mode == "sop" and result.sop:
            sop = result.sop
            elements.append({
                "tag": "note", "elements": [{"tag": "plain_text",
                "content": f"SOP {sop.get('sop_id', '')} / {sop.get('version', '')} · 步骤 {sop.get('current_step', '')}"}],
            })
            if sop.get("high_risk") and action_id:
                elements.append({"tag": "action", "actions": [{
                    "tag": "button", "text": {"tag": "plain_text", "content": "确认继续"},
                    "type": "primary", "value": {"action": "sop_confirm", "action_id": action_id},
                }]})
        elif mode == "nl2sql" and result.sql:
            sql = result.sql
            elements.append({"tag": "note", "elements": [{"tag": "plain_text",
                "content": f"查询 {sql.get('query_id', '')} · 返回 {sql.get('row_count', 0)} 行"}]})
        return json.dumps({"schema": "1.0", "body": {"elements": elements}}, ensure_ascii=False)

    @staticmethod
    def confirmation_payload(action_id: str, conversation_id: str, expected_version: int) -> dict:
        """生成不携带身份的 opaque action 数据，身份由回调上下文解析。"""
        return {"action": "sop_confirm", "action_id": action_id,
                "conversation_id": conversation_id, "expected_version": expected_version}
