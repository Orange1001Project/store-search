# 로컬 개발 준비

> 작성 2026-11-16 · 기준: [`ARCHITECTURE.md`](ARCHITECTURE.md), [`db/schema.sql`](db/schema.sql) v0.3.5, [`api/openapi.yaml`](api/openapi.yaml) v0.5
> 파일: [`infra/docker-compose.yml`](../infra/docker-compose.yml), [`infra/db/Dockerfile`](../infra/db/Dockerfile), [`infra/.env.example`](../infra/.env.example), [`embedding-server/`](../embedding-server/)
> **아직 실제로 띄워 본 적이 없다**(작성한 PC에 Docker가 없음). 처음 띄우는 사람이 막히는 곳을 8절에 적어 주세요.

## 0. 로컬에서 무엇이 어디서 도나

| 구성 요소 | 로컬에서 | 포트 |
|---|---|---|
| DB(PostgreSQL + PostGIS + pgvector) | Docker(`db`) | 127.0.0.1:5432 |
| 임베딩 서버 | Docker(`embedding`, `--profile ai`) | 127.0.0.1:8001 |
| API 서버(Spring Boot) | IDE에서 실행 | 8080 |
| 화면(React) | `npm run dev` | 5173 등 |
| Nginx | 로컬에선 안 씀(화면 개발 서버가 `/api`를 8080으로 넘김) | |

## 1. 환경 세팅 전에 확인할 것

설치를 시작하기 전에 아래를 먼저 정하거나 확인한다. ⛔는 막히면 진행이 안 되는 것이다.

| # | 확인할 것 | 왜 | 누가 |
|---|---|---|---|
| ⛔1 | **PC 관리자 권한, BIOS 가상화(VT-x) 켜짐** | WSL2 설치에 필요. 회사 PC는 IT 승인이 필요할 수 있다 | 본인·IT |
| ⛔2 | **Docker Desktop 라이선스** | 직원 250명 넘는 회사는 유료. 라이선스가 없으면 WSL 안에 Docker 엔진만 설치(2-2) | 본인·IT |
| ⛔3 | **회사 네트워크 프록시·보안 검사(SSL 가로채기)** | Docker 이미지·pip·Gradle/Maven·npm 내려받기가 막히거나 인증서 오류가 난다. 이 PC에서 PyPI 내려받기가 시간 초과된 적이 있다 | 본인·IT |
| ⛔4 | **임베딩 모델 파일**(`bge_m3_ft_mj_20261014_0743`, 약 2GB대) Drive 접근 | 없으면 임베딩 서버가 안 뜬다(DB만은 가능) | 모델 담당 |
| 5 | **코드 폴더 구조와 빌드 도구** | 예: `backend/`(Gradle 추천), `frontend/`, `embedding-server/`, `infra/`. 팀원과 먼저 맞춰야 서로 덮어쓰지 않는다 | 백엔드 |
| 6 | **PR #11 머지** | 요구사항·DB·API 기준 문서가 main에 있어야 개발 브랜치를 main에서 딴다 | 팀 |
| 7 | **원천 엑셀 보관 위치** | 11월 원천(약 22만 6천 행)에는 사업자번호가 들어 있다. git이 아니라 Drive 등에 두고 경로만 맞추는 것을 권장(9월 파일은 이미 저장소에 있음) | 팀 |
| 8 | **첫 적재·벡터 22만 개 생성 방법** | CPU로는 몇 시간. 한 사람이 GPU(Colab)로 한 번 만들고 DB 덤프를 공유하면 팀원은 복원만(6절) | 팀 |
| 9 | **평가 "정답 결과 파일"** | 자바 검색 이식 검증(NFR-QLT-01)용. 파이썬 평가 코드로 질의별 결과·순위를 뽑아 둔다 | 평가 담당 |
| 10 | 네이버 지도 Client ID(서비스 URL에 `http://localhost:5173` 등록) | 화면 지도 | 화면 담당 |
| 11 | 카카오·구글 개발용 앱(콜백 `http://localhost:8080/api/v1/auth/{provider}/callback`) | P1 로그인. 나중에 해도 됨 | 백엔드 |

## 2. 설치

### 2-1. 공통

| 도구 | 버전 | 확인 명령 |
|---|---|---|
| Git | 최신 | `git --version` |
| JDK | 21(Temurin 등) | `java -version` |
| Node.js | LTS(20 이상) | `node -v` |
| Python | 3.12(평가 코드·적재 스크립트) | `python --version` |

### 2-2. WSL2 + Docker

1. PowerShell(관리자)에서 `wsl --install` → 재부팅 → Ubuntu 사용자 만들기.
2. Docker 둘 중 하나
   - 라이선스가 있으면 Docker Desktop(WSL2 엔진 사용).
   - 없으면 WSL Ubuntu 안에 Docker 엔진 설치(docs.docker.com의 Ubuntu 설치 절차), `sudo usermod -aG docker $USER`.
3. WSL 메모리: `%UserProfile%\.wslconfig`에 아래를 두고 `wsl --shutdown`. DB(약 4~8GB) + 임베딩 서버(약 3~4GB)가 들어가야 한다.

```ini
[wsl2]
memory=16GB
```

4. 확인: `docker run --rm hello-world`

### 2-3. 줄바꿈

Windows에서 받은 `Dockerfile`·`.sh`·`.sql`이 CRLF면 컨테이너에서 실패할 수 있다. 저장소의 `.gitattributes`(`* text=auto eol=lf`)가 모든 텍스트 파일을 LF로 받게 한다. 이미 받은 저장소라면 `git rm --cached -r . && git reset --hard`로 다시 받는다(작업 중인 변경이 없을 때만).

## 3. 띄우기

```bash
cd infra
cp .env.example .env      # POSTGRES_PASSWORD 채우기, 모델 경로 확인
docker compose up -d db   # DB만
docker compose ps         # db가 healthy인지
```

- DB가 처음 뜰 때(볼륨이 비어 있을 때) `docs/db/schema.sql`이 실행돼 테이블 20개와 업종·결제 기본 데이터가 생긴다.
- 모델 파일을 `models/bge_m3_ft_mj_20261014_0743/`에 받은 뒤 임베딩 서버까지:

```bash
docker compose --profile ai up -d
docker compose logs -f embedding   # "Application startup complete"까지
```

## 4. DB 다루기

| 하고 싶은 것 | 방법 |
|---|---|
| 접속 | `docker compose exec db psql -U storesearch -d storesearch`, 또는 DBeaver 등으로 `localhost:5432` |
| 테이블 확인 | `\dt` → 20개(파티션 포함 더 보임), `SELECT * FROM category;` → 17행 |
| 처음부터 다시 | `docker compose down -v`(데이터 삭제) → `docker compose up -d db` |
| 테이블 구조 바꾸기 | **지금**: `docs/db/schema.sql`을 고치고 다시 처음부터. **백엔드가 생기면**: Flyway로 옮긴다 — `schema.sql`을 `V1__init.sql`로 넣고, 그 뒤 변경은 `V2__…sql`처럼 새 파일만 더한다(이미 실행한 파일은 고치지 않음). 그때 `docker-compose.yml`의 `schema.sql` 연결 줄을 지운다 |
| 설계 문서 맞추기 | 구조를 바꾸면 `DB_DESIGN.md` 3-2절·`DB_TABLES.md`·`erdcloud.sql`을 같이 다시 만든다 |
| 로그 파티션 | `schema.sql`에는 2026년 11월만 있다. 12월 이후 로그를 쓰려면 같은 모양으로 그달 파티션을 만든다(나중엔 스케줄러가 두 달 앞까지 만듦) |

**기본 데이터 넣기**(스크립트는 아직 없음, 백엔드와 같이 만든다)

| 데이터 | 원본 | 넣을 표 |
|---|---|---|
| 업종 17개, 결제 2개 | `schema.sql`(이미 들어감) | `category`, `payment_method` |
| 브랜드 별칭 | `configs/service/brand_alias_v1.csv` | `brand_alias` |
| 지명 사전 | `data/geo/gazetteer_v1.parquet` | `gazetteer`(`dict_version` = `gazetteer_v1`) |
| 확장어 캐시 | `results/service_pipeline/x8/expansions_Qwen2.5-14B-Instruct.csv` | `expansion_cache` |
| 지명 제외 목록 | 정책·해석 테스트의 목록을 파일로 정리 필요 | `place_exclusion` |
| 첫 관리자 계정 | 배포 스크립트(비밀번호 해시, `must_change_password` = 참) | `admin_user` |

## 5. 임베딩 서버 확인

```bash
curl -s localhost:8001/health
curl -s -X POST localhost:8001/embed -H "Content-Type: application/json" -d '{"texts":["둔산동 치킨"]}'
```

확인할 것 두 가지:

1. **속도**: 응답의 `elapsedMs`가 검색어 하나에 150ms 안인지(FR-FBK-01). 열 번쯤 불러 중간값을 본다. 넘으면 `EMBED_THREADS`를 늘려 보고, 그래도 넘으면 결과를 팀에 공유(아키텍처 8절).
2. **같은 벡터인지**: 평가 때 만든 벡터와 같은지. 같은 문장을 평가 코드(`SentenceTransformerEncoder`, 설정 `configs/models/bge_m3_ft_mj_20261014_0743.yaml`)로 만든 벡터와 코사인 유사도가 0.999 이상이어야 한다. 낮으면 라이브러리 버전(`embedding-server/requirements.txt`)을 모델 학습 때 버전에 맞춘다.

## 6. 가맹점 첫 적재(다음 단계)

갱신 명령(백엔드)이 생기면 11월 원천을 넣는다. 확인할 것:

- **기존 store_id 이어받기**: 9월 원천의 store_id를 새 같은 가게 판단(사업자번호 + 가맹점명 + 도로명 주소)으로 맞춰 이어받는다. 평가 정답이 이 번호에 걸려 있다.
- **벡터 22만 개**: 한 사람이 GPU로 만들어 넣고 `pg_dump -Fc`로 덤프 → Drive 공유 → 팀원은 `pg_restore`. 각자 몇 시간씩 돌리지 않는다.
- 적재 뒤 **실제 DB 속도 측정**(1km·10km·시도 전체 검색, `DB_DESIGN.md` 5-3절). 아직 한 번도 못 한 확인이다.

## 7. 개발 순서(권장)

1. 1절 확인 → 2절 설치
2. `docker compose up -d db`로 스키마가 실제로 도는지 확인(처음 하는 실제 실행)
3. 모델 받고 임베딩 서버 띄워 5절 확인
4. 기본 데이터 넣기 스크립트, 첫 적재(6절), DB 덤프 공유
5. 평가 "정답 결과 파일" → 자바 검색 이식과 비교 테스트
6. API(P0) → 화면

## 8. 막히면

| 증상 | 확인 |
|---|---|
| `docker compose up`에서 이미지 내려받기 실패·인증서 오류 | 회사 프록시·SSL 검사(1절 ⛔3). Docker에 프록시 설정, 회사 루트 인증서 등록 |
| `db`가 뜨다가 멈춤, 로그에 `schema.sql` 오류 | `docker compose logs db`. 스키마 오류면 고치고 `down -v` 뒤 다시 |
| `extension "vector" is not available` | `infra/db/Dockerfile`로 이미지가 만들어졌는지(`docker compose build db`) |
| 임베딩 서버가 `model not loaded` | `.env`의 `EMBED_MODEL_DIR`가 모델 폴더(안에 `config.json` 등)를 가리키는지 |
| 메모리 부족으로 컨테이너가 죽음 | `.wslconfig` 메모리, `DB_SHARED_BUFFERS`를 1GB로 |
| 5432 포트 사용 중 | `.env`의 `DB_PORT`를 5433 등으로 |
