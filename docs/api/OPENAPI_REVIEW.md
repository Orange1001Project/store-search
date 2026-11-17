# openapi.yaml 개발 준비 상태

> 대상 `docs/api/openapi.yaml` (OpenAPI 3.0.3, API 40개: P0 14 · P1 20 · P2 6)
> 목적: 개발자(Spring Boot 백엔드, React 화면)가 이 파일만 보고 개발을 시작할 수 있게 한다.
> 이 문서는 작업 목록이다. 남은 것을 다 처리하면 지운다.

| 단계 | 할 일 | 상태 |
|---|---|---|
| 1 | Swagger로 띄워 보기, Spectral 검사, 문제 목록 | 끝 |
| 2 | 공통 부품 + P0 14개(예시·오류·헤더·설명) | 끝 |
| 3 | OpenAPI 3.0.3으로 바꾸기 → openapi-generator로 Spring 코드 시험 생성 | 끝(컴파일은 아직) |
| 4 | P1 20개·P2 6개에 같은 작업, 문서 전체 교차 점검 | 끝 |
| 5 | 백엔드 저장소로 옮기기 | |

## 보는 법·검사하는 법

Swagger로 보기: 저장소 맨 위 폴더에서 `python -m http.server 8081 --directory docs/api` → 브라우저 http://localhost:8081/swagger.html (yaml을 고치고 새로 고침하면 반영)

```bash
npx -y @stoplight/spectral-cli@6.15.0 lint docs/api/openapi.yaml --ruleset docs/api/.spectral.yaml
```

지금 결과:

- 문법: openapi-spec-validator(3.0) 통과
- 예시: 모든 요청·응답 예시를 그 스키마로 검사해 위반 0
- Spectral: 오류·경고 0
- 코드 생성: openapi-generator 7.10.0으로 오류 없이 생성, 이름 없는 클래스(`…Inner`, `…200Response`) 0
- YAML 한 줄 객체(`{ … }`) 안 쉼표로 값이 잘려 키가 생긴 곳 0

## 정한 것

- **명세 먼저**: `openapi.yaml`이 원본, openapi-generator로 코드 생성(`API_RULES.md` 1절).
- **3.0.3**: Spring 코드 생성기가 안정적으로 지원하는 버전. 3.0에는 `$ref` 객체에 null을 허용하는 표준 방법이 없어 `message`·`subMessage`·`mapFit`·`placeOnly`·요청 `categoryCode`는 **값이 없으면 필드를 뺀다**. 나머지 `nullable: true` 필드는 늘 오고 값이 `null`이다(`required`에 들어 있음, `API_RULES.md` 2절).
- **인증 쿠키**: 회원 `access_token` 쿠키는 14일(토큰 자체는 30분)이라 만료되면 401 `TOKEN_EXPIRED` → `/auth/refresh` 한 번. CSRF 쿠키는 회원 `csrf_token`(14일)과 관리자 `admin_csrf_token`으로 나눈다(`API_RULES.md` 5절).

## 코드 생성 시험

openapi-generator 7.10.0(JDK 21), `-g spring --library spring-boot`, 옵션 `interfaceOnly=true, useSpringBoot3=true, useTags=true, openApiNullable=false, skipDefaultInterface=true, useBeanValidation=true`. API 인터페이스 10개(태그별)·모델 77개.

| 확인한 것 | 결과 |
|---|---|
| `allOf` 한 개로 감싼 필드(`center`, `mapFit`, `message` 등) | 원래 타입(`LatLng`, `Bounds`, `Message`) 그대로 |
| nullable 필드 | `JsonNullable` 없이 일반 필드(`String marketName`) |
| 소수 필드(좌표, 비율) | `format: double`이라 `Double`(`BigDecimal` 아님) |
| 오류 코드 | `ErrorCode` enum, 경로 값 `OverrideField` enum, 쿼리 검사(`@Pattern`, `@Min`·`@Max`, `@Size`) |
| 검색 요청 `paymentCodes`(uniqueItems) | `Set<PaymentCode>` |
| 갱신 파일 올리기 | `MultipartFile` |

백엔드가 알아 둘 것:

- `interfaceOnly`로 만들면 문자열 → enum 변환기가 생기지 않는다. 경로·쿼리의 enum(`OverrideField`, `LifecycleStatus`, 통계 `view`·`intent`, `provider`)은 값이 소문자·camelCase라 Spring 기본 변환(`STORE_NAME`)과 다르다. 각 enum의 `fromValue`를 쓰는 `Converter`를 등록한다.
- 인증 쿠키(`sid`, `access_token`, `admin_sid` 등)는 메서드 파라미터로 나오지 않는다(보안 설정에서 읽음).
- nullable enum(`intent`, `actionType`)은 Java enum에 null 상수가 없고 필드가 null이 된다 — 정상.
- `StoreOverrideRequest.value`, `FieldValue.sourceValue`·`overrideValue`는 field에 따라 모양이 달라 `Object`로 나온다. 서버가 field별로 검사한다.
- 생성 이름이 어색한 곳(동작에는 문제 없음): 건수 필드 `new` → `_new`, `radiusStage` 값 `1km`·`10km` → `_1KM`·`_10KM`, 이름 없는 하위 객체(`preview`, `counts`, `lastEdit` 등)는 `RefreshJobPreview`처럼 부모 이름이 붙는다.

## 남은 것 (미룸)

| 항목 | 언제 |
|---|---|
| 생성 코드 컴파일 | 백엔드 프로젝트를 만들 때(Maven·Spring 라이브러리 필요) |
| 경로·쿼리 enum 변환기 등록 | 백엔드 개발 때(위 "백엔드가 알아 둘 것") |
| 한 줄 객체 안 쉼표 검사, 예시 검사 | 지금은 손으로 돌리는 스크립트. CI를 만들 때 Spectral과 함께 넣는다 |
| 응답마다 `X-Trace-Id` 헤더 표기 | 지금은 `info`와 공통 오류 응답·검색 응답에만 적음. 모든 응답 공통이라 springdoc·필터로 붙이면 됨 |
