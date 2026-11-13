-- 가맹점 검색 서비스 DB 스키마 (초안 v0.3, 2026-11-13) — 필수 테이블 19개
-- 대상: PostgreSQL 16 + PostGIS 3.4 + pgvector 0.8 이상
-- 설계 설명: docs/DB_DESIGN.md · 입력: docs/REQUIREMENTS.md 4절(DR-01~19)
--
-- 규칙
--  * 시각은 모두 timestamptz(UTC 저장). 하루·한 달 경계는 한국 시간(Asia/Seoul) 기준.
--  * 상태값은 PostgreSQL ENUM 대신 varchar + CHECK(JPA @Enumerated(STRING)과 맞고, 값 추가가 쉬움).
--  * 생성 순서는 외래 키 의존 순서: 확장 → 관리자 → 참조 → 버전·갱신 → 가맹점 → 스냅샷 → 회원 → 로그·통계.

-- =====================================================================
-- 0. 확장
-- =====================================================================
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

-- =====================================================================
-- 1. 관리자 (DR-15)
-- =====================================================================
CREATE TABLE admin_user (
    admin_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    login_id              varchar(30)  NOT NULL UNIQUE,
    password_hash         varchar(100) NOT NULL,              -- bcrypt
    status                varchar(10)  NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    must_change_password  boolean      NOT NULL DEFAULT true, -- 첫 로그인 때 비밀번호 변경
    failed_login_count    smallint     NOT NULL DEFAULT 0 CHECK (failed_login_count >= 0),
    locked_until          timestamptz,                        -- 실패가 쌓이면 이 시각까지 잠금
    last_login_at         timestamptz,
    created_at            timestamptz  NOT NULL DEFAULT now()
);

-- =====================================================================
-- 2. 참조 데이터 (DR-07~12)
-- 검색 서버는 1분마다 표마다 count(*)·max(updated_at)를 읽어, 바뀐 표만 통째로 다시 메모리에 올린다.
-- =====================================================================
CREATE TABLE category (                                          -- 업종 칩 17개 = 공식 온누리 중분류(configs/category/taxonomy_v1.yaml)
    category_code  varchar(20) PRIMARY KEY,                      -- K001 식품·마트 … K017 생활서비스
    name           varchar(20) NOT NULL UNIQUE,
    sort_order     smallint    NOT NULL,
    is_active      boolean     NOT NULL DEFAULT true,
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE payment_method (                                    -- 결제 칩: card, qr
    payment_code   varchar(10) PRIMARY KEY,
    name           varchar(20) NOT NULL UNIQUE,                  -- 카드결제, QR결제
    source_column  varchar(30),                                  -- store의 원천 열(card_payment, qr_payment). 데이터 없으면 NULL
    sort_order     smallint    NOT NULL,
    is_visible     boolean     NOT NULL DEFAULT true,            -- 칩 표시 여부
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE brand_alias (                                       -- 브랜드 별칭(대표 이름 1 : 표기 N을 한 표에)
    alias_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_name  varchar(40) NOT NULL,                        -- 대표 이름(GS25)
    alias_text      varchar(40) NOT NULL,                        -- 다른 표기(지에스25)
    alias_norm      varchar(40) NOT NULL UNIQUE,                 -- 정규화(소문자·공백 제거). 한 표기는 한 브랜드에만
    updated_by      bigint REFERENCES admin_user (admin_id),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_brand_alias_canonical ON brand_alias (canonical_name);

CREATE TABLE gazetteer (                                         -- 지명 사전(사전을 바꿀 때는 표를 통째로 교체)
    entry_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            varchar(50) NOT NULL,                        -- 신촌, 대전광역시 중구, 구리전통시장
    name_norm       varchar(50) NOT NULL,
    kind            varchar(10) NOT NULL
                    CHECK (kind IN ('sido', 'city', 'sigungu', 'eupmyeon', 'dong', 'hdong', 'station', 'market')),
    scope           varchar(5)  NOT NULL CHECK (scope IN ('area', 'point')),   -- area = 지역 전체, point = 1km 원
    code_prefix     varchar(10),                                 -- 법정동 코드 앞자리(2·5·8자리), area일 때
    center          geography(Point, 4326) NOT NULL,             -- 지명 중심(검색 중심으로 씀)
    evidence_count  smallint,                                    -- 같은 이름 지명 고르기용(근거 수)
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_gazetteer_name ON gazetteer (name_norm);

CREATE TABLE place_exclusion (                                   -- 지명으로 읽지 않을 말(오케이 정형외과의 '오케이')
    term_norm   varchar(50) PRIMARY KEY,
    term        varchar(50) NOT NULL,
    reason      varchar(200) NOT NULL,
    updated_by  bigint REFERENCES admin_user (admin_id),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE expansion_cache (                                   -- 업종 검색어 LLM 확장어
    query_norm  varchar(100) PRIMARY KEY,                        -- 정규화한 검색어 전체(최대 50자)
    keywords    text[]       NOT NULL CHECK (cardinality(keywords) > 0),   -- 고기 → {삼겹살, 갈비, 정육}
    model       varchar(60)  NOT NULL,                           -- 만든 LLM
    updated_at  timestamptz  NOT NULL DEFAULT now()
);

-- =====================================================================
-- 3. 데이터 버전·주간 갱신 (DR-05, DR-06)
-- =====================================================================
CREATE TABLE data_version (
    version_id      smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    version_name    varchar(20) NOT NULL UNIQUE,                 -- 2026-11-16, 같은 날 두 번째는 2026-11-16.2 (한국 날짜)
    status          varchar(10) NOT NULL DEFAULT 'building'
                    CHECK (status IN ('building', 'active', 'retired', 'failed')),
    embedding_model varchar(60) NOT NULL,                        -- bge_m3_ft_mj_20261014_0743
    n_total         integer,                                     -- 이번 버전 결과(관리자 화면 표시)
    n_new           integer,
    n_changed       integer,
    n_pending       integer,                                     -- 이번에 확인 대기가 된 수
    n_closed        integer,
    n_coord_error   integer,
    created_at      timestamptz NOT NULL DEFAULT now(),
    activated_at    timestamptz
);
-- 활성 버전은 언제나 하나. 검색 서버는 이 행을 읽어 들고 있다가 바뀌면 새 버전으로 갈아탄다
CREATE UNIQUE INDEX uq_data_version_one_active ON data_version (status) WHERE status = 'active';

CREATE TABLE refresh_job (                                       -- 주간 갱신 작업 1건 = 원천 파일 1개
    job_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    file_name           varchar(200) NOT NULL,                   -- 올린 엑셀 이름
    file_path           varchar(500) NOT NULL,                   -- 파일 저장소 위치(파일 본문은 DB에 두지 않음)
    file_sha256         char(64)     NOT NULL,                   -- 파일 지문
    file_size           bigint       NOT NULL CHECK (file_size > 0 AND file_size <= 104857600),   -- 100MB 이하
    target_version_id   smallint     REFERENCES data_version (version_id),   -- 이 작업이 만드는 버전
    status              varchar(20)  NOT NULL DEFAULT 'uploaded'
                        CHECK (status IN ('uploaded', 'validating', 'diffing', 'awaiting_approval', 'approved',
                                          'embedding', 'switching', 'succeeded', 'failed', 'cancelled')),
    progress_pct        smallint     NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
    needs_approval      boolean      NOT NULL DEFAULT false,     -- 사라지는 가게가 기준 %를 넘음(FR-UPD-05)
    preview             jsonb,                                   -- 건수, 좌표 오류·충돌 목록
    error_message       text,
    edits_applied_until timestamptz,                             -- 이 시각까지의 관리자 수정을 새 버전에 반영함(FR-UPD-07)
    started_by          bigint       NOT NULL REFERENCES admin_user (admin_id),
    approved_by         bigint       REFERENCES admin_user (admin_id),
    created_at          timestamptz  NOT NULL DEFAULT now(),
    finished_at         timestamptz
);
-- 진행 중인 갱신은 하나만(FR-UPD-08)
CREATE UNIQUE INDEX uq_refresh_job_one_running ON refresh_job ((true))
    WHERE status NOT IN ('succeeded', 'failed', 'cancelled');
-- 같은 파일을 두 번 반영하지 않음(실패한 파일은 다시 올릴 수 있음)
CREATE UNIQUE INDEX uq_refresh_job_file_done ON refresh_job (file_sha256) WHERE status = 'succeeded';

-- =====================================================================
-- 4. 가맹점 (DR-01~03)
-- =====================================================================
CREATE TABLE store (                                             -- 가게 1곳 = 1행: 원천 값 + 현재 상태
    store_id            uuid        PRIMARY KEY,                 -- 기존 UUID 유지(평가 정답과 연결), 새 가게만 gen_random_uuid()
    fingerprint         char(64)    NOT NULL UNIQUE,             -- sha256(사업자번호+가맹점명+주소), 원천 값으로
    -- 원천 값(매주 원천 파일로 덮어씀. 관리자가 고친 값은 store_override에)
    store_name          varchar(100) NOT NULL,
    business_no         varchar(20)  NOT NULL,                   -- 문자열(앞자리 0)
    merchant_no         varchar(20),                             -- 결측·전화번호 형태 섞임, 식별자로 안 씀
    address             varchar(200) NOT NULL,
    latitude            numeric(9,6),                            -- 원천 그대로(0 좌표 포함). 2026-11-13 파일부터 원천 열 이름은 Y좌표
    longitude           numeric(9,6),                            -- 원천 X좌표
    legal_dong_code     varchar(10),                             -- 문자열
    market_type         varchar(30),
    market_name         varchar(100),
    items               text,
    ksic_code           varchar(5),                              -- 원천 표준산업분류코드(5자리 문자열, 미분류 00000)
    onnuri_category     varchar(4),                              -- 원천 온누리중분류(K001~K017). 비면 ksic_code로 보충
    card_payment        boolean,                                 -- 원천 카드결제, 빈 값 NULL
    qr_payment          boolean,                                 -- 원천 QR결제(이전 파일 열 이름은 모바일결제여부)
    source_conflict     boolean     NOT NULL DEFAULT false,      -- 같은 가게 원천 행끼리 좌표·품목·결제가 다름(결제는 하나라도 Y면 Y)
    -- 상태
    lifecycle_status    varchar(10) NOT NULL DEFAULT 'active'
                        CHECK (lifecycle_status IN ('active', 'pending', 'closed')),
    missing_count       smallint    NOT NULL DEFAULT 0 CHECK (missing_count >= 0),   -- 연속으로 원천에 없던 주 수
    status_changed_at   timestamptz NOT NULL DEFAULT now(),      -- 상태가 마지막으로 바뀐 시각
    is_hidden           boolean     NOT NULL DEFAULT false,
    visibility_reason   varchar(200),                            -- 마지막 숨김·해제 사유(둘 다 필수, FR-STO-07)
    visibility_changed_by bigint    REFERENCES admin_user (admin_id),   -- 마지막으로 숨기거나 해제한 관리자
    visibility_changed_at timestamptz,                           -- 마지막으로 숨기거나 해제한 시각. 한 번도 안 바꿨으면 NULL
    coord_error         boolean     NOT NULL DEFAULT false,      -- 수정 값까지 반영한 좌표가 0·국내 밖·충돌
    last_seen_version_id smallint   NOT NULL REFERENCES data_version (version_id),   -- 원천에서 마지막으로 본 버전
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_store_visibility CHECK (
        (NOT is_hidden OR visibility_changed_at IS NOT NULL)
        AND (visibility_changed_at IS NULL OR (visibility_reason IS NOT NULL AND visibility_changed_by IS NOT NULL))),
    CONSTRAINT ck_store_closed_missing CHECK (lifecycle_status <> 'closed' OR missing_count >= 2)
);
CREATE INDEX ix_store_business_no ON store (business_no);
CREATE INDEX ix_store_name ON store (store_name varchar_pattern_ops);   -- 관리자 상호 앞부분 검색

CREATE TABLE store_override (                                    -- 관리자 수정 값(가게 × 필드, 해제하면 행 삭제)
    store_id             uuid        NOT NULL REFERENCES store (store_id),
    field_name           varchar(20) NOT NULL
                         CHECK (field_name IN ('store_name', 'items', 'location', 'market_name',
                                               'payment_card', 'payment_qr', 'category')),
    override_value       jsonb       NOT NULL,                   -- location = {lat, lon, legal_dong_code, address}
    source_value_at_edit jsonb,                                  -- 수정할 때의 원천 값
    source_changed       boolean     NOT NULL DEFAULT false,     -- 그 뒤 원천 값이 바뀜 → 관리자 화면에 알림(FR-STO-08)
    new_source_value     jsonb,                                  -- 바뀐 원천 값
    reason               varchar(200) NOT NULL,
    admin_id             bigint      NOT NULL REFERENCES admin_user (admin_id),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (store_id, field_name)
);
CREATE INDEX ix_store_override_updated ON store_override (updated_at);   -- 전환 직전 재적용 대상 찾기
CREATE INDEX ix_store_override_alert ON store_override (updated_at) WHERE source_changed;   -- 알림 목록

-- =====================================================================
-- 5. 검색 스냅샷 (DR-04·07·11) — 데이터 버전마다 파티션 하나, 검색은 이 표만 읽는다
-- 외래 키를 두지 않는다: 외래 키가 있으면 파티션을 붙일 때 21만 행을 다시 검사해 전환이 느려진다.
-- 갱신 작업이 store·store_override로 만들어 넣고, 전환 전에 검증 쿼리로 확인한다.
-- 지점 접미사(DR-11)는 검색 서버가 이 표의 상호에서 계산해 메모리에 둔다(표 없음).
-- =====================================================================
CREATE TABLE store_snapshot (
    version_id        smallint     NOT NULL,                     -- data_version.version_id
    store_id          uuid         NOT NULL,                     -- store.store_id
    store_name        varchar(100) NOT NULL,                     -- 원천 + 관리자 수정 = 유효 값
    items             text,
    address           varchar(200) NOT NULL,
    address_short     varchar(100),                              -- 시군구 + 도로명(결과 카드)
    legal_dong_code   varchar(10)  NOT NULL,
    market_type       varchar(30),                               -- 시장유형(결과 카드·상세, FR-LST-03)
    market_name       varchar(100),
    geom             geography(Point, 4326) NOT NULL,
    category_codes    varchar(20)[] NOT NULL DEFAULT '{}',       -- 업종 칩 거르기용 목록(지금은 공식 업종 하나)
    primary_category  varchar(20),                               -- 대표 업종(category.category_code, K001~K017)
    category_source   varchar(10) CHECK (category_source IN ('official', 'ksic', 'admin')),   -- 업종 근거: 원천 온누리중분류 / 산업분류로 보충 / 관리자 수정(DR-07)
    subcategory       varchar(40),                               -- 세부 업종(표준산업분류 세세분류명)
    payment_codes     varchar(10)[] NOT NULL DEFAULT '{}',       -- {card, qr}
    searchable        boolean      NOT NULL,                     -- 영업중 · 숨김 아님 · 좌표 오류 아님
    doc_text          varchar(300) NOT NULL,                     -- 가맹점명: {상호} / 취급품목: {품목}
    embedding         vector(1024) NOT NULL,                     -- fp32, L2 정규화
    PRIMARY KEY (version_id, store_id)
) PARTITION BY LIST (version_id);

-- =====================================================================
-- 6. 회원 (DR-13, DR-14, DR-19)
-- 갱신 토큰(FR-MBR-06, 14일)은 DB 표 대신 세션 저장소(Redis 등)에 해시로 두고 만료되면 자동 삭제한다.
-- =====================================================================
-- 탈퇴는 행을 지우지 않고 status = 'withdrawn'으로 바꾼다(가입·탈퇴 시각을 남기려고, DR-13).
-- 같은 트랜잭션에서 닉네임·이메일·마지막 로그인을 비우고, 로그인 수단·최근 검색어·즐겨찾기는 지운다(P9-4).
-- 남는 것은 회원 번호·시각·약관 버전뿐이라 누구인지 알 수 없다. 같은 소셜 계정으로 다시 가입하면 새 회원.
CREATE TABLE member (
    member_id        uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    status           varchar(10) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'withdrawn')),
    nickname         varchar(12),                                -- 중복 허용, 없으면 '회원1234'. 탈퇴하면 NULL
    email            varchar(254),                               -- 선택 동의. 탈퇴하면 NULL
    terms_version    varchar(20) NOT NULL,                       -- 동의한 약관 묶음 버전(이용약관·개인정보·만 14세)
    terms_agreed_at  timestamptz NOT NULL,                       -- 약관 동의 시각(DR-19)
    created_at       timestamptz NOT NULL DEFAULT now(),         -- 가입 시각
    last_login_at    timestamptz,                                -- 탈퇴하면 NULL
    withdrawn_at     timestamptz,                                -- 탈퇴 시각
    CONSTRAINT ck_member_nickname_len CHECK (nickname IS NULL OR char_length(nickname) BETWEEN 2 AND 12),
    CONSTRAINT ck_member_status CHECK (
        (status = 'active'    AND nickname IS NOT NULL AND withdrawn_at IS NULL)
     OR (status = 'withdrawn' AND withdrawn_at IS NOT NULL
                              AND nickname IS NULL AND email IS NULL AND last_login_at IS NULL))
);

CREATE TABLE member_auth (                                       -- 로그인 수단(회원 1 : N)
    auth_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id         uuid         NOT NULL REFERENCES member (member_id) ON DELETE CASCADE,
    provider          varchar(10)  NOT NULL CHECK (provider IN ('kakao', 'google')),
    provider_user_id  varchar(255) NOT NULL,                     -- 카카오·구글이 준 회원 번호
    created_at        timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT uq_member_auth_provider_user UNIQUE (provider, provider_user_id),
    CONSTRAINT uq_member_auth_member_provider UNIQUE (member_id, provider)
);

CREATE TABLE member_recent_search (                              -- 최근 검색어(회원당 10개, 좌표·query_id 없음)
    member_id    uuid         NOT NULL REFERENCES member (member_id) ON DELETE CASCADE,
    query_norm   varchar(100) NOT NULL,                          -- 같은 말은 한 줄(다시 검색하면 시각만 갱신)
    query_text   varchar(50)  NOT NULL,                          -- 마지막 원문
    searched_at  timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (member_id, query_norm)
);
CREATE INDEX ix_member_recent_search_time ON member_recent_search (member_id, searched_at DESC);

CREATE TABLE member_favorite (                                   -- 즐겨찾기(회원당 500곳)
    member_id   uuid        NOT NULL REFERENCES member (member_id) ON DELETE CASCADE,
    store_id    uuid        NOT NULL REFERENCES store (store_id),
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (member_id, store_id)
);
CREATE INDEX ix_member_favorite_list  ON member_favorite (member_id, created_at DESC);
CREATE INDEX ix_member_favorite_store ON member_favorite (store_id);   -- 폐업·숨김 때 일괄 삭제

-- =====================================================================
-- 7. 로그 (DR-16) — 한국 시간 월 단위 파티션, 1년 뒤 파티션째 삭제. 외래 키 없음. 회원 ID 없음
-- =====================================================================
CREATE TABLE search_log (                                        -- 중심 로그: 검색 결과 한 페이지 = 1행
    query_id           uuid        NOT NULL,                     -- 검색 1건(다음 페이지도 같은 번호)
    page               smallint    NOT NULL DEFAULT 1 CHECK (page >= 1),
    logged_at          timestamptz NOT NULL,                     -- 서버 시각
    session_id         uuid        NOT NULL,                     -- 30분 쉬면 새 세션
    schema_version     smallint    NOT NULL,                     -- 로그 형식 버전
    app_version        varchar(20) NOT NULL,
    pipeline_version   varchar(20) NOT NULL,                     -- 검색 정책·계수 버전
    corpus_version_id  smallint    NOT NULL,                     -- 검색한 데이터 버전(FK 없음)
    query_text         varchar(50),                              -- 검색어 없는 조회는 NULL
    input_type         varchar(15) NOT NULL
                       CHECK (input_type IN ('typed', 'recent', 'autocomplete', 'chip', 'browse', 'place')),
    category_code      varchar(20),                              -- 고른 업종 칩
    payment_codes      varchar(10)[] NOT NULL DEFAULT '{}',      -- 고른 결제 칩(여러 개, 빈 목록 = 전체)
    view               varchar(4)  NOT NULL CHECK (view IN ('list', 'map')),
    location_source    varchar(15) NOT NULL
                       CHECK (location_source IN ('query_region', 'ui_region', 'map_viewport', 'gps', 'default')),
    user_cell          varchar(20),                              -- 사용자 위치 100m 격자(원 좌표 없음)
    viewport_cells     varchar(50),                              -- 지도 화면 남서·북동 100m 격자
    parsed             jsonb,                                    -- 해석 결과: 지역·범위·의도·상호 우선 등
    intent             varchar(10) CHECK (intent IN ('name', 'brand', 'category')),
    radius_stage       varchar(10) CHECK (radius_stage IN ('1km', '10km', 'area', 'viewport')),
    n_relevant_first   smallint,                                 -- 첫 범위(1km 등)의 관련 결과 수(확장 판단 근거)
    n_relevant_final   smallint,                                 -- 최종 관련 결과 수
    message            varchar(25),                              -- 화면에 띄운 안내 문구
    sub_message        varchar(20) CHECK (sub_message IN ('region_info', 'default_location')),   -- 작은 줄 문구
    expansion_cache_hit boolean,                                 -- 업종 의도일 때만
    results            jsonb       NOT NULL DEFAULT '[]',        -- 보여 준 가게: [{store_id, position, distance_m, score}]
    latency_ms         jsonb,                                    -- 단계별 지연(ms)
    is_fallback        boolean     NOT NULL DEFAULT false,       -- 임베딩 서버 장애로 BM25만 씀
    is_bot             boolean     NOT NULL DEFAULT false,
    PRIMARY KEY (query_id, page, logged_at)
) PARTITION BY RANGE (logged_at);
CREATE INDEX ix_search_log_time    ON search_log (logged_at);
CREATE INDEX ix_search_log_session ON search_log (session_id, logged_at);

CREATE TABLE event_log (                                         -- 행동 이벤트(노출·클릭·전화·길찾기 등)
    event_id        uuid        NOT NULL,                        -- 화면이 만든 번호. 재전송 중복은 통계 때 한 번만 셈
    server_ts       timestamptz NOT NULL,
    client_ts       timestamptz,
    session_id      uuid        NOT NULL,
    query_id        uuid,                                        -- 어느 검색에서 나온 행동인지
    event_type      varchar(15) NOT NULL
                    CHECK (event_type IN ('impression', 'click', 'action', 'dwell', 'region_choice', 'chip_change',
                                          'research_here', 'cluster_click', 'pin_click', 'reformulate', 'abandon')),
    store_id        uuid,
    position        smallint,
    action_type     varchar(10) CHECK (action_type IN ('call', 'directions', 'favorite', 'share', 'pay')),
    payload         jsonb,                                       -- 본 가게 목록, 머문 초, 고른 지역 등
    is_bot          boolean     NOT NULL DEFAULT false,
    PRIMARY KEY (event_id, server_ts)
) PARTITION BY RANGE (server_ts);
CREATE INDEX ix_event_log_query ON event_log (query_id);
CREATE INDEX ix_event_log_time  ON event_log (server_ts);

-- =====================================================================
-- 8. 통계 요약 (DR-17) — 한국 시간 하루 단위, 계속 보관
-- 인기 검색어·결과 없는 검색어는 search_log에서 기간을 정해 바로 계산한다(1년 안).
-- =====================================================================
CREATE TABLE stats_daily (
    stat_date            date        NOT NULL,                   -- 한국 시간 날짜
    view                 varchar(4)  NOT NULL CHECK (view IN ('list', 'map', 'all')),
    intent               varchar(10) NOT NULL CHECK (intent IN ('name', 'brand', 'category', 'none', 'all')),
    n_search             integer     NOT NULL DEFAULT 0,         -- 봇·폴백·browse·place 제외
    n_no_result          integer     NOT NULL DEFAULT 0,
    n_expanded           integer     NOT NULL DEFAULT 0,         -- 10km로 넓힘
    n_reformulate        integer     NOT NULL DEFAULT 0,         -- 바로 다시 검색
    n_search_clicked     integer     NOT NULL DEFAULT 0,         -- 클릭이 1번 이상 있었던 검색
    sum_first_click_pos  bigint      NOT NULL DEFAULT 0,         -- 평균 첫 클릭 순위 = 합 ÷ n_search_clicked
    n_impression         bigint      NOT NULL DEFAULT 0,
    n_click              bigint      NOT NULL DEFAULT 0,
    n_cache_lookup       integer     NOT NULL DEFAULT 0,         -- 확장어 캐시 조회
    n_cache_hit          integer     NOT NULL DEFAULT 0,         -- 확장어 캐시 적중
    n_fallback           integer     NOT NULL DEFAULT 0,
    n_bot                integer     NOT NULL DEFAULT 0,
    created_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (stat_date, view, intent)
);

-- =====================================================================
-- 9. 기본 데이터
-- =====================================================================
INSERT INTO payment_method (payment_code, name, source_column, sort_order, is_visible) VALUES
    ('card',    '카드결제',   'card_payment',   1, true),
    ('qr',      'QR결제',     'qr_payment',     2, true);

INSERT INTO category (category_code, name, sort_order) VALUES
    ('K001', '식품·마트', 1), ('K002', '의류', 2), ('K003', '생활·잡화', 3), ('K004', '인테리어', 4),
    ('K005', '가전·디지털', 5), ('K006', '음식점', 6), ('K007', '카페·디저트', 7), ('K008', '편의점', 8),
    ('K009', '주유소', 9), ('K010', '기타', 10), ('K011', '미용', 11), ('K012', '의료', 12),
    ('K013', '교육·문화', 13), ('K014', '스포츠', 14), ('K015', '숙박·여행', 15), ('K016', '자동차·교통', 16),
    ('K017', '생활서비스', 17);

-- =====================================================================
-- 10. 갱신 작업이 실행하는 예시(데이터 버전 7 만들기)
-- =====================================================================
-- (1) 새 버전 파티션: 빈 테이블로 만들어 채우고 인덱스까지 만든 뒤 붙인다(붙이기 전에는 검색에 안 보임)
CREATE TABLE store_snapshot_v7 (LIKE store_snapshot INCLUDING DEFAULTS INCLUDING CONSTRAINTS);
--   ... INSERT INTO store_snapshot_v7 SELECT ... (바뀌지 않은 가게는 이전 버전 벡터를 복사, 바뀐 가게만 임베딩 서버로) ...
ALTER TABLE store_snapshot_v7 ADD PRIMARY KEY (version_id, store_id);
CREATE INDEX ix_store_snapshot_v7_geom ON store_snapshot_v7 USING gist (geom) WHERE searchable;
CREATE INDEX ix_store_snapshot_v7_code ON store_snapshot_v7 (legal_dong_code varchar_pattern_ops) WHERE searchable;
ALTER TABLE store_snapshot_v7 ADD CONSTRAINT ck_store_snapshot_v7_version CHECK (version_id = 7);
-- (2) 전환(한 트랜잭션): 파티션 붙이기 → 이전 활성 버전 내리기 → 새 버전 올리기(활성은 하나만 허용)
-- BEGIN;
ALTER TABLE store_snapshot ATTACH PARTITION store_snapshot_v7 FOR VALUES IN (7);
-- UPDATE data_version SET status = 'retired' WHERE status = 'active';
-- UPDATE data_version SET status = 'active', activated_at = now() WHERE version_id = 7;
-- COMMIT;
-- (3) 직전 버전 1개만 남기고 더 오래된 파티션은 떼어 내고 지운다
-- ALTER TABLE store_snapshot DETACH PARTITION store_snapshot_v5; DROP TABLE store_snapshot_v5;

-- 로그 파티션 예시(한국 시간 2026년 11월). 스케줄러가 매달 다음 달 것을 미리 만들고, 1년 지난 달은 DROP
CREATE TABLE search_log_2026_11 PARTITION OF search_log
    FOR VALUES FROM ('2026-11-01 00:00:00+09') TO ('2026-12-01 00:00:00+09');
CREATE TABLE event_log_2026_11 PARTITION OF event_log
    FOR VALUES FROM ('2026-11-01 00:00:00+09') TO ('2026-12-01 00:00:00+09');
CREATE TABLE search_log_default PARTITION OF search_log DEFAULT;   -- 파티션을 못 만든 달에 대비
CREATE TABLE event_log_default PARTITION OF event_log DEFAULT;
