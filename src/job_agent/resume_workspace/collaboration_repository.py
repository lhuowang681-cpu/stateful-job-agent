"""Application checkpoints, lease fencing and human decisions for M3B.

SQLite transactions guard a single-machine demo; this is not the legacy
PostgreSQL/Redis worker or a native LangGraph checkpointer implementation.
"""
from __future__ import annotations

import json
from datetime import datetime, UTC
from time import time
from uuid import uuid4

from job_agent.resume_workspace.collaboration import draft_hash, eligible_facts, hard_review
from job_agent.resume_workspace.collaboration_contracts import (
    CollaborationState, CollaborationSummary, CollaborationView, CollaborationDecisionResult, ProposalVerification,
)
from job_agent.resume_workspace.contracts import ResumeDocument
from job_agent.resume_workspace.matching import digest
from job_agent.resume_workspace.repository import InvalidProvenance, WorkspaceConflict, WorkspaceNotFound


DDL='''
CREATE TABLE IF NOT EXISTS rw_collaborations (
 run_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
 resume_id TEXT NOT NULL REFERENCES rw_resumes(resume_id) ON DELETE CASCADE,
 version_id TEXT NOT NULL REFERENCES rw_versions(version_id) ON DELETE CASCADE,
 request_key TEXT NOT NULL, request_json TEXT NOT NULL, request_hash TEXT NOT NULL,
 state_json TEXT NOT NULL, state_hash TEXT NOT NULL,
 checkpoint_revision INTEGER NOT NULL DEFAULT 0,
 expected_head TEXT NOT NULL, execution_token TEXT, lease_until REAL NOT NULL DEFAULT 0,
 UNIQUE(owner_id,request_key)
);
CREATE INDEX IF NOT EXISTS rw_collaborations_resume ON rw_collaborations(owner_id,resume_id);
CREATE TABLE IF NOT EXISTS rw_collaboration_decisions (
 run_id TEXT NOT NULL REFERENCES rw_collaborations(run_id) ON DELETE CASCADE,
 proposal_id TEXT NOT NULL, decision TEXT NOT NULL,
 accepted_version_id TEXT REFERENCES rw_versions(version_id) ON DELETE CASCADE,
 PRIMARY KEY(run_id,proposal_id)
);
'''


class CollaborationRepository:
    def __init__(self,workspace):
        self.workspace=workspace
        with workspace._connection() as db:db.executescript(DDL)

    def begin(self,owner,resume_id,request,engine):
        raw=request.model_dump_json(exclude={'request_key','allow_external_processing'})
        hashed=digest(resume_id+raw)
        with self.workspace._connection(write=True) as db:
            self.workspace._resume(db,owner,resume_id)
            version=self.workspace._version(db,resume_id,request.version_id)
            self.workspace._validate_document(db,owner,version.document)
            if version.content_hash!=request.expected_content_hash:raise WorkspaceConflict('collaboration_version_changed')
            existing=db.execute('SELECT * FROM rw_collaborations WHERE owner_id=? AND request_key=?',(owner,request.request_key)).fetchone()
            if existing:
                if existing['request_hash']!=hashed:raise WorkspaceConflict('collaboration_request_key_conflict')
                return existing['run_id'],False
            rid='collab-'+uuid4().hex
            state=CollaborationState(run_id=rid,resume_id=resume_id,version_id=version.version_id,
                version_hash=version.content_hash,jd_text=request.jd_text,mode=request.mode,
                provider=str(getattr(engine.provider,'provider_name','unknown')) if request.mode=='llm' else 'local-rules',
                model=str(getattr(engine.provider,'model','unknown')) if request.mode=='llm' else 'extractive-demo-v1',
                created_at=datetime.now(UTC))
            encoded=state.model_dump_json()
            db.execute('INSERT INTO rw_collaborations(run_id,owner_id,resume_id,version_id,request_key,request_json,request_hash,state_json,state_hash,expected_head) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (rid,owner,resume_id,version.version_id,request.request_key,raw,hashed,encoded,digest(encoded),version.version_id))
            return rid,True

    def _load(self,db,owner,rid):
        row=db.execute('SELECT * FROM rw_collaborations WHERE run_id=? AND owner_id=?',(rid,owner)).fetchone()
        if row is None:raise WorkspaceNotFound('collaboration_not_found')
        if digest(row['state_json'])!=row['state_hash'] or digest(row['resume_id']+row['request_json'])!=row['request_hash']:
            raise InvalidProvenance('collaboration_integrity_failed')
        state=CollaborationState.model_validate_json(row['state_json'])
        version=self.workspace._version(db,row['resume_id'],row['version_id'])
        self.workspace._validate_document(db,owner,version.document)
        req=json.loads(row['request_json'])
        if (state.run_id!=rid or state.version_id!=version.version_id or state.version_hash!=version.content_hash
            or state.resume_id!=row['resume_id'] or state.jd_text!=req['jd_text'] or state.mode!=req['mode']):
            raise InvalidProvenance('collaboration_integrity_failed')
        for d in state.drafts:
            if d.draft_hash!=draft_hash(d.draft) or (d.feedback is not None and
                (d.feedback.draft_hash!=d.draft_hash or d.feedback.draft_revision!=d.revision)):
                raise InvalidProvenance('collaboration_draft_integrity_failed')
        return row,state,version

    def claim(self,owner,rid):
        with self.workspace._connection(write=True) as db:
            row,state,version=self._load(db,owner,rid)
            if row['execution_token'] and row['lease_until']>time():raise WorkspaceConflict('collaboration_in_progress')
            if state.model_inflight:raise WorkspaceConflict('collaboration_uncertain_model_call')
            if state.next_node=='end' or state.status=='failed':raise WorkspaceConflict('collaboration_not_resumable')
            token=uuid4().hex
            db.execute('UPDATE rw_collaborations SET execution_token=?,lease_until=? WHERE run_id=?',(token,time()+600,rid))
            return token,state,version

    def checkpoint(self,owner,rid,token,state):
        encoded=state.model_dump_json()
        with self.workspace._connection(write=True) as db:
            row,_,_=self._load(db,owner,rid)
            if row['execution_token']!=token:raise WorkspaceConflict('collaboration_execution_changed')
            db.execute('UPDATE rw_collaborations SET state_json=?,state_hash=?,checkpoint_revision=checkpoint_revision+1,lease_until=? WHERE run_id=?',
                (encoded,digest(encoded),time()+600,rid))

    def release(self,owner,rid,token):
        with self.workspace._connection(write=True) as db:
            db.execute('UPDATE rw_collaborations SET execution_token=NULL,lease_until=0 WHERE run_id=? AND owner_id=? AND execution_token=?',(rid,owner,token))

    def _view(self,db,owner,rid):
        row,state,version=self._load(db,owner,rid)
        head=self.workspace._resume(db,owner,row['resume_id'])['head_version_id']
        decisions=db.execute('SELECT * FROM rw_collaboration_decisions WHERE run_id=?',(rid,)).fetchall()
        by_id={x['proposal_id']:x for x in decisions}
        checks=[]
        if state.drafts:
            d=state.drafts[-1]; feedback={i.proposal_id:i for i in d.feedback.items} if d.feedback else {}
            for p in d.draft.proposals:
                fact=eligible_facts(version).get(p.source_path)
                exact=fact is not None and p.text==fact.text
                item=feedback.get(p.proposal_id)
                relevance='not_reviewed' if item is None else 'keyword_lead' if item.outcome=='accept' and state.mode=='local_demo' else 'model_recommends' if item.outcome=='accept' else item.outcome
                decision=by_id.get(p.proposal_id)
                confirmation='not_saved'
                if decision and decision['accepted_version_id']:
                    saved=self.workspace._version(db,state.resume_id,decision['accepted_version_id'])
                    confirmation='confirmed' if saved.confirmed_at else 'unconfirmed'
                checks.append(ProposalVerification(proposal_id=p.proposal_id,provenance='matched' if exact else 'not_matched',
                    statement='exact_copy' if exact else 'changed_or_unknown',relevance=relevance,
                    user_decision=decision['decision'] if decision else 'pending',resume_confirmation=confirmation))
        return CollaborationView(state=state,checkpoint_revision=row['checkpoint_revision'],expected_head_version_id=row['expected_head'],
            can_apply=head==row['expected_head'] and state.status=='awaiting_approval',
            decisions={x['proposal_id']:x['decision'] for x in decisions},
            accepted_version_ids={x['proposal_id']:x['accepted_version_id'] for x in decisions if x['accepted_version_id']},
            resumable=state.next_node!='end' and state.status!='failed' and not state.model_inflight and
                (not row['execution_token'] or row['lease_until']<=time()),source_facts=eligible_facts(version),verification=checks)

    def get(self,owner,rid):
        with self.workspace._connection() as db:return self._view(db,owner,rid)

    def list(self,owner,resume_id):
        with self.workspace._connection() as db:
            self.workspace._resume(db,owner,resume_id)
            rows=db.execute('SELECT run_id FROM rw_collaborations WHERE owner_id=? AND resume_id=? ORDER BY rowid DESC LIMIT 100',(owner,resume_id)).fetchall()
            result=[]
            for row in rows:
                _,s,_=self._load(db,owner,row['run_id'])
                result.append(CollaborationSummary(run_id=s.run_id,version_id=s.version_id,status=s.status,created_at=s.created_at))
            return result

    def decide(self,owner,rid,proposal_id,request):
        with self.workspace._connection(write=True) as db:
            row,state,base=self._load(db,owner,rid)
            if state.status!='awaiting_approval' or not state.drafts:raise WorkspaceConflict('collaboration_not_approved')
            latest=state.drafts[-1]
            if request.draft_revision!=latest.revision or request.draft_hash!=latest.draft_hash:
                raise WorkspaceConflict('collaboration_draft_changed')
            if not latest.feedback or latest.feedback.draft_hash!=latest.draft_hash:raise WorkspaceConflict('collaboration_not_approved')
            p=next((p for p in latest.draft.proposals if p.proposal_id==proposal_id),None)
            items=latest.feedback.items
            if (p is None or len(items)!=len(latest.draft.proposals) or len({i.proposal_id for i in items})!=len(items)
                or {i.proposal_id for i in items}!={p.proposal_id for p in latest.draft.proposals}
                or any(i.outcome!='accept' or i.issue_code!='none' for i in items) or hard_review(latest.draft,base)):
                raise WorkspaceConflict('collaboration_not_approved')
            previous=db.execute('SELECT * FROM rw_collaboration_decisions WHERE run_id=? AND proposal_id=?',(rid,proposal_id)).fetchone()
            decision='accepted' if request.action=='accept' else 'rejected'
            if previous:
                if previous['decision']!=decision:raise WorkspaceConflict('proposal_already_decided')
                ver=self.workspace._version(db,state.resume_id,previous['accepted_version_id']) if previous['accepted_version_id'] else None
                return CollaborationDecisionResult(collaboration=self._view(db,owner,rid),version=ver)
            version=None
            if request.action=='accept':
                resume=self.workspace._resume(db,owner,state.resume_id)
                if resume['head_version_id']!=row['expected_head'] or request.expected_parent_version_id!=row['expected_head']:
                    raise WorkspaceConflict('resume_head_changed')
                current=self.workspace._version(db,state.resume_id,row['expected_head'])
                # Only our own checked accepts may advance expected_head. Revalidate sources at append.
                if len(current.document.summary)>=10 or p.text in {f.text for f in current.document.summary}:
                    raise WorkspaceConflict('proposal_no_longer_applicable')
                fact=eligible_facts(base)[p.source_path].model_copy(deep=True)
                fact.fact_id='summary-'+digest(rid+':'+p.proposal_id)[:40]
                document=current.document.model_copy(deep=True)
                document.summary.append(fact)
                document=ResumeDocument.model_validate(document.model_dump())
                version=self.workspace._append(db,owner,state.resume_id,document,sequence=current.sequence+1,
                    parent=current.version_id,note='用户接受协作原文摘要摘录（保留 C1 来源，未自由改写）')
                db.execute('UPDATE rw_collaborations SET expected_head=? WHERE run_id=?',(version.version_id,rid))
            db.execute('INSERT INTO rw_collaboration_decisions VALUES(?,?,?,?)',(rid,proposal_id,decision,version.version_id if version else None))
            return CollaborationDecisionResult(collaboration=self._view(db,owner,rid),version=version)
