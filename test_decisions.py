"""Tests for decisions.py. Stdlib only -- run: python3 test_decisions.py

Regression for the 2026-10-04 bug where every NO-GO comment parsed as GO."""
from decisions import get_latest_decision, parse_decision

CASES = {
    "NO-GO": "NO-GO", "no-go: too risky": "NO-GO", "No Go": "NO-GO", "nogo": "NO-GO",
    "GO": "GO", "go ahead": "GO", "\n\nGO": "GO", "  GO!": "GO",
    "GO — fine, despite the NO-GO risk": "GO", "NO-GO — we should not GO": "NO-GO",
    "I say no-go": "NO-GO", "I say go": "GO", "Looks fine, GO.": "GO",
    "CONFIRM": "CONFIRM", "confirm the red": "CONFIRM", "DISPUTE": "DISPUTE", "dispute this": "DISPUTE",
    "Auto-approved after 1h timeout, proceeding with system recommendation": None,
    "Disputed — resuming pipeline from SCOUT.": None, "": None, "Going to lunch": None,
}


def test_parse_decision_cases():
    bad = {k: (v, parse_decision(k)) for k, v in CASES.items() if parse_decision(k) != v}
    assert not bad, bad


def test_latest_comment_wins_regardless_of_order():
    a = {"body": "GO", "created_at": "2026-10-04T01:00:00Z"}
    b = {"body": "NO-GO", "created_at": "2026-10-04T02:00:00Z"}
    assert get_latest_decision([a, b]) == "NO-GO" and get_latest_decision([b, a]) == "NO-GO"
    assert get_latest_decision([{"body": "chatter", "created_at": "3"}, a]) == "GO"
    assert get_latest_decision([]) is None


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t(); print("PASS", t.__name__)
        except AssertionError as exc:
            failed += 1; print("FAIL", t.__name__, exc)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
