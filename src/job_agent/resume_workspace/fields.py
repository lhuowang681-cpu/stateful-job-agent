"""One field-path allowlist shared by parser materialization and reviewed edits."""
from __future__ import annotations

import re

from job_agent.resume_workspace.parsing_contracts import ParseError


_PERSONAL = {"name", "email", "phone", "location"}
_SCALARS = {
    "education": {"school", "degree", "major", "period"},
    "experience": {"organization", "role", "period"},
    "projects": {"name", "role", "period"},
}
_LIMITS = {"education": 10, "experience": 20, "projects": 30, "summary": 10, "skills": 60}


def checked_path(path: str) -> list[str | int]:
    parts = path.split(".")

    def index(value: str, limit: int) -> int:
        if not re.fullmatch(r"0|[1-9][0-9]?", value) or int(value) >= limit:
            raise ParseError("invalid_field_path")
        return int(value)

    if len(parts) == 2 and parts[0] == "personal" and parts[1] in _PERSONAL:
        return parts
    if len(parts) == 3 and parts[:2] == ["personal", "links"]:
        return ["personal", "links", index(parts[2], 10)]
    if len(parts) == 2 and parts[0] in {"summary", "skills"}:
        return [parts[0], index(parts[1], _LIMITS[parts[0]])]
    if len(parts) in {3, 4} and parts[0] in _SCALARS:
        entry = index(parts[1], _LIMITS[parts[0]])
        if len(parts) == 3 and parts[2] in _SCALARS[parts[0]]:
            return [parts[0], entry, parts[2]]
        list_name = "highlights" if parts[0] == "education" else "bullets"
        if len(parts) == 4 and parts[2] == list_name:
            return [parts[0], entry, list_name, index(parts[3], 20 if list_name == "highlights" else 30)]
    raise ParseError("invalid_field_path")


def set_field(document: dict, path: str, value: dict | None) -> None:
    parts = checked_path(path)
    current = document
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if isinstance(part, int):
            while len(current) <= part:
                current.append(None)
            if last:
                current[part] = value
            else:
                if current[part] is None:
                    current[part] = {"entry_id": f"{parts[0]}-{part}"} if i == 1 and parts[0] in _SCALARS else {}
                current = current[part]
        elif last:
            current[part] = value
        else:
            if part not in current:
                current[part] = [] if isinstance(parts[i + 1], int) else {}
            current = current[part]


def compact(document: dict) -> dict:
    """Drop removed list values; dict None retains a missing required draft field."""
    def visit(value):
        if isinstance(value, list):
            return [visit(item) for item in value if item is not None]
        if isinstance(value, dict):
            return {key: visit(item) for key, item in value.items()}
        return value
    return visit(document)
