"""Restore byte-deterministic public fixtures from checked-in legacy builders.

This is reconstruction now, not evidence that any historical live run happened.
No existing files are overwritten and no gold is manually invented.
"""
import importlib.util,json,sys
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def main():
    target=ROOT/'data/eval/evidence_v2';target.mkdir(parents=True,exist_ok=True)
    record={'reconstructed_at_utc':datetime.now(timezone.utc).isoformat(),
        'historical_live_execution_proven':False,'model_calls':0,'source':'checked-in deterministic public builders',
        'items':[]}
    for filename in ('build_evidence_eval_corpus.py','build_evidence_eval_corpus_v5.py'):
        source=ROOT/'scripts'/filename;name='review_restore_'+source.stem
        spec=importlib.util.spec_from_file_location(name,source);module=importlib.util.module_from_spec(spec)
        sys.modules[name]=module;spec.loader.exec_module(module)
        artifacts=module.build_artifacts()
        for name,content in artifacts.items():
            if Path(name).name!=name:raise ValueError('builder_path_invalid')
            path=target/name
            if path.exists():
                if path.read_bytes()!=content:raise ValueError('existing_frozen_fixture_differs:'+name)
                action='identical_existing'
            else:path.write_bytes(content);action='reconstructed_from_builder'
            record['items'].append({'path':path.relative_to(ROOT).as_posix(),'sha256':sha256(content).hexdigest(),
                'builder':source.relative_to(ROOT).as_posix(),'builder_sha256':sha256(source.read_bytes()).hexdigest(),'action':action})
    output=ROOT/'docs/devlog/evidence/review-20261023/r2-public-fixture-reconstruction-v1.json'
    with output.open('x',encoding='utf-8') as f:json.dump(record,f,indent=2)
    print(json.dumps({'public_artifacts':len(record['items']),'historical_live_execution_proven':False}))


if __name__=='__main__':main()
