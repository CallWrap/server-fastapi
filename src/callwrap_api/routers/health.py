"""헬스체크. 컨테이너 liveness와 배포 확인용.

무상태 워커라 DB를 보지 않는다 — /health/db는 없다(DB는 Spring 소유).
"""

from fastapi import APIRouter

from callwrap_api.settings import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """프로세스가 살아있는지만.

    stt_backend를 같이 노출한다 — stub이 켜진 채로 실서비스에 나가면 오디오를 안 읽고
    고정 더미를 반환하는데, 그게 조용히 넘어가면 안 된다.
    """
    return {"status": "ok", "stt_backend": get_settings().stt_backend}
