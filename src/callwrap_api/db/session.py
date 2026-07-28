"""DB 세션. FastAPI 라우터와 Celery 태스크가 같은 엔진을 공유한다."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from callwrap_api.settings import get_settings

_settings = get_settings()

engine = create_engine(
    _settings.database_url,
    # 커넥션이 죽었는지 빌려줄 때 확인한다. Celery 워커는 유휴 시간이 길어서
    # 이게 없으면 "server closed the connection unexpectedly"를 만나게 된다.
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI 의존성. 라우터에서 Depends(get_db)로 받는다."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
