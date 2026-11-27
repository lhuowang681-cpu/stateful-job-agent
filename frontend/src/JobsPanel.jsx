import React,{useEffect,useRef,useState} from 'react';

const stages={saved:'已收藏',applied:'已投递',screening:'筛选中',interview:'面试中',offer:'已获Offer',rejected:'未通过',withdrawn:'已撤回'};

export function JobsPanel({api,run,busy,version,hasUnsavedChanges,onUseJob,onOpenVersion}) {
  const [jobs,setJobs]=useState([]),[active,setActive]=useState(null),[error,setError]=useState('');
  const [company,setCompany]=useState(''),[title,setTitle]=useState(''),[jd,setJD]=useState(''),[notes,setNotes]=useState('');
  const [stage,setStage]=useState('applied'),[note,setNote]=useState(''),[sessions,setSessions]=useState([]),[sid,setSID]=useState('');
  const createRef=useRef(null),updateRef=useRef(null);
  async function refresh(){setJobs(await api('/jobs'));setError('');}
  useEffect(()=>{let live=true;api('/jobs').then(v=>{if(live)setJobs(v);}).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[]);
  useEffect(()=>{let live=true;setSessions([]);setSID('');if(version)api(`/resumes/${version.resume_id}/interviews`).then(v=>{if(live)setSessions(v);}).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[version?.resume_id,version?.version_id]);
  async function create(){
    const body={company,title,jd_text:jd,notes},fp=JSON.stringify(body);
    if(createRef.current?.fp!==fp)createRef.current={fp,key:crypto.randomUUID()};
    setActive(await api('/jobs',{method:'POST',body:{...body,request_key:createRef.current.key}}));await refresh();
  }
  async function update(){
    const body={expected_revision:active.revision,stage,note},fp=JSON.stringify({...body,job_id:active.job_id});
    if(updateRef.current?.fp!==fp)updateRef.current={fp,key:crypto.randomUUID()};
    setActive(await api(`/jobs/${active.job_id}/events`,{method:'POST',body:{...body,request_key:updateRef.current.key}}));setNote('');await refresh();
  }
  return <div className="longterm-grid"><section className="panel"><p className="eyebrow">长期求职档案</p><h2>每个机会，都留下进展。</h2>
    <p className="muted">手动记录岗位与投递阶段，关联本次使用的简历版本和面试，不自动向招聘网站投递。</p>
    <label>公司<input aria-label="岗位公司" value={company} maxLength={120} onChange={e=>setCompany(e.target.value)}/></label>
    <label>岗位名称<input aria-label="保存岗位名称" value={title} maxLength={120} onChange={e=>setTitle(e.target.value)}/></label>
    <label>岗位要求<textarea aria-label="保存岗位JD" rows={6} maxLength={12000} value={jd} onChange={e=>setJD(e.target.value)}/></label>
    <label>备注<textarea rows={2} maxLength={5000} value={notes} onChange={e=>setNotes(e.target.value)}/></label>
    <div className="button-row"><button className="primary" disabled={busy||!company.trim()||!title.trim()||!jd.trim()} onClick={()=>run(create)}>保存岗位卡片</button>
      <button className="text-button" disabled={busy} onClick={()=>{setCompany('合成科技');setTitle('AI Agent 开发实习');setJD('使用 Python 和 FastAPI 开发接口，理解 Agent Checkpoint、幂等性和代码检索。');setNotes('仅用于演示，不是真实招聘岗位。');}}>填入合成岗位卡片</button></div>
    <h3>我的岗位 · {jobs.length}</h3>{error&&<p role="alert" className="error">{error}</p>}
    {jobs.map(j=><button className={'job-card '+(active?.job_id===j.job_id?'selected':'')} key={j.job_id} disabled={busy} onClick={()=>run(async()=>setActive(await api(`/jobs/${j.job_id}`)))}><strong>{j.company} · {j.title}</strong><small>{stages[j.stage]} · {j.links.length}条版本/面试关联</small></button>)}
  </section><section className="panel">{!active?<><h2>选择一张岗位卡片</h2><p className="muted">查看JD、更新进展、回看当时使用的简历，下一轮继续准备。</p></>:<>
    <p className="eyebrow">{stages[active.stage]}</p><h2>{active.title}</h2><p>{active.company}</p><pre className="match-quote">{active.jd_text}</pre><p>{active.notes}</p>
    <button className="secondary" disabled={busy||!version||hasUnsavedChanges} onClick={()=>onUseJob(active)}>用当前简历分析这份岗位 →</button>
    {!version&&<p className="small muted">先从左侧打开一份简历，再分析或关联。</p>}
    <h3>本次投递进度</h3><label>阶段<select aria-label="投递阶段" value={stage} onChange={e=>setStage(e.target.value)}>{Object.entries(stages).map(([key,label])=><option value={key} key={key}>{label}</option>)}</select></label>
    <label>本次进展<textarea aria-label="投递进展备注" rows={2} maxLength={3000} value={note} onChange={e=>setNote(e.target.value)}/></label>
    <button className="secondary" disabled={busy} onClick={()=>run(update)}>记录进展</button>
    <h3>关联简历与面试</h3><p className="small muted">{version?`当前：第${version.sequence}版 · ${version.content_hash.slice(0,8)}`:'尚未打开简历'}</p>
    <label>同一版本的面试记录<select aria-label="关联面试记录" value={sid} onChange={e=>setSID(e.target.value)}><option value="">仅关联简历版本</option>{sessions.filter(s=>s.version_id===version?.version_id).map(s=><option value={s.session_id} key={s.session_id}>{new Date(s.created_at).toLocaleString()} · {({active:'进行中',paused:'已暂停',complete:'已结束',failed:'已停止'})[s.status]||'状态待确认'} · 已答{s.revision}轮</option>)}</select></label>
    <button className="secondary" disabled={busy||!version||hasUnsavedChanges} onClick={()=>run(async()=>{const updated=await api(`/jobs/${active.job_id}/links`,{method:'POST',body:{resume_id:version.resume_id,version_id:version.version_id,interview_id:sid||null}});setActive(updated);setJobs(rows=>rows.map(j=>j.job_id===updated.job_id?updated:j));})}>关联当前版本/面试</button>
    {active.links.map(link=><div className="source-row" key={`${link.version_id}:${link.interview_id}`}><span>第{link.sequence}版 · {link.content_hash.slice(0,8)}{link.interview_id?' · 含面试':''}</span><button className="text-button" disabled={busy} onClick={()=>run(()=>onOpenVersion(link))}>查看当时简历</button></div>)}
    <h3>进展时间线</h3>{active.events.map(e=><div className="history" key={e.event_id}><strong>{stages[e.stage]}</strong><p>{e.note}</p><small>{new Date(e.created_at).toLocaleString()}</small></div>)}
    <button className="text-button danger" disabled={busy} onClick={()=>{if(window.confirm('删除这张岗位卡片及投递记录？简历和面试仍保留。'))run(async()=>{await api(`/jobs/${active.job_id}`,{method:'DELETE'});setActive(null);await refresh();});}}>删除此岗位卡片</button>
  </>}</section></div>;
}
