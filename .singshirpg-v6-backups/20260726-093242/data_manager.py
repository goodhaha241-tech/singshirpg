import aiomysql
import json
import os
import logging
import copy
import random
import datetime
from config import DB_CONFIG
from character import DEFAULT_PLAYER_DATA

logger = logging.getLogger(__name__)

_pool = None

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
            await cur.execute("SHOW TABLES LIKE 'users'")
            if not await cur.fetchone():
                with open("schema.sql", "r", encoding="utf-8") as f:
                    for stmt in f.read().split(';'):
                        if stmt.strip() and not stmt.upper().startswith(("CREATE DATABASE", "USE")):
                            try: await cur.execute(stmt)
                            except: continue
            
            # 길드 테이블 확인
            try:
                await cur.execute("""CREATE TABLE IF NOT EXISTS guilds (
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
                await cur.execute("""CREATE TABLE IF NOT EXISTS guild_members (
                        guild_id INT, user_id VARCHAR(50), role VARCHAR(20) DEFAULT 'member',
                        contribution INT DEFAULT 0, joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (guild_id, user_id), FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
                    )""")
                await cur.execute("""CREATE TABLE IF NOT EXISTS guild_inventory (
                        guild_id INT, item_name VARCHAR(100), count INT DEFAULT 0, category VARCHAR(50),
                        PRIMARY KEY (guild_id, item_name), FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
                    )""")
                await cur.execute("""CREATE TABLE IF NOT EXISTS guild_stored_artifacts (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY, guild_id INT, artifact_id VARCHAR(100),
                        name VARCHAR(100), rank_level INT, level INT, data JSON,
                        stored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
                    )""")
                await cur.execute("""CREATE TABLE IF NOT EXISTS guild_log (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY, guild_id INT, user_id VARCHAR(50),
                        user_name VARCHAR(100), action_type VARCHAR(50), item_name VARCHAR(100),
                        count INT, logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
                    )""")
            except Exception as e: logger.error(f"Guild Table Error: {e}")

            # 컬럼 추가
            await cur.execute("DESCRIBE users")
            u_cols = [r[0] for r in await cur.fetchall()]
            for col, typ in [("guild_rank", "VARCHAR(20)"), ("guild_data", "JSON"), ("characters", "JSON")]:
                if col not in u_cols:
                    try: await cur.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")
                    except: pass

async def _get_new_user_data(user_name=None):
    new_char = copy.deepcopy(DEFAULT_PLAYER_DATA)
    new_char["name"] = user_name if user_name else "플레이어"
    return {
        "pt": 0, "money": 0, "last_checkin": None, "investigator_index": 0,
        "main_quest_id": 0, "main_quest_current": 0, "main_quest_index": 0,
        "cards": ["기본공격", "기본방어", "기본반격"], "buffs": {}, "main_quest_progress": {},
        "inventory": {}, "characters": [new_char], "artifacts": [],
        "current_dungeon": {}, "unlocked_regions": ["기원의 쌍성"], "recruit_progress": {},
        "myhome": {"garden": {"level": 1, "slots": [], "water_can": 0}, "workshop_level": 1, "workshop_slots": [], "fishing_level": 1, "fishing": {"dismantle_slots": [], "rod": 0, "spot_level": 0, "max_dismantle_slots": 3}, "total_investigations": 0, "total_subjugations": 0, "construction_step": 0},
        "daily_quests": [], "last_quest_date": None, "fertilizers": [],
        "guild_rank": None, "guild_data": {}
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
            "equipped_char_index": row.get('equipped_char_index', -1)
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
            
            if not characters:
                json_chars = user_row.get('characters')
                if json_chars:
                    try: 
                        parsed = json.loads(json_chars)
                        if isinstance(parsed, list) and parsed: characters = parsed
                    except: pass
            if not characters:
                new_char = copy.deepcopy(DEFAULT_PLAYER_DATA)
                new_char["name"] = f"모험가_{str(user_id)[-4:]}"
                characters = [new_char]

            await cur.execute("SELECT region_name FROM unlocked_regions WHERE user_id = %s", (str(user_id),))
            unlocked_regions = [r['region_name'] for r in await cur.fetchall()] or ["기원의 쌍성"]

            await cur.execute("SELECT char_key, progress FROM recruit_progress WHERE user_id = %s", (str(user_id),))
            recruit_progress = {r['char_key']: r['progress'] for r in await cur.fetchall()}

            myhome_data = await _get_myhome_data(cur, user_id, user_row)

            await cur.execute("SELECT target FROM user_fertilizers WHERE user_id = %s", (str(user_id),))
            fertilizers = [{"target": r['target']} for r in await cur.fetchall()]

            return {
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
                "guild_data": json.loads(user_row['guild_data']) if user_row.get('guild_data') else {}
            }

async def save_user_data(user_id, data):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
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
                     garden_level, water_can, workshop_level, fishing_level, fishing_rod, fishing_spot_level, total_subjugations, cards, buffs, main_quest_progress, total_investigations, fishing_max_slots, max_subjugation_depth, daily_quests, last_quest_date, construction_step, current_dungeon, max_subjugation_char, max_subjugation_region, guild_rank, guild_data, characters)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) AS new
                    ON DUPLICATE KEY UPDATE
                    pt=new.pt, money=new.money, last_checkin=new.last_checkin,
                    investigator_index=new.investigator_index,
                    main_quest_id=new.main_quest_id, main_quest_current=new.main_quest_current, main_quest_index=new.main_quest_index,
                    garden_level=new.garden_level, water_can=new.water_can, workshop_level=new.workshop_level,
                    fishing_level=new.fishing_level, fishing_rod=new.fishing_rod, fishing_spot_level=new.fishing_spot_level,
                    total_subjugations=new.total_subjugations, cards=new.cards, buffs=new.buffs, 
                    main_quest_progress=new.main_quest_progress, total_investigations=new.total_investigations,
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
                    myhome.get("total_investigations", 0), myhome.get("fishing", {}).get("max_dismantle_slots", 3),
                    myhome.get("max_subjugation_depth", 0), json_cols['daily_quests'], data.get("last_quest_date"),
                    myhome.get("construction_step", 0), json_cols['current_dungeon'],
                    myhome.get("max_subjugation_char", ""), myhome.get("max_subjugation_region", ""),
                    data.get("guild_rank"), json_cols['guild_data'], json_cols['characters']
                ))

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
                            a.get("special"), a.get("description"), owner_idx
                        ))
                    await cur.executemany("""INSERT INTO artifacts (id, user_id, name, rank_level, grade, level, prefix, stats, special, description, equipped_char_index) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""", art_rows)

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

                await conn.commit()
            except Exception as e:
                await conn.rollback()
                logger.error(f"Save Error for {user_id}: {e}")
                raise e

async def update_user_resources(user_id, money_change=0, pt_change=0):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("UPDATE users SET money = money + %s, pt = pt + %s WHERE user_id = %s", (money_change, pt_change, str(user_id)))
            await conn.commit()
            await cur.execute("SELECT money, pt FROM users WHERE user_id = %s", (str(user_id),))
            return await cur.fetchone()

async def get_user_guild_info(user_id):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("""
                SELECT g.*, m.role, m.contribution 
                FROM guild_members m JOIN guilds g ON m.guild_id = g.guild_id
                WHERE m.user_id = %s
            """, (str(user_id),))
            return await cur.fetchone()

async def create_guild(user_id, guild_name):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1 FROM guild_members WHERE user_id = %s", (str(user_id),))
            if await cur.fetchone(): return False, "이미 길드에 소속되어 있습니다."
            await cur.execute("SELECT 1 FROM guilds WHERE name = %s", (guild_name,))
            if await cur.fetchone(): return False, "이미 존재하는 길드 이름입니다."
            try:
                await cur.execute("INSERT INTO guilds (name, owner_id) VALUES (%s, %s)", (guild_name, str(user_id)))
                guild_id = cur.lastrowid
                await cur.execute("INSERT INTO guild_members (guild_id, user_id, role) VALUES (%s, %s, 'master')", (guild_id, str(user_id)))
                await conn.commit()
                return True, f"길드 **{guild_name}** 창설 완료!"
            except Exception as e:
                await conn.rollback()
                return False, f"오류: {e}"

async def join_guild_by_id(user_id, guild_id):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1 FROM guild_members WHERE user_id = %s", (str(user_id),))
            if await cur.fetchone(): return False, "이미 길드 소속입니다."
            try:
                await cur.execute("INSERT INTO guild_members (guild_id, user_id, role) VALUES (%s, %s, 'member')", (guild_id, str(user_id)))
                await cur.execute("UPDATE guilds SET member_count = member_count + 1 WHERE guild_id = %s", (guild_id,))
                await conn.commit()
                return True, "가입 완료!"
            except Exception as e:
                return False, f"가입 실패: {e}"

async def get_guild_list(limit=5, offset=0):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM guilds ORDER BY level DESC, member_count DESC LIMIT %s OFFSET %s", (limit, offset))
            return await cur.fetchall()

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

async def deposit_guild_item(user_id, guild_id, item_name, count, category, token_rewards):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                await cur.execute("SELECT quantity FROM inventory WHERE user_id=%s AND item_name=%s", (str(user_id), item_name))
                row = await cur.fetchone()
                if not row or row[0] < count: return False, "보유량 부족"
                
                if row[0] == count: await cur.execute("DELETE FROM inventory WHERE user_id=%s AND item_name=%s", (str(user_id), item_name))
                else: await cur.execute("UPDATE inventory SET quantity=quantity-%s WHERE user_id=%s AND item_name=%s", (count, str(user_id), item_name))
                
                await cur.execute("""INSERT INTO guild_inventory (guild_id, item_name, count, category) VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE count = count + VALUES(count)""", (guild_id, item_name, count, category))
                
                set_c = [f"token_{k} = token_{k} + {v}" for k,v in token_rewards.items()]
                if set_c: await cur.execute(f"UPDATE guilds SET {', '.join(set_c)} WHERE guild_id=%s", (guild_id,))
                
                await cur.execute("INSERT INTO guild_log (guild_id, user_id, action_type, item_name, count) VALUES (%s, %s, 'deposit', %s, %s)", (guild_id, str(user_id), item_name, count))
                await conn.commit()
                return True, f"{item_name} {count}개 납품 완료"
            except Exception as e:
                await conn.rollback()
                return False, f"오류: {e}"

# [신규] 길드 아이템 출고 (Withdraw)
async def withdraw_guild_item(user_id, guild_id, item_name, count):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                # 길드 인벤 체크
                await cur.execute("SELECT count FROM guild_inventory WHERE guild_id=%s AND item_name=%s", (guild_id, item_name))
                row = await cur.fetchone()
                if not row or row[0] < count: return False, "길드 보유량 부족"
                
                if row[0] == count: await cur.execute("DELETE FROM guild_inventory WHERE guild_id=%s AND item_name=%s", (guild_id, item_name))
                else: await cur.execute("UPDATE guild_inventory SET count=count-%s WHERE guild_id=%s AND item_name=%s", (count, guild_id, item_name))
                
                # 유저 인벤 추가
                await cur.execute("""INSERT INTO inventory (user_id, item_name, quantity) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE quantity = quantity + VALUES(quantity)""", (str(user_id), item_name, count))
                
                # 로그
                await cur.execute("INSERT INTO guild_log (guild_id, user_id, action_type, item_name, count) VALUES (%s, %s, 'withdraw', %s, %s)", (guild_id, str(user_id), item_name, count))
                await conn.commit()
                return True, f"{item_name} {count}개 수령 완료"
            except Exception as e:
                await conn.rollback()
                return False, f"오류: {e}"

async def deposit_guild_artifact(user_id, guild_id, artifact_data):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                await cur.execute("INSERT INTO guild_stored_artifacts (guild_id, artifact_id, name, rank_level, level, data) VALUES (%s, %s, %s, %s, %s, %s)", 
                                  (guild_id, artifact_data['id'], artifact_data['name'], artifact_data.get('rank', 1), artifact_data.get('level', 0), json.dumps(artifact_data)))
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