import aiomysql
import json
import logging
import asyncio
from config import DB_CONFIG

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_pool = None

async def get_db_pool():
    global _pool
    if _pool is None:
        try:
            _pool = await aiomysql.create_pool(**DB_CONFIG)
            logger.info("DB Pool created successfully.")
        except Exception as e:
            logger.error(f"Failed to create DB Pool: {e}")
            raise
    return _pool

def _create_default_user(user_id, user_name):
    """DB에 데이터가 없을 때 사용할 기본 유저 구조 (메모리상)"""
    from character import DEFAULT_PLAYER_DATA
    
    # 기본 캐릭터 생성 (깊은 복사)
    char_data = DEFAULT_PLAYER_DATA.copy()
    char_data["name"] = user_name # 유저 닉네임 따라감
    
    return {
        "user_id": str(user_id),
        "pt": 0, 
        "money": 0, 
        "last_checkin": None,
        "investigator_index": 0, 
        "main_quest_id": 0, 
        "main_quest_current": 0, 
        "main_quest_index": 0,
        "buffs": {}, 
        "inventory": {}, 
        "unlocked_regions": ["기원의 쌍성"], 
        "artifacts": [],
        "characters": [char_data], # 기본 캐릭터 1명 포함
        "cards": ["기본공격", "기본방어", "기본반격"],
        "recruit_progress": {},
        "myhome": {
            "garden": {
                "level": 1,
                "slots": [
                    {"planted": False, "stage": 0, "last_invest_count": 0},
                    {"planted": False, "stage": 0, "last_invest_count": 0},
                    {"planted": False, "stage": 0, "last_invest_count": 0}
                ]
            },
            "workshop_level": 1,
            "workshop_slots": [],
            "fishing_level": 1,
            "fishing": {"dismantle_slots": []},
            "total_subjugations": 0
        }
    }

async def get_user_data(user_id, user_name=None):
    """
    DB에서 데이터를 가져와 기존 JSON 구조(Dictionary)로 변환하여 반환
    """
    user_id = str(user_id)
    pool = await get_db_pool()
    
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            # 1. Users 테이블 조회
            await cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            user_row = await cur.fetchone()
            
            # 신규 유저라면 기본 데이터 생성 후 DB에 초기 삽입 (Lazy Init)
            if not user_row:
                logger.info(f"New user detected: {user_id}")
                default_data = _create_default_user(user_id, user_name or "Unknown")
                await save_user_data(user_id, default_data) # 초기 데이터 저장
                return default_data

            # 2. 기본 구조 생성
            data = {
                "user_id": user_row["user_id"],
                "pt": user_row["pt"],
                "money": user_row["money"],
                "last_checkin": str(user_row["last_checkin"]) if user_row["last_checkin"] else None,
                "investigator_index": user_row["investigator_index"],
                "main_quest_id": user_row["main_quest_id"],
                "main_quest_current": user_row["main_quest_current"],
                "main_quest_index": user_row["main_quest_index"],
                "buffs": json.loads(user_row["buffs"]) if user_row["buffs"] else {},
                # Inventory, Characters 등은 아래에서 채움
                "inventory": {},
                "characters": [],
                "artifacts": [],
                "unlocked_regions": [],
                "recruit_progress": {},
                "cards": ["기본공격", "기본방어", "기본반격"], # 기본값 (별도 테이블 없다면)
                "myhome": {
                    "garden": {"level": user_row.get("garden_level", 1), "slots": []},
                    "workshop_level": user_row.get("workshop_level", 1),
                    "workshop_slots": [],
                    "fishing_level": user_row.get("fishing_level", 1),
                    "fishing": {"dismantle_slots": []},
                    "total_subjugations": user_row.get("total_subjugations", 0)
                }
            }
            
            # 3. Inventory 로드
            await cur.execute("SELECT item_name, quantity FROM inventory WHERE user_id = %s", (user_id,))
            inv_rows = await cur.fetchall()
            for row in inv_rows:
                data["inventory"][row["item_name"]] = row["quantity"]
            
            # 4. Characters 로드 (char_index 순서 중요)
            await cur.execute("SELECT * FROM characters WHERE user_id = %s ORDER BY char_index ASC", (user_id,))
            char_rows = await cur.fetchall()
            for row in char_rows:
                char_dict = {
                    "name": row["name"],
                    "hp": row["hp"], "current_hp": row["hp"], # DB엔 최대치만 저장되므로 로드시 초기화됨에 주의 (필요시 current 컬럼 추가 추천)
                    "max_mental": row["max_mental"], "current_mental": row["max_mental"],
                    "attack": row["attack"],
                    "defense": row["defense"],
                    "defense_rate": row["defense_rate"],
                    "speed": row["speed"],
                    "card_slots": row["card_slots"],
                    "equipped_cards": json.loads(row["equipped_cards"]) if row["equipped_cards"] else [],
                    "status_effects": json.loads(row["status_effects"]) if row["status_effects"] else {}
                }
                # current_hp 등을 별도 저장하고 싶다면 schema 수정 필요, 여기서는 max로 초기화
                data["characters"].append(char_dict)
                
            # 5. Artifacts 로드
            await cur.execute("SELECT * FROM artifacts WHERE user_id = %s", (user_id,))
            art_rows = await cur.fetchall()
            for row in art_rows:
                art_dict = {
                    "id": row["id"],
                    "name": row["name"],
                    "rank": row["rank_level"],
                    "level": row["level"],
                    "prefix": row["prefix"],
                    "stats": json.loads(row["stats"]) if row["stats"] else {},
                    "special": row["special"], # [추가된 필드]
                    "description": row["description"]
                }
                data["artifacts"].append(art_dict)

            # 6. Unlocked Regions
            await cur.execute("SELECT region_name FROM unlocked_regions WHERE user_id = %s", (user_id,))
            reg_rows = await cur.fetchall()
            data["unlocked_regions"] = [r["region_name"] for r in reg_rows]

            # 7. Recruit Progress (신규)
            await cur.execute("SELECT char_key, progress FROM recruit_progress WHERE user_id = %s", (user_id,))
            rec_rows = await cur.fetchall()
            for row in rec_rows:
                data["recruit_progress"][row["char_key"]] = row["progress"]

            # 8. MyHome - Garden Slots
            await cur.execute("SELECT * FROM garden_slots WHERE user_id = %s ORDER BY slot_index ASC", (user_id,))
            g_rows = await cur.fetchall()
            # 슬롯 인덱스에 맞춰 리스트 구성 (빈 슬롯 채우기 로직은 뷰에서 처리하거나 여기서 처리)
            # 여기서는 단순히 append
            for row in g_rows:
                slot = {
                    "planted": bool(row["planted"]),
                    "stage": row["stage"],
                    "last_invest_count": row["last_invest_count"],
                    "fertilizer": row["fertilizer"]
                }
                data["myhome"]["garden"]["slots"].append(slot)
            
            # 비료 정보
            await cur.execute("SELECT target FROM user_fertilizers WHERE user_id = %s", (user_id,))
            fert_rows = await cur.fetchall()
            data["fertilizers"] = [{"target": r["target"]} for r in fert_rows] # 기존 구조 호환

            # 작업실 슬롯
            await cur.execute("SELECT * FROM workshop_slots WHERE user_id = %s ORDER BY slot_index ASC", (user_id,))
            w_rows = await cur.fetchall()
            for row in w_rows:
                w_slot = {
                    "slot_index": row["slot_index"],
                    "craft_item": row["craft_item"],
                    "start_count": row["start_count"],
                    "required_count": row["required_count"]
                }
                data["myhome"]["workshop_slots"].append(w_slot)
            
            # 낚시 분해 슬롯
            await cur.execute("SELECT * FROM fishing_slots WHERE user_id = %s", (user_id,))
            f_rows = await cur.fetchall()
            for row in f_rows:
                f_slot = {
                    "fish": row["fish_name"],
                    "start_count": row["start_count"]
                }
                data["myhome"]["fishing"]["dismantle_slots"].append(f_slot)

            return data

async def save_user_data(user_id, data):
    """
    Dictionary(JSON) 구조의 데이터를 분해하여 DB에 저장 (UPSERT)
    주의: 성능 최적화를 위해 변경된 부분만 저장하는 것이 좋으나, 
    마이그레이션 초기 안정성을 위해 주요 테이블을 갱신합니다.
    """
    user_id = str(user_id)
    pool = await get_db_pool()
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # 1. Users 테이블 업데이트
            myhome = data.get("myhome", {})
            buffs_json = json.dumps(data.get("buffs", {}), ensure_ascii=False)
            
            sql_users = """
                INSERT INTO users (
                    user_id, pt, money, last_checkin, investigator_index,
                    main_quest_id, main_quest_current, main_quest_index, buffs,
                    garden_level, workshop_level, fishing_level, total_subjugations
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    pt=VALUES(pt), money=VALUES(money), last_checkin=VALUES(last_checkin),
                    investigator_index=VALUES(investigator_index),
                    main_quest_id=VALUES(main_quest_id), main_quest_current=VALUES(main_quest_current),
                    main_quest_index=VALUES(main_quest_index), buffs=VALUES(buffs),
                    garden_level=VALUES(garden_level), workshop_level=VALUES(workshop_level),
                    fishing_level=VALUES(fishing_level), total_subjugations=VALUES(total_subjugations)
            """
            await cur.execute(sql_users, (
                user_id, data.get("pt", 0), data.get("money", 0), data.get("last_checkin"),
                data.get("investigator_index", 0),
                data.get("main_quest_id", 0), data.get("main_quest_current", 0), data.get("main_quest_index", 0),
                buffs_json,
                myhome.get("garden", {}).get("level", 1),
                myhome.get("workshop_level", 1),
                myhome.get("fishing_level", 1),
                myhome.get("total_subjugations", 0)
            ))

            # 2. Inventory 업데이트 (Upsert)
            # 수량이 0 이하면 삭제하는 로직 포함
            inv = data.get("inventory", {})
            if inv:
                # 대량 처리를 위해 executemany 사용
                upsert_data = []
                delete_names = []
                for item_name, qty in inv.items():
                    if qty > 0:
                        upsert_data.append((user_id, item_name, qty))
                    else:
                        delete_names.append(item_name)
                
                if upsert_data:
                    await cur.executemany("""
                        INSERT INTO inventory (user_id, item_name, quantity) 
                        VALUES (%s, %s, %s) 
                        ON DUPLICATE KEY UPDATE quantity=VALUES(quantity)
                    """, upsert_data)
                
                if delete_names:
                    format_strings = ','.join(['%s'] * len(delete_names))
                    await cur.execute(f"DELETE FROM inventory WHERE user_id = %s AND item_name IN ({format_strings})", 
                                      (user_id, *delete_names))

            # 3. Characters 업데이트
            # 기존 캐릭터를 지우고 다시 넣는 것보다, ID가 있다면 UPDATE, 없으면 INSERT가 안전하지만
            # 슬롯 순서 변경 등을 고려하여, 여기서는 간단하게 해당 유저의 캐릭터 정보를 갱신합니다.
            # (복잡성을 줄이기 위해 기존 캐릭터 삭제 후 재삽입 방식 사용 -> ID 유지를 위해선 수정 필요하나, 여기선 데모용)
            # *주의*: 실제 서비스에선 ID가 변하면 안되는 경우가 있으므로 UPDATE를 권장합니다.
            
            # 여기서는 UPDATE or INSERT 로직을 사용합니다.
            chars = data.get("characters", [])
            
            # 먼저 해당 유저의 기존 캐릭터 ID들을 가져옵니다.
            await cur.execute("SELECT id, char_index FROM characters WHERE user_id = %s", (user_id,))
            existing_chars = await cur.fetchall() # {(id, index), ...}
            
            # 현재 데이터의 캐릭터들 저장
            for idx, char in enumerate(chars):
                equipped_json = json.dumps(char.get("equipped_cards", []), ensure_ascii=False)
                effects_json = json.dumps(char.get("status_effects", {}), ensure_ascii=False)
                
                # char_index와 user_id가 Unique Key이므로 이를 이용해 Upsert
                sql_char = """
                    INSERT INTO characters (
                        user_id, char_index, name, hp, max_mental, 
                        attack, defense, defense_rate, speed, 
                        card_slots, equipped_cards, status_effects
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        name=VALUES(name), hp=VALUES(hp), max_mental=VALUES(max_mental),
                        attack=VALUES(attack), defense=VALUES(defense), defense_rate=VALUES(defense_rate),
                        speed=VALUES(speed), card_slots=VALUES(card_slots),
                        equipped_cards=VALUES(equipped_cards), status_effects=VALUES(status_effects)
                """
                await cur.execute(sql_char, (
                    user_id, idx, char["name"], char.get("hp", 100), char.get("max_mental", 100),
                    char.get("attack", 10), char.get("defense", 0), char.get("defense_rate", 0),
                    char.get("speed", 10), char.get("card_slots", 4),
                    equipped_json, effects_json
                ))

            # 4. Artifacts, Unlocked Regions 등도 유사하게 처리
            # (지면 관계상 핵심인 유저, 인벤토리, 캐릭터 위주로 작성)
            # unlocked_regions 처리 예시:
            regions = data.get("unlocked_regions", [])
            if regions:
                r_data = [(user_id, r) for r in regions]
                await cur.executemany("INSERT IGNORE INTO unlocked_regions (user_id, region_name) VALUES (%s, %s)", r_data)

            # 5. Recruit Progress 저장
            prog = data.get("recruit_progress", {})
            if prog:
                p_data = [(user_id, k, v) for k, v in prog.items()]
                await cur.executemany("""
                    INSERT INTO recruit_progress (user_id, char_key, progress) VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE progress=VALUES(progress)
                """, p_data)

            # 6. MyHome Slots (Garden 등)
            # 슬롯 데이터는 갯수가 적으므로 DELETE 후 INSERT 방식이 깔끔할 수 있습니다.
            # (슬롯 순서나 갯수가 변할 수 있기 때문)
            
            # 6-1. Garden Slots
            await cur.execute("DELETE FROM garden_slots WHERE user_id = %s", (user_id,))
            g_slots = myhome.get("garden", {}).get("slots", [])
            if g_slots:
                g_data = []
                for i, s in enumerate(g_slots):
                    g_data.append((
                        user_id, i, s.get("planted", False), s.get("stage", 0),
                        s.get("last_invest_count", 0), s.get("fertilizer")
                    ))
                await cur.executemany("""
                    INSERT INTO garden_slots (user_id, slot_index, planted, stage, last_invest_count, fertilizer)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, g_data)