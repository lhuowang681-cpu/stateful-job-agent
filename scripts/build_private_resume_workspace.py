from __future__ import annotations

import json
from pathlib import Path

from job_agent.evidence.contracts import EvidenceLink, SourceSpan
from job_agent.knowledge.durable import KnowledgeRepository
from job_agent.resume.contracts import ClaimEvidence, DisclosureVisibility
from job_agent.resume.repository import ResumeRepository
from job_agent.resume.service import GroundedResumeService, _claims, _overlap
from job_agent.schemas import EvidenceLevel


KNOWLEDGE_DB = Path("data/private/r10_evidence/jobmatch-state-final/knowledge.sqlite")
OUTPUT_ROOT = Path("data/private/r14_resume_tailoring/state")
SUMMARY = Path("artifacts/r14/resume-workspace-summary.json")


def _best_quote(claim: str, text: str) -> tuple[str, float]:
    candidates = _claims(text)
    if not candidates:
        return text[:500], 0.0
    ranked = sorted(((candidate, _overlap(claim, candidate)) for candidate in candidates), key=lambda item: item[1], reverse=True)
    return ranked[0]


def main() -> None:
    knowledge = KnowledgeRepository(KNOWLEDGE_DB)
    documents = list(knowledge.list_active_documents())
    resume_document = next((document for document in documents if document.source_type == "resume"), None)
    if resume_document is None:
        raise RuntimeError("private candidate resume source is unavailable")
    repository = ResumeRepository.open(OUTPUT_ROOT)
    service = GroundedResumeService(repository)
    version = service.import_text(
        name="Private Candidate Resume",
        text=resume_document.text,
        metadata={
            "source_document_id": resume_document.document_id,
            "source_document_version": resume_document.version,
            "source_content_hash": resume_document.content_hash,
            "private": True,
        },
    )
    initial = service.audit_claims(version.resume_version_id)
    evidence_by_text: dict[str, list[ClaimEvidence]] = {}
    source_documents_used: set[str] = set()
    for claim in initial.claims:
        matches = []
        for document in documents:
            if document.document_id == resume_document.document_id:
                continue
            quote, score = _best_quote(claim.canonical_claim, document.text)
            if score < 0.6 or not quote:
                continue
            start = document.text.find(quote)
            if start < 0:
                continue
            visibility = (
                DisclosureVisibility.ANONYMIZED_ONLY
                if document.source_type == "research"
                else DisclosureVisibility.RESUME_SAFE
            )
            link_id = f"resume-audit-{claim.claim_id}-{document.document_id}"
            matches.append(
                ClaimEvidence(
                    evidence_link=EvidenceLink(
                        link_id=link_id,
                        atom_id=claim.claim_id,
                        source_span=SourceSpan(
                            source_id=document.document_id,
                            content_hash=document.content_hash,
                            start_offset=start,
                            end_offset=start + len(quote),
                            exact_quote=quote,
                        ),
                        claim=claim.canonical_claim,
                        support_status="supported",
                        level=EvidenceLevel.C2,
                        confidence=min(1.0, score),
                    ),
                    knowledge_document_id=document.document_id,
                    knowledge_document_version=document.version,
                    knowledge_content_hash=document.content_hash,
                    visibility=visibility,
                    anonymized_text=(
                        "Anonymous multimodal/model research evidence."
                        if visibility == DisclosureVisibility.ANONYMIZED_ONLY
                        else None
                    ),
                )
            )
            source_documents_used.add(document.document_id)
        if matches:
            evidence_by_text[claim.canonical_claim] = matches
    audit = service.audit_claims(
        version.resume_version_id,
        evidence_by_text=evidence_by_text,
    )
    summary = {
        "schema_version": 1,
        "resumes": len(repository.list_resumes()),
        "versions": len(repository.list_versions(version.resume_id)),
        "sections": len(version.sections),
        "bullets": sum(len(section.items) for section in version.sections),
        "claims": len(audit.claims),
        "claim_audit": {
            "supported": audit.supported,
            "unverified": audit.unverified,
            "conflict": audit.conflict,
            "gap": audit.gap,
            "numeric_claims": audit.numeric_claims,
            "technology_claims": audit.technology_claims,
        },
        "source_documents_available": len(documents) - 1,
        "source_documents_used": len(source_documents_used),
        "matching_policy": "deterministic lexical overlap >= 0.60; resume source cannot self-verify",
        "private_state": str(OUTPUT_ROOT),
        "privacy": "No resume text, source quote, person name, or private document identifier is included in this artifact.",
    }
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
