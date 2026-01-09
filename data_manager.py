import aiomysql
import json
import os
import logging
from config import DB_CONFIG

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_pool = None

async def get_db_pool():
    global _pool
    if _pool is None:
        try:
            _pool = await aiomysql.create_pool(**DB_CONFIG)
            logger.info("DB Pool Created")
            await check_schema(_pool) # 풀 생성 시 스키마 체크
        except Exception as e:
            # DB가 없어서 연결 실패한 경우 (에러 코드 1049: Unknown database)
            if hasattr(e, 'args') and e.args[0] == 1049:
                logger.warning(f"데이터베이스 '{DB_CONFIG['db']}'가 없어서 생성을 시도합니다.")
                try:
                    # DB 지정 없이 연결하여 생성 시도
                    temp_conf = DB_CONFIG.copy()
                    temp_conf.pop('db', None)
                    async with aiomysql.create_pool(**temp_conf) as temp_pool:
                        async with temp_pool.acquire() as conn:
                            async with conn.cursor() as cur:
                                await cur.execute(f"CREATE DATABASE IF NOT EXISTS {DB_CONFIG['db']}")
                    
                    # 생성 후 다시 연결 시도
                    _pool = await aiomysql.create_pool(**DB_CONFIG)
                    logger.info("DB Pool Created (New DB)")
                    await check_schema(_pool)
                except Exception as create_err:
                    logger.error(f"데이터베이스 생성 실패: {create_err}")
                    raise e
            else:
                logger.error(f"DB Pool Creation Failed: {e}")
                raise e
    return _pool

async def check_schema(pool):
    """schema.sql 내용을 실행하거나 테이블 존재 여부 확인"""
    if not os.path.exists("schema.sql"):
        return

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # users 테이블이 있는지 확인
            await cur.execute("SHOW TABLES LIKE 'users'")
            if not await cur.fetchone():
                logger.info("기본 테이블이 없어 schema.sql을 실행합니다...")
                if os.path.exists("schema.sql"):
                    with open("schema.sql", "r", encoding="utf-8") as f:
                        sql = f.read()
                    for stmt in sql.split(';'):
                        if stmt.strip() and not stmt.upper().startswith(("CREATE DATABASE", "USE")):
                            try: await cur.execute(stmt)
                            except: continue
            
            # 컬럼 존재 여부 일괄 확인 및 추가 (성능 최적화)
            # 1. users 테이블
            await cur.execute("DESCRIBE users")
            u_cols = [r[0] for r in await cur.fetchall()]
            
            updates = [
                ("main_quest_progress", "JSON"),
                ("total_investigations", "BIGINT DEFAULT 0"),
                ("water_can", "INT DEFAULT 0"),
                ("fishing_rod", "INT DEFAULT 0"),
                ("fishing_spot_level", "INT DEFAULT 0"),
                ("fishing_max_slots", "INT DEFAULT 3"),
                ("max_subjugation_depth", "INT DEFAULT 0"),
                ("daily_quests", "JSON"),
                ("last_quest_date", "DATE"),
                ("construction_step", "INT DEFAULT 0")
            ]
            for col, col_type in updates:
                if col not in u_cols:
                    logger.warning(f"⚠️ 'users' 테이블에 '{col}' 컬럼 추가 중...")
                    await cur.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")

            # 2. artifacts 테이블
            await cur.execute("DESCRIBE artifacts")
            a_cols = [r[0] for r in await cur.fetchall()]
            if "equipped_char_index" not in a_cols:
                await cur.execute("ALTER TABLE artifacts ADD COLUMN equipped_char_index INT DEFAULT -1")

            # 3. garden_slots 테이블
            await cur.execute("DESCRIBE garden_slots")
            g_cols = [r[0] for r in await cur.fetchall()]
            if "plant_name" not in g_cols:
                await cur.execute("ALTER TABLE garden_slots ADD COLUMN plant_name VARCHAR(100)")
            if "fertilizer" not in g_cols:
                await cur.execute("ALTER TABLE garden_slots ADD COLUMN fertilizer VARCHAR(100)")

            # 4. characters 테이블 (equipped_engraved_artifact 추가)
            await cur.execute("DESCRIBE characters")
            c_cols = [r[0] for r in await cur.fetchall()]
            if "equipped_engraved_artifact" not in c_cols:
                logger.warning("⚠️ 'characters' 테이블에 'equipped_engraved_artifact' 컬럼 추가 중...")
                await cur.execute("ALTER TABLE characters ADD COLUMN equipped_engraved_artifact JSON")

            # users 테이블의 total_subjugations 컬럼을 BIGINT로 확장
            try:
                await cur.execute("ALTER TABLE users MODIFY COLUMN total_subjugations BIGINT DEFAULT 0")
            except Exception as e:
                # 이미 BIGINT이거나 컬럼이 없는 경우 등 예외 처리
                logger.warning(f"⚠️ 'total_subjugations' 컬럼 수정 시도 중 알림: {e}")

            # inventory 수량 및 각 테이블의 PK ID 확장
            try:
                # 인벤토리 수량 확장
                await cur.execute("ALTER TABLE inventory MODIFY COLUMN quantity BIGINT DEFAULT 0")
                
                # 주요 테이블 PK ID 확장 (AUTO_INCREMENT 유지)
                await cur.execute("ALTER TABLE characters MODIFY COLUMN id BIGINT AUTO_INCREMENT")
                await cur.execute("ALTER TABLE garden_slots MODIFY COLUMN id BIGINT AUTO_INCREMENT")
                await cur.execute("ALTER TABLE workshop_slots MODIFY COLUMN id BIGINT AUTO_INCREMENT")
                await cur.execute("ALTER TABLE fishing_slots MODIFY COLUMN id BIGINT AUTO_INCREMENT")
                
                logger.info("✅ 인벤토리 수량 및 PK ID BIGINT 확장 완료")
            except Exception as e:
                logger.warning(f"⚠️ 컬럼 타입 확장 중 알림: {e}")

            # fishing_slots 테이블 확인 (없으면 생성)
            try:
                await cur.execute("SELECT 1 FROM fishing_slots LIMIT 1")
            except (aiomysql.Error, Exception):
                logger.warning("⚠️ 'fishing_slots' 테이블이 없어 생성합니다.")
                try:
                    with open("schema.sql", "r", encoding="utf-8") as f:
                        sql = f.read()
                    # schema.sql에서 fishing_slots 생성 구문만 찾아서 실행하거나, 직접 쿼리 실행
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS fishing_slots (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            user_id VARCHAR(50),
                            fish_name VARCHAR(100),
                            start_count INT DEFAULT 0,
                            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                        )
                    """)
                except Exception as e:
                    logger.error(f"테이블 생성 실패: {e}")

async def _get_new_user_data(user_name=None):
    """Returns the default data structure for a new user."""
    from character import DEFAULT_PLAYER_DATA
    new_char = DEFAULT_PLAYER_DATA.copy()
    new_char["name"] = user_name if user_name else "플레이어"
    
    return {
        "pt": 0, "money": 0, "last_checkin": None,
        "investigator_index": 0,
        "main_quest_id": 0, "main_quest_current": 0, "main_quest_index": 0,
        "cards": ["기본공격", "기본방어", "기본반격"],
        "buffs": {},
        "main_quest_progress": {},
        "inventory": {},
        "characters": [new_char],
        "artifacts": [],
        "unlocked_regions": ["기원의 쌍성"],
        "recruit_progress": {},
        "myhome": {
            "garden": {"level": 1, "slots": [], "water_can": 0},
            "workshop_level": 1, "workshop_slots": [],
            "fishing_level": 1,
            "fishing": {"dismantle_slots": [], "rod": 0, "spot_level": 0, "max_dismantle_slots": 3},
            "total_investigations": 0,
            "total_subjugations": 0,
            "construction_step": 0,
            "max_subjugation_depth": 0
        },
        "daily_quests": [],
        "last_quest_date": None,
        "fertilizers": []
    }

async def _get_inventory(cur, user_id):
    """Fetches user's inventory."""
    await cur.execute("SELECT item_name, quantity FROM inventory WHERE user_id = %s", (str(user_id),))
    return {row['item_name']: row['quantity'] for row in await cur.fetchall()}

async def _get_characters_and_artifacts(cur, user_id):
    """Fetches characters and artifacts, linking them."""
    # Characters
    await cur.execute("SELECT * FROM characters WHERE user_id = %s", (str(user_id),))
    char_rows = await cur.fetchall()
    characters = []
    for row in char_rows:
        char_data = {
            "name": row['name'],
            "hp": row['hp'],
            "current_hp": row['current_hp'],
            "max_mental": row['max_mental'],
            "current_mental": row['current_mental'],
            "attack": row['attack'],
            "defense": row['defense'],
            "defense_rate": row['defense_rate'],
            "card_slots": row['card_slots'],
            "equipped_cards": json.loads(row['equipped_cards']) if row['equipped_cards'] else [],
            "equipped_engraved_artifact": json.loads(row['equipped_engraved_artifact']) if row.get('equipped_engraved_artifact') else None,
            "status_effects": {}, 
            "is_recruited": True,
            "is_down": False
        }
        characters.append(char_data)

    # Artifacts
    await cur.execute("SELECT * FROM artifacts WHERE user_id = %s", (str(user_id),))
    art_rows = await cur.fetchall()
    artifacts = []
    for row in art_rows:
        art = {
            "id": row['id'],
            "name": row['name'],
            "rank": row['rank_level'],
            "grade": row['grade'],
            "level": row['level'],
            "prefix": row['prefix'],
            "stats": json.loads(row['stats']) if row['stats'] else {},
            "special": row['special'],
            "description": row['description'],
            "equipped_char_index": row.get('equipped_char_index', -1)
        }
        artifacts.append(art)
        
        # Link equipped artifact to character
        eq_idx = row.get('equipped_char_index', -1)
        if eq_idx != -1 and 0 <= eq_idx < len(characters):
            characters[eq_idx]["equipped_artifact"] = art
            
    return characters, artifacts

async def _get_unlocked_regions(cur, user_id):
    """Fetches unlocked regions."""
    await cur.execute("SELECT region_name FROM unlocked_regions WHERE user_id = %s", (str(user_id),))
    regions = [r['region_name'] for r in await cur.fetchall()]
    return regions if regions else ["기원의 쌍성"]

async def _get_recruit_progress(cur, user_id):
    """Fetches recruitment progress."""
    await cur.execute("SELECT char_key, progress FROM recruit_progress WHERE user_id = %s", (str(user_id),))
    return {r['char_key']: r['progress'] for r in await cur.fetchall()}

async def _get_myhome_data(cur, user_id, user_row):
    """Fetches and assembles all MyHome related data."""
    # Garden
    await cur.execute("SELECT * FROM garden_slots WHERE user_id = %s ORDER BY slot_index", (str(user_id),))
    g_slots = [{"planted": bool(r['planted']), "plant_name": r['plant_name'], "stage": r['stage'], "last_invest_count": r['last_invest_count'], "fertilizer": r['fertilizer']} for r in await cur.fetchall()]
    
    # Workshop
    await cur.execute("SELECT * FROM workshop_slots WHERE user_id = %s", (str(user_id),))
    w_slots = [{"slot_index": r['slot_index'], "craft_item": r['craft_item'], "start_count": r['start_count'], "required_count": r['required_count']} for r in await cur.fetchall()]

    # Fishing
    await cur.execute("SELECT * FROM fishing_slots WHERE user_id = %s", (str(user_id),))
    f_slots = [{"fish": r['fish_name'], "start_count": r['start_count']} for r in await cur.fetchall()]

    return {
        "garden": {"level": user_row['garden_level'] or 1, "slots": g_slots, "water_can": user_row['water_can'] or 0},
        "workshop_level": user_row['workshop_level'] or 1,
        "workshop_slots": w_slots,
        "fishing_level": user_row['fishing_level'] or 1,
        "total_investigations": user_row['total_investigations'] or 0,
        "fishing": {"dismantle_slots": f_slots, "rod": user_row['fishing_rod'] or 0, "spot_level": user_row['fishing_spot_level'] or 0, "max_dismantle_slots": user_row['fishing_max_slots'] or 3},
        "total_subjugations": user_row['total_subjugations'] or 0,
        "max_subjugation_depth": user_row.get('max_subjugation_depth') or 0,
        "construction_step": user_row.get('construction_step', 0)
    }

async def get_user_data(user_id, user_name=None):
    """DB에서 유저 데이터를 로드하여 딕셔너리 형태로 반환합니다."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM users WHERE user_id = %s", (str(user_id),))
            user_row = await cur.fetchone()
            
            if not user_row:
                return await _get_new_user_data(user_name)

            # 각 부분별 데이터 로드
            inventory = await _get_inventory(cur, user_id)
            characters, artifacts = await _get_characters_and_artifacts(cur, user_id)
            unlocked_regions = await _get_unlocked_regions(cur, user_id)
            recruit_progress = await _get_recruit_progress(cur, user_id)
            myhome_data = await _get_myhome_data(cur, user_id, user_row)

            await cur.execute("SELECT target FROM user_fertilizers WHERE user_id = %s", (str(user_id),))
            fertilizers = [{"target": r['target']} for r in await cur.fetchall()]

            return {
                "pt": user_row['pt'] or 0,
                "money": user_row['money'] or 0,
                "last_checkin": str(user_row['last_checkin']) if user_row['last_checkin'] else None,
                "investigator_index": user_row['investigator_index'] or 0,
                "main_quest_id": user_row['main_quest_id'] or 0,
                "main_quest_current": user_row['main_quest_current'] or 0,
                "main_quest_index": user_row['main_quest_index'] or 0,
                "main_quest_progress": json.loads(user_row['main_quest_progress']) if user_row.get('main_quest_progress') else {},
                "cards": json.loads(user_row['cards']) if user_row['cards'] else ["기본공격", "기본방어", "기본반격"],
                "buffs": json.loads(user_row['buffs']) if user_row['buffs'] else {},
                "inventory": inventory,
                "characters": characters,
                "artifacts": artifacts,
                "unlocked_regions": unlocked_regions,
                "recruit_progress": recruit_progress,
                "myhome": myhome_data,
                "fertilizers": fertilizers,
                "daily_quests": json.loads(user_row['daily_quests']) if user_row.get('daily_quests') else [],
                "last_quest_date": str(user_row['last_quest_date']) if user_row.get('last_quest_date') else None
            }

async def save_user_data(user_id, data):
    """
    [핵심] Python 딕셔너리(JSON 구조)를 받아서 RDB 테이블들에 분산 저장(Upsert)합니다.
    migrate.py는 이 함수 하나만 믿고 데이터를 던집니다.
    """
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                # [신규] 아티팩트 소유자 매핑 (캐릭터 -> 아티팩트 ID)
                # 캐릭터 정보에 있는 equipped_artifact를 기준으로 artifacts 테이블의 equipped_char_index를 갱신하기 위함
                artifact_owner_map = {}
                chars = data.get("characters", [])
                for idx, c in enumerate(chars):
                    eq_art = c.get("equipped_artifact")
                    if eq_art and isinstance(eq_art, dict):
                        art_id = eq_art.get("id")
                        if art_id:
                            artifact_owner_map[art_id] = idx

                # ---------------------------------------------------------
                # 1. USERS 테이블 (기본 정보 + 마이홈 레벨 추출)
                # ---------------------------------------------------------
                myhome = data.get("myhome", {})
                
                # JSON 필드 직렬화
                cards_json = json.dumps(data.get("cards", []))
                buffs_json = json.dumps(data.get("buffs", {}))
                mq_prog_json = json.dumps(data.get("main_quest_progress", {}))
                daily_quests_json = json.dumps(data.get("daily_quests", []))
                
                # 마이홈 레벨 추출 (없으면 기본값 1)
                g_lvl = myhome.get("garden", {}).get("level") or 1
                w_can = myhome.get("garden", {}).get("water_can") or 0
                # JSON 구조에 따라 위치가 다를 수 있음, 안전하게 탐색
                w_lvl = myhome.get("workshop_level") or myhome.get("level") or 1
                f_lvl = myhome.get("fishing_level") or 1
                f_rod = myhome.get("fishing", {}).get("rod") or 0
                f_spot = myhome.get("fishing", {}).get("spot_level") or 0
                t_subj = myhome.get("total_subjugations") or 0
                m_depth = myhome.get("max_subjugation_depth") or 0
                t_invest = myhome.get("total_investigations") or 0

                sql_users = """
                    INSERT INTO users 
                    (user_id, pt, money, last_checkin, investigator_index, 
                     main_quest_id, main_quest_current, main_quest_index,
                     garden_level, water_can, workshop_level, fishing_level, fishing_rod, fishing_spot_level, total_subjugations, cards, buffs, main_quest_progress, total_investigations, fishing_max_slots, max_subjugation_depth, daily_quests, last_quest_date, construction_step)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) AS new
                    ON DUPLICATE KEY UPDATE
                    pt=new.pt, money=new.money, last_checkin=new.last_checkin,
                    investigator_index=new.investigator_index,
                    main_quest_id=new.main_quest_id, 
                    main_quest_current=new.main_quest_current,
                    main_quest_index=new.main_quest_index,
                    garden_level=new.garden_level, 
                    water_can=new.water_can, 
                    workshop_level=new.workshop_level,
                    fishing_level=new.fishing_level, 
                    fishing_rod=new.fishing_rod, 
                    fishing_spot_level=new.fishing_spot_level,
                    total_subjugations=new.total_subjugations,
                    cards=new.cards, buffs=new.buffs, 
                    main_quest_progress=new.main_quest_progress, 
                    total_investigations=new.total_investigations,
                    fishing_max_slots=new.fishing_max_slots,
                    max_subjugation_depth=new.max_subjugation_depth,
                    daily_quests=new.daily_quests,
                    last_quest_date=new.last_quest_date,
                    construction_step=new.construction_step
                """
                await cur.execute(sql_users, (
                    str(user_id), data.get("pt", 0), data.get("money", 0), data.get("last_checkin"),
                    data.get("investigator_index", 0),
                    data.get("main_quest_id", 0), data.get("main_quest_current", 0), data.get("main_quest_index", 0),
                    g_lvl, w_can, w_lvl, f_lvl, f_rod, f_spot, t_subj, 
                    cards_json, buffs_json, mq_prog_json, t_invest,
                    myhome.get("fishing", {}).get("max_dismantle_slots", 3),
                    m_depth,
                    daily_quests_json, data.get("last_quest_date"),
                    myhome.get("construction_step", 0)
                ))

                # ---------------------------------------------------------
                # 2. INVENTORY (전체 삭제 후 재삽입)
                # ---------------------------------------------------------
                await cur.execute("DELETE FROM inventory WHERE user_id = %s", (user_id,))
                inventory = data.get("inventory", {})
                if inventory:
                    inv_list = [(user_id, k, v) for k, v in inventory.items() if v > 0]
                    if inv_list:
                        await cur.executemany("INSERT INTO inventory (user_id, item_name, quantity) VALUES (%s, %s, %s)", inv_list)

                # ---------------------------------------------------------
                # 3. CHARACTERS (전체 삭제 후 재삽입)
                # ---------------------------------------------------------
                await cur.execute("DELETE FROM characters WHERE user_id = %s", (user_id,))
                chars = data.get("characters", [])
                if chars:
                    char_rows = []
                    for c in chars:
                        char_rows.append((
                            user_id, c.get("name", "Unknown"), c.get("hp", 100), c.get("current_hp", 100),
                            c.get("max_mental", 50), c.get("current_mental", 50),
                            c.get("attack", 5), c.get("defense", 0), c.get("defense_rate", 0),
                            c.get("card_slots", 4), json.dumps(c.get("equipped_cards", []))
                            , json.dumps(c.get("equipped_engraved_artifact")) if c.get("equipped_engraved_artifact") else None
                        ))
                    await cur.executemany("""
                        INSERT INTO characters (user_id, name, hp, current_hp, max_mental, current_mental, 
                        attack, defense, defense_rate, card_slots, equipped_cards, equipped_engraved_artifact)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, char_rows)

                # ---------------------------------------------------------
                # 4. ARTIFACTS
                # ---------------------------------------------------------
                await cur.execute("DELETE FROM artifacts WHERE user_id = %s", (user_id,))
                arts = data.get("artifacts", [])
                if arts:
                    art_rows = []
                    for a in arts:
                        # [수정] 매핑된 소유자 정보가 있으면 우선 사용
                        owner_idx = artifact_owner_map.get(a.get("id"), a.get("equipped_char_index", -1))

                        art_rows.append((
                            a.get("id"), user_id, a.get("name"), a.get("rank", 1), a.get("grade", 1),
                            a.get("level", 0), a.get("prefix", ""), json.dumps(a.get("stats", {})),
                            a.get("special"), a.get("description"), owner_idx
                        ))
                    await cur.executemany("""
                        INSERT INTO artifacts (id, user_id, name, rank_level, grade, level, prefix, stats, special, description, equipped_char_index)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, art_rows)

                # ---------------------------------------------------------
                # 5. UNLOCKED REGIONS
                # ---------------------------------------------------------
                await cur.execute("DELETE FROM unlocked_regions WHERE user_id = %s", (user_id,))
                regions = data.get("unlocked_regions", [])
                if regions:
                    reg_rows = [(user_id, r) for r in regions]
                    await cur.executemany("INSERT INTO unlocked_regions (user_id, region_name) VALUES (%s, %s)", reg_rows)

                # ---------------------------------------------------------
                # 6. MYHOME SUB-TABLES (Garden, Fertilizer, etc.)
                # ---------------------------------------------------------
                # (1) Garden Slots
                await cur.execute("DELETE FROM garden_slots WHERE user_id = %s", (user_id,))
                g_slots = myhome.get("garden", {}).get("slots", [])
                if g_slots:
                    g_rows = []
                    for idx, s in enumerate(g_slots):
                        g_rows.append((
                            user_id, idx, s.get("planted", False), s.get("plant_name"),
                            s.get("stage", 0), s.get("last_invest_count", 0), s.get("fertilizer")
                        ))
                    await cur.executemany("""
                        INSERT INTO garden_slots (user_id, slot_index, planted, plant_name, stage, last_invest_count, fertilizer)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, g_rows)

                # (2) Fertilizers
                await cur.execute("DELETE FROM user_fertilizers WHERE user_id = %s", (user_id,))
                ferts = data.get("fertilizers", [])
                if ferts:
                    f_rows = [(user_id, f.get("target")) for f in ferts]
                    await cur.executemany("INSERT INTO user_fertilizers (user_id, target) VALUES (%s, %s)", f_rows)

                # (3) Workshop Slots
                await cur.execute("DELETE FROM workshop_slots WHERE user_id = %s", (user_id,))
                w_slots = myhome.get("workshop_slots", [])
                if w_slots:
                    w_rows = []
                    for s in w_slots:
                        w_rows.append((
                            user_id, s.get("slot_index", 0), s.get("craft_item"), 
                            s.get("start_count", 0), s.get("required_count", 0)
                        ))
                    await cur.executemany("INSERT INTO workshop_slots (user_id, slot_index, craft_item, start_count, required_count) VALUES (%s, %s, %s, %s, %s)", w_rows)

                # (4) Fishing Slots (Dismantle)
                await cur.execute("DELETE FROM fishing_slots WHERE user_id = %s", (user_id,))
                f_slots = myhome.get("fishing", {}).get("dismantle_slots", [])
                if f_slots:
                    f_rows = []
                    for s in f_slots:
                        f_rows.append((
                            user_id, s.get("fish"), s.get("start_count", 0)
                        ))
                    await cur.executemany("INSERT INTO fishing_slots (user_id, fish_name, start_count) VALUES (%s, %s, %s)", f_rows)

                # ---------------------------------------------------------
                # 7. RECRUIT PROGRESS (전체 삭제 후 재삽입)
                # ---------------------------------------------------------
                await cur.execute("DELETE FROM recruit_progress WHERE user_id = %s", (user_id,))
                recruit_progress = data.get("recruit_progress", {})
                if recruit_progress:
                    rp_rows = []
                    for char_key, progress in recruit_progress.items():
                        rp_rows.append((user_id, char_key, progress))
                    await cur.executemany("INSERT INTO recruit_progress (user_id, char_key, progress) VALUES (%s, %s, %s)", rp_rows)



                await conn.commit()
                # logger.info(f"Saved data for user {user_id}")

            except Exception as e:
                await conn.rollback()
                logger.error(f"Save Error for {user_id}: {e}")
                raise e

async def get_subjugation_ranking(limit=10):
    """최대 탐사 층수 기준 상위 유저를 가져옵니다."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("""
                SELECT user_id, max_subjugation_depth 
                FROM users 
                WHERE max_subjugation_depth > 0 
                ORDER BY max_subjugation_depth DESC 
                LIMIT %s
            """, (limit,))
            return await cur.fetchall()