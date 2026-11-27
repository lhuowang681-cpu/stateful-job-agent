from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from job_agent.resume_workspace.contracts import (
    ConfirmVersion, RestoreVersion, ResumeCreate, ResumeSummary, SourceCreate,
    SourceRecord, SourceSummary, VersionCreate, VersionRecord,
)
from job_agent.resume_workspace.repository import (
    InvalidProvenance, SqliteResumeRepository, WorkspaceConflict, WorkspaceNotFound,
)
from job_agent.resume_workspace.ingestion import MAX_UPLOAD_BYTES, extract_upload
from job_agent.resume_workspace.parsing import ResumeParser
from job_agent.resume_workspace.parsing_contracts import (
    AcceptDraft, DraftRecord, EditVersion, ImportErrorCode, ParseError, ParseRequest, UploadView,
)


def create_resume_app(
    repository: SqliteResumeRepository, *, resolve_identity: Callable[[str], str | None],
    parser: ResumeParser | None = None, frontend_dir: Path | None = None,
    demo_only: bool = False,
    matcher=None,
    collaboration_engine=None,
    interview_engine=None,
    task_worker_enabled: bool = True,
    retrieval_runtime=None,
    project_persistence=None,
) -> FastAPI:
    """Authenticated product API increment, separate from the v1 task service.

    Identity is resolved by trusted server configuration. Clients cannot choose
    an owner with a user_id field/header. Full login/OIDC is a later increment.
    """
    app = FastAPI(title="求职助手 · 简历工作台", version="0.2.0-m2")
    parser = parser or ResumeParser()
    from job_agent.resume_workspace.retrieval_runtime import RetrievalRuntime
    retrieval_runtime = retrieval_runtime or RetrievalRuntime()
    app.state.retrieval_runtime = retrieval_runtime
    bearer = HTTPBearer(auto_error=False)

    def owner(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
        identity = resolve_identity(credentials.credentials) if credentials else None
        if not identity:
            raise HTTPException(401, "authentication_required", headers={"WWW-Authenticate": "Bearer"})
        return identity

    @app.exception_handler(WorkspaceNotFound)
    async def not_found(_request, _exc):
        return JSONResponse(status_code=404, content={"detail": "resource_not_found"})

    @app.exception_handler(WorkspaceConflict)
    async def conflict(_request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(InvalidProvenance)
    async def provenance(_request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(ImportErrorCode)
    @app.exception_handler(ParseError)
    async def parse_error(_request, exc):
        code = str(exc)
        status = 413 if code == "upload_too_large" else 503 if code == "model_parser_unavailable" else 422
        return JSONResponse(status_code=status, content={"detail": code})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, exc):
        # FastAPI's default validation response can echo private input values.
        return JSONResponse(status_code=422, content={"detail": "invalid_request", "errors": [
            {"location": list(item["loc"]), "type": item["type"]} for item in exc.errors()
        ]})

    @app.middleware("http")
    async def private_response(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/health/live")
    def health():
        return {"status": "ok", "increment": "structured-resume-m1"}

    @app.get("/api/v2/capabilities")
    def capabilities(user: str = Depends(owner)):
        return {"local_rules": True, "llm": parser.provider is not None,
                "max_upload_bytes": MAX_UPLOAD_BYTES, "ocr": False, "increment": "resume-import-m2",
                "demo_only": demo_only,"synthetic_persistent": bool(getattr(app.state,'synthetic_persistent',False)),
                "retrieval": retrieval_runtime.capabilities(),
                "project_storage":app.state.project_persistence.backend,
                "index_dispatch":getattr(app.state.project_persistence.tasks,'dispatch_mode','polling')}

    @app.post("/api/v2/imports", response_model=UploadView, status_code=201)
    async def import_file(request: Request, filename: str = Query(min_length=1, max_length=200), user: str = Depends(owner)):
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_UPLOAD_BYTES:
                raise ImportErrorCode("upload_too_large")
            data.extend(chunk)
        raw = bytes(data)
        extracted = await run_in_threadpool(extract_upload, filename, raw)
        return await run_in_threadpool(repository.save_upload, user, filename=filename, data=raw, extracted=extracted)

    @app.get("/api/v2/sources/{source_id}/original")
    def original(source_id: str, user: str = Depends(owner)):
        filename, raw = repository.get_upload(user, source_id)
        return Response(raw, media_type="application/octet-stream", headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename, safe="")})

    @app.post("/api/v2/sources/{source_id}/parse", response_model=DraftRecord, status_code=201)
    def parse_source(source_id: str, request: ParseRequest, user: str = Depends(owner)):
        source = repository.get_source(user, source_id)
        if request.mode == "llm" and not request.allow_external_processing:
            raise HTTPException(422, "external_processing_consent_required")
        return repository.save_draft(user, parser.parse(source, mode=request.mode))

    @app.get("/api/v2/drafts", response_model=list[DraftRecord])
    def drafts(user: str = Depends(owner)):
        return repository.list_drafts(user)

    @app.get("/api/v2/drafts/{draft_id}", response_model=DraftRecord)
    def draft(draft_id: str, user: str = Depends(owner)):
        return repository.get_draft(user, draft_id)

    @app.delete("/api/v2/drafts/{draft_id}", status_code=204)
    def delete_draft(draft_id: str, user: str = Depends(owner)):
        repository.delete_draft(user, draft_id)
        return Response(status_code=204)

    @app.post("/api/v2/drafts/{draft_id}/accept", response_model=VersionRecord, status_code=201)
    def accept(draft_id: str, request: AcceptDraft, user: str = Depends(owner)):
        return repository.accept_draft(user, draft_id, request)

    @app.post("/api/v2/resumes/{resume_id}/versions/{version_id}/edit", response_model=VersionRecord, status_code=201)
    def edit(resume_id: str, version_id: str, request: EditVersion, user: str = Depends(owner)):
        return repository.edit_version(user, resume_id, version_id, request)

    @app.post("/api/v2/sources", response_model=SourceRecord, status_code=201)
    def add_source(request: SourceCreate, user: str = Depends(owner)):
        return repository.add_source(user, request)

    @app.get("/api/v2/sources", response_model=list[SourceSummary])
    def list_sources(user: str = Depends(owner)):
        return repository.list_sources(user)

    @app.get("/api/v2/sources/{source_id}", response_model=SourceRecord)
    def get_source(source_id: str, user: str = Depends(owner)):
        return repository.get_source(user, source_id)

    @app.delete("/api/v2/sources/{source_id}", status_code=204)
    def delete_source(source_id: str, user: str = Depends(owner)):
        repository.delete_source(user, source_id)
        return Response(status_code=204)

    @app.post("/api/v2/resumes", response_model=VersionRecord, status_code=201)
    def create_resume(request: ResumeCreate, user: str = Depends(owner)):
        return repository.create_resume(user, request)

    @app.get("/api/v2/resumes", response_model=list[ResumeSummary])
    def list_resumes(user: str = Depends(owner)):
        return repository.list_resumes(user)

    @app.delete("/api/v2/resumes/{resume_id}", status_code=204)
    def delete_resume(resume_id: str, user: str = Depends(owner)):
        repository.delete_resume(user, resume_id)
        return Response(status_code=204)

    @app.get("/api/v2/resumes/{resume_id}/versions", response_model=list[VersionRecord])
    def list_versions(resume_id: str, user: str = Depends(owner)):
        return repository.list_versions(user, resume_id)

    @app.get("/api/v2/resumes/{resume_id}/versions/{version_id}", response_model=VersionRecord)
    def get_version(resume_id: str, version_id: str, user: str = Depends(owner)):
        return repository.get_version(user, resume_id, version_id)

    @app.post("/api/v2/resumes/{resume_id}/versions", response_model=VersionRecord, status_code=201)
    def save_version(resume_id: str, request: VersionCreate, user: str = Depends(owner)):
        return repository.save_version(user, resume_id, request)

    @app.post("/api/v2/resumes/{resume_id}/versions/{version_id}/confirm", response_model=VersionRecord)
    def confirm(resume_id: str, version_id: str, request: ConfirmVersion, user: str = Depends(owner)):
        return repository.confirm_version(user, resume_id, version_id,
                                          expected_content_hash=request.expected_content_hash)

    @app.post("/api/v2/resumes/{resume_id}/versions/{version_id}/restore", response_model=VersionRecord,
              status_code=201)
    def restore(resume_id: str, version_id: str, request: RestoreVersion, user: str = Depends(owner)):
        return repository.restore_version(user, resume_id, version_id,
                                          expected_parent_version_id=request.expected_parent_version_id,
                                          note=request.note)

    from job_agent.resume_workspace.pdf_export import install_pdf_routes
    install_pdf_routes(app, repository, owner)
    from job_agent.resume_workspace.rewrite import install_rewrite_routes
    install_rewrite_routes(app, repository, owner, parser.provider)

    @app.post('/api/v2/jd/extract')
    async def extract_jd(request: Request, filename: str = Query(min_length=1, max_length=200), user: str = Depends(owner)):
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_UPLOAD_BYTES:
                raise ImportErrorCode('upload_too_large')
            data.extend(chunk)
        extracted = await run_in_threadpool(extract_upload, filename, bytes(data))
        if len(extracted.text) > 12000:
            raise ImportErrorCode('jd_text_too_large')
        return {'text': extracted.text, 'extraction_only': True,
                'notice': '仅抽取岗位文字；原子要求请另行分析，不进入候选人经历池。'}

    from job_agent.resume_workspace.match_api import install_matching_routes
    from job_agent.resume_workspace.matching import WorkbenchMatcher
    install_matching_routes(app,repository,owner,matcher or WorkbenchMatcher(parser.provider))
    from job_agent.resume_workspace.collaboration import CollaborationEngine
    from job_agent.resume_workspace.collaboration_api import install_collaboration_routes
    install_collaboration_routes(app,repository,owner,collaboration_engine or CollaborationEngine(parser.provider))
    from job_agent.resume_workspace.interview_api import install_interview_routes
    from job_agent.resume_workspace.interview_collaboration import InterviewEngine
    from job_agent.resume_workspace.public_knowledge import PublicKnowledgeService
    public_knowledge=PublicKnowledgeService(repository,embedding_backend=retrieval_runtime.backend,
        reranker=retrieval_runtime.reranker,retrieval_settings=retrieval_runtime.settings)
    from job_agent.resume_workspace.code_rag import CodeRAGService
    from job_agent.resume_workspace.project_storage import sqlite_persistence
    project_persistence=project_persistence or sqlite_persistence(repository)
    app.state.project_persistence=project_persistence
    from job_agent.resume_workspace.retrieval_interview import RetrievalInterviewEngine
    code_service=CodeRAGService(repository,embedding_backend=retrieval_runtime.backend,
        reranker=retrieval_runtime.reranker,retrieval_settings=retrieval_runtime.settings,
        projects=project_persistence.projects,indexes=project_persistence.indexes)
    if hasattr(project_persistence.tasks,'config_identity'):
        project_persistence.tasks.config_identity=code_service.indexing_config_identity
    app.state.code_service = code_service
    app.state.public_knowledge = public_knowledge
    from job_agent.resume_workspace.evidence_api import install_evidence_routes
    install_evidence_routes(app,repository,owner,public_knowledge,code_service)
    install_interview_routes(app,repository,owner,interview_engine or RetrievalInterviewEngine(repository,public_knowledge,code_service,parser.provider),knowledge_service=public_knowledge)
    from job_agent.resume_workspace.long_term import install_long_term_routes
    install_long_term_routes(app, repository, owner,project_store=project_persistence.projects)
    from job_agent.resume_workspace.code_rag import install_code_routes
    install_code_routes(app, repository, owner,service=code_service)
    from job_agent.resume_workspace.public_knowledge import install_knowledge_routes
    install_knowledge_routes(app, repository, owner, service=public_knowledge)
    from job_agent.resume_workspace.tasks import install_task_routes
    install_task_routes(app,repository,owner,code_service,worker_enabled=task_worker_enabled,store=project_persistence.tasks)
    from job_agent.resume_workspace.unified_trace import install_trace_routes
    install_trace_routes(app,repository,owner,app.state.rewrite_service)

    if frontend_dir is not None:
        if not (frontend_dir / "index.html").is_file():
            raise ValueError("frontend_build_missing")
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="workbench")
    return app
