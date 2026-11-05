# 백엔드(자바) 개발로 넘기는 것 (2026-11-04)

검색 품질 지표(nDCG·bad@3·top1·헛된 "없음")에 영향이 없는 일은 이 저장소에서 하지 않고 자바 개발에서 한다(팀 결정 2026-11-04).
이 저장소는 오프라인 평가로 서비스 목표를 달성하는 데까지만 한다(`docs/SERVICE_PIPELINE_PLAN.md` 11-4). 서빙·화면·데이터 운영은
별도 엔지니어링이고(Sculley et al., *Hidden Technical Debt in ML Systems*, NeurIPS 2015), 출시 뒤 개선은 로그와 온라인 실험으로 한다
(Kohavi et al., *Trustworthy Online Controlled Experiments*, 2020). 단 로그는 처음부터 넣는다(Google *Rules of ML* — 지표·로그 먼저).

## 1. 넘기는 산출물

| 산출물 | 위치 | 내용 |
|---|---|---|
| 정책 값 | `configs/service/search_policy_v1.yaml` | 반경·지역·지도 모드·정렬·임계값·문구. 섹션마다 [실험]/[확정]/[백엔드] 표시 |
| 지명 사전 | `data/geo/gazetteer_v1.parquet` (+ `.meta.json` 원본 해시) | 공공데이터 지명 21,859행: key, kind, scope, 코드, 중심 좌표 |
| 쿼리 이해 규칙 | `src/store_search_ai/query/understanding.py` | 지역·상호·업종 분리, 같은 이름 지명 선택, 상호 우선 — 테스트 `tests/test_query_understanding.py`, `tests/test_gazetteer.py` |
| 임베딩 모델 | v1 = bge-m3 mj (Colab·Drive, `docs/EMBEDDING_V1_PLAN.md`) | 질의·가게 인코딩 |
| 1단계 구성 | `scripts/eval_service_pipeline.py` `first_stage`, `brand_distance_sort` | v1 + 문자 BM25 후보 합집합(v1 점수 min-max 정규화) + 상호 일치 가산점 β=0.5(별칭 포함), 브랜드 쿼리는 반경 안 지점을 이름으로 찾아 가까운 순 |
| 브랜드 별칭 사전 | `configs/service/brand_alias_v1.csv` | 같은 브랜드의 다른 표기(GS25·지에스25, 파리바게뜨·파리바게트) 53행 — 상호 일치·브랜드 지점 찾기 |
| 관련 확률 계수 | `results/service_pipeline/x1/calibrator.json` | 로지스틱 식 하나(점수·1위와 차이·log 순위·BM25), 임계값 P ≥ 0.35(X1). **특성은 그 단계의 후보 집합 안에서 계산**: 1km 단계는 1km 후보(점수 min-max·순위·BM25 비율 모두 1km 기준), 10km 단계는 10km 후보. 브랜드 쿼리의 브랜드 지점은 이 확률을 쓰지 않고 관련(지점 점수 = 100 − 거리km, 일반 후보는 1.6 이하) |
| LLM 쿼리 확장(X8) | `src/store_search_ai/retrieval/expansion.py`, 확장어 캐시 `results/service_pipeline/x8/expansions_Qwen2.5-14B-Instruct.csv`, 생성 `colab/query_expansion.ipynb` | 업종 의도 쿼리만: 확장어(쉼표 목록)로 범위 안 가맹점 문자 BM25(char 2–3gram, k1 1.5, b 0.75) → 사례 안 최댓값으로 나눔 × 0.3을 1단계 점수에 더함, 확장 상위 200 중 1단계에 없던 가게는 사례 최솟값에서 시작. **관련 확률은 확장을 더한 점수로 계산**. 확장어는 미리 만든 캐시(쿼리 → 키워드), 새 쿼리는 배치 생성 — 실시간 LLM 호출 없음. reranker는 쓰지 않음 |
| 가게 업종(임시 v0) | `data/category/store_category_v0.parquet`, `configs/category/taxonomy_v0.yaml` | 공식 업종 17개 이름으로 붙인 가게 업종 — 화면 업종 칩 필터용(순위에는 안 씀). 공식 업종 데이터가 오면 교체 |
| 로그 설계 | `docs/SEARCH_LOGGING.md` | 이벤트·필드·지표 추천안 |

## 2. 백엔드에서 정할 것

| 항목 | 지금 정해진 것 | 정할 것 |
|---|---|---|
| **모델·규칙 실행 방식** | — | 임베딩 모델: 별도 추론 서버(파이썬) 호출 vs ONNX 변환 후 자바에서 직접 실행. 쿼리 이해 규칙: 자바로 옮김 vs 파이썬 서비스. 옮기면 위 테스트 사례를 자바 테스트로 그대로 옮겨 같은 결과인지 확인 |
| 서빙 | 가맹점 약 21만 곳 → 반경·지역 안 정확 검색(exact kNN) | 엔진(DB 공간 필터 + 벡터), 지연 p95(목표 300ms 제안), BM25 단독 폴백 |
| 지도 화면 | 화면 범위 = 지역 필터, 관련 가게 전부(정책 `map_mode`), 겹치는 핀은 숫자로(기존 지도 기능) | '이 지역에서 다시 검색' 버튼 동작, 화면이 아주 넓을 때 상한(추천 300), 빈 화면 문구 |
| 안내 문구 | 정책 `messages`(초안) | 최종 문구 |
| 로그 | `docs/SEARCH_LOGGING.md` 추천안 | 이벤트 구현, 보관 기간, 사용자 좌표 저장 정밀도(추천 100m 격자) |
| 개인위치정보 | — | 위치정보법 검토(위치기반서비스 신고·동의), 법무 확인 |
| 기본 위치 좌표 | 소진공 본부 주소 확정, 좌표는 임시(약 50m 오차) | 지오코딩으로 교체 |
| 데이터 갱신 | 2026-09-07 스냅샷 하나, 결과·로그에 `corpus_version` | 갱신 주기, 폐업 반영, 무중단 색인 교체(나중에) |
| 온라인 검증 | — | shadow → interleaving/A·B(`docs/SERVICE_READINESS.md` 2-4) |

## 3. 넘기기 전 이 저장소에서 끝낼 것

`docs/SERVICE_PIPELINE_PLAN.md` 11-4: X1(관련 임계값) → X5(브랜드 거리순·별칭) → X2+X3(10km 확장·지역 필터, 판정 한 라운드) → X7(test 1회).
임계값(`relevance.threshold`)과 확장 기준(`radius.expand_if_relevant_below`)이 정해져야 정책 파일이 완성된다.
