# 이 폴더에 대해

`store-search-ai-enterprise-new`의 팀 공유용 경량 사본입니다. **코드(scripts/, src/, configs/, colab/,
docs/, tests/, Makefile, pyproject.toml)는 전부 그대로**입니다. 용량이 큰 데이터 산출물 중
**"코드를 실행하면 그대로 다시 만들어지는 파일"만 뺐습니다.** raw 원본, store_id 발급 대장, 사람이
직접 채운 relevance 판정(애노테이션 원본/완료 시트, adjudication 기록)처럼 **사람 손을 다시 거쳐야
하거나 코드만으로는 복원 안 되는 데이터는 전부 남겼습니다**(원본 480MB → 152MB).

## 뺀 것 — 전부 코드 재실행으로 그대로 재생성되는 중간 산출물

| 경로 | 용량 | 재생성 방법 |
|---|---|---|
| `data/interim/`, `data/processed/` | 76+82MB | `02_preprocess_data.py --input data/raw/stores_20260907.xlsx` |
| `data/corpus/store_corpus_v002.parquet` | 88MB | `04_build_corpus.py` (위 processed 산출물 필요) |
| `benchmark/storesearch_ko_v1/runs/pooling/` | 9MB | `06_generate_lexical_runs.py` |
| `benchmark/storesearch_ko_v1/candidate_pool_internal.csv` | 17MB | `07_build_annotation_pool.py --round lexical_v1` |
| `artifacts/reports/item_analysis_stores_v003/`의 큰 CSV들 | 7MB | `03_analyze_items.py` (요약본 `item_analysis_summary_*.json`만 남김) |
| `annotations/full_annotation_v1/`의 split별 파일(`annotation_A_train/val/test*.csv`, `annotation_B_val/test*.csv`, 완료본 포함) | 52MB | **`annotation_A_all(_completed).csv`/`annotation_B_val_test(_completed).csv`(전체 버전)와 완전히 같은 내용을 split별로 나눠놓은 것뿐** — `python scripts/split_completed_annotations.py`로 그 자리에서 다시 만들어짐(사람 입력 불필요, 순수 코드). 전체 버전만 남김 |

전부 `docs/PIPELINE.md` 1~3절 순서대로 실행하면 원본과 바이트 단위로 동일하게 재생성됩니다
(단, `data/registry/store_registry.parquet`이 이미 이 폴더에 있어야 store_id가 기존 qrels와
동일하게 재현됩니다 — 아래 참고).

## 남긴 것 — 사람 손을 거쳤거나 코드만으로 복원 안 되는 데이터

- **`data/raw/stores_20260907.xlsx`(26MB)** — raw 원본. 코드로 만들 수 없는 시작점이라 남김
- **`data/registry/store_registry.parquet`(23MB)** — store_id 발급 대장(append-only). 다시 만들면
  store_id가 새로 발급돼서 qrels의 doc_id와 어긋나므로 **절대 지우거나 덮어쓰지 말 것**
- **`benchmark/storesearch_ko_v1/annotations/full_annotation_v1/`(80MB)** — **사람이 직접 채운
  relevance 판정 원본입니다**: A/B 애노테이터가 채운 시트(전체 버전 `annotation_A_all(_completed).csv`,
  `annotation_B_val_test(_completed).csv`만 남김 — split별 버전은 위 표대로 삭제)와 adjudication
  조정 기록(`analysis/adjudication_*`). 최종 `qrels_*.csv`는 이 원본을 코드로 집계한 결과물이지만,
  **누가 무엇을 판정했는지·A/B가 어디서 갈렸는지·조정 근거**는 이 원본에만 있고 코드로 재생성할 수
  없는 사람의 작업 결과라 그대로 보존했습니다
- `benchmark/storesearch_ko_v1/queries.csv`, `qrels_train/val/test.csv(.trec)`, `qrels.csv(.trec)`,
  `benchmark_manifest.json`, `agreement_report.json`, `validation_final.json` — 위 원본을 집계한
  **최종 산출물**(548개 질의, gold qrels)
- `results/model_eval/`, `artifacts/evaluation/` — zero-shot 모델 비교 결과(리더보드 + 모델별 상세)
- `data/query/queryset_final.xlsx`, `data/finetune/train_pairs.jsonl` — 작고 재사용되는 원본/산출물
- `archive/` — 규칙 기반 train 라벨링을 되돌린 이력(작음)

## 처음부터 다시 돌리려면

`docs/PIPELINE.md` 1절부터 순서대로 실행하면 됩니다. raw와 registry가 이미 이 폴더에 있으므로
`data/interim/`, `data/processed/`, `data/corpus/`, pooling 산출물이 기존과 동일하게 재생성됩니다.
`09_prepare_full_annotations.py`를 다시 돌리려면(split별 완료 파일이 필요) 먼저
`python scripts/split_completed_annotations.py`로 남겨둔 전체 버전을 split별로 풀어내면 됩니다.
