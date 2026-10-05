"""Parse HITL decisions out of issue comments. Pure functions, no I/O, so they
can be tested without Qdrant or GitHub (test_decisions.py)."""
import re
from typing import Any

# Order matters: "NO-GO" contains the word GO, so it must be tested first --
# with GO first, a NO-GO comment was recorded as GO (found 2026-10-04).
_DECISION_PATTERNS = [
    (r"\bCONFIRM\b", "CONFIRM"),
    (r"\bDISPUTE\b", "DISPUTE"),
    (r"\bNO[\s-]?GO\b", "NO-GO"),
    (r"\bGO\b", "GO"),
]
_LEADING_DECISION = re.compile(r"^\W*(CONFIRM|DISPUTE|NO[\s-]?GO|GO)\b", re.IGNORECASE)


def parse_decision(body: str) -> str | None:
    """A comment's first word wins ("GO -- despite the NO-GO risk" is GO);
    otherwise the first pattern found anywhere in the text."""
    for line in body.splitlines():
        if line.strip():
            m = _LEADING_DECISION.match(line)
            if m:
                word = m.group(1).upper()
                return "NO-GO" if word.startswith("NO") else word
            break
    for pattern, decision in _DECISION_PATTERNS:
        if re.search(pattern, body, re.IGNORECASE):
            return decision
    return None


def get_latest_decision(comments: list[dict[str, Any]]) -> str | None:
    latest_decision = None
    latest_date = None
    for comment in comments:
        decision = parse_decision(comment.get("body", ""))
        created_at = comment.get("created_at", "")
        if decision and (latest_date is None or created_at > latest_date):
            latest_date = created_at
            latest_decision = decision
    return latest_decision
