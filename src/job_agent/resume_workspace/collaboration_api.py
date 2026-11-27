from fastapi import Depends, HTTPException
from job_agent.schemas import StrictModel

from job_agent.resume_workspace.collaboration_contracts import (
    CollaborationRequest, CollaborationView, CollaborationSummary, CollaborationError,
    CollaborationDecision, CollaborationDecisionResult,
)
from job_agent.resume_workspace.collaboration_repository import CollaborationRepository


class ResumeConsent(StrictModel):
    allow_external_processing: bool = False


def install_collaboration_routes(app,workspace,owner,engine):
    repository=CollaborationRepository(workspace)

    @app.exception_handler(CollaborationError)
    async def collaboration_error(_request,exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503 if str(exc)=='collaboration_model_unavailable' else 422,content={'detail':str(exc)})

    def consent(mode,allow):
        if mode=='llm':
            if not allow:raise HTTPException(422,'external_processing_consent_required')
            if engine.provider is None:raise CollaborationError('collaboration_model_unavailable')

    def execute(user,rid):
        token,state,version=repository.claim(user,rid)
        def checkpoint(s):repository.checkpoint(user,rid,token,s)
        try:
            engine.execute(state,version,checkpoint)
        except Exception as exc:
            state.status='failed'; state.next_node='end'; state.model_inflight=False
            state.error_code=str(exc) if isinstance(exc,CollaborationError) else 'collaboration_execution_failed'
            checkpoint(state)
        finally:
            repository.release(user,rid,token)
        return repository.get(user,rid)

    @app.post('/api/v2/resumes/{resume_id}/collaborations',response_model=CollaborationView,status_code=201)
    def start(resume_id:str,request:CollaborationRequest,user:str=Depends(owner)):
        consent(request.mode,request.allow_external_processing)
        rid,created=repository.begin(user,resume_id,request,engine)
        return execute(user,rid) if created else repository.get(user,rid)

    @app.get('/api/v2/resumes/{resume_id}/collaborations',response_model=list[CollaborationSummary])
    def history(resume_id:str,user:str=Depends(owner)):return repository.list(user,resume_id)

    @app.get('/api/v2/collaborations/{run_id}',response_model=CollaborationView)
    def get(run_id:str,user:str=Depends(owner)):return repository.get(user,run_id)

    @app.post('/api/v2/collaborations/{run_id}/resume',response_model=CollaborationView)
    def resume(run_id:str,request:ResumeConsent,user:str=Depends(owner)):
        view=repository.get(user,run_id)
        consent(view.state.mode,request.allow_external_processing)
        return execute(user,run_id)

    @app.post('/api/v2/collaborations/{run_id}/proposals/{proposal_id}/decision',response_model=CollaborationDecisionResult)
    def decide(run_id:str,proposal_id:str,request:CollaborationDecision,user:str=Depends(owner)):
        return repository.decide(user,run_id,proposal_id,request)
