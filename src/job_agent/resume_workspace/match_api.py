from __future__ import annotations

from fastapi import Depends, HTTPException

from job_agent.resume_workspace.match_contracts import (
    AnalyzeRequest, DecideProposal, DecisionResult, MatchError, MatchSummary, MatchView,
)
from job_agent.resume_workspace.match_repository import MatchRepository
from job_agent.resume_workspace.matching import WorkbenchMatcher


def install_matching_routes(app, workspace, owner, matcher: WorkbenchMatcher):
    repository = MatchRepository(workspace)

    @app.exception_handler(MatchError)
    async def match_error(_request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503 if str(exc)=='match_model_unavailable' else 422,content={'detail':str(exc)})

    @app.post('/api/v2/resumes/{resume_id}/matches',response_model=MatchView,status_code=201)
    def analyze(resume_id: str, request: AnalyzeRequest, user: str=Depends(owner)):
        if request.mode=='llm':
            if not request.allow_external_processing:
                raise HTTPException(422,'external_processing_consent_required')
            if matcher.provider is None:raise MatchError('match_model_unavailable')
        match_id, version, execute = repository.begin(user,resume_id,request)
        if execute:
            try:
                payload = matcher.analyze(match_id,version,request)
                repository.complete(user,match_id,payload)
            except MatchError as exc:
                repository.fail(user,match_id,str(exc))
                raise
            except Exception as exc:
                repository.fail(user,match_id,'match_analysis_failed')
                raise MatchError('match_analysis_failed') from exc
        return repository.get(user,match_id)

    @app.get('/api/v2/resumes/{resume_id}/matches',response_model=list[MatchSummary])
    def list_matches(resume_id: str, user: str=Depends(owner)):
        return repository.list(user,resume_id)

    @app.get('/api/v2/matches/{match_id}',response_model=MatchView)
    def get_match(match_id: str, user: str=Depends(owner)):
        return repository.get(user,match_id)

    @app.post('/api/v2/matches/{match_id}/proposals/{proposal_id}/decision',response_model=DecisionResult)
    def decide(match_id: str, proposal_id: str, request: DecideProposal, user: str=Depends(owner)):
        return repository.decide(user,match_id,proposal_id,request)
