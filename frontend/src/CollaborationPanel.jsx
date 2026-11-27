import React, {useEffect, useRef, useState} from 'react';
import {quoteParts} from './model.js';
import {collaborationStatus, canAcceptCollaboration, relevanceLabel} from './collaboration.js';

const roles = {writer:'摘要整理者',reviewer:'评审者',supervisor:'流程协调器',user:'你'};
const kinds = {review_request:'提交原句送审',review_feedback:'返回评审反馈',revision_request:'要求调整选择',user_approval:'转交你审批',blocked:'停止并请求补充'};

export function CollaborationPanel({api, run, busy, version, cap, hasUnsavedChanges, onVersionSaved}) {
  const [expanded,setExpanded]=useState(false), [jd,setJD]=useState(''), [mode,setMode]=useState('local_demo');
  const [consent,setConsent]=useState(false), [reviewed,setReviewed]=useState(false), [history,setHistory]=useState([]);
  const [view,setView]=useState(null), [preview,setPreview]=useState(null), [error,setError]=useState('');
  const ref=useRef(null), resumeId=version.resume_id;
  useEffect(()=>{
    let active=true;
    api(`/resumes/${resumeId}/collaborations`).then(h=>{if(active){setHistory(h);setError('');}}).catch(e=>{if(active)setError(e.message);});
    return ()=>{active=false;};
  },[resumeId,version.version_id]);
  useEffect(()=>{setConsent(false);setReviewed(false);setPreview(null);},[version.version_id]);
  async function start(){
    const allow=consent;setConsent(false);setReviewed(false);setPreview(null);
    const data={version_id:version.version_id,expected_content_hash:version.content_hash,jd_text:jd,mode};
    const fingerprint=JSON.stringify(data);
    if(ref.current?.fingerprint!==fingerprint)ref.current={fingerprint,key:crypto.randomUUID()};
    const result=await api(`/resumes/${resumeId}/collaborations`,{method:'POST',body:{...data,request_key:ref.current.key,allow_external_processing:allow}});
    setView(result);setHistory(await api(`/resumes/${resumeId}/collaborations`));
  }
  async function decide(p,action){
    const d=view.state.drafts.at(-1);
    const result=await api(`/collaborations/${view.state.run_id}/proposals/${p.proposal_id}/decision`,{method:'POST',body:{action,
      expected_parent_version_id:view.expected_head_version_id,draft_revision:d.revision,draft_hash:d.draft_hash,user_reviewed:true}});
    setView(result.collaboration);setReviewed(false);
    if(result.version)await onVersionSaved(result.version);
  }
  const last=view?.state.drafts.at(-1), applicable=canAcceptCollaboration(view,version,hasUnsavedChanges);
  return <section className="panel collaboration-panel">
    <div className="section-heading"><div><p className="eyebrow">协作整理 · 保留事实</p><h2>从已有经历中，选出适合岗位的摘要</h2></div>
      <button className="secondary" disabled={busy} onClick={()=>setExpanded(!expanded)}>{expanded?'收起协作摘要':'协作整理摘要 →'}</button></div>
    <p className="small muted">整理者选取完整原句，评审者可要求改选，最多修订两轮。来源对上、岗位相关、事实真实和用户接受是不同判断，由你决定是否加入摘要。</p>
    {expanded && <>
      <div className="match-inputs"><div><div className="label-row"><label htmlFor="collab-jd">摘要面向的岗位要求</label><button className="text-button" disabled={busy} onClick={()=>{setJD('使用 Python 开发接口，具备 RAG 检索项目实践。');setConsent(false);}}>填入合成要求</button></div>
        <textarea id="collab-jd" rows={5} maxLength={12000} value={jd} disabled={busy} onChange={e=>{setJD(e.target.value);setConsent(false);}}/></div>
        <div><label htmlFor="collab-mode">协作方式</label><select id="collab-mode" value={mode} disabled={busy} onChange={e=>{setMode(e.target.value);setConsent(false);}}>
          <option value="local_demo">本地规则演示 · 无模型调用</option><option value="llm" disabled={!cap.llm}>在线双角色送审{!cap.llm?' · 尚未配置':''}</option></select>
          <p className="small muted">本地只比较已知岗位术语；在线由两个角色分别选择和评审。仅支持完整原句摘录，不自由润色，也不证明经历真实。</p>
          {mode==='llm' && <label className="check"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>同意将本次 JD、当前版本的项目/工作经历正文和已有摘要发送给已配置模型。请先检查正文中的私人信息。</label>}
          <button className="primary" disabled={busy||!jd.trim()||hasUnsavedChanges||(mode==='llm'&&!consent)} onClick={()=>run(start)}>生成并送审摘要摘录</button>
          {hasUnsavedChanges && <p className="small error">请先保存字段修改。</p>}
          <p className="small muted">最多 3 次生成与 3 次评审，无工具权限，不自动重试模型。超时后先刷新历史；同一请求不会重新计费调用。</p>
        </div></div>
      <details className="match-history"><summary>协作记录 · {history.length}</summary>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="text-button" disabled={busy} onClick={()=>run(async()=>{setHistory(await api(`/resumes/${resumeId}/collaborations`));setError('');})}>刷新协作记录</button>
        {history.map(h=><div className="source-row" key={h.run_id}><div><strong>{new Date(h.created_at).toLocaleString()}</strong><small>{collaborationStatus({status:h.status})}</small></div>
          <button className="text-button" disabled={busy} onClick={()=>run(async()=>{setView(await api(`/collaborations/${h.run_id}`));setReviewed(false);setConsent(false);setPreview(null);})}>查看协作记录</button></div>)}
      </details>
      {view && <div className="match-results"><div className="section-heading"><h3>{last?.draft.proposals.length>0 && last.draft.proposals.every(p=>view.decisions[p.proposal_id])?'本次摘录已处理':collaborationStatus(view.state)}</h3><span className="pill">{view.state.mode==='local_demo'?'规则角色 · 非模型质量评测':'在线模型角色'}</span></div>
        <p className="small muted">原版本 {view.state.version_id.slice(0,16)}… · 当前第 {view.state.revision} 稿 · 模型请求预留 {view.state.usage.provider_calls} 次 · 已保存检查点 {view.checkpoint_revision}</p>
        <p className="small muted">{view.state.provider} / {view.state.model} · 累计执行 {view.state.usage.active_ms} ms · 费用{view.state.usage.cost==null?'未提供':view.state.usage.cost}。摘录仍是 C1 自述，需结合原经历上下文核对。</p>
        <details><summary>本次岗位要求快照</summary><pre className="match-quote">{view.state.jd_text}</pre></details>
        <details><summary>历次送审原句与反馈</summary>{view.state.drafts.map(d=><section className="match-row" key={d.revision}><h3>第 {d.revision} 稿</h3>{d.draft.proposals.map(p=><p key={p.proposal_id}>{p.text}<small className="muted"> · {p.source_path}</small></p>)}{d.feedback?.items.map((i,n)=><p className="small muted" key={n}>{i.constraint}</p>)}</section>)}</details>
        <ol className="collaboration-trace">{view.state.messages.map(m=><li key={m.message_id}><strong>{roles[m.sender]} → {roles[m.receiver]}</strong><span className="small muted">第 {m.draft_revision} 稿 · {kinds[m.kind]}</span>
          {m.payload.items?.map((i,n)=><p className="small" key={n}>{i.outcome==='accept'?(view.state.mode==='local_demo'?'关键词线索':'模型建议保留'):i.outcome==='needs_input'?'需要补充':'需调整'}：{i.constraint}</p>)}</li>)}</ol>
        {view.state.error_code && <p className="small error">执行已停止（{view.state.error_code}）。原简历未改变。同一请求只返回此记录；需要重新尝试时，请明确新建一次送审。</p>}
        {view.resumable && <button className="secondary" disabled={busy||(view.state.mode==='llm'&&!consent)} onClick={()=>run(async()=>{const allow=consent;setConsent(false);setView(await api(`/collaborations/${view.state.run_id}/resume`,{method:'POST',body:{allow_external_processing:allow}}));})}>从已保存步骤继续</button>}
        {view.state.mode==='llm' && view.resumable && <label className="check"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>同意继续本次在线送审的剩余调用。</label>}
        {['failed','needs_input'].includes(view.state.status) && <button className="text-button" disabled={busy} onClick={()=>{ref.current=null;setView(null);setConsent(false);setReviewed(false);}}>新建一次送审（不会自动执行）</button>}
        {last && <section><h3>第 {last.revision} 稿 · 原文摘录</h3>
          {last.draft.proposals.length===0 && <p>没有找到适合继续送审的原句。可以补充真实材料后重试。</p>}
          {last.draft.proposals.map(p=><article className="match-row" key={p.proposal_id}><p>{p.text}</p><p className="small muted">{p.reason} · 来源字段 {p.source_path}</p>
            {(view.verification??[]).filter(c=>c.proposal_id===p.proposal_id).map(c=><div className="verification-checks" key={c.proposal_id}>
              <p>来源与原句：{c.provenance==='matched'?'已逐字对应所选版本原文':'未通过对应检查'}</p>
              <p>岗位相关性：{relevanceLabel(c.relevance)}</p>
              <p>事实真实性：未独立核实 · C1 自述</p>
              <p>用户决定：{({pending:'待你决定',accepted:'已接受',rejected:'已拒绝'})[c.user_decision]} · 简历版本：{({not_saved:'尚未保存',unconfirmed:'已保存，待最终确认',confirmed:'用户已确认，仍为自述'})[c.resume_confirmation]}</p>
            </div>)}
            <button className="text-button" disabled={busy||!view.source_facts[p.source_path]} onClick={()=>run(async()=>{const span=view.source_facts[p.source_path].source;const s=await api(`/sources/${span.source_id}`);setPreview({label:s.label,parts:quoteParts(s.text,span)});})}>核对摘录原文 ↗</button>
            {view.state.status==='awaiting_approval' && (view.decisions[p.proposal_id]?<span className="pill">{view.decisions[p.proposal_id]==='accepted'?'已加入摘要 · 新版待最终确认':'已拒绝'}</span>:
              <div className="match-actions"><button className="secondary" disabled={busy||!applicable||!reviewed} onClick={()=>run(()=>decide(p,'accept'))}>接受摘录并保存新版</button><button className="text-button" disabled={busy||!reviewed} onClick={()=>run(()=>decide(p,'reject'))}>拒绝摘录</button></div>)}</article>)}
          {view.state.status==='awaiting_approval' && <><label className="check"><input type="checkbox" checked={reviewed} disabled={busy} onChange={e=>setReviewed(e.target.checked)}/>我已核对原句、否定与范围限定，以及原经历上下文；确认后加入摘要，不升级证据。</label>
            {!applicable && <p className="small error">请先查看最新版本并保存修改；其他编辑会使旧建议失效。</p>}</>}
        </section>}
        {preview && <section className="match-source"><h3>摘录来源 · {preview.label}</h3><pre className="match-quote">{preview.parts[0]}<mark>{preview.parts[1]}</mark>{preview.parts[2]}</pre></section>}
      </div>}
    </>}
  </section>;
}
