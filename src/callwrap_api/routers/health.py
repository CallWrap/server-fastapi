"""헬스체크. docker compose의 의존성 판정과 배포 확인용."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from callwrap_api.db.session import get_db
from callwrap_api.settings import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """프로세스가 살아있는지만. DB를 보지 않는다.

    stt_backend를 같이 노출한다 — stub이 켜진 채로 실서비스에 나가면
    오디오를 안 읽고 고정 더미를 반환하는데, 그게 조용히 넘어가면 안 된다.
    """
    return {"status": "ok", "stt_backend": get_settings().stt_backend}


@router.get("/health/db")
def health_db(db: Session = Depends(get_db)) -> dict[str, str]:
    """DB까지 닿는지. 커넥션 설정이 틀렸을 때 여기서 먼저 드러난다."""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "reachable"}
