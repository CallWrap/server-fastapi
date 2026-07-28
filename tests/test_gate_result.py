"""GateResult 계약 검증. ★ 규리와 합의한 인터페이스라 여기서 못을 박아둔다."""

import dataclasses

import pytest

from callwrap_api.schemas.quality import GateResult, decide_passed


def test_action_has_no_default():
    """action에 기본값이 생기면 실패 결과에서 깜빡했을 때 조용히 'pass'가 된다.

    문제 있는 콜이 게이트를 통과해버리는 경로라 기본값을 두지 않기로 했다 (2026-07-17).
    """
    fields = {f.name: f for f in dataclasses.fields(GateResult)}
    assert fields["action"].default is dataclasses.MISSING
    assert fields["action"].default_factory is dataclasses.MISSING


def test_action_must_be_passed_explicitly():
    with pytest.raises(TypeError, match="action"):
        GateResult(  # type: ignore[call-arg]
            check_name="check_x",
            passed=False,
            score=0.5,
            threshold=0.1,
            higher_is_better=False,
        )


def test_higher_is_better_survives():
    """점수 방향을 결과에 명시하기로 한 합의(A안)가 유지되는지."""
    fields = {f.name for f in dataclasses.fields(GateResult)}
    assert "higher_is_better" in fields


@pytest.mark.parametrize(
    "score, threshold, higher_is_better, expected",
    [
        # higher_is_better=False — 비율 점수(낮을수록 좋음). 체크 4개가 다 이 방향이다.
        (0.05, 0.10, False, True),
        (0.15, 0.10, False, False),
        # higher_is_better=True — 반대 방향 체크가 생겨도 동작해야 한다.
        (0.95, 0.90, True, True),
        (0.85, 0.90, True, False),
    ],
)
def test_decide_passed_respects_direction(score, threshold, higher_is_better, expected):
    assert decide_passed(score, threshold, higher_is_better) is expected


@pytest.mark.parametrize("higher_is_better", [True, False])
def test_exactly_at_threshold_passes(higher_is_better):
    """경계값은 통과다. 방향과 무관하게 일관돼야 한다 — 체크마다 다르면 튜닝이 꼬인다."""
    assert decide_passed(0.10, 0.10, higher_is_better) is True


def make_result() -> GateResult:
    return GateResult(
        check_name="check_speaker_overlap",
        passed=False,
        score=0.18,
        threshold=0.10,
        higher_is_better=False,
        action="human_review",
        reason="화자 겹침 과다: 통화 시간의 18% 구간에서 겹침",
        details={"sample_size": 42, "checked_at_version": "v0.1.0-draft"},
    )


def test_to_dict_covers_every_field():
    """필드를 추가하고 to_dict()를 안 고치는 실수를 막는다."""
    data = make_result().to_dict()
    assert set(data) == {f.name for f in dataclasses.fields(GateResult)}
    assert data["action"] == "human_review"
    assert data["higher_is_better"] is False


def test_to_dict_deep_copies_details():
    """반환값을 만져도 원본이 안 바뀌어야 한다 — 로깅하다가 판정 결과를 오염시키면 안 된다."""
    result = make_result()
    data = result.to_dict()
    data["details"]["sample_size"] = 999

    assert result.details["sample_size"] == 42


def test_to_dict_is_json_serializable():
    """web/으로 그대로 나갈 수 있어야 한다."""
    import json

    restored = json.loads(json.dumps(make_result().to_dict(), ensure_ascii=False))
    assert restored["reason"] == "화자 겹침 과다: 통화 시간의 18% 구간에서 겹침"
    assert restored["details"]["checked_at_version"] == "v0.1.0-draft"
