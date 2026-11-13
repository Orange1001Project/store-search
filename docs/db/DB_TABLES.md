# DB 테이블 설명서

> 기준: `docs/DB_DESIGN.md` v0.3.2(테이블 19개) · 실행 SQL `docs/db/schema.sql` · ERDCloud 그림 `docs/db/erdcloud.sql`
> 각 테이블의 역할·주요 규칙과 모든 컬럼의 역할을 적는다. 컬럼표는 `schema.sql`에서 자동으로 만들었다(둘이 다르면 SQL이 맞다).
> 왜 이렇게 설계했는지(관계·키·줄인 테이블)는 [`DB_DESIGN_WHY.md`](DB_DESIGN_WHY.md).
> 표기: **PK** = 기본 키(행 하나를 집어내는 값), **FK** = 다른 테이블에 꼭 있어야 하는 값(연결선). 자료형은 PostgreSQL 기준.

## 1. 한눈에 보기

| 묶음 | 테이블 | 한 줄 설명 | 주요 연결 |
|---|---|---|---|
| 가맹점·갱신 | `store` | 가게 1곳 = 1행. 원천 값 + 현재 상태 | `store_override`, `member_favorite`이 가리킴 |
| | `store_override` | 관리자가 고친 값(가게 × 필드) | → `store`, `admin_user` |
| | `store_snapshot` | **검색이 읽는 표.** 버전 × 가게의 최종 값 + 벡터 | 버전별 파티션(FK 없음) |
| | `data_version` | 데이터 버전. 활성은 언제나 하나 | `store_snapshot`, `refresh_job`이 가리킴 |
| | `refresh_job` | 주간 갱신 작업 1건 = 원천 파일 1개 | → `data_version`, `admin_user` |
| 참조 사전 | `category` | 업종 대분류 17개 | |
| | `payment_method` | 결제 칩(카드결제·QR결제) | |
| | `brand_alias` | 브랜드 대표 이름과 다른 표기 | |
| | `gazetteer` | 지명 사전 | |
| | `place_exclusion` | 지명으로 읽지 않을 말 | |
| | `expansion_cache` | 업종 검색어 확장어 | |
| 회원 | `member` | 회원 1명 = 1행. 탈퇴도 행을 남김 | `member_auth`, `member_recent_search`, `member_favorite`이 가리킴 |
| | `member_auth` | 로그인 수단(카카오·구글) | → `member` |
| | `member_recent_search` | 최근 검색어 10개 | → `member` |
| | `member_favorite` | 관심 가맹점 500곳 | → `member`, `store` |
| 관리자 | `admin_user` | 관리자 계정 | 수정·갱신·숨김 기록이 가리킴 |
| 로그·통계 | `search_log` | **중심 로그.** 검색 결과 한 페이지 = 1행 | 월별 파티션(FK 없음) |
| | `event_log` | 사용자 행동(클릭·길찾기 등) | 월별 파티션(FK 없음) |
| | `stats_daily` | 하루 요약 숫자 | |

## 2. 설계 원칙

1. **검색용 데이터는 버전마다 통째로 만든다.** 매주 원천 파일이 오면 `store_snapshot`의 새 파티션을 다 채운 뒤 한 번에 바꾼다. 갱신 중에도 검색은 지난 버전을 보고, 검색 한 건이 두 버전을 섞어 보지 않는다.
2. **원천 값과 관리자 수정 값을 나눈다.** 원천은 `store`에 매주 덮어쓰고, 관리자가 고친 값은 `store_override`에 따로 둔다. 원천이 바뀌어도 수정 값은 남고, 고친 필드의 원천이 바뀌면 표시가 켜진다.
3. **로그는 검색 로그 하나를 중심으로 월 단위로 쌓는다.** 한국 시간 기준 한 달마다 파티션을 나누고 1년 지난 달은 파티션째 지운다. 쓰기를 가볍게 하려고 FK를 걸지 않는다.
4. **지난 이력은 남기지 않는다.** 수정 이력, 상태 이력, 관리자 접속 기록 표는 없다. 지금 값과 마지막으로 바꾼 사람·시각·사유만 남는다. 필요해지면 표를 더한다.
5. **행을 지우지 않는 표**: `store`(폐업도 상태만 바꿈), `member`(탈퇴도 상태만 바꾸고 개인정보는 비움), `admin_user`(비활성화).

## 3. 가맹점·갱신

### `store` — 가맹점

가게 한 곳이 한 행이다. 원천 엑셀 값과 지금 상태가 같이 있다. 예: 천안의 "피양옥 신불당점".

- `store_id`는 이미 발급한 번호를 바꾸지 않는다. 평가 정답 데이터가 이 번호로 연결되어 있다. 새 가게만 새로 발급한다.
- `fingerprint`(지문) = 사업자번호 + 가맹점명 + 주소(원천 값). 다음 주 파일의 행이 지난주 그 가게인지 이것으로 판단한다. 그래서 상호나 주소가 바뀌면 새 가게가 된다.
- 사업자번호·가맹점번호·법정동코드는 **문자열**이다. 숫자로 두면 앞자리 0이 사라진다.
- 상태(`lifecycle_status`): 원천에서 한 번 빠지면 확인 대기(`missing_count` = 1, 바로 검색에서 빠짐), 다음 주에 돌아오면 영업중, 2주 연속 빠지면 폐업.
- 숨김: 숨길 때도 풀 때도 사유가 필수다. 마지막 숨김·해제의 사유·관리자·시각을 남긴다(`ck_store_visibility`).
- **검색 대상** = 영업중 · 숨김 아님 · 좌표 오류 아님. 이 값은 스냅샷의 `searchable`로 미리 계산해 둔다.

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `store_id` | 가맹점 ID | uuid | PK | 기존 UUID 유지(평가 정답과 연결), 새 가게만 gen_random_uuid() |
| `fingerprint` | 지문 | char(64) |  | sha256(사업자번호+가맹점명+주소), 원천 값으로 |
| `store_name` | 가맹점명 | varchar(100) |  | 가맹점명(원천 값) |
| `business_no` | 사업자번호 | varchar(20) |  | 문자열(앞자리 0) |
| `merchant_no` | 가맹점번호 | varchar(20) |  | 결측·전화번호 형태 섞임, 식별자로 안 씀 |
| `address` | 주소 | varchar(200) |  | 주소 |
| `latitude` | 위도 | numeric(9, 6) |  | 원천 그대로(0 좌표 포함) |
| `longitude` | 경도 | numeric(9, 6) |  | 경도 |
| `legal_dong_code` | 법정동코드 | varchar(10) |  | 문자열 |
| `market_type` | 시장 분류 | varchar(30) |  | 시장 분류(골목형상점가 등) |
| `market_name` | 시장명 | varchar(100) |  | 시장·상점가 이름 |
| `items` | 취급품목 | text |  | 취급품목 |
| `card_payment` | 카드결제 여부 | boolean |  | 원천 카드결제여부, 빈 값 NULL |
| `mobile_payment` | 모바일결제 여부 | boolean |  | 원천 모바일결제여부(화면 이름 QR결제) |
| `source_conflict` | 원천 충돌 | boolean |  | 같은 가게 원천 행끼리 좌표·품목·결제가 다름(결제는 하나라도 Y면 Y) |
| `lifecycle_status` | 영업 상태 | varchar(10) |  | 값: active, pending, closed |
| `missing_count` | 연속 누락 주 수 | smallint |  | 연속으로 원천에 없던 주 수 |
| `status_changed_at` | 상태 변경 시각 | timestamptz |  | 상태가 마지막으로 바뀐 시각 |
| `is_hidden` | 숨김 여부 | boolean |  | 관리자 숨김 여부 |
| `visibility_reason` | 숨김·해제 사유 | varchar(200) |  | 마지막 숨김·해제 사유(둘 다 필수, FR-STO-07) |
| `visibility_changed_by` | 숨김·해제 처리자 | bigint | FK→admin_user | 마지막으로 숨기거나 해제한 관리자 |
| `visibility_changed_at` | 숨김·해제 시각 | timestamptz |  | 마지막으로 숨기거나 해제한 시각. 한 번도 안 바꿨으면 NULL |
| `coord_error` | 좌표 오류 | boolean |  | 수정 값까지 반영한 좌표가 0·국내 밖·충돌 |
| `last_seen_version_id` | 마지막 확인 버전 | smallint | FK→data_version | 원천에서 마지막으로 본 버전 |
| `created_at` | 생성 시각 | timestamptz |  | 이 줄을 만든 시각 |
| `updated_at` | 수정 시각 | timestamptz |  | 마지막으로 바꾼 시각 |

### `store_override` — 관리자 수정 값

관리자는 필드 하나씩 고친다. 키는 가게 + 필드 이름이다.

- 고칠 수 있는 필드: 상호, 취급품목, 위치(주소·좌표·법정동코드), 시장명, 카드결제, QR결제, 업종. 1차에는 위치를 화면이 아니라 DB에서 직접 넣는다.
- `source_value_at_edit`(고칠 때의 원천 값)과 다음 주 원천 값이 다르면 `source_changed`를 켜고 `new_source_value`에 바뀐 값을 둔다. 1차에는 화면 없이 DB에서 확인한다.
- 수정을 해제하면 행을 지우고 원천 값으로 돌아간다.
- 갱신 중에 고친 값은 전환 직전에 새 버전에도 다시 적용한다(`refresh_job.edits_applied_until`).

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `store_id` | 가맹점 ID | uuid | PK FK→store | 가게 고유 번호(평가 데이터와 같은 UUID) |
| `field_name` | 필드명 | varchar(20) | PK | 수정 대상 필드 · 값: store_name, items, location, market_name, payment_card, payment_qr, category |
| `override_value` | 수정 값 | jsonb |  | location = {lat, lon, legal_dong_code, address} |
| `source_value_at_edit` | 수정 당시 원천 값 | jsonb |  | 수정할 때의 원천 값 |
| `source_changed` | 원천 바뀜 | boolean |  | 그 뒤 원천 값이 바뀜 → 관리자 화면에 알림(FR-STO-08) |
| `new_source_value` | 새 원천 값 | jsonb |  | 바뀐 원천 값 |
| `reason` | 사유 | varchar(200) |  | 사유(필수) |
| `admin_id` | 관리자 ID | bigint | FK→admin_user | 처리한 관리자 |
| `updated_at` | 수정 시각 | timestamptz |  | 마지막으로 바꾼 시각 |

### `store_snapshot` — 검색 스냅샷(버전별)

검색이 실제로 읽는 표다. 데이터 버전마다 파티션이 하나씩 있다.

- 상호·주소 등은 원천 값에 관리자 수정을 덮어씌운 **최종 값**이다.
- `geom`은 미터 단위 거리를 바로 재는 좌표 자료형이라 "1km 안"을 정확하게 고른다.
- 업종·결제는 목록(`category_codes`, `payment_codes`)이라 값이 늘어도 열을 늘리지 않는다.
- `embedding`은 1024개 숫자로 된 의미 벡터다. 21만 곳이면 약 0.9GB.
- 벡터 근사 색인(HNSW)은 두지 않는다. 범위(1km·10km·지역)로 먼저 좁히고 그 안에서 정확히 계산한다.
- 전환: 새 파티션을 다 채운 뒤 붙이기·활성 버전 바꾸기를 한 트랜잭션으로 한다. 직전 버전 하나만 남기고 더 오래된 파티션은 지운다(이미 돌던 검색이 끝까지 읽고, 다음 갱신 때 바뀌지 않은 가게의 벡터를 복사해 쓰려고).

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `version_id` | 데이터 버전 ID | smallint | PK | data_version.version_id |
| `store_id` | 가맹점 ID | uuid | PK | store.store_id |
| `store_name` | 가맹점명 | varchar(100) |  | 원천 + 관리자 수정 = 유효 값 |
| `items` | 취급품목 | text |  | 취급품목 |
| `address` | 주소 | varchar(200) |  | 주소 |
| `address_short` | 짧은 주소 | varchar(100) |  | 시군구 + 도로명(결과 카드) |
| `legal_dong_code` | 법정동코드 | varchar(10) |  | 법정동코드(문자열 10자리) |
| `market_type` | 시장 분류 | varchar(30) |  | 시장유형(결과 카드·상세, FR-LST-03) |
| `market_name` | 시장명 | varchar(100) |  | 시장·상점가 이름 |
| `geom` | 좌표(geography) | geography(point, 4326) |  | 좌표(미터 단위 거리 계산용) |
| `category_codes` | 업종 코드 목록 | varchar(20)[] |  | 여러 업종 가능 |
| `primary_category` | 대표 업종 | varchar(20) |  | 대표 업종(category.category_code) |
| `category_source` | 업종 근거 | varchar(10) |  | 업종 근거(DR-07) · 값: item, name, none, admin |
| `subcategory` | 세부 업종 | varchar(40) |  | 세부 업종 |
| `payment_codes` | 결제 코드 목록 | varchar(10)[] |  | {card, qr} |
| `searchable` | 검색 대상 여부 | boolean |  | 영업중 · 숨김 아님 · 좌표 오류 아님 |
| `doc_text` | 임베딩 원문 | varchar(300) |  | 가맹점명: {상호} / 취급품목: {품목} |
| `embedding` | 임베딩 vector(1024) | vector(1024) |  | fp32, L2 정규화 |

### `data_version` — 데이터 버전

- 이름은 한국 날짜(`2026-11-16`). 같은 날 두 번째는 `2026-11-16.2`.
- 활성 버전은 언제나 하나(부분 유일 색인).
- 버전마다 전체·신규·변경·확인 대기·폐업·좌표 오류 건수를 남긴다.

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `version_id` | 데이터 버전 ID | smallint | PK | 데이터 버전 번호 |
| `version_name` | 버전 이름 | varchar(20) |  | 2026-11-16, 같은 날 두 번째는 2026-11-16.2 (한국 날짜) |
| `status` | 상태 | varchar(10) |  | 상태값 · 값: building, active, retired, failed |
| `embedding_model` | 임베딩 모델 | varchar(60) |  | bge_m3_ft_mj_20261014_0743 |
| `n_total` | 전체 가게 수 | integer |  | 이번 버전 결과(관리자 화면 표시) |
| `n_new` | 신규 가게 수 | integer |  | 새로 생긴 가게 수 |
| `n_changed` | 변경 가게 수 | integer |  | 값이 바뀐 가게 수 |
| `n_pending` | 확인 대기 수 | integer |  | 이번에 확인 대기가 된 수 |
| `n_closed` | 폐업 가게 수 | integer |  | 이번에 폐업 처리된 가게 수 |
| `n_coord_error` | 좌표 오류 수 | integer |  | 좌표 오류 가게 수 |
| `created_at` | 생성 시각 | timestamptz |  | 이 줄을 만든 시각 |
| `activated_at` | 활성화 시각 | timestamptz |  | 활성 버전이 된 시각 |

### `refresh_job` — 주간 갱신 작업

원천 파일 하나로 도는 갱신 한 건이다. 1차에는 운영자가 서버에서 갱신 스크립트로 실행하고, 진행 상태를 이 표에 남긴다.

- 파일 본문은 DB에 두지 않고 저장 위치(`file_path`)와 지문(`file_sha256`)만 둔다. 이미 반영한 파일을 다시 넣으면 DB가 막는다.
- 단계: 올림 → 검사 → 차이 계산 → (승인 대기) → 임베딩 → 전환 → 완료 / 실패 / 취소.
- 사라지는 가게가 기준(3%)을 넘으면 `needs_approval`이 켜지고 승인을 기다린다.
- 진행 중인 작업은 언제나 하나뿐이다(부분 유일 색인).

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `job_id` | 작업 ID | bigint | PK | 작업 번호 |
| `file_name` | 파일 이름 | varchar(200) |  | 올린 엑셀 이름 |
| `file_path` | 파일 위치 | varchar(500) |  | 파일 저장소 위치(파일 본문은 DB에 두지 않음) |
| `file_sha256` | 파일 지문 | char(64) |  | 파일 지문 |
| `file_size` | 파일 크기 | bigint |  | 100MB 이하 |
| `target_version_id` | 대상 버전 ID | smallint | FK→data_version | 이 작업이 만드는 버전 |
| `status` | 상태 | varchar(20) |  | 상태값 · 값: uploaded, validating, diffing, awaiting_approval, approved, embedding, switching, succeeded, failed, cancelled |
| `progress_pct` | 진행률(%) | smallint |  | 진행률 0~100(화면 표시) |
| `needs_approval` | 승인 필요 | boolean |  | 사라지는 가게가 기준 %를 넘음(FR-UPD-05) |
| `preview` | 미리보기 요약 | jsonb |  | 건수, 좌표 오류·충돌 목록 |
| `error_message` | 오류 메시지 | text |  | 실패 이유 |
| `edits_applied_until` | 수정 재적용 기준 시각 | timestamptz |  | 이 시각까지의 관리자 수정을 새 버전에 반영함(FR-UPD-07) |
| `started_by` | 실행자 | bigint | FK→admin_user | 실행한 관리자 |
| `approved_by` | 승인자 | bigint | FK→admin_user | 승인한 관리자 |
| `created_at` | 생성 시각 | timestamptz |  | 이 줄을 만든 시각 |
| `finished_at` | 종료 시각 | timestamptz |  | 끝난 시각 |

## 4. 참조 사전

검색 서버가 메모리에 올려 두고 쓰는 사전이다. 표마다 `updated_at`이 있고, 검색 서버는 1분마다 이것을 확인해 바뀐 사전만 다시 읽는다. 그래서 DB에서 고친 내용이 1분 안에 검색에 반영된다.

### `category` — 업종

업종 칩 17개다. 결과를 거르기만 하고 순위에는 쓰지 않는다.

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `category_code` | 업종 코드 | varchar(20) | PK | GAS, CONVENIENCE, MEDICAL ... |
| `name` | 이름 | varchar(20) |  | 이름 |
| `sort_order` | 정렬 순서 | smallint |  | 화면에 보여 줄 순서 |
| `is_active` | 사용 여부 | boolean |  | 사용 여부 |
| `updated_at` | 수정 시각 | timestamptz |  | 마지막으로 바꾼 시각 |

### `payment_method` — 결제 수단

결제 칩이다. 카드결제(원천 카드결제 열), QR결제(원천 QR결제 열) 두 가지.

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `payment_code` | 결제 코드 | varchar(10) | PK | 결제 코드(card, qr) |
| `name` | 이름 | varchar(20) |  | 카드결제, QR결제 |
| `source_column` | 원천 열 | varchar(30) |  | store의 원천 열(card_payment, mobile_payment). 데이터 없으면 NULL |
| `sort_order` | 정렬 순서 | smallint |  | 화면에 보여 줄 순서 |
| `is_visible` | 화면 표시 여부 | boolean |  | 칩 표시 여부 |
| `updated_at` | 수정 시각 | timestamptz |  | 마지막으로 바꾼 시각 |

### `brand_alias` — 브랜드 별칭

대표 이름 하나에 다른 표기를 한 행씩 둔다. 예: "GS25" ↔ "지에스25". 1차에는 DB에서 직접 넣고 지운다.

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `alias_id` | 별칭 ID | bigint | PK | 별칭 번호 |
| `canonical_name` | 대표 브랜드명 | varchar(40) |  | 대표 이름(GS25) |
| `alias_text` | 별칭 | varchar(40) |  | 다른 표기(지에스25) |
| `alias_norm` | 정규화 별칭 | varchar(40) |  | 정규화(소문자·공백 제거). 한 표기는 한 브랜드에만 |
| `updated_by` | 수정자 | bigint | FK→admin_user | 마지막으로 바꾼 관리자 |
| `updated_at` | 수정 시각 | timestamptz |  | 마지막으로 바꾼 시각 |

### `gazetteer` — 지명 사전

"신촌", "대전광역시 중구" 같은 이름과 중심 좌표, 넓은 지역(시도·시군구·읍면)인지 좁은 곳(동·역·시장)인지를 둔다. "신촌 국밥"을 검색하면 여기서 신촌을 찾는다. 사전을 바꿀 때는 표를 통째로 교체한다.

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `entry_id` | 항목 ID | bigint | PK | 항목 번호 |
| `name` | 이름 | varchar(50) |  | 신촌, 대전광역시 중구, 구리전통시장 |
| `name_norm` | 정규화 이름 | varchar(50) |  | 비교용으로 정리한 이름 |
| `kind` | 지명 종류 | varchar(10) |  | 값: sido, city, sigungu, eupmyeon, dong, hdong, station, market |
| `scope` | 지명 범위 | varchar(5) |  | area = 지역 전체, point = 1km 원 · 값: area, point |
| `code_prefix` | 법정동 코드 앞자리 | varchar(10) |  | 법정동 코드 앞자리(2·5·8자리), area일 때 |
| `center` | 중심 좌표 | geography(point, 4326) |  | 지명 중심(검색 중심으로 씀) |
| `evidence_count` | 근거 가게 수 | smallint |  | 같은 이름 지명 고르기용(근거 수) |
| `updated_at` | 수정 시각 | timestamptz |  | 마지막으로 바꾼 시각(검색 서버가 1분마다 확인) |

### `place_exclusion` — 지명 제외어

지명으로 읽으면 안 되는 말이다. 예: "오케이 정형외과"의 "오케이". 1차에는 DB에서 직접 넣고 지운다.

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `term_norm` | 정규화 제외어 | varchar(50) | PK | 비교용으로 정리한 말 |
| `term` | 제외어 | varchar(50) |  | 지명으로 읽지 않을 말(원문) |
| `reason` | 사유 | varchar(200) |  | 사유(필수) |
| `updated_by` | 수정자 | bigint | FK→admin_user | 마지막으로 바꾼 관리자 |
| `updated_at` | 수정 시각 | timestamptz |  | 마지막으로 바꾼 시각 |

### `expansion_cache` — 확장어 캐시

업종 검색어를 넓혀 찾을 말이다. 예: "고기" → "삼겹살, 갈비, 정육". 키는 정규화한 전체 검색어이고, 캐시에 없으면 확장 없이 검색한다.

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `query_norm` | 정규화 검색어 | varchar(100) | PK | 정규화한 검색어 전체(최대 50자) |
| `keywords` | 확장어 목록 | text[] |  | 고기 → {삼겹살, 갈비, 정육} |
| `model` | 생성 모델 | varchar(60) |  | 만든 LLM |
| `updated_at` | 수정 시각 | timestamptz |  | 마지막으로 바꾼 시각 |

## 5. 회원

카카오·구글 소셜 로그인만 쓰고 개인정보는 최소로 둔다. 카카오는 닉네임만, 이메일은 구글에서 동의한 경우만 받는다.

### `member` — 회원

- 닉네임은 중복을 허용한다. 없으면 `회원` + 숫자 4자리.
- 동의한 약관 묶음 버전과 동의 시각을 이 행에 둔다(약관 표 없음).
- **탈퇴**: 행을 지우지 않고 `status`를 탈퇴로, `withdrawn_at`에 시각을 적는다. 닉네임·이메일·마지막 로그인은 그 자리에서 비우고(CHECK로 강제), 로그인 수단·최근 검색어·관심 가맹점은 바로 지운다. 남는 것은 회원 번호와 시각뿐이라 누구였는지 알 수 없다.
- 로그인 유지용 갱신 토큰은 DB가 아니라 세션 저장소(Redis)에 둔다.

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `member_id` | 회원 ID | uuid | PK | 회원 번호(탈퇴해도 행은 남음) |
| `status` | 상태 | varchar(10) |  | 회원 / 탈퇴. 탈퇴해도 행은 지우지 않고 개인정보만 비움 · 값: active, withdrawn |
| `nickname` | 닉네임 | varchar(12) |  | 중복 허용, 없으면 '회원1234'. 탈퇴하면 NULL |
| `email` | 이메일 | varchar(254) |  | 선택 동의. 탈퇴하면 NULL |
| `terms_version` | 약관 버전 | varchar(20) |  | 동의한 약관 묶음 버전(이용약관·개인정보·만 14세) |
| `terms_agreed_at` | 약관 동의 시각 | timestamptz |  | 약관 동의 시각(DR-19) |
| `created_at` | 생성 시각 | timestamptz |  | 가입 시각 |
| `last_login_at` | 마지막 로그인 | timestamptz |  | 탈퇴하면 NULL |
| `withdrawn_at` | 탈퇴 시각 | timestamptz |  | 탈퇴 시각 |

### `member_auth` — 회원 로그인 수단

한 회원이 카카오와 구글을 둘 다 연결할 수 있어서 따로 둔다. 제공자 + 제공자 사용자 ID만 저장한다.

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `auth_id` | 로그인 수단 ID | bigint | PK | 로그인 수단 번호 |
| `member_id` | 회원 ID | uuid | FK→member | 회원 번호(탈퇴하면 이 줄은 삭제) |
| `provider` | 로그인 제공자 | varchar(10) |  | 값: kakao, google |
| `provider_user_id` | 제공자 회원 ID | varchar(255) |  | 카카오·구글이 준 회원 번호 |
| `created_at` | 생성 시각 | timestamptz |  | 이 줄을 만든 시각 |

### `member_recent_search` — 최근 검색어

회원당 10개. 좌표와 `query_id`는 넣지 않는다(분석 로그와 회원이 이어지지 않게).

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `member_id` | 회원 ID | uuid | PK FK→member | 회원 번호(탈퇴하면 이 줄은 삭제) |
| `query_norm` | 정규화 검색어 | varchar(100) | PK | 같은 말은 한 줄(다시 검색하면 시각만 갱신) |
| `query_text` | 검색어 | varchar(50) |  | 마지막 원문 |
| `searched_at` | 검색 시각 | timestamptz |  | 마지막으로 검색한 시각(정렬 기준) |

### `member_favorite` — 관심 가맹점

회원당 500곳. 같은 가게를 두 번 넣어도 한 번만 들어간다. 가게가 폐업 확정되거나 숨겨지면 지운다(확인 대기 동안은 남김).

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `member_id` | 회원 ID | uuid | PK FK→member | 회원 번호(탈퇴하면 이 줄은 삭제) |
| `store_id` | 가맹점 ID | uuid | PK FK→store | 가게 고유 번호(평가 데이터와 같은 UUID) |
| `created_at` | 생성 시각 | timestamptz |  | 이 줄을 만든 시각 |

## 6. 관리자

### `admin_user` — 관리자

- 권한은 한 단계. 계정은 지우지 않고 비활성화한다.
- 비밀번호는 bcrypt 해시만 둔다. 5회 연속 틀리면 30분 잠금(`locked_until`). 첫 로그인 때 비밀번호 변경을 강제한다(`must_change_password`).
- 1차에는 계정 생성·비활성화·초기화를 DB·스크립트로 한다.
- 관리자 접속 기록은 남기지 않는다.

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `admin_id` | 관리자 ID | bigint | PK | 관리자 번호(자동 증가) |
| `login_id` | 로그인 ID | varchar(30) |  | 로그인 아이디(중복 불가) |
| `password_hash` | 비밀번호 해시 | varchar(100) |  | bcrypt |
| `status` | 상태 | varchar(10) |  | 상태값 · 값: active, disabled |
| `must_change_password` | 비밀번호 변경 필요 | boolean |  | 첫 로그인 때 비밀번호 변경 |
| `failed_login_count` | 로그인 실패 횟수 | smallint |  | 연속 로그인 실패 횟수(기준을 넘으면 잠금) |
| `locked_until` | 잠금 해제 시각 | timestamptz |  | 실패가 쌓이면 이 시각까지 잠금 |
| `last_login_at` | 마지막 로그인 | timestamptz |  | 마지막 로그인 시각 |
| `created_at` | 생성 시각 | timestamptz |  | 이 줄을 만든 시각 |

## 7. 로그·통계

회원 ID는 넣지 않는다. 세션 번호와 100m 격자 위치만 남긴다. `search_log`·`event_log`는 한국 시간 기준 월별 파티션이고 1년 지난 달은 파티션째 지운다.

### `search_log` — 검색 로그

검색 결과 한 페이지를 보여 줄 때마다 한 행이다. 다음 페이지를 보면 같은 `query_id`에 `page`만 다른 행이 생긴다.

- `results`: 그때 보여 준 가게 목록(가게·순위·검색 중심 거리·점수). "이 검색에서 3위가 무엇이었나"를 이 한 행으로 본다.
- `corpus_version_id`, `pipeline_version`: 어느 데이터 버전·정책으로 검색했는지. 결과를 다시 따져 볼 때 필요하다.
- `is_bot`, `is_fallback`: 봇이나 임베딩 장애 때 검색을 품질 통계에서 빼려고 표시한다.

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `query_id` | 검색 ID | uuid | PK | 검색 1건(다음 페이지도 같은 번호) |
| `page` | 페이지 | smallint | PK | 페이지 번호(다음 페이지도 같은 검색 ID) |
| `logged_at` | 기록 시각 | timestamptz | PK | 서버 시각 |
| `session_id` | 세션 ID | uuid |  | 30분 쉬면 새 세션 |
| `schema_version` | 로그 형식 버전 | smallint |  | 로그 형식 버전 |
| `app_version` | 앱 버전 | varchar(20) |  | 앱 버전 |
| `pipeline_version` | 검색 정책 버전 | varchar(20) |  | 검색 정책·계수 버전 |
| `corpus_version_id` | 데이터 버전 ID | smallint |  | 검색한 데이터 버전(FK 없음) |
| `query_text` | 검색어 | varchar(50) |  | 검색어 없는 조회는 NULL |
| `input_type` | 입력 방식 | varchar(15) |  | 값: typed, recent, autocomplete, chip, browse, place |
| `category_code` | 업종 코드 | varchar(20) |  | 고른 업종 칩 |
| `payment_codes` | 결제 코드 목록 | varchar(10)[] |  | 고른 결제 칩(여러 개, 빈 목록 = 전체) |
| `view` | 화면 종류 | varchar(4) |  | 목록 / 지도 · 값: list, map |
| `location_source` | 검색 중심 출처 | varchar(15) |  | 값: query_region, ui_region, map_viewport, gps, default |
| `user_cell` | 사용자 위치 격자 | varchar(20) |  | 사용자 위치 100m 격자(원 좌표 없음) |
| `viewport_cells` | 지도 화면 격자 | varchar(50) |  | 지도 화면 남서·북동 100m 격자 |
| `parsed` | 해석 결과 | jsonb |  | 해석 결과: 지역·범위·의도·상호 우선 등 |
| `intent` | 검색 의도 | varchar(10) |  | 검색 의도 · 값: name, brand, category |
| `radius_stage` | 범위 단계 | varchar(10) |  | 값: 1km, 10km, area, viewport |
| `n_relevant_first` | 첫 범위 관련 수 | smallint |  | 첫 범위(1km 등)의 관련 결과 수(확장 판단 근거) |
| `n_relevant_final` | 최종 관련 수 | smallint |  | 최종 관련 결과 수 |
| `message` | 안내 문구 | varchar(25) |  | 화면에 띄운 안내 문구 |
| `sub_message` | 보조 문구 | varchar(20) |  | 작은 줄 문구 · 값: region_info, default_location |
| `expansion_cache_hit` | 확장어 캐시 적중 | boolean |  | 업종 의도일 때만 |
| `results` | 보여 준 가게 목록 | jsonb |  | 보여 준 가게: [{store_id, position, distance_m, score}] |
| `latency_ms` | 단계별 지연(ms) | jsonb |  | 단계별 지연(ms) |
| `is_fallback` | 폴백 여부 | boolean |  | 임베딩 서버 장애로 BM25만 씀 |
| `is_bot` | 봇 여부 | boolean |  | 봇으로 판정되면 true(통계 제외) |

### `event_log` — 행동 이벤트 로그

노출·클릭·길찾기·공유 같은 행동이다. `query_id`로 어느 검색에서 나온 행동인지 잇는다. 같은 이벤트가 재전송되면 통계 때 `event_id`로 한 번만 센다.

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `event_id` | 이벤트 ID | uuid | PK | 화면이 만든 번호. 재전송 중복은 통계 때 한 번만 셈 |
| `server_ts` | 서버 시각 | timestamptz | PK | 서버가 받은 시각(월 파티션 기준) |
| `client_ts` | 화면 시각 | timestamptz |  | 화면에서 일어난 시각 |
| `session_id` | 세션 ID | uuid |  | 세션 번호(30분 쉬면 새로 발급, 회원과 무관) |
| `query_id` | 검색 ID | uuid |  | 어느 검색에서 나온 행동인지 |
| `event_type` | 이벤트 종류 | varchar(15) |  | 값: impression, click, action, dwell, region_choice, chip_change, research_here, cluster_click, pin_click, reformulate, abandon |
| `store_id` | 가맹점 ID | uuid |  | 가게 고유 번호(평가 데이터와 같은 UUID) |
| `position` | 순위 | smallint |  | 화면 순위(1부터) |
| `action_type` | 행동 종류 | varchar(10) |  | 값: call, directions, favorite, share, pay |
| `payload` | 추가 정보 | jsonb |  | 본 가게 목록, 머문 초, 고른 지역 등 |
| `is_bot` | 봇 여부 | boolean |  | 봇으로 판정되면 true(통계 제외) |

### `stats_daily` — 일별 통계

날짜 × 화면(목록·지도) × 검색 의도별 검색 수, 결과 없음, 클릭, 재검색 같은 숫자다. 관리자 통계 화면이 이것을 읽고, 1년이 지나도 계속 보관한다. 인기 검색어·결과 없는 검색어는 필요할 때 검색 로그에서 계산한다.

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `stat_date` | 통계 날짜 | date | PK | 한국 시간 날짜 |
| `view` | 화면 종류 | varchar(4) | PK | 목록 / 지도 · 값: list, map, all |
| `intent` | 검색 의도 | varchar(10) | PK | 검색 의도 · 값: name, brand, category, none, all |
| `n_search` | 검색 수 | integer |  | 봇·폴백·browse·place 제외 |
| `n_no_result` | 결과 없음 수 | integer |  | 결과 없음 수 |
| `n_expanded` | 10km 확장 수 | integer |  | 10km로 넓힘 |
| `n_reformulate` | 재검색 수 | integer |  | 바로 다시 검색 |
| `n_search_clicked` | 클릭 있는 검색 수 | integer |  | 클릭이 1번 이상 있었던 검색 |
| `sum_first_click_pos` | 첫 클릭 순위 합 | bigint |  | 평균 첫 클릭 순위 = 합 ÷ n_search_clicked |
| `n_impression` | 노출 수 | bigint |  | 노출 수 |
| `n_click` | 클릭 수 | bigint |  | 클릭 수 |
| `n_cache_lookup` | 캐시 조회 수 | integer |  | 확장어 캐시 조회 |
| `n_cache_hit` | 캐시 적중 수 | integer |  | 확장어 캐시 적중 |
| `n_fallback` | 폴백 수 | integer |  | BM25만 쓴 검색 수(품질 지표와 따로 셈) |
| `n_bot` | 봇 검색 수 | integer |  | 봇 검색 수(따로 셈) |
| `created_at` | 생성 시각 | timestamptz |  | 이 줄을 만든 시각 |

## 8. 자주 묻는 질문

| 질문 | 답 |
|---|---|
| 가게 정보가 `store`와 `store_snapshot` 두 군데 있는데 중복 아닌가? | 역할이 다르다. `store`는 매주 원천으로 덮어쓰는 원본이고, 스냅샷은 수정 값까지 합친 검색용 완성본이다. 하나로 합치면 갱신 중에 검색이 반쯤 바뀐 값을 보게 된다. |
| 지난 버전을 왜 하나 남기나? | 전환하는 순간 이미 돌던 검색이 이전 버전을 끝까지 읽어야 하고, 다음 갱신 때 바뀌지 않은 가게의 벡터를 복사해 쓴다. 되돌리기 기능은 없다. |
| 수정 이력이 없으면 누가 바꿨는지 모르지 않나? | 마지막으로 바꾼 관리자·시각·사유는 남는다. 그 전 값의 기록만 없다. 필요해지면 이력 표를 더한다. |
| 보여 준 가게를 왜 한 행에 목록으로 넣었나? | 가게마다 한 행씩 쓰면 검색 한 번에 20행이 생긴다. 목록으로 넣으면 쓰기와 보관이 단순하고, 분석할 때는 목록을 펼쳐 본다(DB 설계 조회 ⑫). |
| 로그에 FK가 없으면 잘못된 값이 들어가지 않나? | 서버가 자동으로 쓰는 기록이라 잘못 들어갈 일이 적다. FK가 있으면 쓰기가 느려지고, 월 단위 삭제나 폐업 가게를 가리키는 옛 로그가 꼬인다. |
| 벡터 색인(HNSW)은 왜 없나? | 범위로 먼저 좁히고 그 안에서만 계산한다. 1km 안은 보통 361곳이다. 가장 큰 경우(시도 전체 약 4.7만 곳)는 실제 DB에서 재 보고 느리면 대안을 쓴다. |
| 탈퇴 회원 행을 남기면 개인정보 보관 아닌가? | 닉네임·이메일은 비우고 로그인 수단은 지워서, 남는 것은 의미 없는 회원 번호와 시각뿐이다. |
| 결제 수단이 늘면 열을 추가해야 하나? | 아니다. `payment_method`에 한 행 넣고, 스냅샷 결제 목록에 값만 넣는다. |
