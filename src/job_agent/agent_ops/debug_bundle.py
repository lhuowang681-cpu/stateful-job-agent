from __future__ import annotations

import json
import zipfile
from pathlib import Path

from job_agent.agent_ops.analysis import analyze_tool_necessity, trace_metrics
from job_agent.agent_ops.contracts import PrivacyLevel
from job_agent.agent_ops.privacy import redact
from job_agent.agent_ops.repository import SQLiteTraceRepository


def build_debug_bundle(
    repository: SQLiteTraceRepository,
    trace_id: str,
    destination: Path | str,
) -> Path:
    trace = repository.get(trace_id)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    trace_payload = redact(trace.model_dump(mode="json"), level=PrivacyLevel.REDACTED)
    summary = trace_metrics([trace]).model_dump(mode="json")
    necessity = analyze_tool_necessity(trace)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("trace.json", json.dumps(trace_payload, ensure_ascii=False, indent=2))
        archive.writestr("metrics.json", json.dumps(summary, ensure_ascii=False, indent=2))
        archive.writestr("tool_necessity.json", json.dumps(necessity, ensure_ascii=False, indent=2))
        archive.writestr(
            "README.txt",
            "Redacted Job Agent debug bundle. Private model inputs, career documents, credentials, and source bodies are excluded.\n",
        )
    return destination
