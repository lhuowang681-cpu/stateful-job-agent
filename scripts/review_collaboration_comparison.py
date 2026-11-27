"""Frozen synthetic comparison: one measured first draft shared by three paths.

Network dispatch is counted once globally. Each path's usage attributes that
same first call once; do not sum path-attributed usage into the actual bill.
"""
import argparse,json,sys
from pathlib import Path
from time import monotonic
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from scripts.review_deepseek_pilot import BoundedDeepSeek
from scripts.expansion_collaboration_eval import execute,CASES
from job_agent.resume_workspace.execution_state import state_hash


class SharedFirstProvider:
    provider_name='deepseek';model='deepseek-flash'
    def __init__(self,base,first,first_call):self.base=base;self.first=first;self.first_call=first_call;self.calls=[];self.used=False
    def generate_structured(self,**kw):
        if not self.used:
            self.used=True
            if kw['output_schema'].__name__!='EditDraft':raise ValueError('shared_first_must_be_writer')
            self.calls.append({**self.first_call,'dispatched':False,'reused_shared_first':True,
                'usage_accounting':'attributed_shared_cost_not_new_dispatch'})
            return self.first
        before=len(self.base.calls)
        try:return self.base.generate_structured(**kw)
        finally:self.calls.extend(self.base.calls[before:])


class CapturedProvider(BoundedDeepSeek):
    def generate_structured(self,**kw):
        self.last_result=super().generate_structured(**kw)
        return self.last_result


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if args.output.exists():raise ValueError('refuse_overwrite_comparison')
    data_path=ROOT/'docs/evaluation/expansion/review-collaboration-frozen-v2.json'
    data=json.loads(data_path.read_text(encoding='utf-8'))
    if len(data['cases'])!=10 or data['repeats']!=3:raise ValueError('frozen_case_count')
    provider=CapturedProvider(cap=180);deadline=monotonic()+2400
    result={'version':'review-comparison-2','dataset_hash':state_hash(data),'model':provider.identity,
        'source_hash':state_hash({p.relative_to(ROOT).as_posix():state_hash(p.read_bytes().hex()) for p in (ROOT/'src').rglob('*.py')}),
        'first_draft_policy':'one_real_first_draft_shared_across_paths_per_case_repeat',
        'path_call_budgets':{'writer_once':1,'self_revision':6,'writer_reviewer':6},
        'actual_dispatch_cap':180,'actual_usage_token_stop':200000,'output_token_cap_per_call':1600,
        'human_usefulness':None,'semantic_truth':None,'billing_amount':None,'rows':[],'status':'running'}
    def save():
        result['actual_calls']=provider.calls
        result['actual_dispatched_calls']=len(provider.calls)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        temp=args.output.with_suffix('.tmp');temp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(args.output)
    try:
        CASES.extend((c['id'],c['source'],c['jd']) for c in data['cases'])
        for repeat in range(3):
            for case in data['cases']:
                if monotonic()>=deadline or sum((c.get('usage') or {}).get('total_tokens',0) for c in provider.calls)>=200000:
                    raise ValueError('experiment_budget_exhausted')
                result['rows'].append({})
                def progress(row):result['rows'][-1]=row;save()
                before=len(provider.calls)
                common=execute(provider,case,'writer_once',repeat,progress,deadline)
                if len(provider.calls)!=before+1 or not hasattr(provider,'last_result') or not provider.last_result.schema_valid:
                    raise ValueError('first_draft_not_usable_for_comparison')
                first=provider.last_result;first_call=dict(provider.calls[-1]);first_hash=state_hash(first.raw_output)
                common['shared_first_output_hash']=first_hash;save()
                for variant in ('self_revision','writer_reviewer'):
                    result['rows'].append({})
                    wrapped=SharedFirstProvider(provider,first,first_call)
                    row=execute(wrapped,case,variant,repeat,progress,deadline)
                    row['shared_first_output_hash']=first_hash
                    row['actual_new_dispatches']=sum(c.get('dispatched',False) for c in row['calls'])
                    row['usage_accounting']='includes_attributed_shared_first_once; global actual_calls is billing denominator'
                    save()
        result['status']='completed'
    except Exception as exc:result.update(status='failed',error_type=type(exc).__name__)
    finally:save()
    print(json.dumps({'status':result['status'],'rows':len(result['rows']),'actual_calls':len(provider.calls)}))


if __name__=='__main__':main()
