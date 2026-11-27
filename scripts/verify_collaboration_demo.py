"""Check the browser-created synthetic two-version M3B demo over real HTTP.

Run after following PHASE-03B's demo steps. Refuses non-demo/model-enabled
servers. Only write is repeating an already accepted decision to test idempotency.
Never use a private token or material with this script.
"""
import argparse
from datetime import datetime, UTC
import hashlib
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen


def verify(port=8015):
    base=f'http://127.0.0.1:{port}'
    def http(path,body=None):
        req=Request(base+path,data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization':'Bearer job-agent-synthetic-demo-only-2026','Content-Type':'application/json'})
        with urlopen(req,timeout=15) as response:return json.load(response)
    checks={}
    checks['health_ok']=http('/health/live')['status']=='ok'
    cap=http('/api/v2/capabilities')
    checks['isolated_demo_no_model']=cap['demo_only'] and not cap['llm']
    assert checks['isolated_demo_no_model'],'Refuse a private or model-enabled server.'
    resumes=http('/api/v2/resumes')
    assert len(resumes)==1,'Use a fresh synthetic demo with one browser-created resume.'
    rid=resumes[0]['resume_id']; versions=http(f'/api/v2/resumes/{rid}/versions')
    checks['browser_accept_exactly_two_versions']=len(versions)==2
    latest,original=versions
    history=http(f'/api/v2/resumes/{rid}/collaborations')
    checks['history_persisted']=len(history)==1
    view=http('/api/v2/collaborations/'+history[0]['run_id']); state=view['state']
    drafts=state['drafts']; old,new=drafts
    checks['one_feedback_driven_revision']=state['revision']==2 and old['feedback']['items'][0]['issue_code']=='unrelated'
    checks['selection_actually_changed']=old['draft']['proposals'][0]['text']!=new['draft']['proposals'][0]['text']
    checks['trace_has_six_actual_handoffs']=len(state['messages'])==6 and [m['kind'] for m in state['messages']]==[
        'review_request','review_feedback','revision_request','review_request','review_feedback','user_approval']
    checks['no_provider_call']=state['mode']=='local_demo' and state['usage']['provider_calls']==0
    checks['version_and_hash_pinned']=state['version_id']==original['version_id'] and state['version_hash']==original['content_hash']
    checks['checkpoint_saved']=view['checkpoint_revision']>=6 and not view['resumable']
    p=new['draft']['proposals'][0]; fact=view['source_facts'][p['source_path']]; span=fact['source']
    source=http('/api/v2/sources/'+span['source_id'])
    checks['owner_source_hash_span_and_complete_quote']=source['kind'] in ('original_resume','user_statement') and hashlib.sha256(source['text'].encode()).hexdigest()==span['content_hash'] and source['text'][span['start']:span['end']]==fact['text']==p['text']
    copied=latest['document']['summary'][0]
    checks['summary_same_source_new_identity']=copied['text']==fact['text'] and copied['source']==span and copied['fact_id']!=fact['fact_id']
    before={k:v for k,v in original['document'].items() if k!='summary'}
    after={k:v for k,v in latest['document'].items() if k!='summary'}
    checks['other_sections_identical']=before==after
    checks['latest_unconfirmed']=latest['confirmed_at'] is None
    checks['human_decision_persisted']=view['decisions'][p['proposal_id']]=='accepted' and view['accepted_version_ids'][p['proposal_id']]==latest['version_id']
    result=http(f"/api/v2/collaborations/{state['run_id']}/proposals/{p['proposal_id']}/decision",{
        'action':'accept','expected_parent_version_id':original['version_id'],'draft_revision':new['revision'],
        'draft_hash':new['draft_hash'],'user_reviewed':True})
    checks['retry_same_version_no_duplicate']=result['version']['version_id']==latest['version_id'] and len(http(f'/api/v2/resumes/{rid}/versions'))==2
    with urlopen(base+'/',timeout=15) as response:html=response.read().decode()
    js=re.search(r'src="([^"]+\.js)"',html).group(1)
    local=Path(__file__).resolve().parents[1]/'frontend/dist'/js.lstrip('/')
    with urlopen(base+js,timeout=15) as response:served=response.read()
    checks['current_frontend_build_served']=hashlib.sha256(served).digest()==hashlib.sha256(local.read_bytes()).digest()
    assert all(checks.values()),checks
    return {'date':datetime.now(UTC).isoformat(),'url':base,'scope':'standalone real HTTP of synthetic browser-created data; no real model, no additional pytest cases',
        'checks':checks,'resume_id':rid,'run_id':state['run_id'],'provider_calls':state['usage']['provider_calls']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8015)
    parser.add_argument('--output',type=Path,default=Path('docs/devlog/evidence/m3b-live-http.json'))
    args=parser.parse_args()
    result=verify(args.port)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"{sum(result['checks'].values())}/{len(result['checks'])} synthetic HTTP checks passed; model calls: {result['provider_calls']}")
