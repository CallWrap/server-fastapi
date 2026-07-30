"""Spring ↔ FastAPI 메시징 계층 (RabbitMQ).

경계: Spring은 깔끔한 JSON Job을 발행하고, 여기 컨슈머(consumer.py)가 그걸 받아
Celery 파이프라인으로 넘긴다. 파이프라인이 끝나면 publisher.py가 결과 JSON을
다시 RabbitMQ로 발행해 Spring이 받는다. Spring은 Celery 내부 규격을 몰라도 된다.

계약(메시지 형식)은 contracts.py, 큐·익스체인지·라우팅키는 topology.py.
전체 계약 문서는 docs/message_contract.md.
"""
