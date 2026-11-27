export function collaborationStatus(state) {
  if (state.model_inflight) return '模型调用结果待人工核对，禁止自动重放';
  return ({pending:'等待执行',running:'执行中或等待恢复',awaiting_approval:'原句检查完成 · 等待你核对相关性',needs_input:'暂未形成可接受摘录 · 请补充材料',failed:'执行失败 · 不自动重试'})[state.status] ?? '未知状态';
}
export function relevanceLabel(value) {
  return ({not_reviewed:'尚未评审',keyword_lead:'仅关键词线索 · 待人工判断',model_recommends:'模型建议保留 · 非事实证明',revise:'建议改选',needs_input:'需补上下文'})[value] ?? '待核对';
}
export function canAcceptCollaboration(view, version, unsaved) {
  return !!(view?.can_apply && view.state.status === 'awaiting_approval' &&
    view.expected_head_version_id === version.version_id && !unsaved);
}
