"""Local API launcher. Configure a private bearer token outside source control."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from job_agent.resume_workspace.api import create_resume_app
from job_agent.resume_workspace.repository import SqliteResumeRepository
from job_agent.resume_workspace.parsing import ResumeParser


def create_app():
    token = os.environ.get("JOB_AGENT_WORKSPACE_API_TOKEN", "")
    if len(token) < 32 or not token.isascii():
        raise RuntimeError("Set JOB_AGENT_WORKSPACE_API_TOKEN to a private ASCII token of at least 32 characters")
    db_path = Path(os.environ.get("JOB_AGENT_WORKSPACE_DB", "output/resume-workspace/workspace.sqlite"))
    repository = SqliteResumeRepository(db_path)

    def identity(candidate: str) -> str | None:
        # compare_digest requires same-typed ASCII inputs; invalid bearer is a 401.
        return "local-user" if candidate.isascii() and secrets.compare_digest(candidate, token) else None

    provider = None
    if os.environ.get("JOB_AGENT_WORKSPACE_ENABLE_LLM") == "1":
        from job_agent.llm.providers.deepseek_compatible import DeepSeekCompatibleProvider
        provider = DeepSeekCompatibleProvider(api_key=os.environ.get("JOB_AGENT_WORKSPACE_MODEL_KEY", ""), timeout_s=30,
            base_url="https://api.deepseek.com",model=os.environ.get("JOB_AGENT_WORKSPACE_MODEL_NAME", "deepseek-flash"),
            thinking=os.environ.get("JOB_AGENT_WORKSPACE_MODEL_THINKING", "disabled"))
    frontend = Path("frontend/dist").resolve()
    from job_agent.resume_workspace.retrieval_runtime import RetrievalRuntime
    from job_agent.resume_workspace.project_storage import persistence_from_env
    persistence=persistence_from_env(repository)
    app=create_resume_app(repository, resolve_identity=identity, parser=ResumeParser(provider),
                             project_persistence=persistence,
                             task_worker_enabled=getattr(persistence.tasks,'dispatch_mode','polling')=='polling',
                             retrieval_runtime=RetrievalRuntime.from_env(),
                             frontend_dir=frontend if (frontend / "index.html").is_file() else None)
    from contextlib import asynccontextmanager
    previous=app.router.lifespan_context
    @asynccontextmanager
    async def lifetime(application):
        try:
            async with previous(application):yield
        finally:persistence.close()
    app.router.lifespan_context=lifetime
    return app
