# API 공통 규칙 (v0.2)

> 작성 2026-11-13 · 기준: `docs/REQUIREMENTS.md` v0.9(5절 IR, 3절 NFR-SEC·PRV) · 명세: [`openapi.yaml`](openapi.yaml)(OpenAPI 3.1)
> 모든 API에 똑같이 적용한다. 개별 API 명세는 `openapi.yaml`에 쓰고, 이 문서와 다르면 이 문서를 먼저 고친다.

## 1. 결정 요약

| 항목 | 규칙 | 결정 |
|---|---|---|
| 주소 | 사용자 `/api/v1/...`, 관리자 `/api/v1/admin/...`. 형식을 깨는 변경은 `/api/v2` | 2026-11-13 |
| 필드 이름 | JSON은 **camelCase**(`storeId`, `queryId`). DB·로그 문서는 snake_case 그대로, 변환은 백엔드가 한다 | 2026-11-13 |
| 시각 | **KST 오프셋을 붙인 ISO 8601**(`2026-11-13T14:30:00+09:00`). DB 저장은 UTC(NFR-QLT-05) | 2026-11-13 |
| 날짜만 | `2026-11-13`(한국 날짜). 데이터 버전 이름도 같은 형식(`2026-11-13`, 같은 날 두 번째는 `2026-11-13.2`) | |
| 좌표 | `{ "lat": 36.3504, "lng": 127.3845 }`, WGS84. 지도 범위는 `{ "sw": {…}, "ne": {…} }` | |
| 위치 전송 | GPS 원 좌표는 **요청 본문**으로만 보내고 서버는 저장하지 않는다. 로그는 100m 격자. 좌표·세션을 URL에 넣지 않는다(NFR-PRV-02) | 2026-11-13 |
| 다음 페이지 | 사용자 검색·조회는 커서 방식. 응답의 `nextCursor`를 다음 요청에 그대로 보낸다. 없으면 마지막 페이지(FR-LST-01·02). 관리자 표는 페이지 번호 방식(`page`, `size`, 응답 `totalCount`) — 화면에 페이지 번호가 있어서 | |
| 문서 형식 | OpenAPI 3.1 YAML. 백엔드는 springdoc으로 같은 문서를 내보내 대조한다 | 2026-11-13 |

## 2. 요청

- 본문은 `application/json; charset=utf-8`. 파일 올리기(주간 갱신)만 `multipart/form-data`.
- 조회는 `GET`, 만들기·실행 `POST`, 값 하나를 통째로 정하기 `PUT`(필드 수정, 숨김), 일부 바꾸기 `PATCH`, 지우기 `DELETE`. 검색·조회처럼 좌표를 보내야 하는 읽기는 `POST`(좌표를 URL에 넣지 않기 위해).
- 빈 값: 없는 값은 필드를 빼거나 `null`. 목록은 빈 배열 `[]`(예: `paymentChips: []` = 전체).
- 코드 값은 소문자 영어(`list`, `map`, `qr`, `card`). 화면 글자는 응답에 넣지 않고 코드로 내려 준다(문구는 코드 + 치환값, FR-MSG-02).

## 3. 응답

성공은 데이터를 바로 준다(감싸는 `data` 없음).

```json
{ "queryId": "8c1f…", "results": [ … ], "nextCursor": "MjA", "totalCount": 15 }
```

| 상태 코드 | 쓰는 때 |
|---|---|
| 200 | 조회·처리 성공 |
| 201 | 만들기 성공(즐겨찾기 추가, 관리자 계정 생성) |
| 202 | 받아서 나중에 처리(이벤트 수집 IR-05, 갱신 실행) |
| 204 | 본문 없는 성공(삭제, 로그아웃) |
| 400 | 형식 오류(필드 누락·길이·좌표 범위) |
| 401 | 로그인 필요·토큰 만료 |
| 403 | 권한 없음(남의 데이터, 관리자 아님, CSRF 실패) |
| 404 | 없는 대상(폐업·숨김 가게도 404, FR-DTL-07) |
| 409 | 상태 충돌(갱신이 이미 실행 중 FR-UPD-08, 같은 별칭 중복) |
| 410 | 검색 결과 보관 10분이 지남(다음 페이지 요청, FR-LST-02) |
| 413 | 올린 파일이 너무 큼(100MB) |
| 422 | 형식은 맞지만 처리할 수 없음(엑셀 열 구성이 다름 FR-UPD-02) |
| 429 | 요청 제한 초과(NFR-SEC-04). `Retry-After` 헤더 |
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
| `message` | 사람이 읽는 한국어 설명. 화면은 그대로 띄워도 되지만 문구 확정은 화면설계(8절 ⚠) |
| `details` | 선택. 필드 오류는 `{ "fields": [{ "field": "q", "reason": "TOO_LONG" }] }` |
| `traceId` | 서버 로그와 맞춰 보는 요청 ID. 개인정보를 넣지 않는다 |

| code(초안) | 상태 |
|---|---|
| `INVALID_REQUEST`, `PASSWORD_POLICY`, `INVALID_FILE`(.xlsx 아님) | 400 |
| `AUTH_REQUIRED`, `TOKEN_EXPIRED`, `INVALID_CREDENTIALS`(아이디·비밀번호 틀림) | 401 |
| `FORBIDDEN`, `CSRF_FAILED`, `ACCOUNT_LOCKED`(details.lockedUntil), `ACCOUNT_DISABLED` | 403 |
| `STORE_NOT_FOUND`, `NOT_FOUND` | 404 |
| `REFRESH_ALREADY_RUNNING`, `SAME_FILE_ALREADY_APPLIED`, `INVALID_STATE`, `DUPLICATE` | 409 |
| `SEARCH_RESULT_EXPIRED` | 410 |
| `FILE_TOO_LARGE` | 413 |
| `SOURCE_COLUMNS_MISMATCH` | 422 |
| `RATE_LIMITED` | 429 |
| `INTERNAL_ERROR`, `SERVICE_UNAVAILABLE` | 500, 503 |

## 5. 인증·세션

| 대상 | 방식 | 근거 |
|---|---|---|
| 모든 사용자 | 익명 세션 쿠키 `sid`(첫 방문에 발급, 30분 무활동이면 새로). 로그용이고 회원 ID와 잇지 않는다 | FR-LOG-05 |
| 회원 | 접근 토큰 30분 + 갱신 토큰 14일, 둘 다 HttpOnly·Secure·SameSite=Lax 쿠키. 갱신 토큰은 쓸 때마다 새로 발급, 서버 쪽 저장은 세션 저장소(Redis) | FR-MBR-06, DR-13 |
| 관리자 | 아이디·비밀번호 로그인 후 서버 세션 쿠키(회원과 다른 이름·경로 `/api/v1/admin`). 30분 무활동 만료, 5회 실패 30분 잠금 | FR-ADM-01·02 |
| CSRF | 로그인 때 읽을 수 있는 쿠키 `csrf_token`을 주고, 쿠키 인증을 쓰는 `POST·PUT·PATCH·DELETE`는 그 값을 헤더 `X-CSRF-Token`에 넣는다. 검색·이벤트 수집처럼 로그인과 무관한 요청은 제외 | NFR-SEC-02 |

비회원도 검색·조회·상세·이벤트 API를 쓴다. 회원 전용 API(최근 검색어, 즐겨찾기, 내 정보, 탈퇴)는 401을 준다.

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
| 오류 `message` 최종 문장 | 화면설계 |
| 관리자 세션을 서버 세션으로 둘지 토큰으로 둘지 세부(지금은 서버 세션) | 백엔드 |
| 위치 정밀도(격자 크기) 최종 | 법무 |

## 10. API 목록 (명세 v0.2)

자세한 요청·응답은 [`openapi.yaml`](openapi.yaml). P1 API(소셜 로그인, 회원, 이벤트, 별칭·지명 제외, 원천 변경 알림, 통계, 관리자 계정)는 다음 판에서.

| 우선 | 메서드·주소 | 하는 일 | 화면 |
|---|---|---|---|
| P0 | `GET /meta` | 업종·결제 칩 목록, 기본 위치, 제한 값 | 처음 열 때 |
| P0 | `POST /search` | 검색(검색창 = 목록 규칙, '현 지도 재검색' = 지도 규칙). 첫 20곳 + 핀 전부 + 문구 + 지도 맞춤 범위 | U-01·03·04 |
| P0 | `POST /browse` | 검색어 없는 조회(화면 안 가게, 가까운 순) | U-01 |
| P0 | `GET /search/{queryId}/page?cursor=` | 다음 20곳. 10분 지나면 410 | U-03 |
| P0 | `GET /stores/{storeId}` | 가게 상세. 폐업·숨김·없음은 404 | U-06·11 |
| P0 | `POST /admin/auth/login`, `POST /admin/auth/logout`, `GET /admin/me` | 관리자 로그인·로그아웃·세션 확인 | A-01 |
| P0 | `PUT /admin/me/password` | 비밀번호 변경(첫 로그인 강제) | A-01 |
| P0 | `GET /admin/stores` | 가맹점 목록(검색·거르기·50건씩) | A-03 |
| P0 | `GET /admin/stores/{storeId}` | 원천 값·수정 값·마지막 수정 | A-04 |
| P0 | `PUT·DELETE /admin/stores/{storeId}/overrides/{field}` | 필드 수정(사유 필수)·해제 | A-04 |
| P0 | `PUT /admin/stores/{storeId}/visibility` | 숨김·해제(사유 필수) | A-04 |
| P0 | `GET /admin/data-versions/active` | 지금 검색이 쓰는 데이터 버전 | A-05 |
| P0 | `POST /admin/refresh-jobs` | 원천 엑셀 올리기 → 갱신 시작(202) | A-05 |
| P0 | `GET /admin/refresh-jobs/current`, `GET /admin/refresh-jobs/{jobId}` | 진행 중 작업, 진행·결과 | A-05 |
| P1 | `POST /admin/refresh-jobs/{jobId}/approve`, `/cancel` | 안전장치 승인·취소 | A-05 |
