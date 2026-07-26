from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import random
import math

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. 임시 데이터베이스 (플레이어 & 현재 전투 중인 몬스터)
player_data = {
    "name": "플레이어",
    "current_hp": 170, "max_hp": 170,
    "current_mental": 90, "max_mental": 90,
    "attack": 20, "defense": 10, # 스탯 예시
    "money": 15000, "pt": 1000,
    "cards": ["기본공격", "기본방어", "기본반격"]
}

current_battle = None

# 임시 몬스터 데이터 (monsters.py 및 cards.py 참조)
def get_monster(name):
    return {
        "name": name,
        "current_hp": 50, "max_hp": 50,
        "current_mental": 50, "max_mental": 50,
        "attack": 12, "defense": 6
    }

def get_card_dice(card_name):
    # cards.py의 Dice 객체를 단순화
    cards = {
        "기본공격": {"type": "attack", "val": 10},
        "기본방어": {"type": "defense", "val": 10},
        "기본반격": {"type": "counter", "val": 8}
    }
    return cards.get(card_name, {"type": "attack", "val": 5})

# 주사위 값 보정 (기획 룰 적용)
def roll_dice(dice_type, base_val, atk, def_stat):
    if dice_type == "attack":
        bonus = atk // 2
    elif dice_type in ["defense", "heal"]:
        bonus = def_stat // 2
    elif dice_type == "counter":
        bonus = (atk // 4) + (def_stat // 4)
    else:
        bonus = 0
    return base_val + bonus

# 2. 정보 조회 API
@app.get("/api/myinfo")
def get_my_info():
    return {"player": player_data, "battle": current_battle}

# 3. 조사하기 API
@app.post("/api/action/investigate")
def do_investigate():
    global current_battle
    cost_pt = 100

    if player_data["pt"] < cost_pt:
        return {"success": False, "message": "❌ 포인트가 부족합니다!", "event": "none"}

    player_data["pt"] -= cost_pt
    
    # 30% 확률로 조사 실패
    if random.random() < 0.30:
        # 실패 시 50% 확률로 몬스터 조우
        if random.random() < 0.50:
            current_battle = get_monster("약한 원념")
            return {"success": True, "message": "⚠️ 조사 실패... 앗! 몬스터와 조우했습니다!", "event": "battle_start", "data": player_data}
        else:
            return {"success": True, "message": "💦 조사에 실패했습니다. (아무 일도 일어나지 않음)", "event": "fail", "data": player_data}
    
    # 조사 성공
    earned_item = random.choice(["낡은 보물상자", "사과", "녹슨 철"])
    return {"success": True, "message": f"🔍 조사를 완료하여 [{earned_item}]을(를) 얻었습니다!", "event": "success", "data": player_data}

# 4. 전투 합(Clash) 진행 API
class BattleAction(BaseModel):
    card_name: str

@app.post("/api/battle/clash")
def do_clash(action: BattleAction):
    global current_battle
    if not current_battle:
        return {"error": "진행 중인 전투가 없습니다."}

    # 카드 및 주사위 준비
    p_card = get_card_dice(action.card_name)
    m_card = get_card_dice(random.choice(["기본공격", "기본방어"])) # 몬스터는 랜덤 행동
    
    p_val = roll_dice(p_card["type"], p_card["val"], player_data["attack"], player_data["defense"])
    m_val = roll_dice(m_card["type"], m_card["val"], current_battle["attack"], current_battle["defense"])

    log = f"플레이어({action.card_name}: {p_val}) VS 몬스터({m_card['type']}: {m_val})\\n"
    
    # 패닉 상태 체크 (받는 피해 2배)
    p_panic_mult = 2 if player_data["current_mental"] <= 0 else 1
    m_panic_mult = 2 if current_battle["current_mental"] <= 0 else 1

    # 합(Clash) 룰 판정
    p_dmg, m_dmg = 0, 0
    p_heal_m, m_heal_m = 0, 0

    if p_card["type"] == "attack" and m_card["type"] == "attack":
        p_dmg = m_val * p_panic_mult
        m_dmg = p_val * m_panic_mult
        log += "💥 서로 공격을 주고받았습니다!"

    elif p_card["type"] == "attack" and m_card["type"] == "defense":
        real_dmg = max(0, p_val - m_val)
        m_dmg = real_dmg * m_panic_mult
        m_heal_m = min(p_val, m_val) # 막아낸 만큼 몬스터 정신력 회복
        log += f"🛡️ 몬스터가 방어했습니다! (피해 {m_dmg}, 정신력 회복 {m_heal_m})"

    elif p_card["type"] == "defense" and m_card["type"] == "attack":
        real_dmg = max(0, m_val - p_val)
        p_dmg = real_dmg * p_panic_mult
        p_heal_m = min(m_val, p_val)
        log += f"🛡️ 플레이어가 방어했습니다! (피해 {p_dmg}, 정신력 회복 {p_heal_m})"

    elif p_card["type"] == "attack" and m_card["type"] == "counter":
        if m_val > p_val:
            p_dmg = m_val * p_panic_mult
            log += "⚡ 몬스터의 반격 성공! 일방적인 피해를 입습니다."
        else:
            m_dmg = p_val * m_panic_mult
            log += "⚔️ 반격을 뚫고 공격에 성공했습니다!"
    
    elif p_card["type"] == "counter" and m_card["type"] == "attack":
        if p_val > m_val:
            m_dmg = p_val * m_panic_mult
            log += "⚡ 플레이어의 반격 성공! 일방적인 피해를 줍니다."
        else:
            p_dmg = m_val * p_panic_mult
            log += "⚔️ 반격에 실패하여 일방적인 피해를 입습니다!"
            
    elif p_card["type"] == "defense" and m_card["type"] == "defense":
        log += "💨 서로 방어 태세를 취했습니다. (아무 일도 일어나지 않음)"

    # 데미지 및 정신력 적용 (공격 피해의 절반은 정신력 피해)
    if p_dmg > 0:
        player_data["current_hp"] -= p_dmg
        if player_data["current_mental"] > 0: player_data["current_mental"] -= p_dmg // 2
    if m_dmg > 0:
        current_battle["current_hp"] -= m_dmg
        if current_battle["current_mental"] > 0: current_battle["current_mental"] -= m_dmg // 2

    # 정신력 회복 적용
    if p_heal_m > 0: player_data["current_mental"] = min(player_data["max_mental"], player_data["current_mental"] + p_heal_m)
    if m_heal_m > 0: current_battle["current_mental"] = min(current_battle["max_mental"], current_battle["current_mental"] + m_heal_m)

    # 전투 종료 판정
    battle_status = "ongoing"
    if current_battle["current_hp"] <= 0:
        log += "\\n🎉 몬스터 처치 성공!"
        battle_status = "win"
        current_battle = None
    elif player_data["current_hp"] <= 0:
        log += "\\n☠️ 패배했습니다..."
        battle_status = "lose"
        current_battle = None
        player_data["current_hp"] = 1 # 부활

    return {
        "log": log,
        "battle_status": battle_status,
        "player": player_data,
        "monster": current_battle
    }