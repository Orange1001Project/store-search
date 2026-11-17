# API 공통 규칙 (v0.7)

> 작성 2026-11-13 · 고침 2026-11-16(PR #11 리뷰, 화면 흐름 보완 v0.5, 화면 대응표 검토 v0.6, 위치 동의·오류 화면 v0.7) · 기준: `docs/REQUIREMENTS.md` v0.15(5절 IR, 3절 NFR-SEC·PRV) · 명세: [`openapi.yaml`](openapi.yaml)(OpenAPI 3.1)
> 모든 API에 똑같이 적용한다. 개별 API 명세는 `openapi.yaml`에 쓰고, 이 문서와 다르면 이 문서를 먼저 고친다.

## 1. 결정 요약

| 항목 | 규칙 | 결정 |
|---|---|---|
| 주소 | 사용자 `/api/v1/...`, 관리자 `/api/v1/admin/...`. 형식을 깨는 변경은 `/api/v2` | 2026-11-13 |
| 필드 이름 | JSON은 **camelCase**(`storeId`, `queryId`). DB·로그 문서는 snake_case 그대로, 변환은 백엔드가 한다. 이름이 다른 것: API `centerSource` = 로그 `location_source`, API `bounds` = 로그 `viewport_cells`(격자로 바꿔 저장), API `userLocation` = 로그 `user_cell`(격자). 요구사항 5절 IR 표는 API 이름을 쓴다 | 2026-11-13 |
| 시각 | **KST 오프셋을 붙인 ISO 8601**(`2026-11-13T14:30:00+09:00`). DB 저장은 UTC(NFR-QLT-05) | 2026-11-13 |
| 날짜만 | `2026-11-13`(한국 날짜). 데이터 버전 이름도 같은 형식(`2026-11-13`, 같은 날 두 번째는 `2026-11-13.2`) | |
| 좌표 | `{ "lat": 36.3504, "lng": 127.3845 }`, WGS84. 지도 범위는 `{ "sw": {…}, "ne": {…} }` | |
| 위치 전송 | GPS 원 좌표는 **요청 본문**으로만 보내고 서버는 저장하지 않는다. 로그는 100m 격자. 좌표·세션을 URL에 넣지 않는다(NFR-PRV-02) | 2026-11-13 |
| 다음 페이지 | 사용자 검색·조회는 커서 방식. 응답의 `nextCursor`를 다음 요청에 그대로 보낸다. 없으면 마지막 페이지(FR-LST-01·02). 관리자 표는 페이지 번호 방식(`page`, `size`, 응답 `totalCount`) — 화면에 페이지 번호가 있어서 | |
| 문서 형식 | OpenAPI 3.1 YAML. 백엔드는 springdoc으로 같은 문서를 내보내 대조한다 | 2026-11-13 |

## 2. 요청

- 본문은 `application/json; charset=utf-8`. 파일 올리기(주간 갱신)만 `multipart/form-data`.
- 조회는 `GET`, 만들기·실행 `POST`, 값 하나를 통째로 정하기 `PUT`(필드 수정, 숨김), 일부 바꾸기 `PATCH`, 지우기 `DELETE`. 검색·조회처럼 좌표를 보내야 하는 읽기는 `POST`(좌표를 URL에 넣지 않기 위해).
- 빈 값: 없는 값은 필드를 빼거나 `null`. 목록은 빈 배열 `[]`(예: `paymentCodes: []` = 전체).
- 코드 값은 소문자 영어(`list`, `map`, `qr`, `card`). 화면 글자는 응답에 넣지 않고 코드로 내려 준다(문구는 코드 + 치환값, FR-MSG-02).

## 3. 응답

성공은 데이터를 바로 준다(감싸는 `data` 없음).

```json
{ "queryId": "8c1f…", "results": [ … ], "nextCursor": "MjA", "totalCount": 15 }
```

| 상태 코드 | 쓰는 때 |
|---|---|
| 200 | 조회·처리 성공 |
| 201 | 만들기 성공(관심 가맹점 추가, 가입) |
| 202 | 받아서 나중에 처리(이벤트 수집 IR-05, 갱신 실행) |
| 204 | 본문 없는 성공(삭제, 로그아웃) |
| 400 | 형식 오류(필드 누락·길이·좌표 범위) |
| 401 | 로그인 필요·토큰 만료 |
| 403 | 권한 없음(남의 데이터, 관리자 아님, CSRF 실패) |
| 404 | 없는 대상(폐업·숨김 가게도 404, FR-DTL-07) |
| 409 | 상태 충돌(관심 가맹점 500곳 초과, 갱신이 이미 실행 중 FR-UPD-08) |
| 410 | 검색 결과 보관 10분이 지남(다음 페이지 요청, FR-LST-02) |
| 413 | 올린 파일이 너무 큼(100MB) |
| 422 | 형식은 맞지만 처리할 수 없음(갱신 파일 열 구성이 다름 FR-UPD-02, P2 업로드 API) |
| 429 | 요청 제한 초과(NFR-SEC-04). **모든 API**가 줄 수 있다. `Retry-After` 헤더 |
| 500 / 503 | 서버 오류 / 점검·과부하 |

검색 결과가 0곳인 것은 오류가 아니다. 200으로 빈 목록과 안내 문구 코드를 준다.

## 4. 오류 형식

모든 4xx·5xx는 같은 모양이다.

```json
{
  "code": "SEARCH_RESULT_EXPIRED",
  "message": "검색 결과가 만료됐어요. 다시 검색해 주세요.",
  "details": { "queryId": "8c1f…" },
  "traceId": "4bf92f3577b34da6"
}
```

| 필드 | 내용 |
|---|---|
| `code` | 화면이 분기에 쓰는 고정 코드. `영역_내용` 대문자(아래 표) |
| `message` | 사람이 읽는 한국어 설명(개발·로그용). 화면은 `code`로 요구사항 8절의 문구·형태(전체 화면·대화상자·토스트)를 고른다 |
| `details` | 선택. 필드 오류는 `{ "fields": [{ "field": "q", "reason": "TOO_LONG" }] }` |
| `traceId` | 서버 로그와 맞춰 보는 요청 ID. 개인정보를 넣지 않는다 |

`details.fields[].reason` 값: `REQUIRED`, `TOO_LONG`, `TOO_SHORT`, `INVALID_FORMAT`, `OUT_OF_RANGE`(좌표·숫자 범위 밖), `NOT_ALLOWED`(바꿀 수 없는 값).

| code(초안) | 상태 |
|---|---|
| `INVALID_REQUEST`(필드 오류는 details.fields), `PASSWORD_POLICY`, `INVALID_FILE`(.xlsx 아님), `TERMS_REQUIRED`(필수 약관 미동의) | 400 |
| `AUTH_REQUIRED`, `TOKEN_EXPIRED`, `INVALID_CREDENTIALS`(아이디·비밀번호 틀림), `SIGNUP_EXPIRED`(가입 대기 10분 지남), `REFRESH_REUSED`(이미 쓴 갱신 토큰) | 401 |
| `FORBIDDEN`, `CSRF_FAILED`, `ACCOUNT_LOCKED`(details.lockedUntil), `ACCOUNT_DISABLED`, `PASSWORD_CHANGE_REQUIRED`(첫 비밀번호 변경 전 관리자 API) | 403 |
| `STORE_NOT_FOUND`, `NOT_FOUND` | 404 |
| `REFRESH_ALREADY_RUNNING`, `SAME_FILE_ALREADY_APPLIED`, `INVALID_STATE`, `DUPLICATE`, `FAVORITE_LIMIT`(500곳 초과), `ALREADY_MEMBER` | 409 |
| `SEARCH_RESULT_EXPIRED` | 410 |
| `FILE_TOO_LARGE` | 413 |
| `SOURCE_COLUMNS_MISMATCH` | 422 |
| `RATE_LIMITED` | 429 |
| `INTERNAL_ERROR`, `SERVICE_UNAVAILABLE`, `MAINTENANCE`(계획된 점검, details.until 선택 — 화면 E-01 "서비스 점검 중이에요") | 500, 503 |

## 5. 인증·세션

| 대상 | 방식 | 근거 |
|---|---|---|
| 모든 사용자 | 익명 세션 쿠키 `sid`(첫 방문에 발급, 30분 무활동이면 새로). 로그용이고 회원 ID와 잇지 않는다 | FR-LOG-05 |
| 회원 | 접근 토큰 `access_token` 30분 + 갱신 토큰 `refresh_token` 14일(경로 `/api/v1/auth`), 둘 다 HttpOnly·Secure·SameSite=Lax 쿠키. 갱신 토큰은 쓸 때마다 새로 발급, 이미 쓴 토큰이 오면 그 계열을 모두 폐기. 서버 쪽 저장은 세션 저장소(Redis) | FR-MBR-06, DR-13 |
| 소셜 로그인 | `GET /auth/{provider}/login` → 제공자 화면 → `GET /auth/{provider}/callback`. 위조 방지 state는 `oauth_state` 쿠키(10분). 처음 온 사람·약관이 바뀐 회원은 `signup_token` 쿠키(10분)를 받고 가입 동의(U-08) 뒤 `POST /auth/signup`. 돌아갈 주소(returnTo)는 우리 서비스 안 경로만 | FR-MBR-01·02 |
| 관리자 | 아이디·비밀번호 로그인 후 서버 세션 쿠키(회원과 다른 이름·경로 `/api/v1/admin`). 30분 무활동 만료, 5회 실패 30분 잠금. 임시 비밀번호로 로그인한 세션(`mustChangePassword`)은 비밀번호를 바꾸기 전까지 `/admin/me`·비밀번호 변경·로그아웃만 되고 나머지는 403 `PASSWORD_CHANGE_REQUIRED` | FR-ADM-01·02·04 |
| CSRF | 관리자 로그인, 회원 로그인 콜백·가입·토큰 갱신 때 읽을 수 있는 쿠키 `csrf_token`을 주고, 쿠키 인증을 쓰는 `POST·PUT·PATCH·DELETE`는 그 값을 헤더 `X-CSRF-Token`에 넣는다. 검색·이벤트 수집처럼 로그인과 무관한 요청은 제외 | NFR-SEC-02 |

비회원도 검색·조회·상세·이벤트 API를 쓴다. 회원 전용 API(최근 검색어, 관심 가맹점, 내 정보, 탈퇴)는 401을 준다. 로그인한 회원이 검색·상세를 부르면 결과 카드에 `favorited`가 붙고, 검색어가 최근 검색어에 저장된다. 이벤트 API는 sendBeacon 때문에 회원 쿠키·CSRF 토큰을 요구하지 않고 익명 세션만 쓴다.

## 6. 요청 제한

- IP당 1분 300회, 검색 API는 세션당 1분 60회(NFR-SEC-04). 초과하면 429와 `Retry-After`.
- IP는 메모리에서 세기만 하고 저장하지 않는다.

## 7. 버전·응답 헤더

- 검색 응답 본문에 `corpusVersion`(데이터 버전), `pipelineVersion`(정책·계수 버전)을 넣는다(IR-01).
- 모든 응답 헤더에 `X-Trace-Id`.

## 8. 명세 확장 표시

`openapi.yaml`의 각 API에 `x-priority`(P0·P1·P2, 요구사항 1-4)와 `x-requirements`(근거 요구사항 ID)를 단다.

## 9. 아직 정하지 않은 것

| 항목 | 담당 |
|---|---|
| 관리자 세션을 서버 세션으로 둘지 토큰으로 둘지 세부(지금은 서버 세션) | 백엔드 |
| 위치 정밀도(격자 크기) 최종 | 법무 |

## 10. API 목록 (명세 v0.8)

자세한 요청·응답은 [`openapi.yaml`](openapi.yaml). P1 API(소셜 로그인, 회원, 이벤트, 통계)는 v0.4에서 더했다. 관리자 화면 축소(2026-11-13)로 주간 갱신·별칭·지명 제외·원천 변경 알림·관리자 계정 화면과 그 API는 P2이고, 1차는 서버 스크립트·DB 직접 작업으로 한다.

| 우선 | 메서드·주소 | 하는 일 | 화면 |
|---|---|---|---|
| P0 | `GET /meta` | 업종·결제 칩 목록, 기본 위치, 약관·방침 링크·위치기반서비스 약관 버전, 제한 값 | 처음 열 때, 메뉴, U-12 |
| P0 | `POST /search` | 검색(검색창 = 목록 규칙, '현 지도 재검색' = 지도 규칙), 칩 재검색, "○○ 지역으로 보기". 첫 20곳 + 핀 전부(카드 필드 포함) + 문구 + 지도 맞춤 범위 | U-01·03·04·05 |
| P0 | `POST /browse` | 검색어 없는 조회(화면 안 가게, 가까운 순), 칩만 고름 | U-01·05 |
| P0 | `GET /search/{queryId}/page?cursor=` | 다음 20곳. 10분 지나면 410 | U-03 |
| P0 | `GET /stores/{storeId}` | 가게 상세. 폐업·숨김·없음은 404 | U-06·11 |
| P0 | `POST /admin/auth/login`, `POST /admin/auth/logout`, `GET /admin/me` | 관리자 로그인·로그아웃·세션 확인 | A-01 |
| P0 | `PUT /admin/me/password` | 비밀번호 변경(첫 로그인 강제 — 새 비밀번호만, 평소엔 지금 비밀번호도) | A-01 |
| P0 | `GET /admin/stores` | 가맹점 목록(검색·거르기·50건씩, 상호 가나다순 고정) | A-03 |
| P0 | `GET /admin/stores/{storeId}` | 원천 값·수정 값·마지막 수정 | A-04 |
| P0 | `PUT·DELETE /admin/stores/{storeId}/overrides/{field}` | 필드 수정(사유 필수)·해제. 주소·좌표는 이 API로 고치지 않음(1차 DB 직접, P2) | A-04 |
| P0 | `PUT /admin/stores/{storeId}/visibility` | 숨김·해제(사유 필수) | A-04 |
| P1 | `GET /auth/{provider}/login`, `GET /auth/{provider}/callback` | 카카오·구글 로그인 시작·콜백(302) | U-07 |
| P1 | `GET /auth/terms`, `POST /auth/signup` | 약관 묶음, 가입(또는 바뀐 약관 다시 동의) | U-08 |
| P1 | `POST /auth/refresh`, `POST /auth/logout` | 토큰 다시 받기, 로그아웃 | 공통 |
| P1 | `GET /me`, `PATCH /me`, `DELETE /me` | 내 정보, 닉네임 변경(v0.7에 P1), 탈퇴 | U-09, 메뉴 |
| P1 | `GET·DELETE /me/recent-searches`, `DELETE /me/recent-searches/{recentId}` | 최근 검색어 10개, 전체·하나 삭제 | U-02 |
| P1 | `GET /me/favorites`, `PUT·DELETE /me/favorites/{storeId}` | 관심 가맹점 목록(50곳씩), 추가(최대 500)·해제 | U-10, U-03·U-06 별 버튼 |
| P1 | `POST /events` | 행동 이벤트 묶음(최대 50개, sendBeacon 가능) | 전 화면 |
| P1 | `POST /search`의 `placeOnly`(주변 가게 포함), `regionChoice`·`otherRegions`(지금 지역 포함, 거리순·km), 문구 `zoom_in`·`region_ambiguous` | 지명만 입력, 다른 지역 선택, 확대 안내 | U-01·U-04 |
| P1 | `GET /admin/stats/summary`, `/top-queries`, `/problem-queries`, `/messages` | 지표 요약·추이, 인기 검색어, 결과 없는 검색어, 문구별 비율. CSV는 화면이 이 응답으로 만든다(CSV API 없음, FR-STA-03) | A-10 |
| P2 | `GET /admin/data-versions/active` | 지금 검색이 쓰는 데이터 버전 | A-05 |
| P2 | `POST /admin/refresh-jobs` | 원천 엑셀 올리기 → 갱신 시작(202). 1차는 서버 스크립트 | A-05 |
| P2 | `GET /admin/refresh-jobs/current`, `GET /admin/refresh-jobs/{jobId}` | 진행 중 작업, 진행·결과 | A-05 |
| P2 | `POST /admin/refresh-jobs/{jobId}/approve`, `/cancel` | 안전장치 승인·취소. 1차는 스크립트 명령 | A-05 |

### 10-1. 출시 뒤(P2) 예정 API — 목록만

1차에는 만들지 않고 자세한 명세도 아직 쓰지 않는다. 주소는 가안이다.

| 화면·기능 | 예정 API(가안) | 하는 일 | 근거 |
|---|---|---|---|
| 자동완성 | `GET /autocomplete?q=` | 상호·지명·브랜드 제안 최대 8개 | FR-SRC-12 |
| 비회원 위치 동의 기록(법무 결과에 따라, 필요하면 P1) | `POST /consents/location` | 익명 동의 기록(약관 버전·시각, 회원·좌표 없음) | FR-LOC-03 |
| 로그인 수단 추가·해제 | `GET /auth/{provider}/link`, `DELETE /me/providers/{provider}` | 다른 소셜 계정 연결·해제 | FR-MBR-05 |
| A-02 관리자 홈 | `GET /admin/home` | 오늘 지표, 최근 갱신 상태, 확인할 알림 | FR-ADM-06 |
| A-04 주소·좌표 수정 | `PUT /admin/stores/{storeId}/overrides/location` | 지도 핀 이동으로 주소·좌표·법정동 코드 수정 | FR-STO-03 |
| A-06 원천 변경 알림 | `GET /admin/source-changes`, `POST /admin/source-changes/{id}/keep`·`/revert` | 알림 목록, 수정 유지 / 원천으로 | FR-STO-08 |
| A-07 브랜드 별칭 | `GET·POST /admin/brand-aliases`, `PUT·DELETE /admin/brand-aliases/{id}` | 묶음 조회·추가·수정·삭제 | FR-REF-01 |
| A-08 지명 제외 | `GET·POST /admin/place-exclusions`, `DELETE /admin/place-exclusions/{id}` | 말·사유 추가·삭제 | FR-REF-02 |
| A-09 해석 미리보기 | `POST /admin/parse-preview` | 검색어·검색 중심 → 해석 결과 | FR-REF-03 |
| A-12 관리자 계정 | `GET·POST /admin/accounts`, `PATCH /admin/accounts/{id}`, `POST /admin/accounts/{id}/reset-password` | 생성·비활성화·비밀번호 초기화 | FR-ADM-04 |

## 11. 화면 동작별 호출 (v0.8)

화면설계(`docs/design/`)의 동작마다 어느 API를 어떤 값으로 부르는지. 자세한 필드는 `openapi.yaml`, 화면별 전체 대응은 [`docs/design/SCREEN_API_MAP.md`](../design/SCREEN_API_MAP.md).

| 화면 동작 | 호출 | 보내는 값·받은 값 쓰는 법 | 우선 |
|---|---|---|---|
| 처음 열기 | `GET /meta` → (첫 방문이면 U-12 위치 정보 이용 안내) → `POST /browse`, 뒤에서 `GET /me` | U-12는 브라우저에 저장된 동의 버전이 없거나 `policies.locationTerms.version`과 다를 때만. 고른 뒤 지금 지도 범위·GPS(또는 기본 위치)로 조회. 첫 화면 실패는 E-01(연결 안 됨 / 서버 오류·점검). 칩 목록은 `/meta`에서. 로그인 상태는 검색·조회를 막지 않고 뒤에서: `GET /me` → 401이면 `POST /auth/refresh` 한 번 → 다시 `GET /me`, 또 401이면 비회원(FR-MBR-12) | P0 |
| 내 위치 버튼 | 호출 없음 | 지도만 GPS로 옮기고 '현 지도 재검색' 버튼을 띄운다(FR-MAP-01) | P0 |
| 검색창 ×·←로 검색 끝내기 | 호출 없음 | 검색 전에 받아 둔 `/browse` 결과(지도 위치·핀·시트·칩)를 그대로 다시 보여 준다(FR-BRW-06) | P0 |
| 화면 대각선 50km 초과 | 호출 없음 | 화면이 `/meta`의 `limits.mapMaxDiagonalKm`으로 먼저 재고 토스트 ⑩. 이미 보여 준 핀·시트는 그대로(FR-MAP-05) | P1 |
| 검색창 검색 | `POST /search` | `view=list`, `inputType=typed`. 응답 `mapFit`으로 지도를 맞추고 `pins`·`results`를 함께 표시 | P0 |
| 지도를 옮기고 '현 지도 재검색' | 검색어 있음 `POST /search`(`view=map`, `bounds`) / 없음 `POST /browse` | `mapFit`은 null(지도 그대로). 0곳이라 옮긴 경우(⑧)만 범위가 온다 | P0 |
| **칩 변경**(검색어 있음) | `POST /search` | **직전 요청 본문 그대로, `categoryCode`·`paymentCodes`만 바꾸고 `inputType=chip`**. 그사이 지도를 옮겼어도 직전 조건. `view=list`면 `mapFit`으로 다시 맞추고 `view=map`이면 지도 그대로 | P0 |
| 칩 변경(검색어 없음) | `POST /browse` | 지금 보이는 `bounds`에 칩 적용. 지도 그대로 | P0 |
| **핀 누름** | 호출 없음(+ 이벤트 `pin_click`) | `pins[]`에 카드 필드가 다 있어 바로 요약 카드(U-05). `position`은 `rank` | P0 |
| 핀 묶음 누름 | 호출 없음(+ 이벤트 `cluster_click`) | 지도를 그 영역으로 확대만. 묶음 라벨 "{상호} 외 {n}개"의 상호는 묶음 안 `rank`가 가장 작은 핀(FR-MAP-07) | P1 |
| 목록 아래로 내림 | `GET /search/{queryId}/page` | `nextCursor`. 410이면 직전 요청으로 다시 검색 | P0 |
| 카드·요약 카드 누름 | `GET /stores/{storeId}` | 404면 U-11. 상세에서 보내는 이벤트(`action` 등)의 `queryId`·`position`은 URL이 아니라 화면 상태(history state)로 넘긴다. 공유 링크로 바로 열면 null | P0 |
| 상세 공유 | 호출 없음(+ 이벤트 `action: share`) | 상세 응답 `name`·`address`로 공유 글을 만든다(FR-DTL-05, 전화 줄 없음) | P1 |
| **"○○ 지역으로 보기"**(작은 줄 `name_first`) | `POST /search` | 같은 `q`에 `skipNameFirst=true`, `inputType=region_view` | P0 |
| "다른 ○○"(작은 줄 `region_ambiguous`) | 시트는 호출 없음 → 고르면 `POST /search` | 시트는 `otherRegions`(지금 지역 `current` 포함, `distanceKm` 순). `current`가 아닌 지역을 고르면 같은 `q`에 `regionChoice=regionId`, `inputType=region_choice` | P1 |
| 지명만 입력 | `POST /search` | 응답 `placeOnly.mapFit`으로 지도 이동, 주변 가게는 같은 응답의 `pins`·`results`(따로 `/browse` 안 부름) | P1 |
| "'○○' 가게 보기" | `POST /search` | `q`=가게 이름, `inputType=place_store` | P1 |
| 최근 검색어 누름 | `POST /search` | `inputType=recent` | P1 |
| 별(관심 가맹점) 누름 | `PUT`·`DELETE /me/favorites/{storeId}` | 비회원은 "로그인이 필요해요" 대화상자 → 로그인 → 돌아오면 그 가게로 `PUT` 한 번(화면이 storeId만 sessionStorage에 잠깐 기억). 다음 페이지의 `favorited`는 서버가 응답 때마다 새로 계산 | P1 |
| 관심 가맹점(U-10)에서 별 해제 | `DELETE /me/favorites/{storeId}` | 성공하면 그 줄을 바로 목록에서 뺀다. 비면 빈 화면 | P1 |
| 메뉴 ☰ | `GET /me`(이미 받았으면 호출 없음) | 회원이면 "{nickname}님, 반가워요!". 아래쪽 이용약관·개인정보처리방침 링크는 `/meta`의 `policies` | P1 |
| 닉네임 변경 / 탈퇴 | `PATCH /me` / `DELETE /me` | 탈퇴는 확인 대화상자 뒤에 | P1 |
| 관리자 첫 로그인 | `POST /admin/auth/login` → `PUT /admin/me/password` | 응답 `mustChangePassword`면 비밀번호 변경 화면. `newPassword`만 보낸다 | P0 |
| 관리자 A-10 CSV | 호출 없음 | 화면에 받아 둔 통계 응답으로 CSV(UTF-8 BOM) | P1 |
| 관리자 A-03 필터·A-04 업종 선택지 | `GET /meta` | 업종 17개를 여기서 받는다(관리자 전용 업종 API 없음) | P0 |
