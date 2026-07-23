"""Stable identity helpers for imported historical attempt records.

This module intentionally has no repository/validation dependencies so both the
import boundary and database layer can use the same identity contract without a
circular import.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any


def _locator_text(value: Any) -> str:
    """Normalize harmless locator formatting differences.

    Historical workbook locators are often regenerated as ``問題3``, ``問題 3``
    or ``問題３``.  NFKC plus whitespace removal makes those equivalent without
    trying to guess that semantically different labels (for example ``第3大題``)
    are the same question.
    """
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return re.sub(r"\s+", "", text)


def _prompt_fallback(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return re.sub(r"\s+", " ", text)


def _answer_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return re.sub(r"\s+", " ", text)


def attempt_identity_payload(attempt: dict[str, Any]) -> dict[str, Any]:
    """Return the stable fields that identify one historical learner attempt.

    Explanation/correction metadata and linked-entry order are enrichment, not
    identity.  Source/section/question are compatibility-normalized so harmless
    full-width digits or spaces do not create duplicate historical attempts.
    The prompt is only a fallback when a source+question locator is unavailable.
    """
    source = _locator_text(attempt.get("source", ""))
    section = _locator_text(attempt.get("section", ""))
    question = _locator_text(attempt.get("question", ""))
    user_order = attempt.get("user_order", [])
    return {
        "date": str(attempt.get("date", "") or ""),
        "source": source,
        "section": section,
        "question": question,
        "question_type": _locator_text(attempt.get("question_type", "")),
        # v0.6.3 omitted prompt whenever source+question existed. That could
        # collide for two genuinely different questions sharing a reused
        # locator such as "問題1". Prompt is now always identity material.
        "prompt": _prompt_fallback(attempt.get("prompt", "")),
        "user_answer": _answer_text(attempt.get("user_answer", "")),
        "user_order": list(user_order) if isinstance(user_order, list) else user_order,
    }



def legacy_attempt_identity_payload_v063(attempt: dict[str, Any]) -> dict[str, Any]:
    """Return the v0.6.3-v0.6.5 identity shape for legacy diagnostics only."""
    source = _locator_text(attempt.get("source", ""))
    section = _locator_text(attempt.get("section", ""))
    question = _locator_text(attempt.get("question", ""))
    has_source_question = bool(source and question)
    user_order = attempt.get("user_order", [])
    return {
        "date": str(attempt.get("date", "") or ""),
        "source": source,
        "section": section,
        "question": question,
        "question_type": _locator_text(attempt.get("question_type", "")),
        "prompt": "" if has_source_question else _prompt_fallback(attempt.get("prompt", "")),
        "user_answer": _answer_text(attempt.get("user_answer", "")),
        "user_order": list(user_order) if isinstance(user_order, list) else user_order,
    }


def legacy_attempt_identity_signature_v063(attempt: dict[str, Any]) -> str:
    return json.dumps(legacy_attempt_identity_payload_v063(attempt), ensure_ascii=False, sort_keys=True)

def attempt_identity_signature(attempt: dict[str, Any]) -> str:
    return json.dumps(attempt_identity_payload(attempt), ensure_ascii=False, sort_keys=True)


def attempt_content_payload(attempt: dict[str, Any]) -> dict[str, Any]:
    """Return normalized public content for duplicate/conflict comparison.

    Locator and identity-bearing text must use the same harmless NFKC/spacing
    normalization as :func:`attempt_identity_payload`.  Otherwise two records
    can generate the same identity while being falsely reported as conflicting
    solely because one used ``問題 1`` and the other ``問題1``.
    """
    return {
        "result": str(attempt.get("result", "") or ""),
        "date": str(attempt.get("date", "") or ""),
        "source": _locator_text(attempt.get("source", "")),
        "section": _locator_text(attempt.get("section", "")),
        "question": _locator_text(attempt.get("question", "")),
        "question_type": _locator_text(attempt.get("question_type", "")),
        "prompt": _prompt_fallback(attempt.get("prompt", "")),
        "user_answer": _answer_text(attempt.get("user_answer", "")),
        "correct_answer": _answer_text(attempt.get("correct_answer", "")),
        "options": attempt.get("options", []),
        "reason": str(attempt.get("reason", "") or ""),
        "before": str(attempt.get("before", "") or ""),
        "after": str(attempt.get("after", "") or ""),
        "parts": attempt.get("parts", []),
        "user_order": attempt.get("user_order", []),
        "correct_order": attempt.get("correct_order", []),
        "linked_entries": sorted(set(attempt.get("linked_entries", []))),
    }


def attempt_content_signature(attempt: dict[str, Any]) -> str:
    return json.dumps(attempt_content_payload(attempt), ensure_ascii=False, sort_keys=True)


def generated_attempt_event_key(attempt: dict[str, Any]) -> str:
    signature = attempt_identity_signature(attempt)
    return "attempt:" + hashlib.sha256(signature.encode("utf-8")).hexdigest()[:24]
