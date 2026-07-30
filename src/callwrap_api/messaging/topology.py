"""RabbitMQ 토폴로지 — Spring과 공유하는 상수. 변경 시 규리와 합의.

    Spring ──(call.analyze.request)──▶ [callwrap] exchange ──▶ callwrap.jobs ──▶ FastAPI 컨슈머
    FastAPI ──(call.analyze.result)──▶ [callwrap] exchange ──▶ (Spring이 바인딩한 큐)

익스체인지 하나(topic)에 라우팅키로 방향을 가른다. 결과 큐는 Spring이 자기 쪽에서
바인딩하므로 여기서 이름을 강제하지 않는다 — 우리는 exchange+routing_key까지만 책임진다.
"""

#: 요청·결과가 함께 오가는 topic 익스체인지
EXCHANGE = "callwrap"

#: Spring → FastAPI 작업 요청
ROUTING_JOB_REQUEST = "call.analyze.request"
#: FastAPI → Spring 분석 결과
ROUTING_JOB_RESULT = "call.analyze.result"

#: FastAPI 컨슈머가 소비하는 큐 (요청이 여기 쌓인다)
QUEUE_JOBS = "callwrap.jobs"

#: 처리 불능 메시지 격리용 데드레터
DLX_EXCHANGE = "callwrap.dlx"
QUEUE_JOBS_DLQ = "callwrap.jobs.dlq"
