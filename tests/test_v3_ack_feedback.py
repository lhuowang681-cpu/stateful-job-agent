"""One explicit ACK counterexample, with normal negation controls and actual learning flow."""
import pytest
from test_workbench_interview import setup,start,submit,A
from test_v3_learning import materialize,action,practice

FULL='幂等键记录执行标识，查询回执，不盲目重放。事务和Redis。'


def test_keyword_complete_ack_misconception_changes_followup_and_source_observation(setup):
    c,view=start(setup);before=view['current'];view=submit(c,view,FULL+'ACK保证业务只执行一次。')
    assert view['current']['followup'] and view['current']['topic_id']==before['topic_id']
    url=f"/api/v2/interviews/{view['session_id']}"
    c.post(url+'/finish',headers=A,json={'expected_revision':view['revision']})
    review=c.get(url+'/review',headers=A).json();evaluation=review['assessment_details'][0]
    assert evaluation['mode']=='deterministic_counterexample'
    assert evaluation['method_version']=='s8-answer-ack-1'
    assert evaluation['points'][0]['status']=='incorrect' and 'ACK' in evaluation['points'][0]['answer_quote']
    observations=materialize(c,view)['observations']
    wrong=next(o for o in observations if o['payload']['finding']=='incorrect')
    assert wrong['payload']['question_id']==before['question_id'] and wrong['payload']['answer_hash']
    assert wrong['independent_mastery']=='not_established'
    corrected=action(c,wrong,'correct',user_finding='understood',note='合成自述：ACK确认消息，业务需要按状态和操作键去重。')
    assert corrected['payload']==wrong['payload'] and corrected['confidence']=='user_corrected'
    again=practice(c,corrected);assert again.status_code==200,again.text
    assert again.json()['current']['prompt']==before['prompt']


@pytest.mark.parametrize('statement',[
    'ACK不保证业务只执行一次。','不能认为ACK保证业务只执行一次。',
    '不要声称ACK保证业务只执行一次。','XACK仅确认消息，业务仍要查询回执和去重。'])
def test_normal_negated_or_correct_statement_is_not_rejected_by_ack_counterexample(setup,statement):
    c,view=start(setup);view=submit(c,view,FULL+statement)
    url=f"/api/v2/interviews/{view['session_id']}"
    c.post(url+'/finish',headers=A,json={'expected_revision':view['revision']})
    review=c.get(url+'/review',headers=A).json()
    assert review['assessment_details'][0]['mode']!='deterministic_counterexample'
