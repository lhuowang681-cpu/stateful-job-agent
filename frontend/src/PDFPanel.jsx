import React, {lazy, Suspense, useEffect, useState} from 'react';
const PDFPreview=lazy(()=>import('./PDFPreview.jsx'));

export function PDFPanel({api, run, busy, version, token, hasUnsavedChanges}) {
  const [template, setTemplate] = useState('classic'), [history, setHistory] = useState([]);
  const [preview, setPreview] = useState(null), [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    api(`/resumes/${version.resume_id}/pdfs`).then(v => {if (active) {setHistory(v); setError('');}})
      .catch(e => {if (active) setError(e.message);});
    return () => {active = false;};
  }, [version.resume_id, version.version_id, version.confirmed_at]);
  useEffect(() => {if (!preview) return; return () => URL.revokeObjectURL(preview.url);}, [preview]);
  useEffect(() => {setPreview(null);}, [version.version_id]);
  async function open(item) {
    const response = await fetch(`/api/v2/pdfs/${item.export_id}`, {headers: {Authorization:`Bearer ${token}`}});
    if (!response.ok) throw new Error('PDF 无法读取，请刷新版本后重试。');
    const blob=await response.blob();
    setPreview({url: URL.createObjectURL(blob), blob, item});
  }
  async function generate() {
    const item = await api(`/resumes/${version.resume_id}/versions/${version.version_id}/pdf`, {
      method:'POST', body:{expected_content_hash:version.content_hash, template},
    });
    setHistory(await api(`/resumes/${version.resume_id}/pdfs`)); await open(item);
  }
  return <section className="panel pdf-panel"><div className="section-heading"><div>
    <p className="eyebrow">确认后导出</p><h2>把这一版，带去下一次机会。</h2></div><span className="pill">第 {version.sequence} 版</span></div>
    <p className="small muted">PDF 只使用这份已确认版本，保留可选择的文字。修改后需要重新保存、确认和导出。</p>
    <div className="button-row"><label>简历模板 <select aria-label="简历模板" value={template} onChange={e=>setTemplate(e.target.value)} disabled={busy}>
      <option value="classic">经典 · 舒展留白</option><option value="compact">紧凑 · 居中标题</option></select></label>
      <button className="primary" disabled={busy || !version.confirmed_at || hasUnsavedChanges} onClick={()=>run(generate)}>生成 PDF 预览</button></div>
    {!version.confirmed_at && <p className="small muted">先在编辑区确认此版本，再生成正式 PDF。</p>}
    {hasUnsavedChanges && <p className="small error">有未保存修改，请先保存并确认新版。</p>}
    {error && <p role="alert" className="error">{error}</p>}
    {!!history.length && <details><summary>导出历史 · {history.length}</summary>{history.map(item=><div className="source-row" key={item.export_id}>
      <span>{item.template==='classic'?'经典':'紧凑'} · 版本 {item.version_id.slice(-8)} · 内容 {item.content_hash.slice(0,8)}</span>
      <button className="text-button" disabled={busy} onClick={()=>run(()=>open(item))}>查看已保存文件</button></div>)}</details>}
    {preview && <div><div className="section-heading"><strong>已确认版本 · {preview.item.content_hash.slice(0,12)}</strong>
      <a className="secondary" href={preview.url} download={`resume-${preview.item.version_id}-${preview.item.template}.pdf`}>下载这一版 PDF</a></div>
      <Suspense fallback={<p role="status">正在打开 PDF 预览…</p>}><PDFPreview blob={preview.blob}/></Suspense></div>}
  </section>;
}
