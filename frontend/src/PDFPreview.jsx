import React, {useEffect, useRef, useState} from 'react';
import {getDocument, GlobalWorkerOptions} from 'pdfjs-dist';
import workerURL from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

GlobalWorkerOptions.workerSrc=workerURL;

export default function PDFPreview({blob}) {
  const canvas=useRef(null),[pdf,setPDF]=useState(null),[page,setPage]=useState(1),[error,setError]=useState('');
  useEffect(()=>{
    let active=true,task;
    setPDF(null);setPage(1);setError('');
    blob.arrayBuffer().then(data=>{
      if(!active)return;
      task=getDocument({data:new Uint8Array(data),isEvalSupported:false,useSystemFonts:false,useWasm:false,disableAutoFetch:true});
      return task.promise.then(document=>{if(active)setPDF(document);});
    }).catch(()=>{if(active)setError('预览加载失败，仍可下载文件后打开。');});
    return()=>{active=false;if(task)task.destroy();};
  },[blob]);
  useEffect(()=>{
    if(!pdf)return;
    let active=true,task;
    pdf.getPage(page).then(p=>{
      if(!active||!canvas.current)return;
      const scale=Math.min(1.5,Math.max(0.7,(canvas.current.parentElement.clientWidth-24)/p.getViewport({scale:1}).width));
      const viewport=p.getViewport({scale});const element=canvas.current;
      element.height=viewport.height;element.width=viewport.width;
      task=p.render({canvasContext:element.getContext('2d'),viewport});
      return task.promise;
    }).catch(e=>{if(active&&e?.name!=='RenderingCancelledException')setError('这一页无法显示，请下载检查。');});
    return()=>{active=false;task?.cancel();};
  },[pdf,page]);
  return <div className="pdf-viewer" aria-label="简历 PDF 预览">
    {pdf&&<div className="button-row"><button className="text-button" disabled={page<=1} onClick={()=>setPage(p=>p-1)}>上一页</button>
      <span role="status">第 {page} / {pdf.numPages} 页</span><button className="text-button" disabled={page>=pdf.numPages} onClick={()=>setPage(p=>p+1)}>下一页</button></div>}
    {!pdf&&!error&&<p role="status">正在载入这一版 PDF…</p>}
    {error&&<p role="alert" className="error">{error}</p>}
    <canvas ref={canvas} aria-label={`PDF第${page}页`} role="img"/>
    <p className="small muted">页面预览来自已保存的 PDF 文件；下载后可选取和复制文字。</p>
  </div>;
}
