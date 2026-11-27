"""Owner-scoped version/JD interview snapshots; private rubric never in active view."""
from datetime import datetime, UTC
from time import time
from uuid import uuid4
from contextlib import nullcontext

from job_agent.resume_workspace.interview_contracts import (
    InterviewState, InterviewView, PublicQuestion, PublicTurn, PendingAnswer, InterviewStart,
)
from job_agent.resume_workspace.interview_collaboration import build_plan, question_for
from job_agent.resume_workspace.match_repository import MatchRepository
from job_agent.resume_workspace.matching import digest
from job_agent.resume_workspace.repository import WorkspaceConflict, WorkspaceNotFound, InvalidProvenance
from job_agent.resume_workspace.execution_state import sync_interview,interview_identity

DDL='''
CREATE TABLE IF NOT EXISTS rw_interviews(
 session_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
 resume_id TEXT NOT NULL REFERENCES rw_resumes(resume_id) ON DELETE CASCADE,
 version_id TEXT NOT NULL REFERENCES rw_versions(version_id) ON DELETE CASCADE,
 request_key TEXT NOT NULL, request_hash TEXT NOT NULL,
 state_json TEXT NOT NULL,state_hash TEXT NOT NULL,
 execution_token TEXT,lease_until REAL NOT NULL DEFAULT 0,
 UNIQUE(owner_id,request_key)
);
CREATE INDEX IF NOT EXISTS rw_interviews_resume ON rw_interviews(owner_id,resume_id);
CREATE TABLE IF NOT EXISTS rw_interview_answers(
 session_id TEXT NOT NULL REFERENCES rw_interviews(session_id) ON DELETE CASCADE,
 request_key TEXT NOT NULL,request_hash TEXT NOT NULL,status TEXT NOT NULL,
 PRIMARY KEY(session_id,request_key)
);
'''


class InterviewRepository:
    def __init__(self,workspace,*,code=None,public=None):
        self.workspace=workspace
        self.matches=MatchRepository(workspace)
        with workspace._connection() as db:db.executescript(DDL)
        from job_agent.resume_workspace.code_rag import CodeRAGService
        from job_agent.resume_workspace.public_knowledge import PublicKnowledgeService
        self.code=code or CodeRAGService(workspace);self.public=public or PublicKnowledgeService(workspace)

    def start(self,owner,resume_id,request,engine,*,db=None):
        hashed=digest(resume_id+request.stable_json())
        if request.match_id:
            match=self.matches.get(owner,request.match_id)
            if match.resume_id!=resume_id or match.jd_text!=request.jd_text:raise WorkspaceConflict('interview_match_snapshot_mismatch')
        with (nullcontext(db) if db is not None else self.workspace._connection(write=True)) as db:
            self.workspace._resume(db,owner,resume_id)
            version=self.workspace._version(db,resume_id,request.version_id)
            self.workspace._validate_document(db,owner,version.document)
            if version.content_hash!=request.expected_content_hash:raise WorkspaceConflict('interview_version_changed')
            old=db.execute('SELECT * FROM rw_interviews WHERE owner_id=? AND request_key=?',(owner,request.request_key)).fetchone()
            if old:
                if old['request_hash']!=hashed:raise WorkspaceConflict('interview_request_key_conflict')
                return old['session_id']
            sid='interview-'+uuid4().hex
            learning_context=None
            if request.learning_observation_id:
                if not getattr(self,'learning',None):raise WorkspaceConflict('learning_practice_not_configured')
                learning_context=self.learning.practice_context(db,owner,request)
            state=InterviewState(session_id=sid,resume_id=resume_id,version_id=version.version_id,version_hash=version.content_hash,
                jd_text=request.jd_text,match_id=request.match_id,mode=request.mode,
                provider=getattr(engine.provider,'provider_name','unknown') if request.mode=='llm' else 'local-rules',
                model=getattr(engine.provider,'model','unknown') if request.mode=='llm' else 'question-bank-adapter-v1',
                created_at=datetime.now(UTC),max_turns=request.max_turns,plan=build_plan(request.jd_text),current=None)
            if learning_context:
                state.learning_observation_id=request.learning_observation_id
                state.learning_allow_historical_version=request.learning_allow_historical_version
                state.learning_condition_hash=learning_context[2]
            if request.use_retrieval:
                if not hasattr(engine,'prepare'):raise WorkspaceConflict('retrieval_interview_not_configured')
                if learning_context:engine.prepare(owner,state,request,self,learning_context=learning_context)
                else:engine.prepare(owner,state,request,self)
            state.current=question_for(state)
            if learning_context:state.current=learning_context[1].model_copy(deep=True,update={'question_id':sid+'-q1'})
            sync_interview(state,owner)
            raw=state.model_dump_json()
            db.execute('INSERT INTO rw_interviews(session_id,owner_id,resume_id,version_id,request_key,request_hash,state_json,state_hash) VALUES(?,?,?,?,?,?,?,?)',
                (sid,owner,resume_id,version.version_id,request.request_key,hashed,raw,digest(raw)))
            return sid

    def _load(self,db,owner,sid):
        row=db.execute('SELECT * FROM rw_interviews WHERE session_id=? AND owner_id=?',(sid,owner)).fetchone()
        if row is None:raise WorkspaceNotFound('interview_not_found')
        if digest(row['state_json'])!=row['state_hash']:raise InvalidProvenance('interview_integrity_failed')
        s=InterviewState.model_validate_json(row['state_json'])
        version=self.workspace._version(db,row['resume_id'],row['version_id'])
        self.workspace._validate_document(db,owner,version.document)
        if s.session_id!=sid or s.resume_id!=row['resume_id'] or s.version_id!=version.version_id or s.version_hash!=version.content_hash or s.revision!=len(s.turns):
            raise InvalidProvenance('interview_integrity_failed')
        original=InterviewStart(request_key='integrity-check',version_id=s.version_id,expected_content_hash=s.version_hash,
            jd_text=s.jd_text,match_id=s.match_id,mode=s.mode,max_turns=s.max_turns,use_retrieval=s.use_retrieval,
            track=s.track,project_id=s.project_id,snapshot_id=s.snapshot_id,prior_session_id=s.prior_session_id,
            learning_observation_id=s.learning_observation_id,learning_allow_historical_version=s.learning_allow_historical_version)
        if digest(s.resume_id+original.stable_json())!=row['request_hash']:
            raise InvalidProvenance('interview_request_integrity_failed')
        if s.execution:
            try:s.execution.validate_binding(owner,sid,interview_identity(s))
            except ValueError as exc:raise InvalidProvenance('interview_execution_integrity_failed') from exc
            if s.execution.revision!=s.revision:raise InvalidProvenance('interview_execution_revision_changed')
        if s.use_retrieval:
            if s.bound_owner!=owner:raise InvalidProvenance('interview_reference_scope_changed')
            refs=[r for t in s.plan for r in t.references]+[r for t in s.turns for r in t.question.references]
            for pack in s.evidence_packs:
                scope=pack.plan.scope
                if scope.kind=='private_project' and (scope.owner_id!=owner or scope.project_id!=s.project_id or scope.snapshot_id!=s.snapshot_id):
                    raise InvalidProvenance('interview_evidence_pack_scope_changed')
                for item in pack.items:
                    ref=item.reference
                    if scope.kind=='private_project' and ref.scope!='private_project':raise InvalidProvenance('interview_evidence_pack_scope_changed')
                    if scope.kind!='private_project' and (ref.scope!='public_knowledge' or scope.public_versions.get(ref.source_id)!=ref.snapshot_id):
                        raise InvalidProvenance('interview_evidence_pack_scope_changed')
                    refs.append(ref)
            if s.current:refs+=s.current.references
            contextual=[*s.plan,*[t.question for t in s.turns],*([s.current] if s.current else [])]
            for item in contextual:
                context=item.evidence_boundary
                if context is not None and (context.reference_ids!=[r.evidence_id for r in item.references]
                        or any(r.scope!='private_project' or r.snapshot_id!=context.snapshot_id for r in item.references)):
                    raise InvalidProvenance('interview_evidence_boundary_changed')
            seen=set()
            for ref in refs:
                reference_key=ref.model_dump_json()
                if reference_key in seen:continue
                seen.add(reference_key)
                if ref.scope=='private_project':
                    if ref.project_id!=s.project_id or ref.snapshot_id!=s.snapshot_id:raise InvalidProvenance('interview_reference_scope_changed')
                    self.code.validate_reference(owner,ref,db=self.code.citation_connection(db,self.workspace))
                elif ref.scope=='public_knowledge':self.public.repository.validate_reference(ref,db=db)
                else:raise InvalidProvenance('interview_reference_scope_changed')
        return row,s,version

    def get(self,owner,sid):
        with self.workspace._connection() as db:
            row,s,_=self._load(db,owner,sid)
            head=self.workspace._resume(db,owner,s.resume_id)['head_version_id']
            # Explicit projection. No state.model_dump in the live API.
            def public(q):return PublicQuestion(**{k:getattr(q,k) for k in PublicQuestion.model_fields}) if q else None
            return InterviewView(session_id=sid,resume_id=s.resume_id,version_id=s.version_id,version_hash=s.version_hash,
                jd_text=s.jd_text,match_id=s.match_id,mode=s.mode,provider=s.provider,model=s.model,status=s.status,revision=s.revision,max_turns=s.max_turns,
                created_at=s.created_at,current=public(s.current),turns=[PublicTurn(question=public(t.question),answer=t.answer) for t in s.turns],
                messages=s.messages,usage=s.usage,answer_pending=s.pending is not None,
                track=s.track,use_retrieval=s.use_retrieval,project_id=s.project_id,snapshot_id=s.snapshot_id,tool_trace=s.tool_trace,tool_calls=s.tool_calls,
                resumable=s.pending is not None and not s.model_inflight and s.status=='active' and
                    (not row['execution_token'] or row['lease_until']<=time()),model_inflight=s.model_inflight,error_code=s.error_code,
                version_is_current=head==s.version_id,warnings=[
                    '题库技术练习，不代表真实面试表现或录用概率；本地仅按词面线索评估。',
                    '绑定本次简历版本/JD，之后编辑不会改变本场；C1 自述未独立核实，缺少材料不等于没有能力。',
                    '进行中隐藏参考要点与详细评价，结束后复盘；本次不会写简历或投递。'])

    def list(self,owner,resume_id):
        with self.workspace._connection() as db:
            self.workspace._resume(db,owner,resume_id)
            rows=db.execute('SELECT session_id FROM rw_interviews WHERE owner_id=? AND resume_id=? ORDER BY rowid DESC LIMIT 100',(owner,resume_id)).fetchall()
            return [{'session_id':sid,'version_id':s.version_id,'status':s.status,'revision':s.revision,'created_at':s.created_at}
                    for sid,s in [(row['session_id'],self._load(db,owner,row['session_id'])[1]) for row in rows]]

    def answer(self,owner,sid,request):
        hashed=digest(request.model_dump_json(exclude={'allow_external_processing','request_key'}))
        with self.workspace._connection(write=True) as db:
            row,s,_=self._load(db,owner,sid)
            old=db.execute('SELECT * FROM rw_interview_answers WHERE session_id=? AND request_key=?',(sid,request.request_key)).fetchone()
            if old:
                if old['request_hash']!=hashed:raise WorkspaceConflict('interview_answer_key_conflict')
                return False # Never re-dispatch a saved answer automatically.
            if s.status!='active' or s.pending is not None:raise WorkspaceConflict('interview_not_ready')
            if s.revision!=request.expected_revision or s.current.question_id!=request.question_id:raise WorkspaceConflict('interview_question_changed')
            s.pending=PendingAnswer(request_key=request.request_key,answer=request.answer);s.next_node='evaluator'
            sync_interview(s,owner)
            raw=s.model_dump_json()
            db.execute('UPDATE rw_interviews SET state_json=?,state_hash=? WHERE session_id=?',(raw,digest(raw),sid))
            db.execute('INSERT INTO rw_interview_answers VALUES(?,?,?,?)',(sid,request.request_key,hashed,'pending'))
            return True

    def claim(self,owner,sid):
        with self.workspace._connection(write=True) as db:
            row,s,v=self._load(db,owner,sid)
            if row['execution_token'] and row['lease_until']>time():raise WorkspaceConflict('interview_in_progress')
            if s.model_inflight:raise WorkspaceConflict('interview_uncertain_model_call')
            if s.status!='active' or not s.pending:raise WorkspaceConflict('interview_not_resumable')
            token=uuid4().hex
            execution=sync_interview(s,owner)
            if execution.execution_token is not None:execution.attempt+=1
            execution.execution_token=token;execution.lease_until=time()+600
            db.execute('UPDATE rw_interviews SET execution_token=?,lease_until=? WHERE session_id=?',(token,time()+600,sid))
            return token,s,v

    def checkpoint(self,owner,sid,token,state):
        sync_interview(state,owner)
        raw=state.model_dump_json()
        with self.workspace._connection(write=True) as db:
            row,previous,_=self._load(db,owner,sid)
            if row['execution_token']!=token:raise WorkspaceConflict('interview_execution_changed')
            db.execute('UPDATE rw_interviews SET state_json=?,state_hash=?,lease_until=? WHERE session_id=?',(raw,digest(raw),time()+600,sid))
            if previous.pending and state.pending is None:
                db.execute("UPDATE rw_interview_answers SET status='complete' WHERE session_id=? AND request_key=?",(sid,previous.pending.request_key))

    def release(self,owner,sid,token):
        with self.workspace._connection(write=True) as db:db.execute('UPDATE rw_interviews SET execution_token=NULL,lease_until=0 WHERE session_id=? AND owner_id=? AND execution_token=?',(sid,owner,token))

    def finish(self,owner,sid,revision):
        with self.workspace._connection(write=True) as db:
            row,s,_=self._load(db,owner,sid)
            if s.status=='complete':return
            if s.revision!=revision:raise WorkspaceConflict('interview_question_changed')
            if s.pending or s.model_inflight or row['execution_token']:raise WorkspaceConflict('interview_in_progress')
            s.status='complete';s.current=None
            sync_interview(s,owner)
            raw=s.model_dump_json();db.execute('UPDATE rw_interviews SET state_json=?,state_hash=? WHERE session_id=?',(raw,digest(raw),sid))

    def set_paused(self,owner,sid,revision,paused):
        with self.workspace._connection(write=True) as db:
            row,s,_=self._load(db,owner,sid)
            if s.revision!=revision:raise WorkspaceConflict('interview_question_changed')
            if s.pending or s.model_inflight or row['execution_token']:raise WorkspaceConflict('interview_in_progress')
            if s.status not in ('active','paused'):raise WorkspaceConflict('interview_already_terminal')
            s.status='paused' if paused else 'active'
            sync_interview(s,owner)
            raw=s.model_dump_json();db.execute('UPDATE rw_interviews SET state_json=?,state_hash=? WHERE session_id=?',(raw,digest(raw),sid))

    def review(self,owner,sid):
        with self.workspace._connection() as db:
            _,s,_=self._load(db,owner,sid)
            if s.status!='complete':raise WorkspaceConflict('interview_review_not_available')
            topics={t.anchor_id:t for t in s.plan}
            from job_agent.resume_workspace.learning import withdrawn_questions
            withdrawn=withdrawn_questions(db,owner,sid)
            comparison=None
            if s.prior_session_id:
                try:_,previous,_=self._load(db,owner,s.prior_session_id)
                except (WorkspaceNotFound,WorkspaceConflict,InvalidProvenance):previous=None
                prior_withdrawn=withdrawn_questions(db,owner,s.prior_session_id)
                old_topics={t.anchor_id:t for t in previous.plan} if previous else {}
                old_turns={t.question.topic_id:t for t in previous.turns} if previous else {}
                new_turns={t.question.topic_id:t for t in s.turns}
                same_model=previous and (s.mode,s.provider,s.model,s.version_hash,s.jd_text)==(previous.mode,previous.provider,previous.model,previous.version_hash,previous.jd_text)
                comparable=[k for k in new_turns if k in old_turns and same_model and
                    new_turns[k].question.question_id not in withdrawn and old_turns[k].question.question_id not in prior_withdrawn and
                    topics[k].points==old_topics[k].points and topics[k].aliases==old_topics[k].aliases and
                    new_turns[k].question.prompt==old_turns[k].question.prompt and
                    new_turns[k].question.focus_id==old_turns[k].question.focus_id and
                    [(r.snapshot_id,r.path,r.start_line,r.end_line,r.content_hash) for r in new_turns[k].question.references]==
                    [(r.snapshot_id,r.path,r.start_line,r.end_line,r.content_hash) for r in old_turns[k].question.references] and
                    (new_turns[k].evaluation.method_version,new_turns[k].evaluation.assessment_mode)==
                    (old_turns[k].evaluation.method_version,old_turns[k].evaluation.assessment_mode) and
                    new_turns[k].question.evidence_boundary==old_turns[k].question.evidence_boundary]
                comparison={'prior_session_id':s.prior_session_id,'basis':'last answered turn per identical question/references/rubric/aliases/model/evaluation method; reference only',
                    'status':'comparable' if comparable else 'not_comparable','topics':[
                        {'topic_id':k,'before_covered':len(old_turns[k].evaluation.covered_ids),
                         'after_covered':len(new_turns[k].evaluation.covered_ids),'total':len(topics[k].points)} for k in comparable],
                    'warning':'题目或评价条件不一致时不计算提升；词面要点变化不能证明能力或真实教学效果。'}
            return {'session_id':sid,'scope':'规则参考' if s.mode=='local_demo' else '模型参考，非真实性证明',
                'practice_comparison':comparison,
                'track':s.track,'source_boundary':'通用知识/源码实现/个人贡献分别判断；源码存在和测试文件不代表已运行或本人完成。',
                'weaknesses':[{'topic_id':t.question.topic_id,'question':t.question.prompt,'missing':t.evaluation.missing_ids} for t in s.turns if t.evaluation.missing_ids and t.question.question_id not in withdrawn],
                'code_references':[r.model_dump(mode='json') for t in s.turns for r in t.question.references if r.scope=='private_project'],
                'turns':[{'question_id':t.question.question_id,'question':t.question.prompt,'answer':t.answer,'assessment_withdrawn':t.question.question_id in withdrawn,
                    'evidence_boundary':t.question.evidence_boundary.model_dump(mode='json') if t.question.evidence_boundary else None,
                    'covered':[topics[t.question.topic_id].points[k] for k in t.evaluation.covered_ids],
                    'missing':[topics[t.question.topic_id].points[k] for k in t.evaluation.missing_ids],
                    'claim_needs_evidence':t.evaluation.claim_needs_evidence,'note':t.evaluation.note,'decision':t.decision.action} for t in s.turns],
                'assessment_details':[{'question_id':t.question.question_id,'mode':t.evaluation.assessment_mode,
                    'method_version':t.evaluation.method_version,'semantic_assessments_present':bool(t.evaluation.point_assessments),
                    'points':[a.model_dump() for a in t.evaluation.point_assessments]} for t in s.turns],
                'warning':'未覆盖可能是表达或规则识别问题，不代表没有能力；个人经历需补充材料，当前未独立核实。'}
