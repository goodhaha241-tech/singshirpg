CREATE DATABASE IF NOT EXISTS discord_bot_db
    DEFAULT CHARACTER SET = 'utf8mb4'
    DEFAULT COLLATE = 'utf8mb4_unicode_ci';

USE discord_bot_db;

-- 1. 사용자 기본 정보
CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(50) PRIMARY KEY,
    pt BIGINT DEFAULT 0,
    money BIGINT DEFAULT 0,
    last_checkin DATE,
    investigator_index INT DEFAULT 0, -- 대표 캐릭터 인덱스
    
    -- 메인 퀘스트
    main_quest_id INT DEFAULT 0,
    main_quest_current INT DEFAULT 0,
    main_quest_index INT DEFAULT 0,

    -- 마이홈 정보
    water_can INT DEFAULT 0,
    fishing_rod INT DEFAULT 0,
    fishing_spot_level INT DEFAULT 0,
    garden_level INT DEFAULT 1,
    workshop_level INT DEFAULT 1,
    fishing_level INT DEFAULT 1,
    total_investigations BIGINT DEFAULT 0,
    total_subjugations BIGINT DEFAULT 0,
    total_turns BIGINT DEFAULT 0,
    fishing_max_slots INT DEFAULT 3,
    max_subjugation_depth INT DEFAULT 0,
    max_subjugation_char VARCHAR(100),
    max_subjugation_region VARCHAR(100),
    construction_step INT DEFAULT 0,

    -- JSON 형태로 저장할 가벼운 데이터들
    cards JSON,           -- 보유 카드 리스트
    buffs JSON,           -- 적용 중인 버프
    main_quest_progress JSON, -- 퀘스트 진행 상세
    daily_quests JSON,
    last_quest_date DATE,
    current_dungeon JSON,
    guild_rank VARCHAR(20),
    guild_data JSON,
    characters JSON,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. 인벤토리
CREATE TABLE IF NOT EXISTS inventory (
    user_id VARCHAR(50),
    item_name VARCHAR(100),
    quantity BIGINT DEFAULT 0,
    PRIMARY KEY (user_id, item_name),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 3. 영입 퀘스트 진행도
CREATE TABLE IF NOT EXISTS recruit_progress (
    user_id VARCHAR(50),
    char_key VARCHAR(50), -- 예: 'Yeongsan'
    progress INT DEFAULT 0,
    PRIMARY KEY (user_id, char_key),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 4. 마이홈 - 텃밭 슬롯
CREATE TABLE IF NOT EXISTS garden_slots (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(50),
    slot_index INT,
    planted BOOLEAN DEFAULT FALSE,
    plant_name VARCHAR(100),
    stage INT DEFAULT 0,
    last_invest_count BIGINT DEFAULT 0,
    fertilizer VARCHAR(100),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 5. 마이홈 - 비료
CREATE TABLE IF NOT EXISTS user_fertilizers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(50),
    target VARCHAR(100),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 6. 마이홈 - 작업실 슬롯
CREATE TABLE IF NOT EXISTS workshop_slots (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(50),
    slot_index INT,
    craft_item VARCHAR(100),
    start_count BIGINT DEFAULT 0,
    required_count BIGINT DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- ==========================================
-- [신규] 길드 시스템 관련 테이블 (안정화 핵심)
-- ==========================================

-- 7. 길드 기본 정보
CREATE TABLE IF NOT EXISTS guilds (
    guild_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    level INT DEFAULT 1,
    exp BIGINT DEFAULT 0,
    owner_id VARCHAR(50),
    member_count INT DEFAULT 0,
    
    -- 길드 공용 재화 (토큰)
    token_wood BIGINT DEFAULT 0,
    token_iron BIGINT DEFAULT 0,
    token_magic BIGINT DEFAULT 0,
    token_sorcery BIGINT DEFAULT 0,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 8. 길드 멤버 목록
CREATE TABLE IF NOT EXISTS guild_members (
    guild_id INT,
    user_id VARCHAR(50),
    role VARCHAR(20) DEFAULT 'member', -- master, officer, member
    contribution INT DEFAULT 0,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id),
    FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 9. 길드 창고 (납품 로그 및 보관)
CREATE TABLE IF NOT EXISTS guild_warehouse (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    guild_id INT,
    depositor_id VARCHAR(50),
    depositor_name VARCHAR(100),
    item_name VARCHAR(100),
    quantity INT DEFAULT 1,
    artifact_data JSON, -- 아티팩트일 경우 상세 데이터
    deposited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
);

-- [신규] 길드 인벤토리 (재료, 소모품 등 중첩 가능한 아이템)
CREATE TABLE IF NOT EXISTS guild_inventory (
    guild_id INT,
    item_name VARCHAR(100),
    count INT DEFAULT 0,
    category VARCHAR(50), -- consumable, material, etc. (분류용)
    PRIMARY KEY (guild_id, item_name),
    FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
);

-- [신규] 길드 아티팩트 보관함 (중첩 불가, 개별 데이터)
CREATE TABLE IF NOT EXISTS guild_stored_artifacts (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    guild_id INT,
    artifact_id VARCHAR(100), -- 원본 UUID
    name VARCHAR(100),
    rank_level INT,
    level INT,
    data JSON, -- 전체 데이터 저장
    stored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
);

-- [기존 유지/수정] 입출고 로그 (누가 무엇을 넣고 뺐는지 기록)
CREATE TABLE IF NOT EXISTS guild_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    guild_id INT,
    user_id VARCHAR(50),
    user_name VARCHAR(100),
    action_type VARCHAR(20), -- 'deposit', 'withdraw'
    item_name VARCHAR(100),
    count INT,
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS characters (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(50),
    name VARCHAR(100),
    hp INT DEFAULT 100,
    current_hp INT DEFAULT 100,
    max_mental INT DEFAULT 50,
    current_mental INT DEFAULT 50,
    attack INT DEFAULT 5,
    defense INT DEFAULT 0,
    defense_rate INT DEFAULT 0,
    card_slots INT DEFAULT 4,
    equipped_cards JSON,
    equipped_engraved_artifact JSON,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS artifacts (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(50),
    name VARCHAR(100),
    rank_level INT DEFAULT 1,
    grade INT DEFAULT 1,
    level INT DEFAULT 0,
    prefix VARCHAR(50),
    stats JSON,
    special VARCHAR(100),
    description TEXT,
    equipped_char_index INT DEFAULT -1,
    gems JSON,
    metadata JSON,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS fishing_slots (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(50),
    fish_name VARCHAR(100),
    start_count BIGINT DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS unlocked_regions (
    user_id VARCHAR(50),
    region_name VARCHAR(100),
    PRIMARY KEY (user_id, region_name),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_life_data (
    user_id VARCHAR(50) PRIMARY KEY,
    data JSON NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
