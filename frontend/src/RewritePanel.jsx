import React, {useEffect, useRef, useState} from 'react';

export function RewritePanel({api,run,busy,version,cap,hasUnsavedChanges,onVersionSaved}) {
  const paths=[];
  for (const section of ['projects','experience']) version.document[section].forEach((entry,i)=>entry.bullets.forEach((fact,j)=>paths.push({path:`${section}.${i}.bullets.${j}`,text:fact.text})));
  const [path,setPath]=useState(''),[jd,setJD]=useState(''),[mode,setMode]=useState('local_demo');
  const [consent,setConsent]=useState(false),[reviewed,setReviewed]=useState(false),[result,setResult]=useState(null),[history,setHistory]=useState([]),[error,setError]=useState('');
  const request=useRef(null);
  useEffect(()=>{let active=true;api(`/resumes/${version.resume_id}/rewrites`).then(rows=>{if(active){setHistory(rows);setError('');}}).catch(e=>{if(active)setError(e.message);});return()=>{active=false;};},[version.resume_id,version.version_id]);
  const final=result?.drafts?.at(-1);
  async function generate() {
    const body={version_id:version.version_id,expected_content_hash:version.content_hash,source_path:path||paths[0]?.path,jd_text:jd,mode};
    const fingerprint=JSON.stringify(body);
    if(request.current?.fingerprint!==fingerprint)request.current={fingerprint,key:crypto.randomUUID()};
    const allowed=consent;setConsent(false);setReviewed(false);
    setResult(await api(`/resumes/${version.resume_id}/rewrites`,{method:'POST',body:{...body,request_key:request.current.key,allow_external_processing:allowed}}));
    setHistory(await api(`/resumes/${version.resume_id}/rewrites`));
  }
  async function decide(action) {
    const response=await api(`/rewrites/${result.run_id}/decision`,{method:'POST',body:{action,expected_parent_version_id:version.version_id,expected_draft_hash:final.draft_hash,user_reviewed:true}});
    setResult(response.rewrite);setReviewed(false);
    if(response.version)await onVersionSaved(response.version);
    setHistory(await api(`/resumes/${version.resume_id}/rewrites`));
  }
  return <section className="panel"><details><summary><strong>局部措辞优化 · 独立送审与人工接受</strong></summary>
    <p className="small muted">选择一条项目或实习描述，保留原文与新表述的关联。来源核验和模型建议都不等于第三方事实证明。</p>
    <label>需要优化的经历<select aria-label="需要优化的经历" value={path||paths[0]?.path||''} onChange={e=>{setPath(e.target.value);setResult(null);setReviewed(false);}}>{paths.map(item=><option key={item.path} value={item.path}>{item.text.slice(0,70)}</option>)}</select></label>
    {!paths.length&&<p className="muted">先添加项目或实习描述，再进行局部优化。</p>}
    <label>本次目标岗位<textarea aria-label="改写目标岗位" rows={3} maxLength={12000} value={jd} onChange={e=>{setJD(e.target.value);setConsent(false);}} placeholder="填写岗位重点，例如 Python、FastAPI 接口开发。"/></label>
    <label>优化方式<select value={mode} onChange={e=>{setMode(e.target.value);setConsent(false);}}><option value="local_demo">本地受限措辞转换</option><option value="llm" disabled={!cap.llm}>在线 Writer / Reviewer</option></select></label>
    <p className="small muted">本地仅做少量可解释的措辞转换，不模拟模型质量；在线最多三稿、六次调用，退回仍不支持时停止。</p>
    {mode==='llm'&&<label className="check"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>同意发送所选经历、所属项目上下文和本次岗位要求给配置的模型。</label>}
    <button className="secondary" disabled={busy||!paths.length||!jd.trim()||hasUnsavedChanges||(mode==='llm'&&!consent)} onClick={()=>run(generate)}>生成局部修改并送审</button>
    {error&&<p role="alert" className="error">{error}</p>}
    {!!history.length&&<details><summary>局部修改历史 · {history.length}</summary>{history.map(row=><button className="text-button" key={row.run_id} disabled={busy} onClick={()=>{setResult(row);setReviewed(false);}}>{row.mode==='local_demo'?'本地':'在线'} · {row.status} · {row.run_id.slice(-8)}</button>)}</details>}
    {result&&<div className="notice"><strong>处理状态：{result.status}</strong><p className="small">原始证据：C1 用户自述 · 独立核实：未完成 · 已用模型调用：{result.usage.provider_calls} / 6</p>
      <p><b>原文：</b>{result.source_fact.text}</p>{final&&<><p><b>提案：</b>{final.draft.text}</p><p><b>审查意见：</b>{final.review?.constraint??'尚未完成，不能应用。'}</p></>}
      <details><summary>协作轨迹 · {result.messages.length}</summary>{result.messages.map((m,i)=><p className="small" key={i}>{m.sender} → {m.receiver} · {m.type} · 第{m.revision}稿 · {m.code}</p>)}</details>
      {result.status==='awaiting_approval'&&<><label className="check"><input type="checkbox" checked={reviewed} onChange={e=>setReviewed(e.target.checked)}/>我已逐项核对，新表述忠于我的实际经历。</label><div className="button-row">
        <button className="primary" disabled={busy||!reviewed||hasUnsavedChanges||result.version_id!==version.version_id} onClick={()=>run(()=>decide('accept'))}>接受为新版自述</button>
        <button className="secondary" disabled={busy||!reviewed} onClick={()=>run(()=>decide('reject'))}>拒绝此修改</button></div></>}
      {['running','unknown'].includes(result.status)&&<p className="error small">执行结果尚不确定，不会自动重复调用模型。请保留原文并检查服务状态。</p>}
    </div>}
  </details></section>;
}
