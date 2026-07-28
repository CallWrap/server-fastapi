"""임시 전사기 — stt/가 준비될 때까지 파이프라인을 돌려보기 위한 더미.

★ 교체 지점. stt/가 나오면 이 모듈을 통째로 버리고 tasks/transcribe.py에서
   실제 전사 함수를 부른다. 여기에 로직을 쌓지 말 것.

ai/pipeline.py가 같은 이유로 하드코딩 더미를 반환하고 있다 — 계약을 먼저 고정해서
api/와 web/이 붙기 시작할 수 있게 하려는 것. 그 패턴을 그대로 따른다.

기본은 STT_BACKEND=stub이고, 실서비스에서 이게 켜진 채로 돌면 안 되므로
settings에 명시적으로 남긴다.
"""

from pathlib import Path

from callwrap_ai.schemas import Speaker, Transcript, Utterance


def transcribe_stub(audio_path: str) -> Transcript:
    """오디오를 보지 않고 고정된 전사를 돌려준다.

    발화 내용은 label_spec.md의 "자료 보정" 시나리오를 흉내 낸 것이다 —
    web/이 화면을 만들 때 그럴듯한 데이터가 보이는 게 낫다.

    품질 게이트를 통과하도록 만들어져 있다: confidence 높고, 겹침 없고,
    발화 길이도 0.5~60초 안에 있다. 실패 케이스를 보려면 아래 make_bad_transcript()를 쓴다.
    """
    _ = Path(audio_path)  # 실제 구현이 여기서 파일을 읽는다

    return Transcript(
        utterances=[
            Utterance(
                index=0,
                speaker=Speaker.COUNSELOR,
                text="(더미 전사) 안녕하세요, 무엇을 도와드릴까요?",
                start=0.0,
                end=2.4,
                confidence=0.97,
            ),
            Utterance(
                index=1,
                speaker=Speaker.CUSTOMER,
                text="(더미 전사) 소득 자료가 잘못 등록된 것 같은데 수정하려면 어떻게 하나요?",
                start=2.8,
                end=8.1,
                confidence=0.94,
            ),
            Utterance(
                index=2,
                speaker=Speaker.COUNSELOR,
                text="(더미 전사) 자료 보정 요청 메뉴에서 접수하시면 됩니다. 제가 접수 도와드릴게요.",
                start=8.5,
                end=14.2,
                confidence=0.96,
            ),
            Utterance(
                index=3,
                speaker=Speaker.CUSTOMER,
                text="(더미 전사) 네, 감사합니다.",
                start=14.6,
                end=16.0,
                confidence=0.98,
            ),
        ]
    )


def make_bad_transcript() -> Transcript:
    """게이트를 일부러 실패시키는 전사. 재처리·검토 큐 경로를 테스트할 때 쓴다.

    화자 겹침(체크 ③)과 극단적 세그먼트 길이(체크 ④)를 동시에 만든다.
    """
    return Transcript(
        utterances=[
            # 상담사 발화가 0.0~30.0인데 고객 발화가 5.0에 시작 — 25초 겹침
            Utterance(
                index=0,
                speaker=Speaker.COUNSELOR,
                text="(더미) 화자분리가 실패한 긴 발화",
                start=0.0,
                end=30.0,
                confidence=0.4,
            ),
            Utterance(
                index=1,
                speaker=Speaker.CUSTOMER,
                text="(더미) 겹치는 발화",
                start=5.0,
                end=30.0,
                confidence=0.3,
            ),
            # 0.2초짜리 — min_seconds(0.5) 미만
            Utterance(
                index=2,
                speaker=Speaker.CUSTOMER,
                text="(더미) 짧",
                start=30.1,
                end=30.3,
                confidence=0.2,
            ),
        ]
    )
