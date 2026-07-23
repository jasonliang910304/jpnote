"""Small structured result types shared by the CLI and future API adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class DuplicateWarning:
    code: str
    incoming_key: str
    other_key: str
    reason: str
    scope: str
    severity: str = "review"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ImportPlan:
    source: str
    items: list[dict[str, Any]]
    attempts: list[dict[str, Any]]
    warnings: list[DuplicateWarning] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "items": [
                {key: value for key, value in item.items() if not key.startswith("_")}
                for item in self.items
            ],
            "attempts": [
                {key: value for key, value in attempt.items() if not key.startswith("_")}
                for attempt in self.attempts
            ],
            "warnings": [warning.to_dict() for warning in self.warnings],
            "notes": list(self.notes),
        }


@dataclass(slots=True)
class ImportResult:
    added_entries: int = 0
    updated_entries: int = 0
    unchanged_entries: int = 0
    added_attempts: int = 0
    skipped_attempts: int = 0
    added_relations: int = 0
    updated_relations: int = 0
    pending_relations: int = 0
    resolved_relations: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AuditIssue:
    code: str
    severity: str
    fixable: bool
    key: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
