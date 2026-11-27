import React,{useEffect,useState} from 'react';

const bucketLabel={new:'新观察，待你核对',review_due:'已到复习时间',reviewed:'本次已复核',paused:'你已暂停',historical_version:'来自历史简历版本',expired:'已久未核对',excluded:'来源不可用'};
const findingLabel={needs_practice:'我还需要练习',unsure:'我暂不确定',understood:'我自述已理解'};
export const observationFindingLabel={lexical_located:'找到表达线索（规则参考）',lexical_not_located:'暂未定位表达线索（不等于不会）',
  correct:'参考判断符合要点，待核对',incorrect:'参考判断发现差异，待核对',uncertain:'参考判断不确定'};

function Observation({item,api,run,busy,onChange,onPractice,cap,hasUnsavedChanges}) {
  const [note,setNote]=useState(''),[finding,setFinding]=useState('unsure'),[days,setDays]=useState(3);
  const [mode,setMode]=useState('local_demo'),[consent,setConsent]=useState(false),[historical,setHistorical]=useState(false);
  const p=item.payload,valid=['valid','expired'].includes(item.status);
  async function act(action,extra={}) {
    await api(`/learning/observations/${item.observation_id}/actions`,{method:'POST',body:{request_key:crypto.randomUUID(),expected_revision:item.revision,action,...extra}});
    setNote('');await onChange(action);
  }
  async function practice(){
    const allow=consent;setConsent(false);
    const view=await api(`/learning/observations/${item.observation_id}/practice`,{method:'POST',body:{request_key:crypto.randomUUID(),expected_revision:item.revision,
      mode,allow_external_processing:allow,allow_historical_version:historical}});
    await onPractice(view);
  }
  return <details className="match-row"><summary>{p?.knowledge_point||'来源已失效或评价已撤回'} · {bucketLabel[item.queue_bucket]}</summary>
    {p&&<><p className="small muted">{new Date(p.observed_at*1000).toLocaleString()} · {p.provider} / {p.model} · {p.method_version}</p>
      <h4>{p.question}</h4><p className="match-quote">{p.answer}</p><p className="small">原参考评价：{observationFindingLabel[p.finding]||'暂未形成参考判断'} · {p.evaluation_note}</p>
      <p className="small muted">{item.confidence==='user_corrected'?'包含你的明确纠正':item.confidence==='repeated_consistent_observations'?`${item.consistent_distinct_sessions}场同记录条件下的相同观察`:'一次回答的观察'}；这些记录都不认定已经掌握。</p>
      {p.references?.map((r,i)=><p className="small muted" key={i}>{r.path} : {r.start_line}–{r.end_line} · 来源 {r.snapshot_id?.slice(0,12)} · {r.content_hash?.slice(0,12)}</p>)}
      {item.controls.user_note&&<p className="small">你的纠正：{findingLabel[item.controls.user_finding]} · {item.controls.user_note}</p>}
      <div className="button-row"><button className="secondary" disabled={busy} onClick={()=>run(()=>act('confirm'))}>确认已核对这条观察</button>
        <button className="secondary" disabled={busy||!item.confirmed} onClick={()=>run(()=>act('mark_reviewed'))}>标记本次已复核</button>
        <button className="text-button" disabled={busy} onClick={()=>run(()=>act(item.paused?'resume':'pause'))}>{item.paused?'恢复这条观察':'暂停这条观察'}</button></div>
      <label>我对这条记录的看法<select value={finding} disabled={busy} onChange={e=>setFinding(e.target.value)}>{Object.entries(findingLabel).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>
      <label>纠正或撤回的说明<textarea rows={2} maxLength={1000} disabled={busy} value={note} onChange={e=>setNote(e.target.value)} placeholder="说明表达、识别或评价与实际情况的差异。"/></label>
      <button className="secondary" disabled={busy||!note.trim()} onClick={()=>run(()=>act('correct',{user_finding:finding,note}))}>保存我的纠正</button>
      <button className="text-button" disabled={busy||!note.trim()} onClick={()=>run(()=>act('withdraw',{note}))}>撤回本题评价作为学习依据</button>
      <p className="small muted">纠正单独保存，不改历史评价。撤回会让本题所有观察退出复习，也不再驱动待补充项练习。</p>
      <label>下次复习时间<select value={days} disabled={busy} onChange={e=>setDays(Number(e.target.value))}>{[0,1,3,7,14,30].map(d=><option key={d} value={d}>{d===0?'现在':`${d}天后`}</option>)}</select></label>
      <button className="text-button" disabled={busy} onClick={()=>run(()=>act('schedule',{review_in_days:days}))}>调整这条复习时间</button>
      <label>再次练习方式<select value={mode} disabled={busy} onChange={e=>{setMode(e.target.value);setConsent(false);}}><option value="local_demo">本地规则反馈</option><option value="llm" disabled={!cap.llm}>配置的模型</option></select></label>
      {item.historical_version&&<label className="check"><input type="checkbox" checked={historical} onChange={e=>setHistorical(e.target.checked)}/>我确认使用这条记录的原简历版本练习。</label>}
      {mode==='llm'&&<label className="check"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>同意建立模型练习；提交回答时还需重新同意发送回答、岗位、经历与引用源码。</label>}
      <button className="primary" disabled={busy||hasUnsavedChanges||!item.confirmed||item.paused||item.status!=='valid'||(item.historical_version&&!historical)||(mode==='llm'&&!consent)} onClick={()=>run(practice)}>用这道题和原来源再次练习</button>
      {hasUnsavedChanges&&<p className="small muted">请先保存简历修改。</p>}</>}
    {!valid&&<p className="small muted">来源不可用或本题评价已撤回；内容已隐藏，不会继续作为复习依据。</p>}
    <button className="text-button" disabled={busy} onClick={()=>run(()=>act('delete'))}>删除这条学习记录</button>
    <p className="small muted">删除清除该观察的回答与纠正正文；原面试历史独立保留，同一来源不会自动重建这条观察。</p>
  </details>;
}

export function LearningPanel({api,run,busy,version,view,onPractice,onRecordsChanged,cap,hasUnsavedChanges}) {
  const [items,setItems]=useState([]),[queue,setQueue]=useState(null),[prefs,setPrefs]=useState(null),[error,setError]=useState('');
  const rid=version.resume_id;
  async function read(){const [items,queue]=await Promise.all([api(`/learning/observations?resume_id=${encodeURIComponent(rid)}`),api(`/learning/queue?resume_id=${encodeURIComponent(rid)}`)]);return {items,queue};}
  function update(data){setItems(data.items);setQueue(data.queue);setPrefs(data.queue.preferences);setError('');}
  async function refresh(){update(await read());}
  useEffect(()=>{let live=true;read().then(data=>{if(live)update(data);}).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[rid,version.version_id,view?.session_id,view?.revision]);
  async function changed(action){await refresh();if(['correct','withdraw','delete'].includes(action))await onRecordsChanged();}
  async function savePreferences(){await api('/learning/preferences',{method:'PUT',body:{expected_revision:prefs.revision,cadence_days:prefs.cadence_days,daily_limit:prefs.daily_limit,paused:prefs.paused,include_new:prefs.include_new}});await refresh();}
  return <section className="interview-review"><div className="section-heading"><h3>我的学习记录与复习</h3><button className="text-button" disabled={busy} onClick={()=>run(refresh)}>刷新学习记录</button></div>
    <p className="small muted">从已回答、已结束的面试生成带来源的观察，由你核对和纠正。这里不自动形成能力画像，也不会把观察写进简历。</p>
    {error&&<p className="error">{error}</p>}
    {view?.status==='complete'&&view.revision>0&&<button className="secondary" disabled={busy} onClick={()=>run(async()=>{await api(`/interviews/${view.session_id}/learning-observations`,{method:'POST'});await refresh();})}>将本场已答内容保存为学习观察</button>}
    {prefs&&<details><summary>调整复习节奏 · {prefs.source==='explicit_user_preference'?'你的明确偏好':'当前为默认规则'}</summary>
      <label>默认复习间隔（天）<input type="number" min={1} max={30} value={prefs.cadence_days} disabled={busy} onChange={e=>setPrefs({...prefs,cadence_days:Number(e.target.value)})}/></label>
      <label>每日建议上限<input type="number" min={1} max={20} value={prefs.daily_limit} disabled={busy} onChange={e=>setPrefs({...prefs,daily_limit:Number(e.target.value)})}/></label>
      <label className="check"><input type="checkbox" checked={prefs.include_new} onChange={e=>setPrefs({...prefs,include_new:e.target.checked})}/>在建议中显示尚未核对的新观察</label>
      <label className="check"><input type="checkbox" checked={prefs.paused} onChange={e=>setPrefs({...prefs,paused:e.target.checked})}/>暂停全部复习建议</label>
      <button className="secondary" disabled={busy||prefs.cadence_days<1||prefs.cadence_days>30||prefs.daily_limit<1||prefs.daily_limit>20} onClick={()=>run(savePreferences)}>保存我的复习偏好</button>
    </details>}
    {queue&&<><p className="small">新观察 {queue.counts.new} · 到期 {queue.counts.review_due} · 已复核 {queue.counts.reviewed} · 暂停 {queue.counts.paused} · 历史版本 {queue.counts.historical_version} · 久未核对 {queue.counts.expired} · 失效 {queue.counts.excluded}</p>
      <p className="small muted">{queue.preferences.paused?'已按你的偏好暂停复习建议。':`本次建议 ${queue.items.length} 条，今日已复核 ${queue.reviewed_today} 条，剩余建议额度 ${queue.remaining_today} 条（按上海日期）。`}标记已复核只安排下次时间，不认定学会。</p>
      {queue.items.length>0&&<p className="small">建议先看：{queue.items.map(i=>i.payload?.knowledge_point).join('；')}</p>}</>}
    <p className="small muted">已保存 {items.length} 条；最多展示最近200条，单用户存储上限2000条。</p>
    {items.slice(0,200).map(item=><Observation key={`${item.observation_id}:${item.revision}:${item.status}`} item={item} api={api} run={run} busy={busy} cap={cap} hasUnsavedChanges={hasUnsavedChanges} onChange={changed} onPractice={onPractice}/>)}
  </section>;
}
