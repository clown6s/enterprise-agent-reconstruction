"""SOP execution state machine. The engine, not the LLM, decides valid next steps."""
from dataclasses import replace

from ...domain.exceptions import SopError
from ...domain.models import SopDefinition, SopExecutionState, SopStep


class SopEngine:
    def __init__(self):
        self._high_risk_markers = ("付款", "删除", "修改权限", "对外发送", "关闭账户")

    def begin(self, definition: SopDefinition) -> SopExecutionState:
        if not definition.steps:
            raise SopError(f"SOP {definition.sop_id} 没有步骤")
        first = min(definition.steps, key=lambda step: step.sequence)
        return SopExecutionState(sop_id=definition.sop_id, version=definition.version,
                                 current_step_id=first.step_id)

    def current(self, definition: SopDefinition, state: SopExecutionState) -> SopStep:
        for step in definition.steps:
            if step.step_id == state.current_step_id:
                return step
        raise SopError(f"SOP {definition.sop_id} 未找到步骤 {state.current_step_id}")

    def advance(self, definition: SopDefinition, state: SopExecutionState,
                *, confirmed: bool = False) -> SopExecutionState:
        step = self.current(definition, state)
        if step.requires_confirmation and not confirmed:
            return replace(state, awaiting_confirmation=True)
        completed_steps = (state.completed_steps
                           if step.step_id in state.completed_steps
                           else state.completed_steps + (step.step_id,))
        if not step.next_steps:
            # 终态步骤保持当前位置，并且重复请求不会重复记录步骤。
            return replace(state, awaiting_confirmation=False,
                           completed_steps=completed_steps)
        next_id = step.next_steps[0]
        return replace(state, current_step_id=next_id, awaiting_confirmation=False,
                       completed_steps=completed_steps)

    def is_high_risk(self, step: SopStep) -> bool:
        return step.requires_confirmation or any(
            marker in step.instruction for marker in self._high_risk_markers)
