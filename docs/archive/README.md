# docs/archive — 오프라인 평가·학습 단계 문서

검색 품질 평가와 임베딩 학습은 끝났다(최종 test 2026-11-09). 서비스 개발 기준 문서는 `docs/`의 `SERVICE_POLICY.md`, `BACKEND_HANDOFF.md`,
`SEARCH_LOGGING.md`이고, 여기는 **코드를 다시 돌리거나 근거를 찾을 때** 보는 참고 문서다. 2026-11-10에 18개 문서를 4개로 합쳤다.

## 남은 문서

| 문서 | 내용 | 언제 보나 |
|---|---|---|
| `CODE_AND_RUN.md` | 저장소 폴더·라이브러리 모듈·스크립트 구성, 환경 준비, 실행 순서(데이터 → 코퍼스, 참조 데이터, 서비스셋 평가, 정책 평가, 기존 벤치마크), 서비스 검색 단계별 코드 위치, Colab 노트북 | 코드를 처음 볼 때, 무엇이든 다시 돌릴 때 |
| `EVALUATION.md` | 평가 원칙(pooling 판정, dev로 고르고 test 1회), 서비스 쿼리셋(묶음·split·주 평가셋·C→A 평가용 묶음), 평가 단위·지표, **판정 기준**, 판정 라운드·qrels·채점·정책 시뮬레이션 실행 | 정책을 바꿔 새 판정으로 검증할 때 |
| `TRAINING.md` | 임베딩 평가 구조(encoder → exact search → evaluator), 학습 데이터·Colab 학습·결과 가져오기·재채점, 노트북 셀 지도, 기록 규칙, 임베딩 v1 선택 결과 | 임베딩을 다시 학습·평가할 때 |
| `SERVICE_PIPELINE_PLAN.md` | 검색 파이프라인 실험 기록(1절 ~ 11-29). 인계한 정책의 근거는 11절 | 어떤 값·동작이 왜 정해졌는지 찾을 때 |

## 합치거나 지운 문서

| 예전 문서 | 처리 |
|---|---|
| `PIPELINE.md`, `PIPELINE_CODE_REFERENCE.md`, `EXTENDING_DATA.md` | `CODE_AND_RUN.md`로 합침. 스크립트별 세부는 각 스크립트 머리말에 있다 |
| `EVALUATION_POLICY.md`, `SERVICE_QUERYSET.md`, `SERVICE_QUERYSET_REVIEW.md`, `SERVICE_ANNOTATION_GUIDELINE.md`, `SERVICE_EVAL_METHOD.md`, `QUERY_WRITING_GUIDE.md` | `EVALUATION.md`로 합침(판정 기준은 거의 그대로) |
| `TRAINING.md`(옛), `TRAINING_TEAM.md`, `TRAIN_EVAL_NOTEBOOK.md`, `MODELING.md`, `EMBEDDING_V1_PLAN.md` | `TRAINING.md`로 합침 |
| `SERVICE_READINESS.md` | 지움 — 온라인 검증 방향은 `docs/SERVICE_POLICY.md` 19절, 외부 API 비교는 하지 않기로 함 |

합치면서 뺀 것(날짜별 중간 수치, 작성자 배포용 안내문과 예시, 노트북 셀별 코드 해설, 문제 해결 표, 쿼리 수 검정력 표 등)은 git 커밋 `e2689d8`의
`docs/archive/` 원본에 그대로 있다: `git show e2689d8:docs/archive/QUERY_WRITING_GUIDE.md`.
옛 문서를 가리키던 코드·설정의 경로는 새 문서로 바꿨다. 절 번호는 새 문서와 다르므로 지웠다.
