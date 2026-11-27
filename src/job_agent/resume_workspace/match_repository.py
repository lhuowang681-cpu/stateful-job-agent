"""SQLite match snapshots and transactional acceptance of order-only suggestions."""
from __future__ import annotations

import json
from uuid import uuid4

from job_agent.resume_workspace.contracts import ResumeDocument
from job_agent.resume_workspace.match_contracts import (
    AnalyzeRequest, DecideProposal, DecisionResult, MatchError, MatchPayload,
    MatchSummary, MatchView, ProposalView,
)
from job_agent.resume_workspace.matching import digest, propose_order, row_views, VersionSourceStore
from job_agent.resume_workspace.repository import (
    InvalidProvenance, SqliteResumeRepository, WorkspaceConflict, WorkspaceNotFound, _now,
)


DDL = """
CREATE TABLE IF NOT EXISTS rw_matches (
    match_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
    resume_id TEXT NOT NULL REFERENCES rw_resumes(resume_id) ON DELETE CASCADE,
    version_id TEXT NOT NULL REFERENCES rw_versions(version_id) ON DELETE CASCADE,
    request_key TEXT NOT NULL, request_hash TEXT NOT NULL, request_json TEXT NOT NULL,
    title TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
    payload_json TEXT, payload_hash TEXT, error_code TEXT, expected_head TEXT NOT NULL,
    UNIQUE(owner_id,request_key)
);
CREATE INDEX IF NOT EXISTS rw_matches_resume ON rw_matches(owner_id,resume_id);
CREATE TABLE IF NOT EXISTS rw_match_decisions (
    match_id TEXT NOT NULL REFERENCES rw_matches(match_id) ON DELETE CASCADE,
    proposal_id TEXT NOT NULL, decision TEXT NOT NULL,
    accepted_version_id TEXT REFERENCES rw_versions(version_id) ON DELETE CASCADE,
    PRIMARY KEY(match_id,proposal_id)
);
"""


class MatchRepository:
    def __init__(self, workspace: SqliteResumeRepository):
        self.workspace = workspace
        with workspace._connection() as db:
            db.executescript(DDL)

    def begin(self, owner: str, resume_id: str, request: AnalyzeRequest):
        encoded = request.model_dump_json(exclude={'request_key','allow_external_processing'})
        request_hash = digest(resume_id + encoded)
        with self.workspace._connection(write=True) as db:
            self.workspace._resume(db,owner,resume_id)
            version = self.workspace._version(db,resume_id,request.version_id)
            self.workspace._validate_document(db,owner,version.document)
            if version.content_hash != request.expected_content_hash:
                raise WorkspaceConflict('match_version_changed')
            existing = db.execute('SELECT * FROM rw_matches WHERE owner_id=? AND request_key=?',(owner,request.request_key)).fetchone()
            if existing:
                if existing['request_hash'] != request_hash:
                    raise WorkspaceConflict('match_request_key_conflict')
                if existing['status'] == 'running':
                    raise WorkspaceConflict('match_in_progress')
                if existing['status'] == 'failed':
                    raise WorkspaceConflict('match_previous_failed')
                return existing['match_id'], version, False
            match_id = 'match-' + uuid4().hex
            db.execute('INSERT INTO rw_matches VALUES (?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,?)',
                       (match_id,owner,resume_id,version.version_id,request.request_key,request_hash,encoded,
                        request.title,'running',_now(),version.version_id))
            return match_id, version, True

    def _row(self, db, owner, match_id):
        row = db.execute('SELECT * FROM rw_matches WHERE match_id=? AND owner_id=?',(match_id,owner)).fetchone()
        if row is None:raise WorkspaceNotFound('match_not_found')
        return row

    def complete(self, owner: str, match_id: str, payload: MatchPayload):
        with self.workspace._connection(write=True) as db:
            row = self._row(db,owner,match_id)
            if row['status'] != 'running':raise WorkspaceConflict('match_already_finished')
            version = self.workspace._version(db,row['resume_id'],row['version_id'])
            self.workspace._validate_document(db,owner,version.document)
            self._validate_payload(row,payload,version)
            encoded = payload.model_dump_json()
            db.execute("UPDATE rw_matches SET status='complete',payload_json=?,payload_hash=? WHERE match_id=?",
                       (encoded,digest(encoded),match_id))

    def fail(self, owner, match_id, code):
        with self.workspace._connection(write=True) as db:
            db.execute("UPDATE rw_matches SET status='failed',error_code=? WHERE match_id=? AND owner_id=? AND status='running'",
                       (code,match_id,owner))

    @staticmethod
    def _validate_payload(row,payload,version):
        raw = row['request_json']
        if digest(row['resume_id']+raw)!=row['request_hash']:
            raise InvalidProvenance('match_integrity_failed')
        request = json.loads(raw)
        if (payload.match_id!=row['match_id'] or payload.resume_id!=row['resume_id'] or payload.version_id!=version.version_id
            or payload.version_hash!=version.content_hash or payload.jd_text!=request['jd_text']
            or payload.title!=request['title'] or payload.mode!=request['mode']
            or payload.bundle.manifest.run_id!=row['match_id']):
            raise InvalidProvenance('match_integrity_failed')
        row_views(payload,version)  # Hash/quote/C1/JD exclusion validated on write and read.
        expected = propose_order(version,VersionSourceStore(version,payload.jd_text),payload.bundle)
        if payload.proposals != expected:
            raise InvalidProvenance('match_proposals_changed')

    def _load(self, db, owner, match_id):
        row = self._row(db,owner,match_id)
        if row['status'] != 'complete':raise WorkspaceConflict('match_not_complete')
        if digest(row['payload_json'])!=row['payload_hash']:
            raise InvalidProvenance('match_integrity_failed')
        payload = MatchPayload.model_validate_json(row['payload_json'])
        version = self.workspace._version(db,row['resume_id'],row['version_id'])
        self.workspace._validate_document(db,owner,version.document)
        self._validate_payload(row,payload,version)
        return row, payload, version

    def _view(self, db, owner, match_id):
        row,payload,version = self._load(db,owner,match_id)
        head = self.workspace._resume(db,owner,row['resume_id'])['head_version_id']
        decisions = {r['proposal_id']:r for r in db.execute('SELECT * FROM rw_match_decisions WHERE match_id=?',(match_id,))}
        proposals = [ProposalView(**p.model_dump(),decision=decisions[p.proposal_id]['decision'] if p.proposal_id in decisions else 'pending',
                                 accepted_version_id=decisions[p.proposal_id]['accepted_version_id'] if p.proposal_id in decisions else None)
                     for p in payload.proposals]
        return MatchView(match_id=match_id,resume_id=row['resume_id'],version_id=version.version_id,version_hash=version.content_hash,
                         title=payload.title,jd_text=payload.jd_text,mode=payload.mode,provider=payload.bundle.manifest.provider,model=payload.bundle.manifest.model,
                         usage=payload.usage,created_at=payload.created_at,expected_head_version_id=row['expected_head'],can_apply=head==row['expected_head'],
                         rows=row_views(payload,version),proposals=proposals,warnings=[
                            '本分析绑定所选版本和 JD 快照，不随之后的编辑自动更新。',
                            '简历和人工补充均为 C1 自述；缺少材料不等于没有能力，确认不会升级证据。',
                            '本地仅按条目和术语预检查，未作语义核验。' if payload.mode=='local_check' else '模型语义结论需要核对原文，来源校验不证明经历真实。',
                            '调整建议只移动已有条目，不生成新事实；排序后仍需最终确认。'])

    def get(self, owner, match_id):
        with self.workspace._connection() as db:
            return self._view(db,owner,match_id)

    def list(self, owner, resume_id):
        with self.workspace._connection() as db:
            self.workspace._resume(db,owner,resume_id)
            rows = db.execute('SELECT * FROM rw_matches WHERE owner_id=? AND resume_id=? ORDER BY created_at DESC,match_id DESC LIMIT 100',(owner,resume_id)).fetchall()
            return [MatchSummary(**{k:r[k] for k in MatchSummary.model_fields}) for r in rows]

    def decide(self, owner, match_id, proposal_id, request: DecideProposal):
        with self.workspace._connection(write=True) as db:
            row,payload,_ = self._load(db,owner,match_id)
            proposal = next((p for p in payload.proposals if p.proposal_id==proposal_id),None)
            if proposal is None:raise WorkspaceNotFound('proposal_not_found')
            previous = db.execute('SELECT * FROM rw_match_decisions WHERE match_id=? AND proposal_id=?',(match_id,proposal_id)).fetchone()
            decision = 'accepted' if request.action=='accept' else 'rejected'
            if previous:
                if previous['decision']!=decision:raise WorkspaceConflict('proposal_already_decided')
                version = self.workspace._version(db,row['resume_id'],previous['accepted_version_id']) if previous['accepted_version_id'] else None
                return DecisionResult(match=self._view(db,owner,match_id),version=version)
            version = None
            if request.action=='accept':
                resume = self.workspace._resume(db,owner,row['resume_id'])
                if resume['head_version_id']!=row['expected_head'] or request.expected_parent_version_id!=row['expected_head']:
                    raise WorkspaceConflict('resume_head_changed')
                current = self.workspace._version(db,row['resume_id'],row['expected_head'])
                document = current.document.model_copy(deep=True)
                entries = getattr(document,proposal.section)
                index = next((i for i,e in enumerate(entries) if (e.fact_id if proposal.section=='skills' else e.entry_id)==proposal.target_id),None)
                if index is None or index==0:raise WorkspaceConflict('proposal_no_longer_applicable')
                entries.insert(0,entries.pop(index))
                document = ResumeDocument.model_validate(document.model_dump())
                # Reordering can never mutate/add/remove the actual fact inventory.
                before = sorted(f.model_dump_json() for f in current.document.facts())
                after = sorted(f.model_dump_json() for f in document.facts())
                if before!=after:raise MatchError('proposal_changed_facts')
                version = self.workspace._append(db,owner,row['resume_id'],document,sequence=current.sequence+1,
                                                 parent=current.version_id,note='按 JD 相关线索调整既有条目顺序（无新增事实）')
                db.execute('UPDATE rw_matches SET expected_head=? WHERE match_id=?',(version.version_id,match_id))
            db.execute('INSERT INTO rw_match_decisions VALUES (?,?,?,?)',(match_id,proposal_id,decision,version.version_id if version else None))
            return DecisionResult(match=self._view(db,owner,match_id),version=version)
