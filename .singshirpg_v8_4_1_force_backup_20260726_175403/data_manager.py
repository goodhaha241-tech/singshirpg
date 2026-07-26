import aiomysql
import json
import os
import logging
import copy
import random
import datetime
import asyncio
from collections import defaultdict
from config import DB_CONFIG
from character import DEFAULT_PLAYER_DATA

logger = logging.getLogger(__name__)

# stability-v1 + cumulative-v2 + cumulative-v3 integrated baseline
# guild-pvp-stability-v7.2
# rollback-guard-appraisal-gems-v8

_pool = None
_user_save_locks = defaultdict(asyncio.Lock)


class StaleUserDataError(RuntimeError):
    """An old Discord view attempted to overwrite a newer saved snapshot."""

    def __init__(self, user_id, loaded_revision, current_revision):
        self.user_id = str(user_id)
        self.loaded_revision = int(loaded_revision)
        self.current_revision = int(current_revision)
        super().__init__(
            "다른 화면에서 데이터가 먼저 변경되었습니다. "
            "최신 상태를 보호하기 위해 저장을 중단했습니다. 메뉴를 다시 열어주세요."
        )

async def get_db_pool():
    global _pool
    if _pool is None:
        try:
            _pool = await aiomysql.create_pool(**DB_CONFIG)
            logger.info("DB Pool Created")
            await check_schema(_pool)
        except Exception as e:
            if hasattr(e, 'args') and e.args[0] == 1049:
                logger.warning(f"데이터베이스 '{DB_CONFIG['db']}'가 없어서 생성을 시도합니다.")
                try:
                    temp_conf = DB_CONFIG.copy()
                    temp_conf.pop('db', None)
                    async with aiomysql.create_pool(**temp_conf) as temp_pool:
                        async with temp_pool.acquire() as conn:
                            async with conn.cursor() as cur:
                                await cur.execute(f"CREATE DATABASE IF NOT EXISTS {DB_CONFIG['db']}")
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
    if not os.path.exists("schema.sql"): return
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            async def create_table_if_missing(table_name, create_sql):
                """Avoid MySQL 1050 warnings by checking before CREATE TABLE."""
                await cur.execute(
                    """SELECT 1
                       FROM information_schema.tables
                       WHERE table_schema=DATABASE() AND table_name=%s
                       LIMIT 1""",
                    (table_name,),
                )
                if not await cur.fetchone():
                    await cur.execute(create_sql)

            await cur.execute("SHOW TABLES LIKE 'users'")
            if not await cur.fetchone():
                with open("schema.sql", "r", encoding="utf-8") as f:
                    for stmt in f.read().split(';'):
                        if stmt.strip() and not stmt.upper().startswith(("CREATE DATABASE", "USE")):
                            try: await cur.execute(stmt)
                            except: continue
            
            # 길드 테이블 확인
            try:
                await create_table_if_missing("guilds", """CREATE TABLE guilds (
                        guild_id INT AUTO_INCREMENT PRIMARY KEY,
                        name VARCHAR(50) NOT NULL UNIQUE,
                        owner_id VARCHAR(50),
                        level INT DEFAULT 1,
                        exp INT DEFAULT 0,
                        member_count INT DEFAULT 1,
                        token_wood INT DEFAULT 0, token_iron INT DEFAULT 0,
                        token_magic INT DEFAULT 0, token_sorcery INT DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )""")
                await create_table_if_missing("guild_members", """CREATE TABLE guild_members (
                        guild_id INT, user_id VARCHAR(50), role VARCHAR(20) DEFAULT 'member',
                        contribution INT DEFAULT 0, joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (guild_id, user_id), FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
                    )""")
                await create_table_if_missing("guild_inventory", """CREATE TABLE guild_inventory (
                        guild_id INT, item_name VARCHAR(100), count INT DEFAULT 0, category VARCHAR(50),
                        PRIMARY KEY (guild_id, item_name), FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
                    )""")
                await create_table_if_missing("guild_stored_artifacts", """CREATE TABLE guild_stored_artifacts (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY, guild_id INT, artifact_id VARCHAR(100),
                        name VARCHAR(100), rank_level INT, level INT, data JSON,
                        stored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
                    )""")
                await create_table_if_missing("guild_log", """CREATE TABLE guild_log (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY, guild_id INT, user_id VARCHAR(50),
                        user_name VARCHAR(100), action_type VARCHAR(50), item_name VARCHAR(100),
                        count INT, logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
                    )""")
            except Exception as e: logger.error(f"Guild Table Error: {e}")

            # 컬럼 추가
            await cur.execute("DESCRIBE users")
            u_cols = [r[0] for r in await cur.fetchall()]
            required_user_columns = [
                ("guild_rank", "VARCHAR(20)"),
                ("guild_data", "JSON"),
                ("characters", "JSON"),
                ("fishing_max_slots", "INT NOT NULL DEFAULT 3"),
                ("max_subjugation_depth", "INT NOT NULL DEFAULT 0"),
                ("daily_quests", "JSON"),
                ("last_quest_date", "DATE"),
                ("construction_step", "INT NOT NULL DEFAULT 0"),
                ("current_dungeon", "JSON"),
                ("max_subjugation_char", "VARCHAR(100)"),
                ("max_subjugation_region", "VARCHAR(100)"),
                ("data_revision", "BIGINT NOT NULL DEFAULT 0"),
            ]
            for col, typ in required_user_columns:
                if col not in u_cols:
                    try:
                        await cur.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")
                    except Exception as e:
                        logger.warning("users.%s migration skipped: %s", col, e)
            if "total_turns" not in u_cols:
                try:
                    await cur.execute("ALTER TABLE users ADD COLUMN total_turns BIGINT NOT NULL DEFAULT 0")
                    await cur.execute(
                        "UPDATE users SET total_turns=GREATEST(COALESCE(total_investigations,0),"
                        " COALESCE(total_subjugations,0)) WHERE total_turns=0"
                    )
                except Exception as e:
                    logger.warning("total_turns migration skipped: %s", e)

            await create_table_if_missing("user_life_data", """CREATE TABLE user_life_data (
                user_id VARCHAR(50) PRIMARY KEY,
                data JSON NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )""")
            await create_table_if_missing("user_save_history", """CREATE TABLE user_save_history (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                user_id VARCHAR(50) NOT NULL,
                revision BIGINT NOT NULL,
                data JSON NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_user_revision (user_id, revision),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )""")
            try:
                await cur.execute("DESCRIBE workshop_slots")
                workshop_cols = [r[0] for r in await cur.fetchall()]
                if "start_count" not in workshop_cols:
                    await cur.execute(
                        "ALTER TABLE workshop_slots ADD COLUMN start_count BIGINT NOT NULL DEFAULT 0"
                    )
                if "required_count" not in workshop_cols:
                    await cur.execute(
                        "ALTER TABLE workshop_slots ADD COLUMN required_count BIGINT NOT NULL DEFAULT 0"
                    )
            except Exception as e:
                logger.warning("Workshop schema migration skipped: %s", e)
            try:
                await cur.execute("DESCRIBE artifacts")
                art_cols = [r[0] for r in await cur.fetchall()]
                if "gems" not in art_cols:
                    await cur.execute("ALTER TABLE artifacts ADD COLUMN gems JSON")
                if "metadata" not in art_cols:
                    await cur.execute("ALTER TABLE artifacts ADD COLUMN metadata JSON")
            except Exception as e:
                logger.warning("Artifact v5 schema migration skipped: %s", e)

            await cur.execute("""INSERT INTO guilds
                (guild_id, name, owner_id, level, exp, member_count)
                VALUES (1, '공용 길드', NULL, 1, 0, 0)
                ON DUPLICATE KEY UPDATE name='공용 길드'""")
            await conn.commit()

async def _get_new_user_data(user_name=None):
    new_char = copy.deepcopy(DEFAULT_PLAYER_DATA)
    new_char["name"] = user_name if user_name else "플레이어"
    return {
        "_data_revision": 0,
        "pt": 0, "money": 0, "last_checkin": None, "investigator_index": 0,
        "main_quest_id": 0, "main_quest_current": 0, "main_quest_index": 0,
        "cards": ["기본공격", "기본방어", "기본반격"], "buffs": {}, "main_quest_progress": {},
        "inventory": {}, "characters": [new_char], "artifacts": [],
        "current_dungeon": {}, "unlocked_regions": ["기원의 쌍성"], "recruit_progress": {},
        "myhome": {"garden": {"level": 1, "slots": [], "water_can": 0}, "workshop_level": 1, "workshop_slots": [], "fishing_level": 1, "fishing": {"dismantle_slots": [], "rod": 0, "spot_level": 0, "max_dismantle_slots": 3}, "total_investigations": 0, "total_subjugations": 0, "total_turns": 0, "construction_step": 0},
        "daily_quests": [], "last_quest_date": None, "fertilizers": [],
        "guild_rank": None, "guild_data": {}, "life_data": {}
    }

async def _get_inventory(cur, user_id):
    await cur.execute("SELECT item_name, quantity FROM inventory WHERE user_id = %s", (str(user_id),))
    return {row['item_name']: row['quantity'] for row in await cur.fetchall()}

async def _get_characters_and_artifacts(cur, user_id):
    await cur.execute("SELECT * FROM characters WHERE user_id = %s", (str(user_id),))
    char_rows = await cur.fetchall()
    characters = []
    for row in char_rows:
        char_data = {
            "name": row['name'], "hp": row['hp'], "current_hp": row['current_hp'],
            "max_mental": row['max_mental'], "current_mental": row['current_mental'],
            "attack": row['attack'], "defense": row['defense'], "defense_rate": row['defense_rate'],
            "card_slots": row['card_slots'],
            "equipped_cards": json.loads(row['equipped_cards']) if row['equipped_cards'] else [],
            "equipped_engraved_artifact": json.loads(row['equipped_engraved_artifact']) if row.get('equipped_engraved_artifact') else None,
            "status_effects": {}, "is_recruited": True, "is_down": False
        }
        characters.append(char_data)

    await cur.execute("SELECT * FROM artifacts WHERE user_id = %s", (str(user_id),))
    art_rows = await cur.fetchall()
    artifacts = []
    for row in art_rows:
        art = {
            "id": row['id'], "name": row['name'], "rank": row['rank_level'], "grade": row['grade'],
            "level": row['level'], "prefix": row['prefix'], "stats": json.loads(row['stats']) if row['stats'] else {},
            "special": row['special'], "description": row['description'],
            "equipped_char_index": row.get('equipped_char_index', -1),
            "gems": json.loads(row["gems"]) if row.get("gems") else [],
            "metadata": json.loads(row["metadata"]) if row.get("metadata") else {},
        }
        artifacts.append(art)
        eq_idx = row.get('equipped_char_index', -1)
        if eq_idx != -1 and 0 <= eq_idx < len(characters):
            characters[eq_idx]["equipped_artifact"] = art
    return characters, artifacts

async def _get_myhome_data(cur, user_id, user_row):
    await cur.execute("SELECT * FROM garden_slots WHERE user_id = %s ORDER BY slot_index", (str(user_id),))
    g_slots = [{"planted": bool(r['planted']), "plant_name": r['plant_name'], "stage": r['stage'], "last_invest_count": r['last_invest_count'], "fertilizer": r['fertilizer']} for r in await cur.fetchall()]
    
    await cur.execute("SELECT * FROM workshop_slots WHERE user_id = %s", (str(user_id),))
    w_slots = [{"slot_index": r['slot_index'], "craft_item": r['craft_item'], "start_count": r['start_count'], "required_count": r['required_count']} for r in await cur.fetchall()]

    await cur.execute("SELECT * FROM fishing_slots WHERE user_id = %s", (str(user_id),))
    f_slots = [{"fish": r['fish_name'], "start_count": r['start_count']} for r in await cur.fetchall()]

    return {
        "garden": {"level": user_row['garden_level'] or 1, "slots": g_slots, "water_can": user_row['water_can'] or 0},
        "workshop_level": user_row['workshop_level'] or 1,
        "workshop_slots": w_slots,
        "fishing_level": user_row['fishing_level'] or 1,
        "total_investigations": user_row['total_investigations'] or 0,
        "total_turns": user_row.get('total_turns') or max(
            user_row['total_investigations'] or 0,
            user_row['total_subjugations'] or 0,
        ),
        "fishing": {"dismantle_slots": f_slots, "rod": user_row['fishing_rod'] or 0, "spot_level": user_row['fishing_spot_level'] or 0, "max_dismantle_slots": user_row['fishing_max_slots'] or 3},
        "total_subjugations": user_row['total_subjugations'] or 0,
        "max_subjugation_depth": user_row.get('max_subjugation_depth') or 0,
        "max_subjugation_char": user_row.get('max_subjugation_char') or "",
        "max_subjugation_region": user_row.get('max_subjugation_region') or "",
        "construction_step": user_row.get('construction_step', 0)
    }

async def get_user_data(user_id, user_name=None):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM users WHERE user_id = %s", (str(user_id),))
            user_row = await cur.fetchone()
            if not user_row: return await _get_new_user_data(user_name)

            inventory = await _get_inventory(cur, user_id)
            characters, artifacts = await _get_characters_and_artifacts(cur, user_id)
            json_chars = user_row.get("characters")
            parsed_json_chars = []
            if json_chars:
                try:
                    parsed_json_chars = (
                        json.loads(json_chars) if isinstance(json_chars, str) else json_chars
                    )
                    if not isinstance(parsed_json_chars, list):
                        parsed_json_chars = []
                except (TypeError, ValueError):
                    logger.warning("Invalid users.characters JSON for user %s", user_id)
                    parsed_json_chars = []

            # The relational character rows remain authoritative for persisted
            # combat stats. Preserve character-specific extension fields from the
            # JSON snapshot so loading does not silently erase them.
            if characters and parsed_json_chars:
                json_by_name = {
                    str(item.get("name")): item
                    for item in parsed_json_chars
                    if isinstance(item, dict) and item.get("name")
                }
                merged_characters = []
                for index, relational in enumerate(characters):
                    extension = json_by_name.get(str(relational.get("name")))
                    if extension is None and index < len(parsed_json_chars):
                        candidate = parsed_json_chars[index]
                        extension = candidate if isinstance(candidate, dict) else None
                    merged = copy.deepcopy(extension) if extension else {}
                    merged.update(relational)
                    if "equipped_artifact" not in relational:
                        merged["equipped_artifact"] = None
                    merged_characters.append(merged)
                characters = merged_characters

            if not characters:
                if parsed_json_chars:
                    characters = parsed_json_chars
            if not characters:
                new_char = copy.deepcopy(DEFAULT_PLAYER_DATA)
                new_char["name"] = f"모험가_{str(user_id)[-4:]}"
                characters = [new_char]

            await cur.execute("SELECT region_name FROM unlocked_regions WHERE user_id = %s", (str(user_id),))
            unlocked_regions = [r['region_name'] for r in await cur.fetchall()] or ["기원의 쌍성"]

            await cur.execute("SELECT char_key, progress FROM recruit_progress WHERE user_id = %s", (str(user_id),))
            recruit_progress = {r['char_key']: r['progress'] for r in await cur.fetchall()}

            myhome_data = await _get_myhome_data(cur, user_id, user_row)
            await cur.execute("SELECT data FROM user_life_data WHERE user_id=%s", (str(user_id),))
            life_row = await cur.fetchone()
            life_data = {}
            if life_row and life_row.get("data"):
                try:
                    life_data = json.loads(life_row["data"]) if isinstance(life_row["data"], str) else life_row["data"]
                except (TypeError, ValueError):
                    logger.warning("Invalid life_data JSON for user %s", user_id)

            await cur.execute("SELECT target FROM user_fertilizers WHERE user_id = %s", (str(user_id),))
            fertilizers = [{"target": r['target']} for r in await cur.fetchall()]

            return {
                "_data_revision": int(user_row.get("data_revision", 0) or 0),
                "pt": user_row['pt'] or 0, "money": user_row['money'] or 0,
                "last_checkin": str(user_row['last_checkin']) if user_row['last_checkin'] else None,
                "investigator_index": user_row['investigator_index'] or 0,
                "main_quest_id": user_row['main_quest_id'] or 0,
                "main_quest_current": user_row['main_quest_current'] or 0,
                "main_quest_index": user_row['main_quest_index'] or 0,
                "main_quest_progress": json.loads(user_row['main_quest_progress']) if user_row.get('main_quest_progress') else {},
                "cards": json.loads(user_row['cards']) if user_row['cards'] else ["기본공격", "기본방어", "기본반격"],
                "buffs": json.loads(user_row['buffs']) if user_row['buffs'] else {},
                "inventory": inventory, "characters": characters, "artifacts": artifacts,
                "unlocked_regions": unlocked_regions, "recruit_progress": recruit_progress,
                "myhome": myhome_data, "fertilizers": fertilizers,
                "daily_quests": json.loads(user_row['daily_quests']) if user_row.get('daily_quests') else [],
                "last_quest_date": str(user_row['last_quest_date']) if user_row.get('last_quest_date') else None,
                "current_dungeon": json.loads(user_row['current_dungeon']) if user_row.get('current_dungeon') else {},
                "guild_rank": user_row.get('guild_rank'),
                "guild_data": json.loads(user_row['guild_data']) if user_row.get('guild_data') else {},
                "life_data": life_data,
            }

async def _save_user_data_unlocked(user_id, data):
    user_key = str(user_id)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                # DB_CONFIG uses autocommit=True. Explicitly bind every replacement
                # table write to a single transaction so a mid-save failure cannot
                # leave a half-written snapshot.
                await conn.begin()
                await cur.execute(
                    "SELECT data_revision FROM users WHERE user_id=%s FOR UPDATE",
                    (user_key,),
                )
                revision_row = await cur.fetchone()
                current_revision = int((revision_row or (0,))[0] or 0)
                loaded_revision = int(data.get("_data_revision", current_revision) or 0)
                if revision_row and loaded_revision != current_revision:
                    raise StaleUserDataError(user_key, loaded_revision, current_revision)
                next_revision = current_revision + 1

                artifact_owner_map = {}
                for idx, c in enumerate(data.get("characters", [])):
                    eq_art = c.get("equipped_artifact")
                    if eq_art and isinstance(eq_art, dict) and eq_art.get("id"):
                        artifact_owner_map[eq_art["id"]] = idx

                myhome = data.get("myhome", {})
                json_cols = {
                    'cards': json.dumps(data.get("cards", [])),
                    'buffs': json.dumps(data.get("buffs", {})),
                    'main_quest_progress': json.dumps(data.get("main_quest_progress", {})),
                    'daily_quests': json.dumps(data.get("daily_quests", [])),
                    'current_dungeon': json.dumps(data.get("current_dungeon", {})),
                    'guild_data': json.dumps(data.get("guild_data", {})),
                    'characters': json.dumps(data.get("characters", []))
                }

                await cur.execute("""
                    INSERT INTO users 
                    (user_id, pt, money, last_checkin, investigator_index, 
                     main_quest_id, main_quest_current, main_quest_index,
                     garden_level, water_can, workshop_level, fishing_level, fishing_rod, fishing_spot_level, total_subjugations, cards, buffs, main_quest_progress, total_investigations, total_turns, fishing_max_slots, max_subjugation_depth, daily_quests, last_quest_date, construction_step, current_dungeon, max_subjugation_char, max_subjugation_region, guild_rank, guild_data, characters)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) AS new
                    ON DUPLICATE KEY UPDATE
                    pt=new.pt, money=new.money, last_checkin=new.last_checkin,
                    investigator_index=new.investigator_index,
                    main_quest_id=new.main_quest_id, main_quest_current=new.main_quest_current, main_quest_index=new.main_quest_index,
                    garden_level=new.garden_level, water_can=new.water_can, workshop_level=new.workshop_level,
                    fishing_level=new.fishing_level, fishing_rod=new.fishing_rod, fishing_spot_level=new.fishing_spot_level,
                    total_subjugations=new.total_subjugations, cards=new.cards, buffs=new.buffs, 
                    main_quest_progress=new.main_quest_progress, total_investigations=new.total_investigations,
                    total_turns=new.total_turns,
                    fishing_max_slots=new.fishing_max_slots, max_subjugation_depth=new.max_subjugation_depth,
                    daily_quests=new.daily_quests, last_quest_date=new.last_quest_date,
                    construction_step=new.construction_step, current_dungeon=new.current_dungeon,
                    max_subjugation_char=new.max_subjugation_char, max_subjugation_region=new.max_subjugation_region,
                    guild_rank=new.guild_rank, guild_data=new.guild_data, characters=new.characters
                """, (
                    str(user_id), data.get("pt", 0), data.get("money", 0), data.get("last_checkin"),
                    data.get("investigator_index", 0),
                    data.get("main_quest_id", 0), data.get("main_quest_current", 0), data.get("main_quest_index", 0),
                    myhome.get("garden", {}).get("level", 1), myhome.get("garden", {}).get("water_can", 0),
                    myhome.get("workshop_level", 1), myhome.get("fishing_level", 1),
                    myhome.get("fishing", {}).get("rod", 0), myhome.get("fishing", {}).get("spot_level", 0),
                    myhome.get("total_subjugations", 0),
                    json_cols['cards'], json_cols['buffs'], json_cols['main_quest_progress'],
                    myhome.get("total_investigations", 0), myhome.get("total_turns", 0),
                    myhome.get("fishing", {}).get("max_dismantle_slots", 3),
                    myhome.get("max_subjugation_depth", 0), json_cols['daily_quests'], data.get("last_quest_date"),
                    myhome.get("construction_step", 0), json_cols['current_dungeon'],
                    myhome.get("max_subjugation_char", ""), myhome.get("max_subjugation_region", ""),
                    data.get("guild_rank"), json_cols['guild_data'], json_cols['characters']
                ))

                await cur.execute(
                    """INSERT INTO user_life_data (user_id, data) VALUES (%s, %s)
                       ON DUPLICATE KEY UPDATE data=VALUES(data)""",
                    (str(user_id), json.dumps(data.get("life_data", {}), ensure_ascii=False)),
                )

                await cur.execute("DELETE FROM inventory WHERE user_id = %s", (user_id,))
                if data.get("inventory"):
                    inv_list = [(user_id, k, v) for k, v in data["inventory"].items() if v > 0]
                    if inv_list: await cur.executemany("INSERT INTO inventory (user_id, item_name, quantity) VALUES (%s, %s, %s)", inv_list)

                await cur.execute("DELETE FROM characters WHERE user_id = %s", (user_id,))
                if data.get("characters"):
                    char_rows = []
                    for c in data["characters"]:
                        char_rows.append((
                            user_id, c.get("name", "Unknown"), c.get("hp", 100), c.get("current_hp", 100),
                            c.get("max_mental", 50), c.get("current_mental", 50), c.get("attack", 5), c.get("defense", 0),
                            c.get("defense_rate", 0), c.get("card_slots", 4), json.dumps(c.get("equipped_cards", [])),
                            json.dumps(c.get("equipped_engraved_artifact")) if c.get("equipped_engraved_artifact") else None
                        ))
                    await cur.executemany("""INSERT INTO characters (user_id, name, hp, current_hp, max_mental, current_mental, attack, defense, defense_rate, card_slots, equipped_cards, equipped_engraved_artifact) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""", char_rows)

                await cur.execute("DELETE FROM artifacts WHERE user_id = %s", (user_id,))
                if data.get("artifacts"):
                    art_rows = []
                    for a in data["artifacts"]:
                        owner_idx = artifact_owner_map.get(a.get("id"), a.get("equipped_char_index", -1))
                        art_rows.append((
                            a.get("id"), user_id, a.get("name"), a.get("rank", 1), a.get("grade", 1),
                            a.get("level", 0), a.get("prefix", ""), json.dumps(a.get("stats", {})),
                            a.get("special"), a.get("description"), owner_idx,
                            json.dumps(a.get("gems", []), ensure_ascii=False),
                            json.dumps(a.get("metadata", {}), ensure_ascii=False),
                        ))
                    await cur.executemany("""INSERT INTO artifacts
                        (id,user_id,name,rank_level,grade,level,prefix,stats,special,
                         description,equipped_char_index,gems,metadata)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", art_rows)

                await cur.execute("DELETE FROM unlocked_regions WHERE user_id = %s", (user_id,))
                if data.get("unlocked_regions"):
                    await cur.executemany("INSERT INTO unlocked_regions (user_id, region_name) VALUES (%s, %s)", [(user_id, r) for r in data["unlocked_regions"]])

                await cur.execute("DELETE FROM garden_slots WHERE user_id = %s", (user_id,))
                if myhome.get("garden", {}).get("slots"):
                    g_rows = [(user_id, i, s.get("planted", False), s.get("plant_name"), s.get("stage", 0), s.get("last_invest_count", 0), s.get("fertilizer")) for i, s in enumerate(myhome["garden"]["slots"])]
                    await cur.executemany("INSERT INTO garden_slots (user_id, slot_index, planted, plant_name, stage, last_invest_count, fertilizer) VALUES (%s, %s, %s, %s, %s, %s, %s)", g_rows)

                await cur.execute("DELETE FROM user_fertilizers WHERE user_id = %s", (user_id,))
                if data.get("fertilizers"):
                    await cur.executemany("INSERT INTO user_fertilizers (user_id, target) VALUES (%s, %s)", [(user_id, f.get("target")) for f in data["fertilizers"]])

                await cur.execute("DELETE FROM workshop_slots WHERE user_id = %s", (user_id,))
                if myhome.get("workshop_slots"):
                    w_rows = [(user_id, s.get("slot_index", 0), s.get("craft_item"), s.get("start_count", 0), s.get("required_count", 0)) for s in myhome["workshop_slots"]]
                    await cur.executemany("INSERT INTO workshop_slots (user_id, slot_index, craft_item, start_count, required_count) VALUES (%s, %s, %s, %s, %s)", w_rows)

                await cur.execute("DELETE FROM fishing_slots WHERE user_id = %s", (user_id,))
                if myhome.get("fishing", {}).get("dismantle_slots"):
                    f_rows = [(user_id, s.get("fish"), s.get("start_count", 0)) for s in myhome["fishing"]["dismantle_slots"]]
                    await cur.executemany("INSERT INTO fishing_slots (user_id, fish_name, start_count) VALUES (%s, %s, %s)", f_rows)

                await cur.execute("DELETE FROM recruit_progress WHERE user_id = %s", (user_id,))
                if data.get("recruit_progress"):
                    await cur.executemany("INSERT INTO recruit_progress (user_id, char_key, progress) VALUES (%s, %s, %s)", [(user_id, k, v) for k, v in data["recruit_progress"].items()])

                await cur.execute(
                    "UPDATE users SET data_revision=%s WHERE user_id=%s",
                    (next_revision, user_key),
                )
                history_snapshot = copy.deepcopy(data)
                history_snapshot["_data_revision"] = next_revision
                await cur.execute(
                    """INSERT INTO user_save_history (user_id, revision, data)
                       VALUES (%s, %s, %s)""",
                    (
                        user_key,
                        next_revision,
                        json.dumps(history_snapshot, ensure_ascii=False, default=str),
                    ),
                )
                await cur.execute(
                    """DELETE FROM user_save_history
                       WHERE user_id=%s
                         AND id NOT IN (
                             SELECT id FROM (
                                 SELECT id FROM user_save_history
                                 WHERE user_id=%s
                                 ORDER BY revision DESC, id DESC
                                 LIMIT 10
                             ) AS retained
                         )""",
                    (user_key, user_key),
                )
                await conn.commit()
                data["_data_revision"] = next_revision
            except StaleUserDataError:
                await conn.rollback()
                logger.warning(
                    "Rejected stale save for user %s (loaded=%s, current=%s)",
                    user_key,
                    data.get("_data_revision", 0),
                    current_revision if "current_revision" in locals() else "?",
                )
                raise
            except Exception as e:
                await conn.rollback()
                logger.error(f"Save Error for {user_id}: {e}")
                raise


async def save_user_data(user_id, data):
    """Serialize snapshots per user and reject stale full-state writes."""
    user_key = str(user_id)
    async with _user_save_locks[user_key]:
        return await _save_user_data_unlocked(user_key, data)

async def update_user_resources(user_id, money_change=0, pt_change=0):
    user_key = str(user_id)
    async with _user_save_locks[user_key]:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                try:
                    await conn.begin()
                    await cur.execute(
                        """UPDATE users
                           SET money=money+%s, pt=pt+%s,
                               data_revision=data_revision+1
                           WHERE user_id=%s""",
                        (money_change, pt_change, user_key),
                    )
                    await cur.execute(
                        "SELECT money, pt, data_revision FROM users WHERE user_id=%s",
                        (user_key,),
                    )
                    result = await cur.fetchone()
                    await conn.commit()
                    return result
                except Exception:
                    await conn.rollback()
                    raise

GLOBAL_GUILD_ID = 1
GLOBAL_GUILD_NAME = "공용 길드"


def advance_world_turn(user_data, amount=1):
    """Advance automatic jobs without coupling life content to investigation."""
    amount = max(0, int(amount or 0))
    myhome = user_data.setdefault("myhome", {})
    myhome["total_turns"] = max(0, int(myhome.get("total_turns", 0) or 0)) + amount
    return myhome["total_turns"]


async def ensure_global_guild_membership(user_id):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                await conn.begin()
                await cur.execute(
                    """INSERT INTO guilds
                       (guild_id,name,owner_id,level,exp,member_count)
                       VALUES (%s,%s,NULL,1,0,0)
                       ON DUPLICATE KEY UPDATE name=VALUES(name)""",
                    (GLOBAL_GUILD_ID, GLOBAL_GUILD_NAME),
                )
                await cur.execute(
                    "SELECT COALESCE(SUM(contribution),0) FROM guild_members "
                    "WHERE user_id=%s FOR UPDATE",
                    (str(user_id),),
                )
                contribution = int((await cur.fetchone() or (0,))[0] or 0)
                await cur.execute("DELETE FROM guild_members WHERE user_id=%s", (str(user_id),))
                await cur.execute(
                    """INSERT INTO guild_members
                       (guild_id,user_id,role,contribution)
                       VALUES (%s,%s,'member',%s)""",
                    (GLOBAL_GUILD_ID, str(user_id), contribution),
                )
                await cur.execute(
                    """UPDATE guilds SET member_count=(
                       SELECT COUNT(*) FROM guild_members WHERE guild_id=%s)
                       WHERE guild_id=%s""",
                    (GLOBAL_GUILD_ID, GLOBAL_GUILD_ID),
                )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise


async def get_user_guild_info(user_id):
    await ensure_global_guild_membership(user_id)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("""
                SELECT g.*, m.role, m.contribution 
                FROM guild_members m JOIN guilds g ON m.guild_id = g.guild_id
                WHERE m.user_id = %s AND m.guild_id = %s
            """, (str(user_id), GLOBAL_GUILD_ID))
            return await cur.fetchone()

async def create_guild(user_id, guild_name):
    await ensure_global_guild_membership(user_id)
    return False, f"모든 이용자는 **{GLOBAL_GUILD_NAME}**에 자동 소속됩니다."

async def join_guild_by_id(user_id, guild_id):
    await ensure_global_guild_membership(user_id)
    return True, f"**{GLOBAL_GUILD_NAME}** 소속을 확인했습니다."

async def get_guild_list(limit=5, offset=0):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM guilds WHERE guild_id=%s", (GLOBAL_GUILD_ID,))
            row = await cur.fetchone()
            return [row] if row and int(offset or 0) == 0 else []

async def get_guild_items(guild_id, category=None):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            if category == "artifact":
                await cur.execute("SELECT * FROM guild_stored_artifacts WHERE guild_id = %s", (guild_id,))
            else:
                sql = "SELECT * FROM guild_inventory WHERE guild_id = %s" + (" AND category = %s" if category else "")
                params = (guild_id, category) if category else (guild_id,)
                await cur.execute(sql, params)
            return await cur.fetchall()

async def deposit_guild_item(user_id, guild_id, item_name, count, category, token_rewards, user_name=None):
    try:
        count = int(count)
    except (TypeError, ValueError):
        return False, "수량이 올바르지 않습니다."
    if count <= 0 or int(guild_id) != GLOBAL_GUILD_ID:
        return False, "공용 길드에 양수 수량만 납품할 수 있습니다."
    await ensure_global_guild_membership(user_id)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                await conn.begin()
                # Lock the user snapshot row and invalidate older open menus.
                await cur.execute(
                    "UPDATE users SET data_revision=data_revision+1 WHERE user_id=%s",
                    (str(user_id),),
                )
                await cur.execute(
                    "SELECT 1 FROM guild_members WHERE guild_id=%s AND user_id=%s FOR UPDATE",
                    (GLOBAL_GUILD_ID, str(user_id)),
                )
                if not await cur.fetchone():
                    await conn.rollback()
                    return False, "공용 길드 소속이 아닙니다."
                await cur.execute("SELECT quantity FROM inventory WHERE user_id=%s AND item_name=%s FOR UPDATE", (str(user_id), item_name))
                row = await cur.fetchone()
                if not row or row[0] < count: return False, "보유량 부족"
                
                if row[0] == count: await cur.execute("DELETE FROM inventory WHERE user_id=%s AND item_name=%s", (str(user_id), item_name))
                else: await cur.execute("UPDATE inventory SET quantity=quantity-%s WHERE user_id=%s AND item_name=%s", (count, str(user_id), item_name))
                
                await cur.execute("""INSERT INTO guild_inventory (guild_id, item_name, count, category) VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE count = count + VALUES(count)""", (guild_id, item_name, count, category))
                
                set_c = [f"token_{k} = token_{k} + {v}" for k,v in token_rewards.items()]
                if set_c: await cur.execute(f"UPDATE guilds SET {', '.join(set_c)} WHERE guild_id=%s", (guild_id,))
                
                await cur.execute(
                    """INSERT INTO guild_log
                       (guild_id,user_id,user_name,action_type,item_name,count)
                       VALUES (%s,%s,%s,'deposit',%s,%s)""",
                    (guild_id, str(user_id), user_name, item_name, count),
                )
                await conn.commit()
                return True, f"{item_name} {count}개 납품 완료"
            except Exception as e:
                await conn.rollback()
                return False, f"오류: {e}"

# [신규] 길드 아이템 출고 (Withdraw)
async def withdraw_guild_item(user_id, guild_id, item_name, count):
    return False, "공용 길드 자원은 개인 인벤토리로 출고할 수 없습니다."

async def deposit_guild_artifact(user_id, guild_id, artifact_data):
    if int(guild_id) != GLOBAL_GUILD_ID:
        return False, "공용 길드에만 아티팩트를 보관할 수 있습니다."
    await ensure_global_guild_membership(user_id)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                await conn.begin()
                await cur.execute(
                    "UPDATE users SET data_revision=data_revision+1 WHERE user_id=%s",
                    (str(user_id),),
                )
                await cur.execute(
                    "SELECT 1 FROM guild_members WHERE guild_id=%s AND user_id=%s FOR UPDATE",
                    (GLOBAL_GUILD_ID, str(user_id)),
                )
                if not await cur.fetchone():
                    await conn.rollback()
                    return False, "공용 길드 소속이 아닙니다."
                await cur.execute(
                    """SELECT equipped_char_index FROM artifacts
                       WHERE id=%s AND user_id=%s FOR UPDATE""",
                    (artifact_data["id"], str(user_id)),
                )
                stored = await cur.fetchone()
                if not stored:
                    await conn.rollback()
                    return False, "보관할 아티팩트를 찾을 수 없습니다."
                if int(stored[0] if stored[0] is not None else -1) != -1:
                    await conn.rollback()
                    return False, "캐릭터가 장착 중인 아티팩트는 보관할 수 없습니다."
                await cur.execute("INSERT INTO guild_stored_artifacts (guild_id, artifact_id, name, rank_level, level, data) VALUES (%s, %s, %s, %s, %s, %s)", 
                                  (guild_id, artifact_data['id'], artifact_data['name'], artifact_data.get('rank', 1), artifact_data.get('level', 0), json.dumps(artifact_data)))
                await cur.execute(
                    "DELETE FROM artifacts WHERE id=%s AND user_id=%s",
                    (artifact_data["id"], str(user_id)),
                )
                await cur.execute("INSERT INTO guild_log (guild_id, user_id, action_type, item_name, count) VALUES (%s, %s, 'deposit_artifact', %s, 1)", (guild_id, str(user_id), artifact_data['name']))
                await conn.commit()
                return True, "보관 완료"
            except Exception as e:
                await conn.rollback()
                return False, str(e)

async def get_guild_logs(guild_id, limit=10):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM guild_log WHERE guild_id = %s ORDER BY logged_at DESC LIMIT %s", (guild_id, limit))
            return await cur.fetchall()

async def get_subjugation_ranking(limit=10, region=None):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            sql = "SELECT user_id, max_subjugation_depth, max_subjugation_char, max_subjugation_region FROM users WHERE max_subjugation_depth > 0"
            params = []
            if region:
                sql += " AND max_subjugation_region = %s"
                params.append(region)
            sql += " ORDER BY max_subjugation_depth DESC LIMIT %s"
            params.append(limit)
            await cur.execute(sql, tuple(params))
            return await cur.fetchall()
