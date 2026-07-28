"""오케스트레이터 검증 — 예외 통합 처리(합의 B안)와 액션 종합 규칙.

실제 체크 4개는 아직 NotImplementedError라, 가짜 체크를 끼워서 로직만 본다.
"""

import pytest

from callwrap_api.quality import orchestrator
from callwrap_api.quality.config import CheckConfig, QualityGateConfig
from callwrap_api.schemas.quality import Action, GateResult

from callwrap_ai.schemas import Speaker, Transcript, Utterance


@pytest.fixture
def transcript() -> Transcript:
    return Transcript(
        utterances=[
            Utterance(
                index=0,
                speaker=Speaker.COUNSELOR,
                text="안녕하세요, 무엇을 도와드릴까요?",
                start=0.0,
                end=2.1,
                confidence=0.98,
            ),
            Utterance(
                index=1,
                speaker=Speaker.CUSTOMER,
                text="소득 자료 보정은 어떻게 신청하나요?",
                start=2.4,
                end=5.0,
                confidence=0.95,
            ),
        ]
    )


def make_config(action_on_fail: Action = "retry", max_retry: int = 2) -> QualityGateConfig:
    check = CheckConfig(
        name="check_fake",
        enabled=True,
        threshold=0.1,
        higher_is_better=False,
        action_on_fail=action_on_fail,
        params={},
        version="test-v1",
    )
    return QualityGateConfig(version="test-v1", max_retry=max_retry, checks={"check_fake": check})


def fake_check(passed: bool, action: Action = "pass", details: dict | None = None):
    def _check(transcript: Transcript, config: CheckConfig) -> GateResult:
        return GateResult(
            check_name="check_fake",
            passed=passed,
            score=0.05 if passed else 0.5,
            threshold=config.threshold,
            higher_is_better=config.higher_is_better,
            action=action,
            reason=None if passed else "가짜 실패: 0.5",
            details={"sample_size": 2, "checked_at_version": config.version}
            if details is None
            else details,
        )

    return _check


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch):
    monkeypatch.setattr(orchestrator, "CHECK_REGISTRY", {}, raising=False)


def register(monkeypatch, fn):
    monkeypatch.setattr(orchestrator, "CHECK_REGISTRY", {"check_fake": fn}, raising=False)


def test_all_passing_yields_pass(monkeypatch, transcript):
    register(monkeypatch, fake_check(passed=True))
    report = orchestrator.run_quality_gate(transcript, make_config())
    assert report.action == "pass"
    assert report.passed
    assert report.failed_checks == []


def test_failing_check_uses_its_action(monkeypatch, transcript):
    register(monkeypatch, fake_check(passed=False, action="retry"))
    report = orchestrator.run_quality_gate(transcript, make_config())
    assert report.action == "retry"
    assert not report.passed


def test_human_review_beats_retry(transcript):
    """재처리해도 안 낫는 문제가 하나라도 있으면 재시도는 시간 낭비다."""
    results = [
        GateResult("a", False, 0.5, 0.1, False, "retry", None, {}),
        GateResult("b", False, 0.5, 0.1, False, "human_review", None, {}),
    ]
    assert orchestrator._combine_actions(results, retry_count=0, max_retry=2) == "human_review"


def test_retry_escalates_at_the_limit(monkeypatch, transcript):
    """상한만큼 재시도했으면 retry가 아니라 사람에게 넘긴다."""
    register(monkeypatch, fake_check(passed=False, action="retry"))
    config = make_config(max_retry=2)

    assert orchestrator.run_quality_gate(transcript, config, retry_count=1).action == "retry"
    assert (
        orchestrator.run_quality_gate(transcript, config, retry_count=2).action == "human_review"
    )


def test_exception_becomes_human_review(monkeypatch, transcript):
    """체크가 터지면 오케스트레이터가 흡수한다 (합의 B안). 재처리로는 안 낫는다."""

    def boom(transcript: Transcript, config: CheckConfig) -> GateResult:
        raise RuntimeError("의도적 폭발")

    register(monkeypatch, boom)
    report = orchestrator.run_quality_gate(transcript, make_config())

    assert report.action == "human_review"
    (result,) = report.results
    assert not result.passed
    assert result.details["errored"] is True
    assert result.details["error_type"] == "RuntimeError"
    # 필수 키는 오류 결과에도 들어있어야 DB 저장이 깨지지 않는다.
    assert "sample_size" in result.details
    assert "checked_at_version" in result.details


def test_one_check_crashing_does_not_stop_the_others(monkeypatch, transcript):
    """상담사에게 문제를 다 보여주려면 첫 실패에서 멈추면 안 된다."""

    def boom(transcript: Transcript, config: CheckConfig) -> GateResult:
        raise RuntimeError("폭발")

    config = make_config()
    checks = dict(config.checks)
    checks["check_ok"] = CheckConfig(
        name="check_ok",
        enabled=True,
        threshold=0.1,
        higher_is_better=False,
        action_on_fail="retry",
        params={},
        version="test-v1",
    )
    config = QualityGateConfig(version="test-v1", max_retry=2, checks=checks)

    ok = fake_check(passed=True)

    def ok_named(transcript: Transcript, cfg: CheckConfig) -> GateResult:
        result = ok(transcript, cfg)
        result.check_name = "check_ok"
        return result

    monkeypatch.setattr(
        orchestrator, "CHECK_REGISTRY", {"check_fake": boom, "check_ok": ok_named}, raising=False
    )
    report = orchestrator.run_quality_gate(transcript, config)
    assert len(report.results) == 2


def test_disabled_check_is_skipped(monkeypatch, transcript):
    register(monkeypatch, fake_check(passed=False, action="human_review"))
    config = make_config()
    disabled = CheckConfig(
        name="check_fake",
        enabled=False,
        threshold=0.1,
        higher_is_better=False,
        action_on_fail="human_review",
        params={},
        version="test-v1",
    )
    config = QualityGateConfig(version="test-v1", max_retry=2, checks={"check_fake": disabled})

    report = orchestrator.run_quality_gate(transcript, config)
    assert report.results == []
    assert report.action == "pass"


def test_missing_required_detail_keys_is_a_contract_violation(monkeypatch, transcript):
    """details 필수 키를 빠뜨린 체크는 통과시키지 않는다."""
    register(monkeypatch, fake_check(passed=True, details={"sample_size": 2}))
    report = orchestrator.run_quality_gate(transcript, make_config())

    (result,) = report.results
    assert not result.passed
    assert report.action == "human_review"
    assert "checked_at_version" in result.details["error_message"]


def test_passed_false_with_pass_action_is_rejected(monkeypatch, transcript):
    """실패했는데 통과 액션을 주는 건 계약 위반이다 — 조용히 넘기면 콜이 새어나간다."""
    register(monkeypatch, fake_check(passed=False, action="pass"))
    report = orchestrator.run_quality_gate(transcript, make_config())
    assert report.action == "human_review"


def test_summary_reason_joins_failures(monkeypatch, transcript):
    register(monkeypatch, fake_check(passed=False, action="retry"))
    report = orchestrator.run_quality_gate(transcript, make_config())
    assert report.summary_reason() == "가짜 실패: 0.5"
