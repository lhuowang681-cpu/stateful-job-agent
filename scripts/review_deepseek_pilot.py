"""Bounded authorized synthetic pilot using the production HTTP/role paths.

Key is read from process memory only. Never logs headers or provider error bodies.
This script has no retry path and refuses to overwrite evidence.
"""
import argparse,json,os,sys
from pathlib import Path
from time import monotonic
from urllib import request
from tempfile import TemporaryDirectory
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT),str(ROOT/'scripts')]
from job_agent.llm.providers.deepseek_compatible import DeepSeekCompatibleProvider
from job_agent.resume_workspace.execution_state import state_hash


class BoundedDeepSeek(DeepSeekCompatibleProvider):
    provider_name='deepseek'
    def __init__(self,cap=24):
        self.calls=[];self.cap=cap;self.seed=0
        super().__init__(base_url='https://api.deepseek.com',model='deepseek-flash',
            api_key=os.environ['DEEPSEEK_API_KEY'],timeout_s=60,thinking='disabled')
        self._transport=self.transport
        self.identity={'provider':'deepseek','requested_model':self.model,'thinking':'disabled','revision':'provider_managed',
            'endpoint':'https://api.deepseek.com/chat/completions','response_format':'json_object'}
    def generate_structured(self,**kw):
        before=len(self.calls)
        try:return super().generate_structured(**kw)
        finally:
            for row in self.calls[before:]:
                row['trace_context']=kw['trace'].model_dump()
                row['output_schema']=kw['output_schema'].__name__
    def transport(self,http_request,timeout):
        payload=json.loads(http_request.data)
        payload['thinking']={'type':'disabled'}
        if len(self.calls)>=self.cap:raise ValueError('pilot_call_cap')
        if len(http_request.data)>120000 or payload['max_tokens']>1600:raise ValueError('pilot_token_cap')
        row={'index':len(self.calls)+1,'dispatched':True,'prompt_hash':state_hash(payload['messages']),
            'input_chars':sum(len(m['content']) for m in payload['messages']),
            'max_output_tokens':payload['max_tokens'],'requested_model':payload['model'],'status':'unknown'}
        self.calls.append(row);started=monotonic()
        req=request.Request(http_request.full_url,data=json.dumps(payload,ensure_ascii=False).encode(),
            headers=dict(http_request.header_items()),method='POST')
        try:
            with request.urlopen(req,timeout=timeout) as response:raw=response.read()
            envelope=json.loads(raw)
            row.update(status='completed',returned_model=envelope.get('model'),usage=envelope.get('usage'),
                provider_response_id=envelope.get('id'),provider_created=envelope.get('created'),
                raw_output=envelope['choices'][0]['message'].get('content'),
                finish_reason=envelope['choices'][0].get('finish_reason'))
            row['input_tokens']=(envelope.get('usage') or {}).get('prompt_tokens')
            row['output_tokens']=(envelope.get('usage') or {}).get('completion_tokens')
            return raw
        except Exception as exc:
            row['error_type']=type(exc).__name__
            row['http_status']=getattr(exc,'code',None)
            raise
        finally:row['latency_ms']=round((monotonic()-started)*1000,2)


def learning(provider,result,save,*,launcher=False,retrieval=False):
    import httpx
    from scripts.expansion_baseline import running
    from job_agent.resume_workspace.repository import SqliteResumeRepository
    from job_agent.resume_workspace.api import create_resume_app
    from job_agent.resume_workspace.parsing import ResumeParser
    from job_agent.resume_workspace.interview_collaboration import InterviewEngine
    answers=[('correct','幂等键记录执行标识，持久化执行回执；超时后先查询回执，确认后续状态，不盲目重放。'),
        ('partial','幂等键记录执行标识，但我还不清楚如何查询执行结果。'),
        ('incorrect','幂等就是每次生成不同的请求键，超时后直接重新执行，不用保存回执。'),
        ('dont_know','这个问题我暂时不会回答。'),
        ('insufficient_evidence','源码有接口定义，但我没有运行记录，无法证明生产运行或我个人负责过部署。')]
    if retrieval:
        answers=[('correct','Checkpoint保存线程运行状态，包括当前任务和待执行动作；Store保存跨会话的业务信息，例如用户偏好。内存保存器在进程退出后会丢失，服务重启后恢复需要数据库等持久化存储。'),
            ('partial','Checkpoint保存当前线程的运行状态。我还不清楚跨会话信息和重启后的状态应该怎么保存。'),
            ('incorrect','Checkpoint就是所有用户永久共享的长期记忆，只放在内存也能在进程退出后恢复，线程运行状态不需要保存。'),
            ('dont_know','这个问题我暂时不会回答。'),
            ('insufficient_evidence','源码有接口定义，但我没有运行记录，无法证明生产运行或我个人负责过部署。')]
    with TemporaryDirectory(prefix='review-deepseek-synthetic-') as folder:
        ws=SqliteResumeRepository(Path(folder)/'state.sqlite')
        token='review-synthetic'
        if launcher:
            import job_agent.llm.providers.deepseek_compatible as module
            from job_agent.resume_workspace.main import create_app
            token='review-synthetic-launcher-token-000000000'
            values={'JOB_AGENT_WORKSPACE_API_TOKEN':token,'JOB_AGENT_WORKSPACE_DB':str(ws.path),
                'JOB_AGENT_PROJECT_BACKEND':'sqlite','JOB_AGENT_INDEX_DISPATCH':'polling',
                'JOB_AGENT_WORKSPACE_EMBEDDING':'disabled','JOB_AGENT_WORKSPACE_RERANK_PATH':'',
                'JOB_AGENT_WORKSPACE_ENABLE_LLM':'1','JOB_AGENT_WORKSPACE_MODEL_KEY':os.environ['DEEPSEEK_API_KEY'],
                'JOB_AGENT_WORKSPACE_MODEL_NAME':'deepseek-flash','JOB_AGENT_WORKSPACE_MODEL_THINKING':'disabled'}
            previous={k:os.environ.get(k) for k in values};original=module.DeepSeekCompatibleProvider
            def counted_provider(**kw):
                assert kw['api_key']==provider._api_key and kw['model']==provider.model and kw['thinking']=='disabled'
                provider.timeout_s=kw['timeout_s']
                result['launcher_configuration']={k:v for k,v in kw.items() if k!='api_key'}
                result['launcher_instrumentation']='same production provider with counted transport; no mocked model output'
                return provider
            try:
                os.environ.update(values);module.DeepSeekCompatibleProvider=counted_provider;app=create_app()
            finally:
                module.DeepSeekCompatibleProvider=original
                for k,v in previous.items():
                    if v is None:os.environ.pop(k,None)
                    else:os.environ[k]=v
        else:
            app=create_resume_app(ws,resolve_identity={token:'alice'}.get,parser=ResumeParser(provider),
                task_worker_enabled=False,demo_only=True)
        with running(app) as url,httpx.Client(base_url=url,headers={'Authorization':'Bearer '+token},timeout=150) as c:
            def call(method,path,expected=200,**kw):
                r=c.request(method,'/api/v2'+path,**kw)
                if r.status_code!=expected:
                    result['failed_http']={'method':method,'path':path,'status':r.status_code,'body':r.text[:500]};save()
                    raise RuntimeError('pilot_http_failed')
                return r.json()
            source=call('POST','/sources',201,json={'kind':'original_resume','label':'CC0 authored synthetic',
                'text':'姓名：合成同学\n项目经历\n原型 | 开发 | 2025\n- 使用 Python 开发本地原型接口。'})
            draft=call('POST',f"/sources/{source['source_id']}/parse",201,json={'mode':'local_rules'})
            v=call('POST',f"/drafts/{draft['draft_id']}/accept",201,json={'title':'Synthetic',
                'expected_source_hash':source['content_hash'],'user_reviewed':True})
            for category,text in answers:
                row={'category':category,'answer':text,'status':'running'};result['learning'].append(row);save()
                view=call('POST',f"/resumes/{v['resume_id']}/interviews",201,json={'request_key':str(uuid4()),
                    'version_id':v['version_id'],'expected_content_hash':v['content_hash'],
                    'jd_text':'Checkpoint 线程状态与跨会话记忆' if retrieval else 'Checkpoint 恢复 幂等',
                    'mode':'llm','max_turns':2,'use_retrieval':retrieval,'allow_external_processing':True})
                if retrieval:
                    assert any(r['source_id']=='question-checkpoint' for r in view['current']['references']), 'unexpected_fixed_question_source'
                    row['fixed_question_source_id']='question-checkpoint'
                sid=view['session_id'];path='/interviews/'+sid
                view=call('POST',path+'/answers',json={'request_key':str(uuid4()),'question_id':view['current']['question_id'],
                    'expected_revision':0,'answer':text,'allow_external_processing':True})
                row['answer_view']=view
                with ws._connection() as db:
                    row['synthetic_state']=json.loads(db.execute('SELECT state_json FROM rw_interviews WHERE session_id=?',(sid,)).fetchone()[0])
                if view['status']=='failed':row['status']='failed';save();continue
                call('POST',path+'/finish',json={'expected_revision':view['revision']})
                observations=call('POST',path+'/learning-observations')
                row['observations']=observations;row['status']='source_observation_created';save()
                if category!='correct':continue
                o=observations['observations'][0]
                def act(o,action,**kw):return call('POST','/learning/observations/'+o['observation_id']+'/actions',json={
                    'request_key':str(uuid4()),'expected_revision':o['revision'],'action':action,**kw})
                o=act(o,'confirm');o=act(o,'correct',user_finding='unsure',note='合成用户纠正，不作为已掌握。')
                o=act(o,'mark_reviewed');o=act(o,'schedule',review_in_days=0)
                row['queue']=call('GET','/learning/queue')
                practice=call('POST','/learning/observations/'+o['observation_id']+'/practice',json={'request_key':str(uuid4()),
                    'expected_revision':o['revision'],'mode':'llm','allow_external_processing':True})
                row['practice_initial']=practice
                assert practice['turns']==[] and practice['current']['prompt']==o['payload']['question']
                practice=call('POST','/interviews/'+practice['session_id']+'/answers',json={'request_key':str(uuid4()),
                    'question_id':practice['current']['question_id'],'expected_revision':0,'answer':text,'allow_external_processing':True})
                row['practice_answer']=practice
                if practice['status']=='failed':row['status']='practice_failed';save();continue
                call('POST','/interviews/'+practice['session_id']+'/finish',json={'expected_revision':practice['revision']})
                row['practice_observations']=call('POST','/interviews/'+practice['session_id']+'/learning-observations')
                row['status']='complete_http_learning_loop';save()


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--mode',choices=['rewrite','learning','launcher-learning'],required=True)
    p.add_argument('--retrieval',action='store_true',help='Bind the initial session to the actual project-authored public question reference')
    args=p.parse_args()
    if args.output.exists():raise ValueError('refuse_overwrite')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    provider=BoundedDeepSeek()
    result={'version':'review-deepseek-pilot-1','data':'CC0 AI-authored synthetic only','mode':args.mode,
        'model':provider.identity,'call_cap':provider.cap,'output_token_cap_per_call':1600,'auto_retries':0,
        'human_quality':None,'billing_amount':None,'retrieval_enabled':args.retrieval,'learning':[],'rows':[],'status':'running'}
    def save():
        result['calls']=provider.calls
        result['source_hash']=state_hash({str(p.relative_to(ROOT)):state_hash(p.read_bytes().hex())
            for p in (ROOT/'src').rglob('*.py')})
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        if args.mode in ('learning','launcher-learning'):learning(provider,result,save,launcher=args.mode=='launcher-learning',retrieval=args.retrieval)
        else:
            from scripts.expansion_collaboration_eval import execute,CASES
            deadline=monotonic()+900
            pilot_cases=[
                ('pilot-verbose-python','我参与了本地课程原型开发。我使用 Python 开发接口。','Python 实习；去掉重复的第一人称，使表达紧凑；保留本地、课程、原型、参与范围。'),
                ('pilot-verbose-receipt','我参与了本地原型测试。我使用 Python 开发回执查询接口。','Python 实习；合并重复主语，表达简洁；保留所有范围。'),
                *CASES[1:3]]
            CASES.extend(pilot_cases[:2])
            result['pilot_cases']=[{'id':k,'source':s,'jd':j} for k,s,j in pilot_cases]
            for key,source,jd in pilot_cases:
                result['rows'].append({})
                def progress(row):result['rows'][-1]=row;save()
                execute(provider,{'id':key,'source':source,'jd':jd},'writer_reviewer',0,progress,deadline)
        result['status']='completed'
    except Exception as exc:result.update(status='failed',error_type=type(exc).__name__)
    finally:save()
    print(json.dumps({'status':result['status'],'calls':len(provider.calls),
        'outcomes':[r.get('status') for r in result['learning']+result['rows']]}))


if __name__=='__main__':main()
