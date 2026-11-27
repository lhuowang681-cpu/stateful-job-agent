import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { changedFields, example, extractionSummary, factFields, quoteParts } from './model.js';
import './style.css';
import { MatchingPanel } from './MatchingPanel.jsx';
import { CollaborationPanel } from './CollaborationPanel.jsx';
import { InterviewPanel } from './InterviewPanel.jsx';
import { PDFPanel } from './PDFPanel.jsx';
import { RewritePanel } from './RewritePanel.jsx';
import { JobsPanel } from './JobsPanel.jsx';
import { ProjectsPanel } from './ProjectsPanel.jsx';
import { KnowledgePanel } from './KnowledgePanel.jsx';

const messages = {
  learning_revision_changed:'这条学习记录已更新，请刷新后再操作。',
  learning_preferences_changed:'复习偏好已在其他页面更新，请刷新后重新设置。',
  learning_source_not_eligible:'这条记录尚未核对、已暂停、过期或来源不可用。请刷新查看原因；撤回或失效的记录不能再用来练习。',
  learning_confirmation_required:'请先核对并确认这条观察，再标记本次复核。',
  learning_historical_version_requires_confirmation:'最新简历已变化；如要沿用原版练习，请明确勾选使用历史版本。',
  learning_practice_scope_changed:'练习的版本或来源与原观察不一致，请从学习记录重新发起。',
  learning_request_key_conflict:'本次操作与已保存的请求不一致，请刷新学习记录后重新操作。',
  learning_owner_quota_reached:'已达到当前学习记录上限（含防重建标记）。请保留需要的原记录并联系维护者核对存储范围。',
  learning_session_quota_reached:'本场可保存的观察超过上限，本次没有新增记录。',
  learning_requires_completed_source:'请先结束本场面试，再保存已回答内容的学习观察。',
  learning_record_integrity_failed:'学习记录校验未通过，本次未更新。请保留原记录并核对存储状态。',
  learning_preferences_integrity_failed:'复习偏好校验未通过，请核对存储状态后再操作。',
  github_rate_limit_exceeded_try_zip:'GitHub公开接口已限流。请稍后重试，或直接上传仓库ZIP；系统不会索取你的访问令牌。',
  github_redirect_rejected:'仓库地址发生跳转，请使用当前公开仓库的正式地址。',
  github_public_repository_unavailable:'暂时无法下载这份公开仓库，请核对地址和版本，或改用ZIP导入。',
  authentication_required: '访问口令无效，请重新连接。', needs_ocr: '这份 PDF 没有可提取文字，可能是扫描件。当前尚未接入 OCR，请粘贴识别后的文字。',
  encrypted_pdf: '请先解除 PDF 的密码保护。', unsupported_file_type: '支持 TXT、Markdown、带文字的 PDF 和 DOCX。',
  upload_too_large: '文件超过 5 MB，请缩小后重试。', document_extraction_failed: '无法提取文字，请检查文件或改用粘贴。',
  invalid_pdf: '文件不是有效的 PDF。', invalid_docx: '文件不是有效的 DOCX。', required_fields_missing: '还有必填字段未补充，请检查姓名及经历名称。',
  model_parser_unavailable: '在线模型未配置，可先使用本地解析。', model_parse_failed: '模型未返回可核验的字段，草稿未保存。请核对原文或改用本地解析。',
  model_request_failed: '模型请求失败，系统没有自动重试。请检查服务后再操作。', model_input_too_large: '材料超出本轮模型输入上限，可先使用本地模式。',
  user_edits_too_large: '一次补充的文字过多，请分次保存。',
  external_processing_consent_required: '使用在线模型前，请确认发送材料。', resume_head_changed: '其他页面已保存新版。请重新打开最新版本再修改。',
  only_current_version_can_be_confirmed: '只能确认当前最新版本。', draft_already_accepted: '此草稿已经保存，请在简历版本中继续编辑。',
  source_referenced_by_version: '来源仍被历史版本引用，请先删除相应简历。', source_referenced_by_draft: '来源仍被草稿引用，请先删除草稿。',
  local_parse_limit_or_format: '本地解析超出格式或数量限制，请精简材料，或使用已配置的模型解析。',
  match_model_unavailable: '在线分析模型未配置，可先使用本地预检查。',
  match_analysis_failed: '分析没有得到可核验的结果，未保存成功快照。请查看历史状态后再决定是否重试。',
  match_model_request_failed: '模型请求失败，已停止后续调用；如需重试，请重新确认发送。',
  match_model_budget_exceeded: '已达到本次分析调用上限，没有继续请求模型。',
  match_input_too_large: '所选版本与 JD 超出本轮分析上限，请精简材料。', jd_has_no_requirements: '未找到可检查的岗位条目，请补充岗位要求。',
  match_in_progress: '同一分析请求还在等待结果。请先刷新历史状态；服务异常退出时需要人工检查。',
  match_previous_failed: '上次分析已失败；再次点击将新建一次请求，在线模式需重新同意发送。',
  match_request_key_conflict: '请求标识与输入不一致，请刷新页面后重试。', match_version_changed: '简历内容已变化，请重新打开版本。',
  proposal_already_decided: '这项建议已经处理，不能覆盖原决定。', proposal_no_longer_applicable: '这项排序建议不再适用，请重新分析。',
};
const sections = [
  {key: 'education', name: '教育经历', fields: [['school', '学校 *'], ['degree', '学位'], ['major', '专业'], ['period', '时间']], list: 'highlights'},
  {key: 'experience', name: '工作与实习', fields: [['organization', '组织名称 *'], ['role', '职位'], ['period', '时间']], list: 'bullets'},
  {key: 'projects', name: '项目经历', fields: [['name', '项目名称 *'], ['role', '角色'], ['period', '时间']], list: 'bullets'},
];

function App() {
  const [token, setToken] = useState(''), [password, setPassword] = useState('');
  const [cap, setCap] = useState({}), [busy, setBusy] = useState(false), [notice, setNotice] = useState(null);
  const [resumes, setResumes] = useState([]), [drafts, setDrafts] = useState([]), [versions, setVersions] = useState([]);
  const [draft, setDraft] = useState(null), [version, setVersion] = useState(null), [document, setDocument] = useState(null);
  const [values, setValues] = useState({}), [extra, setExtra] = useState({}), [title, setTitle] = useState('');
  const [sources, setSources] = useState({}), [activeSource, setActiveSource] = useState(null), [highlight, setHighlight] = useState(null);
  const [paste, setPaste] = useState(''), [file, setFile] = useState(null), [imported, setImported] = useState(null);
  const [mode, setMode] = useState('local_rules'), [consent, setConsent] = useState(false), [reviewed, setReviewed] = useState(false);
  const [sourceManager, setSourceManager] = useState(false), [sourceList, setSourceList] = useState([]);
  const [interviewContext,setInterviewContext]=useState(null);
  const [view,setView]=useState('resumes'),[targetJob,setTargetJob]=useState(null);

  async function api(path, options = {}, auth = token) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 90_000);
    try {
      const response = await fetch('/api/v2' + path, {
        method: options.method ?? 'GET', signal: controller.signal,
        headers: {Authorization: `Bearer ${auth}`, 'Content-Type': options.raw ? 'application/octet-stream' : 'application/json'},
        body: options.body === undefined ? undefined : options.raw ? options.body : JSON.stringify(options.body),
      });
      const data = response.status === 204 ? null : await response.json();
      if (!response.ok) {
        const error = new Error(messages[data?.detail] ?? `操作未完成（${data?.detail ?? response.status}），请检查后重试。`);
        error.code = data?.detail; throw error;
      }
      return data;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('请求超过等待时间。请先刷新草稿或版本列表，确认是否已完成，再决定是否重试。');
      throw error;
    } finally { clearTimeout(timer); }
  }
  async function run(action) {
    setBusy(true); setNotice(null);
    try { await action(); } catch (error) { setNotice({error: true, text: error.message}); }
    finally { setBusy(false); }
  }
  async function refresh(auth = token) {
    const [r, d] = await Promise.all([api('/resumes', {}, auth), api('/drafts', {}, auth)]);
    setResumes(r); setDrafts(d);
  }
  function resetEditor() { setDocument(null); setDraft(null); setVersion(null); setValues({}); setVersions([]); setReviewed(false); setExtra({}); setHighlight(null); setNotice(null); }
  function showDocument(doc) {
    setDocument(doc); setValues(Object.fromEntries(Object.entries(factFields(doc)).map(([k, v]) => [k, v.text])));
    setExtra({}); setReviewed(false); setHighlight(null);
  }
  async function loadSources(doc, fallback) {
    const ids = [...new Set(Object.values(factFields(doc)).map(f => f.source.source_id))];
    if (fallback && !ids.includes(fallback)) ids.unshift(fallback);
    const records = await Promise.all(ids.map(id => api('/sources/' + id)));
    setSources(Object.fromEntries(records.map(s => [s.source_id, s]))); setActiveSource(records[0]?.source_id ?? null);
  }
  async function openDraft(d) {
    setSourceManager(false);
    resetEditor(); setDraft(d); showDocument(d.document); setTitle(d.document.personal.name ? `${d.document.personal.name.text}的简历`.slice(0, 120) : '我的求职简历');
    await loadSources(d.document, d.source_id);
  }
  async function openResume(r, selected) {
    setSourceManager(false);
    const history = await api(`/resumes/${r.resume_id}/versions`);
    const current = selected ?? history[0];
    resetEditor(); setVersions(history); setVersion(current); showDocument(current.document); setTitle(r.title);
    await loadSources(current.document);
  }
  async function parse() {
    // Consent is for this attempt/material, not a persistent opt-in for later uploads.
    const allowExternal = consent;
    setConsent(false);
    let source = imported;
    if (!source) {
      if (file) {
        const uploaded = await api('/imports?filename=' + encodeURIComponent(file.name), {method: 'POST', raw: true, body: file});
        source = await api('/sources/' + uploaded.source_id);
      } else source = await api('/sources', {method: 'POST', body: {kind: 'original_resume', label: '粘贴的简历', text: paste}});
      setImported(source); setSources({[source.source_id]: source}); setActiveSource(source.source_id);
    }
    const d = await api(`/sources/${source.source_id}/parse`, {method: 'POST', body: {mode, allow_external_processing: allowExternal}});
    await openDraft(d); await refresh();
    const summary = extractionSummary(d.document);
    setNotice({text: `已自动填写 ${summary.fields} 项信息，识别到 ${summary.education} 段教育、${summary.experience} 段工作/实习、${summary.projects} 个项目。请核对后保存，遗漏的信息再补充。`});
  }
  async function save() {
    const edits = changedFields(document, values);
    const saved = draft
      ? await api(`/drafts/${draft.draft_id}/accept`, {method: 'POST', body: {
          title, edits, user_reviewed: reviewed, expected_source_hash: draft.source_content_hash}})
      : await api(`/resumes/${version.resume_id}/versions/${version.version_id}/edit`, {method: 'POST', body: {edits}});
    await refresh(); await openResume({resume_id: saved.resume_id, title}, saved);
    setNotice({text: '已保存新版本。新增或修改的文字作为用户补充保留来源；最终确认需要单独操作。'});
  }
  const fields = document ? factFields(document) : {};
  const changes = document ? changedFields(document, values) : [];
  const questions = draft?.questions.filter(q => !values[q.path]?.trim()) ?? [];
  const head = version && versions[0]?.version_id === version.version_id;
  function add(key) { setExtra(prev => ({...prev, [key]: (prev[key] ?? 0) + 1})); }
  function field(path, label, multiline = false) {
    const original = fields[path], value = values[path] ?? '', changed = value !== (original?.text ?? '');
    const Input = multiline ? 'textarea' : 'input';
    return <div className={'field ' + (multiline ? 'wide' : '')} key={path}>
      <label htmlFor={path}>{label}</label>
      <Input id={path} value={value} disabled={busy} rows={multiline ? 2 : undefined}
        onChange={e => {setValues(v => ({...v, [path]: e.target.value})); setReviewed(false);}} />
      {changed && value ? <span className="source-label">将作为用户补充保存</span> : original ?
        <button type="button" className="source-link" disabled={busy} onClick={() => {setActiveSource(original.source.source_id); setHighlight(original.source);}}>查看原文依据 ↗</button> : null}
    </div>;
  }
  const source = sources[activeSource];
  const parts = source && highlight?.source_id === activeSource ? quoteParts(source.text, highlight) : null;

  if (!token) return <main className="login-shell"><section className="login-card">
    <div className="brand-symbol">↗</div><p className="eyebrow">行远 · CAREER WORKSPACE</p><h1>每一步，都有据可循。</h1>
    <p className="muted">从整理真实经历开始，建立属于你的长期求职档案。</p>
    <form onSubmit={e => {e.preventDefault(); run(async () => {
      const config = await api('/capabilities', {}, password); await refresh(password); setCap(config); setToken(password); setPassword('');
    });}}><label htmlFor="access-code">本地工作台访问口令</label><input id="access-code" type="password" autoComplete="off" value={password} onChange={e => setPassword(e.target.value)} />
      <button className="primary" disabled={busy || !password}>{busy ? '连接中…' : '进入工作台 →'}</button></form>
    {notice && <p role="alert" className="error">{notice.text}</p>}
    <p className="small muted">口令仅保留在当前页面内存中。此版本用于本地开发，尚未提供完整账号系统。</p>
  </section><aside className="login-story"><span className="outline-circle">01</span><h2>经历是起点，<br/>成长有记录。</h2><p>导入简历 · 核对事实 · 保存版本</p><div className="story-line"/><small>简历导入 · 岗位档案 · 局部优化 · PDF 导出<br/>个人项目空间与面试练习</small></aside></main>;

  return <div className="shell"><aside className="sidebar">
    <div className="brand"><span className="brand-symbol">↗</span><div>行远<small>求职工作台</small></div></div>
    <p className="nav-caption">我的空间</p><button className={view==='resumes'?'nav-active':'nav-later'} disabled={busy} onClick={() => {setView('resumes');}}>▤ 简历档案</button>
    <button className={view==='jobs'?'nav-active':'nav-later'} disabled={busy} onClick={()=>setView('jobs')}>◎ 岗位与投递</button>
    <button className={view==='projects'?'nav-active':'nav-later'} disabled={busy} onClick={()=>setView('projects')}>⌘ 个人项目空间</button>
    <button className={view==='knowledge'?'nav-active':'nav-later'} disabled={busy} onClick={()=>setView('knowledge')}>◇ 公共知识与练习</button>
    <div className="nav-later">◷ 面试练习 <small>简历内使用</small></div>
    <div className="sidebar-section"><div className="section-label">已保存简历 <span>{resumes.length}</span></div>
      {resumes.map(r => <button className="resume-item" key={r.resume_id} disabled={busy} onClick={() => {setView('resumes');run(() => openResume(r));}}><strong>{r.title}</strong><small>{r.version_count} 个版本</small></button>)}
      {!resumes.length && <p className="small muted">保存第一份简历后，会显示在这里。</p>}
    </div>
    {!!drafts.length && <div className="sidebar-section"><div className="section-label">待核对 <span>{drafts.length}</span></div>{drafts.map(d => <button className="resume-item" key={d.draft_id} disabled={busy} onClick={() => {setView('resumes');run(() => openDraft(d));}}>解析草稿 <small>{new Date(d.created_at).toLocaleDateString()}</small></button>)}</div>}
    <div className="sidebar-bottom"><span className="status-dot"/> 本地开发版本 <button className="text-button" onClick={() => window.location.reload()}>退出</button></div>
  </aside><main className="workspace"><header className="topbar"><span>我的空间 <b>/</b> 简历档案</span><button className="text-button" disabled={busy} onClick={() => run(async () => {setSourceList(await api('/sources')); setSourceManager(!sourceManager);})}>管理来源材料</button><span className="pill">{cap.demo_only ? '合成演示' : '资料由你核对'}</span></header>
    <div className="page-heading"><div><p className="eyebrow">YOUR EXPERIENCE, YOUR STORY</p><h1>让每一份经历，清楚可信。</h1><p className="muted">先整理事实，再表达价值。每次修改都保留自己的来路。</p></div>
      {document && <button className="secondary" disabled={busy} onClick={() => {resetEditor(); setImported(null); setPaste(''); setFile(null); setConsent(false);}}>＋ 导入新简历</button>}
    </div>
    {view==='resumes'&&<ol className="steps"><li className="done"><span>1</span> 导入材料</li><li className={document ? 'done' : ''}><span>2</span> 核对与补充</li><li className={version ? 'done' : ''}><span>3</span> 保存与确认</li></ol>}
    {notice && <div role={notice.error ? 'alert' : 'status'} className={'notice ' + (notice.error ? 'error' : '')}>{notice.text}</div>}
    {busy && <div className="busy" role="status">正在处理，请稍候…</div>}
    {cap.demo_only && <div className="notice">当前为合成演示，模型已关闭。请勿填写真实私人资料；{cap.synthetic_persistent?'演示数据保留供下次继续。':'退出服务后演示数据会清理。'}</div>}
    {view==='jobs'&&<JobsPanel api={api} run={run} busy={busy} version={version} hasUnsavedChanges={changes.length>0} onUseJob={job=>run(async()=>{await api(`/jobs/${job.job_id}/links`,{method:'POST',body:{resume_id:version.resume_id,version_id:version.version_id}});setTargetJob({...job,resume_id:version.resume_id});setView('resumes');})} onOpenVersion={async link=>{const saved=await api(`/resumes/${link.resume_id}/versions/${link.version_id}`);await openResume(resumes.find(r=>r.resume_id===link.resume_id)||{resume_id:link.resume_id,title:'我的简历'},saved);setView('resumes');}}/>}
    {view==='projects'&&<ProjectsPanel api={api} run={run} busy={busy}/>}
    {view==='knowledge'&&<KnowledgePanel api={api} run={run} busy={busy}/>}
    {view==='resumes'&&<>
    {version && <MatchingPanel key={`matching:${version.resume_id}`} targetJob={targetJob?.resume_id===version.resume_id?targetJob:null} onPrepareInterview={setInterviewContext} api={api} run={run} busy={busy} cap={cap} version={version} hasUnsavedChanges={changes.length > 0} onVersionSaved={async saved => {await refresh(); await openResume({resume_id:saved.resume_id,title},saved); setNotice({text:'已按建议保存新版本，事实与来源保持不变，请核对后最终确认。'});}}/>}
    {version && <CollaborationPanel key={`collaboration:${version.resume_id}`} api={api} run={run} busy={busy} cap={cap} version={version} hasUnsavedChanges={changes.length > 0} onVersionSaved={async saved => {await refresh(); await openResume({resume_id:saved.resume_id,title},saved); setNotice({text:'已将完整原句加入摘要并保存新版，请核对后最终确认。'});}}/>}
    {version && <InterviewPanel key={`interview:${version.resume_id}`} api={api} run={run} busy={busy} cap={cap} version={version} context={interviewContext?.resume_id===version.resume_id?interviewContext:null} hasUnsavedChanges={changes.length>0}/>}
    {version && <PDFPanel api={api} run={run} busy={busy} version={version} token={token} hasUnsavedChanges={changes.length>0}/>}
    {version && <RewritePanel api={api} run={run} busy={busy} cap={cap} version={version} hasUnsavedChanges={changes.length>0} onVersionSaved={async saved=>{await refresh();await openResume({resume_id:saved.resume_id,title},saved);setNotice({text:'局部修改已保存为新版用户自述；原文和评审记录保留，请重新确认后导出。'});}}/>}
    {sourceManager && <section className="panel source-manager"><div className="section-heading"><h3>来源材料</h3><button className="text-button" onClick={() => setSourceManager(false)}>收起</button></div><p className="small muted">这里显示最近 200 份材料。引用中的来源需先删除对应草稿或简历；删除未引用来源会同时移除其原始附件。</p>
      {!sourceList.length && <p className="muted">暂无来源材料。</p>}{sourceList.map(s => <div className="source-row" key={s.source_id}><div><strong>{s.label}</strong><small>{s.kind === 'user_statement' ? '用户补充' : '原始材料'} · {s.referenced ? '引用中' : '未引用'}{s.has_original ? ' · 含原始附件' : ''}</small></div>
        <button className="text-button danger" disabled={busy || s.referenced} onClick={() => {
          if (window.confirm('删除这份未引用的来源材料及附件？')) run(async () => {await api('/sources/'+s.source_id,{method:'DELETE'}); setSourceList(await api('/sources')); if (activeSource === s.source_id) {setActiveSource(null); setImported(null);}});
        }}>删除材料</button></div>)}
    </section>}

    {!document ? <div className="import-layout"><section className="panel import-panel"><p className="eyebrow">01 / 导入</p><h2>上传简历，自动填写档案</h2><p className="muted">从 PDF 等文档提取姓名、联系方式、教育与项目经历。你只需核对和补充遗漏，原始材料会单独保留。</p>
      <label className="drop-zone"><span className="upload-symbol">↑</span><strong>{file ? file.name : '选择一份简历文档'}</strong><small>TXT / Markdown / PDF / DOCX · 最大 5 MB</small><input type="file" aria-label="上传简历" accept=".txt,.md,.pdf,.docx" disabled={busy} onChange={e => {setFile(e.target.files[0] ?? null); setImported(null); setConsent(false);}}/></label>
      {file && <button className="text-button" onClick={() => {setFile(null); setImported(null); setConsent(false);}}>改用粘贴文字</button>}
      {!file && <><div className="label-row"><label htmlFor="resume-text">或粘贴简历文字</label><button className="text-button" disabled={busy} onClick={() => {setPaste(example); setImported(null); setConsent(false);}}>填入合成示例</button></div><textarea id="resume-text" className="resume-paste" value={paste} placeholder="姓名：…\n教育经历\n项目经历\n技能" disabled={busy} onChange={e => {setPaste(e.target.value); setImported(null); setConsent(false);}}/></>}
      <div className="parse-options"><label htmlFor="parse-mode">解析方式</label><select id="parse-mode" value={mode} disabled={busy} onChange={e => {setMode(e.target.value); setConsent(false);}}><option value="local_rules">本地规则解析 · 不发送资料</option><option value="llm" disabled={!cap.llm}>在线模型解析{!cap.llm ? ' · 尚未配置' : ''}</option></select>
        <p className="small muted">文字版 PDF 可直接提取，无需先粘贴。支持常见简历标题和分段；复杂多栏、图片与无明确结构的材料可能漏识别。</p>
        {mode === 'llm' && <label className="check"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}/>我同意将本次简历文字发送给已配置的在线模型。</label>}
      </div><button className="primary" disabled={busy || (!file && !paste.trim()) || (mode === 'llm' && !consent)} onClick={() => run(parse)}>自动填写并核对 →</button>
    </section><aside className="import-aside"><p className="eyebrow">一份可以回看的简历</p><h2>写得更好，<br/>也要说得清楚。</h2><div className="principle"><b>01</b><div><strong>原文与字段并排核对</strong><p>解析结果是草稿，遗漏可以补充。</p></div></div><div className="principle"><b>02</b><div><strong>每项事实有来源</strong><p>手动补充单独保存，不改写原始材料。</p></div></div><div className="principle"><b>03</b><div><strong>修改留下版本</strong><p>保存、确认与恢复是独立操作。</p></div></div><p className="small muted">保存后可分析岗位、审批局部修改并导出已确认版本的 PDF。扫描 PDF 暂需先转成文字。</p></aside></div> :
    <div className="editor-layout"><section className="editor"><div className="panel editor-title"><div><p className="eyebrow">02 / 核对与编辑</p><h2>{draft ? '检查解析草稿' : `简历 · 第 ${version.sequence} 版`}</h2><span className="pill">{draft ? (draft.mode === 'local_rules' ? '本地规则草稿' : '在线模型草稿') : version.confirmed_at ? '用户已确认' : '待最终确认'}</span></div>
      {draft && <label>简历名称<input aria-label="简历名称" value={title} disabled={busy} onChange={e => setTitle(e.target.value)}/></label>}
      {draft && <p className="small muted">本次模型调用 {draft.usage.provider_calls} 次 · {draft.usage.latency_ms} ms{draft.usage.input_tokens !== null ? ` · 输入 ${draft.usage.input_tokens} tokens` : ''} · 请核对未识别内容</p>}
      {draft && draft.warnings.map((warning, i) => <p className="small muted" key={i}>{warning}</p>)}
    </div>
    {questions.length > 0 && <div className="questions"><strong>这些信息需要你核对</strong>{questions.map(q => <p key={q.path}>{q.required ? '必填' : '可选'} · {q.question}</p>)}</div>}
    <section className="panel"><div className="section-heading"><h3>个人信息</h3><span>姓名为必填项</span></div><div className="field-grid">{[['name','姓名 *'],['email','邮箱'],['phone','电话'],['location','城市']].map(([k,l]) => field('personal.'+k,l))}</div>
      {Array.from({length: Math.max(document.personal.links?.length ?? 0, 0) + (extra.links ?? 0)}, (_, i) => field(`personal.links.${i}`, '个人链接'))}<button className="text-button" disabled={busy || (document.personal.links?.length ?? 0) + (extra.links ?? 0) >= 10} onClick={() => add('links')}>＋ 添加链接</button>
    </section>
    {sections.map(s => <section className="panel" key={s.key}><div className="section-heading"><h3>{s.name}</h3><button className="text-button" disabled={busy || document[s.key].length + (extra[s.key] ?? 0) >= (s.key === 'education' ? 10 : s.key === 'experience' ? 20 : 30)} onClick={() => add(s.key)}>＋ 添加</button></div>
      {Array.from({length: document[s.key].length + (extra[s.key] ?? 0)}, (_, i) => <div className="entry" key={i}><p className="entry-number">{String(i + 1).padStart(2,'0')}</p><div className="field-grid">{s.fields.map(([k,l]) => field(`${s.key}.${i}.${k}`,l))}</div>
        {Array.from({length: (document[s.key][i]?.[s.list]?.length ?? 0) + (extra[`${s.key}.${i}`] ?? 0)}, (_, j) => field(`${s.key}.${i}.${s.list}.${j}`, s.key === 'education' ? '补充说明' : '经历描述', true))}
        <button className="text-button" disabled={busy || (document[s.key][i]?.[s.list]?.length ?? 0) + (extra[`${s.key}.${i}`] ?? 0) >= (s.key === 'education' ? 20 : 30)} onClick={() => add(`${s.key}.${i}`)}>＋ 添加一条描述</button>
      </div>)}{!document[s.key].length && !extra[s.key] && <p className="small muted">尚未识别到此类经历，可按实际情况补充。</p>}
    </section>)}
    {['skills','summary'].map(key => <section className="panel" key={key}><div className="section-heading"><h3>{key === 'skills' ? '技能' : '个人简介'}</h3><button className="text-button" disabled={busy || document[key].length + (extra[key] ?? 0) >= (key === 'skills' ? 60 : 10)} onClick={() => add(key)}>＋ 添加</button></div>
      {Array.from({length: document[key].length + (extra[key] ?? 0)}, (_, i) => field(`${key}.${i}`, key === 'skills' ? `技能 ${i + 1}` : '简介', key === 'summary'))}
    </section>)}
    <div className="save-bar"><label className="check"><input type="checkbox" checked={reviewed} disabled={busy || (version && !head)} onChange={e => setReviewed(e.target.checked)}/>我已核对字段，补充内容是我的真实自述。</label>
      <button className="primary" disabled={busy || !reviewed || !title.trim() || (version && (!head || !changes.length))} onClick={() => run(save)}>{draft ? '核对并保存简历' : '保存为新版本'}</button>
      {version && head && !version.confirmed_at && <button className="secondary" disabled={busy || changes.length > 0} onClick={() => run(async () => {
        const confirmed = await api(`/resumes/${version.resume_id}/versions/${version.version_id}/confirm`, {method: 'POST', body: {expected_content_hash: version.content_hash}});
        await openResume({resume_id: version.resume_id, title}, confirmed); await refresh(); setNotice({text: '已确认当前版本。这代表你的自述确认，不等于第三方证明。'});
      })}>确认当前版本</button>}
    </div></section><aside className="reference-pane"><section className="panel source-panel"><div className="section-heading"><h3>来源原文</h3><span>只读保留</span></div>
      <select aria-label="选择来源" value={activeSource ?? ''} onChange={e => {setActiveSource(e.target.value); setHighlight(null);}}>{Object.values(sources).map(s => <option value={s.source_id} key={s.source_id}>{s.kind === 'user_statement' ? '用户补充' : s.label}</option>)}</select>
      <pre>{source ? parts ? <>{parts[0]}<mark>{parts[1]}</mark>{parts[2]}</> : source.text : '选择一个字段查看原文。'}</pre><p className="small muted">引用可验证文字来源；不能独立证明经历真实性。</p>
    </section>
    {!!versions.length && <section className="panel"><div className="section-heading"><h3>版本记录</h3><span>{versions.length} 个版本</span></div>{versions.map((v,i) => <div className="history" key={v.version_id}><button className={v.version_id === version?.version_id ? 'history-selected' : ''} disabled={busy} onClick={() => run(() => openResume({resume_id:v.resume_id,title}, v))}><strong>第 {v.sequence} 版 {i === 0 ? '· 最新' : ''}</strong><small>{v.confirmed_at ? '用户已确认' : '待确认'} · {new Date(v.created_at).toLocaleString()}</small></button>
      {i > 0 && <button className="text-button" disabled={busy} onClick={() => run(async () => {
        const restored = await api(`/resumes/${v.resume_id}/versions/${v.version_id}/restore`, {method:'POST',body:{expected_parent_version_id:versions[0].version_id,note:'通过工作台恢复'}});
        await refresh(); await openResume({resume_id:v.resume_id,title}, restored); setNotice({text:'已恢复为新版本，请重新核对并确认。'});
      })}>恢复为新版本</button>}</div>)}</section>}
    <section className="panel small muted"><strong>你始终保留决定权</strong><p>清空字段会从新版中移除，旧版与原文仍保留。</p>
      {draft ? <button className="text-button danger" disabled={busy} onClick={() => run(async () => {await api('/drafts/'+draft.draft_id,{method:'DELETE'}); resetEditor(); await refresh();})}>删除此草稿</button> : <button className="text-button danger" disabled={busy} onClick={() => {
        if (window.confirm('删除此简历及所有版本？来源材料仍将保留。')) run(async () => {await api('/resumes/'+version.resume_id,{method:'DELETE'}); resetEditor(); await refresh();});
      }}>删除简历及版本</button>}
    </section></aside></div>}
    </>}
    <footer>行远 · 求职工作台 <span>经历 → 岗位 → 准备 → 成长</span></footer>
  </main></div>;
}

createRoot(document.getElementById('root')).render(<App/>);
