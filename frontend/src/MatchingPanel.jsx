import React, {useEffect, useRef, useState} from 'react';
import {quoteParts} from './model.js';
import {matchLabel} from './matching.js';

const sampleJD = `岗位要求
1. 使用 Python 和 FastAPI 开发接口。
2. 具备 RAG 检索项目实践。
3. 掌握 Kubernetes 生产部署。
4. 有 PostgreSQL 实践者优先。`;

export function MatchingPanel({api, run, busy, version, cap, hasUnsavedChanges, onVersionSaved, onPrepareInterview, targetJob}) {
  const [title, setTitle] = useState('AI Agent 开发实习'), [jd, setJD] = useState('');
  const [mode, setMode] = useState('local_check'), [consent, setConsent] = useState(false);
  const [history, setHistory] = useState([]), [match, setMatch] = useState(null);
  const [reviewed, setReviewed] = useState(false), [preview, setPreview] = useState(null);
  const [expanded, setExpanded] = useState(false), [historyError, setHistoryError] = useState('');
  const requestRef = useRef(null);
  const resumeId = version.resume_id;
  useEffect(()=>{if(targetJob){setTitle(targetJob.title);setJD(targetJob.jd_text);setExpanded(true);setConsent(false);setMatch(null);}},[targetJob]);
  useEffect(() => {
    let active = true;
    api(`/resumes/${resumeId}/matches`).then(v => {if (active) {setHistory(v); setHistoryError('');}})
      .catch(e => {if (active) setHistoryError(e.message);});
    return () => {active = false;};
  }, [resumeId, version.version_id]);
  useEffect(() => {setMatch(null); setPreview(null); setConsent(false); setReviewed(false); requestRef.current = null;}, [resumeId]);
  async function analyze() {
    const allow = consent; setConsent(false); setPreview(null); setReviewed(false);
    const content = {version_id: version.version_id, expected_content_hash: version.content_hash, title, jd_text: jd, mode};
    const fingerprint = JSON.stringify(content);
    if (requestRef.current?.fingerprint !== fingerprint) requestRef.current = {fingerprint, key: crypto.randomUUID()};
    try {
      setMatch(await api(`/resumes/${resumeId}/matches`, {method: 'POST', body: {...content, request_key: requestRef.current.key, allow_external_processing: allow}}));
      setHistory(await api(`/resumes/${resumeId}/matches`));
    } catch (e) {
      if (['match_model_request_failed','match_analysis_failed','match_previous_failed','match_model_budget_exceeded','jd_has_no_requirements','match_input_too_large'].includes(e.code)) requestRef.current = null;
      setHistory(await api(`/resumes/${resumeId}/matches`));
      throw e;
    }
  }
  async function openMatch(id) {setMatch(await api(`/matches/${id}`)); setPreview(null); setReviewed(false); setExpanded(true);}
  async function decide(proposal, action) {
    const result = await api(`/matches/${match.match_id}/proposals/${proposal.proposal_id}/decision`, {method:'POST', body:{
      action, expected_parent_version_id: match.expected_head_version_id, user_reviewed:true,
    }});
    setMatch(result.match); setReviewed(false);
    if (result.version) await onVersionSaved(result.version);
  }
  async function showQuote(link) {
    const source = await api(`/sources/${link.fact.source.source_id}`);
    setPreview({label:source.label, parts:quoteParts(source.text, link.fact.source)});
  }
  const applicable = match?.can_apply && match.expected_head_version_id === version.version_id && !hasUnsavedChanges;
  return <section className="panel matching-panel">
    <div className="section-heading"><div><p className="eyebrow">岗位匹配 · 有据可查</p><h2>这份经历，如何对应目标岗位？</h2></div>
      <button className="secondary" disabled={busy} onClick={() => setExpanded(v => !v)}>{expanded ? '收起岗位分析' : '分析目标岗位 →'}</button></div>
    <p className="small muted">以当前查看的第 {version.sequence} 版为输入，保存 JD 和分析快照。缺少材料不代表你没有相关能力。</p>
    {expanded && <>
      <div className="match-inputs"><div><label htmlFor="job-title">岗位名称</label><input id="job-title" value={title} maxLength={120} disabled={busy} onChange={e => {setTitle(e.target.value); setConsent(false);}}/>
        <div className="label-row"><label htmlFor="target-jd">目标岗位 JD</label><button className="text-button" disabled={busy} onClick={() => {setJD(sampleJD); setConsent(false);}}>填入合成岗位</button></div>
        <textarea id="target-jd" rows={7} maxLength={15000} value={jd} disabled={busy} placeholder="粘贴岗位要求和职责，每条单独一行便于核对。" onChange={e => {setJD(e.target.value); setConsent(false);}}/>
        <label className="small">或导入岗位文件（PDF / DOCX / TXT）<input type="file" aria-label="导入岗位文件" accept=".pdf,.docx,.txt,.md" disabled={busy} onChange={e=>{
          const file=e.target.files?.[0]; if (!file) return;
          run(async()=>{const result=await api('/jd/extract?filename='+encodeURIComponent(file.name),{method:'POST',raw:true,body:file});setJD(result.text);setConsent(false);});
          e.target.value='';
        }}/></label>
      </div><div className="match-options"><label htmlFor="match-mode">分析方式</label><select id="match-mode" disabled={busy} value={mode} onChange={e => {setMode(e.target.value); setConsent(false);}}>
        <option value="local_check">本地条目与关键词预检查</option><option value="llm" disabled={!cap.llm}>在线语义分析{!cap.llm ? ' · 尚未配置' : ''}</option></select>
        <p className="small muted">本地模式帮助定位原文线索，不判断语义支持；在线模式复用证据分析与来源校验。两种模式均不将简历自述升级为独立证明。</p>
        {mode === 'llm' && <label className="check"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}/>同意将本次 JD 和所选版本的经历字段发送给已配置模型。不发送个人信息栏目；请先检查经历正文是否含私人信息。</label>}
        {hasUnsavedChanges && <p className="error small">当前有未保存的字段修改，请先保存再分析。</p>}
        <button className="primary" disabled={busy || !jd.trim() || !title.trim() || hasUnsavedChanges || (mode === 'llm' && !consent)} onClick={() => run(analyze)}>生成分析快照</button>
        <p className="small muted">在线最多 4 次调用；传输失败停止。超时后先查看历史状态，同一输入重试保留请求标识。</p>
      </div></div>
      <details className="match-history"><summary>岗位分析历史 · {history.length}</summary>
        {historyError && <p role="alert" className="error">{historyError}</p>}
        <button className="text-button" disabled={busy} onClick={() => run(async () => {setHistory(await api(`/resumes/${resumeId}/matches`)); setHistoryError('');})}>刷新分析状态</button>
        {history.map(item => <div className="source-row" key={item.match_id}><div><strong>{item.title}</strong><small>{new Date(item.created_at).toLocaleString()} · {item.status === 'complete' ? '已保存' : item.status === 'failed' ? '分析失败，可重新发起' : '等待结果，服务中断后需人工检查'}</small></div>
          <button className="text-button" disabled={busy || item.status !== 'complete'} onClick={() => run(() => openMatch(item.match_id))}>查看快照</button></div>)}
      </details>
      {match && <div className="match-results">
        <div className="section-heading"><h3>{match.title}</h3><span className="pill">{match.mode === 'local_check' ? '本地预检查 · 非语义结论' : '在线语义参考'}</span></div>
        {onPrepareInterview && <button className="secondary" disabled={busy || hasUnsavedChanges} onClick={()=>onPrepareInterview({resume_id:resumeId,match_id:match.match_id,jd_text:match.jd_text})}>沿用此岗位，准备面试 →</button>}
        <p className="small muted">绑定版本 {match.version_id.slice(0, 14)}… · 模型调用 {match.usage.provider_calls} 次 · {match.usage.latency_ms} ms · {match.provider} / {match.model}</p>
        {match.warnings.map((w, i) => <p className="small muted" key={i}>{w}</p>)}
        <details><summary>本次 JD 原文快照</summary><pre className="match-quote">{match.jd_text}</pre></details>
        {match.rows.map((row, i) => <article className="match-row" key={row.atom_id}>
          <div className="section-heading"><h3>{i + 1}. {row.text}</h3><span className={'match-badge ' + (row.has_contradiction ? 'review' : '')}>{matchLabel(row, match.mode)}</span></div>
          <p className="small muted">JD 引用：“{row.jd_quote}”</p><p className="small">{row.rationale}</p>
          {row.links.map((link, n) => <div className="match-evidence" key={n}><p>{link.quote}</p><span className="small muted">C1 自述 · {link.path} · {match.mode === 'local_check' ? '词面线索，含义待核对' : ({supported:'完整语义支持（仍需核对）',partial:'部分语义支持',contradictory:'存在冲突或范围限制',unsupported:'引用未支持该要求'})[link.support_status]}</span>
            <button className="text-button" disabled={busy} onClick={() => run(() => showQuote(link))}>查看来源原文 ↗</button></div>)}
        </article>)}
        {preview && <section className="match-source"><h3>来源原文 · {preview.label}</h3><pre className="match-quote">{preview.parts[0]}<mark>{preview.parts[1]}</mark>{preview.parts[2]}</pre></section>}
        <section className="match-proposals"><h3>调整已有内容的展示顺序</h3><p className="small muted">保留所有事实和来源，逐条接受后生成新版本。暂不自动补写自由文本。</p>
          {!applicable && match.proposals.some(p => p.decision === 'pending') && <p className="small error">当前查看版本或最新版本已变化，或有未保存修改。请查看最新版本后再接受；其他人工编辑会使旧建议失效。</p>}
          {match.proposals.length === 0 && <p className="small muted">没有生成需要置顶的条目。可根据分析补充真实材料后再比较。</p>}
          {match.proposals.length > 0 && <label className="check"><input type="checkbox" checked={reviewed} disabled={busy} onChange={e => setReviewed(e.target.checked)}/>我已核对建议，仅调整已有内容顺序。</label>}
          {match.proposals.map(p => <div className="match-row" key={p.proposal_id}><strong>{p.title}</strong><p className="small muted">{p.reason}</p>
            {p.decision === 'pending' ? <div className="match-actions"><button className="secondary" disabled={busy || !applicable || !reviewed} onClick={() => run(() => decide(p,'accept'))}>接受并保存新版</button><button className="text-button" disabled={busy} onClick={() => run(() => decide(p,'reject'))}>拒绝此建议</button></div> : <span className="pill">{p.decision === 'accepted' ? '已接受 · 新版仍需最终确认' : '已拒绝'}</span>}
          </div>)}
        </section>
      </div>}
    </>}
  </section>;
}
