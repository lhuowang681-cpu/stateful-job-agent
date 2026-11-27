from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from job_agent.interview.copilot_contracts import InterviewMode, InterviewRoundType
from job_agent.interview.copilot_repository import InterviewCopilotRepository
from job_agent.interview.copilot_service import ApplicationCopilotService
from job_agent.resume.contracts import (
    ApplicationResumeLink,
    Resume,
    ResumeItem,
    ResumeSection,
    ResumeSourceType,
    ResumeVersion,
    ResumeVersionStatus,
    SectionKind,
)
from job_agent.resume.repository import ResumeRepository
from job_agent.schemas import ApplicationRecord, ApplicationStatus, TrackerEvent
from job_agent.tools.application_tracker import ApplicationTrackerStore


def build_demo(output: Path) -> dict:
    now = datetime.now(UTC)
    output.parent.mkdir(parents=True, exist_ok=True)
    runtime_root = Path("output")
    runtime_root.mkdir(parents=True, exist_ok=True)
    state_root = Path(tempfile.mkdtemp(prefix="r15-demo-", dir=runtime_root))
    tracker = ApplicationTrackerStore(state_root / "application-tracker.json", now=lambda: now)
    tracker.add_application(
        user_id="demo-candidate",
        user_confirmed=True,
        application=ApplicationRecord(
            id="app-demo",
            job_id="job-agent-engineer",
            company="Example AI",
            title="Agent Engineer",
            city="杭州",
            source="referral",
            current_state=ApplicationStatus.FIRST_INTERVIEW,
            submitted_at=(now - timedelta(days=3)).isoformat(),
            state_history=[
                TrackerEvent(
                    state=ApplicationStatus.FIRST_INTERVIEW,
                    timestamp=now.isoformat(),
                    notes="First interview invitation",
                )
            ],
        ),
    )
    resumes = ResumeRepository.open(state_root)
    resumes.save_resume(Resume(resume_id="resume-demo", name="Redacted Candidate", created_at=now))
    version = ResumeVersion(
        resume_version_id="resume-demo-v1",
        resume_id="resume-demo",
        version=1,
        target_job_id="job-agent-engineer",
        target_jd_snapshot_id="jd-demo-v1",
        target_jd_version=1,
        analysis_snapshot_id="analysis-demo-v1",
        created_at=now,
        source_type=ResumeSourceType.PLAIN_TEXT,
        status=ResumeVersionStatus.BASE,
        content_hash="d" * 64,
        raw_text="Built a governed Agent Runtime with deterministic evidence evaluation.",
        sections=[
            ResumeSection(
                section_id="project",
                kind=SectionKind.PROJECT,
                title="Projects",
                order=0,
                items=[
                    ResumeItem(
                        item_id="job-agent",
                        section=SectionKind.PROJECT,
                        title="Job Agent",
                        original_text="Built a governed Agent Runtime.",
                        current_text="Built a governed Agent Runtime.",
                        order=0,
                    )
                ],
            )
        ],
    )
    resumes.save_version(version)
    resumes.link_application(
        ApplicationResumeLink(
            application_id="app-demo",
            job_id="job-agent-engineer",
            resume_version_id=version.resume_version_id,
            linked_at=now,
        )
    )
    repository = InterviewCopilotRepository.open(state_root)
    service = ApplicationCopilotService(
        repository=repository,
        tracker_store=tracker,
        resume_repository=resumes,
        user_id="demo-candidate",
        now=lambda: now,
    )
    service.bind_resume("app-demo", resume_version_id=version.resume_version_id, action_id="demo-bind")
    round_value = service.create_round(
        "app-demo",
        action_id="demo-round",
        round_type=InterviewRoundType.TECHNICAL,
        scheduled_at=now + timedelta(days=5),
    )
    prep = service.create_prep(
        application_id="app-demo",
        round_id=round_value.round_id,
        action_id="demo-prep",
        jd_snapshot_id="jd-demo-v1",
        jd_version=1,
        analysis_snapshot_id="analysis-demo-v1",
        requirements=[
            {"requirement_id": "req-agent", "text": "Agent Runtime governance", "strength": True},
            {"requirement_id": "req-k8s", "text": "Kubernetes production experience", "gap": True},
        ],
    )
    session = service.start_mock(
        prep.prep_version_id,
        action_id="demo-session",
        mode=InterviewMode.PROJECT_DEEP_DIVE,
    )
    question = repository.get_question(session.question_ids[0])
    turn = service.submit_answer(
        session.session_id,
        question_id=question.question_id,
        answer="我在生产环境部署了 Kubernetes，并把吞吐提升了 80%。",
        action_id="demo-answer",
    )
    completed = service.complete_session(session.session_id, action_id="demo-complete")
    repository.close()
    repository = InterviewCopilotRepository.open(state_root)
    recovered = repository.get_session(session.session_id)
    review = ApplicationCopilotService(
        repository=repository,
        tracker_store=tracker,
        resume_repository=resumes,
        user_id="demo-candidate",
        now=lambda: now,
    ).review_queue("app-demo")
    result = {
        "flow": ["Job", "Application", "ResumeVersion", "First Interview", "Prep", "Mock", "Feedback", "Weakness", "Restart", "Review"],
        "application": {"application_id": "app-demo", "job_id": "job-agent-engineer", "stage": "first_interview", "resume_version_id": version.resume_version_id},
        "round": round_value.model_dump(mode="json"),
        "prep": {"prep_version_id": prep.prep_version_id, "jd_snapshot_id": prep.jd_snapshot_id, "analysis_snapshot_id": prep.analysis_snapshot_id, "resume_version_id": prep.resume_version_id},
        "mock": {"session_id": completed.session_id, "status": completed.status.value, "question": question.prompt, "answer": turn.user_answer},
        "feedback": turn.evaluation.model_dump(mode="json"),
        "follow_up": turn.follow_up.model_dump(mode="json") if turn.follow_up else None,
        "restart": {"recovered": recovered.session_id == session.session_id, "turns": len(recovered.turns), "summary": recovered.summary},
        "review_queue": [item.model_dump(mode="json") for item in review],
        "token_usage": {
            "prep": prep.token_usage,
            "question": {
                key: value
                for key, value in completed.token_usage.items()
                if key.startswith("question_")
            },
            "evaluation": {
                key: value
                for key, value in completed.token_usage.items()
                if key.startswith("evaluation_") or key.startswith("follow_up_")
            },
            "session": completed.token_usage,
        },
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    repository.close()
    resumes.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/r15/demo.json"))
    args = parser.parse_args()
    result = build_demo(args.output)
    print(json.dumps({"artifact": str(args.output), "session": result["mock"]["session_id"], "recovered": result["restart"]["recovered"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
