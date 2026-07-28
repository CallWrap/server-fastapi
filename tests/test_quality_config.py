"""quality_gate.yaml 로더 검증.

★ 규리와 공유하는 설정 파일이라, 실제 파일이 계약을 지키는지도 여기서 확인한다.
"""

import pytest

from callwrap_api.quality.config import QualityGateConfigError, load_quality_gate_config
from callwrap_api.quality.orchestrator import CHECK_REGISTRY
from callwrap_api.settings import get_settings


def test_real_config_file_loads():
    """저장소에 커밋된 실제 설정이 유효한지. 오타 난 채로 머지되는 걸 막는다."""
    config = load_quality_gate_config(get_settings().quality_gate_config_path)
    assert config.version
    assert config.max_retry == 2


def test_config_covers_every_registered_check():
    """체크를 추가했는데 yaml에 안 넣으면 런타임에 터진다 — 여기서 먼저 잡는다."""
    config = load_quality_gate_config(get_settings().quality_gate_config_path)
    assert set(config.checks) == set(CHECK_REGISTRY)


def test_my_checks_escalate_to_human_review():
    """정민 담당 두 체크는 재처리로 안 나아지는 문제라 human_review여야 한다."""
    config = load_quality_gate_config(get_settings().quality_gate_config_path)
    assert config.for_check("check_speaker_overlap").action_on_fail == "human_review"
    assert config.for_check("check_segment_length").action_on_fail == "human_review"


def test_missing_file_is_an_error(tmp_path):
    with pytest.raises(QualityGateConfigError, match="설정 파일이 없다"):
        load_quality_gate_config(tmp_path / "nope.yaml")


def _write(tmp_path, body: str):
    path = tmp_path / "quality_gate.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_bad_action_is_rejected(tmp_path):
    path = _write(
        tmp_path,
        """
version: "test"
max_retry: 2
checks:
  check_x:
    enabled: true
    threshold: 0.1
    higher_is_better: false
    action_on_fail: retyr
""",
    )
    with pytest.raises(QualityGateConfigError, match="action_on_fail"):
        load_quality_gate_config(path)


def test_pass_as_fail_action_is_rejected(tmp_path):
    path = _write(
        tmp_path,
        """
version: "test"
max_retry: 2
checks:
  check_x:
    enabled: true
    threshold: 0.1
    higher_is_better: false
    action_on_fail: pass
""",
    )
    with pytest.raises(QualityGateConfigError, match="'pass'는 쓸 수 없다"):
        load_quality_gate_config(path)


def test_missing_version_is_rejected(tmp_path):
    """version이 없으면 어떤 임계값으로 판정했는지 추적할 수 없다."""
    path = _write(
        tmp_path,
        """
max_retry: 2
checks:
  check_x:
    enabled: true
    threshold: 0.1
    higher_is_better: false
    action_on_fail: retry
""",
    )
    with pytest.raises(QualityGateConfigError, match="version"):
        load_quality_gate_config(path)


def test_higher_is_better_must_be_explicit(tmp_path):
    """점수 방향은 추측하지 않는다 (합의 A안)."""
    path = _write(
        tmp_path,
        """
version: "test"
max_retry: 2
checks:
  check_x:
    enabled: true
    threshold: 0.1
    action_on_fail: retry
""",
    )
    with pytest.raises(QualityGateConfigError, match="higher_is_better"):
        load_quality_gate_config(path)
