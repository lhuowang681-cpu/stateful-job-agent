import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from job_agent.resume_workspace.rewrite import RewriteService, RewriteRoles, RewriteRequest, RewriteDecision, EditDraft, EditReview, hard_constraints
from job_agent.resume_workspace.repository import WorkspaceConflict, WorkspaceNotFound, SqliteResumeRepository
from job_agent.resume_workspace.contracts import SourceCreate,ResumeCreate,ResumeDocument,ResumeFact,SourceSpan,Project,PersonalInfo,VersionCreate


@pytest.fixture
def context(tmp_path):
    repo=SqliteResumeRepository(tmp_path/'rw.sqlite')
    s=repo.add_source('alice',SourceCreate(kind='user_statement',label='合成',text='合成同学\n项目\n使用 Python 开发 FastAPI 接口，参与本地原型测试。'))
    def f(key,text):
        n=s.text.index(text)
        return ResumeFact(fact_id=key,text=text,source=SourceSpan(source_id=s.source_id,content_hash=s.content_hash,start=n,end=n+len(text)))
    v=repo.create_resume('alice',ResumeCreate(title='合成',document=ResumeDocument(personal=PersonalInfo(name=f('n','合成同学')),projects=[Project(entry_id='p',name=f('p','项目'),bullets=[f('b',s.text.splitlines()[-1])])])))
    request=RewriteRequest(request_key='rewrite-test-001',version_id=v.version_id,expected_content_hash=v.content_hash,source_path='projects.0.bullets.0',jd_text='Python FastAPI 实习')
    return repo,v,request


def decision(state,v,action='accept'):
    return RewriteDecision(action=action,expected_parent_version_id=v.version_id,expected_draft_hash=state['drafts'][-1]['draft_hash'],user_reviewed=True)


def test_local_paraphrase_keeps_original_and_new_self_statement_separate(context):
    repo,v,request=context;service=RewriteService(repo)
    state=service.start('alice',v.resume_id,request)
    assert state['status']=='awaiting_approval' and state['usage']['provider_calls']==0
    assert state['drafts'][-1]['draft']['text'].startswith('基于 Python 实现 FastAPI')
    result=service.decide('alice',state['run_id'],decision(state,v));saved=result['version']
    original=repo.get_version('alice',v.resume_id,v.version_id)
    assert original.document.projects[0].bullets[0].text.startswith('使用 Python 开发')
    fact=saved['document']['projects'][0]['bullets'][0]
    assert fact['source']['source_id']!=state['source_fact']['source']['source_id']
    assert repo.get_source('alice',fact['source']['source_id']).kind=='user_statement'
    assert not saved['confirmed_at'] and result['rewrite']['independent_truth']=='not_verified'
    assert service.decide('alice',state['run_id'],decision(state,v))==result


@pytest.mark.parametrize('candidate',[
    '主导 Python 开发 FastAPI 生产环境接口，提升80%。',
    '使用 Python 和 Kubernetes 开发 FastAPI 接口，参与本地原型测试。',
    '使用 Python 开发 FastAPI 接口。',
])
def test_widening_scope_numbers_technologies_cannot_pass_hard_gate(candidate):
    original='使用 Python 开发 FastAPI 接口，参与本地原型测试。'
    assert hard_constraints(original,candidate)


class FeedbackRoles(RewriteRoles):
    def __init__(self):self.feedback=[]
    def invoke(self,role,source,context,jd,drafts,mode,run_id,revision):
        if role=='writer':
            if revision==1:return EditDraft(text=source+' 性能提升90%。',reason='测试故意产生扩大事实')
            self.feedback.append(drafts[-1]['review']['constraint'])
            return EditDraft(text=source.replace('使用 ','基于 ').replace(' 开发 ',' 实现 '),reason='依反馈删除虚构数字')
        return EditReview(outcome='accept',constraint='测试替身故意放行，硬门禁仍必须拦截')


def test_reviewer_feedback_actually_changes_next_draft_and_python_overrides_accept(context):
    repo,v,request=context;roles=FeedbackRoles();service=RewriteService(repo,roles=roles)
    state=service.start('alice',v.resume_id,request)
    assert len(state['drafts'])==2 and state['status']=='awaiting_approval'
    assert '数字' in roles.feedback[0]
    assert state['drafts'][0]['review']['outcome']=='revise'
    assert any(m['type']=='revision' for m in state['messages'])
    assert '90' not in state['drafts'][-1]['draft']['text']


def test_three_draft_budget_and_refusal(context):
    repo,v,request=context
    class Bad(RewriteRoles):
        def invoke(self,role,*args):
            # Distinct bad drafts exercise the 3-draft cap; identical drafts now stop earlier.
            return EditDraft(text=f'主导生产环境提升90%，第{args[-1]}稿',reason='故意错误') if role=='writer' else EditReview(outcome='accept',constraint='故意错误')
    service=RewriteService(repo,roles=Bad());state=service.start('alice',v.resume_id,request)
    assert state['status']=='needs_input' and len(state['drafts'])==3 and state['usage']['role_calls']==6
    with pytest.raises(WorkspaceConflict,match='not_approved'):service.decide('alice',state['run_id'],decision(state,v))
    assert repo.list_resumes('alice')[0].version_count==1


def test_duplicate_owner_hash_and_no_external_consent(context):
    repo,v,request=context;service=RewriteService(repo);state=service.start('alice',v.resume_id,request)
    assert service.start('alice',v.resume_id,request)==state
    with pytest.raises(WorkspaceConflict,match='key_conflict'):service.start('alice',v.resume_id,request.model_copy(update={'jd_text':'different'}))
    with pytest.raises(WorkspaceNotFound):service.get('bob',state['run_id'])
    with pytest.raises(WorkspaceConflict,match='consent'):service.start('alice',v.resume_id,request.model_copy(update={'mode':'llm','request_key':'different-key'}))
    assert service.get('alice',state['run_id'])['usage']['provider_calls']==0


def test_head_conflict_and_restart_preserve_lineage(context):
    repo,v,request=context;state=RewriteService(repo).start('alice',v.resume_id,request)
    service=RewriteService(SqliteResumeRepository(repo.path))
    repo.save_version('alice',v.resume_id,VersionCreate(expected_parent_version_id=v.version_id,document=v.document))
    with pytest.raises(WorkspaceConflict,match='head_changed'):service.decide('alice',state['run_id'],decision(state,v))
    assert service.get('alice',state['run_id'])['status']=='awaiting_approval'


def test_concurrent_accept_makes_one_version_and_deletion_cascades(context):
    repo,v,request=context;service=RewriteService(repo);state=service.start('alice',v.resume_id,request)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(service.decide,'alice',state['run_id'],decision(state,v)) for _ in range(2)]
        outcomes=[]
        for future in futures:
            try:outcomes.append(future.result())
            except WorkspaceConflict:pass
    assert outcomes and repo.list_resumes('alice')[0].version_count==2
    repo.delete_resume('alice',v.resume_id)
    with pytest.raises(WorkspaceNotFound):service.get('alice',state['run_id'])


def test_unknown_model_dispatch_not_replayed(context):
    repo,v,request=context
    class Explodes(RewriteRoles):
        def __init__(self):self.calls=0
        def invoke(self,*args):self.calls+=1;raise TimeoutError('DO_NOT_EXPOSE_TEST_SECRET')
    roles=Explodes();service=RewriteService(repo,provider=object(),roles=roles)
    request=request.model_copy(update={'mode':'llm','allow_external_processing':True})
    state=service.start('alice',v.resume_id,request)
    assert state['status']=='unknown' and state['model_inflight'] and roles.calls==1
    assert 'DO_NOT_EXPOSE' not in json.dumps(state)
    assert service.start('alice',v.resume_id,request)==state and roles.calls==1


def test_online_adapter_uses_two_schemas_no_contact_and_bounded_real_provider_interface(context):
    from job_agent.llm.providers.mock import result_from_raw_output
    repo,v,request=context
    class Provider:
        provider_name='v3-fixture';model='mock-not-LLM-quality'
        def __init__(self):self.calls=[]
        def generate_structured(self,**kw):
            self.calls.append(kw)
            data={'text':'基于 Python 实现 FastAPI 接口，参与本地原型测试。','reason':'合成改写'} if kw['output_schema'] is EditDraft else {'outcome':'accept','constraint':'合成独立审查'}
            return result_from_raw_output(provider=self.provider_name,model=self.model,raw_output=json.dumps(data),output_schema=kw['output_schema'],trace=kw['trace'],latency_ms=1,input_tokens=10,output_tokens=5)
    provider=Provider();service=RewriteService(repo,provider=provider)
    state=service.start('alice',v.resume_id,request.model_copy(update={'mode':'llm','allow_external_processing':True}))
    assert state['status']=='awaiting_approval' and len(provider.calls)==2
    assert state['usage']['input_tokens']==20 and state['usage']['output_tokens']==10
    assert all(kw['max_output_tokens']==1600 and kw['tools']==() for kw in provider.calls)
    assert all('合成同学' not in kw['user_prompt'] for kw in provider.calls)
    assert {kw['trace'].skill_id for kw in provider.calls}=={'v3-rewrite-writer','v3-rewrite-reviewer'}
