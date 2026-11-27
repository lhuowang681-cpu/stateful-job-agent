"""Fresh clone source fixture and inherited quality floors, no binary DB in Git."""
from pathlib import Path
import json
import pytest
from scripts.review_materialize_fixture import materialize
from job_agent.knowledge.research_contract import read_json,evaluate,check_gate

ROOT=Path(__file__).resolve().parents[1]


def test_public_dump_rebuild_preserves_retrieval_scope_and_original_positive_floors(tmp_path):
    bundle=materialize(tmp_path/'portable')
    old=read_json(ROOT/'docs/evaluation/expansion/retrieval-gate-v1.json')['payload']
    new=read_json(bundle/'portable-gate.json')['payload']
    assert new['floors']==old['floors'] and new['baseline']==old['baseline']
    assert new['dataset_hash']==old['dataset_hash'] and new['corpus_snapshot']==old['corpus_snapshot']
    run=evaluate(ROOT,bundle,tmp_path/'run',variants=['A_bm25'],repeats=1,strict_algorithm=False)
    assert check_gate(run,bundle/'portable-gate.json')['status']=='passed'
    assert run['summary']['A_bm25']['invalid_citations']==0
    with pytest.raises(FileExistsError):materialize(bundle)


def test_installed_package_declares_both_httpx_observed_versions_and_root_engine():
    import tomllib
    from packaging.requirements import Requirement
    data=tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))
    for group in ('dev','workbench'):
        requirement=next(Requirement(r) for r in data['project']['optional-dependencies'][group] if r.startswith('httpx'))
        assert all(v in requirement.specifier for v in ('0.27.2','0.28.1'))
    assert 'fit_verdict_engine*' in data['tool']['setuptools']['packages']['find']['include']
