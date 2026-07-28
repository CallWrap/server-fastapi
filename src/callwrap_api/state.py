"""콜 상태 FSM. calls.status가 가질 수 있는 값과 허용된 전이를 한곳에서 정의한다.

파이프라인 태스크가 상태를 바꿀 때는 반드시 assert_transition()을 거친다.
Celery 태스크는 재시도·중복 실행이 흔하므로, 허용되지 않는 전이를 조용히 넘기면
"이미 DONE인 콜이 다시 ANALYZING으로 돌아가는" 종류의 버그를 잡을 수 없다.
"""

from enum import Enum


class CallStatus(str, Enum):
    UPLOADED = "UPLOADED"
    TRANSCRIBING = "TRANSCRIBING"
    QUALITY_CHECK = "QUALITY_CHECK"
    PASSED = "PASSED"
    RETRYING = "RETRYING"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    ANALYZING = "ANALYZING"
    DONE = "DONE"
    FAILED = "FAILED"


#: 어떤 상태에서든 예외로 FAILED에 떨어질 수 있다.
_TO_FAILED = frozenset({CallStatus.FAILED})

ALLOWED_TRANSITIONS: dict[CallStatus, frozenset[CallStatus]] = {
    CallStatus.UPLOADED: frozenset({CallStatus.TRANSCRIBING}) | _TO_FAILED,
    CallStatus.TRANSCRIBING: frozenset({CallStatus.QUALITY_CHECK}) | _TO_FAILED,
    # 품질 게이트 판정 결과 3갈래
    CallStatus.QUALITY_CHECK: frozenset(
        {CallStatus.PASSED, CallStatus.RETRYING, CallStatus.NEEDS_HUMAN_REVIEW}
    )
    | _TO_FAILED,
    # 재시도는 ①번(STT)부터 다시. 상한(MAX_RETRY) 초과 시 사람에게 넘긴다.
    CallStatus.RETRYING: frozenset({CallStatus.TRANSCRIBING, CallStatus.NEEDS_HUMAN_REVIEW})
    | _TO_FAILED,
    CallStatus.PASSED: frozenset({CallStatus.ANALYZING}) | _TO_FAILED,
    # 사람이 검토 후: 그냥 통과시키거나(PASSED), 다시 전사시키거나(TRANSCRIBING).
    CallStatus.NEEDS_HUMAN_REVIEW: frozenset({CallStatus.PASSED, CallStatus.TRANSCRIBING})
    | _TO_FAILED,
    CallStatus.ANALYZING: frozenset({CallStatus.DONE}) | _TO_FAILED,
    CallStatus.DONE: frozenset(),  # 종착. 재분석이 필요하면 새 콜로 올린다.
    # 실패한 콜은 운영자가 수동으로 다시 태울 수 있다.
    CallStatus.FAILED: frozenset({CallStatus.TRANSCRIBING}),
}

#: 더 이상 파이프라인이 건드리지 않는 상태.
TERMINAL_STATUSES = frozenset({CallStatus.DONE})

#: 사람의 개입을 기다리는 상태. web/의 검토 큐가 이 상태를 조회한다.
WAITING_FOR_HUMAN = frozenset({CallStatus.NEEDS_HUMAN_REVIEW})


class InvalidTransition(Exception):
    """허용되지 않은 상태 전이."""

    def __init__(self, current: CallStatus, target: CallStatus) -> None:
        self.current = current
        self.target = target
        allowed = sorted(s.value for s in ALLOWED_TRANSITIONS[current])
        super().__init__(
            f"{current.value} → {target.value} 전이는 허용되지 않는다. "
            f"허용: {allowed or '(없음 — 종착 상태)'}"
        )


def can_transition(current: CallStatus, target: CallStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def assert_transition(current: CallStatus, target: CallStatus) -> None:
    if not can_transition(current, target):
        raise InvalidTransition(current, target)
