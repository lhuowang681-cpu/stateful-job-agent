import React,{useEffect,useState} from 'react';

export function KnowledgePanel({api,run,busy}) {
  const [status,setStatus]=useState(null),[query,setQuery]=useState(''),[kind,setKind]=useState('doc');
  const [method,setMethod]=useState('bm25'),[result,setResult]=useState(null),[error,setError]=useState('');
  useEffect(()=>{let active=true;api('/knowledge/status').then(v=>{if(active)setStatus(v);}).catch(e=>{if(active)setError(e.message);});return()=>{active=false;};},[]);
  async function search(){setResult(await api('/knowledge/search',{method:'POST',body:{query,kind,method,limit:5}}));}
  return <section className="panel"><p className="eyebrow">公共知识 · 学习参考</p><h2>理解概念，再回到自己的实现。</h2>
    <p className="muted">本项目整理的技术摘要和原创练习，每条保留参考资料、整理版本与许可。公共知识可以解释概念，不能证明你的个人经历。</p>
    {status&&<p className="small muted">{status.documents}份技术摘要 · {status.questions}道原创练习 · 参考要点仅在完成面试后的复盘使用。</p>}
    {error&&<p role="alert" className="error">{error}</p>}
    <div className="match-inputs"><div><label>想学习的主题<input aria-label="公共知识检索问题" value={query} maxLength={600} onChange={e=>setQuery(e.target.value)} placeholder="例如 Checkpoint、RRF 或 AST 引用边界"/></label>
      <div className="button-row">{['Checkpoint 长期记忆','幂等 回执','AST 静态源码','RRF 融合'].map(t=><button className="text-button" key={t} disabled={busy} onClick={()=>setQuery(t)}>{t}</button>)}</div></div>
      <div><label>资料类型<select aria-label="公共知识资料类型" value={kind} onChange={e=>setKind(e.target.value)}><option value="doc">技术摘要</option><option value="question">练习题目 · 不展示参考答案</option></select></label>
        <label>查找方式<select aria-label="公共知识检索方式" value={method} onChange={e=>setMethod(e.target.value)}><option value="bm25">关键词检索</option><option value="tag">主题标签</option><option value="dense" disabled={!status?.dense_available}>语义向量{!status?.dense_available?' · 本地模型未配置':''}</option><option value="hybrid">混合检索 · 缺向量时明确降级</option></select></label>
        <button className="primary" disabled={busy||!query.trim()} onClick={()=>run(search)}>查找学习材料</button></div></div>
    {result&&<><h3>找到 {result.hits.length} 条材料</h3>{result.warnings.length>0&&<p className="small muted">本次按关键词查找，没有使用语义向量。</p>}
      {!result.hits.length&&<p className="muted">当前小型资料库未找到匹配内容，可换用准确术语；未检出不代表该知识点不存在。</p>}
      {result.hits.map(hit=><article className="match-row" key={hit.entry.version_id}><div className="section-heading"><h3>{hit.entry.title}</h3><span className="pill">{hit.entry.kind==='doc'?'整理摘要':'原创练习'}</span></div>
        <p>{hit.entry.body}</p><p className="small muted">{hit.entry.tags.join(' · ')} · 整理于 {hit.entry.updated_at} · {hit.entry.license}</p>
        <p className="small muted">此处内容是本项目整理，非官方逐字引用；参考版本：{hit.entry.source_version}</p>
        <a href={hit.entry.source_url} target="_blank" rel="noreferrer">阅读参考资料 ↗</a>
        <details><summary>引用与版本依据</summary><p className="small muted">{hit.reference.path} · 第{hit.reference.start_line}–{hit.reference.end_line}行 · {hit.reference.content_hash.slice(0,12)}</p><p className="small muted">来源定位不等于用户具备该能力。</p></details>
      </article>)}
    </>}
  </section>;
}
