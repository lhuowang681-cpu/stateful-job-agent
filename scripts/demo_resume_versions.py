"""Run the M1 data/version demo using synthetic facts; no models or credentials.

Usage: python scripts/demo_resume_versions.py --output-dir output/demo-resume-m1
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from job_agent.resume_workspace.contracts import (
    PersonalInfo, ResumeCreate, ResumeDocument, ResumeFact, SourceCreate, SourceSpan, VersionCreate,
)
from job_agent.resume_workspace.repository import SqliteResumeRepository


def run_demo(output_dir: Path) -> dict:
    repository = SqliteResumeRepository(output_dir / "workspace.sqlite")
    user = "synthetic-demo-user"
    source = repository.add_source(user, SourceCreate(
        kind="original_resume", label="合成示例：不是用户的真实经历",
        text="演示同学\nPython\nFastAPI\n用 Python 编写接口回归脚本。",
    ))

    def fact(key: str, text: str) -> ResumeFact:
        start = source.text.index(text)
        return ResumeFact(fact_id=key, text=text, source=SourceSpan(
            source_id=source.source_id, content_hash=source.content_hash,
            start=start, end=start + len(text),
        ))

    document = ResumeDocument(personal=PersonalInfo(name=fact("name", "演示同学")),
                              skills=[fact("python", "Python"), fact("fastapi", "FastAPI")])
    first = repository.create_resume(user, ResumeCreate(title="合成演示简历", document=document))
    confirmed = repository.confirm_version(user, first.resume_id, first.version_id,
                                           expected_content_hash=first.content_hash)
    reordered = ResumeDocument.model_validate(document.model_dump())
    reordered.skills.reverse()
    second = repository.save_version(user, first.resume_id, VersionCreate(
        expected_parent_version_id=first.version_id, document=reordered, note="只调整技能顺序",
    ))
    restored = repository.restore_version(user, first.resume_id, first.version_id,
                                          expected_parent_version_id=second.version_id,
                                          note="恢复旧内容，保留修改历史")
    reopened = SqliteResumeRepository(repository.path)
    report = {
        "scope": "M1 structured resume/version demo; deterministic, synthetic; no LLM or product UI",
        "resume_id": first.resume_id,
        "versions": [{"sequence": version.sequence, "content_hash": version.content_hash,
                      "confirmed": version.confirmed_at is not None}
                     for version in reopened.list_versions(user, first.resume_id)],
        "checks": {
            "first_version_confirmed": confirmed.confirmed_at is not None,
            "edit_requires_new_confirmation": second.confirmed_at is None,
            "restore_requires_new_confirmation": restored.confirmed_at is None,
            "restored_content_matches_original": restored.content_hash == first.content_hash,
            "restored_has_new_version_id": restored.version_id != first.version_id,
            "history_survives_repository_reopen": len(reopened.list_versions(user, first.resume_id)) == 3,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("output/demo-resume-m1"))
    args = parser.parse_args()
    print(json.dumps(run_demo(args.output_dir), ensure_ascii=False, indent=2))
