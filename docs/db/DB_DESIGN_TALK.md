# DB 설계 설명 스크립트 (10~15분)

> 기준: `docs/DB_DESIGN.md` v0.3(테이블 19개) · `docs/db/schema.sql` · ERDCloud 그림은 `docs/db/erdcloud.sql`
> 사용법: **본문(1~8)** 은 소리 내어 읽는 원고예요(약 11분). `[화면]`은 그때 띄울 곳, `[시간]`은 누적 시간이에요.
> **부록 A**는 모든 컬럼의 역할표예요. 읽지 말고 질문이 나오면 찾아보는 용도예요.

---

## 1. 시작 — 한 문장 요약 `[0:00 ~ 1:00]`

`[화면] ERDCloud 전체 그림`

안녕하세요. 가맹점 검색 서비스 DB 설계를 설명드릴게요.

한 문장으로 말하면 이래요.
**"원천 엑셀 값과 관리자가 고친 값을 따로 두고, 둘을 합친 값으로 매주 검색용 사본을 새로 만들어서 한 번에 갈아끼운다."**

테이블은 **19개**예요. 처음에는 36개였는데 꼭 필요한 것만 남겼어요. 다섯 묶음이에요.
가맹점·갱신 5개, 참조 사전 6개, 회원 4개, 관리자 1개, 로그·통계 3개예요.

그림 보는 법을 먼저 말씀드릴게요.
- **PK(기본 키)** 는 그 행을 하나로 집어내는 번호예요.
- **FK(외래 키)** 는 "이 값은 저 테이블에 꼭 있어야 한다"는 연결선이에요. 예를 들어 즐겨찾기의 가게 번호는 가맹점 테이블에 있는 가게여야 해요.
- 선이 없이 떠 있는 테이블은 참조 사전과 로그예요. 로그는 일부러 연결을 끊었어요. 이유는 뒤에서 말씀드릴게요.

---

## 2. 핵심 결정 세 가지 `[1:00 ~ 2:30]`

**첫째, 검색용 데이터는 버전마다 통째로 하나씩 만들어요.**
매주 원천 파일이 오면 검색용 표를 새로 다 만든 다음에 한 번에 바꿔요. 그래서 갱신하는 도중에도 검색은 지난주 데이터를 멀쩡히 보고, 검색 한 건이 두 버전을 섞어 보는 일이 없어요.

**둘째, 원천 값과 관리자가 고친 값을 나눴어요.**
원천 파일이 매주 덮어써도 관리자가 고친 값은 안 지워져요. 원천이 바뀌면 "고친 필드의 원천 값이 바뀌었어요"라고 알려 줄 수 있어요.

**셋째, 로그는 검색 로그 하나를 중심으로, 한 달 단위로 쌓아요.**
검색 한 번에 한 줄이고, 1년 지나면 달째로 지워요. 쓰기를 가볍게 하려고 연결선(외래 키)은 안 걸었어요.

---

## 3. 가맹점과 주간 갱신 `[2:30 ~ 6:30]`

`[화면] store, store_override, store_snapshot, data_version, refresh_job`

실제 가게 하나로 따라가 볼게요. 천안의 **"피양옥 신불당점"** 이에요.

### `store` — 가게 한 곳 = 한 줄

여기에 가게의 **원천 값**과 **지금 상태**가 같이 있어요.

- `store_id`: 가게 고유 번호예요. **평가 정답 데이터가 이 번호로 연결돼 있어서 이미 발급된 번호는 절대 안 바꿔요.**
- `fingerprint`(지문): 사업자번호 + 가맹점명 + 주소를 합친 값이에요. 다음 주 파일이 왔을 때 "이 줄이 지난주 그 가게인가?"를 이걸로 판단해요. 그래서 상호나 주소가 바뀌면 새 가게가 돼요.
- 가맹점명, 사업자번호, 주소, 위도·경도, 법정동코드, 취급품목, 카드결제·모바일결제: 원천 엑셀 값 그대로예요. **사업자번호·법정동코드는 문자열이에요.** 숫자로 저장하면 앞자리 0이 사라지거든요.
- `source_conflict`: 같은 가게가 원천에 여러 줄로 나왔는데 값이 서로 다를 때 켜는 표시예요.
- `lifecycle_status`: 영업중 / 확인 대기 / 폐업이에요.
- `missing_count`: **원천 파일에 연속으로 안 나온 주 수**예요. 한 번 빠지면 "확인 대기"가 되면서 바로 검색에서 빠지고, 다음 주에 돌아오면 다시 영업중이에요. 2주 연속 빠지면 폐업이에요.
- `is_hidden`, `hidden_reason`: 관리자가 숨긴 가게예요. 숨기려면 사유를 꼭 적어야 해요.
- `coord_error`: 좌표가 0이거나 국내 밖인 가게예요. 지금 281곳이에요.

**검색에 나오는 가게 = 영업중이고, 숨김이 아니고, 좌표 오류가 아닌 가게**예요.
가게 줄은 **절대 지우지 않아요.** 폐업도 상태만 바꿔요.

### `store_override` — 관리자가 고친 값

관리자는 **필드 하나씩** 고쳐요. 키가 "가게 + 필드 이름"이에요.
- `field_name`: 상호, 품목, 위치, 시장명, 카드결제, QR결제, 업종 중 하나예요.
- `override_value`: 고친 값이에요.
- `source_value_at_edit`: **고칠 당시의 원천 값**이에요. 다음 주 원천이 이것과 다르면 `source_changed`를 켜서 관리자 화면에 알림을 띄워요.
- `reason`, `admin_id`, `updated_at`: 누가 언제 왜 고쳤는지예요.

수정을 해제하면 이 줄을 지우고 원천 값으로 돌아가요. 지난 수정 이력은 따로 남기지 않고, 마지막으로 고친 사람·시각·사유만 남아요.

### 매주 갱신 흐름

1. **`refresh_job`**: 관리자가 엑셀을 올리면 작업 한 건이 생겨요. 파일 이름, 저장 위치, 파일 지문이 여기 들어가요. **같은 파일을 두 번 반영하면 DB가 막아요.** 단계(검사 → 비교 → 승인 대기 → 임베딩 → 전환)와 진행률을 화면에 보여 줘요.
   - 사라지는 가게가 너무 많으면 `needs_approval`이 켜져서 관리자 승인을 기다려요. 잘못된 파일을 막는 안전장치예요.
   - **갱신은 동시에 하나만** 돌아요.
   - 갱신 중에 관리자가 고친 값은 **전환 직전에 새 버전에 다시 적용**해요.
2. **`data_version`**: 데이터 버전이에요. 이름은 `2026-11-16`처럼 한국 날짜예요. **활성 버전은 언제나 딱 하나**예요. 새로 생긴 가게, 바뀐 가게, 폐업한 가게 수도 여기 남아서 관리자 화면에 보여 줘요.
3. **`store_snapshot`**: **검색이 실제로 읽는 표**예요. 버전마다 칸이 하나씩 있어요.
   - 상호·주소 등은 **원천 값에 관리자 수정을 덮어씌운 최종 값**이에요.
   - `geom`: 좌표예요. 미터 단위 거리를 바로 재는 자료형이라 "1km 안"을 정확하게 골라요.
   - `category_codes`, `payment_codes`: 업종과 결제 수단 목록이에요. **바코드 데이터가 오면 열을 늘리지 않고 목록에 값만 추가**하면 돼요.
   - `searchable`: 검색 대상 여부를 미리 계산해 둔 값이에요.
   - `embedding`: 1024개 숫자로 된 의미 벡터예요. 21만 곳이면 약 0.9GB예요.

**전환은 이렇게 해요.** 새 칸을 다 채운 다음, 칸을 붙이고 활성 버전을 바꾸는 걸 한 번에 해요. 지난 버전은 하나만 남기고 그보다 오래된 칸은 통째로 지워요.

---

## 4. 참조 사전 `[6:30 ~ 7:45]`

`[화면] category ~ expansion_cache`

검색 서버가 메모리에 올려 두고 쓰는 사전들이에요.

- **`category`**: 업종 17개예요.
- **`payment_method`**: 결제 칩이에요. 카드결제, QR결제, 바코드결제예요. 바코드는 데이터가 아직 없어서 화면에 숨겨 뒀어요.
- **`brand_alias`**: 브랜드 별칭이에요. 대표 이름 "GS25" 옆에 "지에스25" 같은 다른 표기를 한 줄씩 적어요.
- **`gazetteer`**: 지명 사전이에요. "신촌", "대전광역시 중구" 같은 이름과 중심 좌표, 지역 전체인지 한 지점인지가 있어요. "신촌 국밥"을 검색하면 여기서 신촌을 찾아요.
- **`place_exclusion`**: "오케이 정형외과"의 "오케이"처럼 지명으로 읽으면 안 되는 말이에요.
- **`expansion_cache`**: "고기"를 검색하면 "삼겹살, 갈비, 정육"처럼 넓혀 찾을 말이에요.

사전마다 `updated_at`(마지막 수정 시각)이 있어요. **검색 서버는 1분마다 이걸 확인해서 바뀐 사전만 다시 읽어요.** 그래서 고친 내용이 1분 안에 반영돼요.

---

## 5. 회원 `[7:45 ~ 9:00]`

`[화면] member 주변`

회원은 **카카오·구글 소셜 로그인만** 쓰고, 개인정보는 최소한만 둬요.

- **`member`**: 닉네임(중복 허용), 이메일(동의한 경우만), 동의한 약관 버전과 동의 시각, 가입 시각이에요.
- **`member_auth`**: 로그인 수단이에요. 한 사람이 카카오와 구글을 둘 다 연결할 수 있어서 따로 뒀어요.
- **`member_recent_search`**: 최근 검색어 10개예요. **좌표나 검색 번호는 넣지 않아요.** 분석 로그와 회원이 이어지지 않게 하려고요.
- **`member_favorite`**: 즐겨찾기 500곳까지예요. 버튼을 두 번 눌러도 한 번만 들어가요. 가게가 폐업하거나 숨겨지면 지워져요.

**탈퇴는 줄을 지우지 않고 상태로 관리해요.** `status`를 "탈퇴"로 바꾸고 `withdrawn_at`에 탈퇴 시각을 적어요.
대신 **닉네임·이메일은 그 자리에서 비우고**, 로그인 수단·최근 검색어·즐겨찾기는 바로 지워요. 남는 건 회원 번호와 시각뿐이라 누구였는지 알 수 없어요.

---

## 6. 관리자 `[9:00 ~ 9:20]`

- **`admin_user`**: 관리자 계정이에요. 권한은 한 단계예요. 비밀번호는 해시로만 두고, 로그인을 여러 번 틀리면 잠깐 잠가요.
- 관리자 접속 기록은 따로 남기지 않기로 했어요.

---

## 7. 로그와 통계 — 검색 로그가 중심 `[9:20 ~ 11:00]`

`[화면] search_log, event_log, stats_daily`

검색 품질을 보려고 남기는 기록이에요. **회원 ID는 넣지 않고, 세션 번호와 100m 칸 위치만** 남겨요.

### `search_log` — 검색 한 번 = 한 줄

검색 결과 한 페이지를 보여 줄 때마다 한 줄씩 남겨요.
- `query_id`: 검색 한 건의 번호예요. 다음 페이지를 봐도 같은 번호이고 `page`만 달라요.
- `query_text`, `input_type`: 무엇을 어떻게 입력했는지예요(직접 입력, 최근 검색어, 칩, 지명만 입력 등).
- `location_source`, `radius_stage`: 검색 중심을 어디로 잡았는지, 1km에서 끝났는지 10km로 넓혔는지예요.
- `n_relevant_first`, `n_relevant_final`, `message`: 처음 범위와 최종 관련 결과가 몇 개였고 어떤 안내 문구를 띄웠는지예요.
- **`results`: 그때 보여 준 가게 목록이에요.** 가게마다 순위, 거리, 점수가 들어 있어요. "이 검색에서 3등에 뭐가 나왔지?"를 이 한 줄로 볼 수 있어요.
- `corpus_version_id`, `pipeline_version`: 어느 데이터 버전·정책으로 검색했는지예요. 나중에 결과를 다시 따져 볼 때 꼭 필요해요.
- `is_bot`, `is_fallback`: 봇이나 임베딩 서버 장애 때 검색은 통계에서 빼려고 표시해요.

### `event_log` — 사용자 행동

클릭, 전화, 길찾기, 머문 시간 같은 행동이에요. `query_id`로 어느 검색에서 나온 행동인지 이어져요. 네트워크 때문에 같은 이벤트가 두 번 오면 통계를 낼 때 한 번만 세요.

로그 두 개는 **한국 시간 기준 한 달마다 칸을 나눠서**, 1년 지난 달은 칸째 지워요.

### `stats_daily` — 하루 요약

날짜 × 화면(목록/지도) × 검색 의도별로 검색 수, 결과 없음, 클릭, 재검색 같은 숫자를 둬요. 관리자 통계 화면은 이걸 읽고, **1년이 지나도 계속 보관해요.** 인기 검색어나 결과 없는 검색어는 필요할 때 검색 로그에서 바로 계산해요.

---

## 8. 마무리 `[11:00 ~ 11:30]`

정리하면 이래요.
1. **원천 값과 수정 값을 나눠서** 매주 덮어써도 관리자 수정이 살아 있어요.
2. **버전마다 검색용 사본을 통째로 만들어 한 번에 바꿔서** 갱신 중에도 검색이 멈추거나 섞이지 않아요.
3. **검색 로그 하나를 중심으로** 가볍게 쌓고 1년 뒤 지워요. 통계 요약은 계속 남겨요.

테이블을 줄이면서 **지난 이력(수정 이력, 상태 이력, 관리자 접속 기록)은 남기지 않기로** 했어요. 지금 값과 마지막으로 바꾼 사람·시각만 남아요. 필요해지면 표만 더하면 돼요.

아직 남은 일은 실제 DB에서 실행해 보고, 시도 전체나 대도시 10km 검색 속도를 재는 거예요. 지금은 문법만 검사했어요.

질문 받겠습니다.

---

## 예상 질문과 답

| 질문 | 답 |
|---|---|
| 가게 정보가 `store`와 `store_snapshot` 두 군데 있는데 중복 아닌가요? | 역할이 달라요. `store`는 매주 원천으로 덮어쓰이는 원본이고, 스냅샷은 수정 값까지 합친 검색용 완성본이에요. 하나로 합치면 갱신하는 동안 검색이 반쯤 바뀐 값을 보게 돼요. |
| 지난 버전을 왜 하나 남기나요? | 전환하는 순간 이미 돌고 있던 검색이 이전 버전을 끝까지 읽어야 하고, 다음 갱신 때 바뀌지 않은 가게의 벡터를 복사해 써요. 되돌리기 기능은 만들지 않아요. |
| 수정 이력이 없으면 누가 바꿨는지 모르지 않나요? | 마지막으로 바꾼 관리자·시각·사유는 남아요. 그 전 값들의 기록만 없어요. 필요해지면 이력 표를 추가하면 돼요. |
| 보여 준 가게를 왜 한 줄에 목록으로 넣었나요? | 가게마다 한 줄씩 쓰면 검색 한 번에 20줄이 생겨요. 한 줄에 목록으로 넣으면 쓰기와 보관이 훨씬 단순하고, 분석할 때는 목록을 펼쳐서 볼 수 있어요. |
| 로그에 외래 키가 없으면 잘못된 값이 들어가지 않나요? | 서버가 자동으로 쓰는 기록이라 잘못 들어갈 일이 적어요. 외래 키가 있으면 쓰기가 느려지고, 달 단위 삭제나 폐업 가게를 가리키는 옛 로그가 꼬여요. |
| 벡터 검색 색인(HNSW)은 왜 안 만드나요? | 먼저 1km·10km·지역으로 범위를 좁히고 그 안에서만 계산해요. 1km 안은 보통 361곳이라 필요 없어요. 가장 큰 경우(시도 전체 약 4.7만 곳)는 실제 DB에서 재 보고 느리면 대안을 써요. |
| 탈퇴한 회원 줄을 남기면 개인정보 보관 아닌가요? | 닉네임·이메일은 비우고 로그인 수단은 지워서, 남는 건 의미 없는 회원 번호와 시각뿐이에요. 누구인지 알아낼 방법이 없어요. |
| 결제 수단이 늘면 열을 추가해야 하나요? | 아니요. `payment_method`에 한 줄 추가하고, 스냅샷의 결제 목록에 값만 넣으면 돼요. |

---

## 부록 A. 모든 컬럼 역할표

> 질문 대응용. 키: PK = 기본 키, FK = 다른 테이블을 가리킴. 자료형은 실제 DB(PostgreSQL) 기준.

### `admin_user` — 관리자

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

### `category` — 업종 · 업종 대분류 17개

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `category_code` | 업종 코드 | varchar(20) | PK | GAS, CONVENIENCE, MEDICAL ... |
| `name` | 이름 | varchar(20) |  | 이름 |
| `sort_order` | 정렬 순서 | smallint |  | 화면에 보여 줄 순서 |
| `is_active` | 사용 여부 | boolean |  | 사용 여부 |
| `updated_at` | 수정 시각 | timestamptz |  | 마지막으로 바꾼 시각 |

### `payment_method` — 결제 수단 · 결제 칩: card, qr, barcode

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `payment_code` | 결제 코드 | varchar(10) | PK | 결제 코드(card, qr, barcode) |
| `name` | 이름 | varchar(20) |  | 카드결제, QR결제, 바코드결제 |
| `source_column` | 원천 열 | varchar(30) |  | store의 원천 열(card_payment, mobile_payment). 데이터 없으면 NULL |
| `sort_order` | 정렬 순서 | smallint |  | 화면에 보여 줄 순서 |
| `is_visible` | 화면 표시 여부 | boolean |  | 바코드는 데이터가 올 때까지 false |
| `updated_at` | 수정 시각 | timestamptz |  | 마지막으로 바꾼 시각 |

### `brand_alias` — 브랜드 별칭 · 브랜드 별칭(대표 이름 1 : 표기 N을 한 표에)

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `alias_id` | 별칭 ID | bigint | PK | 별칭 번호 |
| `canonical_name` | 대표 브랜드명 | varchar(40) |  | 대표 이름(GS25) |
| `alias_text` | 별칭 | varchar(40) |  | 다른 표기(지에스25) |
| `alias_norm` | 정규화 별칭 | varchar(40) |  | 정규화(소문자·공백 제거). 한 표기는 한 브랜드에만 |
| `updated_by` | 수정자 | bigint | FK→admin_user | 마지막으로 바꾼 관리자 |
| `updated_at` | 수정 시각 | timestamptz |  | 마지막으로 바꾼 시각 |

### `gazetteer` — 지명 사전 · 지명 사전(사전을 바꿀 때는 표를 통째로 교체)

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

### `place_exclusion` — 지명 제외어 · 지명으로 읽지 않을 말(오케이 정형외과의 '오케이')

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `term_norm` | 정규화 제외어 | varchar(50) | PK | 비교용으로 정리한 말 |
| `term` | 제외어 | varchar(50) |  | 지명으로 읽지 않을 말(원문) |
| `reason` | 사유 | varchar(200) |  | 사유(필수) |
| `updated_by` | 수정자 | bigint | FK→admin_user | 마지막으로 바꾼 관리자 |
| `updated_at` | 수정 시각 | timestamptz |  | 마지막으로 바꾼 시각 |

### `expansion_cache` — 확장어 캐시 · 업종 검색어 LLM 확장어

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `query_norm` | 정규화 검색어 | varchar(100) | PK | 정규화한 검색어 전체(최대 50자) |
| `keywords` | 확장어 목록 | text[] |  | 고기 → {삼겹살, 갈비, 정육} |
| `model` | 생성 모델 | varchar(60) |  | 만든 LLM |
| `updated_at` | 수정 시각 | timestamptz |  | 마지막으로 바꾼 시각 |

### `data_version` — 데이터 버전

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

### `refresh_job` — 주간 갱신 작업 · 주간 갱신 작업 1건 = 원천 파일 1개

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

### `store` — 가맹점 · 가게 1곳 = 1행: 원천 값 + 현재 상태

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
| `hidden_reason` | 숨김 사유 | varchar(200) |  | 숨긴 사유(숨기면 필수) |
| `hidden_by` | 숨김 처리자 | bigint | FK→admin_user | 숨긴 관리자 |
| `coord_error` | 좌표 오류 | boolean |  | 수정 값까지 반영한 좌표가 0·국내 밖·충돌 |
| `last_seen_version_id` | 마지막 확인 버전 | smallint | FK→data_version | 원천에서 마지막으로 본 버전 |
| `created_at` | 생성 시각 | timestamptz |  | 이 줄을 만든 시각 |
| `updated_at` | 수정 시각 | timestamptz |  | 마지막으로 바꾼 시각 |

### `store_override` — 관리자 수정 값 · 관리자 수정 값(가게 × 필드, 해제하면 행 삭제)

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
| `payment_codes` | 결제 코드 목록 | varchar(10)[] |  | {card, qr}; 바코드는 데이터 오면 값만 추가 |
| `searchable` | 검색 대상 여부 | boolean |  | 영업중 · 숨김 아님 · 좌표 오류 아님 |
| `doc_text` | 임베딩 원문 | varchar(300) |  | 가맹점명: {상호} / 취급품목: {품목} |
| `embedding` | 임베딩 vector(1024) | vector(1024) |  | fp32, L2 정규화 |

### `member` — 회원

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

### `member_auth` — 회원 로그인 수단 · 로그인 수단(회원 1 : N)

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `auth_id` | 로그인 수단 ID | bigint | PK | 로그인 수단 번호 |
| `member_id` | 회원 ID | uuid | FK→member | 회원 번호(탈퇴하면 이 줄은 삭제) |
| `provider` | 로그인 제공자 | varchar(10) |  | 값: kakao, google |
| `provider_user_id` | 제공자 회원 ID | varchar(255) |  | 카카오·구글이 준 회원 번호 |
| `created_at` | 생성 시각 | timestamptz |  | 이 줄을 만든 시각 |

### `member_recent_search` — 최근 검색어 · 최근 검색어(회원당 10개, 좌표·query_id 없음)

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `member_id` | 회원 ID | uuid | PK FK→member | 회원 번호(탈퇴하면 이 줄은 삭제) |
| `query_norm` | 정규화 검색어 | varchar(100) | PK | 같은 말은 한 줄(다시 검색하면 시각만 갱신) |
| `query_text` | 검색어 | varchar(50) |  | 마지막 원문 |
| `searched_at` | 검색 시각 | timestamptz |  | 마지막으로 검색한 시각(정렬 기준) |

### `member_favorite` — 즐겨찾기 · 즐겨찾기(회원당 500곳)

| 컬럼 | 이름 | 자료형 | 키 | 역할 |
|---|---|---|---|---|
| `member_id` | 회원 ID | uuid | PK FK→member | 회원 번호(탈퇴하면 이 줄은 삭제) |
| `store_id` | 가맹점 ID | uuid | PK FK→store | 가게 고유 번호(평가 데이터와 같은 UUID) |
| `created_at` | 생성 시각 | timestamptz |  | 이 줄을 만든 시각 |

### `search_log` — 검색 로그 · 중심 로그: 검색 결과 한 페이지 = 1행

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

### `event_log` — 행동 이벤트 로그 · 행동 이벤트(노출·클릭·전화·길찾기 등)

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
