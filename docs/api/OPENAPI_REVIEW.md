# openapi.yaml 개발 준비 작업 목록

> 2026-11-17 · 대상 `docs/api/openapi.yaml` (API 40개: P0 14 · P1 20 · P2 6)
> 목적: 개발자(Spring Boot 백엔드, React 화면)가 이 파일만 보고 개발을 시작할 수 있게 한다.
> 이 문서는 작업 목록이다. 다 고치면 문서를 지운다.

| 단계 | 할 일 | 상태 |
|---|---|---|
| 1 | Swagger로 띄워 보기, Spectral 검사, 문제 목록 | 끝 |
| 2 | 공통 부품 + P0 14개(예시·오류·헤더·설명) | **끝** |
| 3 | OpenAPI 3.0.3으로 바꾸기 → openapi-generator로 Spring 코드 시험 생성 | **끝**(컴파일은 아직) |
| 4 | P1 20개·P2 6개에 같은 작업 | **끝** |
| 5 | 백엔드 폴더 구조가 정해지면 옮기기 | |

## 보는 법·검사하는 법

Swagger로 보기: 저장소 맨 위 폴더에서 `python -m http.server 8081 --directory docs/api` → 브라우저 http://localhost:8081/swagger.html (yaml을 고치고 새로 고침하면 반영)


```bash
npx -y @stoplight/spectral-cli@6.15.0 lint docs/api/openapi.yaml --ruleset docs/api/.spectral.yaml
```

- 문법: openapi-spec-validator(3.0) 통과
- 예시: 모든 요청·응답 예시 558개를 그 스키마로 검사해 위반 0
- Spectral: 오류·경고 0
- 코드 생성: openapi-generator 7.10.0으로 오류 없이 생성, 이름 없는 클래스(`…Inner`, `…200Response`) 0

## 2단계에서 고친 것

| 항목 | 내용 |
|---|---|
| 응답 순서(D-1) | 모든 API: 2xx → 4xx 숫자순 → 5XX |
| 5XX(B-5) | `ServerError`(500 `INTERNAL_ERROR`, 503 `SERVICE_UNAVAILABLE`·`MAINTENANCE`, Retry-After)를 모든 API에 |
| 빠진 400·403(B-1~3) | 모든 API에 추가(CSRF 실패, 첫 비밀번호 변경 전, 잘못된 경로·쿼리 값) |
| 오류 코드(B-6) | `ErrorCode` enum(29개), `FieldError.reason` enum. `Error.code`가 이 목록을 가리킴. 공통 오류 응답마다 대표 예시 |
| 오류 줄 | P0 API 설명 끝에 "오류: 400 … · 404 …" — 그 API에서 실제로 나오는 코드 |
| 헤더(C-1·3) | P0: `Set-Cookie`(sid, admin_sid·csrf_token 발급·삭제), 503 Retry-After |
| 예시(A) | P0 14개 모두 성공 예시. `/search`는 4가지(지역 결과·같은 좌표 2곳, 10km 확장 ②, 상호 우선, 0곳), `/browse` 2가지, 요청 예시 추가 |
| 이름 붙인 스키마(F-2) | `AdminLoginRequest`, `AdminPasswordChangeRequest`, `StoreVisibilityRequest`, `AdminStoreListResponse` |
| 설명(E) | `info`는 짧은 소개 + 쿠키 인증 안내, 변경 이력은 없앰. `/search` 설명은 서버 동작만 남기고 화면 동작은 `API_RULES.md` 11절로. 버전 메모 삭제 |
| servers·contact(D-2·3) | 로컬 `http://localhost:8080/api/v1` 추가, 저장소 링크 |

## 2단계에서 새로 찾아 고친 것

| 문제 | 고침 |
|---|---|
| `interpretation.region.scope`가 `wide`·`narrow`인데 DB `gazetteer.scope`는 `area`·`point`(어디에도 wide·narrow 정의 없음) | API를 DB 값에 맞춤. `regionId`는 `gazetteer.entry_id`라고 적음 |
| 정책 설정 파일 문구의 치환 이름이 API와 다름: `{n_first}`·`{n_more}` ↔ `params.n`·`m`, name_first `{name}` ↔ `params.storeName` | `configs/service/search_policy_v1.yaml`을 API 이름으로(테스트 통과) |
| `/search`·`/browse`·`/page`가 sid 쿠키를 필수로 적었는데 sid는 서버가 첫 응답에서 발급 | `/meta`·`/stores`처럼 쿠키 없이도 부를 수 있게 |
| 관리자 로그아웃: 세션이 끝난 뒤 누르면 401인지 정해지지 않음 | 보통 서비스처럼 언제나 204. `API_RULES.md` 3절에 적음 |
| `GET /admin/me`는 첫 비밀번호 변경 전에도 되는 API인데 다른 관리자 API와 같이 403을 붙일 뻔함 | 예외 3개(`/admin/me`, 비밀번호 변경, 로그아웃)는 403 PASSWORD_CHANGE_REQUIRED 없음 |

## 정한 것

- 명세 먼저(2026-11-17): `openapi.yaml`이 원본, openapi-generator로 코드 생성. `API_RULES.md` 1절에 반영

## 4단계 — P1에서 고친 것

| 항목 | 내용 |
|---|---|
| 예시 | P1 20개 모두 성공 예시, 요청 예시(가입, 닉네임, 이벤트 묶음) |
| 오류 줄 | P1 API 설명 끝에 "오류:" 줄. 회원 401은 `AUTH_REQUIRED`(비회원)·`TOKEN_EXPIRED`(→ `/auth/refresh`)로 나눠 적음 |
| `Set-Cookie`·`Location` | 로그인 시작·콜백(302), 가입, 토큰 갱신, 로그아웃, 탈퇴 |
| 이름 붙인 스키마 | `SignupRequest`·`TermsAgreements`, `UpdateMeRequest`, `EventBatchRequest`·`EventBatchResponse`, `RecentSearchListResponse`, `FavoriteListResponse`, 통계 `StatsUnit`·`TopQueriesResponse`·`ProblemQueriesResponse`·`MessageStatsResponse`. 배열 안 객체는 `title`로 이름(`CategoryItem`, `PaymentMethodItem`, `OtherRegion`, `TermsItem`, `StatsPeriod`) |
| 설명 없던 API | `GET /me`(로그인 상태 확인에도 씀), 최근 검색어 전체 삭제, `/auth/terms` |
| 공통 오류 예시 | 401 `TOKEN_EXPIRED`·`SIGNUP_EXPIRED`·`REFRESH_REUSED`, 400 `TERMS_REQUIRED`, 409 `FAVORITE_LIMIT`·`ALREADY_MEMBER` |

새로 찾아 고친 것:

| 문제 | 고침 |
|---|---|
| 로그인 시작·콜백·이벤트 API가 sid 쿠키를 필수로 적음(sid는 서버가 발급) | 쿠키 없이도 부를 수 있게 |
| 가입 API에 409가 있는데 언제인지 설명 없음 | 409 `ALREADY_MEMBER`(그사이 다른 창에서 가입을 마침 → 다시 로그인) |
| 회원 로그아웃: 접근 토큰이 만료됐을 때 결과가 정해지지 않음 | 관리자와 같이 언제나 204 |
| 문제 검색어 `topMessage`가 null 포함 enum을 직접 적음 | `MessageCode`를 가리키고, 없으면 필드를 뺌 |
| YAML 한 줄 객체 안 쉼표 때문에 값이 잘려 키가 생김: 문구별 비율 `total` 설명, 필드 수정 요청 예시 `reason`(P0) | 따옴표로 묶음. 같은 문제가 더 있는지 전체를 검사해 0건 확인 |
| Spectral 규칙이 `$ref`를 펼쳐 세서 경고가 부풀려짐(30건 → 실제 0~1건) | 두 규칙에 `resolved: false` |

## 4단계 — P2에서 고친 것

| 항목 | 내용 |
|---|---|
| 예시 | 주간 갱신 API 6개 모두(업로드 받음, 승인 대기, 검사 실패, 승인, 취소, 지금 데이터 버전) |
| 오류 줄 | 6개 모두. 승인·취소의 409는 `INVALID_STATE` |
| 이름 | 업로드 요청 `RefreshJobUploadRequest`, 하위 객체 `CoordErrorStore`·`ValidationError` |
| 공통 오류 예시 | 400 `INVALID_FILE`, 409 `REFRESH_ALREADY_RUNNING`·`SAME_FILE_ALREADY_APPLIED`·`INVALID_STATE`, 413 `FILE_TOO_LARGE`, 422 `SOURCE_COLUMNS_MISMATCH` |
| 안 쓰는 부품 | `LocationValue` 삭제(P2 주소·좌표 수정 API를 만들 때 그 요청 모양을 새로 정함) |
| 설명 | `GET /admin/data-versions/active` |

## 남은 것 (미룸)

| 항목 | 언제 |
|---|---|
| 생성 코드 컴파일 | 백엔드 프로젝트를 만들 때(Maven·Spring 라이브러리 필요) |
| 경로·쿼리 enum 변환기 등록 | 백엔드 개발 때(아래 "백엔드가 알아 둘 것") |
| 한 줄 객체 안 쉼표 검사 | 지금은 손으로 돌리는 스크립트. 같은 실수가 3번 나와서 CI를 만들 때 검사에 넣는다 |

## 3단계 — 3.0.3 변환

| 3.1 문법 | 3.0.3으로 |
|---|---|
| `type: [string, 'null']` 26곳 | `type: string` + `nullable: true` |
| `oneOf: [$ref, type: 'null']` 8곳(`message`, `subMessage`, `mapFit`, `placeOnly`, 요청 `categoryCode`) | 3.0은 `$ref` 객체에 null을 허용하는 표준 방법이 없다. **값이 없으면 필드를 뺀다**로 바꿈(`API_RULES.md` 2절). 예시의 `null` 줄도 지움 |
| `const` 4곳(`limits`) | 값 하나짜리 `enum` |
| 스키마 안 `examples: [..]` 20곳 | `example` |
| `$ref` 옆 `description` 6곳(3.0에서 무시됨) | `allOf: [{ $ref }]`로 감싸 설명 유지 |

검사: 3.0 검증기 통과, 예시 위반 0, Spectral 오류 0. 3.0 검증기가 3.1 때 놓친 오류 1건을 찾음 — `Event.payload.previousQueryId`의 설명에 쉼표가 있어 YAML이 키 3개로 나눠 읽고 있었다(설명을 따옴표로 묶음).

### 코드 생성 시험 결과

openapi-generator 7.10.0(JDK 21), `-g spring --library spring-boot`, 옵션 `interfaceOnly=true, useSpringBoot3=true, useTags=true, openApiNullable=false, skipDefaultInterface=true, useBeanValidation=true`. 오류 없이 API 인터페이스 10개(태그별)·모델 78개가 나왔다.

| 확인한 것 | 결과 |
|---|---|
| `allOf` 한 개로 감싼 필드(`center`, `mapFit`, `message` 등) | 원래 타입(`LatLng`, `Bounds`, `Message`) 그대로 |
| nullable 필드 | `JsonNullable` 없이 일반 필드(`String marketName`) |
| 오류 코드 | `ErrorCode` enum, 경로 값 `OverrideField` enum, 쿼리 검사(`@Pattern`, `@Min`·`@Max`, `@Size`) 생성 |
| 검색 요청 `paymentCodes`(uniqueItems) | `Set<PaymentCode>` |

고친 것(명세):

| 문제 | 고침 |
|---|---|
| 오류 본문 스키마 이름 `Error` → Java 클래스 `Error`가 `java.lang.Error`와 겹침 | `ErrorResponse`로 이름 바꿈 |
| `StoreOverrideRequest.value`(`oneOf: string \| boolean`) → 아무것도 구현하지 않는 빈 인터페이스가 나와 쓸 수 없음 | 타입을 비워 `Object`로(서버가 field별로 검사) |
| `limits`의 값 하나짜리 enum → `QueryMaxLengthEnum` 같은 쓸모없는 enum 4개 | 그냥 `integer` + 예시 |

백엔드가 알아 둘 것:

- `interfaceOnly`로 만들면 문자열 → enum 변환기가 생기지 않는다. 경로·쿼리의 enum(`OverrideField`, `LifecycleStatus`, 통계 `view`·`intent`, `provider`)은 값이 소문자·camelCase라 Spring 기본 변환(`STORE_NAME`)과 다르다. 각 enum의 `fromValue`를 쓰는 `Converter`를 등록한다
- 인증 쿠키(`sid`, `admin_sid` 등)는 메서드 파라미터로 나오지 않는다(보안 설정에서 읽음)
- nullable enum(`intent`, `actionType`)은 Java enum에 null 상수가 없고 필드가 null이 된다 — 정상
- 이름 없는 본문은 `…200Response`, `…Inner` 같은 이름으로 나온다 → 모두 이름을 붙여 0개
- 컴파일은 아직 안 했다(Maven과 Spring 라이브러리를 받아야 함). 백엔드 프로젝트를 만들 때 같은 옵션으로 생성해 컴파일한다
