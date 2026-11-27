"""Rebuild public synthetic research DBs from audited SQL; preserve old artifacts."""
import argparse,copy,json,shutil,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from job_agent.knowledge.research_contract import read_json,write_new,file_hash,fingerprint,inspect_bundle


def materialize(output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    source=ROOT/'tests/fixtures/expansion_research/index-v1'
    portability=read_json(source/'portable-source-v2.json')
    sealed=read_json(source/'manifest.json')
    if file_hash(source/'manifest.json')!=portability['original_manifest_sha256']:raise ValueError('portable_manifest_changed')
    for split in ('dev','test'):
        dump=source/(split+'.sql')
        if file_hash(dump)!=portability['dumps'][split]['sha256']:raise ValueError('portable_dump_changed')
        with sqlite3.connect(output/(split+'.sqlite')) as db:db.executescript(dump.read_text(encoding='utf-8'))
    for name in ('dataset.json','dev-public-vectors.json','test-public-vectors.json'):
        shutil.copyfile(source/name,output/name)
    payload=copy.deepcopy(sealed['payload'])
    payload['portability']={'version':'portable-research-2','source_sha256':file_hash(source/'portable-source-v2.json'),
        'original_manifest_sha256':portability['original_manifest_sha256'],'physical_db_hashes_rebuilt':True}
    payload['artifacts']={name:file_hash(output/name) for name in payload['artifacts']}
    write_new(output/'manifest.json',{'payload':payload,'sha256':fingerprint(payload)})
    # Full product audit checks scope, source hashes, symbols/chunks/edges and vectors.
    inspect_bundle(ROOT,output,strict_algorithm=False)
    original=read_json(ROOT/'docs/evaluation/expansion/retrieval-gate-v1.json')
    if original['sha256']!=fingerprint(original['payload']):raise ValueError('original_gate_changed')
    gate=copy.deepcopy(original['payload'])
    gate['manifest_sha256']=file_hash(output/'manifest.json')
    gate['portability']={'original_gate_sha256':fingerprint(original['payload']),
        'thresholds_changed':False,'only_manifest_binding_changed':True}
    write_new(output/'portable-gate.json',{'payload':gate,'sha256':fingerprint(gate)})
    return output


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    print(materialize(args.output))
