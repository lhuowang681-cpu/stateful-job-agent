from fastapi import Depends, HTTPException
from job_agent.resume_workspace.interview_contracts import InterviewStart, InterviewAnswer, InterviewView, FinishInterview
from job_agent.resume_workspace.interview_repository import InterviewRepository
from job_agent.resume_workspace.collaboration_api import ResumeConsent
from job_agent.resume_workspace.collaboration_contracts import CollaborationError


def install_interview_routes(app,workspace,owner,engine,knowledge_service=None):
    store=InterviewRepository(workspace,code=getattr(app.state,'code_service',None),public=knowledge_service)
    app.state.interview_store=store
    def consent(mode,allow):
        if mode=='llm':
            if not allow:raise HTTPException(422,'external_processing_consent_required')
            if engine.provider is None:raise HTTPException(503,'interview_model_unavailable')
    def execute(user,sid):
        token,state,version=store.claim(user,sid)
        def save(s):store.checkpoint(user,sid,token,s)
        try:engine.execute(state,version,save)
        except Exception as exc:
            state.status='failed';state.error_code=str(exc) if isinstance(exc,CollaborationError) else 'interview_execution_failed'
            # Unknown transport/dispatch stays uncertain and cannot be replayed.
            save(state)
        finally:store.release(user,sid,token)
        return store.get(user,sid)

    @app.post('/api/v2/resumes/{resume_id}/interviews',response_model=InterviewView,status_code=201)
    def start(resume_id:str,request:InterviewStart,user:str=Depends(owner)):
        consent(request.mode,request.allow_external_processing)
        return store.get(user,store.start(user,resume_id,request,engine))

    @app.get('/api/v2/resumes/{resume_id}/interviews')
    def history(resume_id:str,user:str=Depends(owner)):return store.list(user,resume_id)

    @app.get('/api/v2/interviews/{session_id}',response_model=InterviewView)
    def get(session_id:str,user:str=Depends(owner)):return store.get(user,session_id)

    @app.post('/api/v2/interviews/{session_id}/answers',response_model=InterviewView)
    def answer(session_id:str,request:InterviewAnswer,user:str=Depends(owner)):
        current=store.get(user,session_id);consent(current.mode,request.allow_external_processing)
        return execute(user,session_id) if store.answer(user,session_id,request) else store.get(user,session_id)

    @app.post('/api/v2/interviews/{session_id}/resume',response_model=InterviewView)
    def resume(session_id:str,request:ResumeConsent,user:str=Depends(owner)):
        current=store.get(user,session_id);consent(current.mode,request.allow_external_processing)
        return execute(user,session_id)

    @app.post('/api/v2/interviews/{session_id}/finish',response_model=InterviewView)
    def finish(session_id:str,request:FinishInterview,user:str=Depends(owner)):
        store.finish(user,session_id,request.expected_revision);return store.get(user,session_id)

    @app.post('/api/v2/interviews/{session_id}/pause',response_model=InterviewView)
    def pause(session_id:str,request:FinishInterview,user:str=Depends(owner)):
        store.set_paused(user,session_id,request.expected_revision,True);return store.get(user,session_id)

    @app.post('/api/v2/interviews/{session_id}/continue',response_model=InterviewView)
    def continue_session(session_id:str,request:FinishInterview,user:str=Depends(owner)):
        store.set_paused(user,session_id,request.expected_revision,False);return store.get(user,session_id)

    @app.get('/api/v2/interviews/{session_id}/review')
    def review(session_id:str,user:str=Depends(owner)):
        result=store.review(user,session_id) # Completion/owner gate precedes retrieval.
        result['learning_comparison']=app.state.learning.comparison(user,session_id)
        if result['learning_comparison'] is not None:result['practice_comparison']=None
        if knowledge_service is not None:
            from job_agent.resume_workspace.repository import WorkspaceConflict,WorkspaceNotFound
            from job_agent.resume_workspace.interview_tools import InterviewTools,new_retrieval_state
            from job_agent.resume_workspace.evidence_pack import EvidenceBudget
            result['learning_resources']=[]
            if not result['turns']:
                result['resources_status']='no_answered_turns'
                return result
            execution=new_retrieval_state('post-review')
            try:
                # A separate post-completion execution has its own bounded budget.
                # It is not silently attributed to the 18 in-interview tool calls.
                tools=InterviewTools(workspace,knowledge_service,getattr(app.state,'code_service',None),user)
                query=' '.join(t['question'] for t in result['turns'][:2])[:600]
                pack=tools.retrieve_pack(execution,'coach',query,scope_kind='public_docs',budget=EvidenceBudget(tools=2))
                # UI compatibility: reconstruct body from the already verified
                # title/body quote; no uncounted extra source lookup.
                result['learning_resources']=[{'entry':{**i.entry,'body':i.reference.quote[len(i.entry['title'])+1:]},
                    'reference':i.reference.model_dump(mode='json'),'score':i.score} for i in pack.items]
                result['learning_resource_pack']=pack.role_summary()
                result['resource_execution']={'execution_id':execution.session_id,'scope':'post_review',
                    'usage':pack.usage.model_dump(),'tool_trace':execution.tool_trace}
                result['resources_status']='retrieved_reference_only' if pack.items else 'insufficient_evidence'
            except (WorkspaceConflict,WorkspaceNotFound):
                result['resources_status']='unavailable'
                result['resource_execution']={'execution_id':execution.session_id,'scope':'post_review',
                    'tool_calls':execution.tool_calls,'tool_trace':execution.tool_trace,'error_code':'resource_reference_unavailable'}
        return result

    from job_agent.resume_workspace.learning_api import install_learning_routes
    install_learning_routes(app,workspace,owner,store,engine,consent)
