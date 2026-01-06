CREATE DATABASE IF NOT EXISTS discord_bot_db
    DEFAULT CHARACTER SET = 'utf8mb4'
    DEFAULT COLLATE = 'utf8mb4_unicode_ci';

USE discord_bot_db;

-- --------------------------------------------------------
-- 1. 사용자 정보 (Users)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(20) PRIMARY KEY COMMENT 'Discord User ID',
    pt BIGINT DEFAULT 0,
    money BIGINT DEFAULT 0,
    last_checkin DATE,
    
    -- 현재 선택된 캐릭터 (대표 캐릭터) 인덱스
    investigator_index INT DEFAULT 0,
    
    -- 메인 퀘스트 정보
    main_quest_id INT DEFAULT 0,
    main_quest_current INT DEFAULT 0,
    main_quest_index INT DEFAULT 0,
    
    -- [추가] 마이홈 시설 레벨 (기존 JSON의 myhome.level 대응)
    garden_level INT DEFAULT 1,
    workshop_level INT DEFAULT 1,
    fishing_level INT DEFAULT 1,
    
    -- [추가] 통계 데이터
    total_subjugations INT DEFAULT 0,

    -- 유저 적용 버프 (카페 버프 등) - JSON으로 저장
    buffs JSON COMMENT 'Active buffs data',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- --------------------------------------------------------
-- 2. 캐릭터 (Characters)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS characters (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(20) NOT NULL,
    
    -- [중요] 캐릭터 순서 정렬을 위한 인덱스 (0, 1, 2...)
    char_index INT NOT NULL,
    
    name VARCHAR(50),
    
    -- 기본 스탯
    hp INT DEFAULT 100,
    max_mental INT DEFAULT 100,
    
    -- 전투 스탯
    attack INT DEFAULT 10,
    defense INT DEFAULT 0,
    defense_rate INT DEFAULT 0,
    speed INT DEFAULT 10,
    
    -- 장비 및 덱 정보
    card_slots INT DEFAULT 4,
    
    -- [JSON] 장착한 스킬 카드 목록 (예: ["기본공격", "방어"])
    equipped_cards JSON,
    
    -- [JSON] 상태이상 및 임시 버프 (예: {"bleed": 0})
    status_effects JSON,
    
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    -- 한 유저 내에서 슬롯 번호는 중복될 수 없음
    UNIQUE KEY unique_char_slot (user_id, char_index)
);

-- --------------------------------------------------------
-- 3. 인벤토리 (Inventory)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS inventory (
    user_id VARCHAR(20),
    item_name VARCHAR(100),
    quantity INT DEFAULT 0,
    PRIMARY KEY (user_id, item_name),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- --------------------------------------------------------
-- 4. 아티팩트 (Artifacts)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS artifacts (
    id VARCHAR(50) PRIMARY KEY COMMENT 'UUID string',
    user_id VARCHAR(20),
    name VARCHAR(100),
    
    rank_level INT DEFAULT 1 COMMENT '성급 (1~3)',
    level INT DEFAULT 0 COMMENT '강화 수치 (+0~+5)',
    prefix VARCHAR(50),
    
    -- [JSON] 스탯 정보 (예: {"attack": 5, "defense": 2})
    stats JSON,
    
    -- [추가] 3성 아티팩트 특수 효과 코드
    special VARCHAR(50) DEFAULT NULL,
    
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- --------------------------------------------------------
-- 5. 해금된 지역 (Unlocked Regions)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS unlocked_regions (
    user_id VARCHAR(20),
    region_name VARCHAR(100),
    PRIMARY KEY (user_id, region_name),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- --------------------------------------------------------
-- 6. [신규] 영입 퀘스트 진행도 (Recruit Progress)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS recruit_progress (
    user_id VARCHAR(20),
    char_key VARCHAR(50) COMMENT '영입 대상 키 (예: Yeongsan)',
    progress INT DEFAULT 0 COMMENT '현재 퀘스트 단계',
    PRIMARY KEY (user_id, char_key),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- --------------------------------------------------------
-- 7. 마이홈 - 텃밭 슬롯 (Garden Slots)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS garden_slots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(20),
    slot_index INT,
    planted BOOLEAN DEFAULT FALSE,
    stage INT DEFAULT 0,
    last_invest_count INT DEFAULT 0,
    fertilizer VARCHAR(100),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- --------------------------------------------------------
-- 8. 마이홈 - 비료 보관함 (User Fertilizers)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_fertilizers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(20),
    target VARCHAR(100) COMMENT '수확 시 얻게 될 타겟 아이템',
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- --------------------------------------------------------
-- 9. 마이홈 - 낚시 분해 슬롯 (Fishing Dismantle Slots)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS fishing_slots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(20),
    fish_name VARCHAR(100),
    start_count INT DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- --------------------------------------------------------
-- 10. 마이홈 - 작업실 슬롯 (Workshop Slots)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS workshop_slots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(20),
    slot_index INT,
    craft_item VARCHAR(100),
    start_count INT DEFAULT 0,
    required_count INT DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- --------------------------------------------------------
-- 11. 거래소 (Trades)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS trades (
    id VARCHAR(36) PRIMARY KEY,
    seller_id VARCHAR(20),
    item_name VARCHAR(100),
    quantity INT,
    price INT,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);