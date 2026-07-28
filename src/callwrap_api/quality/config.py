"""config/quality_gate.yaml 로더.

★ 규리와 공유. 체크 함수는 임계값을 인자로 받지 말고 CheckConfig를 받는다.
   그래야 params가 체크마다 달라도 시그니처가 하나로 유지된다.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, get_args

import yaml

from callwrap_api.schemas.quality import Action

_VALID_ACTIONS = set(get_args(Action))


class QualityGateConfigError(Exception):
    """설정 파일이 계약을 어겼을 때. 서버 기동 시점에 터뜨린다."""


@dataclass(frozen=True)
class CheckConfig:
    """체크 함수 하나가 판정에 쓰는 모든 설정."""

    name: str
    enabled: bool
    threshold: float
    higher_is_better: bool
    action_on_fail: Action
    params: dict[str, Any] = field(default_factory=dict)
    #: 소속 설정 파일의 version. GateResult.details.checked_at_version에 그대로 넣는다.
    version: str = "unknown"


@dataclass(frozen=True)
class QualityGateConfig:
    version: str
    max_retry: int
    checks: dict[str, CheckConfig]

    def for_check(self, name: str) -> CheckConfig:
        try:
            return self.checks[name]
        except KeyError:
            raise QualityGateConfigError(
                f"'{name}' 체크 설정이 quality_gate.yaml에 없다. "
                f"정의된 체크: {sorted(self.checks)}"
            ) from None


def load_quality_gate_config(path: Path) -> QualityGateConfig:
    """yaml을 읽어 검증까지 마친 설정을 돌려준다.

    설정 오류는 콜 처리 도중이 아니라 여기서 즉시 드러나야 한다 —
    100번째 콜에서 오타 난 action_on_fail을 발견하는 상황을 막는다.
    """
    if not path.exists():
        raise QualityGateConfigError(f"품질 게이트 설정 파일이 없다: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise QualityGateConfigError(f"설정 파일 최상위가 매핑이 아니다: {path}")

    version = raw.get("version")
    if not version:
        raise QualityGateConfigError("version이 비어 있다. 임계값 이력 추적에 필요하다.")

    max_retry = raw.get("max_retry")
    if not isinstance(max_retry, int) or max_retry < 0:
        raise QualityGateConfigError(f"max_retry는 0 이상의 정수여야 한다: {max_retry!r}")

    raw_checks = raw.get("checks")
    if not isinstance(raw_checks, dict) or not raw_checks:
        raise QualityGateConfigError("checks가 비어 있다.")

    checks: dict[str, CheckConfig] = {}
    for name, body in raw_checks.items():
        checks[name] = _parse_check(name, body, version)

    return QualityGateConfig(version=version, max_retry=max_retry, checks=checks)


def _parse_check(name: str, body: Any, version: str) -> CheckConfig:
    if not isinstance(body, dict):
        raise QualityGateConfigError(f"checks.{name}이 매핑이 아니다.")

    action = body.get("action_on_fail")
    if action not in _VALID_ACTIONS:
        raise QualityGateConfigError(
            f"checks.{name}.action_on_fail이 잘못됐다: {action!r} (허용: {sorted(_VALID_ACTIONS)})"
        )
    # 통과했는데 action을 주는 건 의미가 없다. 실패 시 액션만 설정한다.
    if action == "pass":
        raise QualityGateConfigError(
            f"checks.{name}.action_on_fail에 'pass'는 쓸 수 없다. retry 또는 human_review."
        )

    threshold = body.get("threshold")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        raise QualityGateConfigError(f"checks.{name}.threshold가 숫자가 아니다: {threshold!r}")

    higher_is_better = body.get("higher_is_better")
    if not isinstance(higher_is_better, bool):
        raise QualityGateConfigError(
            f"checks.{name}.higher_is_better는 true/false여야 한다: {higher_is_better!r}"
        )

    params = body.get("params") or {}
    if not isinstance(params, dict):
        raise QualityGateConfigError(f"checks.{name}.params가 매핑이 아니다.")

    return CheckConfig(
        name=name,
        enabled=bool(body.get("enabled", True)),
        threshold=float(threshold),
        higher_is_better=higher_is_better,
        action_on_fail=action,
        params=params,
        version=version,
    )
