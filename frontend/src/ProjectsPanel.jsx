import React,{useEffect,useRef,useState} from 'react';
const indexStatus={not_imported:'待导入',pending_index:'已保存，待索引',indexed:'索引可用',failed:'索引失败'};
const taskFailure={dispatch_retry_exhausted:'任务多次投递未成功，请检查后台服务后重新提交。',dispatch_delivery_exhausted:'任务等待执行过久，请检查后台服务后重新提交。',worker_recovery_exhausted:'多次恢复仍未完成，请检查后重新提交。',index_retry_exhausted:'多次重试仍未完成，请检查后重新提交。',task_superseded:'已存在更新的索引请求，请查看最新任务。',source_unavailable_or_integrity_failed:'原始资料已不可用或校验未通过。',index_task_rejected:'索引条件未满足，请检查资料和服务配置。'};

export function ProjectsPanel({api,run,busy}) {
  const [projects,setProjects]=useState([]),[project,setProject]=useState(null),[files,setFiles]=useState([]),[error,setError]=useState('');
  const [name,setName]=useState(''),[contribution,setContribution]=useState(''),[doc,setDoc]=useState('');
  const [github,setGithub]=useState(''),[ref,setRef]=useState(''),[snapshot,setSnapshot]=useState('');
  const [index,setIndex]=useState(null),[query,setQuery]=useState(''),[method,setMethod]=useState('code_aware'),[result,setResult]=useState(null),[details,setDetails]=useState([]);
  const [task,setTask]=useState(null),[taskError,setTaskError]=useState(''),[pollRetry,setPollRetry]=useState(0);const taskKey=useRef(null);
  async function refresh(){setProjects(await api('/projects'));setError('');}
  async function loadSnapshot(value,sid){setSnapshot(sid||'');setResult(null);setDetails([]);setTask(null);setTaskError('');setFiles(sid?await api(`/projects/${value.project_id}/files?snapshot=${encodeURIComponent(sid)}`):[]);setIndex(sid?await api(`/projects/${value.project_id}/index?snapshot=${encodeURIComponent(sid)}`):null);const tasks=await api(`/projects/${value.project_id}/index-tasks`);setTask(tasks.find(t=>t.snapshot_id===sid)||null);}
  async function open(value){setProject(value);await loadSnapshot(value,value.current_snapshot);}
  useEffect(()=>{let live=true;api('/projects').then(v=>{if(live)setProjects(v);}).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[]);
  useEffect(()=>{if(!task||!['QUEUED','RUNNING'].includes(task.status))return;let live=true,timer;
    async function poll(){try{const v=await api(`/tasks/${task.task_id}`);if(!live)return;setTask(v);setTaskError('');if(v.status==='SUCCEEDED'){setIndex(await api(`/projects/${project.project_id}/index?snapshot=${encodeURIComponent(snapshot)}`));await refresh();}else if(['QUEUED','RUNNING'].includes(v.status))timer=setTimeout(poll,800);}catch(e){if(live)setTaskError(e.message);}}
    timer=setTimeout(poll,400);return()=>{live=false;clearTimeout(timer);};
  },[task?.task_id,task?.status,project?.project_id,snapshot,pollRetry]);
  return <div className="longterm-grid"><section className="panel"><p className="eyebrow">个人项目知识空间</p><h2>让追问回到真实源码。</h2>
    <p className="muted">项目贡献是你的自述，源码只能证明某个版本的实现存在。导入的文件不会执行，也不会自动发送给模型。</p>
    <label>项目名称<input aria-label="新项目名称" value={name} maxLength={120} onChange={e=>setName(e.target.value)}/></label>
    <label>我的实际参与范围<textarea aria-label="项目贡献自述" rows={4} maxLength={6000} value={contribution} onChange={e=>setContribution(e.target.value)} placeholder="负责哪些部分，哪些是团队或开源代码，哪些只做过实验。"/></label>
    <button className="primary" disabled={busy||!name.trim()} onClick={()=>run(async()=>{await open(await api('/projects',{method:'POST',body:{name,contribution}}));await refresh();})}>创建私人项目空间</button>
    <h3>我的项目 · {projects.length}</h3>{error&&<p role="alert" className="error">{error}</p>}
    {projects.map(p=><button className={'job-card '+(project?.project_id===p.project_id?'selected':'')} key={p.project_id} disabled={busy} onClick={()=>run(()=>open(p))}><strong>{p.name}</strong><small>{p.snapshots.length}个快照 · {indexStatus[p.index_status]||'状态待确认'}</small></button>)}
  </section><section className="panel">{!project?<><h2>创建或选择项目</h2><p className="muted">从自己的代码压缩包或项目说明开始，后续检索始终绑定文件、行号与版本。</p></>:<>
    <h2>{project.name}</h2><p className="small muted">贡献自述 · 未独立核实</p><pre className="match-quote">{project.contribution||'尚未补充参与范围'}</pre>
    <label className="drop-zone"><strong>导入项目ZIP · 最大8MB</strong><small>排除密钥、环境文件、依赖目录；限制解压体积，不在磁盘解包和执行。</small>
      <input aria-label="上传项目ZIP" type="file" accept=".zip" disabled={busy} onChange={e=>{const file=e.target.files?.[0];if(file)run(async()=>{await open(await api(`/projects/${project.project_id}/zip`,{method:'POST',raw:true,body:file}));await refresh();});e.target.value='';}}/></label>
    <details><summary>或导入公开 GitHub 仓库</summary><p className="small muted">只下载公开源码并固定实际 commit，不传凭据、不访问私有仓库，也不会安装或执行项目。</p>
      <label>仓库地址<input aria-label="公开GitHub仓库地址" maxLength={300} value={github} onChange={e=>setGithub(e.target.value)} placeholder="https://github.com/组织/仓库"/></label>
      <label>分支、Tag 或 Commit（可选）<input aria-label="GitHub版本" maxLength={150} value={ref} onChange={e=>setRef(e.target.value)}/></label>
      <button className="secondary" disabled={busy||!github.trim()} onClick={()=>run(async()=>{await open(await api(`/projects/${project.project_id}/github`,{method:'POST',body:{url:github,ref}}));await refresh();})}>下载公开源码快照</button></details>
    <label>或添加项目说明<textarea aria-label="项目说明文档" rows={5} maxLength={100000} value={doc} onChange={e=>setDoc(e.target.value)} placeholder="说明模块关系、运行限制、自己的参与范围。不要填写API Key。"/></label>
    <button className="secondary" disabled={busy||!doc.trim()} onClick={()=>run(async()=>{await open(await api(`/projects/${project.project_id}/documents`,{method:'POST',body:{path:'PROJECT_NOTES.md',text:doc}}));await refresh();})}>保存为新项目快照</button>
    {!!project.snapshots.length&&<label>正在查看的项目版本<select aria-label="项目快照版本" value={snapshot} disabled={busy} onChange={e=>{const sid=e.target.value;run(()=>loadSnapshot(project,sid));}}>{project.snapshots.map(s=><option value={s.snapshot_id} key={s.snapshot_id}>{s.commit_sha?.slice(0,12)||s.content_hash.slice(0,12)} · {new Date(s.created_at).toLocaleString()}{s.snapshot_id===project.current_snapshot?' · 最新':''}</option>)}</select></label>}
    <h3>当前文件 · {files.length}</h3><p className="small muted">索引状态：{index?.status==='indexed'?'索引可用':indexStatus[project.index_status]||'状态待确认'}。快照导入成功不代表代码已运行。</p>
    {snapshot&&<><button className="secondary" disabled={busy||['QUEUED','RUNNING'].includes(task?.status)} onClick={()=>run(async()=>{const fp=project.project_id+snapshot;if(taskKey.current?.fp!==fp||['SUCCEEDED','FAILED','CANCELLED'].includes(task?.status))taskKey.current={fp,key:crypto.randomUUID()};setTask(await api(`/projects/${project.project_id}/index-tasks`,{method:'POST',body:{snapshot_id:snapshot,request_key:taskKey.current.key}}));setTaskError('');})}>{index?.status==='indexed'?'后台重建此快照索引':'后台建立此快照索引'}</button>
      {task&&<div className="notice" role="status"><p>索引任务 · {({QUEUED:'已排队',RUNNING:'正在解析源码',SUCCEEDED:'已完成',FAILED:'已停止',CANCELLED:'已取消'})[task.status]||'状态待确认'} · 第{task.attempts}次执行</p><p className="small muted">任务会保存，可离开页面后回来查看。故障恢复只重建索引，不运行上传的项目代码。</p>{task.status==='FAILED'&&<p className="small error">{taskFailure[task.error_code]||'索引未能完成，请检查后重新提交。'}</p>}{task.stage==='retry_wait'&&<p className="small muted">任务正在等待重试，原始资料已保留。</p>}{task.status==='QUEUED'&&<button className="text-button" disabled={busy} onClick={()=>run(async()=>setTask(await api(`/tasks/${task.task_id}/cancel`,{method:'POST',body:{}})))}>取消尚未开始的任务</button>}{taskError&&<><p className="small error">暂未取得进度：{taskError}</p><button className="text-button" disabled={busy} onClick={()=>run(async()=>{setTask(await api(`/tasks/${task.task_id}`));setTaskError('');setPollRetry(n=>n+1);})}>重新读取任务状态</button></>}</div>}
      {index?.status==='indexed'&&<div className="notice"><p>已处理 {index.files} 个文件 · {index.symbols} 个符号 · {index.edges} 条静态引用关系</p><p className="small muted">静态关系只表示源码可解析引用，不代表实际运行调用。{index.oversized_lines_omitted>0?`有 ${index.oversized_lines_omitted} 行超过读取上限，未作为检索片段。`:''}</p></div>}
      <label>关于实现的问题<input aria-label="代码检索问题" maxLength={600} value={query} onChange={e=>setQuery(e.target.value)} placeholder="例如 save_receipt 在哪里被调用？"/></label>
      <label>检索方式<select aria-label="代码检索方式" value={method} onChange={e=>setMethod(e.target.value)}><option value="code_aware">符号、关键词与静态关系</option><option value="symbol">精确符号</option><option value="keyword">关键词</option><option value="flat">平面分块（对照）</option><option value="readme">仅 README（对照）</option><option value="dense" disabled={!index?.dense_available}>语义向量{!index?.dense_available?' · 未配置本地模型':''}</option><option value="hybrid">混合检索 · 未配置向量时明确降级</option></select></label>
      <button className="primary" disabled={busy||!query.trim()||index?.status!=='indexed'} onClick={()=>run(async()=>{setDetails([]);setResult(await api(`/projects/${project.project_id}/search`,{method:'POST',body:{snapshot_id:snapshot,query,method,limit:5,expand_relations:true}}));})}>检索实现与来源</button>
      {result&&<section><h3>找到 {result.hits.length} 条线索</h3><p className="small muted">相关片段需要进一步判断，不能证明用户贡献或实际运行结果。{result.warnings.length?'本次没有使用语义向量，按符号/关键词检索。':''}</p>
        {!result.hits.length&&<p className="muted">此快照未定位到可返回的线索，可尝试准确函数名或补充文件；不代表项目没有相关能力。</p>}
        {result.hits.map(hit=><div className="match-row" key={hit.reference.evidence_id}><CodeQuote value={hit.reference}/>{hit.symbol&&<div className="button-row"><span className="small muted">{hit.symbol.qualified_name}</span>
          <button className="text-button" disabled={busy} onClick={()=>run(async()=>{const detail=await api(`/projects/${project.project_id}/symbol?snapshot=${encodeURIComponent(snapshot)}&name=${encodeURIComponent(hit.symbol.symbol_id)}`);setDetails([detail]);})}>查看符号范围</button>
          <button className="text-button" disabled={busy} onClick={()=>run(async()=>setDetails(await api(`/projects/${project.project_id}/references?snapshot=${encodeURIComponent(snapshot)}&symbol_id=${encodeURIComponent(hit.symbol.symbol_id)}`)))}>查找引用</button>
          <button className="text-button" disabled={busy} onClick={()=>run(async()=>setDetails(await api(`/projects/${project.project_id}/references?snapshot=${encodeURIComponent(snapshot)}&symbol_id=${encodeURIComponent(hit.symbol.symbol_id)}&tests_only=true`)))}>查找测试源码</button></div>}</div>)}
        {!!details.length&&<details open><summary>精确读取结果 · {details.length}</summary>{details.map((item,i)=><div className="match-row" key={i}><CodeQuote value={item.reference}/><p className="small muted">{item.test_execution==='not_run'?'这是测试文件中的引用，未运行测试。':'仅展示静态源码，不能推断已经执行。'}</p></div>)}</details>}
      </section>}
    </>}
    <details><summary>查看原始文件清单 · {files.length}</summary>{files.map(f=><div className="source-row" key={f.path}><code>{f.path}</code><small>{f.lines}行 · {f.content_hash.slice(0,8)}</small></div>)}</details>
    <details><summary>不可变快照 · {project.snapshots.length}</summary>{project.snapshots.map(s=><div className="history" key={s.snapshot_id}><strong>{s.commit_sha?.slice(0,12)||s.content_hash.slice(0,12)}</strong><p className="small muted">{s.origin} · {new Date(s.created_at).toLocaleString()} · {s.metadata.stored_files??'文档'}个文件</p></div>)}</details>
    <button className="text-button danger" disabled={busy} onClick={()=>{if(window.confirm('删除这个项目及所有快照、文件和派生索引？'))run(async()=>{await api(`/projects/${project.project_id}`,{method:'DELETE'});setProject(null);setFiles([]);await refresh();});}}>删除项目及派生资料</button>
  </>}</section></div>;
}

function CodeQuote({value}) {
  return <div><strong>{value.path} : {value.start_line}–{value.end_line}</strong><p className="small muted">{value.commit?`commit ${value.commit.slice(0,12)}`:`不可变快照 ${value.snapshot_id.slice(-8)}`} · 来源已定位，语义支持仍需判断</p><pre className="match-quote">{value.quote}</pre></div>;
}
