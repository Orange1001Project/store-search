# 화면설계

> 원본: claude.ai 디자인 캔버스 [가맹점 찾기 화면설계](https://claude.ai/artifact/PRLSNyFnSkW8ema6xMRv7M) (조직 안에서만 열림) · 이 폴더의 그림은 캔버스 버전 `1794552223-5d25`(2026-11-13)에서 만든 사본이다.
> 화면 ID와 기능은 [`docs/REQUIREMENTS.md`](../REQUIREMENTS.md) 7절(화면 목록·흐름), 우선순위는 1-4절을 따른다. 캔버스와 이 그림이 다르면 캔버스가 맞다.
> 그림은 캔버스의 화면 원본을 브라우저로 찍은 것이다. 모바일은 390×844, 관리자는 1440 너비. `[N]`·`[상호]`는 실제 데이터로 채울 자리다.

## 1. 사용자 화면 (모바일 웹)

| 화면 | 그림 |
|---|---|
| **U-01 메인 (처음 화면)**<br>`Main.dc.html` | <img src="screens/Main.png" width="260" alt="U-01 메인 (처음 화면)"> |
| **U-01 결제 칩 (여러 개 선택)**<br>`U01-Payment.dc.html` | <img src="screens/U01-Payment.png" width="260" alt="U-01 결제 칩 (여러 개 선택)"> |
| **U-01 지명만 입력**<br>`U01-PlaceOnly.dc.html` | <img src="screens/U01-PlaceOnly.png" width="260" alt="U-01 지명만 입력"> |
| **U-01 확대 안내 ⑩**<br>`U01-ZoomIn.dc.html` | <img src="screens/U01-ZoomIn.png" width="260" alt="U-01 확대 안내 ⑩"> |
| **U-01 화면 안 0곳 ④**<br>`U01-Empty.dc.html` | <img src="screens/U01-Empty.png" width="260" alt="U-01 화면 안 0곳 ④"> |
| **U-02 검색창 열림 (회원)**<br>`U02-Member.dc.html` | <img src="screens/U02-Member.png" width="260" alt="U-02 검색창 열림 (회원)"> |
| **U-02 검색창 열림 (비회원)**<br>`U02-Guest.dc.html` | <img src="screens/U02-Guest.png" width="260" alt="U-02 검색창 열림 (비회원)"> |
| **U-04 검색 결과 – 지도 (시트 중간)**<br>`U04-Map.dc.html` | <img src="screens/U04-Map.png" width="260" alt="U-04 검색 결과 – 지도 (시트 중간)"> |
| **U-03 검색 결과 – 목록 (시트 전체)**<br>`U03-List.dc.html` | <img src="screens/U03-List.png" width="260" alt="U-03 검색 결과 – 목록 (시트 전체)"> |
| **U-05 가게 요약 카드**<br>`U05-Card.dc.html` | <img src="screens/U05-Card.png" width="260" alt="U-05 가게 요약 카드"> |
| **U-04 같은 이름 지명 – 다른 ○○**<br>`U04-OtherRegion.dc.html` | <img src="screens/U04-OtherRegion.png" width="260" alt="U-04 같은 이름 지명 – 다른 ○○"> |
| **U-06 가게 상세**<br>`U06-Detail.dc.html` | <img src="screens/U06-Detail.png" width="260" alt="U-06 가게 상세"> |
| **U-11 찾을 수 없음**<br>`U11-NotFound.dc.html` | <img src="screens/U11-NotFound.png" width="260" alt="U-11 찾을 수 없음"> |
| **메뉴 (☰, 비회원)**<br>`Menu.dc.html` | <img src="screens/Menu.png" width="260" alt="메뉴 (☰, 비회원)"> |
| **U-07 로그인**<br>`U07-Login.dc.html` | <img src="screens/U07-Login.png" width="260" alt="U-07 로그인"> |
| **U-08 가입 동의**<br>`U08-Terms.dc.html` | <img src="screens/U08-Terms.png" width="260" alt="U-08 가입 동의"> |
| **U-09 내 정보**<br>`U09-MyInfo.dc.html` | <img src="screens/U09-MyInfo.png" width="260" alt="U-09 내 정보"> |
| **U-10 관심 가맹점**<br>`U10-Favorites.dc.html` | <img src="screens/U10-Favorites.png" width="260" alt="U-10 관심 가맹점"> |

## 2. 관리자 화면 (1차)

1차 관리자 웹은 로그인(A-01), 가맹점 목록·상세·수정(A-03·A-04), 통계(A-10)만 둔다(요구사항 v0.10).

| 화면 | 그림 |
|---|---|
| **A-01 로그인 (잠김 안내)**<br>`A01-Login.dc.html` | <img src="screens/A01-Login.png" width="520" alt="A-01 로그인 (잠김 안내)"> |
| **A-01 첫 로그인 비밀번호 변경**<br>`A01-Password.dc.html` | <img src="screens/A01-Password.png" width="520" alt="A-01 첫 로그인 비밀번호 변경"> |
| **A-03 가맹점 목록**<br>`A03-Stores.dc.html` | <img src="screens/A03-Stores.png" width="520" alt="A-03 가맹점 목록"> |
| **A-04 가맹점 상세·수정**<br>`A04-StoreDetail.dc.html` | <img src="screens/A04-StoreDetail.png" width="520" alt="A-04 가맹점 상세·수정"> |
| **A-10 통계**<br>`A10-Stats.dc.html` | <img src="screens/A10-Stats.png" width="520" alt="A-10 통계"> |

## 3. 출시 뒤(P2) 관리자 화면

1차에는 서버 스크립트·DB 직접 작업으로 대신한다. 화면은 참고용이다.

| 화면 | 그림 |
|---|---|
| **A-02 홈**<br>`A02-Home.dc.html` | <img src="screens/A02-Home.png" width="520" alt="A-02 홈"> |
| **A-05 주간 갱신 – 미리보기·승인**<br>`A05-Refresh.dc.html` | <img src="screens/A05-Refresh.png" width="520" alt="A-05 주간 갱신 – 미리보기·승인"> |
| **A-05 주간 갱신 – 진행**<br>`A05-RefreshProgress.dc.html` | <img src="screens/A05-RefreshProgress.png" width="520" alt="A-05 주간 갱신 – 진행"> |
| **A-06 원천 변경 알림**<br>`A06-SourceAlerts.dc.html` | <img src="screens/A06-SourceAlerts.png" width="520" alt="A-06 원천 변경 알림"> |
| **A-07 브랜드 별칭**<br>`A07-BrandAlias.dc.html` | <img src="screens/A07-BrandAlias.png" width="520" alt="A-07 브랜드 별칭"> |
| **A-08 지명 제외 목록**<br>`A08-PlaceExclusion.dc.html` | <img src="screens/A08-PlaceExclusion.png" width="520" alt="A-08 지명 제외 목록"> |
| **A-09 해석 미리보기**<br>`A09-ParsePreview.dc.html` | <img src="screens/A09-ParsePreview.png" width="520" alt="A-09 해석 미리보기"> |
| **A-12 관리자 계정**<br>`A12-Accounts.dc.html` | <img src="screens/A12-Accounts.png" width="520" alt="A-12 관리자 계정"> |

## 4. 그림 다시 만들기

캔버스를 고친 뒤 이 폴더를 갱신할 때는 캔버스의 `project/*.dc.html`을 내려받아 `<script src="./support.js"></script>` 줄을 빼고, 헤드리스 Chrome으로 위 크기대로 찍는다(`--headless=new --window-size=W,H --screenshot`, 모바일은 `--force-device-scale-factor=2`).
