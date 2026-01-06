import json
import asyncio
import os
import sys
import logging
from datetime import datetime

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 경로 설정 (모듈 임포트 문제 해결)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from data_manager import save_user_data, get_db_pool
    # 캐릭터 기본값 참조용
    from character import DEFAULT_PLAYER_DATA 
except ImportError as e:
    logger.error(f"필수 모듈 로드 실패: {e}")
    sys.exit(1)

JSON_FILE_PATH = "user_data.json"

async def run_migration():
    """
    JSON 파일의 데이터를 읽어 DB로 마이그레이션합니다.
    """
    if not os.path.exists(JSON_FILE_PATH):
        logger.error(f"'{JSON_FILE_PATH}' 파일을 찾을 수 없습니다.")
        return

    logger.info("📂 JSON 데이터 로딩 중...")
    try:
        with open(JSON_FILE_PATH, 'r', encoding='utf-8') as f:
            all_data = json.load(f)
    except Exception as e:
        logger.error(f"JSON 파일 읽기 실패: {e}")
        return

    total_users = len(all_data)
    logger.info(f"총 {total_users}명의 유저 데이터를 발견했습니다. 마이그레이션 시작...")

    success_count = 0
    fail_count = 0
    
    # DB 연결 풀 초기화
    await get_db_pool()

    for i, (user_id, json_data) in enumerate(all_data.items()):
        try:
            # -------------------------------------------------------
            # 1. 데이터 클리닝 및 정규화
            # -------------------------------------------------------
            
            # (1) 기본 재화 및 정보
            migrated_data = {
                "user_id": str(user_id),
                "pt": json_data.get("pt", 0),
                "money": json_data.get("money", 0),
                "last_checkin": json_data.get("last_checkin"),
                "investigator_index": json_data.get("investigator_index", 0),
                "main_quest_id": json_data.get("main_quest_id", 0),
                "main_quest_current": json_data.get("main_quest_current", 0),
                "main_quest_index": json_data.get("main_quest_index", 0),
                "buffs": json_data.get("buffs", {}),
                "inventory": json_data.get("inventory", {}),
                "unlocked_regions": json_data.get("unlocked_regions", ["기원의 쌍성"]),
                "recruit_progress": json_data.get("recruit_progress", {}),
                
                # 아티팩트는 리스트 형태 유지
                "artifacts": json_data.get("artifacts", []),
                
                # 카드 목록 (없으면 기본값)
                "cards": json_data.get("cards", ["기본공격", "기본방어", "기본반격"])
            }

            # (2) 캐릭터 데이터 정규화
            # DB 스키마에 맞게 키 이름 변경 (mental -> max_mental 등)
            char_list = json_data.get("characters", [])
            cleaned_chars = []
            
            if not char_list:
                # 캐릭터가 하나도 없으면 기본 캐릭터 생성
                default_char = DEFAULT_PLAYER_DATA.copy()
                default_char["name"] = "플레이어"
                cleaned_chars.append(default_char)
            else:
                for char in char_list:
                    # 구버전 데이터 호환성 처리
                    c_dict = char.copy()
                    
                    # mental -> max_mental 키 변경
                    if "mental" in c_dict and "max_mental" not in c_dict:
                        c_dict["max_mental"] = c_dict["mental"]
                    
                    # 필수 필드 기본값 채우기
                    c_dict.setdefault("hp", 100)
                    c_dict.setdefault("max_mental", 100)
                    c_dict.setdefault("attack", 10)
                    c_dict.setdefault("defense", 0)
                    c_dict.setdefault("defense_rate", 0)
                    c_dict.setdefault("speed", 10)
                    c_dict.setdefault("card_slots", 4)
                    c_dict.setdefault("equipped_cards", [])
                    c_dict.setdefault("status_effects", {})
                    
                    cleaned_chars.append(c_dict)
            
            migrated_data["characters"] = cleaned_chars

            # (3) 마이홈 데이터 구조 맞추기
            # JSON의 myhome이 없거나, 구조가 깨져있을 경우를 대비
            org_myhome = json_data.get("myhome", {})
            
            # 텃밭
            garden = org_myhome.get("garden", {})
            garden_slots = garden.get("slots", [])
            # 슬롯 데이터가 dict 형태가 아니라면(혹시 모를 에러) 초기화
            if not isinstance(garden_slots, list):
                garden_slots = []
            
            # 작업실
            workshop_slots = org_myhome.get("workshop_slots", [])
            
            # 낚시 분해
            fishing = org_myhome.get("fishing", {})
            fishing_slots = fishing.get("dismantle_slots", [])

            # 마이홈 데이터 조립
            migrated_data["myhome"] = {
                "garden": {
                    "level": garden.get("level", 1),
                    "slots": garden_slots
                },
                "workshop_level": org_myhome.get("workshop_level", 1),
                "workshop_slots": workshop_slots,
                "fishing_level": org_myhome.get("fishing_level", 1),
                "fishing": {
                    "dismantle_slots": fishing_slots
                },
                "total_subjugations": org_myhome.get("total_subjugations", 0)
            }
            
            # 비료 정보는 user_data 루트에 있는지 myhome 안에 있는지 확인 필요
            # 보통 user_data["fertilizers"]에 있었던 것으로 추정 (코드 스니펫 기반)
            migrated_data["fertilizers"] = json_data.get("fertilizers", [])

            # -------------------------------------------------------
            # 2. DB 저장 실행
            # -------------------------------------------------------
            await save_user_data(user_id, migrated_data)
            
            success_count += 1
            
            # 100명 단위 로그
            if success_count % 100 == 0:
                logger.info(f"⏳ 진행 중... ({success_count}/{total_users})")

        except Exception as e:
            fail_count += 1
            logger.error(f"❌ User ID {user_id} 처리 중 오류: {e}")

    logger.info("=" * 50)
    logger.info("🎉 마이그레이션 완료")
    logger.info(f"✅ 성공: {success_count}명")
    logger.info(f"❌ 실패: {fail_count}명")
    logger.info("=" * 50)

if __name__ == "__main__":
    try:
        asyncio.run(run_migration())
    except KeyboardInterrupt:
        logger.info("작업이 사용자에 의해 중단되었습니다.")
    except Exception as e:
        logger.error(f"오류가 발생했습니다: {e}")
        sys.exit(1)