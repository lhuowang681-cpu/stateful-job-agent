"""Validate and inspect a saved export. This command never replays business actions."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from job_agent.resume_workspace.unified_trace import UnifiedTraceEvent


def inspect(path):
    path=Path(path)
    if path.stat().st_size>8*1024*1024:raise ValueError('trace_file_budget')
    text=path.read_text(encoding='utf-8')
    if path.suffix=='.jsonl':rows=[json.loads(line) for line in text.splitlines() if line.strip()]
    else:rows=json.loads(text)['events']
    if not 1<=len(rows)<=512:raise ValueError('trace_event_budget')
    rows=[UnifiedTraceEvent.model_validate(r).model_dump(mode='json') for r in rows]
    root=rows[0]
    if root['kind']!='run' or root['parent_span_id'] is not None:raise ValueError('trace_root_invalid')
    if [r['seq'] for r in rows]!=list(range(len(rows))):raise ValueError('trace_sequence_invalid')
    if any((r['trace_id'],r['run_id'])!=(root['trace_id'],root['run_id']) for r in rows):raise ValueError('trace_run_changed')
    if any(r['parent_span_id']!=root['span_id'] for r in rows[1:]):raise ValueError('trace_parent_invalid')
    return {'status':'valid_read_only','events':len(rows),'trace_id':root['trace_id'],
        'root_status':root['status'],'input_tokens':root['input_tokens'],'output_tokens':root['output_tokens'],'cost':root['cost'],
        'usage_basis':'root_only_children_excluded','unknown_times':sum(r['time_quality']=='unknown' for r in rows),
        'executed_actions':0,'semantic_quality':None}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('file',type=Path);a=p.parse_args()
    print(json.dumps(inspect(a.file),ensure_ascii=False))
