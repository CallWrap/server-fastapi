"""파이프라인 전 구간 흐름 검증 (무상태).

Celery를 eager로 돌려 태스크 체인을 인라인 실행하고, 결말은 DB가 아니라 **발행된 결과
메시지**(captured_results)로 확인한다. DB가 없으므로 이 테스트는 항상 돈다.

품질 체크를 '가짜'로 갈아끼워 분기(pass/retry/human_review)만 본다. 값 검증은
test_example_analyzer_e2e가 실제 체크로 한다.
"""

import uuid

import pytest

from callwrap_api.messaging.contracts import ResultStatus
from callwrap_api.quality import orchestrator
from callwrap_api.quality.config import CheckConfig, QualityGateConfig
from callwrap_api.schemas.quality import Action, GateResult

from callwrap_ai.schemas import Transcript


@pytest.fixture(autouse=True)
def eager_celery():
    from callwrap_api.tasks.app import celery_app

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    yield
    celery_app.conf.task_always_eager = False


def fake_check(passed: bool, action: Action):
    def _check(transcript: Transcript, config: CheckConfig) -> GateResult:
        return GateResult(
            check_name="check_fake",
            passed=passed,
            score=0.05 if passed else 0.5,
            threshold=config.threshold,
            higher_is_better=config.higher_is_better,
            action="pass" if passed else action,
            reason=None if passed else "가짜 실패: 0.5",
            details={"sample_size": 4, "checked_at_version": config.version},
        )

    return _check


@pytest.fixture
def only_fake_check(monkeypatch):
    """체크 레지스트리를 가짜 하나로 교체하고 yaml 설정도 맞춰준다."""

    def _install(passed: bool, action: Action = "retry"):
        monkeypatch.setattr(
            orchestrator, "CHECK_REGISTRY", {"check_fake": fake_check(passed, action)}
        )
        import callwrap_api.tasks.quality_gate as qg

        cfg = QualityGateConfig(
            version="test-v1",
            max_retry=2,
            checks={
                "check_fake": CheckConfig(
                    name="check_fake",
                    enabled=True,
                    threshold=0.1,
                    higher_is_better=False,
                    action_on_fail=action,
                    params={},
                    version="test-v1",
                )
            },
        )
        monkeypatch.setattr(qg, "load_quality_gate_config", lambda path: cfg)

    return _install


def _audio(tmp_path) -> str:
    p = tmp_path / "flow.wav"
    p.write_bytes(b"dummy-audio")
    return str(p)


def test_happy_path_publishes_done(only_fake_check, captured_results, tmp_path):
    """전사 → 게이트 통과 → 분석 → DONE 발행."""
    only_fake_check(passed=True)
    from callwrap_api.tasks.transcribe import transcribe_task

    cid = uuid.uuid4()
    transcribe_task.apply(args=(str(cid), _audio(tmp_path))).get()

    done = [m for m in captured_results if m.status is ResultStatus.DONE]
    assert len(done) == 1
    assert done[0].call_id == cid


def test_failed_gate_publishes_human_review(only_fake_check, captured_results, tmp_path):
    only_fake_check(passed=False, action="human_review")
    from callwrap_api.tasks.transcribe import transcribe_task

    cid = uuid.uuid4()
    transcribe_task.apply(args=(str(cid), _audio(tmp_path))).get()

    hr = [m for m in captured_results if m.status is ResultStatus.NEEDS_HUMAN_REVIEW]
    assert len(hr) == 1
    assert hr[0].call_id == cid
    assert hr[0].quality.failed_checks == ["check_fake"]
    # 사람 검토는 종착 — DONE은 나오지 않아야 한다
    assert not any(m.status is ResultStatus.DONE for m in captured_results)


def test_retry_loop_escalates_to_human_review_at_the_limit(only_fake_check, captured_results, tmp_path):
    """retry가 무한히 돌지 않고 max_retry(2)에서 사람에게 넘어가는지.

    eager 모드라 transcribe → gate → transcribe … 가 재귀적으로 인라인 실행된다.
    상한이 없으면 이 테스트는 스택 오버플로로 죽는다 — 그게 바로 확인하려는 것.
    """
    only_fake_check(passed=False, action="retry")
    from callwrap_api.tasks.transcribe import transcribe_task

    cid = uuid.uuid4()
    transcribe_task.apply(args=(str(cid), _audio(tmp_path))).get()

    hr = [m for m in captured_results if m.status is ResultStatus.NEEDS_HUMAN_REVIEW]
    assert len(hr) == 1, "재시도 상한에서 정확히 한 번 사람 검토로 넘어가야 한다"
