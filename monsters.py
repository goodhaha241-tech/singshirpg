# monsters.py
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