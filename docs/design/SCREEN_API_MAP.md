# 화면별 기능·API 대응표

기준: 화면 그림 `docs/design/screens/`(캔버스 `1794882428-8e37`), 요구사항 7·8절, API 명세 `docs/api/openapi.yaml`, API 규칙 11절.
표시: — 는 API를 부르지 않고 화면 안에서 처리. 우선은 요구사항 1-4 기준.

## 1. 사용자 화면

### U-01 메인 (`Main`, `U01-Payment`, `U01-PlaceOnly`, `U01-ZoomIn`, `U01-Empty`)

| 화면 요소·동작 | API | 보내는 값 / 쓰는 응답 | 우선 |
|---|---|---|---|
| 처음 열기: 칩 목록·기본 위치·한도 | `GET /meta` | `categories`(17), `paymentMethods`, `defaultLocation`, `limits.mapMaxDiagonalKm` | P0 |
| 첫 방문: U-12 위치 정보 이용 안내 | `GET /meta`(`policies.locationTerms`) | 브라우저에 저장한 동의 버전이 없거나 다르면 띄움. [동의하고 위치 사용] → 브라우저 권한 창, [나중에] → 기본 위치 + ⑨. 고른 뒤 조회 | P0 |
| 처음 열기: 화면 안 핀·시트 목록("가까운 순 · 106곳") | `POST /browse` | `bounds`·`center`·`centerSource`·`userLocation` → `pins`, `results`(20), `totalCount` | P0 |
| 처음 열기: 로그인 상태(메뉴·별 표시용) | 뒤에서 `GET /me` → 401이면 `POST /auth/refresh` 한 번 → `GET /me` | 검색·조회를 기다리게 하지 않음. 실패하면 비회원(FR-MBR-12) | P1 |
| 첫 화면을 못 불러옴 | — | E-01 전체 화면: 연결 안 됨 / 서버 오류·응답 없음·지도 로드 실패(503 `MAINTENANCE`면 점검 문구). 고객센터 1670-1600은 화면에 고정 | P0 |
| 위치 권한 없음 → 작은 줄 ⑨ | `POST /browse` | `centerSource=default` → `subMessage=default_location` | P0 |
| 핀 묶음 라벨 "○○ 외 N개" | — | 묶음 안 `rank`가 가장 작은 핀의 상호(검색 = 목록 맨 위, 조회 = 가장 가까운 곳) | P1 |
| 핀 묶음 누름 | — (+ 이벤트 `cluster_click`) | 갈라지면 확대, 안 갈라지면(최대 줌·30m 안) 겹친 가게 목록 | P1 |
| 같은 좌표 핀 누름 | — (조회가 300곳에서 잘렸으면 `POST /browse`에 `spot` = 누른 핀 좌표, 300곳 상한 없이 20곳씩 `/page`) | U-05b "이 위치 가맹점 n곳" 목록. 검색 = rank 순, 조회 = 상호 가나다순 | P0 |
| 내 위치 버튼 | — | 지도만 이동, '현 지도 재검색' 버튼 표시. 두 버튼은 시트 위 12px에 붙어 시트와 함께 움직이고 시트 전체면 숨김 | P0 |
| 지도 이동 → '현 지도 재검색' | `POST /browse` (+ `research_here`) | 지금 `bounds` | P0 |
| 화면 0곳 ④ | `POST /browse` | `message=map_empty` | P0 |
| 확대 안내 ⑩ | — | 대각선 > `limits.mapMaxDiagonalKm`이면 부르지 않고 토스트. 이전 핀·시트 유지, 재검색 버튼도 토스트만 | P1 |
| 업종 칩 / 결제 칩 "선택완료" | `POST /browse` / 검색어 있으면 `POST /search` | `categoryCode`·`paymentCodes`. 검색은 직전 본문 + `inputType=chip` | P0 |
| 칩 0곳 ⑫ "조건 해제" | 위와 같음 | 칩을 비운 본문 | P0 |
| 지명만 입력 / "'노량진수산' 가게 보기" | `POST /search` | `placeOnly.mapFit` / `q=storeSuggestion.name`, `inputType=place_store` | P1 |
| 시트 카드 누름 | `GET /stores/{id}` | U-06 | P0 |
| 별 | `PUT`·`DELETE /me/favorites/{id}` | 비회원 → "로그인이 필요해요" → U-07 → 돌아오면 그 가게 `PUT` 한 번 | P1 |
| 메뉴 ☰ | `GET /me`(받아 둔 값), `/meta`의 `policies` | 비회원 `Menu` / 회원 `Menu-Member` "{닉네임}님, 반가워요!" · 내 정보 > · 관심 가맹점 >. 아래쪽 이용약관 · 개인정보처리방침(P0) — 온누리상품권 홈페이지 `terms?tab=0`·`tab=1`, 새 탭 | P1 |

### U-02 검색창 열림 (`U02-Member`, `U02-Guest`)

| 화면 요소·동작 | API | 보내는 값 / 쓰는 응답 | 우선 |
|---|---|---|---|
| 최근 검색어 10개 | `GET /me/recent-searches` | 비회원 401 → 로그인 안내 한 줄 | P1 |
| 하나 삭제 / 전체삭제 | `DELETE /me/recent-searches/{recentId}` / `DELETE /me/recent-searches` | | P1 |
| 최근 검색어 누름 | `POST /search` | `inputType=recent` | P1 |
| 검색 실행 | `POST /search` | `view=list`, `inputType=typed` | P0 |
| 저장 대상 | (검색 API 안) | `typed`·`recent`·`place_store`·`autocomplete`만. 칩·지역 재검색은 저장·시각 갱신 안 함 | P1 |

### U-03 목록 / U-04 지도 (`U03-List`, `U04-Map`, `U04-OtherRegion`)

| 화면 요소·동작 | API | 보내는 값 / 쓰는 응답 | 우선 |
|---|---|---|---|
| 검색 직후 지도 맞춤·핀·시트 | `POST /search` 응답 | `mapFit`, `pins`, `results`, `totalCount` | P0 |
| 큰 문구·작은 줄 | 응답 `message`·`subMessage` | 코드 + 치환값 | P0 |
| "○○ 지역으로 보기" | `POST /search` | `skipNameFirst=true`, `inputType=region_view` | P0 |
| "다른 중구" 시트 | 응답 `interpretation.otherRegions` | 지금 지역(`current`) 포함, `distanceKm` 순, 지역마다 km | P1 |
| 시트에서 다른 지역 고름 | `POST /search` (+ `region_choice`) | `regionChoice`, `inputType=region_choice`. 지금 지역을 고르면 시트만 닫음 | P1 |
| 목록 아래로 내림 | `GET /search/{queryId}/page` | 20곳씩 이어 붙임(앞 카드 유지, 위로 올리면 1위부터, 상세에서 돌아오면 위치 그대로). 410 → 목록은 그대로 두고 더 부르지 않음(다시 검색 안 함) | P0 |
| '목록 보기' / '지도 보기' | — | 같은 결과 | P0 |
| '현 지도 재검색' | `POST /search` | `view=map`, `bounds` | P0 |
| 검색창 × / ← | — | 검색 전 조회 화면(지도·핀·시트·칩)을 그대로 다시 보여 줌 | P0 |
| 노출·클릭 | `POST /events` | `impression`, `click` | P1 |

### U-05 요약 카드 · U-05b 겹친 가게 목록 (`U05-Card`, `U05-SameSpot`)

| 화면 요소·동작 | API | 보내는 값 / 쓰는 응답 | 우선 |
|---|---|---|---|
| 핀 누름 | — (+ `pin_click`) | `pins[]`의 카드 필드 | P0 |
| 카드 누름 / 별 | `GET /stores/{id}` / `PUT`·`DELETE /me/favorites/{id}` | | P0 / P1 |
| 같은 좌표 핀 누름 → 목록 | 보통 호출 없음 | 받아 둔 핀으로 목록, 카드 클릭은 `click`(position = rank) | P0 |

### U-06 상세 (`U06-Detail`)

| 화면 요소·동작 | API | 보내는 값 / 쓰는 응답 | 우선 |
|---|---|---|---|
| 업종·시장·상호·주소·결제·별 | `GET /stores/{id}` | `StoreDetail`(`favorited` 포함) | P0 |
| 거리 | — | GPS와 `location`으로 화면 계산 | P0 |
| 길찾기 | — (+ `action: directions`) | `nmap://route` → 웹 | P0 |
| 공유 | — (+ `action: share`) | `[디지털온누리상품권 가맹점]` / 상호 / `주소 : {address}` / (전화 없으면 줄 뺌) / 링크. 공유 불가면 링크 복사 토스트. `/store/{id}` 첫 HTML에 `og:title`·`og:description` | P1 |
| 이벤트의 `queryId`·`position` | `POST /events` | 화면 상태(history state)로 넘김, URL에 넣지 않음 | P1 |
| 폐업·숨김·없는 ID | 404 | U-11 | P0 |

### U-07 로그인 · U-08 가입 동의

| 화면 요소·동작 | API | 우선 |
|---|---|---|
| 카카오·Google로 시작하기 | `GET /auth/{provider}/login?returnTo=` → callback | P1 |
| 약관 목록·전문 | `GET /auth/terms` | P1 |
| 동의하고 시작하기 | `POST /auth/signup` | P1 |
| 로그인 실패 | — | 대화상자 "로그인하지 못했어요" | P1 |

### U-09 내 정보 (`U09-MyInfo`, `U09-Nickname`, `U09-Withdraw`)

| 화면 요소·동작 | API | 보내는 값 / 쓰는 응답 | 우선 |
|---|---|---|---|
| 닉네임·이메일·로그인 수단 | `GET /me` | 이메일은 보기만(바꾸지 않음) | P1 |
| 닉네임 '변경' → 입력 시트 → 저장 | `PATCH /me` | `nickname`(2~12자, 한글·영문·숫자) | P1 |
| 로그아웃 | `POST /auth/logout` | | P1 |
| 탈퇴하기 → "정말 탈퇴하시겠습니까?" → 탈퇴 | `DELETE /me` | | P1 |

### U-10 관심 가맹점 (`U10-Favorites`, `U10-Empty`)

| 화면 요소·동작 | API | 보내는 값 / 쓰는 응답 | 우선 |
|---|---|---|---|
| 목록(최신 순, 거리) | `GET /me/favorites` | 커서 | P1 |
| 별 해제 | `DELETE /me/favorites/{id}` | 바로 그 줄을 뺌. 비면 "등록된 관심 가맹점이 없어요." | P1 |
| 카드 누름 | `GET /stores/{id}` | | P1 |

### U-11 찾을 수 없음 · E-01 연결 안 됨 · 공통 대화상자 (`U11-NotFound`, `E01-Offline`, `Dialogs`)

| 상황 | 형태 | 우선 |
|---|---|---|
| 폐업·숨김·없는 가게 | U-11 전체 화면 | P0 |
| 첫 화면 연결 안 됨 / 서버 오류·점검 | E-01 전체 화면 두 가지 · 고객센터 · 다시 시도 | P0 |
| 쓰던 중 연결 끊김 / 서버 오류 | 대화상자 [닫기] [다시 시도], 이전 화면 유지 | P0 |
| 429 / 결과 만료 / 링크 복사 | 토스트 | P0 / P0 / P1 |
| 로그인 필요 / 로그인 실패 / 500곳 초과 | 대화상자 | P1 |

## 2. 관리자 화면 (1차)

| 화면 | 요소·동작 | API | 우선 |
|---|---|---|---|
| A-01 로그인 | 로그인, 잠김 "24분 뒤" | `POST /admin/auth/login`(403 `ACCOUNT_LOCKED`, `details.lockedUntil`) | P0 |
| A-01 비밀번호 변경 | 새 비밀번호·확인 | `PUT /admin/me/password`(`mustChangePassword` 세션은 `newPassword`만). 바꾸기 전 다른 관리자 API는 403 `PASSWORD_CHANGE_REQUIRED` | P0 |
| 공통 틀 | 아이디 표시·로그아웃 | `GET /admin/me`, `POST /admin/auth/logout` | P0 |
| A-03 목록 | 검색·필터 6개, 50건씩, 상호(수정 값 반영) 가나다순 고정, 시장명·시장유형 열, "수정 N" 표시 | `GET /admin/stores`(정렬은 서버 고정, `marketType`·`editedCount`), 업종 선택지 `GET /meta` | P0 |
| A-04 상세 | 제목(`name`)·상태·`editedCount`, 필드 7줄(`fields`: 상호·품목·주소·좌표(보기만)·시장명·업종·카드·QR)의 원천·수정·마지막 수정, 숨김(`visibility`), 고칠 수 없는 값 | `GET /admin/stores/{id}` | P0 |
| A-04 수정 대화상자 | 원천 값·지금 수정 값·새 값·사유 → 저장 | `PUT /admin/stores/{id}/overrides/{field}` | P0 |
| A-04 해제 | | `DELETE /admin/stores/{id}/overrides/{field}` | P0 |
| A-04 숨김·보이기(사유) | | `PUT /admin/stores/{id}/visibility` | P0 |
| A-10 통계 | 지표·인기 검색어·결과 없는 검색어·문구 비율 | `GET /admin/stats/summary`·`/top-queries`·`/problem-queries`·`/messages` | P1 |
| A-10 CSV 내려받기 | 화면이 받은 표로 CSV(UTF-8 BOM) | — (API 없음) | P1 |

## 3. P2 관리자 화면 (목록만)

A-02 홈, A-05 주간 갱신, A-06 원천 변경 알림, A-07 브랜드 별칭, A-08 지명 제외, A-09 해석 미리보기, A-12 관리자 계정 → 예정 API는 `docs/api/API_RULES.md` 10·10-1절.

## 4. 결정 사항

| 항목 | 결정 | 반영 |
|---|---|---|
| 첫 비밀번호 변경 | 발급받은 아이디·임시 비밀번호로 로그인 → 새 비밀번호만 입력(로그인한 세션이 확인을 대신). 바꾸기 전 다른 기능은 서버가 막음 | FR-ADM-04, `changeAdminPassword`, `PASSWORD_CHANGE_REQUIRED` |
| A-03 정렬 | 상호 가나다순 고정. 페이지를 서버가 나누므로 서버가 정함, 정렬 파라미터 없음 | FR-STO-01, `listAdminStores` |
| 다른 지역 시트 | 지금 지역 포함 모두 거리순, 거리 km | FR-SRC-06, FR-MAP-10, 정책 4-2, `otherRegions` |
| 닉네임 변경 | P1 | FR-MBR-10, `updateMe` |
| 통계 CSV | API 없음, 화면에서 만듦 | FR-STA-03 |
| 공유 | 공유 글 형식, 전화 없으면 줄 뺌, 링크 미리보기 | FR-DTL-05 |
| 검색에서 돌아오기·내 위치 | 이전 조회 그대로 / 지도만 이동 | FR-BRW-06, FR-MAP-01 |
| 확대 안내 | 화면이 먼저 막고 이전 핀·시트 유지 | FR-MAP-05 |
| 로그인 뒤 별 | 돌아오면 자동으로 한 번 추가 | FR-DTL-06 |
| 최근 검색어 저장 | typed·recent·place_store·autocomplete만 | FR-MBR-07, `/search` |
| 상세 이벤트 queryId | history state로 | API_RULES 11절 |
| 핀 묶음 라벨 | 묶음 안 rank 가장 앞 | FR-MAP-07 |
| 로그인 상태 | 로그인 없이 열고, 회원 기능 누를 때만 로그인. 첫 화면 안내 문구 없음 | FR-MBR-12 |
| 관심 가맹점 해제 | 바로 목록에서 뺌, 빈 화면 | FR-MBR-08, `U10-Empty` |
| 회원 메뉴·탈퇴 확인·오류 | 그림 있음 | 7·8절, `Menu-Member`, `U09-*`, `E01-Offline`, `Dialogs`, `A04-EditDialog` |

### 그 밖의 결정

| 항목 | 결정 | 반영 |
|---|---|---|
| 위치 정보 이용 안내 | 첫 진입에 U-12 시트(동의 줄은 법무 결과에 따라) | FR-LOC-03, 정책 3-5, `/meta.policies.locationTerms` |
| 약관 동의 내역 메뉴 | 두지 않음(바꿀 선택 동의가 없음). 대신 메뉴에 이용약관·개인정보처리방침 링크 → 온누리상품권 홈페이지 문서 | FR-MBR-13, `/meta.policies` |
| E-01 | 연결 안 됨 / 서버 오류·점검 두 가지, 고객센터 1670-1600 | 7-1, 8절, `MAINTENANCE` |
| 내 위치 버튼 | 시트 위 12px, 시트와 함께 움직임 | FR-MAP-01 |
| 이메일 | 보기만 | FR-MBR-09 |
| 겹친 가게 목록 | 같은 좌표 핀·안 갈라지는 묶음을 누르면 "이 위치 가맹점 n곳" 목록(원천 66%가 좌표 공유) | FR-MAP-11, 정책 6-5, U-05b |

남은 확인: 위치기반서비스 약관 동의·비회원 동의 기록 필요 여부(법무, 요구사항 9절).
