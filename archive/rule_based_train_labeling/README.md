# Rule-based train qrels 자동 라벨링 (보류)

`08_auto_label_train_qrels.py`는 train qrels를 query family의 `positive_terms`/`boundary_terms`
문자열 매칭만으로 자동 생성하는 weak supervision 스크립트였습니다. 과거 대전/세종 전용 데이터셋(현재는
삭제됨)에서 같은 corpus·같은 term 정의 기준으로 사람이 직접 만든 train qrels와 직접 비교해본 결과,
사람이 `relevance=3`(직접 관련)으로 확정한 문서의 약 80%가 이 규칙 기반 방식에서는 `relevance=0`
(무관)으로 라벨링되는 것을 확인했습니다(재현율이 매우 낮음 — candidate pool에 lexical run으로만
들어오고 term 목록에 문자 그대로 안 걸리는 문서를 전부 무관 처리하기 때문).

이 재현율 손실이 fine-tuning 신호로서 감당 가능한 수준인지 실제 학습·평가로 검증되기
전까지는 다시 사람 라벨링(calibration + full annotation) 방식으로 되돌리기로 하고, 이
스크립트는 향후 재검토용으로 보존합니다. 다시 쓰려면 `configs/benchmark/storesearch_ko_v1.yaml`
기준 `--config`만 맞추면 그대로 동작합니다(경로 하드코딩 없음).
