export function factFields(document) {
  const result = {};
  function visit(value, path) {
    if (value && typeof value === 'object' && 'text' in value && 'source' in value) result[path] = value;
    else if (Array.isArray(value)) value.forEach((item, index) => visit(item, `${path}.${index}`));
    else if (value && typeof value === 'object') Object.entries(value).forEach(([key, item]) => visit(item, path ? `${path}.${key}` : key));
  }
  visit(document, '');
  return result;
}
export function changedFields(original, values) {
  const fields = factFields(original);
  return Object.entries(values).filter(([path, value]) => value.trim() !== (fields[path]?.text ?? ''))
    .map(([path, value]) => ({ path, value }));
}
export function quoteParts(text, span) {
  const chars = Array.from(text);
  return [chars.slice(0, span.start).join(''), chars.slice(span.start, span.end).join(''), chars.slice(span.end).join('')];
}
export function extractionSummary(document) {
  return {
    fields: Object.keys(factFields(document)).length,
    education: document.education?.length ?? 0,
    experience: document.experience?.length ?? 0,
    projects: document.projects?.length ?? 0,
    skills: document.skills?.length ?? 0,
  };
}
export const example = `姓名：演示同学
邮箱：demo@example.invalid
城市：北京

教育经历
示例大学 | 硕士 | 计算机技术 | 2024.09—2027.06

项目经历
求职资料管理工具 | 项目开发 | 2025.03—2025.06
- 使用 Python 和 FastAPI 实现资料录入与查询接口。
- 为接口编写回归测试，检查异常输入和重复提交。

技能
Python、FastAPI、SQL、Git
`;
