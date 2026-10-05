import os
import sys
import time
import re
import requests
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "private"))

from orchestrator.qdrant_store import (
    get_pending_tasks,
    get_tasks_by_status,
    get_open_hitl_issues,
    update_task,
    append_event,
)
from github_client import (
    create_workflow_dispatch,
    get_issue,
    get_issue_comments,
    post_comment,
    add_labels,
    close_issue,
)

QDRANT_URL = os.environ.get("QDRANT_URL", "")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "")
PRIVATE_REPO_TOKEN = os.environ.get("PRIVATE_REPO_TOKEN", "")
PRIVATE_REPOSITORY = os.environ.get("PRIVATE_REPOSITORY", "")

POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "300"))
WORKFLOW_FILE = os.environ.get("WORKFLOW_FILE", "pipeline-steps.yml")
WORKFLOW_REF = os.environ.get("WORKFLOW_REF", "main")

HITL1_TIMEOUT_SECONDS = int(os.environ.get("HITL1_TIMEOUT_SECONDS", "3600"))
HITL2_TIMEOUT_SECONDS = int(os.environ.get("HITL2_TIMEOUT_SECONDS", "3600"))
HITL3_TIMEOUT_SECONDS = int(os.environ.get("HITL3_TIMEOUT_SECONDS", "0"))

HITL_STATUSES = ["awaiting-hitl-1", "awaiting-hitl-2", "awaiting-hitl-3"]


def _parse_issue_info(issue_url: str) -> tuple[str, int] | None:
    match = re.search(r"https://github\.com/([^/]+/[^/]+)/issues/(\d+)", issue_url)
    if match:
        return match.group(1), int(match.group(2))
    return None


def dispatch_pending() -> None:
    tasks = get_pending_tasks(limit=50)
    for task in tasks:
        task_id = task.get("task_id")
        if not task_id:
            continue
        now = datetime.now(timezone.utc).isoformat()
        update_task(task_id, {
            "status": "running",
            "current_step": "brainstormer",
            "updated_at": now,
        })
        append_event({
            "task_id": task_id,
            "run_id": task.get("run_id", task_id),
            "type": "step_start",
            "stage": "brainstormer",
            "status": "in_process",
            "payload": {"task_id": task_id, "step": "brainstormer"},
        })
        inputs = {
            "task_id": task_id,
            "topic": task.get("topic", ""),
            "domain": task.get("domain", ""),
            "constraints": task.get("constraints", ""),
        }
        try:
            create_workflow_dispatch(WORKFLOW_FILE, WORKFLOW_REF, inputs)
        except Exception as exc:
            update_task(task_id, {
                "status": "failed",
                "error": str(exc),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })
            append_event({
                "task_id": task_id,
                "run_id": task.get("run_id", task_id),
                "type": "step_error",
                "stage": "brainstormer",
                "status": "failed",
                "payload": {"task_id": task_id, "error": str(exc)},
            })


# Order matters: "NO-GO" contains the word GO, so it must be tested first --
# with GO first, a NO-GO comment was recorded as GO (found 2026-10-04).
_DECISION_PATTERNS = [
    (r"\bCONFIRM\b", "CONFIRM"),
    (r"\bDISPUTE\b", "DISPUTE"),
    (r"\bNO[\s-]?GO\b", "NO-GO"),
    (r"\bGO\b", "GO"),
]
_LEADING_DECISION = re.compile(r"^\W*(CONFIRM|DISPUTE|NO[\s-]?GO|GO)\b", re.IGNORECASE)


def _parse_decision(body: str) -> str | None:
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


def _get_latest_decision(comments: list[dict[str, Any]]) -> str | None:
    latest_decision = None
    latest_date = None
    for comment in comments:
        decision = _parse_decision(comment.get("body", ""))
        created_at = comment.get("created_at", "")
        if decision and (latest_date is None or created_at > latest_date):
            latest_date = created_at
            latest_decision = decision
    return latest_decision


def _close_with_result_comment(issue_number: int | None, repo: str | None, emoji: str, decision: str, status: str) -> None:
    if issue_number is None:
        return
    title = (get_issue(issue_number, repo=repo) or {}).get("title", "")
    post_comment(
        issue_number,
        f"{emoji} {title}\n\nResolved: {decision}. Pipeline complete, status={status}.",
        repo=repo,
    )
    close_issue(issue_number, repo=repo)


def _acknowledge_dispute(issue_number: int | None, repo: str | None, resume_stage: str) -> None:
    if issue_number is None:
        return
    title = (get_issue(issue_number, repo=repo) or {}).get("title", "")
    post_comment(
        issue_number,
        f"🔁 {title}\n\nDisputed — resuming pipeline from {resume_stage}.",
        repo=repo,
    )


def process_hitl_decision(
    task: dict[str, Any],
    decision: str,
    hitl_stage: str,
    issue_number: int | None = None,
    repo: str | None = None,
) -> None:
    task_id = task.get("task_id")
    if not task_id:
        return
    now = datetime.now(timezone.utc).isoformat()
    run_id = task.get("run_id", task_id)

    if hitl_stage == "hitl_1":
        if decision == "CONFIRM":
            update_task(task_id, {
                "status": "archived",
                "finished_at": now,
                "updated_at": now,
            })
            append_event({
                "task_id": task_id,
                "run_id": run_id,
                "type": "hitl_decision",
                "stage": "hitl-1",
                "status": "succeeded",
                "payload": {"decision": "confirmed", "hitl_id": "HITL-1"},
            })
            append_event({
                "task_id": task_id,
                "run_id": run_id,
                "type": "archive",
                "stage": "archive",
                "status": "succeeded",
                "payload": {"reason": "HITL-1 confirmed RED"},
            })
            _close_with_result_comment(issue_number, repo, "❌", "CONFIRM", "archived")
        elif decision == "DISPUTE":
            update_task(task_id, {
                "status": "running",
                "current_step": "scout",
                "updated_at": now,
            })
            append_event({
                "task_id": task_id,
                "run_id": run_id,
                "type": "hitl_decision",
                "stage": "hitl-1",
                "status": "succeeded",
                "payload": {"decision": "disputed", "hitl_id": "HITL-1"},
            })
            _dispatch_continue(task, "dispute", "hitl-1")
            _acknowledge_dispute(issue_number, repo, "SCOUT")
    elif hitl_stage == "hitl_2":
        if decision == "CONFIRM":
            update_task(task_id, {
                "status": "archived",
                "finished_at": now,
                "updated_at": now,
            })
            append_event({
                "task_id": task_id,
                "run_id": run_id,
                "type": "hitl_decision",
                "stage": "hitl-2",
                "status": "succeeded",
                "payload": {"decision": "confirmed", "hitl_id": "HITL-2"},
            })
            append_event({
                "task_id": task_id,
                "run_id": run_id,
                "type": "archive",
                "stage": "archive",
                "status": "succeeded",
                "payload": {"reason": "HITL-2 confirmed DEAD"},
            })
            _close_with_result_comment(issue_number, repo, "❌", "CONFIRM", "archived")
        elif decision == "DISPUTE":
            update_task(task_id, {
                "status": "running",
                "current_step": "financier",
                "updated_at": now,
            })
            append_event({
                "task_id": task_id,
                "run_id": run_id,
                "type": "hitl_decision",
                "stage": "hitl-2",
                "status": "succeeded",
                "payload": {"decision": "disputed", "hitl_id": "HITL-2"},
            })
            _dispatch_continue(task, "dispute", "hitl-2")
            _acknowledge_dispute(issue_number, repo, "FINANCIER")
    elif hitl_stage == "hitl_3":
        if decision == "GO":
            update_task(task_id, {
                "status": "succeeded",
                "finished_at": now,
                "updated_at": now,
            })
            append_event({
                "task_id": task_id,
                "run_id": run_id,
                "type": "hitl_decision",
                "stage": "hitl-3",
                "status": "succeeded",
                "payload": {"decision": "go", "hitl_id": "HITL-3"},
            })
            _close_with_result_comment(issue_number, repo, "✅", "GO", "succeeded")
        elif decision == "NO-GO":
            update_task(task_id, {
                "status": "archived",
                "finished_at": now,
                "updated_at": now,
            })
            append_event({
                "task_id": task_id,
                "run_id": run_id,
                "type": "hitl_decision",
                "stage": "hitl-3",
                "status": "succeeded",
                "payload": {"decision": "no-go", "hitl_id": "HITL-3"},
            })
            append_event({
                "task_id": task_id,
                "run_id": run_id,
                "type": "archive",
                "stage": "archive",
                "status": "succeeded",
                "payload": {"reason": "HITL-3 NO-GO"},
            })
            _close_with_result_comment(issue_number, repo, "❌", "NO-GO", "archived")


def _dispatch_continue(task: dict[str, Any], decision: str, hitl_id: str) -> None:
    task_id = task.get("task_id")
    if not task_id:
        return
    inputs = {
        "continue_run_id": task_id,
        "hitl_decision": decision,
        "hitl_id": hitl_id,
    }
    try:
        create_workflow_dispatch(WORKFLOW_FILE, WORKFLOW_REF, inputs)
    except Exception as exc:
        update_task(task_id, {
            "status": "failed",
            "error": str(exc),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        })
        append_event({
            "task_id": task_id,
            "run_id": task.get("run_id", task_id),
            "type": "step_error",
            "stage": hitl_id,
            "status": "failed",
            "payload": {"task_id": task_id, "error": str(exc)},
        })


def poll_hitl_issues() -> None:
    tasks = get_tasks_by_status(HITL_STATUSES, limit=50)
    for task in tasks:
        task_id = task.get("task_id")
        status = task.get("status", "")
        if not task_id or status not in HITL_STATUSES:
            continue

        hitl_stage = status.replace("awaiting-", "").replace("-", "_")

        hitl_events = get_open_hitl_issues(task_id=task_id, hitl_type=hitl_stage)
        if not hitl_events:
            continue

        hitl_events.sort(key=lambda e: e.get("created_at", ""))
        event = hitl_events[-1]
        issue_url = event.get("payload", {}).get("issue_url", "")
        if not issue_url:
            continue

        repo_issue = _parse_issue_info(issue_url)
        if not repo_issue:
            continue
        repo, issue_number = repo_issue

        if PRIVATE_REPOSITORY and repo != PRIVATE_REPOSITORY:
            continue

        try:
            issue = get_issue(issue_number, repo=repo)
        except Exception:
            continue
        if not issue:
            continue

        try:
            comments = get_issue_comments(issue_number, repo=repo)
        except Exception:
            continue

        decision = _get_latest_decision(comments)
        if decision:
            process_hitl_decision(task, decision, hitl_stage, issue_number=issue_number, repo=repo)
            continue

        created_at = issue.get("created_at", "")
        if created_at:
            created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            now_dt = datetime.now(timezone.utc)
            age_seconds = (now_dt - created_dt).total_seconds()

            timeout = (
                HITL1_TIMEOUT_SECONDS
                if hitl_stage == "hitl_1"
                else HITL2_TIMEOUT_SECONDS
                if hitl_stage == "hitl_2"
                else HITL3_TIMEOUT_SECONDS
            )

            if age_seconds > timeout and timeout > 0:
                post_comment(
                    issue_number,
                    "Auto-approved after 1h timeout, proceeding with system recommendation",
                    repo=repo,
                )
                add_labels(issue_number, ["auto-approved"], repo=repo)
                append_event({
                    "task_id": task_id,
                    "run_id": task.get("run_id", task_id),
                    "type": "hitl_auto_approved",
                    "stage": status.replace("awaiting-", "hitl-"),
                    "status": "succeeded",
                    "payload": {"task_id": task_id, "issue_number": issue_number},
                })
                process_hitl_decision(task, "CONFIRM", hitl_stage, issue_number=issue_number, repo=repo)


def main() -> None:
    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        print("ERROR: GITHUB_TOKEN and GITHUB_REPOSITORY must be set", file=sys.stderr)
        sys.exit(1)
    while True:
        try:
            dispatch_pending()
            poll_hitl_issues()
        except Exception as exc:
            print(f"POLL_ERROR err={exc}", file=sys.stderr)
        if os.environ.get("POLL_ONCE") == "true":
            break
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
