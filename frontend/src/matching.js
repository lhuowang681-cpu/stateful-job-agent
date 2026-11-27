export function matchLabel(row, mode) {
  if (row.has_contradiction) return '冲突或范围限制 · 待核对';
  if (mode === 'local_check') return row.links.length ? '待核对线索' : '未定位线索';
  return ({unverified_lead: '简历自述 · 未独立核实', gap: '材料缺口', unsupported: '当前引用未支持', partial: '部分支持', supported: '支持'})[row.match_status] ?? '待核对';
}
