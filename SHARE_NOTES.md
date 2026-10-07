# 이 폴더에 대해

`store-search-ai-enterprise-new`의 팀 공유용 경량 사본입니다. **코드(scripts/, src/, configs/, colab/,
docs/, tests/, Makefile, pyproject.toml, requirements-lock.txt)는 전부 그대로**입니다.
`requirements-lock.txt`는 검증된 정확한 패키지 버전 조합을 고정한 파일이니, 환경을 새로 만들 때는
`pip install -e ".[dev]"`가 아니라 이 파일로 설치할 것(`docs/PIPELINE.md` 0절 참고 — 버전이
설치 시점마다 달라져서 실제로 문제가 된 적이 있음). 용량이 큰 데이터 산출물 중
**"코드를 실행하면 그대로 다시 만들어지는 파일"만 뺐습니다.** raw 원본, store_id 발급 대장, 사람이
직접 채운 relevance 판정(애노테이션 원본/완료 시트, adjudication 기록)처럼 **사람 손을 다시 거쳐야
하거나 코드만으로는 복원 안 되는 데이터는 전부 남겼습니다**(원본 480MB → 152MB).

## 뺀 것 — 전부 코드 재실행으로 그대로 재생성되는 중간 산출물

| 경로 | 용량 | 재생성 방법 |
|---|---|---|
| `data/interim/`, `data/processed/` | 76+82MB | `02_preprocess_data.py --input data/raw/stores_20260907.xlsx` |
| `data/corpus/store_corpus_v002.parquet` | 88MB | `04_build_corpus.py` (위 processed 산출물 필요) |
| `benchmark/storesearch_ko_v1/runs/pooling/` | 9MB | `06_generate_lexical_runs.py` (⚠ 아래 참고 — 바이트 단위 재현 안 됨) |
| `benchmark/storesearch_ko_v1/candidate_pool_internal.csv` | 17MB | `07_build_annotation_pool.py --round lexical_v1` (⚠ 아래 참고 — 바이트 단위 재현 안 됨) |
| `artifacts/reports/item_analysis_stores_v003/`의 큰 CSV들 | 7MB | `03_analyze_items.py` (요약본 `item_analysis_summary_*.json`만 남김) |
| `annotations/full_annotation_v1/`의 split별 파일(`annotation_A_train/val/test*.csv`, `annotation_B_val/test*.csv`, 완료본 포함) | 52MB | **`annotation_A_all(_completed).csv`/`annotation_B_val_test(_completed).csv`(전체 버전)와 완전히 같은 내용을 split별로 나눠놓은 것뿐** — `python scripts/split_completed_annotations.py`로 그 자리에서 다시 만들어짐(사람 입력 불필요, 순수 코드). 전체 버전만 남김 |

`docs/PIPELINE.md` 1~3절 순서대로 실행하면 재생성됩니다(`data/registry/store_registry.parquet`이
이미 이 폴더에 있어야 store_id가 기존 qrels와 동일하게 재현됩니다 — 아래 참고). 단, 이 "바이트
단위로 동일하게 재생성된다"는 보장은 **1절(전처리~corpus, 01~04번)까지만 실제로 확인됐습니다**
— `02_preprocess_data.py`/`04_build_corpus.py`를 두 번 별도로 재실행해서 체크인된 산출물과
정확히 일치함을 검증했습니다(리팩토링 작업 중 golden-file 테스트로 재확인, 2026-09).

**3절(lexical pooling, 06~07번)은 바이트 단위로 재현되지 않는다는 것을 발견했습니다.** 같은
corpus·같은 config로 `06_generate_lexical_runs.py` → `07_build_annotation_pool.py`를 두 번
독립적으로 재실행했는데, 둘 다 `candidate_pool_internal.csv`가 55,647행이 나왔습니다 — 이 폴더에
체크인된 `pool_history.csv`의 원본 기록(61,619행)과 다릅니다. 두 번의 재실행이 서로 다른 값이
아니라 **매번 똑같이 55,647행**이 나왔다는 점에서 무작위성 문제는 아닙니다. 원인을 끝까지 추적한
결과(2026-09, 원본 GitHub 이력 대조 포함) 두 가지가 확인됐습니다.

1. **원본 프로젝트 자체가 06~07을 여러 번 누적 실행해서 만들어졌을 가능성이 높습니다.** 원본
   레포(`Silverbird04/store-search-ai-enterprise-new`)의 커밋 이력을 직접 대조해본 결과, 61,619행이
   처음 기록된 커밋 시점의 `06_generate_lexical_runs.py` 코드와 `queries.csv`는 지금 이 폴더의
   리팩토링 이전 버전과 바이트/값 단위로 완전히 동일했습니다(코드·쿼리 텍스트 차이는 배제됨).
   `07_build_annotation_pool.py --round`는 원래 여러 번 누적 호출하도록 설계돼 있고, 원본 커밋
   메시지에도 "fast annotation test until qrels" 같은 반복 실행을 시사하는 기록이 남아 있어, 단일
   클린 실행이 아니라 여러 pooling round가 누적되어 61,619행이 됐을 가능성이 큽니다 — 이 경우 단
   1회 재실행으로는 애초에 재현이 불가능합니다.
2. **별도로, word_tfidf/bm25 채널 자체에 실재하는 토큰화 한계도 확인했습니다.** 두 채널은 원래
   정규식 단어 경계 토큰화(`\b\w+\b` 류)를 썼는데, 한국어는 복합어를 띄어쓰기 없이 붙여 쓰는
   경우가 흔해서(예: "가구추천" = "가구"+"추천") 548개 쿼리 중 97개가 이 두 채널에서 후보를
   0개 받는 것으로 확인됐습니다. 이건 환경 차이가 아니라 **토큰화 방식 자체의 구조적 한계**이며,
   기업 서비스로 확장 시 실사용자가 자주 입력할 패턴이라 방치할 수 없다고 판단해 McNamee &
   Mayfield(2004)의 문자 n-gram 방식으로 고쳤습니다(`src/store_search_ai/retrieval/lexical.py`의
   `char_ngrams`, commit `33378d0`). 이 수정 이후로는 06을 다시 돌리면 **의도적으로** 결과가
   달라집니다 — 버그가 아니라 개선이며, 기존 pool을 대체하지 않고 `--round char_ngram_v1` 같은
   새 round로 누적하도록 설계되어 있습니다(아래 "다시 돌리려면" 참고).

실무 영향은 그대로입니다: `candidate_pool_internal.csv`를 처음부터 다시 만들어서 기존 걸 덮어쓰면
안 되고(이미 사람이 그 pool을 보고 판정한 애노테이션 원본과 어긋나게 됨), 이 공유 폴더에 이미
남아있는 애노테이션 원본·qrels·리더보드 등 "사람 손을 거친" 산출물을 그대로 써야 합니다. pooling을
확장하고 싶다면(예: 이번 토큰화 개선분 반영) 처음부터 다시 만들지 말고 `--round`로 누적하세요.

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
- `results/model_eval/`, `artifacts/evaluation/` — 모델 평가 결과. `artifacts/evaluation/`의 기존 zero-shot json은 gold qrels
  확정(2026-10-02) **이전** 정답 기준이라 지금 점수와 비교할 수 없습니다(그 run CSV는 pooling 재시작 때 삭제). Colab 평가 결과를
  `scripts/import_colab_results.py --verify`로 가져오면 같은 이름 파일이 새 결과로 바뀝니다
- `data/query/queryset_final.xlsx`, `data/finetune/train_pairs.jsonl` — 작고 재사용되는 원본/산출물
- `archive/` — 규칙 기반 train 라벨링을 되돌린 이력(작음)

## 처음부터 다시 돌리려면

`docs/PIPELINE.md` 1절부터 순서대로 실행하면 됩니다. raw와 registry가 이미 이 폴더에 있으므로
`data/interim/`, `data/processed/`, `data/corpus/`는 기존과 바이트 단위로 동일하게 재생성됩니다.
**pooling 산출물(`runs/pooling/`, `candidate_pool_internal.csv`)은 위 "⚠" 표시 항목에 적은 대로
기존과 다르게 나올 수 있습니다** — 이미 사람이 판정을 마친 애노테이션이 있다면 pooling을 다시
돌리지 말고 이 폴더에 남아있는 애노테이션 원본을 그대로 쓰세요. `09_prepare_full_annotations.py`를
다시 돌리려면(split별 완료 파일이 필요) 먼저 `python scripts/split_completed_annotations.py`로
남겨둔 전체 버전을 split별로 풀어내면 됩니다.
