"""Real loopback checks of the PHASE-03C browser demo, never private material.

active: run after two answers but before finishing. complete: after UI finish.
Only repeats an already completed finish action in complete mode.
"""
import argparse
from datetime import datetime, UTC
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def verify(port,stage):
    base=f'http://127.0.0.1:{port}'
    def http(path,data=None):
        r=Request(base+path,data=json.dumps(data).encode() if data is not None else None,
            headers={'Authorization':'Bearer job-agent-synthetic-demo-only-2026','Content-Type':'application/json'})
        with urlopen(r,timeout=15) as res:return json.load(res)
    checks={}
    cap=http('/api/v2/capabilities')
    checks['isolated_synthetic_no_model']=cap['demo_only'] and not cap['llm']
    assert checks['isolated_synthetic_no_model'],'Refuse private/model-enabled servers.'
    resumes=http('/api/v2/resumes');assert len(resumes)==1
    rid=resumes[0]['resume_id'];versions=http(f'/api/v2/resumes/{rid}/versions')
    checks['exactly_two_versions_no_interview_writes']=len(versions)==2
    collaboration=http(f'/api/v2/resumes/{rid}/collaborations');assert len(collaboration)==1
    cv=http('/api/v2/collaborations/'+collaboration[0]['run_id']);c=cv['verification'][0]
    checks['origin_match_is_separate']=c['provenance']=='matched' and c['statement']=='exact_copy'
    checks['keyword_not_semantic_support']=c['relevance']=='keyword_lead'
    checks['accepted_not_truth_verified']=c['user_decision']=='accepted' and c['independent_truth']=='not_verified' and c['evidence_level']=='C1'
    checks['accepted_version_still_unconfirmed']=c['resume_confirmation']=='unconfirmed'
    history=http(f'/api/v2/resumes/{rid}/interviews');assert len(history)==1
    v=http('/api/v2/interviews/'+history[0]['session_id']);sid=v['session_id']
    match=http('/api/v2/matches/'+v['match_id'])
    checks['job_handoff_and_version_snapshot']=match['jd_text']==v['jd_text'] and v['version_id']==versions[0]['version_id'] and v['version_hash']==versions[0]['content_hash']
    checks['two_answers_and_four_handoffs']=v['revision']==2 and len(v['turns'])==2 and len(v['messages'])==4
    checks['feedback_actually_caused_followup']=v['turns'][1]['question']['followup'] and '超时' in v['turns'][1]['question']['prompt']
    checks['followup_then_switch']=v['messages'][1]['action']=='follow_up' and v['messages'][3]['action']=='next'
    def keys(value):
        if isinstance(value,dict):return set(value)|set().union(*(keys(v) for v in value.values()))
        if isinstance(value,list):return set().union(*(keys(v) for v in value)) if value else set()
        return set()
    checks['public_projection_hides_rubric_and_evaluation']=not keys(v).intersection({'plan','points','reference_points','evaluation','covered_ids','missing_ids','note','focus_id'})
    checks['zero_model_calls']=v['mode']=='local_demo' and v['usage']['provider_calls']==0
    if stage=='active':
        checks['active_next_topic_not_another_followup']=v['status']=='active' and not v['current']['followup']
        try:http(f'/api/v2/interviews/{sid}/review');checks['active_review_is_blocked']=False
        except HTTPError as exc:checks['active_review_is_blocked']=exc.code==409
    else:
        checks['complete_no_future_question']=v['status']=='complete' and v['current'] is None
        review=http(f'/api/v2/interviews/{sid}/review')
        checks['review_only_answered_turns']=len(review['turns'])==2 and review['turns'][0]['missing']!=[]
        checks['finish_retry_is_idempotent']=http(f'/api/v2/interviews/{sid}/finish',{'expected_revision':2})['revision']==2
    assert all(checks.values()),checks
    return {'date':datetime.now(UTC).isoformat(),'stage':stage,'url':base,'checks':checks,'session_id':sid,'resume_id':rid,
        'scope':'real loopback HTTP against synthetic browser-created data; not additional pytest or real-model quality cases'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=int,default=8016);p.add_argument('--stage',choices=['active','complete'],required=True)
    p.add_argument('--output',type=Path)
    args=p.parse_args();result=verify(args.port,args.stage)
    path=args.output or Path('docs/devlog/evidence')/f'm3c-live-{args.stage}.json'
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"{args.stage}: {sum(result['checks'].values())}/{len(result['checks'])} synthetic HTTP checks passed")
