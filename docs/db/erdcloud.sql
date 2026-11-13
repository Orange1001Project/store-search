-- ERDCloud 가져오기용(보기 전용, MySQL 문법). 실제 DB는 docs/db/schema.sql(PostgreSQL)을 쓴다.
-- 바꾼 자료형: uuid→CHAR(36), timestamptz→DATETIME, jsonb·배열→JSON, geography→GEOMETRY, vector(1024)→BLOB
-- CHECK·기본값·부분 인덱스·파티션은 생략. 테이블 이름은 영어, COMMENT가 한글 이름.

CREATE TABLE `admin_user` (
  `admin_id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '관리자 ID',
  `login_id` VARCHAR(30) NOT NULL COMMENT '로그인 ID',
  `password_hash` VARCHAR(100) NOT NULL COMMENT '비밀번호 해시',
  `status` VARCHAR(10) NOT NULL COMMENT '상태',
  `must_change_password` BOOLEAN NOT NULL COMMENT '비밀번호 변경 필요',
  `failed_login_count` SMALLINT NOT NULL COMMENT '로그인 실패 횟수',
  `locked_until` DATETIME NULL COMMENT '잠금 해제 시각',
  `last_login_at` DATETIME NULL COMMENT '마지막 로그인',
  `created_at` DATETIME NOT NULL COMMENT '생성 시각',
  PRIMARY KEY (`admin_id`),
  UNIQUE KEY `uq_admin_user_login_id` (`login_id`)
) COMMENT = '관리자';

CREATE TABLE `category` (
  `category_code` VARCHAR(20) NOT NULL COMMENT '업종 코드',
  `name` VARCHAR(20) NOT NULL COMMENT '이름',
  `sort_order` SMALLINT NOT NULL COMMENT '정렬 순서',
  `is_active` BOOLEAN NOT NULL COMMENT '사용 여부',
  `updated_at` DATETIME NOT NULL COMMENT '수정 시각',
  PRIMARY KEY (`category_code`),
  UNIQUE KEY `uq_category_name` (`name`)
) COMMENT = '업종';

CREATE TABLE `payment_method` (
  `payment_code` VARCHAR(10) NOT NULL COMMENT '결제 코드',
  `name` VARCHAR(20) NOT NULL COMMENT '이름',
  `source_column` VARCHAR(30) NULL COMMENT '원천 열',
  `sort_order` SMALLINT NOT NULL COMMENT '정렬 순서',
  `is_visible` BOOLEAN NOT NULL COMMENT '화면 표시 여부',
  `updated_at` DATETIME NOT NULL COMMENT '수정 시각',
  PRIMARY KEY (`payment_code`),
  UNIQUE KEY `uq_payment_method_name` (`name`)
) COMMENT = '결제 수단';

CREATE TABLE `brand_alias` (
  `alias_id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '별칭 ID',
  `canonical_name` VARCHAR(40) NOT NULL COMMENT '대표 브랜드명',
  `alias_text` VARCHAR(40) NOT NULL COMMENT '별칭',
  `alias_norm` VARCHAR(40) NOT NULL COMMENT '정규화 별칭',
  `updated_by` BIGINT NULL COMMENT '수정자',
  `updated_at` DATETIME NOT NULL COMMENT '수정 시각',
  PRIMARY KEY (`alias_id`),
  UNIQUE KEY `uq_brand_alias_alias_norm` (`alias_norm`)
) COMMENT = '브랜드 별칭';

CREATE TABLE `gazetteer` (
  `entry_id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '항목 ID',
  `name` VARCHAR(50) NOT NULL COMMENT '이름',
  `name_norm` VARCHAR(50) NOT NULL COMMENT '정규화 이름',
  `kind` VARCHAR(10) NOT NULL COMMENT '지명 종류',
  `scope` VARCHAR(5) NOT NULL COMMENT '지명 범위',
  `code_prefix` VARCHAR(10) NULL COMMENT '법정동 코드 앞자리',
  `center` GEOMETRY NOT NULL COMMENT '중심 좌표',
  `evidence_count` SMALLINT NULL COMMENT '근거 가게 수',
  `updated_at` DATETIME NOT NULL COMMENT '수정 시각',
  PRIMARY KEY (`entry_id`)
) COMMENT = '지명 사전';

CREATE TABLE `place_exclusion` (
  `term_norm` VARCHAR(50) NOT NULL COMMENT '정규화 제외어',
  `term` VARCHAR(50) NOT NULL COMMENT '제외어',
  `reason` VARCHAR(200) NOT NULL COMMENT '사유',
  `updated_by` BIGINT NULL COMMENT '수정자',
  `updated_at` DATETIME NOT NULL COMMENT '수정 시각',
  PRIMARY KEY (`term_norm`)
) COMMENT = '지명 제외어';

CREATE TABLE `expansion_cache` (
  `query_norm` VARCHAR(100) NOT NULL COMMENT '정규화 검색어',
  `keywords` JSON NOT NULL COMMENT '확장어 목록',
  `model` VARCHAR(60) NOT NULL COMMENT '생성 모델',
  `updated_at` DATETIME NOT NULL COMMENT '수정 시각',
  PRIMARY KEY (`query_norm`)
) COMMENT = '확장어 캐시';

CREATE TABLE `data_version` (
  `version_id` SMALLINT NOT NULL AUTO_INCREMENT COMMENT '데이터 버전 ID',
  `version_name` VARCHAR(20) NOT NULL COMMENT '버전 이름',
  `status` VARCHAR(10) NOT NULL COMMENT '상태',
  `embedding_model` VARCHAR(60) NOT NULL COMMENT '임베딩 모델',
  `n_total` INT NULL COMMENT '전체 가게 수',
  `n_new` INT NULL COMMENT '신규 가게 수',
  `n_changed` INT NULL COMMENT '변경 가게 수',
  `n_pending` INT NULL COMMENT '확인 대기 수',
  `n_closed` INT NULL COMMENT '폐업 가게 수',
  `n_coord_error` INT NULL COMMENT '좌표 오류 수',
  `created_at` DATETIME NOT NULL COMMENT '생성 시각',
  `activated_at` DATETIME NULL COMMENT '활성화 시각',
  PRIMARY KEY (`version_id`),
  UNIQUE KEY `uq_data_version_version_name` (`version_name`)
) COMMENT = '데이터 버전';

CREATE TABLE `refresh_job` (
  `job_id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '작업 ID',
  `file_name` VARCHAR(200) NOT NULL COMMENT '파일 이름',
  `file_path` VARCHAR(500) NOT NULL COMMENT '파일 위치',
  `file_sha256` CHAR(64) NOT NULL COMMENT '파일 지문',
  `file_size` BIGINT NOT NULL COMMENT '파일 크기',
  `target_version_id` SMALLINT NULL COMMENT '대상 버전 ID',
  `status` VARCHAR(20) NOT NULL COMMENT '상태',
  `progress_pct` SMALLINT NOT NULL COMMENT '진행률(%)',
  `needs_approval` BOOLEAN NOT NULL COMMENT '승인 필요',
  `preview` JSON NULL COMMENT '미리보기 요약',
  `error_message` TEXT NULL COMMENT '오류 메시지',
  `edits_applied_until` DATETIME NULL COMMENT '수정 재적용 기준 시각',
  `started_by` BIGINT NOT NULL COMMENT '실행자',
  `approved_by` BIGINT NULL COMMENT '승인자',
  `created_at` DATETIME NOT NULL COMMENT '생성 시각',
  `finished_at` DATETIME NULL COMMENT '종료 시각',
  PRIMARY KEY (`job_id`)
) COMMENT = '주간 갱신 작업';

CREATE TABLE `store` (
  `store_id` CHAR(36) NOT NULL COMMENT '가맹점 ID',
  `fingerprint` CHAR(64) NOT NULL COMMENT '지문',
  `store_name` VARCHAR(100) NOT NULL COMMENT '가맹점명',
  `business_no` VARCHAR(20) NOT NULL COMMENT '사업자번호',
  `merchant_no` VARCHAR(20) NULL COMMENT '가맹점번호',
  `address` VARCHAR(200) NOT NULL COMMENT '주소',
  `latitude` DECIMAL(9,6) NULL COMMENT '위도',
  `longitude` DECIMAL(9,6) NULL COMMENT '경도',
  `legal_dong_code` VARCHAR(10) NULL COMMENT '법정동코드',
  `market_type` VARCHAR(30) NULL COMMENT '시장 분류',
  `market_name` VARCHAR(100) NULL COMMENT '시장명',
  `items` TEXT NULL COMMENT '취급품목',
  `card_payment` BOOLEAN NULL COMMENT '카드결제 여부',
  `mobile_payment` BOOLEAN NULL COMMENT '모바일결제 여부',
  `source_conflict` BOOLEAN NOT NULL COMMENT '원천 충돌',
  `lifecycle_status` VARCHAR(10) NOT NULL COMMENT '영업 상태',
  `missing_count` SMALLINT NOT NULL COMMENT '연속 누락 주 수',
  `status_changed_at` DATETIME NOT NULL COMMENT '상태 변경 시각',
  `is_hidden` BOOLEAN NOT NULL COMMENT '숨김 여부',
  `hidden_reason` VARCHAR(200) NULL COMMENT '숨김 사유',
  `hidden_by` BIGINT NULL COMMENT '숨김 처리자',
  `coord_error` BOOLEAN NOT NULL COMMENT '좌표 오류',
  `last_seen_version_id` SMALLINT NOT NULL COMMENT '마지막 확인 버전',
  `created_at` DATETIME NOT NULL COMMENT '생성 시각',
  `updated_at` DATETIME NOT NULL COMMENT '수정 시각',
  PRIMARY KEY (`store_id`),
  UNIQUE KEY `uq_store_fingerprint` (`fingerprint`)
) COMMENT = '가맹점';

CREATE TABLE `store_override` (
  `store_id` CHAR(36) NOT NULL COMMENT '가맹점 ID',
  `field_name` VARCHAR(20) NOT NULL COMMENT '필드명',
  `override_value` JSON NOT NULL COMMENT '수정 값',
  `source_value_at_edit` JSON NULL COMMENT '수정 당시 원천 값',
  `source_changed` BOOLEAN NOT NULL COMMENT '원천 바뀜',
  `new_source_value` JSON NULL COMMENT '새 원천 값',
  `reason` VARCHAR(200) NOT NULL COMMENT '사유',
  `admin_id` BIGINT NOT NULL COMMENT '관리자 ID',
  `updated_at` DATETIME NOT NULL COMMENT '수정 시각',
  PRIMARY KEY (`store_id`, `field_name`)
) COMMENT = '관리자 수정 값';

CREATE TABLE `store_snapshot` (
  `version_id` SMALLINT NOT NULL COMMENT '데이터 버전 ID',
  `store_id` CHAR(36) NOT NULL COMMENT '가맹점 ID',
  `store_name` VARCHAR(100) NOT NULL COMMENT '가맹점명',
  `items` TEXT NULL COMMENT '취급품목',
  `address` VARCHAR(200) NOT NULL COMMENT '주소',
  `address_short` VARCHAR(100) NULL COMMENT '짧은 주소',
  `legal_dong_code` VARCHAR(10) NOT NULL COMMENT '법정동코드',
  `market_type` VARCHAR(30) NULL COMMENT '시장 분류',
  `market_name` VARCHAR(100) NULL COMMENT '시장명',
  `geom` GEOMETRY NOT NULL COMMENT '좌표(geography)',
  `category_codes` JSON NOT NULL COMMENT '업종 코드 목록',
  `primary_category` VARCHAR(20) NULL COMMENT '대표 업종',
  `category_source` VARCHAR(10) NULL COMMENT '업종 근거',
  `subcategory` VARCHAR(40) NULL COMMENT '세부 업종',
  `payment_codes` JSON NOT NULL COMMENT '결제 코드 목록',
  `searchable` BOOLEAN NOT NULL COMMENT '검색 대상 여부',
  `doc_text` VARCHAR(300) NOT NULL COMMENT '임베딩 원문',
  `embedding` BLOB NOT NULL COMMENT '임베딩 vector(1024)',
  PRIMARY KEY (`version_id`, `store_id`)
) COMMENT = '검색 스냅샷(버전별)';

CREATE TABLE `member` (
  `member_id` CHAR(36) NOT NULL COMMENT '회원 ID',
  `status` VARCHAR(10) NOT NULL COMMENT '상태',
  `nickname` VARCHAR(12) NULL COMMENT '닉네임',
  `email` VARCHAR(254) NULL COMMENT '이메일',
  `terms_version` VARCHAR(20) NOT NULL COMMENT '약관 버전',
  `terms_agreed_at` DATETIME NOT NULL COMMENT '약관 동의 시각',
  `created_at` DATETIME NOT NULL COMMENT '생성 시각',
  `last_login_at` DATETIME NULL COMMENT '마지막 로그인',
  `withdrawn_at` DATETIME NULL COMMENT '탈퇴 시각',
  PRIMARY KEY (`member_id`)
) COMMENT = '회원';

CREATE TABLE `member_auth` (
  `auth_id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '로그인 수단 ID',
  `member_id` CHAR(36) NOT NULL COMMENT '회원 ID',
  `provider` VARCHAR(10) NOT NULL COMMENT '로그인 제공자',
  `provider_user_id` VARCHAR(255) NOT NULL COMMENT '제공자 회원 ID',
  `created_at` DATETIME NOT NULL COMMENT '생성 시각',
  PRIMARY KEY (`auth_id`),
  UNIQUE KEY `uq_member_auth_provider_provider_user_id` (`provider`, `provider_user_id`),
  UNIQUE KEY `uq_member_auth_member_id_provider` (`member_id`, `provider`)
) COMMENT = '회원 로그인 수단';

CREATE TABLE `member_recent_search` (
  `member_id` CHAR(36) NOT NULL COMMENT '회원 ID',
  `query_norm` VARCHAR(100) NOT NULL COMMENT '정규화 검색어',
  `query_text` VARCHAR(50) NOT NULL COMMENT '검색어',
  `searched_at` DATETIME NOT NULL COMMENT '검색 시각',
  PRIMARY KEY (`member_id`, `query_norm`)
) COMMENT = '최근 검색어';

CREATE TABLE `member_favorite` (
  `member_id` CHAR(36) NOT NULL COMMENT '회원 ID',
  `store_id` CHAR(36) NOT NULL COMMENT '가맹점 ID',
  `created_at` DATETIME NOT NULL COMMENT '생성 시각',
  PRIMARY KEY (`member_id`, `store_id`)
) COMMENT = '즐겨찾기';

CREATE TABLE `search_log` (
  `query_id` CHAR(36) NOT NULL COMMENT '검색 ID',
  `page` SMALLINT NOT NULL COMMENT '페이지',
  `logged_at` DATETIME NOT NULL COMMENT '기록 시각',
  `session_id` CHAR(36) NOT NULL COMMENT '세션 ID',
  `schema_version` SMALLINT NOT NULL COMMENT '로그 형식 버전',
  `app_version` VARCHAR(20) NOT NULL COMMENT '앱 버전',
  `pipeline_version` VARCHAR(20) NOT NULL COMMENT '검색 정책 버전',
  `corpus_version_id` SMALLINT NOT NULL COMMENT '데이터 버전 ID',
  `query_text` VARCHAR(50) NULL COMMENT '검색어',
  `input_type` VARCHAR(15) NOT NULL COMMENT '입력 방식',
  `category_code` VARCHAR(20) NULL COMMENT '업종 코드',
  `payment_codes` JSON NOT NULL COMMENT '결제 코드 목록',
  `view` VARCHAR(4) NOT NULL COMMENT '화면 종류',
  `location_source` VARCHAR(15) NOT NULL COMMENT '검색 중심 출처',
  `user_cell` VARCHAR(20) NULL COMMENT '사용자 위치 격자',
  `viewport_cells` VARCHAR(50) NULL COMMENT '지도 화면 격자',
  `parsed` JSON NULL COMMENT '해석 결과',
  `intent` VARCHAR(10) NULL COMMENT '검색 의도',
  `radius_stage` VARCHAR(10) NULL COMMENT '범위 단계',
  `n_relevant_first` SMALLINT NULL COMMENT '첫 범위 관련 수',
  `n_relevant_final` SMALLINT NULL COMMENT '최종 관련 수',
  `message` VARCHAR(25) NULL COMMENT '안내 문구',
  `sub_message` VARCHAR(20) NULL COMMENT '보조 문구',
  `expansion_cache_hit` BOOLEAN NULL COMMENT '확장어 캐시 적중',
  `results` JSON NOT NULL COMMENT '보여 준 가게 목록',
  `latency_ms` JSON NULL COMMENT '단계별 지연(ms)',
  `is_fallback` BOOLEAN NOT NULL COMMENT '폴백 여부',
  `is_bot` BOOLEAN NOT NULL COMMENT '봇 여부',
  PRIMARY KEY (`query_id`, `page`, `logged_at`)
) COMMENT = '검색 로그';

CREATE TABLE `event_log` (
  `event_id` CHAR(36) NOT NULL COMMENT '이벤트 ID',
  `server_ts` DATETIME NOT NULL COMMENT '서버 시각',
  `client_ts` DATETIME NULL COMMENT '화면 시각',
  `session_id` CHAR(36) NOT NULL COMMENT '세션 ID',
  `query_id` CHAR(36) NULL COMMENT '검색 ID',
  `event_type` VARCHAR(15) NOT NULL COMMENT '이벤트 종류',
  `store_id` CHAR(36) NULL COMMENT '가맹점 ID',
  `position` SMALLINT NULL COMMENT '순위',
  `action_type` VARCHAR(10) NULL COMMENT '행동 종류',
  `payload` JSON NULL COMMENT '추가 정보',
  `is_bot` BOOLEAN NOT NULL COMMENT '봇 여부',
  PRIMARY KEY (`event_id`, `server_ts`)
) COMMENT = '행동 이벤트 로그';

CREATE TABLE `stats_daily` (
  `stat_date` DATE NOT NULL COMMENT '통계 날짜',
  `view` VARCHAR(4) NOT NULL COMMENT '화면 종류',
  `intent` VARCHAR(10) NOT NULL COMMENT '검색 의도',
  `n_search` INT NOT NULL COMMENT '검색 수',
  `n_no_result` INT NOT NULL COMMENT '결과 없음 수',
  `n_expanded` INT NOT NULL COMMENT '10km 확장 수',
  `n_reformulate` INT NOT NULL COMMENT '재검색 수',
  `n_search_clicked` INT NOT NULL COMMENT '클릭 있는 검색 수',
  `sum_first_click_pos` BIGINT NOT NULL COMMENT '첫 클릭 순위 합',
  `n_impression` BIGINT NOT NULL COMMENT '노출 수',
  `n_click` BIGINT NOT NULL COMMENT '클릭 수',
  `n_cache_lookup` INT NOT NULL COMMENT '캐시 조회 수',
  `n_cache_hit` INT NOT NULL COMMENT '캐시 적중 수',
  `n_fallback` INT NOT NULL COMMENT '폴백 수',
  `n_bot` INT NOT NULL COMMENT '봇 검색 수',
  `created_at` DATETIME NOT NULL COMMENT '생성 시각',
  PRIMARY KEY (`stat_date`, `view`, `intent`)
) COMMENT = '일별 통계';

-- 외래 키(실제 DB와 같음)
ALTER TABLE `brand_alias` ADD CONSTRAINT `fk_brand_alias_1` FOREIGN KEY (`updated_by`) REFERENCES `admin_user` (`admin_id`);
ALTER TABLE `place_exclusion` ADD CONSTRAINT `fk_place_exclusion_2` FOREIGN KEY (`updated_by`) REFERENCES `admin_user` (`admin_id`);
ALTER TABLE `refresh_job` ADD CONSTRAINT `fk_refresh_job_3` FOREIGN KEY (`target_version_id`) REFERENCES `data_version` (`version_id`);
ALTER TABLE `refresh_job` ADD CONSTRAINT `fk_refresh_job_4` FOREIGN KEY (`started_by`) REFERENCES `admin_user` (`admin_id`);
ALTER TABLE `refresh_job` ADD CONSTRAINT `fk_refresh_job_5` FOREIGN KEY (`approved_by`) REFERENCES `admin_user` (`admin_id`);
ALTER TABLE `store` ADD CONSTRAINT `fk_store_6` FOREIGN KEY (`hidden_by`) REFERENCES `admin_user` (`admin_id`);
ALTER TABLE `store` ADD CONSTRAINT `fk_store_7` FOREIGN KEY (`last_seen_version_id`) REFERENCES `data_version` (`version_id`);
ALTER TABLE `store_override` ADD CONSTRAINT `fk_store_override_8` FOREIGN KEY (`store_id`) REFERENCES `store` (`store_id`);
ALTER TABLE `store_override` ADD CONSTRAINT `fk_store_override_9` FOREIGN KEY (`admin_id`) REFERENCES `admin_user` (`admin_id`);
ALTER TABLE `member_auth` ADD CONSTRAINT `fk_member_auth_10` FOREIGN KEY (`member_id`) REFERENCES `member` (`member_id`);
ALTER TABLE `member_recent_search` ADD CONSTRAINT `fk_member_recent_search_11` FOREIGN KEY (`member_id`) REFERENCES `member` (`member_id`);
ALTER TABLE `member_favorite` ADD CONSTRAINT `fk_member_favorite_12` FOREIGN KEY (`member_id`) REFERENCES `member` (`member_id`);
ALTER TABLE `member_favorite` ADD CONSTRAINT `fk_member_favorite_13` FOREIGN KEY (`store_id`) REFERENCES `store` (`store_id`);

-- 논리 관계: 그림에서 연결이 보이도록만 넣음. 실제 DB에는 외래 키가 없다(버전 전환 속도 때문). 로그(search_log·event_log)는 외래 키 없이 따로 둔다
ALTER TABLE `store_snapshot` ADD CONSTRAINT `fk_store_snapshot_14` FOREIGN KEY (`version_id`) REFERENCES `data_version` (`version_id`);
ALTER TABLE `store_snapshot` ADD CONSTRAINT `fk_store_snapshot_15` FOREIGN KEY (`store_id`) REFERENCES `store` (`store_id`);
