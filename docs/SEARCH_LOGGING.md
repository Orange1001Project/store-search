# 검색 로그 설계

기준: 2026-11-10 팀 결정(`docs/DB_DESIGN_PROMPT.md`), 정책 `docs/SERVICE_POLICY.md` 14절. 구조는 OpenSearch User Behavior Insights(검색 1건 =
query 기록, 그 뒤 행동 = event 기록, `query_id`로 잇는다)와 Algolia Insights(클릭·전환에 `objectID`·`position`(1부터))를 따른다.

## 1. 수집

- **서버**: 검색 응답을 만들 때 검색 1건(2절)과 노출 결과(3절)를 **비동기로** 기록한다.
- **화면**: 행동 이벤트(4절)를 모아 몇 초마다 묶어 보낸다. 페이지를 떠날 때 `sendBeacon`, 앱은 끊기면 저장 후 재전송.
- **모든 이벤트 공통 필드**: `event_id`(UUID — 재전송 중복 제거), `client_ts`(화면 시각, 순서용), `server_ts`(서버 시각, 기준), `schema_version`.
- **회원과 연결하지 않는다**: 회원 ID 없이 `session_id`만. 세션은 **30분 무활동이면 새 세션**.
- 최근 검색어(회원 기능)는 로그가 아니라 별도 회원 테이블이다. 좌표·`query_id`를 넣지 않는다(넣으면 로그와 이어져 재식별).

## 2. 검색 1건 (search)

| 필드 | 예 / 값 |
|---|---|
| `query_id` | UUID. 다음 페이지도 같은 값 |
| `session_id` | 30분 무활동 기준 세션 |
| `app_version`, `pipeline_version`, `corpus_version` | 앱, 정책·계수 버전, 가맹점 스냅샷 |
| `query`, `input` | "신촌 설렁탕", typed / recent / autocomplete / chip / browse(검색어 없는 조회) / place(지명만 입력 — 지도 이동, 품질 통계 제외) |
| `category_chip`, `payment_chips` | 음식점 / null, 결제는 여러 개 목록 [qr, card, barcode] / 빈 목록(전체) |
| `location_source` | query_region / ui_region / map_viewport / gps / default |
| `view`, `viewport` | list / map, 지도 화면 범위(100m 격자) |
| `user_cell` | 사용자 위치 100m 격자 ID(원 좌표는 남기지 않음) |
| `parsed` | 지역(이름·scope·code_prefix), intent, name_first, 다른 지역 후보 |
| `radius_stage` | 1km / 10km / area(넓은 지명, 확장 없음) / viewport(지도) |
| `n_relevant_first`, `n_relevant_final` | 관련 가게 수(확장 판단 근거) |
| `message` | none / expanded_none_in_first / expanded_partial / no_result / area_empty / map_empty / no_exact_name / weak_result / map_moved / zoom_in / chip_empty (+ 작은 줄 region_info / default_location)(정책 8-3) |
| `fallback` | 임베딩 장애로 BM25 + 상호 일치만 썼는지 |
| `expansion_cache_hit` | 확장어 캐시 적중 |
| `latency_ms` | 단계별 지연 |

## 3. 노출 결과 (search_result)

사용자가 본 페이지까지 **가게 하나를 한 행으로** 저장한다(JSON 묶음 아님) — 첫 페이지 1~20위, 다음 페이지를 보면 같은 `query_id`로 21~40위를 더한다: `query_id`, `store_id`, `position`(1부터, 절대 순위), `distance_m`(**검색 중심 기준**, 정렬·반경과 같은 기준), `score`.
위치 편향 보정·임계값 재조정에는 노출 순위가 꼭 있어야 한다(Joachims et al., WSDM 2017).

## 4. 행동 이벤트 (모두 `query_id` 포함)

| 이벤트 | 필드·뜻 |
|---|---|
| `impression` | 본 가게 목록 — 카드 면적 50% 이상이 1초 이상 보였을 때 |
| `click` | store_id, position, distance_m |
| `action` | store_id, position, call / directions / favorite / share / pay — 전환 |
| `dwell` | store_id, 상세 체류 초 |
| `region_choice` | 고른 다른 지역(지역 해석이 틀렸다는 신호) |
| `chip_change`, `research_here` | 업종·결제 칩 변경 / '현 지도 재검색' — 새 query_id |
| `cluster_click`, `pin_click` | 지도 묶음 / 핀 |
| `reformulate` | 30초 안 같은 세션 재검색(이전 → 새 query_id) |
| `abandon` | 아무 행동 없이 종료 |

## 5. 봇 의심·보관·통계

- **봇 의심**: 지우지 않고 표시만 하고 통계에서 뺀다. 기본 규칙(세션 기준, IP는 저장하지 않음) — 알려진 봇 User-Agent, 한 세션 1분 30회 초과 검색, 한 세션 하루 200회 이상이면서 클릭 없음.
  규칙과 기준값은 설정으로 바꿀 수 있게(출시 뒤 조정).
- **보관**: 원본(검색·노출·행동) **1년**, 월 단위로 통째로 삭제. 삭제 전에 **일별 통계 요약**을 만들어 계속 보관. 기간은 법무 결과로 바뀔 수 있다.
- **관리자 통계**: 인기 검색어, 결과 없음 비율, 확장 비율, 재검색 비율, 첫 클릭 순위, 클릭률, 의도별 지표, 확장어 캐시 적중률, 폴백 비율.
  봇 의심과 폴백 검색은 품질 지표에서 뺀다.

## 6. 개인위치정보

- 위치는 100m 격자로만 저장하고 원 좌표는 요청 처리에만 쓴다. 정밀도·보관 기간은 설정값(법무 확인 중 — 위치기반서비스 신고·동의 여부).
- 격자 위치와 회원 ID가 같은 행에 있지 않게 하는 것이 재식별 위험을 줄이는 핵심이다(1절).

출처: OpenSearch UBI 스키마 https://docs.opensearch.org/docs/search-plugins/ubi/schemas ·
Algolia Insights https://www.algolia.com/doc/libraries/search-insights/clicked-object-ids-after-search.md
