"""PipelineTask.on_failure 검증 (무상태).
"""

import uuid

from callwrap_api.messaging.contracts import ResultStatus
from callwrap_api.tasks.base import PipelineTask


def test_extracts_call_id_from_positional_arg():
    call_id = uuid.uuid4()
    assert PipelineTask._call_id_from((str(call_id), "transcript"), {}) == call_id


def test_extracts_call_id_from_kwarg():
    call_id = uuid.uuid4()
    assert PipelineTask._call_id_from((), {"call_id": str(call_id)}) == call_id


def test_returns_none_for_garbage():
    """call_id를 못 찾으면 조용히 엉뚱한 콜을 건드리는 대신 None을 준다."""
    assert PipelineTask._call_id_from((), {}) is None
    assert PipelineTask._call_id_from(("not-a-uuid",), {}) is None
    assert PipelineTask._call_id_from((123,), {}) is None


def test_on_failure_publishes_failed(captured_results):
    call_id = uuid.uuid4()
    task = PipelineTask()
    task.name = "callwrap.test"

    task.on_failure(RuntimeError("폭발"), "task-1", (str(call_id),), {}, None)

    failed = [m for m in captured_results if m.status is ResultStatus.FAILED]
    assert len(failed) == 1
    assert failed[0].call_id == call_id
    assert "폭발" in failed[0].error


def test_on_failure_without_call_id_publishes_nothing(captured_results):
    """call_id가 없으면 아무것도 발행하지 않는다 — 엉뚱한 콜을 FAILED로 만들면 더 나쁘다."""
    task = PipelineTask()
    task.name = "callwrap.test"

    task.on_failure(RuntimeError("폭발"), "task-1", (), {}, None)

    assert captured_results == []
