import React, {useEffect, useRef, useState} from 'react';
import {LearningPanel,observationFindingLabel} from './LearningPanel.jsx';

const statusLabel={active:'练习进行中',paused:'已暂停，记录已保存',complete:'本场已结束',failed:'执行已停止，请查看记录'};
export function InterviewPanel({api,run,busy,version,cap,context,hasUnsavedChanges}) {
  const [expanded,setExpanded]=useState(false),[jd,setJD]=useState(''),[matchId,setMatchId]=useState(null);
  const [mode,setMode]=useState('local_demo'),[consent,setConsent]=useState(false),[limit,setLimit]=useState(4);
  const [view,setView]=useState(null),[history,setHistory]=useState([]),[error,setError]=useState('');
  const [answer,setAnswer]=useState(''),[review,setReview]=useState(null);
  const [track,setTrack]=useState('job'),[projects,setProjects]=useState([]),[projectId,setProjectId]=useState(''),[snapshot,setSnapshot]=useState(''),[prior,setPrior]=useState('');
  const startRef=useRef(null),answerRef=useRef(null),rid=version.resume_id;
  useEffect(()=>{
    let active=true;
    api(`/resumes/${rid}/interviews`).then(h=>{if(active){setHistory(h);setError('');}}).catch(e=>{if(active)setError(e.message);});
    return()=>{active=false;};
  },[rid,version.version_id]);
  useEffect(()=>{let live=true;api('/projects').then(v=>{if(live)setProjects(v);}).catch(()=>{});return()=>{live=false;};},[expanded]);
  useEffect(()=>{if(context){setJD(context.jd_text);setMatchId(context.match_id);setExpanded(true);setConsent(false);}},[context]);
  async function load(id){
    const v=await api(`/interviews/${id}`);setView(v);setAnswer('');setConsent(false);setReview(null);
    if(v.status==='complete')setReview(await api(`/interviews/${id}/review`));
  }
  async function refresh(){setHistory(await api(`/resumes/${rid}/interviews`));setError('');}
  async function start(){
    const data={version_id:version.version_id,expected_content_hash:version.content_hash,jd_text:jd,match_id:matchId,mode,max_turns:Number(limit),use_retrieval:true,track,
      project_id:track==='project'?projectId:null,snapshot_id:track==='project'?snapshot:null,prior_session_id:track==='weakness'?prior:null};
    const fp=JSON.stringify(data);
    if(startRef.current?.fp!==fp)startRef.current={fp,key:crypto.randomUUID()};
    const allow=consent;setConsent(false);
    const v=await api(`/resumes/${rid}/interviews`,{method:'POST',body:{...data,request_key:startRef.current.key,allow_external_processing:allow}});
    setView(v);setAnswer('');setReview(null);await refresh();
  }
  async function submit(){
    const data={question_id:view.current.question_id,expected_revision:view.revision,answer};const fp=JSON.stringify(data);
    if(answerRef.current?.fp!==fp)answerRef.current={fp,key:crypto.randomUUID()};
    const allow=consent;setConsent(false);
    const v=await api(`/interviews/${view.session_id}/answers`,{method:'POST',body:{...data,request_key:answerRef.current.key,allow_external_processing:allow}});
    setView(v);if(!v.answer_pending)setAnswer('');await refresh();
    if(v.status==='complete')setReview(await api(`/interviews/${v.session_id}/review`));
  }
  return <section className="panel interview-panel">
    <div className="section-heading"><div><p className="eyebrow">从岗位到面试 · 有界协作</p><h2>练习回答，让下一题回应你的薄弱点</h2></div><button className="secondary" disabled={busy} onClick={()=>setExpanded(!expanded)}>{expanded?'收起面试练习':'准备模拟面试 →'}</button></div>
    <p className="small muted">评估者给出后续行动建议，面试官决定追问或换题。参考要点和详细评价在结束后开放，练习不会改写简历。</p>
    {expanded && <>
      <div className="match-inputs"><div><label htmlFor="interview-track">本场练习目标</label><select id="interview-track" disabled={busy} value={track} onChange={e=>{setTrack(e.target.value);setConsent(false);}}><option value="job">岗位面试 · 公共题库检索</option><option value="project">项目源码 · 函数与测试追问</option><option value="weakness">薄弱项 · 从已结束场次复习</option></select>
      {track==='project'&&<><label htmlFor="interview-project">私人项目范围</label><select id="interview-project" disabled={busy} value={projectId} onChange={e=>{const p=projects.find(x=>x.project_id===e.target.value);setProjectId(e.target.value);setSnapshot(p?.current_snapshot||'');setConsent(false);}}><option value="">选择已导入的项目</option>{projects.filter(p=>p.current_snapshot).map(p=><option key={p.project_id} value={p.project_id}>{p.name}</option>)}</select><label htmlFor="interview-snapshot">固定源码版本</label><select id="interview-snapshot" disabled={busy} value={snapshot} onChange={e=>{setSnapshot(e.target.value);setConsent(false);}}><option value="">选择快照</option>{(projects.find(p=>p.project_id===projectId)?.snapshots||[]).map(s=><option key={s.snapshot_id} value={s.snapshot_id}>{s.commit_sha?.slice(0,12)||s.content_hash.slice(0,12)}</option>)}</select><p className="small muted">先在项目空间完成索引，在下方写明函数名或关心的实现。源码存在不证明个人贡献，也不会运行导入代码。</p></>}
      {track==='weakness'&&<><label htmlFor="interview-prior">已结束的面试</label><select id="interview-prior" disabled={busy} value={prior} onChange={e=>setPrior(e.target.value)}><option value="">选择已有待补充项的场次</option>{history.filter(h=>h.status==='complete').map(h=><option key={h.session_id} value={h.session_id}>{new Date(h.created_at).toLocaleString()} · 已答{h.revision}轮</option>)}</select></>}
      </div><p className="small muted">工具只读取所选用户范围的资料，最多18次；公开知识用于概念练习，项目源码用于实现分析，个人经历保持未独立核实。</p></div>
      <div className="match-inputs"><div><div className="label-row"><label htmlFor="interview-jd">本场岗位 JD</label><button className="text-button" disabled={busy} onClick={()=>{setJD('LangGraph Agent 开发，理解 Checkpoint 恢复、外部副作用和幂等。');setMatchId(null);setConsent(false);}}>填入合成面试岗位</button></div>
        <textarea id="interview-jd" rows={4} maxLength={12000} value={jd} disabled={busy} onChange={e=>{setJD(e.target.value);setMatchId(null);setConsent(false);}}/>
        <p className="small muted">新场次绑定当前第 {version.sequence} 版{matchId?'；JD 沿用已保存岗位快照，面试版本单独绑定。':'及此处 JD 快照。'}</p></div>
        <div><label htmlFor="interview-mode">练习方式</label><select id="interview-mode" disabled={busy} value={mode} onChange={e=>{setMode(e.target.value);setConsent(false);}}><option value="local_demo">本地题库与规则反馈 · 无模型调用</option><option value="llm" disabled={!cap.llm}>在线评估与选题{!cap.llm?' · 尚未配置':''}</option></select>
          <label htmlFor="interview-limit">最多回答轮数</label><select id="interview-limit" disabled={busy} value={limit} onChange={e=>setLimit(e.target.value)}>{[2,3,4,5,6].map(n=><option key={n} value={n}>{n} 轮</option>)}</select>
          {mode==='llm' && <label className="check"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>同意创建在线练习；每次提交回答还需重新同意发送回答、JD、所选经历和本场检索到的项目源码片段给配置模型。</label>}
          <button className="primary" disabled={busy||!jd.trim()||hasUnsavedChanges||(track==='project'&&(!projectId||!snapshot))||(track==='weakness'&&!prior)||(mode==='llm'&&!consent)} onClick={()=>run(start)}>建立本场面试快照</button>
          {hasUnsavedChanges && <p className="small error">请先保存简历修改，再创建面试。</p>}
        </div></div>
      <details className="match-history"><summary>面试练习记录 · {history.length}</summary>{error&&<p className="error">{error}</p>}<button className="text-button" disabled={busy} onClick={()=>run(refresh)}>刷新面试记录</button>
        {history.map(h=><div className="source-row" key={h.session_id}><div><strong>{new Date(h.created_at).toLocaleString()}</strong><small>{statusLabel[h.status]} · 已回答 {h.revision} 轮</small></div><button className="text-button" disabled={busy} onClick={()=>run(()=>load(h.session_id))}>查看本场</button></div>)}
      </details>
      {view && <div className="match-results"><div className="section-heading"><h3>{statusLabel[view.status]}</h3><span className="pill">{view.mode==='local_demo'?'规则练习 · 非模型质量成绩':'在线角色参考'}</span></div>
        <p className="small muted">{view.provider} / {view.model} · 已回答 {view.revision}/{view.max_turns} 轮 · 每主题最多一次追问 · 模型请求预留 {view.usage.provider_calls} 次（最多 {view.max_turns*2} 次）</p>
        {!view.version_is_current && <p className="small muted">最新简历已变化；本场仍使用创建时的版本快照。</p>}
        {view.warnings.map((w,i)=><p className="small muted" key={i}>{w}</p>)}
        <details><summary>本场 JD</summary><pre className="match-quote">{view.jd_text}</pre></details>
        {view.turns.map((t,i)=><details className="match-row" key={t.question.question_id}><summary>已答 {i+1} · {t.question.prompt}</summary><p className="match-quote">{t.answer}</p></details>)}
        {view.current && view.status==='active' && <section className="interview-question"><span className="pill">{view.current.followup?'根据反馈追问':'新主题'}</span><h3>{view.current.prompt}</h3>
          {view.current.references?.filter(r=>r.scope==='private_project').map(r=><details key={r.evidence_id} open><summary>{r.path} : {r.start_line}–{r.end_line} · {r.commit?.slice(0,12)||'不可变快照'}</summary><pre className="match-quote">{r.quote}</pre><p className="small muted">来源已定位，语义仍需判断；{r.evidence_kind==='test_code'?'仅找到测试源码，未执行测试。':'静态实现不代表已运行或个人贡献。'}</p></details>)}
          <label htmlFor="interview-answer">你的回答</label><textarea id="interview-answer" rows={6} maxLength={5000} value={answer} disabled={busy||view.answer_pending} onChange={e=>{setAnswer(e.target.value);setConsent(false);}} placeholder="用自己的话说明设计、取舍和边界。暂不展示参考答案。"/>
          {view.mode==='llm' && <label className="check"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>同意发送本次回答、JD、绑定版本的经历正文及引用源码片段（请检查私人信息），最多两次模型调用，无自动重试。</label>}
          <button className="primary" disabled={busy||view.answer_pending||!answer.trim()||(view.mode==='llm'&&!consent)} onClick={()=>run(submit)}>提交回答，让面试官决定下一步</button>
        </section>}
        {view.answer_pending && <p className="small muted">这条回答已保存，正在处理或等待恢复。先刷新本场，不要重复建立任务。</p>}
        {view.model_inflight && <p className="small error">模型调用结果尚不确定，系统禁止自动重放；请核对服务结果后决定是否另建场次。</p>}
        {view.error_code && <p className="small error">本场已停止（{view.error_code}），未自动重复调用。</p>}
        {view.resumable && <button className="secondary" disabled={busy||(view.mode==='llm'&&!consent)} onClick={()=>run(async()=>{const allow=consent;setConsent(false);const v=await api(`/interviews/${view.session_id}/resume`,{method:'POST',body:{allow_external_processing:allow}});setView(v);if(v.status==='complete')setReview(await api(`/interviews/${v.session_id}/review`));await refresh();})}>从已保存面试步骤继续</button>}
        {view.answer_pending && <button className="text-button" disabled={busy} onClick={()=>run(()=>load(view.session_id))}>刷新本场状态</button>}
        {view.status==='active' && <button className="text-button" disabled={busy||view.answer_pending} onClick={()=>run(async()=>{const v=await api(`/interviews/${view.session_id}/finish`,{method:'POST',body:{expected_revision:view.revision}});setView(v);setReview(await api(`/interviews/${view.session_id}/review`));await refresh();})}>结束本场并查看复盘</button>}
        {['active','paused'].includes(view.status)&&<button className="secondary" disabled={busy||view.answer_pending} onClick={()=>run(async()=>{setView(await api(`/interviews/${view.session_id}/${view.status==='paused'?'continue':'pause'}`,{method:'POST',body:{expected_revision:view.revision}}));await refresh();})}>{view.status==='paused'?'继续这场练习':'暂停并保存本场'}</button>}
        <details className="match-history"><summary>真实资料工具调用 · {view.tool_calls||0}/18</summary><p className="small muted">下面是实际读取记录。规则模式也会调用真实资料工具，但不代表运行了模型或项目代码。</p>{view.tool_trace?.map(t=><p key={t.index} className="small">#{t.index} · {t.role} → {t.tool} · {t.status} · {t.duration_ms}ms{t.error_code?` · ${t.error_code}`:''}</p>)}</details>
        <details className="match-history"><summary>面试协作交接 · {view.messages.length}</summary>{view.messages.map((m,i)=><p className="small" key={i}>{({evaluator:'评估者',interviewer:'面试官',coordinator:'协调器'})[m.from]||m.from} → {({interviewer:'面试官',coordinator:'协调器'})[m.to]||m.to} · 第 {m.turn} 轮 · {m.action?({follow_up:'追问',next:'换题',finish:'结束'})[m.action]:m.retrieval_target?`选择资料：${m.retrieval_target}`:'交接信息'} · {m.detail}</p>)}</details>
        {['complete','failed'].includes(view.status) && <button className="text-button" disabled={busy} onClick={()=>{startRef.current=null;setView(null);setReview(null);setConsent(false);}}>准备新一场（不会自动执行）</button>}
        {review && <section className="interview-review"><h3>结束后复盘 · {review.scope}</h3><p className="small muted">{review.warning}</p>
          {review.learning_comparison&&<p className="small muted">本条再次练习：{review.learning_comparison.status==='same_recorded_conditions'?`记录条件相同，原参考评价 ${observationFindingLabel[review.learning_comparison.before_finding]} → 本次 ${observationFindingLabel[review.learning_comparison.after_finding]}。`:'来源或评价条件变化，不直接比较。'} {review.learning_comparison.warning}</p>}
          {review.practice_comparison&&!review.learning_comparison&&<div className="notice"><strong>与上一场的表达回顾</strong><p className="small muted">{review.practice_comparison.warning}</p>{review.practice_comparison.status==='not_comparable'?<p className="small">本次题目或评价条件不同，保留两次记录，不计算提升率。</p>:review.practice_comparison.topics.map(t=><p className="small" key={t.topic_id}>{t.topic_id} · 上次定位{t.before_covered}/{t.total}个参考要点 → 本次{t.after_covered}/{t.total}（同题目/同规则的末次回答）</p>)}</div>}
          <p className="small muted">{review.source_boundary}</p>{!!review.weaknesses?.length&&<button className="secondary" disabled={busy} onClick={()=>{setTrack('weakness');setPrior(view.session_id);setJD(view.jd_text);setMatchId(null);startRef.current=null;setView(null);setReview(null);setConsent(false);}}>根据本场待补充项准备专项练习</button>}
          {review.turns.map((t,i)=><article className="match-row" key={i}><h3>{i+1}. {t.question}</h3><p className="small">已定位要点：{t.covered.join('；')||'暂未定位'}</p><p className="small">待补充或未识别：{t.missing.join('；')||'本轮参考要点已覆盖'}</p>
            {t.assessment_withdrawn&&<p className="small error">你已撤回本题评价作为学习依据；历史记录保留，本题不再进入复习或待补充项练习。</p>}
            {t.claim_needs_evidence&&<p className="small">个人经历或责任范围需补充材料；这不等于认定表述为假。</p>}<p className="small muted">{t.note}</p></article>)}
          {!!review.learning_resources?.length&&<section><h3>继续学习 · 带来源的公共资料</h3><p className="small muted">仅作概念参考，不作为个人经历证明；摘要是本项目整理，并非官方逐字引用。</p>{review.learning_resources.map(hit=><article className="match-row" key={hit.entry.version_id}><h3>{hit.entry.title}</h3><p>{hit.entry.body}</p><a href={hit.entry.source_url} target="_blank" rel="noreferrer">阅读参考资料 ↗</a><p className="small muted">{hit.entry.source_version} · {hit.entry.license} · {hit.reference.content_hash.slice(0,12)}</p></article>)}</section>}
          {review.resources_status==='unavailable'&&<p className="small muted">本次公共资料暂不可读，面试复盘仍已保留，可稍后重试资料检索。</p>}
        </section>}
      </div>}
      {(!view||view.status==='complete')&&<LearningPanel api={api} run={run} busy={busy} cap={cap} version={version} view={view} hasUnsavedChanges={hasUnsavedChanges}
        onRecordsChanged={async()=>{if(view?.status==='complete')setReview(await api(`/interviews/${view.session_id}/review`));}}
        onPractice={async v=>{setView(v);setAnswer('');setConsent(false);setReview(null);await refresh();}}/>}
    </>}
  </section>;
}
