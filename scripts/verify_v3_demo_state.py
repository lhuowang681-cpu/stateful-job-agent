"""Read-only assertions after the manual CUA flow. Synthetic local demo only."""
from pathlib import Path
from hashlib import sha256
from io import BytesIO
import json
import httpx
from pypdf import PdfReader
ROOT=Path(__file__).resolve().parents[1]


def main():
    main_headers={'Authorization':'Bearer job-agent-synthetic-demo-only-2026'}
    second={'Authorization':'Bearer job-agent-second-demo-user-2026'}
    with httpx.Client(base_url='http://127.0.0.1:8019/api/v2',headers=main_headers,trust_env=False,timeout=15) as c:
        def get(path):
            r=c.get(path);r.raise_for_status();return r.json()
        cap=get('/capabilities');assert cap['demo_only'] and not cap['llm']
        resume=next(r for r in get('/resumes') if r['title']=='V3完整演示 · PDF导入');rid=resume['resume_id']
        versions=sorted(get(f'/resumes/{rid}/versions'),key=lambda v:v['sequence']);assert len(versions)==2
        assert versions[0]['document']['projects'][0]['bullets'][0]['text'].startswith('使用 Python')
        assert versions[1]['document']['projects'][0]['bullets'][0]['text'].startswith('基于 Python')
        assert versions[1]['confirmed_at'] and versions[1]['content_hash']!=versions[0]['content_hash']
        exports=get(f'/resumes/{rid}/pdfs');assert exports and exports[0]['version_id']==versions[1]['version_id']
        raw=c.get('/pdfs/'+exports[0]['export_id']).content
        assert sha256(raw).hexdigest()==exports[0]['pdf_hash']
        reader=PdfReader(BytesIO(raw));text=''.join(p.extract_text() for p in reader.pages);assert '基于 Python' in text
        project=next(p for p in get('/projects') if p['name']=='V3连续演示源码');pid=project['project_id'];snapshot=project['current_snapshot']
        tasks=get(f'/projects/{pid}/index-tasks');assert tasks and tasks[0]['status']=='SUCCEEDED'
        assert tasks[0]['result']['files']==6 and tasks[0]['attempts']==1
        sessions=[get('/interviews/'+s['session_id']) for s in get(f'/resumes/{rid}/interviews')]
        assert {s['track'] for s in sessions}=={'job','project','weakness'}
        assert all(s['status']=='complete' and s['usage']['provider_calls']==0 for s in sessions)
        source=next(s for s in sessions if s['track']=='project')
        assert [t['tool'] for t in source['tool_trace']]==['code_search','get_symbol','find_references']
        trace_dir=ROOT/'docs/devlog/traces';trace_dir.mkdir(parents=True,exist_ok=True)
        trace={k:source[k] for k in ('track','mode','provider','model','status','revision','max_turns','tool_calls','tool_trace','messages','usage')}
        trace['scope']='real local rule-mode interactions after synthetic ZIP upload; no LLM or imported code execution'
        (trace_dir/'v3-source-interview.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2),encoding='utf-8')
        review=get('/interviews/'+source['session_id']+'/review');assert review['code_references'] and review['learning_resources']
        weak=next(s for s in sessions if s['track']=='weakness')
        weak_review=get('/interviews/'+weak['session_id']+'/review')
        assert weak_review['practice_comparison']['status']=='not_comparable'
        job=next(j for j in get('/jobs') if j['company']=='合成机会 · V3演示')
        assert job['stage']=='applied' and len(job['links'])==3
        assert {l['version_id'] for l in job['links']}=={v['version_id'] for v in versions}
        assert c.get('/interviews/'+source['session_id'],headers=second).status_code==404
        assert c.get('/tasks/'+tasks[0]['task_id'],headers=second).status_code==404
        assert c.get('/resumes',headers=second).json()==[]
        other=c.get('/projects',headers=second).json();assert len(other)==1 and other[0]['name']=='第二用户隔离样例'
        result={'scope':'read-only HTTP assertions after real manual CUA interactions; synthetic/public data only',
            'resume_versions':len(versions),'confirmed_sequence':2,'pdf_pages':len(reader.pages),'pdf_sha256':exports[0]['pdf_hash'],
            'pdf_matches_approved_version':True,'source_zip_files':6,'background_task_status':'SUCCEEDED',
            'interview_modes':sorted(s['track'] for s in sessions),'all_three_finished':True,
            'source_tool_trace':[{'tool':t['tool'],'status':t['status']} for t in source['tool_trace']],
            'review_has_public_learning_resources':True,'different_topic_comparison':'not_comparable',
            'job_stage':job['stage'],'job_version_interview_links':3,'second_user_resume_count':0,
            'second_user_project_count':1,'foreign_session_and_task_http_status':404,'model_calls':0,
            'screenshots':['f7-pdf-v2-detail.png','f7-async-index.png','f7-weakness-review.png','f7-job-version-links.png','f7-second-user.png']}
        dest=ROOT/'docs/devlog/evidence/v3/f7-demo-state.json';dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
