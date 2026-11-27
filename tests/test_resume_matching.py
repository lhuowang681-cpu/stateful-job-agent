"""Synthetic product matching tests; fixture models are never live-model scores."""
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from job_agent.evidence.projections import EvidenceProjectionService
from job_agent.llm.providers.mock import result_from_raw_output
from job_agent.llm.provider import ProviderTimeoutError
from job_agent.resume_workspace.api import create_resume_app
from job_agent.resume_workspace.contracts import SourceCreate
from job_agent.resume_workspace.match_contracts import AnalyzeRequest, DecideProposal, MatchError
from job_agent.resume_workspace.match_repository import MatchRepository
from job_agent.resume_workspace.matching import WorkbenchMatcher, VersionSourceStore, terms
from job_agent.resume_workspace.parsing import ResumeParser
from job_agent.resume_workspace.parsing_contracts import AcceptDraft, EditVersion, FieldEdit
from job_agent.resume_workspace.repository import SqliteResumeRepository, WorkspaceConflict


TEXT = '''姓名：合成同学
邮箱：never-send@example.invalid
电话：13800000000
项目经历
校园海报 | 设计 | 2024
- 使用图像工具完成校园海报。
RAG 检索平台 | 后端开发 | 2025
- 使用 Python 实现 RAG 检索接口。
- 未使用 Kubernetes 进行生产部署。
技能
SQL、Python
'''
JD = '掌握 Python。\n具备 RAG 检索实践。\n要求 Kubernetes 生产部署。\n优先了解 PostgreSQL。'
A = {'Authorization':'Bearer alice-token'}
B = {'Authorization':'Bearer bob-token'}


@pytest.fixture
def setup(tmp_path):
    repo = SqliteResumeRepository(tmp_path/'workspace.sqlite')
    source = repo.add_source('alice',SourceCreate(kind='original_resume',label='合成',text=TEXT))
    draft = repo.save_draft('alice',ResumeParser().parse(source))
    version = repo.accept_draft('alice',draft.draft_id,AcceptDraft(title='合成简历',expected_source_hash=source.content_hash,user_reviewed=True))
    return repo,version


def request(version, **kwargs):
    return AnalyzeRequest(request_key='test-key-12345678',version_id=version.version_id,
                          expected_content_hash=version.content_hash,title='合成岗位',jd_text=JD,**kwargs)


def complete(setup, req=None, matcher=None):
    repo,version=setup
    store=MatchRepository(repo); req=req or request(version)
    mid,v,execute=store.begin('alice',version.resume_id,req)
    assert execute
    payload=(matcher or WorkbenchMatcher()).analyze(mid,v,req)
    store.complete('alice',mid,payload)
    return store,store.get('alice',mid),payload


def test_local_precheck_quotes_gaps_conflict_and_C1_do_not_become_verified_support(setup):
    repo,v=setup; store,view,payload=complete(setup)
    assert len(view.rows)==4 and view.rows[0].match_status=='unverified_lead'
    assert view.rows[2].has_contradiction
    assert view.rows[3].match_status=='gap' and '不能推断' in view.rows[3].rationale
    assert view.usage.provider_calls==0
    assert EvidenceProjectionService().for_resume(payload.bundle).claims==[]
    for row in view.rows:
        assert view.jd_text[row.jd_start:row.jd_end]==row.jd_quote
        for link in row.links:
            source=repo.get_source('alice',link.fact.source.source_id)
            span=link.fact.source
            assert source.text[span.start:span.end]==link.quote
            assert link.level=='C1'
    assert {p.section for p in view.proposals}=={'projects','skills'}


def test_selected_version_excludes_deleted_raw_resume_facts_and_personal_contacts(setup):
    repo,v=setup
    edited=repo.edit_version('alice',v.resume_id,v.version_id,EditVersion(edits=[FieldEdit(path='projects.1.bullets.1',value='')]))
    _,view,_=complete((repo,edited))
    assert view.rows[2].match_status=='gap'
    store=VersionSourceStore(edited,JD)
    assert all('personal.' not in p for p in store.facts)
    assert 'never-send@example.invalid' not in '\n'.join(store.texts.values())
    assert not any('Kubernetes' in t for sid,t in store.texts.items() if sid!='jd')


def test_accept_order_preserves_inventory_sources_and_confirmation_and_is_idempotent(setup):
    repo,v=setup; store,view,_=complete(setup)
    repo.confirm_version('alice',v.resume_id,v.version_id,expected_content_hash=v.content_hash)
    p=next(p for p in view.proposals if p.section=='projects')
    req=DecideProposal(action='accept',expected_parent_version_id=v.version_id,user_reviewed=True)
    result=store.decide('alice',view.match_id,p.proposal_id,req)
    new=result.version
    assert new.sequence==2 and new.confirmed_at is None
    assert new.document.projects[0].name.text=='RAG 检索平台'
    assert sorted(f.model_dump_json() for f in new.document.facts())==sorted(f.model_dump_json() for f in v.document.facts())
    assert store.decide('alice',view.match_id,p.proposal_id,req).version.version_id==new.version_id
    assert len(repo.list_versions('alice',v.resume_id))==2
    assert repo.get_version('alice',v.resume_id,v.version_id).confirmed_at is not None


def test_multiple_proposals_form_one_checked_chain_and_rejection_creates_no_version(setup):
    repo,v=setup; store,view,_=complete(setup)
    p=next(p for p in view.proposals if p.section=='projects')
    first=store.decide('alice',view.match_id,p.proposal_id,DecideProposal(action='accept',expected_parent_version_id=v.version_id,user_reviewed=True))
    s=next(p for p in view.proposals if p.section=='skills')
    second=store.decide('alice',view.match_id,s.proposal_id,DecideProposal(action='accept',expected_parent_version_id=first.version.version_id,user_reviewed=True))
    assert second.version.sequence==3 and second.version.document.skills[0].text=='Python'
    with pytest.raises(WorkspaceConflict,match='proposal_already_decided'):
        store.decide('alice',view.match_id,s.proposal_id,DecideProposal(action='reject',expected_parent_version_id=v.version_id,user_reviewed=True))
    # A separate unchanged snapshot can reject both without touching versions.
    fresh=request(second.version).model_copy(update={'request_key':'new-analysis-key'})
    mid,ver,_=store.begin('alice',v.resume_id,fresh)
    store.complete('alice',mid,WorkbenchMatcher().analyze(mid,ver,fresh))
    assert len(repo.list_versions('alice',v.resume_id))==3


def test_reject_is_persisted_idempotently_and_cannot_later_accept(setup):
    repo,v=setup; store,view,_=complete(setup); p=view.proposals[0]
    req=DecideProposal(action='reject',expected_parent_version_id=v.version_id,user_reviewed=True)
    assert store.decide('alice',view.match_id,p.proposal_id,req).version is None
    assert store.decide('alice',view.match_id,p.proposal_id,req).match.proposals[0].decision=='rejected'
    assert len(repo.list_versions('alice',v.resume_id))==1
    with pytest.raises(WorkspaceConflict,match='proposal_already_decided'):
        store.decide('alice',view.match_id,p.proposal_id,req.model_copy(update={'action':'accept'}))


def test_intervening_edit_invalidates_accept_but_keeps_old_jd_snapshot(setup):
    repo,v=setup; store,view,_=complete(setup)
    repo.edit_version('alice',v.resume_id,v.version_id,EditVersion(edits=[FieldEdit(path='skills.0',value='SQLite')]))
    assert not store.get('alice',view.match_id).can_apply
    with pytest.raises(WorkspaceConflict,match='resume_head_changed'):
        store.decide('alice',view.match_id,view.proposals[0].proposal_id,DecideProposal(action='accept',expected_parent_version_id=v.version_id,user_reviewed=True))
    assert store.get('alice',view.match_id).jd_text==JD


def test_simultaneous_accept_produces_one_version(setup):
    repo,v=setup; store,view,_=complete(setup)
    req=DecideProposal(action='accept',expected_parent_version_id=v.version_id,user_reviewed=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:store.decide('alice',view.match_id,view.proposals[0].proposal_id,req),range(2)))
    assert results[0].version.version_id==results[1].version.version_id
    assert len(repo.list_versions('alice',v.resume_id))==2


def test_analysis_request_key_is_durable_and_changed_input_or_running_is_rejected(setup):
    repo,v=setup; store,view,_=complete(setup)
    mid,_,execute=MatchRepository(SqliteResumeRepository(repo.path)).begin('alice',v.resume_id,request(v))
    assert mid==view.match_id and not execute
    with pytest.raises(WorkspaceConflict,match='match_request_key_conflict'):
        store.begin('alice',v.resume_id,request(v).model_copy(update={'jd_text':'changed'}))
    req=request(v).model_copy(update={'request_key':'inflight-key-123'})
    running,_,_=store.begin('alice',v.resume_id,req)
    with pytest.raises(WorkspaceConflict,match='match_in_progress'):
        store.begin('alice',v.resume_id,req)
    store.fail('alice',running,'synthetic_failure')
    with pytest.raises(WorkspaceConflict,match='match_previous_failed'):
        store.begin('alice',v.resume_id,req)


def test_payload_tampering_is_detected(setup):
    repo,_=setup; store,view,_=complete(setup)
    with sqlite3.connect(repo.path) as db:
        db.execute('UPDATE rw_matches SET payload_json=? WHERE match_id=?',('{}',view.match_id))
    from job_agent.resume_workspace.repository import InvalidProvenance
    with pytest.raises(InvalidProvenance,match='match_integrity_failed'):
        store.get('alice',view.match_id)


class FixtureProvider:
    provider_name='fixture-only'
    model='not-a-real-model'
    def __init__(self,version,*,bad_source=False,level='C1',failure=False,partial=False):
        self.calls=[]; self.version=version; self.bad_source=bad_source; self.level=level; self.failure=failure; self.partial=partial
    def generate_structured(self,**kw):
        self.calls.append(kw)
        if self.failure:raise ProviderTimeoutError('private-error-never-returned')
        if kw['trace'].skill_id=='jd-analysis':
            output={'requirements':[{'text':'Python 接口开发','importance':'must','hard_gate':False,'exact_quote':'掌握 Python。','verification_signals':[]}],'warnings':[]}
        else:
            store=VersionSourceStore(self.version,JD)
            sid=next(s for s,(_,f) in store.origins.items() if f.text=='使用 Python 实现 RAG 检索接口。')
            output={'atom_results':[{'atom_id':'atom_001','links':[{'link_id':'l1','atom_id':'atom_001',
                'source_locator':{'source_id':'jd' if self.bad_source else sid,'exact_quote':'掌握 Python。' if self.bad_source else '使用 Python 实现 RAG 检索接口。'},
                'claim':'使用 Python 实现 RAG 检索接口。','support_status':'partial' if self.partial else 'supported','level':self.level,'confidence':0.8,'needs_confirmation':True}],
                'rationale':'synthetic semantic fixture'}],'warnings':[]}
        return result_from_raw_output(provider=self.provider_name,model=self.model,raw_output=json.dumps(output),output_schema=kw['output_schema'],trace=kw['trace'],latency_ms=1,input_tokens=20,output_tokens=10)


@pytest.mark.parametrize('partial',[False,True],ids=['supported-C1','partial-C1'])
def test_online_adapter_reuses_evidence_guards_but_preserves_C1_semantics_and_omits_contacts(setup,partial):
    _,v=setup; provider=FixtureProvider(v,partial=partial)
    store,view,payload=complete(setup,request(v,mode='llm',allow_external_processing=True),WorkbenchMatcher(provider))
    assert len(provider.calls)==2 and view.usage.provider_calls==2 and view.usage.input_tokens==40
    assert view.rows[0].match_status=='unverified_lead'
    assert view.rows[0].links[0].support_status==('partial' if partial else 'supported')
    assert EvidenceProjectionService().for_resume(payload.bundle).claims==[]
    assert all(not call['tools'] for call in provider.calls)
    assert all('never-send@example.invalid' not in call['user_prompt'] for call in provider.calls)
    assert all('13800000000' not in call['user_prompt'] for call in provider.calls)


@pytest.mark.parametrize('options',[{'bad_source':True},{'level':'C2'},{'level':'C3'}],ids=['JD-forbidden','C2-forbidden','C3-forbidden'])
def test_online_jd_citation_and_level_upgrades_fail_closed_with_bounded_calls(setup,options):
    repo,v=setup; provider=FixtureProvider(v,**options)
    client=TestClient(create_resume_app(repo,resolve_identity={'alice-token':'alice'}.get,matcher=WorkbenchMatcher(provider)))
    req=request(v,mode='llm',allow_external_processing=True)
    response=client.post(f'/api/v2/resumes/{v.resume_id}/matches',headers=A,json=req.model_dump())
    assert response.status_code==422 and len(provider.calls)<=4
    history=client.get(f'/api/v2/resumes/{v.resume_id}/matches',headers=A).json()
    assert history[0]['status']=='failed'
    assert client.post(f'/api/v2/resumes/{v.resume_id}/matches',headers=A,json=req.model_dump()).status_code==409
    assert len(repo.list_versions('alice',v.resume_id))==1


def test_model_timeout_is_not_retried_and_failed_key_cannot_trigger_billing_again(setup):
    repo,v=setup; provider=FixtureProvider(v,failure=True)
    client=TestClient(create_resume_app(repo,resolve_identity={'alice-token':'alice'}.get,matcher=WorkbenchMatcher(provider)))
    req=request(v,mode='llm',allow_external_processing=True)
    response=client.post(f'/api/v2/resumes/{v.resume_id}/matches',headers=A,json=req.model_dump())
    assert response.status_code==422 and response.json()['detail']=='match_model_request_failed'
    assert len(provider.calls)==1 and 'private-error' not in response.text
    assert client.post(f'/api/v2/resumes/{v.resume_id}/matches',headers=A,json=req.model_dump()).status_code==409
    assert len(provider.calls)==1


def test_http_match_history_quote_accept_reject_persistence_and_cross_user_scope(setup):
    repo,v=setup; client=TestClient(create_resume_app(repo,resolve_identity={'alice-token':'alice','bob-token':'bob'}.get))
    url=f'/api/v2/resumes/{v.resume_id}/matches'; req=request(v).model_dump()
    assert client.post(url,json=req).status_code==401
    assert client.post(url,headers=B,json=req).status_code==404
    response=client.post(url,headers=A,json=req); assert response.status_code==201
    view=response.json(); mid=view['match_id']; proposal=view['proposals'][0]
    assert client.post(url,headers=A,json=req).json()['match_id']==mid
    assert client.get(f'/api/v2/matches/{mid}',headers=B).status_code==404
    assert client.get(url,headers=B).status_code==404
    decision=f"/api/v2/matches/{mid}/proposals/{proposal['proposal_id']}/decision"
    body={'action':'accept','expected_parent_version_id':v.version_id,'user_reviewed':True}
    assert client.post(decision,headers=B,json=body).status_code==404
    assert client.post(decision,headers=A,json={**body,'new_text':'invented achievement'}).status_code==422
    accepted=client.post(decision,headers=A,json=body)
    assert accepted.status_code==200 and accepted.json()['version']['sequence']==2
    assert MatchRepository(SqliteResumeRepository(repo.path)).get('alice',mid).proposals[0].decision=='accepted'
    assert client.delete(f'/api/v2/resumes/{v.resume_id}',headers=A).status_code==204
    assert client.get(f'/api/v2/matches/{mid}',headers=A).status_code==404
    with sqlite3.connect(repo.path) as db:
        assert db.execute('SELECT COUNT(*) FROM rw_matches').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM rw_match_decisions').fetchone()[0]==0


def test_online_requires_configuration_and_consent_before_any_reservation(setup):
    repo,v=setup; client=TestClient(create_resume_app(repo,resolve_identity={'alice-token':'alice'}.get))
    url=f'/api/v2/resumes/{v.resume_id}/matches'
    req=request(v,mode='llm').model_dump()
    assert client.post(url,headers=A,json=req).json()['detail']=='external_processing_consent_required'
    assert client.post(url,headers=A,json={**req,'allow_external_processing':True}).status_code==503
    assert client.get(url,headers=A).json()==[]


@pytest.mark.parametrize('text,expected',[('JavaScript React',{'JavaScript','React'}),('C++ 与 C#',{'C++','C#'}),('PostgreSQL',{'PostgreSQL'}),('Pythonized',set())])
def test_literal_terms_respect_token_boundaries(text,expected):
    assert terms(text)==expected


def test_JD_reference_source_cannot_be_saved_as_personal_fact(setup):
    repo,v=setup; source=repo.add_source('alice',SourceCreate(kind='job_description',label='JD',text='熟练掌握 Kubernetes'))
    fact=v.document.skills[0].model_copy(update={'text':source.text,'source':v.document.skills[0].source.model_copy(update={'source_id':source.source_id,'content_hash':source.content_hash,'start':0,'end':len(source.text)})})
    bad=v.document.model_copy(update={'skills':[fact]})
    from job_agent.resume_workspace.contracts import VersionCreate
    from job_agent.resume_workspace.repository import InvalidProvenance
    with pytest.raises(InvalidProvenance,match='reference_or_jd'):
        repo.save_version('alice',v.resume_id,VersionCreate(expected_parent_version_id=v.version_id,document=bad))


def test_total_model_budget_stops_schema_repair_across_both_nodes(setup):
    repo,v=setup
    class BadSchemaProvider(FixtureProvider):
        requirements_seen=0
        mappings_seen=0
        def generate_structured(self,**kw):
            if kw['trace'].skill_id=='jd-analysis':
                self.requirements_seen+=1
                if self.requirements_seen>1:return super().generate_structured(**kw)
                self.calls.append(kw)
                return result_from_raw_output(provider=self.provider_name,model=self.model,
                    raw_output=json.dumps({'requirements':[{'text':'Python','importance':'must','hard_gate':False,'exact_quote':'not-in-JD','verification_signals':[]}],'warnings':[]}),
                    output_schema=kw['output_schema'],trace=kw['trace'],latency_ms=1,input_tokens=20,output_tokens=10)
            self.mappings_seen+=1
            if self.mappings_seen>1:
                self.bad_source=True
                return super().generate_structured(**kw)
            self.calls.append(kw)
            return result_from_raw_output(provider=self.provider_name,model=self.model,raw_output='{"atom_results":"invalid"}',
                output_schema=kw['output_schema'],trace=kw['trace'],latency_ms=1,input_tokens=20,output_tokens=10)
    provider=BadSchemaProvider(v)
    client=TestClient(create_resume_app(repo,resolve_identity={'alice-token':'alice'}.get,matcher=WorkbenchMatcher(provider)))
    response=client.post(f'/api/v2/resumes/{v.resume_id}/matches',headers=A,json=request(v,mode='llm',allow_external_processing=True).model_dump())
    assert response.status_code==422 and len(provider.calls)==4
    assert response.json()['detail']=='match_model_budget_exceeded'
    assert 'invalid' not in response.text


def test_snapshot_cannot_silently_follow_later_user_statement_and_wrong_parent_is_rejected(setup):
    repo,v=setup; store,view,_=complete(setup)
    p=view.proposals[0]
    with pytest.raises(WorkspaceConflict,match='resume_head_changed'):
        store.decide('alice',view.match_id,p.proposal_id,DecideProposal(action='accept',expected_parent_version_id='wrong-parent',user_reviewed=True))
    assert len(repo.list_versions('alice',v.resume_id))==1
    edited=repo.edit_version('alice',v.resume_id,v.version_id,EditVersion(edits=[FieldEdit(path='skills.0',value='PostgreSQL')]))
    assert store.get('alice',view.match_id).rows[3].match_status=='gap'
    later_req=request(edited).model_copy(update={'request_key':'later-request-key'})
    mid,ver,_=store.begin('alice',v.resume_id,later_req)
    store.complete('alice',mid,WorkbenchMatcher().analyze(mid,ver,later_req))
    assert store.get('alice',mid).rows[3].match_status=='unverified_lead'


def test_source_hash_tampering_invalidates_analysis_read_and_accept(setup):
    repo,v=setup; store,view,_=complete(setup)
    sid=v.document.projects[1].bullets[0].source.source_id
    with sqlite3.connect(repo.path) as db:
        db.execute('UPDATE rw_sources SET text=? WHERE source_id=?',('tampered',sid))
    from job_agent.resume_workspace.repository import InvalidProvenance
    with pytest.raises(InvalidProvenance,match='source_integrity_failed'):
        store.get('alice',view.match_id)


def test_empty_requirements_fail_without_saving_success_and_oversized_request_is_rejected(setup):
    repo,v=setup
    client=TestClient(create_resume_app(repo,resolve_identity={'alice-token':'alice'}.get))
    url=f'/api/v2/resumes/{v.resume_id}/matches'
    req=request(v).model_dump(); req['jd_text']='岗位要求\n任职要求'
    assert client.post(url,headers=A,json=req).json()['detail']=='jd_has_no_requirements'
    assert client.get(url,headers=A).json()[0]['status']=='failed'
    req['request_key']='oversized-key-123'; req['jd_text']='x'*15001
    assert client.post(url,headers=A,json=req).status_code==422


def test_accept_requires_explicit_review_without_creating_a_version(setup):
    repo,v=setup; store,view,_=complete(setup)
    client=TestClient(create_resume_app(repo,resolve_identity={'alice-token':'alice'}.get))
    url=f'/api/v2/matches/{view.match_id}/proposals/{view.proposals[0].proposal_id}/decision'
    req={'action':'accept','expected_parent_version_id':v.version_id}
    assert client.post(url,headers=A,json=req).status_code==422
    assert client.post(url,headers=A,json={**req,'user_reviewed':False}).status_code==422
    assert len(repo.list_versions('alice',v.resume_id))==1
