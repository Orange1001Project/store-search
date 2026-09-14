# ============================================================
# StoreSearch-KO v1 pipeline DAG
#
# 이 Makefile은 scripts/01_*.py ~ scripts/07_*.py 까지 (사람 개입이 없는 구간)를
# 파일 의존관계 기반으로 자동 재실행합니다. `make <target>`을 실행하면 make가
# 알아서 "무엇이 이미 최신 상태인지" 파일 수정시각(mtime)으로 판단해서, 필요한
# 앞단계만 다시 돌립니다 — docs/PIPELINE.md의 실행 순서를 사람이 손으로 따라가지
# 않아도 되게 하기 위한 것입니다.
#
# 08번부터는 실제 사람이 애노테이션/adjudication을 해야 하므로 make로 자동화할
# 수 없습니다(train도 08번에서 사람이 직접 라벨링합니다). 대신 "사람이 만들어야
# 할 파일이 없으면 무엇을 해야 하는지" 안내하는 가드 타겟을 제공합니다
# (make prepare-full-annotations 등).
#
# 사용 예:
#   make corpus              # 01~04 중 필요한 것만 재실행해서 corpus까지 최신화
#   make pool                # 01~07 전체를 최신화
#   make validate            # 현재 benchmark 상태 무결성 검증 (pilot)
#   make clean-derived       # 재실행 가능한 산출물만 삭제 (raw/qrels/completed 애노테이션은 보존)
# ============================================================

PY := .venv/bin/python
SCRIPTS := scripts
CONFIG_DATA := configs/data/default.yaml
CONFIG_BENCH := configs/benchmark/storesearch_ko_v1.yaml
FAMILIES := configs/benchmark/query_families_v1.yaml
RAW := data/raw/stores_20260907.xlsx
DATASET_VERSION := stores_v003
CORPUS_VERSION := store_corpus_v002

.PHONY: all profile preprocess analyze corpus benchmark-init lexical-runs pool \
        validate validate-final evaluate \
        full-annotation-sheets prepare-full-annotations apply-adjudication build-qrels \
        clean-derived help

help:
	@echo "make corpus            01~04 (전처리~corpus) 재실행"
	@echo "make pool              01~07 (corpus~lexical pooling) 재실행"
	@echo "make validate          benchmark 무결성 검증 (pilot)"
	@echo "make validate-final    benchmark 무결성 검증 (final, double-annotation coverage 등 포함)"
	@echo "make evaluate RUN=... TAG=...   13_evaluate_run.py 실행"
	@echo "사람이 개입해야 하는 단계(annotation/adjudication)는 docs/PIPELINE.md 4~5절 참고"

# ---------- 01: profile (재실행은 자유, 다른 산출물의 선행조건은 아님) ----------

artifacts/reports/data_profile.json: $(RAW) $(CONFIG_DATA)
	$(PY) $(SCRIPTS)/01_profile_data.py --input $(RAW) --config $(CONFIG_DATA)

profile: artifacts/reports/data_profile.json

# ---------- 02: preprocess ----------

data/processed/stores_master_$(DATASET_VERSION).parquet: $(RAW) $(CONFIG_DATA)
	$(PY) $(SCRIPTS)/02_preprocess_data.py --input $(RAW) --config $(CONFIG_DATA)

preprocess: data/processed/stores_master_$(DATASET_VERSION).parquet

# ---------- 03: item 분석 (정보성 리포트 — corpus 빌드의 필수 선행조건 아님) ----------

analyze: data/processed/stores_master_$(DATASET_VERSION).parquet
	$(PY) $(SCRIPTS)/03_analyze_items.py

# ---------- 04: corpus ----------

data/corpus/$(CORPUS_VERSION).parquet: data/processed/stores_master_$(DATASET_VERSION).parquet
	$(PY) $(SCRIPTS)/04_build_corpus.py --config $(CONFIG_BENCH)

corpus: data/corpus/$(CORPUS_VERSION).parquet

# ---------- 05: query set 초기화 ----------

benchmark/storesearch_ko_v1/queries.csv: $(FAMILIES) $(CONFIG_BENCH)
	$(PY) $(SCRIPTS)/05_init_benchmark.py --config $(CONFIG_BENCH) --families $(FAMILIES)

benchmark-init: benchmark/storesearch_ko_v1/queries.csv

# ---------- 06: lexical pooling runs ----------

benchmark/storesearch_ko_v1/runs/pooling/lexical_run_manifest.json: data/corpus/$(CORPUS_VERSION).parquet benchmark/storesearch_ko_v1/queries.csv
	$(PY) $(SCRIPTS)/06_generate_lexical_runs.py --config $(CONFIG_BENCH)

lexical-runs: benchmark/storesearch_ko_v1/runs/pooling/lexical_run_manifest.json

# ---------- 07: candidate pool (lexical_v1 라운드) ----------

benchmark/storesearch_ko_v1/candidate_pool_internal.csv: benchmark/storesearch_ko_v1/runs/pooling/lexical_run_manifest.json
	$(PY) $(SCRIPTS)/07_build_annotation_pool.py --config $(CONFIG_BENCH) --round lexical_v1

pool: benchmark/storesearch_ko_v1/candidate_pool_internal.csv

# ---------- 12: 벤치마크 무결성 검증 ----------

validate: corpus benchmark-init
	$(PY) $(SCRIPTS)/12_validate_benchmark.py --config $(CONFIG_BENCH) --stage pilot

validate-final: corpus benchmark-init
	$(PY) $(SCRIPTS)/12_validate_benchmark.py --config $(CONFIG_BENCH) --stage final

# ---------- 13: 평가 (사람이 만든 run.csv 필요) ----------

evaluate:
	@test -n "$(RUN)" || (echo "make evaluate RUN=<run.csv> TAG=<experiment_name> 형식으로 호출하세요" && exit 1)
	@test -n "$(TAG)" || (echo "make evaluate RUN=<run.csv> TAG=<experiment_name> 형식으로 호출하세요" && exit 1)
	$(PY) $(SCRIPTS)/13_evaluate_run.py --run $(RUN) --tag $(TAG)

# ============================================================
# 08~11: 사람 개입 구간 — 자동 실행 대신 가드 + 안내만 제공
# 자세한 절차는 docs/PIPELINE.md 4~5절 참고
# ============================================================

ANNOT_DIR := benchmark/storesearch_ko_v1/annotations/full_annotation_v1

full-annotation-sheets: pool
	$(PY) $(SCRIPTS)/08_make_full_annotation_sheets.py --config $(CONFIG_BENCH)
	@echo ">> $(ANNOT_DIR)/annotation_A_{train,val,test}.csv, annotation_B_{val,test}.csv 를 전달하세요."

prepare-full-annotations:
	@test -d "$(ANNOT_DIR)/completed" || (echo "$(ANNOT_DIR)/completed/ 에 5개 *_completed.csv 파일이 필요합니다 (docs/PIPELINE.md 4절)" && exit 1)
	$(PY) $(SCRIPTS)/09_prepare_full_annotations.py --config $(CONFIG_BENCH)
	@echo ">> $(ANNOT_DIR)/analysis/adjudication_val_test_needed_only.csv 를 조정자에게 전달하세요."

apply-adjudication:
	@test -n "$(PATCH)" || (echo "make apply-adjudication PATCH=<완료된 adjudication_val_test_needed_only_completed.csv>" && exit 1)
	$(PY) $(SCRIPTS)/10_apply_adjudication_patch.py --patch $(PATCH)

build-qrels:
	$(PY) $(SCRIPTS)/11_build_qrels.py --config $(CONFIG_BENCH) \
		--adjudication $(ANNOT_DIR)/analysis/adjudication_val_test_full_completed.csv

# ============================================================
# 정리
# ============================================================

# 재실행하면 그대로 복구되는 파생 산출물만 삭제한다.
# data/raw, data/registry(누적 store_id), benchmark의 애노테이션/qrels/완료본은 절대 지우지 않는다.
clean-derived:
	rm -rf artifacts
	rm -rf data/interim data/processed data/corpus
	rm -f benchmark/storesearch_ko_v1/queries.csv benchmark/storesearch_ko_v1/annotation_guideline.md
	rm -f benchmark/storesearch_ko_v1/query_manifest.json
	rm -rf benchmark/storesearch_ko_v1/runs
	rm -f benchmark/storesearch_ko_v1/candidate_pool_internal.csv benchmark/storesearch_ko_v1/pool_stats.json
