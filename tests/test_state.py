"""상태 FSM 검증. DB 없이 도는 순수 테스트."""

import pytest

from callwrap_api.state import (
    ALLOWED_TRANSITIONS,
    CallStatus,
    InvalidTransition,
    assert_transition,
    can_transition,
)


def test_every_status_has_a_transition_rule():
    """상태를 추가하고 전이 규칙을 빠뜨리면 KeyError로 터진다 — 그 전에 여기서 잡는다."""
    assert set(ALLOWED_TRANSITIONS) == set(CallStatus)


def test_happy_path():
    path = [
        CallStatus.UPLOADED,
        CallStatus.TRANSCRIBING,
        CallStatus.QUALITY_CHECK,
        CallStatus.PASSED,
        CallStatus.ANALYZING,
        CallStatus.DONE,
    ]
    for current, target in zip(path, path[1:]):
        assert can_transition(current, target), f"{current} → {target}"


def test_gate_can_branch_three_ways():
    for target in (CallStatus.PASSED, CallStatus.RETRYING, CallStatus.NEEDS_HUMAN_REVIEW):
        assert can_transition(CallStatus.QUALITY_CHECK, target)


def test_retry_goes_back_to_transcribing():
    """재시도는 ①번(STT)부터 다시 돈다."""
    assert can_transition(CallStatus.RETRYING, CallStatus.TRANSCRIBING)


def test_retry_can_escalate_to_human_review():
    """상한 초과 시 무한 재시도 대신 사람에게."""
    assert can_transition(CallStatus.RETRYING, CallStatus.NEEDS_HUMAN_REVIEW)


def test_human_review_can_pass_or_retranscribe():
    assert can_transition(CallStatus.NEEDS_HUMAN_REVIEW, CallStatus.PASSED)
    assert can_transition(CallStatus.NEEDS_HUMAN_REVIEW, CallStatus.TRANSCRIBING)


def test_done_is_terminal():
    assert ALLOWED_TRANSITIONS[CallStatus.DONE] == frozenset()


def test_anything_can_fail_except_done():
    for status in CallStatus:
        if status in (CallStatus.DONE, CallStatus.FAILED):
            continue
        assert can_transition(status, CallStatus.FAILED), status


def test_cannot_skip_the_quality_gate():
    """전사 직후 바로 분석으로 넘어가면 게이트가 무의미해진다."""
    assert not can_transition(CallStatus.TRANSCRIBING, CallStatus.ANALYZING)
    assert not can_transition(CallStatus.UPLOADED, CallStatus.PASSED)


def test_invalid_transition_message_lists_allowed():
    with pytest.raises(InvalidTransition) as exc:
        assert_transition(CallStatus.DONE, CallStatus.ANALYZING)
    assert "종착" in str(exc.value)
