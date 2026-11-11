# 평가·판정 방법 (서비스셋 기준, 2026-11-10 정리)

오프라인 평가는 끝났다(최종 test 2026-11-09, 결과는 `docs/BACKEND_HANDOFF.md` 3절). 앞으로 검색 구성을 바꾸면 **새 판정 라운드로
검증**한다. 이 문서는 그때 같은 절차를 다시 밟을 수 있도록 원칙, 쿼리셋, 판정 기준, 실행 순서를 한곳에 모았다.

아래 문서를 합쳤다: EVALUATION_POLICY, SERVICE_QUERYSET, SERVICE_QUERYSET_REVIEW, SERVICE_ANNOTATION_GUIDELINE, SERVICE_EVAL_METHOD,
QUERY_WRITING_GUIDE. 진행 기록과 그때그때의 숫자는 `docs/archive/SERVICE_PIPELINE_PLAN.md`에 있다.

## 0. 한눈에

| 무엇 | 파일 |
|---|---|
| 설정(쿼리셋·주 평가셋·판정) | `configs/query/service_queryset_v1.yaml` (`import`, `eval_set`, `judging` 블록) |
| 검색 정책(채점이 흉내 내는 규칙) | `configs/service/search_policy_v1.yaml` |
| 쿼리 표(가져온 원본) | `data/query/service_queries_v1.csv` (+ `.meta.json`) |
| 쿼리 전체 표(회의·검토용) | `benchmark/service_ko_v1/queries.csv` |
| 평가 사례(쿼리 × 가정위치) | `benchmark/service_ko_v1/instances.csv` |
| 주 평가셋 | `benchmark/service_ko_v1/eval_set.csv` |
| 평가용 묶음 목록(C → A) | `data/query/service_eval_bundle_v1.csv` |
| 판정 라운드 | `benchmark/service_ko_v1/annotations/<round>/` |
| qrels | `benchmark/service_ko_v1/qrels.csv`, `qrels_status.json` |
| 10km·지역·지도 요청표 | `benchmark/service_ko_v1/x23/requests.csv` |
| 기본 판정 가이드라인 v1.2 | `benchmark/storesearch_ko_v1/annotation_guideline.md` |

| 단계 | 스크립트(`scripts/`) |
|---|---|
| 쿼리 | `make_writer_sheets.py`(작성 시트), `select_old_benchmark_a.py`(A head), `import_service_queries.py`(→ 쿼리 표), `export_service_query_table.py`(전체 표) |
| 사례·주 평가셋 | `build_service_instances.py`(random·anchor), `build_service_eval_set.py` |
| 판정 pool | `build_service_pool.py`(반경 1·2km), `build_x23_round.py`(10km·지역·지도) — 둘 다 export → Colab → runs → pool |
| qrels | `build_service_qrels.py`(라운드 합치기·조정) |
| 채점 | `score_service_eval.py`(시스템 단위), `eval_service_pipeline.py`(1단계 구성), `eval_x8.py`(1km + 쿼리 확장), `eval_x23.py`(정책 시뮬레이션) |

## 1. 평가 원칙

정답은 미리 다 만들 수 없다(21만 매장 × 쿼리). 그래서 **비교할 시스템들의 상위 결과를 모아(pool) 사람이 판정하고, 그 판정으로
모든 시스템을 채점한다**(TREC pooling). 순환 논리가 되지 않게 아래를 지킨다.

| 조건 | 이유 | 이 저장소에서 |
|---|---|---|
| 판정자는 어느 시스템·몇 위 결과인지 모른다 | 알면 새 시스템에 후하게 매긴다 | 시트에 시스템·순위 없음, 쿼리·가게 순서 섞음 |
| 비교하는 시스템 **전부**의 상위를 같은 라운드에서 판정 | 한쪽만 판정하면 그쪽만 판정 누락을 벗어난다 | 후보를 모아 일괄 판정 |
| 판정은 (쿼리, 가게) 단위로 고정, 위치·순위·시스템과 무관 | 같은 가게는 누가 가져와도 같은 점수 | 판정한 쌍은 다시 판정하지 않고 새 쌍만 더함 |
| 판정 → 튜닝 → 판정을 같은 쿼리로 반복하지 않는다 | dev를 외운다(adaptive overfitting) | 결정 주기마다 한 번 |
| test는 판정을 먼저 끝내고 점수는 마지막에 한 번 | 점수를 보고 바꾸면 test가 오염된다 | test 채점은 구성 하나만(`--only`, 정책 고정 후) |
| AI 초안은 참고만, 점수는 사람이 확정 | v1.2 "AI 보조 사용 원칙" | A·B가 같은 AI 초안을 보면 일치도가 부풀므로 초안은 한 명만 본다 |

**순서 — 판정 없이 고르고, 모아서 한 번에 판정하고, test는 한 번.**

1. 탐색: 새 구성마다 판정하지 않는다. dev에서 nDCG@10(판정만, condensed — Sakai 2007), Judged@10, bad@3, top1_ok를 보고 후보만 고른다.
   Judged@10이 0.95 미만이면 판정 누락이 점수를 깎는 중이므로 공식 nDCG로 "나빠졌다"고 하지 않는다.
2. 후보 등록: 기준 대비 nDCG(판정만)가 떨어지지 않고(−0.005 이내) bad@3·top1_ok 중 하나가 좋아진 구성.
3. 일괄 판정: 결정할 때 후보 전부의 상위 10개 중 미판정 쌍을 한 라운드로 판정한다(5절).
4. dev로 구성 **하나**를 고르고, 정책 파일을 고정·커밋한 뒤 그 구성만 test를 한 번 채점한다.

- dev 실패 쿼리에 맞춘 데이터·규칙을 만들지 않는다. 실패는 **유형** 파악에만 쓴다.
- 보고: 사례 수, nDCG@10(95% CI), Judged@10, bad@3(개수/전체), top1_ok, 기준 대비 Δ·CI·p(같은 사례끼리, 부호 뒤집기 순열검정)·wins/losses.
  Δ < 0.03이거나 p ≥ 0.05면 "개선"이라 하지 않는다. 같은 설정도 다시 돌리면 ±0.005 정도 흔들린다.
- 이번 구성은 test를 이미 썼다. 새 구성을 test로 재려면 그 구성의 상위를 새로 판정한 뒤 한 번만 잰다.

기존 벤치마크(`storesearch_ko_v1`, 임베딩 모델 비교)의 일괄 판정은 `configs/benchmark/judging_candidates.yaml` 등록 →
`python scripts/collect_judging_candidates.py`(건수만) → `--make --reason "..."`(A·B 시트) → `16_supplemental_round.py merge` → 조정 →
`11_build_qrels.py` → `12_validate_benchmark.py --stage final` → `rescore_evaluations.py` 순서다(`docs/archive/CODE_AND_RUN.md` 4~6절).

## 2. 서비스 쿼리셋

기존 벤치마크(업종 의도 72개)는 업종명을 보고 쓴 쿼리라 실제 사용자 쿼리를 넓게 재지 못해 별도 셋을 만들었다. **평가 전용**이다
(학습에 쓰지 않는다 — 쓰면 평가 정밀도를 잃고, 학습 이득은 작다).

### 2-1 묶음

| 묶음 | 내용 | 작성 재료 |
|---|---|---|
| A 업종 | 기존 셋에 없던 업종·품목(tail) + 기존 벤치마크 val/test 업종(head) | `A_업종후보`, `select_old_benchmark_a.py` |
| B 상호명·브랜드 | 체인(GS25↔지에스25), 개별 상호의 전체·일부·지점명 | `B_가맹점표본`, `B_체인목록` |
| C 상황 | 업종명 없이 상황 카드만 보고 쓴 쿼리 | `C_상황카드` |
| D 지역+업종 | "망원시장 떡집" | `D_시장표본` |
| E 결과 없음 | 가맹점이 아닐 법한 대상(코스트코, 신세계) | 없음 |

- 오타는 넣지 않는다(철자 교정은 앞단 처리).
- A head는 업종당 최대 2개(짧은 형태 1 + 자연스러운 형태 1)다. 같은 업종 변형은 점수가 같이 움직여 3개째부터 표본이 거의 늘지 않는다.
  train 업종은 v1 학습에 써서 뺀다. split은 업종 단위로 val → dev, test → test(설정 `import.old_benchmark_a`).

### 2-2 쿼리 작성 — 사람이 직접 쓴다

- **test 쿼리는 사람이 쓴 것이다. AI 초안은 쓰지 않는다.** AI 초안을 사람이 검수만 하면 LLM 말투를 재게 된다(팀 작성본의 AI 초안 A·C·D·E 350개는 버렸다).
- 작성자 3명(W1~W3, 1명 이상 팀 밖)이 서로 보지 않고 각자 쓴다. AI·검색·지도를 보지 않는다. 한 번 쓴 것은 고치지 않는다.
- C → E → A → D 순서로 쓴다(재료가 적은 것부터 — 업종 목록을 먼저 보면 그 단어를 베낀다). B는 표본 가게를 보고 거꾸로 쓴다.
- 진행자는 문구를 고치지 않고 표시만 한다(중복·오타·범위밖·묶음 정정).
- 시트: `python scripts/make_writer_sheets.py`(배정은 설정 `writers` 블록과 seed). 작성자에게는 `--layout per-writer`로 따로 준다
  (한 파일을 공유하면 서로의 쿼리가 보인다). 추가분은 `--extra-c` / `--extra-b`. 회수본은 `data/query/writers_completed/`에 두고 설정 `import.writers_completed`에 더한다.

```bash
python scripts/import_service_queries.py --dry-run   # 묶음 × split 개수, 제외·중복 요약
python scripts/import_service_queries.py             # → data/query/service_queries_v1.csv (+ .meta.json)
python scripts/export_service_query_table.py         # → benchmark/service_ko_v1/queries.csv(batch·source·freq·eval_set·n_judged 열)
```

가져오기 규칙:
- 공백 제거·소문자로 같은 문자열은 합친다(`n_writers`). 여러 묶음에 나오면 `import.bundle_priority`(B > D > C > A > E) 앞 묶음.
- 기존 벤치마크 **train**과 같은 문자열, 설정 `import.exclude_queries`는 `status=excluded`(행은 지우지 않음).
- 템플릿 배포 뒤 seed(`random_seed`)를 바꾸지 않는다. 바꾸면 표본 ID(S·M번호)가 다른 가게를 가리킨다.

### 2-3 split

- dev 25% / test 75%, 묶음마다. 같은 근거(A 업종, C 카드, B 가맹점, D 시장)의 쿼리는 같은 쪽에 둔다 — dev에서 본 카드가 test에 다시 나오면
  dev 튜닝이 test에 샌다.
- dev: 개발 중 지표·실패 유형. test: 결정 시점에 한 번.

### 2-4 가정위치

| 묶음 | 위치 |
|---|---|
| B 개별 가게 | 그 가게 좌표 |
| B 브랜드, D | 작성자가 고른 시장 |
| A·C·E | 쿼리 문자열 해시로 **전체 가맹점 중 하나**를 골라 그 좌표(`location_source=auto_store`). 가맹점 밀도에 비례 |

- 쿼리 내용과 무관하게 고른다(정답이 있는 곳을 고르면 평가가 쉬운 쪽으로 치우친다).
- 검색 로그가 없어서 쓰는 **대용 가정**이다. 로그를 받으면 로그의 (쿼리, 위치)로 바꾸고, 보고에 대용임을 적는다.

### 2-5 주 평가셋 — 가정 쿼리 비율에 맞춘 사례 목록

- 설정 `eval_set.shares` B 50 / A 35 / D 10 / C 5, A 안은 head:tail 50:50(`strata`). 쿼리마다 사례 하나(1km 안 정답이 있는 random, 없으면 anchor).
- split마다 "쓸 수 있는 쿼리 수 ÷ 비율"이 가장 작은 묶음(지금 B)이 크기를 정한다. 지금 test 320 / dev 108.
- 이전 `eval_set.csv`의 사례는 정답이 남아 있는 한 그대로 둔다(같은 입력이면 같은 결과). E는 순위 지표가 없어 밖에서 따로 본다.
- 비율은 우리 서비스 로그 없이 정한 가정이다(일반 웹 검색 로그 연구의 경향을 보고 팀이 정함). 보고에 적는다.

```bash
python scripts/build_service_eval_set.py --dry-run   # 묶음별 크기, 이전 셋 대비 바뀐 수
python scripts/build_service_eval_set.py
```

### 2-6 평가용 묶음 — C의 업종·품목명형을 A로 센다

C는 상황 카드에서 출발했지만 "쌀", "치과"처럼 업종·품목 이름을 그대로 쓴 쿼리가 절반을 넘었다. 이 쿼리들은 점수가 A와 같아서
섞이면 C 점수가 상황 검색을 재지 못한다. 그래서 **작성 뒤에** 진행자가 분류한다(작성자 안내는 바꾸지 않는다).

판단 질문: **"이 쿼리를 보고 가게 종류를 하나로 바로 말할 수 있나?"** — 판정된 정답 가게가 한 종류로 모이면 A, 퍼지면 C.

| 규칙 | 조건 | 예 |
|---|---|---|
| A1 | 가게 종류 이름이 있거나 하나로 정해진다 | 치과, 동네 미용실, 눈 검사할 곳(안경점) |
| A2 | 파는 물건·서비스 이름이 있다(수식어 붙어도 됨) | 우산, 쌀 사는 곳, 하객 원피스 |
| A3 | 수리·수선 대상이 가게 취급품목에 업종처럼 적혀 있다 | 휴대폰 수리, 구두 수선 |
| C1 | 상황·목적·행사만 있고 정답이 여러 종류로 퍼진다 | 집들이 선물, 자취용품 |
| C2 | 수리·수선 대상이 가게 데이터에 없다 | 운동화 수선, 수도꼭지 수리 |
| C3 | 어떤 가게인지 하나로 떠오르지 않는다 | 야식, 술안주 파는 곳 |

- 반영: 목록 `data/query/service_eval_bundle_v1.csv`(설정 `eval_set.bundle_overrides`) → `service_eval.apply_eval_bundle`이 주 평가셋·채점의
  묶음만 바꾸고 원래 묶음은 `source_bundle`에 남긴다. query_id·qrels·split·판정 규칙은 그대로. 쿼리 표와 목록의 묶음이 어긋나면 멈춘다.
- 옮긴 쿼리(109개)는 C 규칙으로 판정된 그대로 쓴다(재판정 안 함). 보고에 적는다.
- 효과: 주 평가셋 크기는 그대로(test 320), test의 C 16개가 모두 상황형이 됐다. 측정 변경이라 바꾸기 전 묶음별 점수와 비교하지 않는다.
  C 16개는 n과 구간을 같이 적고 큰 실패 확인용으로만 쓴다(시스템 비교 근거 아님).
- B 상호 일부·지역+상호 쿼리("청송", "효준")는 빼지 않는다. 근처 1km에서 찾는 가게가 하나로 정해지면 그대로 쓴다.
- 앞으로 C를 보충하면: `scenario_cards_extra`에 카드 추가 → `make_writer_sheets.py --extra-c` → 가져오기 → 위 기준으로 분류.

## 3. 평가 단위와 지표

### 3-1 사례 = 쿼리 × 가정위치

| 맥락 | 위치 | 쓰임 |
|---|---|---|
| random | 2-4절의 가정위치 | 순위 품질 + "근처에 없음" |
| anchor | random 위치 1km 안에 정답이 없는 A·B(브랜드)·C 쿼리에, 의도에 맞는 가게(앵커) 근처 좌표 | 순위 품질(조건부) |

- anchor는 "근처에 맞는 가게가 있을 때 잘 찾는가"를 재는 조건부 점수다. 정답 비율 같은 서비스 통계로 쓰지 않는다.
- 앵커는 쿼리·의도 단어로 고르고 시스템 결과는 보지 않는다. 엉뚱한 업종을 고르는 쿼리는 설정 `judging.anchor_keywords`로 지정한다.
  앵커 가게도 사람이 판정하므로 앵커가 틀리면 그 사례에 정답이 없을 뿐 점수가 틀어지지 않는다.

```bash
python scripts/build_service_instances.py                              # 처음 한 번(파일이 있으면 멈춤)
python scripts/build_service_instances.py --append-new --batch <이름>   # 새 활성 쿼리의 random 사례만 덧붙임
python scripts/build_service_instances.py --add-anchors [--dry-run]     # 판정 뒤 정답 없는 쿼리에 anchor(기본 batch anchor_extra)
python scripts/build_service_instances.py --add-anchors --proxy-old-qrels --only-batch extra_a --batch anchor_extra_a
    # 기존 벤치마크 쿼리: 서비스 판정 전에 기존 판정으로 anchor를 미리 붙여 한 라운드로 판정
```

batch 이름 = `build_service_pool.py --set` 묶음 이름(main, anchor, extra, extra_b, anchor_extra, extra_a, anchor_extra_a). 새 batch는 `SETS`에 폴더를 더해야 한다.

### 3-2 지표

- 반경 R(1km·2km) 안 결과만 남겨 순위를 다시 매기고 nDCG@10, Judged@10, bad@3(상위 3개가 모두 오답), top1_ok를 낸다.
  이상적 순위(IDCG)도 반경 안 판정된 가게로 만든다. 2점 이상이 정답.
- **반경 안 정답이 없는 사례는 순위 지표에서 뺀다**(TREC: 정답 없는 토픽 제외). 수는 `no_answer_instances`로 따로 보고한다.
- 보고 단위: 반경 × split × 묶음(A head / A tail / B / C / D) × 맥락, 속성 쿼리 따로. 전체 평균 하나는 묶음 비율에 좌우되므로 묶음별로 같이 본다.
- 정책 시뮬레이션(`eval_x23.py`)은 요청 단위로 헛된 "없음"(범위 안 정답이 있는데 아무것도 안 보임), 확장 비율, 상위 3개 평균 거리,
  지도 노출 정밀도를 더한다.

### 3-3 필요한 사례 수

- 목표: 묶음마다 1km 정답 있는 test 100개 이상. 절대 nDCG를 ±0.03 안팎으로, 묶음 간 차이 0.05를 말할 수 있다(Sakai 2016, topic set size design).
- 쿼리별 차이의 sd는 묶음마다 약 0.16~0.20이었다. 유의수준 5%, 검정력 80%로 Δ0.05에 약 80~125개, Δ0.03에 약 220~340개가 필요하다.
- bad@3 ≤ 0.05를 판별하려면(실제 0.03일 때) test 약 300개.
- 지금 C test(상황형 약 42개, 주 평가셋 16개)와 D(38개)는 묶음 결론에 부족하다 — 큰 실패 확인용.

## 4. 판정 기준

**기본은 가이드라인 v1.2**(`benchmark/storesearch_ko_v1/annotation_guideline.md`)이고, 아래는 서비스셋에만 있는 쿼리 유형의 기준이다.
두 문서가 다르면 이 절을 따른다.

### 4-1 점수 — 기존과 같다

| 점수 | 뜻 |
|---|---|
| 3 | 쿼리 의도를 바로 채우는 가맹점 |
| 2 | 의도를 채우지만 핵심이 아니거나 일부만 채움 |
| 1 | 관련은 있지만 찾는 가게는 아님(같은 업종의 대안 등) |
| 0 | 관련 없음 |

2점 이상을 정답으로 센다. 판정자는 어느 시스템이 몇 위로 가져온 가맹점인지 모른다.

### 4-2 지역 — 판정하지 않는다

- 판정자는 가맹점의 위치·거리를 보지 않는다. "망원시장 떡집"도 떡집이면 3점이다.
- 지역이 맞는지는 좌표·법정동 코드로 자동 처리한다. 판정 대상은 이미 요청 범위 안의 가맹점이다.
- 그래서 반경을 바꿔도 판정은 다시 하지 않는다. 줄이면 다시 채점만, 늘리면 새로 들어온 가맹점만 판정한다.

### 4-3 쿼리 유형별 기준

**B 개별 가맹점** ("왜관 발톱닥터 네일", "광복카센타")

| 경우 | 점수 |
|---|---|
| 찾는 그 가게. 상호가 같으면 지점·띄어쓰기·법인 표기가 달라도 같은 가게로 본다 | 3 |
| 같은 업종의 다른 가게 | 1 |
| 상호 일부만 겹치는 다른 업종 가게, 그 밖 | 0 |

**B 브랜드** ("교촌", "GS25", "텐퍼센트커피")

| 경우 | 점수 |
|---|---|
| 그 브랜드의 지점. 표기가 달라도 같은 브랜드면 3점(지에스25·GS25, 비비큐·BBQ) | 3 |
| 같은 업종의 다른 브랜드(교촌 → 다른 치킨집) | 1 |
| 그 밖 | 0 |

반경 안에 그 브랜드 지점이 여러 곳이면 **전부 3점**이다(가까운 지점만 정답이 아니다 — 거리는 4-2대로 판정하지 않는다).

**E 결과 없음** ("코스트코", "신세계", "백화점")
- 이름만 겹치고 의도를 채우지 못하는 가게는 **0점**이다(신세계약국, 원일정육백화점, 온천어묵, 샤넬의상실).
- 의도를 일부라도 채우면 다른 쿼리처럼 판정한다("5성급 호텔" → 일반 숙박업소 1점, "스타벅스" → 다른 카페 1점).
- 2점 이상이 나온 E 쿼리는 E가 아니므로 진행자가 설정 `import.exclude_queries`로 빼거나 A로 옮긴다.

**C 상황** ("집들이 선물", "야식")
- **쿼리 문자열만 보고** 보통 사람이 그 말로 찾을 가게를 기준으로 판정한다. 작성자가 적은 의도(`intent`)는 참고만 한다.
- 해석이 여럿이면 그럴듯한 해석 하나라도 채우면 2점 이상이다("집들이 선물" → 꽃집·와인샵·생활용품점 모두 가능).

**데이터에 없는 속성** ("단체 예약 가능 식당", "늦게까지 여는", "맛집", "24시", "분위기 좋은")
- 가맹점 데이터에 영업시간·예약·평판이 없으므로 **속성은 판정하지 않고 업종·상품만 본다**. "24시 당구장"이면 당구장이면 3점.
- 이런 쿼리는 `attribute` 표시로 따로 집계한다(설정 `judging.attribute_keywords`).

**A 업종, D 지역+업종**: 가이드라인 v1.2와 같다(D는 4-2대로 지역을 보지 않으므로 A와 같은 방식).

### 4-4 판정 운영

- 판정자 A·B 두 명. 쿼리의 20%는 둘 다 독립 판정해 일치도를 재고(`judging.double_annotation_share`), 나머지는 판정 쌍 수가 비슷하게
  한 명에게만 준다. 판정자가 쓴 쿼리는 가능하면 다른 사람에게 준다(`judging.annotators`).
- 판정 파일은 `annotations/<round>/판정_A.xlsx`, `판정_B.xlsx`. relevance(0~3)·uncertain(Y)은 드롭다운, `annotator_note`는 자유.
  한 쿼리의 후보가 이어서 나오고, 쿼리 순서와 쿼리 안 가게 순서는 섞여 있다.
- 채운 시트는 같은 폴더에 `annotation_A_completed.csv`, `annotation_B_completed.csv`로 저장한다(열은 그대로).
- AI 초안은 판정자 한 명만 본다. 점수는 사람이 확정한다.

### 4-5 확정·조정 규칙

자동 확정(`build_service_qrels.py`):
- 한 명만 판정했거나 둘이 같은 점수 → 그 점수. 한 명이 빈칸이고 한 명이 점수 → 그 점수.
- 이진 판정(2점 이상 여부)은 같고 점수만 다름(0↔1, 2↔3) → **낮은 점수**(보수적).
- 이진 판정이 다르거나, 아무도 점수를 주지 않음 → 조정 대상.

사람이 조정할 때:
- 조정 점수는 보통 두 판정자 점수 사이에서 고른다. **범위를 벗어나는 점수를 줄 때는 `adjudication_note`에 근거를 적는다**
  (예: "식육·정육점은 고기 내장도 판다").
- 같은 쿼리에서 같은 종류의 가게(편의점끼리, 같은 업종의 식당끼리)는 같은 점수를 준다. 다르게 줄 때는 이유를 적는다.
- 취급품목이 비어 상호만으로 업종을 알 수 없으면 판단 보류(빈칸)로 둔다 — 상호에서 추측한 높은 점수를 주지 않는다.
- `final_relevance`를 빈칸으로 두면 gold에서 빠진다(미판정 취급).

## 5. 판정 라운드 실행 순서

모든 라운드는 같은 틀이다: **후보 범위를 정한다 → 시스템(또는 정책) run을 만든다 → 상위 depth 중 미판정 쌍만 시트로 → 판정 → qrels.**
임베딩 run은 Colab(`colab/service_dense_runs.ipynb`)에서 만든다. Colab은 Drive에 같은 이름의 결과가 있으면 건너뛰므로, 다시 돌릴 때는
Drive의 옛 `<모델>.csv`를 먼저 지운다.

### 5-1 반경 1·2km pool (`build_service_pool.py`)

판정 범위는 가정위치 2km 안(`judging.judge_radius_km`), 채점은 1km·2km(`report_radii_km`). pool은 시스템(`judging.dense_models`의
v1 bge-m3 mj·bge-m3 zero-shot + char BM25)마다 **1km 안 상위 depth와 2km 안 상위 depth**를 합치고, 키워드 후보(쿼리 단어가 상호·취급품목에
든 가게, `keyword_per_query`)와 앵커 가게를 더한다. 1km를 따로 넣는 이유: 2km 순위 11~50위가 1km로 좁히면 상위 10에 올라온다.

```bash
python scripts/build_service_pool.py export --set <묶음...>   # 반경 안 가맹점·쿼리 → colab_upload/service_eval[_<묶음>]/
#   Colab: colab/service_dense_runs.ipynb → <모델>.csv를 benchmark/service_ko_v1/runs[_<묶음>]/에
python scripts/build_service_pool.py runs --set <묶음...>     # char BM25·키워드 후보 run(로컬)
python scripts/build_service_pool.py pool --set <묶음...> --dry-run         # depth별 판정 건수
python scripts/build_service_pool.py pool --set <묶음...> --round service_vN --depth 10
#   --eval-set-only: 주 평가셋 사례만 후보로(새 시스템 보충 판정)
```

- `--set` 기본은 main, pool은 여러 묶음을 한 라운드로 합친다. run은 반경마다 그 안 상위 `run_depth`(50)개를 합쳐 저장한다.
- BM25·키워드 후보 쿼리에서는 서술어('파는', '곳')와 지역 표현을 뺀다(후보가 이미 반경 안이라 지역 단어가 같은 지점명 가게를 끌어온다).
- 쿼리 위치가 바뀌면 모든 run을 다시 만든다. `pool`은 run 결과가 지금 위치의 반경 밖이면 멈춘다.
- 이미 판정한 묶음의 run은 다시 만들지 않는다(BM25 색인 범위가 바뀌면 순위가 흔들려 판정 범위와 어긋난다). 새 쿼리는 새 묶음으로.
- 1단계 구성 보충은 `eval_service_pipeline.py --exp rerank --pool-round ...`, 쿼리 확장 보충은 `eval_x8.py --pool-round service_vN [--dry-run]`
  (확장 구성의 반경별 상위 10 중 미판정 쌍, dev+test 모든 사례).

### 5-2 10km·지역·지도 라운드 (`build_x23_round.py`)

2km 판정만으로는 10km 확장, 원격 사용자의 지역 검색, 지도 화면 결과를 잴 수 없어 주 평가셋 사례(dev+test)마다 '요청'을 만든다.

| 요청 | 후보 범위 | 채점 |
|---|---|---|
| expand | 사례 위치 반경 10km | 1km·10km — 반경 확장 |
| region_point | 원격 사용자(서울시청, 사례가 서울 근처면 부산시청)가 같은 쿼리를 칠 때 쿼리 이해가 고른 좁은 지역(동·역·시장) 중심 10km | 1km·10km |
| region_area | 넓은 지역(시도·시군구·읍면) — 법정동 코드 앞자리 필터 | 지역 안 |
| map5 | 업종 쿼리 사례 위치 중심 5km × 5km 화면 | 화면 안(1km 화면은 이미 판정된 1km 원 안이라 뺌) |

```bash
python scripts/build_x23_round.py export              # 요청표 x23/requests.csv + Colab 입력 colab_upload/service_eval_x23/
#   Colab: colab/service_dense_runs.ipynb — SETS=["service_eval_x23"], MODELS는 bge_m3_ft_mj만
#          → bge_m3_ft_mj_20261014_0743.csv를 benchmark/service_ko_v1/runs_x23/에
python scripts/build_x23_round.py runs                # 로컬 char BM25 run(같은 후보 범위)
python scripts/build_x23_round.py pool --dry-run      # 판정 건수(종류·depth별)
python scripts/build_x23_round.py pool --round service_vN --depth 10
```

- 필터 요청(region_area·map5)은 노트북의 요청별 필터(`code_prefix`·`bbox`)가 필요하다. 필터 요청만 다시 돌릴 때
  `export --filtered-only` → `colab_upload/service_eval_x23f/` → `runs_x23f/`(있으면 그 결과를 쓴다).
  쿼리 이해 수정으로 범위가 바뀐 요청만 다시 돌릴 때 `export --p0` → `runs_x23p0/`(새 run이 없는 요청은 판정·채점에서 뺀다).
- 요청 범위 밖 행이 하나라도 있으면 라운드를 만들지 않는다. 그 요청을 빼고 만들려면 `--allow-partial`.
- **판정 대상은 평가할 정책 구성이 실제로 상위 depth에 올리는 가게**다(정책 파일의 확장·상호 코사인·완전 일치 그대로 + 반경 요청은 거리 감쇠
  h = 2·5km 변형). 확장 가중치는 기본이 정책 `ranking.expansion_w`, `--expansion-w`로 바꾼다(0이면 끔).
- 새 구성을 검증하려면: 정책 파일을 그 구성으로 바꿔 `pool --dry-run` → `pool --round <새 라운드>` → 판정 → qrels → dev 채점 → test 한 번.

### 5-3 qrels

```bash
python scripts/build_service_qrels.py
```

- `pool_manifest.json`이 있는 모든 라운드의 `annotation_*_completed.csv`를 합친다. 완료 시트가 없는 라운드는 건너뛴다.
- 조정 대상은 `annotations/<round>/analysis/adjudication_needed.csv`로 나온다 → `final_relevance`를 채워 `adjudication_completed.csv`
  (또는 `adjudication_needed_completed.csv`)로 저장 → 다시 실행하면 반영된다(4-5절).
- 라운드별 판정 수·조정 대상·판정자 일치도(이진 κ)는 `qrels_status.json`. 보고에 κ를 적는다(지금까지 0.65~0.97, 정답이 드문 라운드는 낮게 나옴).
- qrels가 바뀌면 `build_service_eval_set.py`(주 평가셋)와 `export_service_query_table.py`(쿼리 표)를 다시 돌린다.

### 5-4 지금까지의 라운드

| 라운드 | 대상 | 만든 방법 |
|---|---|---|
| service_v1 | 1차 쿼리 498개, random, 2km 상위 10 | `build_service_pool.py pool` |
| service_v2 | 같은 사례, 1km 상위 10(새 쌍만) | 같음 |
| service_v3 / v4 / v6 | anchor 사례 / 추가 C / 추가 B | `--set anchor` / `extra` / `extra_b` |
| service_v5 | 1단계·reranker 상위 10 보충 | `eval_service_pipeline.py --exp rerank --pool-round` |
| service_v7 | 반경별 run 보충(5개 묶음) + 추가 C의 anchor | `pool --set main anchor extra extra_b anchor_extra` |
| service_v8 | A head(기존 벤치마크 업종) random + anchor | `--set extra_a anchor_extra_a` |
| service_v9 / v10 | 새 임베딩 후보 보충(주 평가셋만) | `pool --eval-set-only` |
| service_v11 | 10km·지역·지도 요청 756개 | `build_x23_round.py pool` |
| service_v12 | LLM 쿼리 확장 w 0.1~0.3 상위 10 보충 | `eval_x8.py --pool-round` |
| service_v13 | 확장 적용 정책 목록 상위 10 보충(dev+test) | `build_x23_round.py pool`(확장 w 0.3) |

## 6. 채점·정책 시뮬레이션 실행

판정이 qrels에 들어간 뒤 돌린다. 판정 전에 돌린 숫자는 코드 확인용이다(Judged@10을 같이 보고, 0.95 미만이면 비교하지 않는다).

| 스크립트 | 대상 | 출력 |
|---|---|---|
| `score_service_eval.py` | 시스템(임베딩·BM25) × 반경 × split × 묶음 × 맥락, **모든 사례**(주 평가셋으로 거르지 않음) | `results/service_eval/summary.csv`, `pairs.csv`(시스템 − v1), `per_instance.csv` |
| `eval_service_pipeline.py --exp ...` | 1단계 구성(hybrid, hybrid2, qu, brand, rerank), 주 평가셋(`--set main` 기본) | `results/service_pipeline/` |
| `eval_x8.py` | 1km 1단계 + reranker 가산 / LLM 쿼리 확장, 주 평가셋 | `results/service_pipeline/x8/x8_<split>[...].csv`, `_paired.csv` |
| `eval_x23.py` | 정책 시뮬레이션(expand·region_point·region_area·map5) | `results/service_pipeline/x23/summary_<split><suffix>.csv`, `per_request_...`, `shown_...`(`--dump`) |

```bash
python scripts/score_service_eval.py                      # dev+test 전체와 test만 둘 다
python scripts/eval_x8.py                                 # dev 주 평가셋(--set all: dev 모든 사례)
python scripts/eval_x23.py                                # dev(결정용) — 정책 파일 값으로
python scripts/eval_x23.py --expansion-w 0 --suffix _exp0 # dev 비교 예: 확장 끔
python scripts/eval_x23.py --dump --suffix _base          # 노출 목록(상위 20) 정성 점검용
```

- `eval_x23.py`는 정책 파일(`--policy`, 기본 `configs/service/search_policy_v1.yaml`)을 그대로 흉내 낸다: 관련 = P(관련) ≥ `relevance.threshold_p`
  (브랜드 지점은 확률 없이 관련), 1km 관련이 `radius.expand_if_relevant_below`개 미만이면 10km, 확장 정렬 `ranking.expanded_order`,
  지역·지도는 범위 안 관련 전부. dev 비교용 덮어쓰기: `--expansion-w`, `--category-gamma`, `--brand-others-min`, `--exact-name 0|1`,
  `--calibrator`, `--area-calibrator`, `--full-cosine --cosine-scope all|name`, `--dense-query full|no_region`, `--refit-oof k --refit-scope all|area`.
- `eval_x8.py`는 정책 파일을 읽지 않는다. 채택 구성은 `--final`(= `--full-cosine --cosine-scope name --exact-name`, `--only` 없으면 `"exp+0.3 cat"`)로 켠다. test는 `--only` 또는 `--final`이 반드시 필요하다.

**최종 test(2026-11-09) 명령** — 정책을 고정·커밋한 뒤 구성 하나만:

```bash
python scripts/eval_x23.py --split test
python scripts/eval_x8.py --final --split test
```

- 결과: `x23/summary_test.csv`·`per_request_test.csv`, `x8/x8_test_fcn_ex.csv`·`_paired.csv`(`results/service_pipeline/` 아래). 같은 이름으로
  덮어쓰므로 새 test 전에 옛 파일을 보관한다(이전 test는 `_1105` 접미사). 최종 숫자는 `docs/BACKEND_HANDOFF.md` 3절.

## 7. 한계 — 결과 보고에 적을 것

- **가정이 셋 있다**: 묶음 비율(`eval_set.shares`), 작성자 3명, 가정위치(밀도 비례 대용). 이 셋의 점수는 실제 서비스 평균이 아니라
  PoC 근거다. 로그를 받으면 (쿼리, 위치)와 묶음 비율을 로그 분포로 바꾸고, 빈도 구간별 층화 추출로 쿼리를 더한다.
- **D(지역+업종)는 1km 평가에서 의미 있게 재지 못한다.** 가정위치를 그 지역에 두어 "망원시장 떡집"이 "떡집"과 같은 문제가 된다.
  원격 사용자의 지역 검색은 5-2절 region_point·region_area 요청으로 따로 잰다.
- "양곡시장 음식"처럼 업종이 너무 넓은 쿼리는 반경 안 대부분이 정답이라 천장에 붙는다.
- C test(주 평가셋 16개)·넓은 지역(28개)은 n이 작다 — n과 구간을 같이 적고 시스템 비교 근거로 쓰지 않는다.
- 평가용 묶음으로 A에 옮긴 109개는 C 규칙으로 판정됐다.
- E는 정답이 없어 nDCG로 못 잰다. 평가 방법은 정하지 않았다.
- 판단 보류(정보 없는 가게)는 미판정으로 둔다 — 상호만 있는 가게가 많은 쿼리는 Judged@10이 조금 낮다.
- 폴백(임베딩 장애) 동작은 평가하지 않았다.

근거: Voorhees & Harman (2005) TREC pooling, Zobel (1998) pool 편향, Sakai (2007) condensed nDCG, Sakai (2016) topic set size,
Dwork et al. (2015) reusable holdout, Lv et al. (SIGIR 2012) 거리 감쇠.
