"""파이프라인 전 구간 흐름 검증 (Week 2).

Celery를 eager 모드로 돌려 태스크 체인을 인라인으로 실행한다. 큐를 실제로
통과하는지는 워커를 띄워 따로 확인했고, 여기서는 분기 로직을 본다.

DB가 필요하다 — CALLWRAP_TEST_DATABASE_URL이 없으면 통째로 skip한다.
CI에 Postgres가 붙기 전까지는 로컬에서만 도는 테스트다.
"""

import os
import uuid

import pytest

from callwrap_api.quality import orchestrator
from callwrap_api.quality.config import CheckConfig
from callwrap_api.schemas.quality import Action, GateResult

from callwrap_ai.schemas import Transcript

TEST_DB_URL = os.environ.get("CALLWRAP_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DB_URL, reason="CALLWRAP_TEST_DATABASE_URL 없음 — DB 붙는 테스트는 건너뛴다"
)


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
        real_loader = orchestrator.__dict__.get("load_quality_gate_config")
        _ = real_loader  # 사용 안 함 — 아래에서 config를 직접 만든다

        from callwrap_api.quality.config import QualityGateConfig
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


def make_call() -> str:
    from callwrap_api.db import repository
    from callwrap_api.db.session import SessionLocal

    with SessionLocal() as db:
        call = repository.create_call(db, audio_path="/tmp/flow.wav")
        return str(call.id)


def status_of(call_id: str) -> str:
    from callwrap_api.db import repository
    from callwrap_api.db.session import SessionLocal

    with SessionLocal() as db:
        return repository.get_call(db, uuid.UUID(call_id)).status


def retry_count_of(call_id: str) -> int:
    from callwrap_api.db import repository
    from callwrap_api.db.session import SessionLocal

    with SessionLocal() as db:
        return repository.get_call(db, uuid.UUID(call_id)).retry_count


def test_happy_path_reaches_done(only_fake_check):
    """업로드 → STT → 게이트 통과 → 분석 → DONE."""
    only_fake_check(passed=True)
    from callwrap_api.tasks.transcribe import transcribe_task

    call_id = make_call()
    transcribe_task.apply(args=(call_id,)).get()

    assert status_of(call_id) == "DONE"


def test_failed_gate_goes_to_human_review(only_fake_check):
    only_fake_check(passed=False, action="human_review")
    from callwrap_api.tasks.transcribe import transcribe_task

    call_id = make_call()
    transcribe_task.apply(args=(call_id,)).get()

    assert status_of(call_id) == "NEEDS_HUMAN_REVIEW"


def test_retry_loop_escalates_to_human_review_at_the_limit(only_fake_check):
    """retry가 무한히 돌지 않고 MAX_RETRY(2)에서 사람에게 넘어가는지.

    eager 모드라 transcribe → gate → transcribe … 가 재귀적으로 인라인 실행된다.
    상한이 없으면 이 테스트는 스택 오버플로로 죽는다 — 그게 바로 확인하려는 것.
    """
    only_fake_check(passed=False, action="retry")
    from callwrap_api.tasks.transcribe import transcribe_task

    call_id = make_call()
    transcribe_task.apply(args=(call_id,)).get()

    assert status_of(call_id) == "NEEDS_HUMAN_REVIEW"
    assert retry_count_of(call_id) == 2, "MAX_RETRY만큼만 재시도해야 한다"


def test_gate_results_accumulate_per_retry(only_fake_check):
    """재시도마다 결과가 덮어써지지 않고 회차별로 쌓이는지 (Week 7 튜닝 전제)."""
    only_fake_check(passed=False, action="retry")
    from callwrap_api.db import repository
    from callwrap_api.db.session import SessionLocal
    from callwrap_api.tasks.transcribe import transcribe_task

    call_id = make_call()
    transcribe_task.apply(args=(call_id,)).get()

    with SessionLocal() as db:
        rows = repository.list_gate_results(db, uuid.UUID(call_id))

    iterations = sorted({r.retry_iteration for r in rows})
    assert iterations == [0, 1, 2], f"회차별로 쌓여야 한다. 실제: {iterations}"
    assert len(rows) == 3


def test_duplicate_transcribe_is_skipped(only_fake_check):
    """같은 태스크가 두 번 배달돼도 파이프라인이 두 갈래로 갈라지지 않는지."""
    only_fake_check(passed=False, action="human_review")
    from callwrap_api.db import repository
    from callwrap_api.db.session import SessionLocal
    from callwrap_api.state import CallStatus
    from callwrap_api.tasks.transcribe import transcribe_task

    call_id = make_call()
    with SessionLocal() as db:
        call = repository.get_call(db, uuid.UUID(call_id))
        repository.set_status(db, call, CallStatus.TRANSCRIBING)

    result = transcribe_task.apply(args=(call_id,)).get()
    assert result == "skipped"


def test_duplicate_quality_gate_does_not_flip_a_settled_call(only_fake_check):
    """이미 판정된 콜에 게이트가 다시 배달돼도 상태를 뒤집지 않는지.

    회귀 방지: 중복 방어가 없을 때 재진입이 InvalidTransition을 던지고,
    on_failure가 그걸 받아 정상 콜(NEEDS_HUMAN_REVIEW)을 FAILED로 만들었다.
    """
    only_fake_check(passed=False, action="human_review")
    from callwrap_ai.schemas import Speaker, Transcript, Utterance
    from callwrap_api.db import repository
    from callwrap_api.db.session import SessionLocal
    from callwrap_api.state import CallStatus
    from callwrap_api.tasks.quality_gate import run_quality_gate_task

    t = Transcript(
        utterances=[
            Utterance(index=0, speaker=Speaker.COUNSELOR, text="x", start=0.0, end=2.0, confidence=0.9)
        ]
    )
    tj = t.model_dump_json()

    call_id = make_call()
    with SessionLocal() as db:
        call = repository.get_call(db, uuid.UUID(call_id))
        repository.set_status(db, call, CallStatus.TRANSCRIBING)

    run_quality_gate_task.apply(args=(call_id, tj)).get()
    assert status_of(call_id) == "NEEDS_HUMAN_REVIEW"

    # 중복 배달 — skip해야 하고 상태는 그대로여야 한다
    result = run_quality_gate_task.apply(args=(call_id, tj)).get()
    assert result == "skipped"
    assert status_of(call_id) == "NEEDS_HUMAN_REVIEW", "중복 배달이 콜을 뒤집으면 안 된다"
