CREATE TABLE `admin_user` (
	`admin_id`	BIGINT	NOT NULL	COMMENT '관리자 ID',
	`login_id`	VARCHAR(30)	NOT NULL	COMMENT '로그인 ID',
	`password_hash`	VARCHAR(100)	NOT NULL	COMMENT '비밀번호 해시',
	`status`	VARCHAR(10)	NOT NULL	COMMENT '상태',
	`must_change_password`	BOOLEAN	NOT NULL	COMMENT '비밀번호 변경 필요',
	`failed_login_count`	SMALLINT	NOT NULL	COMMENT '로그인 실패 횟수',
	`locked_until`	DATETIME	NULL	COMMENT '잠금 해제 시각',
	`last_login_at`	DATETIME	NULL	COMMENT '마지막 로그인',
	`created_at`	DATETIME	NOT NULL	COMMENT '생성 시각'
);

CREATE TABLE `category` (
	`category_code`	VARCHAR(20)	NOT NULL	COMMENT '업종 코드',
	`name`	VARCHAR(20)	NOT NULL	COMMENT '이름',
	`sort_order`	SMALLINT	NOT NULL	COMMENT '정렬 순서',
	`is_active`	BOOLEAN	NOT NULL	COMMENT '사용 여부',
	`updated_at`	DATETIME	NOT NULL	COMMENT '수정 시각'
);

CREATE TABLE `payment_method` (
	`payment_code`	VARCHAR(10)	NOT NULL	COMMENT '결제 코드',
	`name`	VARCHAR(20)	NOT NULL	COMMENT '이름',
	`source_column`	VARCHAR(30)	NULL	COMMENT '원천 열',
	`sort_order`	SMALLINT	NOT NULL	COMMENT '정렬 순서',
	`is_visible`	BOOLEAN	NOT NULL	COMMENT '화면 표시 여부',
	`updated_at`	DATETIME	NOT NULL	COMMENT '수정 시각'
);

CREATE TABLE `brand_alias` (
	`alias_id`	BIGINT	NOT NULL	COMMENT '별칭 ID',
	`canonical_name`	VARCHAR(40)	NOT NULL	COMMENT '대표 브랜드명',
	`alias_text`	VARCHAR(40)	NOT NULL	COMMENT '별칭',
	`alias_norm`	VARCHAR(40)	NOT NULL	COMMENT '정규화 별칭',
	`updated_by`	BIGINT	NULL	COMMENT '수정자',
	`updated_at`	DATETIME	NOT NULL	COMMENT '수정 시각'
);

CREATE TABLE `gazetteer` (
	`entry_id`	BIGINT	NOT NULL	COMMENT '항목 ID',
	`name`	VARCHAR(50)	NOT NULL	COMMENT '이름',
	`name_norm`	VARCHAR(50)	NOT NULL	COMMENT '정규화 이름',
	`kind`	VARCHAR(10)	NOT NULL	COMMENT '지명 종류',
	`scope`	VARCHAR(5)	NOT NULL	COMMENT '지명 범위',
	`code_prefix`	VARCHAR(10)	NULL	COMMENT '법정동 코드 앞자리',
	`center`	VARCHAR(100)	NOT NULL	COMMENT '중심 좌표',
	`evidence_count`	SMALLINT	NULL	COMMENT '근거 가게 수',
	`updated_at`	DATETIME	NOT NULL	COMMENT '수정 시각'
);

CREATE TABLE `place_exclusion` (
	`term_norm`	VARCHAR(50)	NOT NULL	COMMENT '정규화 제외어',
	`term`	VARCHAR(50)	NOT NULL	COMMENT '제외어',
	`reason`	VARCHAR(200)	NOT NULL	COMMENT '사유',
	`updated_by`	BIGINT	NULL	COMMENT '수정자',
	`updated_at`	DATETIME	NOT NULL	COMMENT '수정 시각'
);

CREATE TABLE `expansion_cache` (
	`query_norm`	VARCHAR(100)	NOT NULL	COMMENT '정규화 검색어',
	`keywords`	JSON	NOT NULL	COMMENT '확장어 목록',
	`model`	VARCHAR(60)	NOT NULL	COMMENT '생성 모델',
	`updated_at`	DATETIME	NOT NULL	COMMENT '수정 시각'
);

CREATE TABLE `data_version` (
	`version_id`	SMALLINT	NOT NULL	COMMENT '데이터 버전 ID',
	`version_name`	VARCHAR(20)	NOT NULL	COMMENT '버전 이름',
	`status`	VARCHAR(10)	NOT NULL	COMMENT '상태',
	`embedding_model`	VARCHAR(60)	NOT NULL	COMMENT '임베딩 모델',
	`n_total`	INT	NULL	COMMENT '전체 가게 수',
	`n_new`	INT	NULL	COMMENT '신규 가게 수',
	`n_changed`	INT	NULL	COMMENT '변경 가게 수',
	`n_pending`	INT	NULL	COMMENT '확인 대기 수',
	`n_closed`	INT	NULL	COMMENT '폐업 가게 수',
	`n_coord_error`	INT	NULL	COMMENT '좌표 오류 수',
	`created_at`	DATETIME	NOT NULL	COMMENT '생성 시각',
	`activated_at`	DATETIME	NULL	COMMENT '활성화 시각'
);

CREATE TABLE `refresh_job` (
	`job_id`	BIGINT	NOT NULL	COMMENT '작업 ID',
	`file_name`	VARCHAR(200)	NOT NULL	COMMENT '파일 이름',
	`file_path`	VARCHAR(500)	NOT NULL	COMMENT '파일 위치',
	`file_sha256`	CHAR(64)	NOT NULL	COMMENT '파일 지문',
	`file_size`	BIGINT	NOT NULL	COMMENT '파일 크기',
	`target_version_id`	SMALLINT	NULL	COMMENT '대상 버전 ID',
	`status`	VARCHAR(20)	NOT NULL	COMMENT '상태',
	`progress_pct`	SMALLINT	NOT NULL	COMMENT '진행률(%)',
	`needs_approval`	BOOLEAN	NOT NULL	COMMENT '승인 필요',
	`preview`	JSON	NULL	COMMENT '미리보기 요약',
	`error_message`	TEXT	NULL	COMMENT '오류 메시지',
	`edits_applied_until`	DATETIME	NULL	COMMENT '수정 재적용 기준 시각',
	`started_by`	BIGINT	NOT NULL	COMMENT '실행자',
	`approved_by`	BIGINT	NULL	COMMENT '승인자',
	`created_at`	DATETIME	NOT NULL	COMMENT '생성 시각',
	`finished_at`	DATETIME	NULL	COMMENT '종료 시각'
);

CREATE TABLE `store` (
	`store_id`	CHAR(36)	NOT NULL	COMMENT '가맹점 ID',
	`fingerprint`	CHAR(64)	NOT NULL	COMMENT '지문',
	`store_name`	VARCHAR(100)	NOT NULL	COMMENT '가맹점명',
	`business_no`	VARCHAR(20)	NOT NULL	COMMENT '사업자번호',
	`merchant_no`	VARCHAR(20)	NULL	COMMENT '가맹점번호',
	`address`	VARCHAR(200)	NOT NULL	COMMENT '주소',
	`latitude`	DECIMAL(9,6)	NULL	COMMENT '위도',
	`longitude`	DECIMAL(9,6)	NULL	COMMENT '경도',
	`legal_dong_code`	VARCHAR(10)	NULL	COMMENT '법정동코드',
	`market_type`	VARCHAR(30)	NULL	COMMENT '시장 분류',
	`market_name`	VARCHAR(100)	NULL	COMMENT '시장명',
	`items`	TEXT	NULL	COMMENT '취급품목',
	`ksic_code`	VARCHAR(5)	NULL	COMMENT '표준산업분류코드',
	`onnuri_category`	VARCHAR(4)	NULL	COMMENT '온누리 중분류',
	`card_payment`	BOOLEAN	NULL	COMMENT '카드결제 여부',
	`qr_payment`	BOOLEAN	NULL	COMMENT 'QR결제 여부',
	`source_conflict`	BOOLEAN	NOT NULL	COMMENT '원천 충돌',
	`lifecycle_status`	VARCHAR(10)	NOT NULL	COMMENT '영업 상태',
	`missing_count`	SMALLINT	NOT NULL	COMMENT '연속 누락 주 수',
	`status_changed_at`	DATETIME	NOT NULL	COMMENT '상태 변경 시각',
	`is_hidden`	BOOLEAN	NOT NULL	COMMENT '숨김 여부',
	`visibility_reason`	VARCHAR(200)	NULL	COMMENT '숨김·해제 사유',
	`visibility_changed_by`	BIGINT	NULL	COMMENT '숨김·해제 처리자',
	`visibility_changed_at`	DATETIME	NULL	COMMENT '숨김·해제 시각',
	`coord_error`	BOOLEAN	NOT NULL	COMMENT '좌표 오류',
	`last_seen_version_id`	SMALLINT	NOT NULL	COMMENT '마지막 확인 버전',
	`created_at`	DATETIME	NOT NULL	COMMENT '생성 시각',
	`updated_at`	DATETIME	NOT NULL	COMMENT '수정 시각'
);

CREATE TABLE `store_override` (
	`store_id`	CHAR(36)	NOT NULL	COMMENT '가맹점 ID',
	`field_name`	VARCHAR(20)	NOT NULL	COMMENT '필드명',
	`override_value`	JSON	NOT NULL	COMMENT '수정 값',
	`source_value_at_edit`	JSON	NULL	COMMENT '수정 당시 원천 값',
	`source_changed`	BOOLEAN	NOT NULL	COMMENT '원천 바뀜',
	`new_source_value`	JSON	NULL	COMMENT '새 원천 값',
	`reason`	VARCHAR(200)	NOT NULL	COMMENT '사유',
	`admin_id`	BIGINT	NOT NULL	COMMENT '관리자 ID',
	`updated_at`	DATETIME	NOT NULL	COMMENT '수정 시각'
);

CREATE TABLE `store_snapshot` (
	`version_id`	SMALLINT	NOT NULL	COMMENT '데이터 버전 ID',
	`store_id`	CHAR(36)	NOT NULL	COMMENT '가맹점 ID',
	`store_name`	VARCHAR(100)	NOT NULL	COMMENT '가맹점명',
	`items`	TEXT	NULL	COMMENT '취급품목',
	`address`	VARCHAR(200)	NOT NULL	COMMENT '주소',
	`address_short`	VARCHAR(100)	NULL	COMMENT '짧은 주소',
	`legal_dong_code`	VARCHAR(10)	NOT NULL	COMMENT '법정동코드',
	`market_type`	VARCHAR(30)	NULL	COMMENT '시장 분류',
	`market_name`	VARCHAR(100)	NULL	COMMENT '시장명',
	`geom`	VARCHAR(100)	NOT NULL	COMMENT '좌표(geography)',
	`category_codes`	JSON	NOT NULL	COMMENT '업종 코드 목록',
	`primary_category`	VARCHAR(20)	NULL	COMMENT '대표 업종',
	`category_source`	VARCHAR(10)	NULL	COMMENT '업종 근거',
	`subcategory`	VARCHAR(40)	NULL	COMMENT '세부 업종',
	`payment_codes`	JSON	NOT NULL	COMMENT '결제 코드 목록',
	`searchable`	BOOLEAN	NOT NULL	COMMENT '검색 대상 여부',
	`doc_text`	VARCHAR(300)	NOT NULL	COMMENT '임베딩 원문',
	`embedding`	BLOB	NOT NULL	COMMENT '임베딩 vector(1024)'
);

CREATE TABLE `member` (
	`member_id`	CHAR(36)	NOT NULL	COMMENT '회원 ID',
	`status`	VARCHAR(10)	NOT NULL	COMMENT '상태',
	`nickname`	VARCHAR(12)	NULL	COMMENT '닉네임',
	`email`	VARCHAR(254)	NULL	COMMENT '이메일',
	`terms_version`	VARCHAR(20)	NOT NULL	COMMENT '약관 버전',
	`terms_agreed_at`	DATETIME	NOT NULL	COMMENT '약관 동의 시각',
	`created_at`	DATETIME	NOT NULL	COMMENT '생성 시각',
	`last_login_at`	DATETIME	NULL	COMMENT '마지막 로그인',
	`withdrawn_at`	DATETIME	NULL	COMMENT '탈퇴 시각'
);

CREATE TABLE `member_auth` (
	`auth_id`	BIGINT	NOT NULL	COMMENT '로그인 수단 ID',
	`member_id`	CHAR(36)	NOT NULL	COMMENT '회원 ID',
	`provider`	VARCHAR(10)	NOT NULL	COMMENT '로그인 제공자',
	`provider_user_id`	VARCHAR(255)	NOT NULL	COMMENT '제공자 회원 ID',
	`created_at`	DATETIME	NOT NULL	COMMENT '생성 시각'
);

CREATE TABLE `member_recent_search` (
	`member_id`	CHAR(36)	NOT NULL	COMMENT '회원 ID',
	`query_norm`	VARCHAR(100)	NOT NULL	COMMENT '정규화 검색어',
	`query_text`	VARCHAR(50)	NOT NULL	COMMENT '검색어',
	`searched_at`	DATETIME	NOT NULL	COMMENT '검색 시각'
);

CREATE TABLE `member_favorite` (
	`member_id`	CHAR(36)	NOT NULL	COMMENT '회원 ID',
	`store_id`	CHAR(36)	NOT NULL	COMMENT '가맹점 ID',
	`created_at`	DATETIME	NOT NULL	COMMENT '생성 시각'
);

CREATE TABLE `search_log` (
	`query_id`	CHAR(36)	NOT NULL	COMMENT '검색 ID',
	`page`	SMALLINT	NOT NULL	COMMENT '페이지',
	`logged_at`	DATETIME	NOT NULL	COMMENT '기록 시각',
	`session_id`	CHAR(36)	NOT NULL	COMMENT '세션 ID',
	`schema_version`	SMALLINT	NOT NULL	COMMENT '로그 형식 버전',
	`app_version`	VARCHAR(20)	NOT NULL	COMMENT '앱 버전',
	`pipeline_version`	VARCHAR(20)	NOT NULL	COMMENT '검색 정책 버전',
	`corpus_version_id`	SMALLINT	NOT NULL	COMMENT '데이터 버전 ID',
	`query_text`	VARCHAR(50)	NULL	COMMENT '검색어',
	`input_type`	VARCHAR(15)	NOT NULL	COMMENT '입력 방식',
	`category_code`	VARCHAR(20)	NULL	COMMENT '업종 코드',
	`payment_codes`	JSON	NOT NULL	COMMENT '결제 코드 목록',
	`view`	VARCHAR(4)	NOT NULL	COMMENT '화면 종류',
	`location_source`	VARCHAR(15)	NOT NULL	COMMENT '검색 중심 출처',
	`user_cell`	VARCHAR(20)	NULL	COMMENT '사용자 위치 격자',
	`viewport_cells`	VARCHAR(50)	NULL	COMMENT '지도 화면 격자',
	`parsed`	JSON	NULL	COMMENT '해석 결과',
	`intent`	VARCHAR(10)	NULL	COMMENT '검색 의도',
	`radius_stage`	VARCHAR(10)	NULL	COMMENT '범위 단계',
	`n_relevant_first`	SMALLINT	NULL	COMMENT '첫 범위 관련 수',
	`n_relevant_final`	SMALLINT	NULL	COMMENT '최종 관련 수',
	`message`	VARCHAR(25)	NULL	COMMENT '안내 문구',
	`sub_message`	VARCHAR(20)	NULL	COMMENT '보조 문구',
	`expansion_cache_hit`	BOOLEAN	NULL	COMMENT '확장어 캐시 적중',
	`results`	JSON	NOT NULL	COMMENT '보여 준 가게 목록',
	`latency_ms`	JSON	NULL	COMMENT '단계별 지연(ms)',
	`is_fallback`	BOOLEAN	NOT NULL	COMMENT '폴백 여부',
	`is_bot`	BOOLEAN	NOT NULL	COMMENT '봇 여부'
);

CREATE TABLE `event_log` (
	`event_id`	CHAR(36)	NOT NULL	COMMENT '이벤트 ID',
	`server_ts`	DATETIME	NOT NULL	COMMENT '서버 시각',
	`client_ts`	DATETIME	NULL	COMMENT '화면 시각',
	`session_id`	CHAR(36)	NOT NULL	COMMENT '세션 ID',
	`query_id`	CHAR(36)	NULL	COMMENT '검색 ID',
	`event_type`	VARCHAR(15)	NOT NULL	COMMENT '이벤트 종류',
	`store_id`	CHAR(36)	NULL	COMMENT '가맹점 ID',
	`position`	SMALLINT	NULL	COMMENT '순위',
	`action_type`	VARCHAR(10)	NULL	COMMENT '행동 종류',
	`payload`	JSON	NULL	COMMENT '추가 정보',
	`is_bot`	BOOLEAN	NOT NULL	COMMENT '봇 여부'
);

CREATE TABLE `stats_daily` (
	`stat_date`	DATE	NOT NULL	COMMENT '통계 날짜',
	`view`	VARCHAR(4)	NOT NULL	COMMENT '화면 종류',
	`intent`	VARCHAR(10)	NOT NULL	COMMENT '검색 의도',
	`n_search`	INT	NOT NULL	COMMENT '검색 수',
	`n_no_result`	INT	NOT NULL	COMMENT '결과 없음 수',
	`n_expanded`	INT	NOT NULL	COMMENT '10km 확장 수',
	`n_reformulate`	INT	NOT NULL	COMMENT '재검색 수',
	`n_search_clicked`	INT	NOT NULL	COMMENT '클릭 있는 검색 수',
	`sum_first_click_pos`	BIGINT	NOT NULL	COMMENT '첫 클릭 순위 합',
	`n_impression`	BIGINT	NOT NULL	COMMENT '노출 수',
	`n_click`	BIGINT	NOT NULL	COMMENT '클릭 수',
	`n_cache_lookup`	INT	NOT NULL	COMMENT '캐시 조회 수',
	`n_cache_hit`	INT	NOT NULL	COMMENT '캐시 적중 수',
	`n_fallback`	INT	NOT NULL	COMMENT '폴백 수',
	`n_bot`	INT	NOT NULL	COMMENT '봇 검색 수',
	`created_at`	DATETIME	NOT NULL	COMMENT '생성 시각'
);

ALTER TABLE `admin_user` ADD CONSTRAINT `PK_ADMIN_USER` PRIMARY KEY (`admin_id`);
ALTER TABLE `category` ADD CONSTRAINT `PK_CATEGORY` PRIMARY KEY (`category_code`);
ALTER TABLE `payment_method` ADD CONSTRAINT `PK_PAYMENT_METHOD` PRIMARY KEY (`payment_code`);
ALTER TABLE `brand_alias` ADD CONSTRAINT `PK_BRAND_ALIAS` PRIMARY KEY (`alias_id`);
ALTER TABLE `gazetteer` ADD CONSTRAINT `PK_GAZETTEER` PRIMARY KEY (`entry_id`);
ALTER TABLE `place_exclusion` ADD CONSTRAINT `PK_PLACE_EXCLUSION` PRIMARY KEY (`term_norm`);
ALTER TABLE `expansion_cache` ADD CONSTRAINT `PK_EXPANSION_CACHE` PRIMARY KEY (`query_norm`);
ALTER TABLE `data_version` ADD CONSTRAINT `PK_DATA_VERSION` PRIMARY KEY (`version_id`);
ALTER TABLE `refresh_job` ADD CONSTRAINT `PK_REFRESH_JOB` PRIMARY KEY (`job_id`);
ALTER TABLE `store` ADD CONSTRAINT `PK_STORE` PRIMARY KEY (`store_id`);
ALTER TABLE `store_override` ADD CONSTRAINT `PK_STORE_OVERRIDE` PRIMARY KEY (`store_id`, `field_name`);
ALTER TABLE `store_snapshot` ADD CONSTRAINT `PK_STORE_SNAPSHOT` PRIMARY KEY (`version_id`, `store_id`);
ALTER TABLE `member` ADD CONSTRAINT `PK_MEMBER` PRIMARY KEY (`member_id`);
ALTER TABLE `member_auth` ADD CONSTRAINT `PK_MEMBER_AUTH` PRIMARY KEY (`auth_id`);
ALTER TABLE `member_recent_search` ADD CONSTRAINT `PK_MEMBER_RECENT_SEARCH` PRIMARY KEY (`member_id`, `query_norm`);
ALTER TABLE `member_favorite` ADD CONSTRAINT `PK_MEMBER_FAVORITE` PRIMARY KEY (`member_id`, `store_id`);
ALTER TABLE `search_log` ADD CONSTRAINT `PK_SEARCH_LOG` PRIMARY KEY (`query_id`, `page`, `logged_at`);
ALTER TABLE `event_log` ADD CONSTRAINT `PK_EVENT_LOG` PRIMARY KEY (`event_id`, `server_ts`);
ALTER TABLE `stats_daily` ADD CONSTRAINT `PK_STATS_DAILY` PRIMARY KEY (`stat_date`, `view`, `intent`);

ALTER TABLE `brand_alias` ADD CONSTRAINT `fk_brand_alias_1` FOREIGN KEY (`updated_by`) REFERENCES `admin_user` (`admin_id`);
ALTER TABLE `place_exclusion` ADD CONSTRAINT `fk_place_exclusion_2` FOREIGN KEY (`updated_by`) REFERENCES `admin_user` (`admin_id`);
ALTER TABLE `refresh_job` ADD CONSTRAINT `fk_refresh_job_3` FOREIGN KEY (`target_version_id`) REFERENCES `data_version` (`version_id`);
ALTER TABLE `refresh_job` ADD CONSTRAINT `fk_refresh_job_4` FOREIGN KEY (`started_by`) REFERENCES `admin_user` (`admin_id`);
ALTER TABLE `refresh_job` ADD CONSTRAINT `fk_refresh_job_5` FOREIGN KEY (`approved_by`) REFERENCES `admin_user` (`admin_id`);
ALTER TABLE `store` ADD CONSTRAINT `fk_store_6` FOREIGN KEY (`visibility_changed_by`) REFERENCES `admin_user` (`admin_id`);
ALTER TABLE `store` ADD CONSTRAINT `fk_store_7` FOREIGN KEY (`last_seen_version_id`) REFERENCES `data_version` (`version_id`);
ALTER TABLE `store_override` ADD CONSTRAINT `fk_store_override_8` FOREIGN KEY (`store_id`) REFERENCES `store` (`store_id`);
ALTER TABLE `store_override` ADD CONSTRAINT `fk_store_override_9` FOREIGN KEY (`admin_id`) REFERENCES `admin_user` (`admin_id`);
ALTER TABLE `member_auth` ADD CONSTRAINT `fk_member_auth_10` FOREIGN KEY (`member_id`) REFERENCES `member` (`member_id`);
ALTER TABLE `member_recent_search` ADD CONSTRAINT `fk_member_recent_search_11` FOREIGN KEY (`member_id`) REFERENCES `member` (`member_id`);
ALTER TABLE `member_favorite` ADD CONSTRAINT `fk_member_favorite_12` FOREIGN KEY (`member_id`) REFERENCES `member` (`member_id`);
ALTER TABLE `member_favorite` ADD CONSTRAINT `fk_member_favorite_13` FOREIGN KEY (`store_id`) REFERENCES `store` (`store_id`);
ALTER TABLE `store_snapshot` ADD CONSTRAINT `fk_store_snapshot_14` FOREIGN KEY (`version_id`) REFERENCES `data_version` (`version_id`);
ALTER TABLE `store_snapshot` ADD CONSTRAINT `fk_store_snapshot_15` FOREIGN KEY (`store_id`) REFERENCES `store` (`store_id`);
