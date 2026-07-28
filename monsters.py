# monsters.py
# pve-gem-runtime-v8.2
import random
from cards import get_card, SKILL_CARDS

class Monster:
    """모든 몬스터의 기본 클래스"""
    def __init__(self, name, hp, attack, defense, description="", 
                 pattern_type="balanced", reward=None, reward_count=1,
                 pt_range=(0, 0), money_range=(0, 0), card_deck=None):
        self.name = name
        self.max_hp = hp
        self.current_hp = hp
        self.max_mental = hp
        self.current_mental = hp
        self.attack = attack
        self.defense = defense
        self.description = description
        self.pattern_type = pattern_type
        self.reward = reward 
        self.reward_count = reward_count
        self.pt_range = pt_range 
        self.money_range = money_range
        # PvE uses the same battle engine as PvP.  Monsters do not equip gems,
        # but the shared engine still needs harmless runtime/status stores.
        self.runtime_cooldowns = {}
        self.status_effects = {"bleed": 0, "paralysis": 0, "stun": 0, "freeze": 0}
        
        self.card_deck = card_deck if card_deck else ["기본공격", "기본방어"]

    def decide_action(self):
        available_cards = [get_card(name) for name in self.card_deck if get_card(name)]
        if not available_cards: return get_card("기본공격")

        weights = []
        for card in available_cards:
            primary_type = card.dice_list[0].action_type
            if self.pattern_type == "aggressive":
                w = 70 if primary_type == "attack" else 15
            elif self.pattern_type == "defensive":
                w = 70 if primary_type in ["defense", "counter", "heal"] else 15
            else:
                w = 33 
            weights.append(w)

        return random.choices(available_cards, weights=weights)[0]

# --- 몬스터 도감 ---
MONSTER_DATA = {
    # [기존 몬스터들]
    "길 잃은 바람비": { "hp": 50, "attack": 1, "defense": 2, "reward": "무지개 열매", "pt_range": (30, 70), "money_range": (400, 1200), "pattern_type": "defensive", "card_deck": ["기본공격", "섬세한 방어", "재생"] },
    "약한 원념": { "hp": 60, "attack": 2, "defense": 1, "reward": "섬세한 보물상자", "pt_range": (30, 75), "money_range": (400, 1200), "pattern_type": "aggressive", "card_deck": ["기본공격", "연속할퀴기", "작은원망"] },
    "눈 감은 원념": { "hp": 120, "attack": 4, "defense": 3, "reward": "투명한 유리", "pt_range": (120, 300), "money_range": (700, 1800), "pattern_type": "balanced", "card_deck": ["겁나는얼굴", "작은원망", "재생"] },
    "커다란 별기구": { "hp": 50, "attack": 1, "defense": 3, "reward": "사랑나무 가지", "pt_range": (30, 75), "money_range": (400, 1200), "pattern_type": "defensive", "card_deck": ["비축분 던지기", "복합공격", "재생"] },
    "주신의 눈물방울": { "hp": 140, "attack": 9, "defense": 8, "reward": "빛구슬", "reward_count": 3, "pt_range": (400, 600), "money_range": (1000, 2500), "pattern_type": "balanced", "card_deck": ["기망", "책임", "우주", "소명"] },
    "예민한 집요정": { "hp": 130, "attack": 10, "defense": 5, "reward": "섬세한 열쇠", "reward_count": 2, "pt_range": (400, 600), "money_range": (1000, 2500), "pattern_type": "aggressive", "card_deck": ["강한참격", "연속할퀴기", "먼지쓸기"] },
    "굴레늑대": { "hp": 120, "attack": 6, "defense": 6, "reward": "굴레늑대 털", "reward_count": 5, "pt_range": (500, 1000), "money_range": (3000, 4000), "pattern_type": "balanced", "card_deck": ["깊은집중", "연속할퀴기", "숨고르기", "겁나는얼굴"] },
    "얼어붙은 원념": { "hp": 100, "attack": 12, "defense": 3, "reward": "천년얼음", "reward_count": 3, "pt_range": (500, 1000), "money_range": (3000, 4000), "pattern_type": "aggressive", "card_deck": ["육참골단", "작은원망", "숨고르기", "섬세한 방어"] },
    "경계꽃 골렘": { "hp": 90, "attack": 3, "defense": 10, "reward": "혹한의 눈꽃", "pt_range": (300, 600), "money_range": (2000, 3000), "pattern_type": "defensive", "card_deck": ["기본공격", "섬세한 방어", "기본반격"] },
    "시간의 방랑자": { "hp": 150, "attack": 8, "defense": 5, "reward": "시간의 모래", "reward_count": 2, "pt_range": (600, 1200), "money_range": (3000, 5000), "pattern_type": "balanced", "card_deck": ["육참골단", "깊은집중", "복합공격", "회전베기"] },
    "과거의 망집": { "hp": 140, "attack": 10, "defense": 3, "reward": "기억 종이", "reward_count": 3, "pt_range": (600, 1200), "money_range": (3000, 5000), "pattern_type": "aggressive", "card_deck": ["강한참격", "작은원망"] },

    # [신규 - 이루지 못한 꿈들의 별]
    "몽상행인": {
        "hp": 200, "attack": 3, "defense": 2,
        "description": "꿈속을 거니는 수수께끼의 행인.",
        "pattern_type": "balanced",
        "card_deck": ["꿈꾸기", "자각몽", "후회", "연속할퀴기"],
        "reward": "깔끔한 열쇠",
        "reward_count": 1,
        "pt_range": (1000, 1500),
        "money_range": (4500, 5500)
    },
    "살아난 발상": {
        "hp": 250, "attack": 2, "defense": 3,
        "description": "버려진 아이디어가 생명을 얻어 움직입니다.",
        "pattern_type": "defensive",
        "card_deck": ["꿈꾸기", "자각몽", "떠올리기"],
        "reward": "맑은 생각",
        "reward_count": 2,
        "pt_range": (1000, 1500),
        "money_range": (4500, 5500)
    },
    "구체화된 악몽": {
        "hp": 180, "attack": 4, "defense": 1,
        "description": "가장 두려워하던 것이 눈앞에 나타났습니다.",
        "pattern_type": "aggressive",
        "card_deck": ["연속할퀴기", "자각몽", "트라우마 자극"],
        "reward": "악몽 파편",
        "reward_count": 2,
        "pt_range": (1000, 1500),
        "money_range": (4500, 5500)
    },

    # [신규 추가 - 일한산 중턱 히든 몬스터]
    "굴레늑대 우두머리": {
        "hp": 210, "attack": 10, "defense": 8,
        "description": "무리를 이끄는 강력한 늑대 우두머리.",
        "pattern_type": "balanced",
        "card_deck": ["깊은집중", "연속할퀴기", "숨고르기", "인파이트"], 
        "reward": "굴레늑대 털",
        "reward_count": 10,
        "pt_range": (1000, 1500),
        "money_range": (4500, 5500)
    },
    "은하새": {
        "hp": 150, "attack": 8, "defense": 7,
        "description": "밤하늘의 은하수를 닮은 신비로운 새.",
        "pattern_type": "defensive",
        "card_deck": ["회피기동", "깊은집중", "재생", "자각몽"],
        "reward": "일한산의 정수",
        "reward_count": 1,
        "pt_range": (1000, 1500),
        "money_range": (4500, 5500)
    },
    "뒤틀린 식충식물": {
        "hp": 300, "attack": 14, "defense": 15,
        "description": "생명의 숲에 서식하는 기괴한 식물.",
        "pattern_type": "balanced",
        "card_deck": ["더러운 공격", "불안정한 재생", "연속할퀴기", "중급회복"],
        "reward": "재생의 흔적", "reward_count": 5,
        "pt_range": (1000, 1500), "money_range": (4500, 5500)
    },
    "굶주린 포식자": {
        "hp": 170, "attack": 19, "defense": 9,
        "description": "피 냄새를 맡고 달려드는 맹수.",
        "pattern_type": "aggressive",
        "card_deck": ["더러운 공격", "육참골단", "인파이트", "상처 벌리기"],
        "reward": "소멸의 흔적", "reward_count": 5,
        "pt_range": (1000, 1500), "money_range": (4500, 5500)
    },
    "아름다운 나비": {
        "hp": 320, "attack": 9, "defense": 19,
        "description": "숲의 생명력을 수호하는 나비.",
        "pattern_type": "defensive",
        "card_deck": ["꿈꾸기", "재생", "불안정한 재생", "후회"],
        "reward": "하급 마력석", "reward_count": 2,
        "pt_range": (1000, 1500), "money_range": (4500, 5500)
    },
    "르네아": {
        "hp": 1300, 
        "attack": 13, 
        "defense": 40,
        "description": "생명의 숲 최심부를 지키는 전설적인 존재.",
        "pattern_type": "defensive",
        "card_deck": ["꿈꾸기", "중급회복", "숨고르기", "방어와 수복", "불안정한 재생"],
        "reward": "신화의 발자취", 
        "reward_count": 1,
        "pt_range": (5, 8), 
        "money_range": (5, 10)
    },
    # [아르카워드 제도]
    "아사한 원념": {
        "hp": 210, "attack": 20, "defense": 1,
        "pattern_type": "aggressive",
        "card_deck": ["식탐", "폭풍", "아집"], # 임의 배정
        "reward": "깔끔한 열쇠",
        "pt_range": (1000, 1500), "money_range": (4500, 5500)
    },
    "변질된 바람": {
        "hp": 300, "attack": 10, "defense": 10,
        "pattern_type": "balanced",
        "card_deck": ["괴상한바람", "산들바람", "사이클론"],
        "reward": "창공의 은혜",
        "pt_range": (1000, 1500), "money_range": (4500, 5500)
    },
    "폐허를 지키는 문지기": {
        "hp": 330, "attack": 1, "defense": 25,
        "pattern_type": "defensive",
        "card_deck": ["모닝 글로리", "아집", "기본방어"],
        "reward": "투명한 유리", "reward_count": 3,
        "pt_range": (1000, 1500), "money_range": (4500, 5500)
    },
    # [생명의 숲 - 추가 몬스터]
    "냉혹한 원념": {
        "hp": 210, "attack": 15, "defense": 3,
        "pattern_type": "aggressive",
        "card_deck": ["더러운 공격", "육참골단", "인파이트", "상처 벌리기", "연속내치기"],
        "reward": "깔끔한 보물상자", "reward_count": 2,
        "pt_range": (1000, 1500), "money_range": (4500, 5500)
    },
    "사나운 은하새": {
        "hp": 300, "attack": 12, "defense": 8,
        "pattern_type": "balanced",
        "card_deck": ["자각몽", "꿈꾸기", "불안정한 재생", "더러운 공격"],
        "reward": "굳어버린 열매", "reward_count": 2,
        "pt_range": (1000, 1500), "money_range": (4500, 5500)
    },
    # [공간의 신전]
    "취한 파티원": {
        "hp": 310, "attack": 13, "defense": 8,
          "pattern_type": "balanced",
        "money_range": (2000, 3000), "pt_range": (1100, 1200),
        "reward": "오렌지 주스", "reward_count": 5,
        "card_deck": ["방울방울", "방울연발", "차원베기", "찌릿찌릿"]
    },
    "겁쟁이 원념": {
        "hp": 350, "attack": 8, "defense": 15,
          "pattern_type": "defensive",
        "money_range": (1500, 2500), "pt_range": (1100, 1300),
        "reward": "경계꽃 꽃잎", "reward_count": 2,
        "card_deck": ["방울방울", "찌릿찌릿", "작은원망", "연속할퀴기"]
    },
    "폭주 거대 짤똥이": {
        "hp": 300, "attack": 15, "defense": 8,
          "pattern_type": "aggressive",
        "money_range": (3000, 5000), "pt_range": (1300, 1500),
        "reward": "눈덩이", "reward_count": 20,
        "card_deck": ["찌릿찌릿", "순간이동", "차원베기", "폭풍"]
    }
}

def spawn_monster(name):
    data = MONSTER_DATA.get(name)
    if not data: return Monster("이름 없는 원념", 50, 2, 1)
    
# ==================================================================================
# [신규] 던전 지역별 보스 데이터 (1, 2, 3단계)
# ==================================================================================
DUNGEON_BOSSES = {
    "기원의 쌍성": {
        1: {"name": "별의 파편", "hp": 600, "atk": 15, "def": 10, "deck": ["강철타격", "단단한껍질", "기본공격"], "desc": "떨어진 별똥별들이 뭉쳤습니다."},
        2: {"name": "쌍둥이 성좌의 영령", "hp": 1800, "atk": 25, "def": 15, "deck": ["광란", "강철타격", "회피기동"], "desc": "잊혀진 별자리의 기억이 형상화되었습니다."},
        3: {"name": "주신의 흔적", "hp": 5000, "atk": 45, "def": 30, "deck": ["신성한심판", "절대방어", "강철타격"], "desc": "안녕, 나의 작은 친구,"}
    },
    "시간의 신전": {
        1: {"name": "태엽지기 오토마톤", "hp": 550, "atk": 18, "def": 8, "deck": ["강철타격", "연속공격", "기본방어"], "desc": "영원히 작동하는 낡은 기계 병사입니다."},
        2: {"name": "뒤틀린 시간의 망령", "hp": 1700, "atk": 30, "def": 12, "deck": ["심연의주시", "시간역행", "찌릿찌릿"], "desc": "시간의 틈새에 끼어버린 불쌍한 영혼입니다."},
        3: {"name": "과거의 얼룩", "hp": 4800, "atk": 50, "def": 25, "deck": ["멸망의노래", "공간절단", "시간역행"], "desc": "시간의 신화가 미처 보지 못한, 어쩌면 보고 싶지 않았던."}
    },
    "일한산 중턱": {
        1: {"name": "설산의 요정", "hp": 700, "atk": 16, "def": 5, "deck": ["강철타격", "광란", "기본공격"], "desc": "눈보라 속에 숨어있는 하얀 요정입니다."},
        2: {"name": "만년설의 정령", "hp": 2000, "atk": 22, "def": 25, "deck": ["단단한껍질", "얼음창", "대지진"], "desc": "절대 녹지 않는 얼음으로 이루어진 정령입니다."},
        3: {"name": "날뛰는 산군", "hp": 5500, "atk": 60, "def": 20, "deck": ["신성한심판", "광란", "영혼수확"], "desc": "일한산을 지키는 전설 속의 영물입니다."}
    },
    "이루지 못한 꿈들의 별": {
        1: {"name": "악몽 덩어리", "hp": 500, "atk": 12, "def": 3, "deck": ["심연의주시", "기본공격"], "desc": "아이들의 악몽이 뭉쳐 만들어진 슬라임입니다."},
        2: {"name": "꿈을 먹는 맥", "hp": 1600, "atk": 22, "def": 20, "deck": ["영혼수확", "심연의주시", "자각몽"], "desc": "행복한 꿈을 먹어치우는 요괴입니다."},
        3: {"name": "절망의 몽상가", "hp": 4500, "atk": 48, "def": 25, "deck": ["멸망의노래", "영혼수확", "심연의주시"], "desc": "영원히 깨지 않는 악몽 속에 갇힌 마법사입니다."}
    },
    "생명의 숲": {
        1: {"name": "배고픈 고대수", "hp": 800, "atk": 14, "def": 15, "deck": ["단단한껍질", "기본방어", "회복"], "desc": "한동안 누군가를 먹지 못한 움직이는 나무입니다."},
        2: {"name": "맹독 라플레시아", "hp": 1900, "atk": 28, "def": 5, "deck": ["맹독포자", "더러운 공격", "상처 벌리기"], "desc": "지독한 냄새와 독을 뿜는 거대 식물입니다."},
        3: {"name": "생명에 취한 자", "hp": 5200, "atk": 45, "def": 30, "deck": ["영혼수확", "대지진", "맹독포자"], "desc": "생명과 힘에 취한 자의 최후란."}
    },
    "아르카워드 제도": {
        1: {"name": "하늘독수리", "hp": 750, "atk": 18, "def": 20, "deck": ["단단한껍질", "강철타격"], "desc": "하늘을 호령하는 독수리입니다."},
        2: {"name": "고요한 원념", "hp": 1800, "atk": 35, "def": 12, "deck": ["심연의주시", "멸망의노래", "물대포"], "desc": "결국 미쳐버린 주민의 말로입니다."},
        3: {"name": "창공의 왕", "hp": 6000, "atk": 70, "def": 40, "deck": ["대지진", "공간절단", "강철타격"], "desc": "여전히 창공의 전설을 기다리고 있답니다."}
    },
    "공간의 신전": {
        1: {"name": "차원문 파수꾼", "hp": 600, "atk": 22, "def": 5, "deck": ["차원베기", "회피기동"], "desc": "차원의 문을 지키는 기사입니다."},
        2: {"name": "뒤틀린 원념", "hp": 2200, "atk": 38, "def": 20, "deck": ["공간절단", "심연의주시", "광란"], "desc": "왁자지껄함마저 몰아내지 못한 원념입니다."},
        3: {"name": "공허의 불청객", "hp": 7000, "atk": 80, "def": 35, "deck": ["공간절단", "멸망의노래", "절대방어", "신성한심판"], "desc": "존재해서는 안 될 차원의 틈새에서 넘어왔습니다."}
    }
}

def spawn_monster(name):
    """일반 몬스터 소환 함수"""
    data = MONSTER_DATA.get(name)
    if not data: return Monster("이름 없는 원념", 50, 2, 1)
    
    return Monster(
        name=name,
        hp=data["hp"],
        attack=data["attack"],
        defense=data["defense"],
        description=data.get("description", ""),
        pattern_type=data.get("pattern_type", "balanced"),
        reward=data.get("reward"),
        reward_count=data.get("reward_count", 1),
        pt_range=data.get("pt_range", (0, 0)),
        money_range=data.get("money_range", (0, 0)),
        card_deck=data.get("card_deck")
    )

def get_dungeon_boss(region_name, depth):
    """던전 깊이에 따른 보스 몬스터 소환 함수"""
    # 깊이에 따른 티어 계산 (30, 60, 90층 기준)
    if depth < 60: tier = 1      # ~59층 (실제로는 29층에서 1단계 등장)
    elif depth < 90: tier = 2    # 60~89층
    else: tier = 3               # 90층 이상
    
    # 해당 지역의 보스 데이터 가져오기 (없으면 기본값: 기원의 쌍성)
    region_bosses = DUNGEON_BOSSES.get(region_name, DUNGEON_BOSSES["기원의 쌍성"])
    boss_data = region_bosses.get(tier, region_bosses[3]) # 티어가 없으면 가장 강한 보스
    
    # Monster 객체 생성
    boss = Monster(
        name=f"👑 {boss_data['name']}",
        hp=boss_data['hp'],
        attack=boss_data['atk'],
        defense=boss_data['def'],
        description=boss_data['desc'],
        pattern_type="aggressive" if tier >= 2 else "balanced",
        reward="보스 전리품", # 보상은 subjugation.py에서 처리
        money_range=(boss_data['hp']*2, boss_data['hp']*4),
        pt_range=(boss_data['atk']*10, boss_data['atk']*20),
        card_deck=boss_data['deck']
    )
    
    # 90층 이후 3단계 보스 반복 시 스탯 추가 보정 (무한 성장)
    if depth > 90:
        multiplier = (depth - 90) // 30
        if multiplier > 0:
            boss.max_hp += int(boss.max_hp * 0.2 * multiplier)
            boss.current_hp = boss.max_hp
            boss.attack += int(boss.attack * 0.1 * multiplier)
            boss.defense += int(boss.defense * 0.1 * multiplier)
            boss.name = f"👑 {boss_data['name']} (Lv.{multiplier+1})"

    return boss

# ==================================================================================
# [신규] 길드 레이드 보스 데이터
# ==================================================================================
RAID_BOSS_DATA = {
    "Gold": {
        "name": "대지의 형상", "hp": 5000, "atk": 30, "def": 30,
        "desc": "약하기에 비춰지지 않는 것이다.",
        "deck": ["대지진(광역)", "단단한껍질", "강철타격", "기본공격"],
        "reward_tokens": {"wood": 50, "iron": 30, "magic": 10}
    },
    "Platinum": {
        "name": "겁화의 형상", "hp": 15000, "atk": 50, "def": 40,
        "desc": "낙원은 이미 불타버렸다.",
        "deck": ["화염숨결(광역)", "포효(광역)", "광란", "영혼수확"],
        "reward_tokens": {"iron": 50, "magic": 30, "sorcery": 10}
    },
    "Diamond": {
        "name": "끝의 형상", "hp": 50000, "atk": 80, "def": 60,
        "desc": "네가 떠올렸다 한들, 내 상처가 낫는 건 아닌지라.",
        "deck": ["멸망의노래", "공간절단", "대지진(광역)", "화염숨결(광역)", "신성한심판"],
        "reward_tokens": {"magic": 50, "sorcery": 30, "wood": 100}
    }
}

def get_raid_boss(rank):
    data = RAID_BOSS_DATA.get(rank, RAID_BOSS_DATA["Gold"])
    # 레이드 보스는 Monster 클래스 재사용 (패턴 타입은 aggressive 고정)
    return Monster(name=f"👹 {data['name']}", hp=data['hp'], attack=data['atk'], defense=data['def'], description=data['desc'], pattern_type="aggressive", card_deck=data['deck'])
