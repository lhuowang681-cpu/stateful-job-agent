"""Small raw-writer prompt ablation. Product gates are never disabled."""
from pathlib import Path
from time import monotonic
import argparse,json,sys
from hashlib import sha256
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from expansion_collaboration_eval import dataset
from job_agent.resume_workspace.rewrite import EditDraft
from job_agent.resume_workspace.claim_audit import audit_claims
from job_agent.resume_workspace.execution_state import state_hash
from job_agent.llm.provider import TraceContext


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model-path',required=True);parser.add_argument('--device',default='cuda:1')
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.output.exists():raise ValueError('refuse_overwrite_ablation')
    from job_agent.llm.providers.local_text import OfflineTextProvider
    started=monotonic();provider=OfflineTextProvider(args.model_path,device=args.device,capture_synthetic_outputs=True)
    data=dataset();result={'data_hash':state_hash(data),'selected_cases':['new-success','new-throughput','jd-technology'],
        'scope':'offline_raw_writer_grounding_instruction_only','production_gates_disabled':False,'model':provider.identity,
        'human_semantic_quality':None,'rows':[]}
    for case in data['cases']:
        if case['id'] not in result['selected_cases']:continue
        for enabled in (False,True):
            prefix='Write one concise resume bullet matching the JD. Return JSON with text, reason, claims; claim items only text, source_quote, status, reason. '
            if enabled:prefix+='Use ONLY source C1 facts. JD is not personal evidence. Preserve scope and negation; no new figures, technologies, roles or outcomes. Unsupported changes must keep original. '
            system=prefix+'\nOutput schema:\n'+json.dumps(EditDraft.model_json_schema(),ensure_ascii=False)
            user=json.dumps({'source':case['source'],'jd':case['jd']},ensure_ascii=False)
            provider.seed=42
            response=provider.generate_structured(system_prompt=system,user_prompt=user,output_schema=EditDraft,tools=(),temperature=.2,max_output_tokens=512,
                trace=TraceContext(session_id='s4-ablation',run_id='s4-ablation-'+case['id']+str(enabled),node_id='writer',
                    skill_id='s4-raw-writer-ablation',skill_version='1',prompt_version='s4-ablation-1'))
            row={'case_id':case['id'],'grounding_instruction':enabled,'schema_valid':response.schema_valid,'error_code':response.error_code,
                'input_tokens':response.input_tokens,'output_tokens':response.output_tokens,'raw_output':response.raw_output}
            if response.schema_valid:
                draft=EditDraft.model_validate(response.parsed_output);row['draft']=draft.model_dump()
                row['audit']=audit_claims(case['source'],draft.text,reviews=draft.claims,source_id=case['id']).model_dump(mode='json')
            result['rows'].append(row)
    result['provider_history']=[dict(c) for c in provider.calls];result['total_ms']=round((monotonic()-started)*1000,2)
    result['source_identity']=sha256(json.dumps({p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest()
        for base in ('src','tests','scripts') for p in (ROOT/base).rglob('*.py') if '__pycache__' not in p.parts},sort_keys=True).encode()).hexdigest()
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'rows':len(result['rows']),'calls':len(provider.calls),'output':str(args.output)}))


if __name__=='__main__':main()
