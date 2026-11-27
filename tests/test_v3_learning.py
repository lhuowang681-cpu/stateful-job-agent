"""Source-linked learning controls: synthetic engineering contracts, no mastery oracle."""
import json
import pytest
from test_workbench_interview import setup,A,B,JD,client,request,submit
from job_agent.resume_workspace.learning import DAY,ObservationAction
from job_agent.resume_workspace.long_term import encoded,digest
from job_agent.resume_workspace.parsing_contracts import EditVersion,FieldEdit


def completed(setup,*,retrieval=True,answers=1):
    repo,v=setup;c=client(repo)
    r=c.post(f'/api/v2/resumes/{v.resume_id}/interviews',headers=A,json=request(v,use_retrieval=retrieval).model_dump())
    assert r.status_code==201,r.text
    view=r.json()
    for _ in range(answers):view=submit(c,view,'幂等键记录执行标识。')
    r=c.post(f"/api/v2/interviews/{view['session_id']}/finish",headers=A,json={'expected_revision':view['revision']})
    assert r.status_code==200,r.text
    return c,r.json()


def materialize(c,view):
    r=c.post(f"/api/v2/interviews/{view['session_id']}/learning-observations",headers=A)
    assert r.status_code==200,r.text
    return r.json()


def action(c,obs,kind,**kw):
    body={'action':kind,'request_key':f"action-{obs['revision']}-{kind}",'expected_revision':obs['revision'],**kw}
    r=c.post(f"/api/v2/learning/observations/{obs['observation_id']}/actions",headers=A,json=body)
    assert r.status_code==200,r.text
    return r.json()


def practice(c,obs,**kw):
    body={'request_key':f"practice-{obs['revision']}",'expected_revision':obs['revision'],**kw}
    return c.post(f"/api/v2/learning/observations/{obs['observation_id']}/practice",headers=A,json=body)


def test_complete_answered_only_dedup_and_followup_focus(setup):
    repo,v=setup;c=client(repo)
    view=c.post(f'/api/v2/resumes/{v.resume_id}/interviews',headers=A,json=request(v,use_retrieval=True).model_dump()).json()
    assert c.post(f"/api/v2/interviews/{view['session_id']}/learning-observations",headers=A).status_code==409
    view=submit(c,view,'幂等键记录执行标识。');focus=view['current']['focus_id'] if 'focus_id' in view['current'] else None
    view=submit(c,view,'暂时不确定。')
    c.post(f"/api/v2/interviews/{view['session_id']}/finish",headers=A,json={'expected_revision':view['revision']})
    saved=materialize(c,view);assert saved['added']>0
    assert materialize(c,view)['added']==0
    turns={}
    for item in saved['observations']:turns.setdefault(item['payload']['question_id'],[]).append(item)
    assert len(turns)==2
    assert len(turns[view['turns'][1]['question']['question_id']])==1
    for o in saved['observations']:
        assert o['payload']['answer_hash'] and o['payload']['rubric_hash']
        assert o['independent_mastery']=='not_established'
        assert all('quote' not in r for r in o['payload']['references'])


def test_empty_finished_source_creates_no_observations(setup):
    repo,v=setup;c=client(repo)
    view=c.post(f'/api/v2/resumes/{v.resume_id}/interviews',headers=A,json=request(v).model_dump()).json()
    c.post(f"/api/v2/interviews/{view['session_id']}/finish",headers=A,json={'expected_revision':0})
    assert materialize(c,view)['observations']==[]


def test_owner_isolation_for_all_learning_routes(setup):
    c,v=completed(setup);o=materialize(c,v)['observations'][0];base='/api/v2/learning/observations/'+o['observation_id']
    assert c.get(base,headers=B).status_code==404 and c.get(base).status_code==401
    assert c.get('/api/v2/learning/observations',headers=B).json()==[]
    assert c.get('/api/v2/learning/queue',headers=B).json()['items']==[]
    assert c.post(base+'/actions',headers=B,json={'request_key':'owner-denied','expected_revision':0,'action':'confirm'}).status_code==404
    assert c.post(base+'/practice',headers=B,json={'request_key':'owner-denied','expected_revision':0}).status_code==404
    assert c.post(f"/api/v2/interviews/{v['session_id']}/learning-observations",headers=B).status_code==404
    assert c.get('/api/v2/learning/observations',headers=B,params={'resume_id':v['resume_id']}).status_code==404


def test_cas_idempotence_changed_key_body_and_correction_separation(setup):
    repo,_=setup;c,v=completed(setup);o=materialize(c,v)['observations'][0]
    before=repo.get_version('alice',v['resume_id'],v['version_id'])
    original=c.get(f"/api/v2/interviews/{v['session_id']}/review",headers=A).json()['turns']
    corrected=action(c,o,'correct',user_finding='understood',note='我已补充理解，这是我的自述。')
    assert corrected['payload']==o['payload'] and corrected['controls']['user_finding']=='understood'
    assert corrected['confidence']=='user_corrected' and corrected['revision']==1
    assert action(c,o,'correct',user_finding='understood',note='我已补充理解，这是我的自述。')['revision']==1
    for payload in [{'request_key':'action-0-correct','expected_revision':0,'action':'correct','user_finding':'unsure','note':'不同说明'},
                    {'request_key':'different-request','expected_revision':0,'action':'confirm'}]:
        assert c.post('/api/v2/learning/observations/'+o['observation_id']+'/actions',headers=A,json=payload).status_code==409
    assert c.get(f"/api/v2/interviews/{v['session_id']}/review",headers=A).json()['turns']==original
    assert repo.get_version('alice',v['resume_id'],v['version_id'])==before


def test_delete_scrubs_payload_and_notes_tombstone_blocks_resync(setup):
    repo,_=setup;c,v=completed(setup);o=materialize(c,v)['observations'][0]
    o=action(c,o,'correct',user_finding='unsure',note='合成纠正说明')
    deleted=action(c,o,'delete');assert deleted['payload'] is None and deleted['status']=='deleted'
    assert materialize(c,v)['added']==0
    assert o['observation_id'] not in [v['observation_id'] for v in c.get('/api/v2/learning/observations',headers=A).json()]
    with repo._connection() as db:
        row=db.execute('SELECT * FROM rw_learning_observations WHERE observation_id=?',(o['observation_id'],)).fetchone()
        assert row['payload'] is None and row['payload_hash'] is None and json.loads(row['controls'])=={'deleted':True}
    assert practice(c,deleted).status_code==409


def test_queue_preferences_pause_schedule_review_are_explicit_rules(setup):
    c,v=completed(setup);o=materialize(c,v)['observations'][0];base='/api/v2/learning'
    assert c.get(base+'/preferences',headers=A).json()['source']=='system_default'
    pref={'expected_revision':0,'cadence_days':7,'daily_limit':1,'paused':False,'include_new':False}
    r=c.put(base+'/preferences',headers=A,json=pref);assert r.status_code==200
    assert r.json()['source']=='explicit_user_preference'
    assert c.put(base+'/preferences',headers=A,json=pref).status_code==409
    assert c.get(base+'/queue',headers=A).json()['items']==[]
    assert practice(c,o).status_code==409
    o=action(c,o,'confirm');assert c.get(base+'/queue',headers=A).json()['items'][0]['observation_id']==o['observation_id']
    o=action(c,o,'pause');assert c.get(base+'/queue',headers=A).json()['items']==[] and practice(c,o).status_code==409
    o=action(c,o,'resume');o=action(c,o,'mark_reviewed');assert o['queue_bucket']=='reviewed'
    o=action(c,o,'schedule',review_in_days=0);assert o['queue_bucket']=='review_due'
    pref.update(expected_revision=1,paused=True);assert c.put(base+'/preferences',headers=A,json=pref).status_code==200
    assert c.get(base+'/queue',headers=A).json()['items']==[]


def test_withdrawal_hides_entire_question_and_no_longer_drives_weakness(setup):
    c,v=completed(setup);saved=materialize(c,v);o=saved['observations'][0]
    assert c.get(f"/api/v2/interviews/{v['session_id']}/review",headers=A).json()['weaknesses']
    result=action(c,o,'withdraw',note='不采用这次评价作复习依据。');assert result['status']=='withdrawn' and result['payload'] is None
    assert all(o['status']=='withdrawn' for o in c.get('/api/v2/learning/observations',headers=A).json())
    review=c.get(f"/api/v2/interviews/{v['session_id']}/review",headers=A).json()
    assert review['weaknesses']==[] and review['turns'][0]['assessment_withdrawn']
    assert materialize(c,v)['added']==0 and practice(c,o).status_code==409
    req=request(setup[1],use_retrieval=True,track='weakness',prior_session_id=v['session_id']).model_dump()
    req['request_key']='new-weakness-request'
    assert c.post(f"/api/v2/resumes/{v['resume_id']}/interviews",headers=A,json=req).status_code==409


@pytest.mark.parametrize('retrieval',[True,False])
def test_fixed_question_new_history_and_honest_comparison(setup,retrieval):
    c,v=completed(setup,retrieval=retrieval);o=action(c,materialize(c,v)['observations'][0],'confirm')
    r=practice(c,o);assert r.status_code==200,r.text
    new=r.json();assert practice(c,o).json()['session_id']==new['session_id']
    assert new['current']['prompt']==o['payload']['question'] and new['turns']==[]
    assert new['current']['question_id']!=o['payload']['question_id']
    assert not any(k in json.dumps(new) for k in ('covered_ids','missing_ids','point_assessments','rubric_hash','evaluation_note'))
    new=submit(c,new,'幂等键记录执行标识，查询回执，不盲目重放。')
    c.post(f"/api/v2/interviews/{new['session_id']}/finish",headers=A,json={'expected_revision':new['revision']})
    comparison=c.get(f"/api/v2/interviews/{new['session_id']}/review",headers=A).json()['learning_comparison']
    assert comparison['status']==('same_recorded_conditions' if retrieval else 'not_comparable')
    assert comparison['mastery_claim'] is None
    assert materialize(c,new)['added']>0


def test_corrected_source_not_used_for_comparison(setup):
    c,v=completed(setup);o=action(c,materialize(c,v)['observations'][0],'correct',user_finding='unsure',note='参考判断与我的表述有差异。')
    new=practice(c,o).json();new=submit(c,new)
    c.post(f"/api/v2/interviews/{new['session_id']}/finish",headers=A,json={'expected_revision':new['revision']})
    assert c.get(f"/api/v2/interviews/{new['session_id']}/review",headers=A).json()['learning_comparison']['status']=='not_comparable'


def test_source_hash_changed_invalidates_without_exposing_payload(setup):
    repo,_=setup;c,v=completed(setup);o=materialize(c,v)['observations'][0]
    with repo._connection(write=True) as db:
        row,state,_=c.app.state.interview_store._load(db,'alice',v['session_id']);state.turns[0].evaluation.note='新的合成评价依据'
        raw=state.model_dump_json()
        from job_agent.resume_workspace.matching import digest as state_digest
        db.execute('UPDATE rw_interviews SET state_json=?,state_hash=? WHERE session_id=?',(raw,state_digest(raw),v['session_id']))
    result=c.get('/api/v2/learning/observations/'+o['observation_id'],headers=A).json()
    assert result['status']=='invalid' and result['payload'] is None
    assert practice(c,o).status_code==409


def test_expired_requires_recheck_and_keeps_original_time(setup):
    c,v=completed(setup);o=materialize(c,v)['observations'][0];learning=c.app.state.learning
    observed=o['payload']['observed_at'];learning.clock=lambda:observed+91*DAY
    expired=c.get('/api/v2/learning/observations/'+o['observation_id'],headers=A).json()
    assert expired['status']=='expired' and practice(c,expired).status_code==409
    checked=action(c,expired,'confirm');assert checked['status']=='valid' and checked['payload']['observed_at']==observed


def test_historical_version_requires_explicit_original_version_practice(setup):
    repo,version=setup;c,v=completed(setup);o=action(c,materialize(c,v)['observations'][0],'confirm')
    repo.edit_version('alice',version.resume_id,version.version_id,EditVersion(edits=[FieldEdit(path='skills.0',value='SQL')]))
    o=c.get('/api/v2/learning/observations/'+o['observation_id'],headers=A).json()
    assert o['historical_version'] and o['queue_bucket']=='historical_version'
    assert practice(c,o).status_code==409
    r=practice(c,o,allow_historical_version=True);assert r.status_code==200,r.text
    assert r.json()['version_id']==version.version_id and not r.json()['version_is_current']


def test_consent_and_provider_gates_preserved(setup):
    c,v=completed(setup);o=action(c,materialize(c,v)['observations'][0],'confirm')
    assert practice(c,o,mode='llm').status_code==422
    assert practice(c,o,mode='llm',allow_external_processing=True).status_code==503
    assert c.get('/api/v2/learning/observations/'+o['observation_id'],headers=A).json()['revision']==o['revision']


def test_source_resume_deletion_cascades_observations_but_not_user_preferences(setup):
    repo,_=setup;c,v=completed(setup);materialize(c,v)
    c.put('/api/v2/learning/preferences',headers=A,json={'expected_revision':0,'daily_limit':2})
    assert c.delete('/api/v2/resumes/'+v['resume_id'],headers=A).status_code==204
    assert c.get('/api/v2/learning/observations',headers=A).json()==[]
    with repo._connection() as db:assert db.execute('SELECT COUNT(*) FROM rw_learning_operations').fetchone()[0]==0
    assert c.get('/api/v2/learning/preferences',headers=A).json()['daily_limit']==2


def test_corrupt_control_or_payload_fails_closed(setup):
    repo,_=setup;c,v=completed(setup);o=materialize(c,v)['observations'][0]
    with repo._connection(write=True) as db:
        altered=encoded({**o['payload'],'answer':'替换回答'})
        db.execute('UPDATE rw_learning_observations SET payload=?,payload_hash=? WHERE observation_id=?',(altered,digest(altered),o['observation_id']))
    assert c.get('/api/v2/learning/observations/'+o['observation_id'],headers=A).status_code==422


def test_single_session_does_not_become_repeated_consistent(setup):
    c,v=completed(setup);obs=materialize(c,v)['observations']
    for o in obs:action(c,o,'confirm')
    result=c.get('/api/v2/learning/observations',headers=A).json()
    assert all(o['confidence']=='single_observation' and o['consistent_distinct_sessions']==1 for o in result)


def test_distinct_confirmed_matching_sessions_remain_observations(setup):
    c,v=completed(setup);o=action(c,materialize(c,v)['observations'][0],'confirm')
    new=practice(c,o).json();new=submit(c,new,'幂等键记录执行标识。')
    c.post(f"/api/v2/interviews/{new['session_id']}/finish",headers=A,json={'expected_revision':new['revision']})
    new_o=next(x for x in materialize(c,new)['observations'] if x['payload']['point_id']==o['payload']['point_id'])
    action(c,new_o,'confirm')
    result=c.get('/api/v2/learning/observations',headers=A).json()
    pair=[v for v in result if v['observation_id'] in {o['observation_id'],new_o['observation_id']}]
    assert all(v['confidence']=='repeated_consistent_observations' and v['consistent_distinct_sessions']==2 for v in pair)
    assert all(v['independent_mastery']=='not_established' for v in pair)


def test_original_source_removed_does_not_hide_new_independent_review(setup):
    repo,_=setup;c,v=completed(setup);o=action(c,materialize(c,v)['observations'][0],'confirm')
    new=practice(c,o).json();new=submit(c,new)
    c.post(f"/api/v2/interviews/{new['session_id']}/finish",headers=A,json={'expected_revision':new['revision']})
    with repo._connection(write=True) as db:db.execute('DELETE FROM rw_interviews WHERE session_id=?',(v['session_id'],))
    r=c.get(f"/api/v2/interviews/{new['session_id']}/review",headers=A)
    assert r.status_code==200,r.text
    assert r.json()['practice_comparison'] is None
    assert r.json()['learning_comparison']['status']=='not_comparable'


def test_new_observation_time_is_answer_commit_not_session_creation(setup):
    c,v=completed(setup);o=materialize(c,v)['observations'][0]
    assert o['payload']['observation_time_source']=='answer_committed_at'


@pytest.mark.parametrize('change',[{'jd_text':'另一个岗位'}, {'prior_session_id':'other-source'}, {'project_id':'other-project','snapshot_id':'other-snapshot'},
    {'version_id':'other-version'}, {'learning_allow_historical_version':True,'learning_observation_id':None}])
def test_generic_interview_start_cannot_change_learning_scope(setup,change):
    c,v=completed(setup);o=action(c,materialize(c,v)['observations'][0],'confirm')
    req=request(setup[1],use_retrieval=True,track='weakness',prior_session_id=v['session_id'],learning_observation_id=o['observation_id']).model_dump()
    req.update(request_key='scope-changed-learning',**change)
    assert c.post(f"/api/v2/resumes/{v['resume_id']}/interviews",headers=A,json=req).status_code in (404,409,422)


def test_daily_suggestions_stop_after_review_and_reset_on_next_shanghai_day(setup):
    c,v=completed(setup);obs=materialize(c,v)['observations'];o=action(c,obs[0],'confirm')
    c.put('/api/v2/learning/preferences',headers=A,json={'expected_revision':0,'daily_limit':1})
    o=action(c,o,'mark_reviewed')
    q=c.get('/api/v2/learning/queue',headers=A).json();assert q['reviewed_today']==1 and q['items']==[] and q['remaining_today']==0
    learning=c.app.state.learning;now=learning.clock();learning.clock=lambda:now+DAY
    q=c.get('/api/v2/learning/queue',headers=A).json();assert q['reviewed_today']==0 and q['remaining_today']==1 and q['items']


def test_deleted_question_point_stays_deleted_after_source_fingerprint_changes(setup):
    repo,_=setup;c,v=completed(setup);o=materialize(c,v)['observations'][0];pid=o['payload']['point_id']
    action(c,o,'delete')
    with repo._connection(write=True) as db:
        _,state,_=c.app.state.interview_store._load(db,'alice',v['session_id']);state.turns[0].evaluation.note='模拟来源评价修订'
        raw=state.model_dump_json()
        from job_agent.resume_workspace.matching import digest as state_digest
        db.execute('UPDATE rw_interviews SET state_json=?,state_hash=? WHERE session_id=?',(raw,state_digest(raw),v['session_id']))
    saved=materialize(c,v)
    assert all(not x['payload'] or x['payload']['point_id']!=pid for x in saved['observations'])
    assert c.get('/api/v2/learning/observations/'+o['observation_id'],headers=A).json()['status']=='deleted'


def test_withdrawal_does_not_refund_daily_limit_but_payload_deletion_discards_review_time(setup):
    c,v=completed(setup);o=action(c,materialize(c,v)['observations'][0],'confirm');o=action(c,o,'mark_reviewed')
    o=action(c,o,'withdraw',note='不再采用本题评价，已花费的复核次数仍保留。')
    assert c.get('/api/v2/learning/queue',headers=A).json()['reviewed_today']==1
    action(c,o,'delete')
    assert c.get('/api/v2/learning/queue',headers=A).json()['reviewed_today']==0
