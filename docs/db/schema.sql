-- 가맹점 검색 서비스 DB 스키마 (초안 v0.1, 2026-11-12)
-- 대상: PostgreSQL 16 + PostGIS 3.4 + pgvector 0.8 이상
-- 설계 설명: docs/DB_DESIGN.md · 입력: docs/REQUIREMENTS.md 4절(DR-01~19)
--
-- 규칙
--  * 시각은 모두 timestamptz(UTC 저장). 하루·한 달 경계는 한국 시간(Asia/Seoul) 기준.
--  * 상태값은 PostgreSQL ENUM 대신 varchar + CHECK(JPA @Enumerated(STRING)과 맞고, 값 추가가 쉬움).
--  * 생성 순서는 외래 키 의존 순서: 확장 → 참조 → 관리자 → 버전·갱신 → 가맹점 → 스냅샷 → 회원 → 로그 → 통계.

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
    login_id              varchar(30)  NOT NULL,
    password_hash         varchar(100) NOT NULL,              -- bcrypt 60자, 여유
    status                varchar(10)  NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active', 'disabled')),
    must_change_password  boolean      NOT NULL DEFAULT true,
    failed_login_count    smallint     NOT NULL DEFAULT 0 CHECK (failed_login_count >= 0),
    locked_until          timestamptz,
    password_changed_at   timestamptz,
    last_login_at         timestamptz,
    created_by            bigint REFERENCES admin_user (admin_id),
    created_at            timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT uq_admin_user_login_id UNIQUE (login_id)
);

CREATE TABLE admin_access_log (
    log_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    admin_id     bigint REFERENCES admin_user (admin_id),       -- 로그인 실패(없는 아이디)는 NULL
    login_id     varchar(30),                                    -- 시도한 아이디(실패 기록용)
    occurred_at  timestamptz NOT NULL DEFAULT now(),
    client_ip    inet        NOT NULL,
    action       varchar(40) NOT NULL,                           -- login, login_fail, logout, view, store_edit, store_hide, refresh_run, ref_edit, admin_manage ...
    target_type  varchar(30),                                    -- store, refresh_job, brand_alias, place_exclusion, admin_user, stats ...
    target_id    varchar(64),
    detail       jsonb                                           -- 조회 조건, 변경 전·후 값 등
);
CREATE INDEX ix_admin_access_log_time  ON admin_access_log (occurred_at);
CREATE INDEX ix_admin_access_log_admin ON admin_access_log (admin_id, occurred_at);

-- =====================================================================
-- 2. 참조 데이터 (DR-07~12)
-- =====================================================================
CREATE TABLE category (                                          -- 업종 대분류 17개
    category_code  varchar(20) PRIMARY KEY,                      -- GAS, CONVENIENCE, MEDICAL ...
    name           varchar(20) NOT NULL UNIQUE,
    sort_order     smallint    NOT NULL,
    is_active      boolean     NOT NULL DEFAULT true
);

CREATE TABLE payment_method (                                    -- 결제 칩: card, qr, barcode
    payment_code   varchar(10) PRIMARY KEY,
    name           varchar(20) NOT NULL UNIQUE,                  -- 카드결제, QR결제, 바코드결제
    source_column  varchar(30),                                  -- 원천 열(card_payment, mobile_payment). 데이터 없으면 NULL
    sort_order     smallint    NOT NULL,
    is_visible     boolean     NOT NULL DEFAULT true             -- 바코드는 데이터가 올 때까지 false
);

CREATE TABLE brand_alias_group (
    group_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_name  varchar(40) NOT NULL UNIQUE,                 -- 대표 이름(GS25)
    updated_by      bigint REFERENCES admin_user (admin_id),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE brand_alias (
    alias_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    group_id    bigint      NOT NULL REFERENCES brand_alias_group (group_id) ON DELETE CASCADE,
    alias_text  varchar(40) NOT NULL,                            -- 지에스25
    alias_norm  varchar(40) NOT NULL,                            -- 정규화(소문자·공백 제거)
    CONSTRAINT uq_brand_alias_norm UNIQUE (alias_norm)           -- 한 표기는 한 브랜드에만
);
CREATE INDEX ix_brand_alias_group ON brand_alias (group_id);

CREATE TABLE gazetteer_version (
    gazetteer_version_id  smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                  varchar(30) NOT NULL UNIQUE,           -- gazetteer_v1
    source_sha256         char(64)    NOT NULL,
    row_count             integer     NOT NULL,
    is_active             boolean     NOT NULL DEFAULT false,
    loaded_at             timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_gazetteer_version_active ON gazetteer_version (is_active) WHERE is_active;

CREATE TABLE gazetteer_entry (
    entry_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    gazetteer_version_id  smallint    NOT NULL REFERENCES gazetteer_version (gazetteer_version_id) ON DELETE CASCADE,
    name                  varchar(50) NOT NULL,                  -- 신촌, 대전광역시 중구, 구리전통시장
    name_norm             varchar(50) NOT NULL,
    kind                  varchar(10) NOT NULL
                          CHECK (kind IN ('sido', 'city', 'sigungu', 'eupmyeon', 'dong', 'hdong', 'station', 'market')),
    scope                 varchar(5)  NOT NULL CHECK (scope IN ('area', 'point')),
    code_prefix           varchar(10),                           -- 법정동 코드 앞자리(2·5·8자리)
    center                geography(Point, 4326) NOT NULL,
    center_source         varchar(20),                           -- 공공데이터, 가게 중앙값 등
    evidence_count        smallint                               -- 같은 이름 지명 고르기용(공공데이터 근거 갈래 수)
);
CREATE INDEX ix_gazetteer_entry_name ON gazetteer_entry (gazetteer_version_id, name_norm);

CREATE TABLE place_exclusion (                                   -- 지명으로 읽지 않을 말(오케이 정형외과의 '오케이')
    term_norm   varchar(50) PRIMARY KEY,
    term        varchar(50) NOT NULL,
    reason      varchar(200) NOT NULL,
    created_by  bigint NOT NULL REFERENCES admin_user (admin_id),
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE expansion_cache (                                   -- 업종 검색어 LLM 확장어
    query_norm  varchar(100) PRIMARY KEY,                        -- NFKC·공백 정리·영문 소문자(검색어 최대 50자)
    keywords    text[]       NOT NULL CHECK (cardinality(keywords) > 0),
    model       varchar(60)  NOT NULL,                           -- Qwen2.5-14B-Instruct
    origin      varchar(10)  NOT NULL CHECK (origin IN ('offline', 'batch')),
    created_at  timestamptz  NOT NULL DEFAULT now()
);

CREATE TABLE reference_revision (                                -- 서버가 1분마다 읽어 바뀐 참조 데이터만 다시 올림
    ref_name    varchar(30) PRIMARY KEY
                CHECK (ref_name IN ('brand_alias', 'place_exclusion', 'gazetteer', 'expansion_cache', 'category', 'payment_method')),
    revision    bigint      NOT NULL DEFAULT 1,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- =====================================================================
-- 3. 데이터 버전·주간 갱신 (DR-05, DR-06)
-- =====================================================================
CREATE TABLE source_file (                                       -- 올린 원천 엑셀(파일은 저장소에, DB에는 정보만)
    file_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    original_name  varchar(200) NOT NULL,
    storage_path   varchar(500) NOT NULL,
    sha256         char(64)     NOT NULL UNIQUE,                 -- 같은 파일 두 번 반영 방지
    size_bytes     bigint       NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 104857600),
    row_count      integer,
    uploaded_by    bigint       NOT NULL REFERENCES admin_user (admin_id),
    uploaded_at    timestamptz  NOT NULL DEFAULT now()
);

CREATE TABLE data_version (
    version_id      smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    version_name    varchar(20) NOT NULL UNIQUE,                 -- 2026-11-16, 같은 날 두 번째는 2026-11-16.2 (한국 시간 날짜)
    status          varchar(10) NOT NULL DEFAULT 'building'
                    CHECK (status IN ('building', 'active', 'retired', 'failed')),
    source_file_id  bigint REFERENCES source_file (file_id),     -- 최초 적재는 NULL 가능
    embedding_model varchar(60) NOT NULL,                        -- bge_m3_ft_mj_20261014_0743
    n_total         integer,
    n_new           integer,
    n_changed       integer,
    n_pending       integer,                                     -- 확인 대기로 바뀐 수
    n_restored      integer,
    n_closed        integer,
    n_coord_error   integer,
    n_conflict      integer,
    created_by      bigint REFERENCES admin_user (admin_id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    activated_at    timestamptz
);
-- 활성 버전은 언제나 하나. 검색 서버는 이 행을 읽어 메모리에 들고 있고, 바뀌면 새 버전으로 갈아탄다
CREATE UNIQUE INDEX uq_data_version_one_active ON data_version (status) WHERE status = 'active';

CREATE TABLE refresh_job (
    job_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    file_id          bigint      NOT NULL REFERENCES source_file (file_id),
    target_version_id smallint   REFERENCES data_version (version_id),
    status           varchar(20) NOT NULL DEFAULT 'uploaded'
                     CHECK (status IN ('uploaded', 'validating', 'diffing', 'awaiting_approval', 'approved',
                                       'embedding', 'indexing', 'switching', 'succeeded', 'failed', 'cancelled')),
    progress_pct     smallint    NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
    needs_approval   boolean     NOT NULL DEFAULT false,         -- 사라지는 가게가 기준 %를 넘음(FR-UPD-05)
    preview          jsonb,                                      -- 건수, 좌표 오류·충돌 목록, 같은 사업자번호 목록
    error_step       varchar(20),
    error_message    text,
    started_by       bigint      NOT NULL REFERENCES admin_user (admin_id),
    approved_by      bigint      REFERENCES admin_user (admin_id),
    approved_at      timestamptz,
    edits_applied_until timestamptz,                             -- 이 시각까지의 관리자 수정을 새 버전에 반영함(FR-UPD-07)
    created_at       timestamptz NOT NULL DEFAULT now(),
    finished_at      timestamptz
);
-- 진행 중인 갱신은 하나만(FR-UPD-08): 끝나지 않은 상태의 행은 최대 1개
CREATE UNIQUE INDEX uq_refresh_job_one_running ON refresh_job ((true))
    WHERE status NOT IN ('succeeded', 'failed', 'cancelled');
CREATE INDEX ix_refresh_job_created ON refresh_job (created_at);

CREATE UNLOGGED TABLE refresh_staging_row (                      -- 갱신 중 원천 행 임시 보관(작업 끝나면 비움)
    job_id          bigint  NOT NULL REFERENCES refresh_job (job_id) ON DELETE CASCADE,
    source_row_no   integer NOT NULL,
    store_name      varchar(100),
    business_no     varchar(20),
    merchant_no     varchar(20),
    address         varchar(200),
    latitude        varchar(20),
    longitude       varchar(20),
    legal_dong_code varchar(10),
    market_type     varchar(30),
    market_name     varchar(100),
    items           text,
    card_payment    varchar(5),
    mobile_payment  varchar(5),
    fingerprint     char(64),
    store_id        uuid,                                        -- 기존 가게면 채움
    diff_type       varchar(10) CHECK (diff_type IN ('new', 'changed', 'same')),
    PRIMARY KEY (job_id, source_row_no)
);

-- =====================================================================
-- 4. 가맹점 (DR-01~03)
-- =====================================================================
CREATE TABLE store (                                             -- 가게 정체성·생애 상태(버전과 무관한 현재 값)
    store_id              uuid        PRIMARY KEY,               -- 기존 UUID 유지, 새 가게만 gen_random_uuid()
    fingerprint           char(64)    NOT NULL,                  -- sha256(사업자번호+가맹점명+주소), 원천 값으로
    lifecycle_status      varchar(10) NOT NULL DEFAULT 'active'
                          CHECK (lifecycle_status IN ('active', 'pending', 'closed')),
    missing_count         smallint    NOT NULL DEFAULT 0 CHECK (missing_count >= 0),  -- 연속으로 원천에 없던 주 수
    is_hidden             boolean     NOT NULL DEFAULT false,
    hidden_reason         varchar(200),
    hidden_by             bigint REFERENCES admin_user (admin_id),
    hidden_at             timestamptz,
    coord_error           boolean     NOT NULL DEFAULT false,    -- 수정 값까지 반영한 좌표가 0·국내 밖·충돌
    first_version_id      smallint    NOT NULL REFERENCES data_version (version_id),
    last_seen_version_id  smallint    NOT NULL REFERENCES data_version (version_id),
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_store_fingerprint UNIQUE (fingerprint),
    CONSTRAINT ck_store_hidden_reason CHECK (NOT is_hidden OR hidden_reason IS NOT NULL),
    CONSTRAINT ck_store_closed_missing CHECK (lifecycle_status <> 'closed' OR missing_count >= 2)
);
CREATE INDEX ix_store_status ON store (lifecycle_status) WHERE lifecycle_status <> 'active' OR is_hidden OR coord_error;

CREATE TABLE store_source (                                      -- 원천 파일의 최신 값 그대로(원천 열 거울)
    store_id         uuid PRIMARY KEY REFERENCES store (store_id),
    store_name       varchar(100) NOT NULL,
    business_no      varchar(20)  NOT NULL,                      -- 문자열(앞자리 0)
    merchant_no      varchar(20),                                -- 결측·전화번호 형태 섞임
    address          varchar(200) NOT NULL,
    latitude         numeric(9,6),                               -- 원천 그대로(0 좌표 포함)
    longitude        numeric(9,6),
    legal_dong_code  varchar(10),
    market_type      varchar(30),
    market_name      varchar(100),
    items            text,                                       -- 없으면 NULL(채우지 않음)
    card_payment     boolean,                                    -- 원천 카드결제여부, 빈 값 NULL
    mobile_payment   boolean,                                    -- 원천 모바일결제여부(화면 이름 QR결제)
    geo_conflict     boolean NOT NULL DEFAULT false,             -- 중복 행끼리 좌표 다름
    item_conflict    boolean NOT NULL DEFAULT false,
    payment_conflict boolean NOT NULL DEFAULT false,             -- 중복 행끼리 결제 값 다름(하나라도 Y면 Y)
    source_version_id smallint NOT NULL REFERENCES data_version (version_id),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_store_source_business_no ON store_source (business_no);
CREATE INDEX ix_store_source_name ON store_source (store_name varchar_pattern_ops);   -- 관리자 상호 앞부분 검색

CREATE TABLE store_override (                                    -- 관리자 수정 값(필드별, 해제 전까지)
    store_id            uuid        NOT NULL REFERENCES store (store_id),
    field_name          varchar(20) NOT NULL
                        CHECK (field_name IN ('store_name', 'items', 'location', 'market_name',
                                              'payment_card', 'payment_qr', 'category')),
    override_value      jsonb       NOT NULL,                    -- location = {lat, lon, legal_dong_code, address}
    source_value_at_edit jsonb,                                  -- 수정할 때의 원천 값(바뀌면 알림)
    reason              varchar(200) NOT NULL,
    admin_id            bigint      NOT NULL REFERENCES admin_user (admin_id),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (store_id, field_name)
);
CREATE INDEX ix_store_override_updated ON store_override (updated_at);   -- 갱신 전환 직전 재적용 대상 찾기

CREATE TABLE store_override_alert (                              -- 수정한 필드의 원천 값이 바뀜(FR-STO-08)
    alert_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    store_id          uuid        NOT NULL REFERENCES store (store_id),
    field_name        varchar(20) NOT NULL,
    old_source_value  jsonb,
    new_source_value  jsonb,
    version_id        smallint    NOT NULL REFERENCES data_version (version_id),
    status            varchar(10) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'kept', 'reverted')),
    resolved_by       bigint REFERENCES admin_user (admin_id),
    resolved_at       timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_store_override_alert_open ON store_override_alert (store_id, field_name) WHERE status = 'open';

CREATE TABLE store_edit_history (                                -- 관리자 수정·해제·숨김 이력(영구)
    history_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    store_id    uuid        NOT NULL REFERENCES store (store_id),
    action      varchar(10) NOT NULL CHECK (action IN ('set', 'clear', 'hide', 'unhide', 'keep', 'revert')),
    field_name  varchar(20),
    old_value   jsonb,
    new_value   jsonb,
    reason      varchar(200) NOT NULL,
    admin_id    bigint      NOT NULL REFERENCES admin_user (admin_id),
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_store_edit_history_store ON store_edit_history (store_id, created_at);

CREATE TABLE store_status_history (                              -- 상태 전이 이력(영구)
    history_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    store_id     uuid        NOT NULL REFERENCES store (store_id),
    from_status  varchar(10),
    to_status    varchar(10) NOT NULL,
    reason       varchar(20) NOT NULL
                 CHECK (reason IN ('new', 'missing', 'returned', 'missing_2w', 'coord_error', 'coord_fixed')),
    version_id   smallint    NOT NULL REFERENCES data_version (version_id),
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_store_status_history_store ON store_status_history (store_id, created_at);

-- =====================================================================
-- 5. 검색 스냅샷 (데이터 버전별, DR-04·07·11) — 버전마다 파티션 하나
-- =====================================================================
-- 외래 키를 두지 않는다: 갱신 작업만 쓰는 파생 테이블이고, 외래 키가 있으면 파티션을 붙일 때(ATTACH) 21만 행을 다시 검사해 전환이 느려진다.
-- 무결성은 갱신 작업이 store·data_version에서 만들어 넣는 것으로 보장하고, 전환 전에 검증 쿼리로 확인한다.
CREATE TABLE store_snapshot (
    version_id        smallint     NOT NULL,                     -- data_version.version_id
    store_id          uuid         NOT NULL,                     -- store.store_id
    store_name        varchar(100) NOT NULL,                     -- 수정 값 반영(유효 값)
    items             text,
    address           varchar(200) NOT NULL,
    address_short     varchar(100),                              -- 시군구 + 도로명(결과 카드)
    legal_dong_code   varchar(10)  NOT NULL,
    market_type       varchar(30),
    market_name       varchar(100),
    geom              geography(Point, 4326) NOT NULL,
    category_codes    varchar(20)[] NOT NULL DEFAULT '{}',       -- 여러 업종 가능
    primary_category  varchar(20),                               -- category.category_code
    category_source   varchar(10) CHECK (category_source IN ('item', 'name', 'none', 'admin')),
    subcategory       varchar(40),
    payment_codes     varchar(10)[] NOT NULL DEFAULT '{}',       -- {card, qr}; 바코드는 데이터 오면 추가
    searchable        boolean      NOT NULL,                     -- 영업중 · 숨김 아님 · 좌표 오류 아님
    doc_text          varchar(300) NOT NULL,                     -- 가맹점명: {상호} / 취급품목: {품목}
    embedding         vector(1024) NOT NULL,                     -- fp32, L2 정규화된 값
    PRIMARY KEY (version_id, store_id)
) PARTITION BY LIST (version_id);
-- 파티션과 인덱스는 갱신 작업이 만든다(아래 예시). 검색은 항상 version_id = 활성 버전으로 조회.

CREATE TABLE branch_suffix (                                     -- 지점 접미사(버전과 묶음, BM25 쿼리에서 뺌)
    version_id  smallint    NOT NULL REFERENCES data_version (version_id) ON DELETE CASCADE,
    suffix      varchar(10) NOT NULL,                            -- 선운점, 중앙점
    PRIMARY KEY (version_id, suffix)
);

-- =====================================================================
-- 6. 회원 (DR-13, DR-14, DR-19)
-- =====================================================================
CREATE TABLE member (
    member_id      uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    nickname       varchar(12) NOT NULL,                         -- 중복 허용, 없으면 '회원1234'
    email          varchar(254),                                 -- 선택 동의, 동의 안 하면 NULL
    created_at     timestamptz NOT NULL DEFAULT now(),
    last_login_at  timestamptz,
    CONSTRAINT ck_member_nickname_len CHECK (char_length(nickname) BETWEEN 2 AND 12)
);

CREATE TABLE member_auth (                                       -- 로그인 수단(회원 1 : N)
    auth_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    member_id         uuid        NOT NULL REFERENCES member (member_id) ON DELETE CASCADE,
    provider          varchar(10) NOT NULL CHECK (provider IN ('kakao', 'google')),
    provider_user_id  varchar(255) NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_member_auth_provider_user UNIQUE (provider, provider_user_id),
    CONSTRAINT uq_member_auth_member_provider UNIQUE (member_id, provider)
);

CREATE TABLE member_refresh_token (
    token_id     uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id    uuid        NOT NULL REFERENCES member (member_id) ON DELETE CASCADE,
    token_hash   char(64)    NOT NULL UNIQUE,                    -- 토큰 원문은 저장하지 않음(sha256)
    family_id    uuid        NOT NULL,                           -- 재사용 감지: 같은 계열의 옛 토큰이 오면 계열 전체 폐기
    expires_at   timestamptz NOT NULL,
    revoked_at   timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_member_refresh_token_member ON member_refresh_token (member_id);
CREATE INDEX ix_member_refresh_token_expires ON member_refresh_token (expires_at);

CREATE TABLE terms (                                             -- 약관 버전
    terms_type    varchar(10) NOT NULL CHECK (terms_type IN ('service', 'privacy', 'age14', 'location')),
    version       varchar(20) NOT NULL,
    is_required   boolean     NOT NULL,
    effective_at  timestamptz NOT NULL,
    PRIMARY KEY (terms_type, version)
);

CREATE TABLE member_terms_agreement (                            -- 약관 동의 기록(DR-19)
    member_id   uuid        NOT NULL REFERENCES member (member_id) ON DELETE CASCADE,
    terms_type  varchar(10) NOT NULL,
    version     varchar(20) NOT NULL,
    agreed_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (member_id, terms_type, version),
    FOREIGN KEY (terms_type, version) REFERENCES terms (terms_type, version)
);

CREATE TABLE member_recent_search (                              -- 최근 검색어(회원당 10개, 좌표·query_id 없음)
    member_id    uuid         NOT NULL REFERENCES member (member_id) ON DELETE CASCADE,
    query_norm   varchar(100) NOT NULL,
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
-- 7. 검색 로그 (DR-16) — 한국 시간 월 단위 파티션, 1년 뒤 파티션째 삭제. 외래 키 없음
-- =====================================================================
CREATE TABLE search_log (
    query_id             uuid        NOT NULL,
    logged_at            timestamptz NOT NULL,                   -- server_ts
    session_id           uuid        NOT NULL,
    schema_version       smallint    NOT NULL,
    app_version          varchar(20) NOT NULL,
    pipeline_version     varchar(20) NOT NULL,                   -- 정책 yaml·계수 버전
    corpus_version_id    smallint    NOT NULL,                   -- data_version.version_id(FK 없음)
    query_text           varchar(50),                            -- browse는 NULL
    input_type           varchar(15) NOT NULL
                         CHECK (input_type IN ('typed', 'recent', 'autocomplete', 'chip', 'browse', 'place')),
    category_code        varchar(20),
    payment_code         varchar(10),
    location_source      varchar(15) NOT NULL
                         CHECK (location_source IN ('query_region', 'ui_region', 'map_viewport', 'gps', 'default')),
    view                 varchar(4)  NOT NULL CHECK (view IN ('list', 'map')),
    viewport_cells       varchar(50),                            -- 지도 화면 남서·북동 100m 격자
    user_cell            varchar(20),                            -- 사용자 위치 100m 격자(원 좌표 없음)
    parsed               jsonb,                                  -- 지역·scope·code_prefix·intent·name_first·다른 지역 후보
    intent               varchar(10) CHECK (intent IN ('name', 'brand', 'category')),   -- 통계용으로 parsed에서 꺼냄
    radius_stage         varchar(10) CHECK (radius_stage IN ('1km', '10km', 'area', 'viewport')),
    n_relevant_first     smallint,
    n_relevant_final     smallint,
    message              varchar(25),
    sub_message          varchar(20) CHECK (sub_message IN ('region_info', 'default_location')),
    is_fallback          boolean     NOT NULL DEFAULT false,
    expansion_cache_hit  boolean,                                -- 업종 의도일 때만 값
    latency_ms           jsonb,                                  -- 단계별 지연
    is_bot               boolean     NOT NULL DEFAULT false,
    bot_rule             varchar(20),
    PRIMARY KEY (query_id, logged_at)
) PARTITION BY RANGE (logged_at);
CREATE INDEX ix_search_log_time    ON search_log (logged_at);
CREATE INDEX ix_search_log_session ON search_log (session_id, logged_at);

CREATE TABLE search_result_log (                                 -- 노출 결과: 본 페이지까지 가게 1개 = 1행
    query_id    uuid        NOT NULL,
    logged_at   timestamptz NOT NULL,
    position    smallint    NOT NULL CHECK (position BETWEEN 1 AND 300),
    store_id    uuid        NOT NULL,
    distance_m  integer     NOT NULL,                            -- 검색 중심 기준
    score       real        NOT NULL,
    PRIMARY KEY (query_id, position, logged_at)
) PARTITION BY RANGE (logged_at);

CREATE TABLE event_log (                                         -- 행동 이벤트
    event_id        uuid        NOT NULL,                        -- 화면이 만든 ID(재전송 중복 제거)
    server_ts       timestamptz NOT NULL,
    client_ts       timestamptz,
    schema_version  smallint    NOT NULL,
    session_id      uuid        NOT NULL,
    query_id        uuid,
    event_type      varchar(15) NOT NULL
                    CHECK (event_type IN ('impression', 'click', 'action', 'dwell', 'region_choice', 'chip_change',
                                          'research_here', 'cluster_click', 'pin_click', 'reformulate', 'abandon')),
    store_id        uuid,
    position        smallint,
    distance_m      integer,
    action_type     varchar(10) CHECK (action_type IN ('call', 'directions', 'favorite', 'share', 'pay')),
    impressed_ids   uuid[],                                      -- impression일 때 본 가게들
    payload         jsonb,                                       -- dwell 초, 고른 지역, 이전 query_id 등
    is_bot          boolean     NOT NULL DEFAULT false,
    PRIMARY KEY (event_id, server_ts)
) PARTITION BY RANGE (server_ts);
CREATE INDEX ix_event_log_query ON event_log (query_id);
CREATE INDEX ix_event_log_time  ON event_log (server_ts);

-- 재전송 중복 제거: 재전송된 이벤트는 server_ts가 달라 event_log 기본 키로는 못 거른다.
-- 받을 때 여기에 먼저 넣고(ON CONFLICT DO NOTHING) 새로 들어간 것만 event_log에 저장. 2일 지난 행은 매일 삭제.
CREATE TABLE event_dedup (
    event_id     uuid        PRIMARY KEY,
    received_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_event_dedup_received ON event_dedup (received_at);

-- =====================================================================
-- 8. 통계 요약 (DR-17) — 한국 시간 하루 단위, 계속 보관
-- =====================================================================
CREATE TABLE stats_daily (
    stat_date            date        NOT NULL,                   -- 한국 시간 날짜
    view                 varchar(4)  NOT NULL CHECK (view IN ('list', 'map', 'all')),
    intent               varchar(10) NOT NULL CHECK (intent IN ('name', 'brand', 'category', 'none', 'all')),
    n_search             integer     NOT NULL DEFAULT 0,         -- 봇·폴백·browse·place 제외
    n_no_result          integer     NOT NULL DEFAULT 0,
    n_expanded           integer     NOT NULL DEFAULT 0,
    n_reformulate        integer     NOT NULL DEFAULT 0,
    n_search_clicked     integer     NOT NULL DEFAULT 0,         -- 클릭이 1번 이상 있었던 검색
    sum_first_click_pos  bigint      NOT NULL DEFAULT 0,         -- 평균 첫 클릭 순위 = 합 ÷ n_search_clicked
    n_impression         bigint      NOT NULL DEFAULT 0,
    n_click              bigint      NOT NULL DEFAULT 0,
    n_cache_lookup       integer     NOT NULL DEFAULT 0,
    n_cache_hit          integer     NOT NULL DEFAULT 0,
    n_fallback           integer     NOT NULL DEFAULT 0,         -- 품질 지표와 따로 셈
    n_bot                integer     NOT NULL DEFAULT 0,
    message_counts       jsonb       NOT NULL DEFAULT '{}',      -- 문구별 건수
    created_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (stat_date, view, intent)
);

CREATE TABLE stats_daily_query (                                 -- 인기 검색어·결과 없는 검색어(하루 상위 1,000개)
    stat_date      date         NOT NULL,
    query_norm     varchar(100) NOT NULL,
    n_search       integer      NOT NULL,
    n_no_result    integer      NOT NULL DEFAULT 0,
    n_no_exact     integer      NOT NULL DEFAULT 0,              -- 문구 ⑤
    n_weak         integer      NOT NULL DEFAULT 0,              -- 문구 ⑥
    n_click        integer      NOT NULL DEFAULT 0,
    PRIMARY KEY (stat_date, query_norm)
);

-- =====================================================================
-- 9. 기본 데이터
-- =====================================================================
INSERT INTO payment_method (payment_code, name, source_column, sort_order, is_visible) VALUES
    ('card',    '카드결제',   'card_payment',   1, true),
    ('qr',      'QR결제',     'mobile_payment', 2, true),
    ('barcode', '바코드결제', NULL,             3, false);

INSERT INTO reference_revision (ref_name) VALUES
    ('brand_alias'), ('place_exclusion'), ('gazetteer'), ('expansion_cache'), ('category'), ('payment_method');

-- =====================================================================
-- 10. 갱신 작업이 실행하는 예시(데이터 버전 7 만들기)
-- =====================================================================
-- (1) 새 버전 파티션: 빈 테이블로 만들어 채우고 인덱스까지 만든 뒤 붙인다(붙이기 전에는 검색에 안 보임)
CREATE TABLE store_snapshot_v7 (LIKE store_snapshot INCLUDING DEFAULTS INCLUDING CONSTRAINTS);
--   ... INSERT INTO store_snapshot_v7 SELECT ... (바뀌지 않은 가게는 이전 버전 벡터를 복사, 바뀐 가게만 추론 서버로) ...
ALTER TABLE store_snapshot_v7 ADD PRIMARY KEY (version_id, store_id);   -- 붙이기 전에 만들어 두면 ATTACH가 그대로 씀
CREATE INDEX ix_store_snapshot_v7_geom ON store_snapshot_v7 USING gist (geom) WHERE searchable;
CREATE INDEX ix_store_snapshot_v7_code ON store_snapshot_v7 (legal_dong_code varchar_pattern_ops) WHERE searchable;
ALTER TABLE store_snapshot_v7 ADD CONSTRAINT ck_store_snapshot_v7_version CHECK (version_id = 7);
-- (2) 전환(한 트랜잭션): 파티션 붙이기 → 이전 활성 버전 내리기 → 새 버전 올리기(순서 중요: 활성은 하나만 허용)
-- BEGIN;
ALTER TABLE store_snapshot ATTACH PARTITION store_snapshot_v7 FOR VALUES IN (7);
-- UPDATE data_version SET status = 'retired' WHERE status = 'active';
-- UPDATE data_version SET status = 'active', activated_at = now() WHERE version_id = 7;
-- COMMIT;
-- (3) 이전 버전 1개만 남기고 더 오래된 파티션은 떼어 내고 지운다
-- ALTER TABLE store_snapshot DETACH PARTITION store_snapshot_v5; DROP TABLE store_snapshot_v5;

-- 로그 파티션 예시(한국 시간 2026년 11월). 스케줄러가 매달 다음 달 것을 미리 만들고, 1년 지난 달은 통계 요약 확인 뒤 DROP
CREATE TABLE search_log_2026_11 PARTITION OF search_log
    FOR VALUES FROM ('2026-11-01 00:00:00+09') TO ('2026-12-01 00:00:00+09');
CREATE TABLE search_result_log_2026_11 PARTITION OF search_result_log
    FOR VALUES FROM ('2026-11-01 00:00:00+09') TO ('2026-12-01 00:00:00+09');
CREATE TABLE event_log_2026_11 PARTITION OF event_log
    FOR VALUES FROM ('2026-11-01 00:00:00+09') TO ('2026-12-01 00:00:00+09');
CREATE TABLE search_log_default PARTITION OF search_log DEFAULT;          -- 파티션을 못 만든 달에 대비
CREATE TABLE search_result_log_default PARTITION OF search_result_log DEFAULT;
CREATE TABLE event_log_default PARTITION OF event_log DEFAULT;
