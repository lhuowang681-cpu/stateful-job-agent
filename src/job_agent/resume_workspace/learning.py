"""Source-linked practice observations, explicit user controls and finite review rules.

Observations never become resume facts or claims of personal mastery.
"""
from contextlib import nullcontext
import json
from time import time
from pydantic import Field,model_validator
from typing import Literal
from job_agent.schemas import StrictModel
from job_agent.resume_workspace.long_term import encoded,digest
from job_agent.resume_workspace.repository import WorkspaceConflict,WorkspaceNotFound,InvalidProvenance

DAY=86400
DDL='''
CREATE TABLE IF NOT EXISTS rw_learning_observations(
 observation_id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,
 session_id TEXT NOT NULL REFERENCES rw_interviews(session_id) ON DELETE CASCADE,
 question_id TEXT NOT NULL,point_id TEXT NOT NULL,source_fingerprint TEXT NOT NULL,
 payload TEXT,payload_hash TEXT,controls TEXT NOT NULL,controls_hash TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 0,created_at REAL NOT NULL,
 UNIQUE(owner_id,session_id,question_id,point_id,source_fingerprint));
CREATE INDEX IF NOT EXISTS rw_learning_owner ON rw_learning_observations(owner_id,created_at);
CREATE TABLE IF NOT EXISTS rw_learning_operations(
 observation_id TEXT NOT NULL REFERENCES rw_learning_observations ON DELETE CASCADE,
 request_key TEXT NOT NULL,request_hash TEXT NOT NULL,result_id TEXT,
 PRIMARY KEY(observation_id,request_key));
CREATE TABLE IF NOT EXISTS rw_learning_withdrawals(
 session_id TEXT NOT NULL REFERENCES rw_interviews(session_id) ON DELETE CASCADE,
 question_id TEXT NOT NULL,owner_id TEXT NOT NULL,reason TEXT NOT NULL,recorded_at REAL NOT NULL,
 PRIMARY KEY(session_id,question_id));
CREATE TABLE IF NOT EXISTS rw_learning_preferences(
 owner_id TEXT PRIMARY KEY,payload TEXT NOT NULL,payload_hash TEXT NOT NULL,
 revision INTEGER NOT NULL,updated_at REAL NOT NULL);
'''


class ObservationAction(StrictModel):
    request_key:str=Field(pattern=r'^[a-zA-Z0-9_-]{8,80}$')
    expected_revision:int=Field(ge=0)
    action:Literal['confirm','correct','pause','resume','schedule','mark_reviewed','delete','withdraw']
    user_finding:Literal['needs_practice','unsure','understood']|None=None
    note:str=Field(default='',max_length=1000)
    review_in_days:int|None=Field(default=None,ge=0,le=30)

    @model_validator(mode='after')
    def required(self):
        if self.action=='correct' and (not self.note.strip() or self.user_finding is None):raise ValueError('correction_requires_user_reason')
        if self.action=='withdraw' and not self.note.strip():raise ValueError('withdrawal_requires_reason')
        if self.action=='schedule' and self.review_in_days is None:raise ValueError('review_days_required')
        if self.action!='correct' and self.user_finding is not None:raise ValueError('unexpected_user_finding')
        return self


class ReviewPreferences(StrictModel):
    expected_revision:int=Field(ge=0)
    cadence_days:int=Field(default=3,ge=1,le=30)
    daily_limit:int=Field(default=10,ge=1,le=20)
    paused:bool=False
    include_new:bool=True


class LearningPractice(StrictModel):
    request_key:str=Field(pattern=r'^[a-zA-Z0-9_-]{8,80}$')
    expected_revision:int=Field(ge=0)
    mode:Literal['local_demo','llm']='local_demo'
    allow_external_processing:bool=False
    allow_historical_version:bool=False


def withdrawn_questions(db,owner,session_id):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='rw_learning_withdrawals'").fetchone():return set()
    return {r[0] for r in db.execute('SELECT question_id FROM rw_learning_withdrawals WHERE owner_id=? AND session_id=?',(owner,session_id))}


def condition(s,turn,topic,point_id):
    """Recorded conditions only: matching this hash is not independent truth."""
    value={'question':turn.question.prompt,'focus':turn.question.focus_id,'followup':turn.question.followup,
        'point_id':point_id,'rubric':topic.points,'aliases':topic.aliases,
        'references':[r.model_dump(mode='json',exclude={'quote','retrieval_method','supports_claim','independent_truth'}) for r in turn.question.references],
        'version_hash':s.version_hash,'jd_hash':digest(s.jd_text),
        'mode':s.mode,'provider':s.provider,'model':s.model,
        'model_configuration':s.execution.model_identity if s.execution else {'revision':'unknown'},
        'evaluation_method':turn.evaluation.method_version,'assessment_mode':turn.evaluation.assessment_mode}
    if turn.question.evidence_boundary is not None:value['evidence_boundary']=turn.question.evidence_boundary.model_dump(mode='json')
    return value


def observation_payload(s,turn,topic,point_id):
    assessment=next((a for a in turn.evaluation.point_assessments if a.point_id==point_id),None)
    finding=(assessment.status if assessment else 'lexical_located' if point_id in turn.evaluation.covered_ids else 'lexical_not_located')
    data={'session_id':s.session_id,'resume_id':s.resume_id,'version_id':s.version_id,'version_hash':s.version_hash,
        'question_id':turn.question.question_id,'topic_id':topic.anchor_id,'point_id':point_id,
        'knowledge_point':topic.points[point_id],'question':turn.question.prompt,'answer':turn.answer,'answer_hash':digest(turn.answer),
        'finding':finding,'evaluation_note':turn.evaluation.note,'point_assessment':assessment.model_dump() if assessment else None,
        'assessment_mode':turn.evaluation.assessment_mode,'method_version':turn.evaluation.method_version,
        'mode':s.mode,'provider':s.provider,'model':s.model,'observed_at':(turn.answered_at or s.created_at).timestamp(),
        'observation_time_source':'answer_committed_at' if turn.answered_at else 'legacy_session_created_at_fallback',
        'references':condition(s,turn,topic,point_id)['references'],
        'rubric_hash':digest({'points':topic.points,'aliases':topic.aliases}),
        'condition_hash':digest(condition(s,turn,topic,point_id)),
        'independent_mastery':'not_established','personal_experience_truth':'not_verified'}
    if turn.question.evidence_boundary is not None:data['evidence_boundary']=turn.question.evidence_boundary.model_dump(mode='json')
    return data


def usable_evaluation_source(s,turn,topic):
    """Validate persisted LLM evidence shape without inventing semantic labels."""
    evaluation=turn.evaluation
    if evaluation is None:return False
    if s.mode!='llm':return True
    if not evaluation.has_complete_assessments(topic.points):return False
    correct={a.point_id for a in evaluation.point_assessments if a.status=='correct'}
    covered=evaluation.covered_ids;missing=evaluation.missing_ids
    if len(covered)!=len(set(covered)) or len(missing)!=len(set(missing)):return False
    if set(covered)!=correct or set(missing)!=set(topic.points)-correct:return False
    for assessment in evaluation.point_assessments:
        quote=assessment.answer_quote.strip()
        if (quote and quote not in turn.answer) or (assessment.status!='uncertain' and not quote):return False
    return True


class LearningRepository:
    def __init__(self,workspace,interviews,*,clock=time):
        self.workspace=workspace;self.interviews=interviews;self.clock=clock
        with workspace._connection(write=True) as db:db.executescript(DDL)
        interviews.learning=self

    def _row(self,db,owner,key):
        row=db.execute('SELECT o.*,i.resume_id FROM rw_learning_observations o JOIN rw_interviews i USING(session_id) WHERE observation_id=? AND o.owner_id=?',(key,owner)).fetchone()
        if row is None:raise WorkspaceNotFound('learning_observation_not_found')
        if digest(row['controls'])!=row['controls_hash'] or (row['payload'] and digest(row['payload'])!=row['payload_hash']):raise InvalidProvenance('learning_record_integrity_failed')
        if row['payload']:
            if digest(json.loads(row['payload']))!=row['source_fingerprint']:raise InvalidProvenance('learning_record_integrity_failed')
        elif not json.loads(row['controls']).get('deleted'):raise InvalidProvenance('learning_record_integrity_failed')
        return row

    def _source(self,db,owner,sid,cache):
        if sid not in cache:
            try:
                _,s,v=self.interviews._load(db,owner,sid)
                if s.status!='complete':raise WorkspaceConflict('learning_requires_completed_source')
                cache[sid]=(s,v)
            except (WorkspaceNotFound,WorkspaceConflict,InvalidProvenance):cache[sid]=None
        return cache[sid]

    def _payload_for(self,s,question_id,point_id):
        turn=next((t for t in s.turns if t.question.question_id==question_id),None)
        topic=next((t for t in s.plan if turn and t.anchor_id==turn.question.topic_id),None)
        if not turn or not topic or point_id not in topic.points:return None
        if not usable_evaluation_source(s,turn,topic):return None
        return observation_payload(s,turn,topic,point_id)

    def _view(self,db,owner,row,cache):
        controls=json.loads(row['controls']);now=self.clock()
        base={'observation_id':row['observation_id'],'session_id':row['session_id'],'revision':row['revision'],
            'resume_id':row['resume_id'],
            'created_at':row['created_at'],'confirmed':bool(controls.get('confirmed')),'paused':bool(controls.get('paused')),
            'independent_mastery':'not_established'}
        if controls.get('deleted'):return {**base,'status':'deleted','queue_bucket':'excluded','payload':None,'controls':{}}
        source=self._source(db,owner,row['session_id'],cache)
        if row['question_id'] in withdrawn_questions(db,owner,row['session_id']):
            return {**base,'status':'withdrawn','queue_bucket':'excluded','payload':None,'controls':{},'reason':'evaluation_withdrawn'}
        current=self._payload_for(source[0],row['question_id'],row['point_id']) if source else None
        if not current or digest(current)!=row['source_fingerprint']:
            return {**base,'status':'invalid','queue_bucket':'excluded','payload':None,'controls':{},'reason':'source_unavailable_or_changed'}
        payload=json.loads(row['payload'])
        head=self.workspace._resume(db,owner,payload['resume_id'])['head_version_id']
        historical=head!=payload['version_id']
        expired=now-max(payload['observed_at'],controls.get('checked_at',0))>90*DAY
        bucket=('paused' if controls.get('paused') else 'historical_version' if historical else 'expired' if expired else
            'new' if not controls.get('confirmed') else 'review_due' if controls.get('due_at',now)<=now else 'reviewed')
        return {**base,'status':'expired' if expired else 'valid','queue_bucket':bucket,'payload':payload,'controls':controls,
            'historical_version':historical,'source_age_days':max(0,int((now-payload['observed_at'])/DAY)),
            'confidence':'user_corrected' if controls.get('user_finding') else 'single_observation',
            'reason':{'new':'awaiting_user_check','review_due':'scheduled_time_reached','reviewed':'user_review_scheduled_next',
                'paused':'user_paused','expired':'observation_requires_recheck','historical_version':'resume_head_changed'}[bucket]}

    def get(self,owner,key):
        with self.workspace._connection() as db:return self._view(db,owner,self._row(db,owner,key),{})

    def list(self,owner,*,resume_id=None):
        with self.workspace._connection() as db:
            if resume_id:self.workspace._resume(db,owner,resume_id)
            rows=list(db.execute('''SELECT o.*,i.resume_id FROM rw_learning_observations o JOIN rw_interviews i USING(session_id)
                WHERE o.owner_id=? AND (? IS NULL OR i.resume_id=?) ORDER BY o.created_at DESC,o.observation_id LIMIT 2000''',(owner,resume_id,resume_id)))
            cache={};views=[]
            for row in rows:
                self._row(db,owner,row['observation_id'])
                view=self._view(db,owner,row,cache)
                if view['status']!='deleted':views.append(view)
            groups={}
            for view in views:
                if view['status']=='valid' and view['confirmed'] and not view['controls'].get('user_finding'):
                    groups.setdefault((view['payload']['condition_hash'],view['payload']['finding']),set()).add(view['session_id'])
            for view in views:
                if view['status']!='valid' or not view['confirmed'] or view['controls'].get('user_finding'):continue
                peers=groups[(view['payload']['condition_hash'],view['payload']['finding'])]
                view['consistent_distinct_sessions']=len(peers)
                if len(peers)>1:view['confidence']='repeated_consistent_observations'
            return views

    def materialize(self,owner,sid):
        with self.workspace._connection(write=True) as db:
            _,s,_=self.interviews._load(db,owner,sid)
            if s.status!='complete':raise WorkspaceConflict('learning_requires_completed_source')
            topics={t.anchor_id:t for t in s.plan};withdrawn=withdrawn_questions(db,owner,sid)
            if any(not usable_evaluation_source(s,t,topics[t.question.topic_id]) for t in s.turns if t.question.question_id not in withdrawn):
                raise WorkspaceConflict('learning_source_incomplete_semantic_review')
            payloads=[observation_payload(s,t,topics[t.question.topic_id],point) for t in s.turns if t.question.question_id not in withdrawn
                for point in ([t.question.focus_id] if t.question.focus_id in topics[t.question.topic_id].points else topics[t.question.topic_id].points)]
            if len(payloads)>100:raise WorkspaceConflict('learning_session_quota_reached')
            quota=db.execute('SELECT COUNT(*) FROM rw_learning_observations WHERE owner_id=?',(owner,)).fetchone()[0]
            added=0
            for data in payloads:
                fp=digest(data);key='learn-'+digest([owner,sid,data['question_id'],data['point_id'],fp])[:32]
                old_scope=db.execute('SELECT controls FROM rw_learning_observations WHERE owner_id=? AND session_id=? AND question_id=? AND point_id=?',
                    (owner,sid,data['question_id'],data['point_id'])).fetchall()
                if any(json.loads(old['controls']).get('deleted') for old in old_scope):continue
                if db.execute('SELECT 1 FROM rw_learning_observations WHERE observation_id=?',(key,)).fetchone():continue
                if quota+added>=2000:raise WorkspaceConflict('learning_owner_quota_reached')
                raw=encoded(data);controls=encoded({'confirmed':False,'paused':False,'deleted':False,'due_at':self.clock()})
                db.execute('INSERT INTO rw_learning_observations VALUES (?,?,?,?,?,?,?,?,?,?,0,?)',
                    (key,owner,sid,data['question_id'],data['point_id'],fp,raw,digest(raw),controls,digest(controls),self.clock()))
                added+=1
        return {'added':added,'source_session_id':sid,'observations':[v for v in self.list(owner) if v['session_id']==sid],
            'warning':'练习观察可纠正，不是用户能力画像、个人经历证明或已掌握结论。'}

    def preferences(self,owner,*,db=None):
        with (nullcontext(db) if db is not None else self.workspace._connection()) as db:
            row=db.execute('SELECT * FROM rw_learning_preferences WHERE owner_id=?',(owner,)).fetchone()
            if not row:return {'revision':0,'cadence_days':3,'daily_limit':10,'paused':False,'include_new':True,'source':'system_default'}
            if digest(row['payload'])!=row['payload_hash']:raise InvalidProvenance('learning_preferences_integrity_failed')
            return {'revision':row['revision'],**json.loads(row['payload']),'source':'explicit_user_preference'}

    def set_preferences(self,owner,request):
        with self.workspace._connection(write=True) as db:
            previous=self.preferences(owner,db=db)
            if previous['revision']!=request.expected_revision:raise WorkspaceConflict('learning_preferences_changed')
            raw=encoded(request.model_dump(exclude={'expected_revision'}))
            db.execute('INSERT OR REPLACE INTO rw_learning_preferences VALUES (?,?,?,?,?)',(owner,raw,digest(raw),request.expected_revision+1,self.clock()))
        return self.preferences(owner)

    def queue(self,owner,*,resume_id=None):
        preferences=self.preferences(owner);all_views=self.list(owner)
        if resume_id:
            with self.workspace._connection() as db:self.workspace._resume(db,owner,resume_id)
        views=[v for v in all_views if not resume_id or v['resume_id']==resume_id]
        day=int((self.clock()+8*3600)//DAY)
        with self.workspace._connection() as db:
            controls=[]
            for row in db.execute('SELECT controls,controls_hash FROM rw_learning_observations WHERE owner_id=?',(owner,)):
                if digest(row['controls'])!=row['controls_hash']:raise InvalidProvenance('learning_record_integrity_failed')
                controls.append(json.loads(row['controls']))
        reviewed_today=sum(bool(v.get('last_reviewed_at')) and int((v['last_reviewed_at']+8*3600)//DAY)==day for v in controls)
        remaining=max(0,preferences['daily_limit']-reviewed_today)
        eligible=[v for v in views if v['queue_bucket']=='review_due' or (v['queue_bucket']=='new' and preferences['include_new'])]
        eligible.sort(key=lambda v:(v['queue_bucket']=='new',v['controls'].get('due_at',0),v['observation_id']))
        return {'preferences':preferences,'items':[] if preferences['paused'] else eligible[:remaining],
            'reviewed_today':reviewed_today,'remaining_today':remaining,'day_timezone':'Asia/Shanghai',
            'counts':{key:sum(v['queue_bucket']==key for v in views) for key in ('new','review_due','reviewed','paused','historical_version','expired','excluded')},
            'rule_version':'s7-review-rules-1','warning':'按用户核对与时间生成建议；标已复核不代表已经掌握。'}

    def _operation(self,db,row,request):
        old=db.execute('SELECT * FROM rw_learning_operations WHERE observation_id=? AND request_key=?',(row['observation_id'],request.request_key)).fetchone()
        if old:
            if old['request_hash']!=digest(request.model_dump()):raise WorkspaceConflict('learning_request_key_conflict')
            return old
        if row['revision']!=request.expected_revision:raise WorkspaceConflict('learning_revision_changed')
        return None

    def _save_control(self,db,row,request,controls,*,result_id=None):
        raw=encoded(controls)
        db.execute('UPDATE rw_learning_observations SET controls=?,controls_hash=?,revision=revision+1 WHERE observation_id=?',
            (raw,digest(raw),row['observation_id']))
        db.execute('INSERT INTO rw_learning_operations VALUES (?,?,?,?)',
            (row['observation_id'],request.request_key,digest(request.model_dump()),result_id))

    def act(self,owner,key,request):
        with self.workspace._connection(write=True) as db:
            row=self._row(db,owner,key)
            if self._operation(db,row,request):return self._view(db,owner,row,{})
            controls=json.loads(row['controls']);view=self._view(db,owner,row,{})
            if controls.get('deleted'):raise WorkspaceNotFound('learning_observation_deleted')
            if request.action not in ('delete','pause') and view['status'] in ('invalid','withdrawn'):raise WorkspaceConflict('learning_source_not_eligible')
            now=self.clock()
            if request.action in ('confirm','correct'):
                controls.update(confirmed=True,checked_at=now)
                if request.action=='correct':controls.update(user_finding=request.user_finding,user_note=request.note,correction_source='explicit_user')
            elif request.action in ('pause','resume'):controls['paused']=request.action=='pause'
            elif request.action=='schedule':controls['due_at']=now+request.review_in_days*DAY
            elif request.action=='mark_reviewed':
                if not controls.get('confirmed'):raise WorkspaceConflict('learning_confirmation_required')
                controls.update(last_reviewed_at=now,checked_at=now,due_at=now+self.preferences(owner,db=db)['cadence_days']*DAY)
            elif request.action=='withdraw':
                db.execute('INSERT OR IGNORE INTO rw_learning_withdrawals VALUES (?,?,?,?,?)',(row['session_id'],row['question_id'],owner,request.note,now))
            elif request.action=='delete':
                controls={'deleted':True}
                db.execute('UPDATE rw_learning_observations SET payload=NULL,payload_hash=NULL WHERE observation_id=?',(key,))
            self._save_control(db,row,request,controls)
        return self.get(owner,key)

    def practice_context(self,db,owner,request):
        row=self._row(db,owner,request.learning_observation_id);view=self._view(db,owner,row,{})
        if view['status']!='valid' or not view['confirmed'] or view['paused']:raise WorkspaceConflict('learning_source_not_eligible')
        if view['historical_version'] and not request.learning_allow_historical_version:raise WorkspaceConflict('learning_historical_version_requires_confirmation')
        s,_=self._source(db,owner,row['session_id'],{})
        if (request.prior_session_id,request.version_id,request.expected_content_hash,request.jd_text,request.project_id,request.snapshot_id)!=(s.session_id,s.version_id,s.version_hash,s.jd_text,s.project_id,s.snapshot_id):
            raise WorkspaceConflict('learning_practice_scope_changed')
        turn=next(t for t in s.turns if t.question.question_id==row['question_id'])
        topic=next(t for t in s.plan if t.anchor_id==turn.question.topic_id)
        return topic.model_copy(deep=True,update={'prompt':turn.question.prompt,'references':turn.question.references,
            'evidence_boundary':turn.question.evidence_boundary}),turn.question,view['payload']['condition_hash']

    def practice(self,owner,key,request,engine):
        from job_agent.resume_workspace.interview_contracts import InterviewStart
        with self.workspace._connection(write=True) as db:
            row=self._row(db,owner,key);old=self._operation(db,row,request)
            if old:return old['result_id']
            view=self._view(db,owner,row,{})
            if view['status']!='valid' or not view['confirmed'] or view['paused']:raise WorkspaceConflict('learning_source_not_eligible')
            if view['historical_version'] and not request.allow_historical_version:raise WorkspaceConflict('learning_historical_version_requires_confirmation')
            s,_=self._source(db,owner,row['session_id'],{})
            start=InterviewStart(request_key='learning-'+digest([key,request.request_key])[:40],version_id=s.version_id,
                expected_content_hash=s.version_hash,jd_text=s.jd_text,mode=request.mode,max_turns=2,use_retrieval=True,
                track='weakness',prior_session_id=s.session_id,project_id=s.project_id,snapshot_id=s.snapshot_id,
                learning_observation_id=key,allow_external_processing=request.allow_external_processing,
                learning_allow_historical_version=request.allow_historical_version)
            sid=self.interviews.start(owner,s.resume_id,start,engine,db=db)
            controls=json.loads(row['controls']);controls['last_practice_session_id']=sid
            self._save_control(db,row,request,controls,result_id=sid)
            return sid

    def comparison(self,owner,sid):
        with self.workspace._connection() as db:
            _,s,_=self.interviews._load(db,owner,sid)
            if not s.learning_observation_id:return None
            try:old=self._view(db,owner,self._row(db,owner,s.learning_observation_id),{})
            except WorkspaceNotFound:old={'status':'invalid','controls':{},'payload':None}
            if s.status!='complete':raise WorkspaceConflict('learning_comparison_requires_completion')
            matches=[]
            if old['status']=='valid':
                topics={t.anchor_id:t for t in s.plan};pid=old['payload']['point_id']
                for turn in s.turns:
                    topic=topics[turn.question.topic_id]
                    if pid in topic.points:
                        new=observation_payload(s,turn,topic,pid)
                        if new['condition_hash']==old['payload']['condition_hash']:matches.append(new)
            comparable=bool(matches) and not old.get('controls',{}).get('user_finding')
            return {'source_observation_id':s.learning_observation_id,'status':'same_recorded_conditions' if comparable else 'not_comparable',
                'before_finding':old['payload']['finding'] if comparable else None,'after_finding':matches[-1]['finding'] if comparable else None,
                'mastery_claim':None,'warning':'仅比较同记录条件下的参考评价，不计算能力提升；用户纠正/撤回或条件变化时不直接比较。'}
