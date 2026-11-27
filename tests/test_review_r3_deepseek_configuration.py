"""Current provider payload and launcher configuration; no paid calls."""
import json
import pytest
from job_agent.schemas import StrictModel
from job_agent.llm.provider import TraceContext
from job_agent.llm.providers.deepseek_compatible import DeepSeekCompatibleProvider


class Echo(StrictModel):
    value:str


def test_current_deepseek_configuration_preserves_json_budget_and_explicit_thinking():
    provider=DeepSeekCompatibleProvider(api_key='synthetic-not-live',model='deepseek-flash',
        base_url='https://api.deepseek.com',thinking='disabled')
    observed=[]
    def transport(req,timeout):
        observed.append((req.full_url,json.loads(req.data)))
        return json.dumps({'model':'deepseek-flash','choices':[{'message':{'content':'{"value":"synthetic"}'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':5,'completion_tokens':3}}).encode()
    provider._transport=transport
    result=provider.generate_structured(system_prompt='Return JSON.',user_prompt='Synthetic only.',output_schema=Echo,
        tools=(),temperature=0,max_output_tokens=128,trace=TraceContext(session_id='s',run_id='r',node_id='n',skill_id='fixture',skill_version='1',prompt_version='1'))
    assert result.schema_valid and result.input_tokens==5 and result.output_tokens==3
    url,payload=observed[0]
    assert url=='https://api.deepseek.com/chat/completions'
    assert payload['model']=='deepseek-flash' and payload['thinking']=={'type':'disabled'}
    assert payload['max_tokens']==128 and payload['response_format']=={'type':'json_object'}
    assert DeepSeekCompatibleProvider(api_key='fixture')._extra_request_fields()=={}


@pytest.mark.parametrize('kw',[{'base_url':'https://api.deepseek.com.example.invalid'},
    {'model':'arbitrary-model'},{'thinking':'arbitrary-mode'}])
def test_current_configuration_does_not_open_unbounded_endpoints_models_or_modes(kw):
    with pytest.raises(ValueError,match='not_allowlisted'):DeepSeekCompatibleProvider(api_key='fixture',**kw)


def test_actual_workspace_launcher_honors_explicit_model_configuration(tmp_path,monkeypatch):
    import job_agent.llm.providers.deepseek_compatible as module
    from job_agent.resume_workspace.main import create_app
    seen={};original=module.DeepSeekCompatibleProvider
    def provider(**kw):seen.update(kw);return original(**kw)
    monkeypatch.setattr(module,'DeepSeekCompatibleProvider',provider)
    for key,value in {'JOB_AGENT_WORKSPACE_API_TOKEN':'synthetic-placeholder-token-only-0000',
        'JOB_AGENT_WORKSPACE_DB':str(tmp_path/'state.sqlite'),'JOB_AGENT_PROJECT_BACKEND':'sqlite',
        'JOB_AGENT_WORKSPACE_EMBEDDING':'disabled','JOB_AGENT_WORKSPACE_RERANK_PATH':'',
        'JOB_AGENT_WORKSPACE_ENABLE_LLM':'1','JOB_AGENT_WORKSPACE_MODEL_KEY':'synthetic-not-live',
        'JOB_AGENT_WORKSPACE_MODEL_NAME':'deepseek-flash','JOB_AGENT_WORKSPACE_MODEL_THINKING':'disabled'}.items():monkeypatch.setenv(key,value)
    app=create_app()
    assert seen['model']=='deepseek-flash' and seen['thinking']=='disabled'
    assert seen['base_url']=='https://api.deepseek.com'
    app.state.project_persistence.close()
