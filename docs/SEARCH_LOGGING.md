# 검색 로그 설계(추천안, 2026-11-03)

서비스 개발 쪽과 합의할 초안이다. 구현은 자바 백엔드에서 한다(`docs/BACKEND_HANDOFF.md`) — 이 저장소의 실험(X1~X7)은 로그 없이 판정셋으로 한다. 기준은 공개된 검색 로그 표준 두 가지 — **OpenSearch User Behavior Insights(UBI)**(검색 1건 = query
기록, 그 뒤 사용자 행동 = event 기록, 둘을 `query_id`로 잇는다)와 **Algolia Insights**(클릭·전환 이벤트에 `queryID`·`objectID`·
`position`(1부터) 필수). 우리 과제에 맞춰 위치·반경·지역 해석 필드를 더했다.

## 1. 왜 지금 정하나

| 쓰임 | 필요한 로그 | 근거 |
|---|---|---|
| 관련 임계값·"없음" 판단을 실제 사용으로 다시 맞춤(X1) | 노출 결과·점수, 클릭·전환 | 판정셋은 쿼리 수백 개 — 로그가 쿼리 분포의 표준(평가 정책 7절) |
| 같은 이름 지명의 인지도(지금은 공공데이터 근거 갈래 수로 대신) | 지역 해석, 다른 곳 선택 | 질의 지명의 의도 판별에 로그를 쓰는 관행(Wang et al., SIGIR 2005) |
| 거리·순위 학습(Lv et al., SIGIR 2012 — 클릭률은 거리에 따라 완만히 감소) | 노출 순위·거리·클릭 | 위치 편향 보정 학습(Joachims et al., WSDM 2017)에는 노출 **순위**가 필수 |
| 새 구성 비교(A/B, interleaving — Chapelle et al., TOIS 2012) | 구성 버전, 노출 목록 | 어떤 구성이 어떤 목록을 보였는지 없으면 비교 불가 |
| 실패 탐지 | 결과 없음, 바로 다시 검색, 이탈 | 다시 검색(재질의)은 실패의 대표 신호 |

## 2. 이벤트

### 2-0 수집 방식·공통 필드(2026-11-09 PR #9 리뷰 반영 — UBI·Algolia Insights와 같은 구조)

- **서버**: 검색 API가 응답을 만들 때 `search`와 노출 결과(`results`)를 기록한다. 응답 지연을 막으려고 비동기로 쓴다.
- **화면**: 2-2 이벤트를 모아 몇 초마다 묶어 보낸다. 페이지를 떠날 때는 `sendBeacon`, 앱은 로컬에 저장했다가 다시 보낸다.
- **모든 이벤트 공통 필드**

| 필드 | 비고 |
|---|---|
| `event_id` | UUID — 재전송으로 같은 이벤트가 두 번 들어와도 거른다 |
| `client_ts`, `server_ts` | 화면 시각(순서), 서버 시각(기준) |
| `schema_version` | 로그 스키마 버전 |

- **impression 기준**: 카드 면적 50% 이상이 1초 이상 보였을 때(MRC 노출 기준을 관례로 씀).
- **회원과 연결하지 않는다**: 분석 로그에는 `session_id`만 둔다. 3절 지표(결과 없음·확장·재질의·첫 클릭 순위·전환)는
  `query_id`와 세션만으로 계산된다. 회원 ID(해시)와 100m 격자 위치가 함께 남으면 개인위치정보가 되거나 가명정보 재식별 위험이 생긴다(4절).
- **최근 검색어(회원 기능)는 별도 테이블**: 회원 ID, 검색어, 시각만 저장하고 회원이 지울 수 있다. 좌표와 `query_id`는 넣지 않는다
  (`query_id`가 있으면 그것만으로 분석 로그와 이어진다).

### 2-1 search (검색 1건 — UBI의 query 기록)

| 필드 | 예 | 비고 |
|---|---|---|
| `query_id` | uuid | 이후 모든 이벤트가 이 값으로 이어진다. 페이지를 넘겨도 같은 값(순위는 절대 순위) |
| `session_id` | 해시 | 회원 ID는 남기지 않는다(2-0) |
| `app_version`, `pipeline_version`, `corpus_version` | | 구성(임베딩·임계값·정책 파일 버전)과 가맹점 스냅샷 — A/B 비교·데이터 갱신 영향의 키 |
| `query`, `input` | "신촌 설렁탕", typed/autocomplete/chip | |
| `category_chip` | 음식점 / null | 업종 필터 |
| `location_source` | query_region / ui_region / map_viewport / gps / default | 검색 중심을 무엇으로 정했나(정책 location.priority) |
| `view`, `viewport` | list / map, 지도면 화면 사각형(100m 격자로 낮춤)·확대 수준 | 지도 모드는 화면 범위가 지역 필터('이 지역에서 다시 검색' 버튼마다 새 query_id) |
| `user_cell` | 100m 격자 id | **정확한 좌표는 남기지 않는다**(개인위치정보 — 4절) |
| `parsed` | region 이름·scope·code_prefix, intent, name_first, 다른 곳 후보 목록 | 쿼리 이해 결과 그대로 |
| `radius_stage` | 1km / 10km / region / region+10km | 확장했는지 |
| `n_relevant_first`, `n_relevant_final` | 3, 10 | 임계값 이상 가게 수(확장 판단 근거) |
| `message` | none / expanded_none_in_first / expanded_partial / no_result | 화면 문구 |
| `results` | [{object_id, position, distance_m, score}] 상위 20 | 노출 후보(UBI의 query_response) |
| `latency_ms` | 단계별(파싱·검색·재정렬) | |

### 2-2 사용자 행동(UBI의 event 기록) — 모두 `query_id` 포함

| 이벤트 | 필드 | 의미 |
|---|---|---|
| `impression` | object_id 목록, 보인 범위(스크롤 깊이) | 실제로 본 결과 — 클릭률의 분모 |
| `click` | object_id, position(1부터), distance_m | 상세 보기 |
| `action` | object_id, position, `call` / `directions` / `favorite` / `share` / `pay` | **전환** — 클릭보다 강한 관련 신호(Algolia conversion) |
| `dwell` | object_id, 상세 체류 초 | 짧은 클릭(곧 뒤로) = 부정 신호 |
| `region_choice` | 고른 다른 곳(예: 창원 신촌동) | 지역 해석이 틀렸다는 직접 신호 |
| `chip_change`, `research_here` | 새 업종 / '이 지역에서 다시 검색'(새 화면 범위) | 결과 다시 요청(새 query_id). 지도만 움직이고 버튼을 안 누른 것은 `map_move`(검색 아님) |
| `cluster_click`, `pin_click` | 묶음 개수·확대 / object_id | 지도에서는 순위보다 핀을 본다(Airbnb, Haldar et al., KDD 2024) — 핀 클릭은 position 대신 화면 위치로 |
| `reformulate` | 이전 query_id → 새 query_id(30초 안 같은 세션) | 실패 신호 |
| `abandon` | 결과를 보고 아무 행동 없이 종료 | |

## 3. 바로 볼 지표

- 쿼리 수준: 결과 없음 비율, 확장 비율(10km까지 넓힌 비율), 재질의 비율, 이탈 비율, 첫 클릭 순위, 전환율.
- 묶음별(상호/업종/상황 — 쿼리 이해의 intent로): 위 지표를 나눠 본다. 판정셋(B 50 / A 35 / D 10 / C 5 가정)을 로그 분포로 교체.
- 지역: `region_choice` 비율(같은 이름 지명 오해석률), `location_source=default` 비율(위치 권한 거부 — 대전 기본 위치 결과가 쓸모없는 비율).

## 4. 개인위치정보 — 법무 확인 필요

- 사용자 좌표는 위치정보법상 개인위치정보일 수 있다. 개인위치정보를 다루는 위치기반서비스는 사업 신고와 이용자 동의가 필요하다
  (개인위치정보가 아닌 위치기반서비스의 신고 의무는 개정으로 폐지 — 방송통신위원회 발표). 운영 주체(소진공) 쪽 법무 확인 뒤 확정.
- 추천: 저장 좌표는 100m 격자로 낮추고, 원 좌표는 요청 처리에만 쓰고 남기지 않는다. 보관 기간을 정해 지운다.
- 분석 로그는 회원 ID 없이 `session_id`만 남긴다(2-0). 격자 위치와 회원 ID가 같은 행에 있지 않게 하는 것이 재식별 위험을 줄이는 핵심이다.

## 5. 출처

- OpenSearch UBI 스키마: https://docs.opensearch.org/docs/search-plugins/ubi/schemas
- Algolia Insights(clickedObjectIDsAfterSearch, position은 1부터): https://www.algolia.com/doc/libraries/search-insights/clicked-object-ids-after-search.md
- AWS, OpenSearch로 검색 품질 측정(페이지를 넘겨도 같은 query_id, 절대 순위): https://aws.amazon.com/blogs/big-data/measuring-and-improving-search-quality-with-amazon-opensearch-service/
- 위치기반서비스 신고 의무 개정: https://www.kukinews.com/article/view/kuk202105120240
