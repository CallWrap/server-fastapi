"""PipelineTask.on_failure 검증.

Week 1 워커 검증에서 발견한 구멍: 태스크가 죽으면 콜이 중간 상태에 영원히 갇혔다.
"""

import uuid
from unittest.mock import patch

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


def test_on_failure_marks_call_failed():
    call_id = uuid.uuid4()
    task = PipelineTask()
    task.name = "callwrap.test"

    # autospec=True — 시그니처까지 맞는지 검증한다. 통짜 mock으로 두면
    # mark_failed의 인자가 바뀌어도 테스트가 통과해버린다 (실제로 그랬다).
    with patch(
        "callwrap_api.tasks.base.repository.mark_failed", autospec=True
    ) as mark_failed:
        task.on_failure(RuntimeError("폭발"), "task-1", (str(call_id),), {}, None)

    mark_failed.assert_called_once_with(call_id)


def test_on_failure_without_call_id_does_not_touch_db():
    """call_id가 없으면 아무 콜도 건드리지 않는다 — 엉뚱한 콜을 FAILED로 만들면 더 나쁘다."""
    task = PipelineTask()
    task.name = "callwrap.test"

    # autospec=True — 시그니처까지 맞는지 검증한다. 통짜 mock으로 두면
    # mark_failed의 인자가 바뀌어도 테스트가 통과해버린다 (실제로 그랬다).
    with patch(
        "callwrap_api.tasks.base.repository.mark_failed", autospec=True
    ) as mark_failed:
        task.on_failure(RuntimeError("폭발"), "task-1", (), {}, None)

    mark_failed.assert_not_called()
