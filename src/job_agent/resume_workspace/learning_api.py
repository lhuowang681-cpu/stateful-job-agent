"""Owner-scoped user learning controls, with original interview execution gates."""
from fastapi import Depends,Query
from job_agent.resume_workspace.learning import LearningRepository,ObservationAction,ReviewPreferences,LearningPractice


def install_learning_routes(app,workspace,owner,interviews,engine,consent):
    learning=LearningRepository(workspace,interviews);app.state.learning=learning
    @app.post('/api/v2/interviews/{session_id}/learning-observations')
    def materialize(session_id:str,user:str=Depends(owner)):return learning.materialize(user,session_id)
    @app.get('/api/v2/learning/observations')
    def observations(resume_id:str|None=Query(default=None,max_length=100),user:str=Depends(owner)):
        return learning.list(user,resume_id=resume_id)
    @app.get('/api/v2/learning/observations/{observation_id}')
    def observation(observation_id:str,user:str=Depends(owner)):return learning.get(user,observation_id)
    @app.post('/api/v2/learning/observations/{observation_id}/actions')
    def act(observation_id:str,request:ObservationAction,user:str=Depends(owner)):
        return learning.act(user,observation_id,request)
    @app.get('/api/v2/learning/preferences')
    def preferences(user:str=Depends(owner)):return learning.preferences(user)
    @app.put('/api/v2/learning/preferences')
    def save_preferences(request:ReviewPreferences,user:str=Depends(owner)):return learning.set_preferences(user,request)
    @app.get('/api/v2/learning/queue')
    def queue(resume_id:str|None=Query(default=None,max_length=100),user:str=Depends(owner)):
        return learning.queue(user,resume_id=resume_id)
    @app.post('/api/v2/learning/observations/{observation_id}/practice')
    def practice(observation_id:str,request:LearningPractice,user:str=Depends(owner)):
        consent(request.mode,request.allow_external_processing)
        return interviews.get(user,learning.practice(user,observation_id,request,engine))

