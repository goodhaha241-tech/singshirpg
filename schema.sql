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

    -- 마이홈 레벨 (JSON의 myhome 내부 값을 여기로 풀어서 저장)
    garden_level INT DEFAULT 1,
    workshop_level INT DEFAULT 1,
    fishing_level INT DEFAULT 1,
    total_subjugations INT DEFAULT 0,

    -- JSON 형태로 저장할 가벼운 데이터들
    cards JSON,           -- 보유 카드 리스트
    buffs JSON,           -- 적용 중인 버프
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. 인벤토리
CREATE TABLE IF NOT EXISTS inventory (
    user_id VARCHAR(50),
    item_name VARCHAR(100),
    quantity INT,
    PRIMARY KEY (user_id, item_name),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 3. 캐릭터 (보유 캐릭터 목록)
CREATE TABLE IF NOT EXISTS characters (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(50),
    name VARCHAR(100),
    hp INT,
    current_hp INT,
    max_mental INT,
    current_mental INT,
    attack INT,
    defense INT,
    defense_rate INT DEFAULT 0,
    card_slots INT DEFAULT 4,
    equipped_cards JSON, -- 장착한 카드 목록
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 4. 아티팩트
CREATE TABLE IF NOT EXISTS artifacts (
    id VARCHAR(36) PRIMARY KEY, -- UUID
    user_id VARCHAR(50),
    name VARCHAR(100),
    rank_level INT, -- rank 예약어 회피
    grade INT,
    level INT,
    prefix VARCHAR(50),
    stats JSON,
    special VARCHAR(100),
    description TEXT,
    equipped_char_index INT DEFAULT -1, -- 장착된 캐릭터 인덱스 (-1이면 미장착)
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 5. 해금된 지역
CREATE TABLE IF NOT EXISTS unlocked_regions (
    user_id VARCHAR(50),
    region_name VARCHAR(100),
    PRIMARY KEY (user_id, region_name),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 6. 퀘스트/영입 진행도 (recruit_progress)
CREATE TABLE IF NOT EXISTS recruit_progress (
    user_id VARCHAR(50),
    char_key VARCHAR(50), -- 예: 'Yeongsan'
    progress INT DEFAULT 0,
    PRIMARY KEY (user_id, char_key),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 7. 마이홈 - 텃밭 슬롯
CREATE TABLE IF NOT EXISTS garden_slots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(50),
    slot_index INT,
    planted BOOLEAN DEFAULT FALSE,
    plant_name VARCHAR(100),
    stage INT DEFAULT 0,
    last_invest_count INT DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 8. 마이홈 - 비료 (JSON의 fertilizers)
CREATE TABLE IF NOT EXISTS user_fertilizers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(50),
    target VARCHAR(100),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 9. 마이홈 - 작업실 슬롯
CREATE TABLE IF NOT EXISTS workshop_slots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(50),
    slot_index INT,
    craft_item VARCHAR(100),
    start_count INT DEFAULT 0,
    required_count INT DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 10. 마이홈 - 낚시 분해 슬롯
CREATE TABLE IF NOT EXISTS fishing_slots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(50),
    fish_name VARCHAR(100),
    start_count INT DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);