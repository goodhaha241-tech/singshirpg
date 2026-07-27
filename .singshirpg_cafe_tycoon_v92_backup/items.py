# items.py
# 아이템 데이터, 지역 정보, 제작 레시피, 소비 아이템 효과 정의

# ==================================================================================
# 1. 아이템 목록 정의
# ==================================================================================
COMMON_ITEMS = [
    "사과", "녹슨 철", "깃털나무 잎사귀", "초코과자", "낡은 보물상자", 
    "낡은 열쇠", "평범한 나무판자", "빈 앨범", "두루마리 종이", "빛구슬", "낡은 모래시계",
    "흐린 꿈", "구름 한 줌", "이상한 새순", "깔끔한 보물상자", "깔끔한 열쇠",
    "부서진 스틱", "소멸의 흔적", "재생의 흔적", "나뭇가지", 
    "바람깃펜", "하늘잉크", "아르카워드의 문장",
    "버려진 장갑", "섬세한 보물상자", 
    "오렌지 주스", "새보눈 씨앗", "눈 스프레이", "파티용 모자",
    "빵잉어", "빵붕어", "민물배스", "피라미",
    # [길드 자재]
    "목재", "철괴", "중급 마력석", "주술석", "구름 블럭",
    # [노드 해역 일반]
    "메롱물고기", "꽁다리치", "쵸비고기", "밭갱어"
]

RARE_ITEMS = [
    "장식용 열쇠", "무지개 열매", "설국 열매", "사랑나무 가지", 
    "빈 팬던트", "하급 마력석", "반짝가루", "투명한 유리", "시간의 모래", 
    "천년얼음", "혹한의 눈꽃", "맑은 생각", "악몽 파편", "별모양 별",
    "뒤틀린 씨앗", "굳어버린 열매", "창공의 은혜", "무지개 한조각", "부유석",
    "물고기 비늘",
    "경계꽃 꽃잎", "대리석 씨앗", "희미한 다정함", "희미한 친절함",
    # [길드 고급 자재]
    "양질 목재", "강화 철강", "상급 마력석", "고급 주술석", "응결 구름 블럭",
    # [물고기]
    "모래무지", "버들치", "쉬리", "각시붕어",
    "어름치", "동사리", "송사리", "버들매치", "가는돌고기",
    # [노드 해역 희귀]
    "등불오징어", "명이태", "로운새우", "돔돌치"
]

GUILD_ITEMS = [
    "목재", "철괴", "중급 마력석", "주술석", "구름 블럭",
    "양질 목재", "강화 철강", "상급 마력석", "고급 주술석", "응결 구름 블럭"
]

LIMITED_ONE_TIME_ITEMS = []

# ==================================================================================
# 2. 아이템 상세 정보 및 가격
# ==================================================================================
ITEM_CATEGORIES = {
    # --- [기원의 쌍성] ---
    "사과": {"type": "material", "area": "기원의 쌍성", "price": 50},
    "녹슨 철": {"type": "material", "area": "기원의 쌍성", "price": 30},
    "깃털나무 잎사귀": {"type": "material", "area": "기원의 쌍성", "price": 80},
    "초코과자": {"type": "material", "area": "기원의 쌍성", "price": 40},
    "평범한 나무판자": {"type": "material", "area": "기원의 쌍성", "price": 60},
    
    # --- [시간의 신전] ---
    "빈 앨범": {"type": "material", "area": "시간의 신전", "price": 60},
    "두루마리 종이": {"type": "material", "area": "시간의 신전", "price": 80},
    "빛구슬": {"type": "material", "area": "시간의 신전", "price": 50},
    "낡은 모래시계": {"type": "material", "area": "시간의 신전", "price": 40},

    # --- [일한산 중턱] ---
    "눈덩이": {"type": "material", "area": "일한산 중턱", "price": 50},
    "굴레늑대 털": {"type": "material", "area": "일한산 중턱", "price": 100},
    "버려진 장갑": {"type": "material", "area": "일한산 중턱", "price": 80},
    "나뭇가지": {"type": "material", "area": "일한산 중턱", "price": 30}, 
    "버려진 팬던트": {"type": "material", "area": "일한산 중턱", "price": 200},

    # --- [이루지 못한 꿈들의 별] ---
    "흐린 꿈": {"type": "material", "area": "이루지 못한 꿈들의 별", "price": 100},
    "구름 한 줌": {"type": "material", "area": "이루지 못한 꿈들의 별", "price": 120},
    "이상한 새순": {"type": "material", "area": "이루지 못한 꿈들의 별", "price": 150},

    # --- [생명의 숲] ---
    "부서진 스틱": {"type": "material", "area": "생명의 숲", "price": 80},
    "소멸의 흔적": {"type": "material", "area": "생명의 숲", "price": 150},
    "재생의 흔적": {"type": "material", "area": "생명의 숲", "price": 150},

    # --- [아르카워드 제도] ---
    "바람깃펜": {"type": "material", "area": "아르카워드 제도", "price": 200},
    "하늘잉크": {"type": "material", "area": "아르카워드 제도", "price": 250},
    "아르카워드의 문장": {"type": "material", "area": "아르카워드 제도", "price": 300},

    # --- [노드 해역] ---
    "물고기 비늘": {"type": "rare_mat", "area": "노드 해역", "price": 400},

    # --- [노드 해역 물고기] ---
    "메롱물고기": {"type": "fish", "tier": "node_common", "area": "노드 해역", "price": 100},
    "등불오징어": {"type": "fish", "tier": "node_rare", "area": "노드 해역", "price": 500},
    "꽁다리치": {"type": "fish", "tier": "node_common", "area": "노드 해역", "price": 120},
    "명이태": {"type": "fish", "tier": "node_rare", "area": "노드 해역", "price": 450},
    "로운새우": {"type": "fish", "tier": "node_rare", "area": "노드 해역", "price": 400},
    "쵸비고기": {"type": "fish", "tier": "node_common", "area": "노드 해역", "price": 110},
    "돔돌치": {"type": "fish", "tier": "node_rare", "area": "노드 해역", "price": 500},
    "밭갱어": {"type": "fish", "tier": "node_common", "area": "노드 해역", "price": 130},

    # --- [공간의 신전] ---
    "오렌지 주스": {"type": "material", "area": "공간의 신전", "price": 100},
    "새보눈 씨앗": {"type": "material", "area": "공간의 신전", "price": 120},
    "눈 스프레이": {"type": "material", "area": "공간의 신전", "price": 150},
    "파티용 모자": {"type": "material", "area": "공간의 신전", "price": 200},
    "경계꽃 꽃잎": {"type": "rare_mat", "area": "공간의 신전", "price": 1600},
    "대리석 씨앗": {"type": "rare_mat", "area": "공간의 신전", "price": 1800},
    "희미한 다정함": {"type": "rare_mat", "area": "공간의 신전", "price": 2000},
    "희미한 친절함": {"type": "rare_mat", "area": "공간의 신전", "price": 2000},

    # --- [길드 자재] ---
    "목재": {"type": "material", "price": 100},
    "철괴": {"type": "material", "price": 150},
    "중급 마력석": {"type": "material", "price": 300},
    "주술석": {"type": "material", "price": 500},
    "구름 블럭": {"type": "material", "price": 200},
    "양질 목재": {"type": "rare_mat", "price": 500},
    "강화 철강": {"type": "rare_mat", "price": 800},
    "상급 마력석": {"type": "rare_mat", "price": 1500},
    "고급 주술석": {"type": "rare_mat", "price": 2000},
    "응결 구름 블럭": {"type": "rare_mat", "price": 1200},
    
    # --- [희귀 재료] ---
    "장식용 열쇠": {"type": "rare_mat", "price": 150}, 
    "무지개 열매": {"type": "rare_mat", "price": 300}, 
    "설국 열매": {"type": "rare_mat", "price": 300}, 
    "사랑나무 가지": {"type": "rare_mat", "price": 350}, 
    "빈 팬던트": {"type": "rare_mat", "price": 120}, 
    "하급 마력석": {"type": "rare_mat", "price": 400}, 
    "반짝가루": {"type": "rare_mat", "price": 300},
    "투명한 유리": {"type": "rare_mat", "price": 300},
    "시간의 모래": {"type": "rare_mat", "price": 350},
    "천년얼음": {"type": "rare_mat", "price": 500},
    "혹한의 눈꽃": {"type": "rare_mat", "price": 800},
    "맑은 생각": {"type": "rare_mat", "price": 1000},
    "악몽 파편": {"type": "rare_mat", "price": 1200},
    "별모양 별": {"type": "rare_mat", "price": 1500},
    "뒤틀린 씨앗": {"type": "rare_mat", "price": 2500}, 
    "굳어버린 열매": {"type": "rare_mat", "price": 3000}, 
    "창공의 은혜": {"type": "rare_mat", "area": "아르카워드 제도", "price": 3000},
    "무지개 한조각": {"type": "rare_mat", "area": "아르카워드 제도", "price": 3500},
    "부유석": {"type": "rare_mat", "area": "아르카워드 제도", "price": 4000},
    "신화의 발자취": {"type": "mythic", "price": 0, "description": "신화의 흔적"},

    # --- [물고기 - 일반] ---
    "빵잉어": {"type": "fish", "tier": "common", "price": 100}, 
    "빵붕어": {"type": "fish", "tier": "common", "price": 100}, 
    "민물배스": {"type": "fish", "tier": "common", "price": 120}, 
    "피라미": {"type": "fish", "tier": "common", "price": 80},
    # --- [물고기 - 희귀] ---
    "모래무지": {"type": "fish", "tier": "rare", "price": 300}, 
    "버들치": {"type": "fish", "tier": "rare", "price": 350},
    "쉬리": {"type": "fish", "tier": "rare", "price": 400}, 
    "각시붕어": {"type": "fish", "tier": "rare", "price": 450},
    # --- [물고기 - 고급] ---
    "어름치": {"type": "fish", "tier": "advanced", "price": 1000}, 
    "동사리": {"type": "fish", "tier": "advanced", "price": 1200},
    "송사리": {"type": "fish", "tier": "advanced", "price": 1500}, 
    "버들매치": {"type": "fish", "tier": "advanced", "price": 1800},
    "가는돌고기": {"type": "fish", "tier": "advanced", "price": 2000},

    # --- [소모품 및 텃밭 아이템] ---
    "작은 회복약": {"type": "consumable", "effect": "hp", "value": 20, "price": 40},
    "작은 비타민": {"type": "consumable", "effect": "mental", "value": 20, "price": 30},
    "일반 회복약": {"type": "consumable", "effect": "hp", "value": 50, "price": 130},
    "일반 비타민": {"type": "consumable", "effect": "mental", "value": 50, "price": 120},
    "이상한 씨앗": {"type": "consumable", "price": 300, "description": "텃밭에 심을 수 있는 기본 씨앗"},
    "신비한 비료": {"type": "consumable", "price": 500, "description": "텃밭의 작물에 희귀한 힘을 부여합니다."},

    # --- [제작/기타] ---
    "아티팩트 제작키트": {"type": "crafted", "price": 500},
    "이름 변경권": {"type": "consumable", "price": 120000},
    "강화키트": {"type": "consumable", "price": 50000},

    # --- [제작 결과물] ---
    "열매 샐러드": {"type": "crafted", "price": 1000}, 
    "허술한 장식품": {"type": "crafted", "price": 700}, 
    "투명한 조화": {"type": "crafted", "price": 700}, 
    "간단한 다과": {"type": "crafted", "price": 800}, 
    "기억 종이": {"type": "crafted", "price": 300},
    "추억사진첩": {"type": "crafted", "price": 2500},
    "섬세한 열쇠": {"type": "crafted", "price": 1000},
    "찬란한 유리병": {"type": "crafted", "price": 1200},
    "신전의 등불": {"type": "crafted", "price": 1800},
    "눈꽃팬던트": {"type": "crafted", "price": 3000},
    "얼음썬캐쳐": {"type": "crafted", "price": 4000},
    "따스한 목도리": {"type": "crafted", "price": 500},
    "눈사람": {"type": "crafted", "price": 5000},
    "일한산의 정수": {"type": "crafted", "price": 10000},
    "친절함 한 스푼": {"type": "crafted", "price": 2000},
    "다정함 한 스푼": {"type": "crafted", "price": 2000},
    "별자리 망원경": {"type": "crafted", "price": 2000},
    "태양 선글라스": {"type": "crafted", "price": 2000},
    "악몽 프라페": {"type": "crafted", "price": 4000},
    "작은 테라리움": {"type": "crafted", "price": 20000},
    "정교한 나무조각상": {"type": "crafted", "price": 30000}, 
    "삶의 흔적": {"type": "crafted", "price": 13000},
    "창공마크": {"type": "crafted", "price": 30000},
    "예쁜 선물상자": {"type": "crafted", "price": 13000},
    "비늘 목걸이": {"type": "crafted", "price": 3000},
    "불꽃놀이 세트": {"type": "crafted", "price": 10000},
    "수제 설국청": {"type": "crafted", "price": 12000},
    "설국 열매 조각": {"type": "crafted", "price": 100},
    "무지개 열매 조각": {"type": "crafted", "price": 100},
    "달빛 머금은 잎사귀": {"type": "crafted", "price": 12000, "area": "생명의 숲"},
    "생명의 정수": {"type": "crafted", "price": 12000, "area": "생명의 숲"},
    "행운의 부적": {"type": "crafted", "price": 15000, "description": "사용 시 다음 조사(10턴) 동안 성공 확률이 5% 증가합니다."},

    # --- [신규 소모품 (부적 등)] ---
    "건승의 부적": {"type": "consumable", "price": 5000},
    "행복의 부적": {"type": "consumable", "price": 5000},
    "성공의 부적": {"type": "consumable", "price": 10000},
    "바닷물고기 회": {"type": "consumable", "price": 5000},
    "카이의 자비": {"type": "consumable", "price": 20000},
    "파티 풀세트": {"type": "consumable", "price": 8000},
    "다과 풀세트": {"type": "consumable", "price": 8000},
    "그림 풀세트": {"type": "consumable", "price": 15000},
    
    # --- [스탯 상승 영구/일시 아이템] ---
    "삶의 문장": {"type": "consumable", "price": 10000},
    "순환의 문장": {"type": "consumable", "price": 10000},
    "형상각인기": {"type": "consumable", "price": 15000},
    "구름다리 스낵": {"type": "consumable", "price": 12000},
    "아르카워드의 영광": {"type": "consumable", "price": 12000},
    "자그마한 바람": {"type": "consumable", "price": 20000},   

    # --- [보물상자] ---
    "낡은 보물상자": {"type": "box", "price": 100}, 
    "섬세한 보물상자": {"type": "box", "price": 500},
    "깔끔한 보물상자": {"type": "box", "price": 2000},
    "낡은 열쇠": {"type": "box_key", "price": 100},
    "깔끔한 열쇠": {"type": "box_key", "price": 500},
}

ITEM_PRICES = {name: info["price"] for name, info in ITEM_CATEGORIES.items() if "price" in info}

# ==================================================================================
# 3. 지역 정보 정의 (노드 해역 추가)
# ==================================================================================
REGIONS = {
    "기원의 쌍성": {
        "fail_rate": 0.1, 
        "energy_cost": 2, 
        "common": ["사과", "녹슨 철", "깃털나무 잎사귀", "초코과자", "낡은 보물상자", "낡은 열쇠", "평범한 나무판자"], 
        "rare": ["장식용 열쇠", "무지개 열매", "설국 열매", "사랑나무 가지"], 
        "unlock_cost": 0
    },
    "시간의 신전": {
        "fail_rate": 0.3, 
        "energy_cost": 3, 
        "common": ["평범한 나무판자", "녹슨 철", "빛구슬", "빈 앨범", "두루마리 종이", "낡은 모래시계"], 
        "rare": ["빈 팬던트", "하급 마력석", "반짝가루", "투명한 유리", "시간의 모래"], 
        "unlock_cost": 30000
    },
    "일한산 중턱": {
        "fail_rate": 0.3, 
        "energy_cost": 4, 
        "common": ["눈덩이", "굴레늑대 털", "버려진 장갑", "나뭇가지", "녹슨 철"], 
        "rare": ["설국 열매", "천년얼음", "혹한의 눈꽃"], 
        "unlock_cost": 70000
    },
    "이루지 못한 꿈들의 별": {
        "fail_rate": 0.35, 
        "energy_cost": 5, 
        "common": ["빛구슬", "깔끔한 보물상자", "깔끔한 열쇠", "흐린 꿈", "구름 한 줌", "이상한 새순"], 
        "rare": ["무지개 열매", "맑은 생각", "악몽 파편", "별모양 별", "반짝가루", "빈 팬던트"], 
        "unlock_cost": 200000
    },
    "생명의 숲": {
        "fail_rate": 0.35,
        "energy_cost": 10, 
        "common": ["나뭇가지", "사과", "이상한 새순", "부서진 스틱", "소멸의 흔적", "재생의 흔적", "깔끔한 보물상자"],
        "rare": ["사랑나무 가지", "하급 마력석", "뒤틀린 씨앗", "굳어버린 열매"],
        "unlock_cost": 300000, 
        "pt_cost": 5000
    },
    "아르카워드 제도": {
        "fail_rate": 0.4,
        "energy_cost": 15,
        "common": ["구름 한 줌", "두루마리 종이", "평범한 나무판자", "바람깃펜", "하늘잉크", "아르카워드의 문장"],
        "rare": ["투명한 유리", "천년얼음", "사랑나무 가지", "창공의 은혜", "무지개 한조각", "부유석"],
        "unlock_cost": 500000, 
        "pt_cost": 10000
    },
    "노드 해역": {
        "fail_rate": 0.3, 
        "energy_cost": 15,
        "common": ["녹슨 철", "평범한 나무판자", "버려진 장갑", "부서진 스틱", "낡은 열쇠", "낡은 보물상자", "섬세한 보물상자", "깔끔한 보물상자"],
        "rare": ["시간의 모래", "하급 마력석", "장식용 열쇠", "무지개 한조각", "물고기 비늘"],
        "unlock_cost": 700000,
        "pt_cost": 10000
    },
    "공간의 신전": {
        "fail_rate": 0.4,
        "energy_cost": 20,
        "common": ["빈 앨범", "초코과자", "흐린 꿈", "오렌지 주스", "새보눈 씨앗", "눈 스프레이", "파티용 모자"],
        "rare": ["별모양 별", "장식용 열쇠", "부유석", "경계꽃 꽃잎", "대리석 씨앗", "희미한 다정함", "희미한 친절함"],
        "unlock_cost": 0
    }
}

# ==================================================================================
# 4. 제작 레시피 정의 (씨앗 변환 포함)
# ==================================================================================
CRAFT_RECIPES = {
    # [씨앗 변환 레시피 - GardenView에서 주로 참조]
    "weird_seed_twisted": {"need": {"뒤틀린 씨앗": 1}, "result": "이상한 씨앗", "count": 3, "region": "기타"},
    "weird_seed_marble": {"need": {"대리석 씨앗": 1}, "result": "이상한 씨앗", "count": 3, "region": "기타"},
    "weird_seed_bird": {"need": {"새보눈 씨앗": 1}, "result": "이상한 씨앗", "count": 1, "region": "기타"},

    # [기본]
    "make_box_common": {"need": {"평범한 나무판자": 3}, "result": "낡은 보물상자"},
    "make_box_rare": {"need": {"섬세한 열쇠": 1, "평범한 나무판자": 5}, "result": "섬세한 보물상자"},
    "make_key": {"need": {"녹슨 철": 3}, "result": "낡은 열쇠"},
    "salad": {"need": {"설국 열매": 1, "무지개 열매": 1}, "result": "열매 샐러드"},
    "ornament": {"need": {"녹슨 철": 1, "깃털나무 잎사귀": 1}, "result": "허술한 장식품"},
    "flower": {"need": {"깃털나무 잎사귀": 1, "사랑나무 가지": 1}, "result": "투명한 조화"},
    "snack": {"need": {"초코과자": 1, "사과": 1}, "result": "간단한 다과"},
    "process_snow_fruit": {"need": {"설국 열매": 1}, "result": "설국 열매 조각", "count": 3},
    "process_rainbow_fruit": {"need": {"무지개 열매": 1}, "result": "무지개 열매 조각", "count": 3},
    
    # [시간의 신전]
    "fancy_key": {"need": {"장식용 열쇠": 1, "낡은 열쇠": 1, "빛구슬": 1}, "result": "섬세한 열쇠", "region": "시간의 신전"},
    "make_memory_paper": {"need": {"두루마리 종이": 1, "빛구슬": 1}, "result": "기억 종이", "region": "시간의 신전"},
    "make_album": {"need": {"빈 앨범": 1, "기억 종이": 3}, "result": "추억사진첩", "region": "시간의 신전"},
    "shining_bottle": {"need": {"투명한 유리": 1, "빛구슬": 2, "반짝가루": 1}, "result": "찬란한 유리병", "region": "시간의 신전"},
    "temple_lantern": {"need": {"녹슨 철": 2, "빛구슬": 3, "하급 마력석": 1}, "result": "신전의 등불", "region": "시간의 신전"},
    
    # [일한산 중턱]
    "snow_pendant": {"need": {"빈 팬던트": 1, "혹한의 눈꽃": 1}, "result": "눈꽃팬던트", "region": "일한산 중턱"},
    "ice_suncatcher": {"need": {"천년얼음": 1, "녹슨 철": 2, "사랑나무 가지": 1}, "result": "얼음썬캐쳐", "region": "일한산 중턱"},
    "warm_scarf": {"need": {"굴레늑대 털": 3}, "result": "따스한 목도리", "region": "일한산 중턱"},
    "snowman": {"need": {"눈덩이": 5, "따스한 목도리": 1, "버려진 장갑": 2, "나뭇가지": 2}, "result": "눈사람", "region": "일한산 중턱"},
    "ilhan_essence": {"need": {"반짝가루": 2, "시간의 모래": 2, "혹한의 눈꽃": 1}, "result": "일한산의 정수", "region": "일한산 중턱"},
    
    # [이루지 못한 꿈들의 별]
    "spoon_kindness": {"need": {"구름 한 줌": 3, "낡은 모래시계": 2, "맑은 생각": 1, "추억사진첩": 2}, "result": "친절함 한 스푼", "region": "이루지 못한 꿈들의 별"},
    "spoon_affection": {"need": {"별모양 별": 1, "흐린 꿈": 3, "따스한 목도리": 1, "열매 샐러드": 2}, "result": "다정함 한 스푼", "region": "이루지 못한 꿈들의 별"},
    "telescope": {"need": {"반짝가루": 2, "구름 한 줌": 3, "허술한 장식품": 2, "별모양 별": 1}, "result": "별자리 망원경", "region": "이루지 못한 꿈들의 별"},
    "sunglasses": {"need": {"이상한 새순": 5, "신전의 등불": 2, "악몽 파편": 1, "맑은 생각": 1}, "result": "태양 선글라스", "region": "이루지 못한 꿈들의 별"},
    "nightmare_frappe": {"need": {"악몽 파편": 2, "하급 마력석": 1}, "result": "악몽 프라페", "region": "이루지 못한 꿈들의 별"},
    "terrarium": {"need": {"일한산의 정수": 1, "찬란한 유리병": 1, "간단한 다과": 5, "친절함 한 스푼": 1}, "result": "작은 테라리움", "region": "이루지 못한 꿈들의 별"},
    
    # [생명의 숲]
    "life_emblem": {"need": {"재생의 흔적": 2, "이상한 새순": 1, "뒤틀린 씨앗": 3, "작은 테라리움": 1}, "result": "삶의 문장", "region": "생명의 숲"},
    "cycle_emblem": {"need": {"재생의 흔적": 1, "소멸의 흔적": 1, "나뭇가지": 1, "굳어버린 열매": 3, "작은 테라리움": 1}, "result": "순환의 문장", "region": "생명의 숲"},
    "shape_engraver": {"need": {"부서진 스틱": 5, "얼음썬캐쳐": 1, "신전의 등불": 3}, "result": "형상각인기", "region": "생명의 숲"},
    "life_essence": {"need": {"재생의 흔적": 3}, "result": "생명의 정수", "region": "생명의 숲"},
    "moonlight_leaf": {"need": {"소멸의 흔적": 3}, "result": "달빛 머금은 잎사귀", "region": "생명의 숲"},
    "swollen_fruit": {"need": {"간단한 다과": 3, "굳어버린 열매": 1}, "result": "불어난 열매", "count": 3, "region": "생명의 숲"},
    "wooden_statue": {"need": {"나뭇가지": 10, "부서진 스틱": 5}, "result": "정교한 나무조각상", "region": "생명의 숲"},
    "trace_of_life": {"need": {"소멸의 흔적": 5, "재생의 흔적": 5}, "result": "삶의 흔적", "region": "생명의 숲"},
    "artifact_kit": {"need": {"천년얼음": 3, "녹슨 철": 20, "빈 팬던트": 3, "낡은 모래시계": 10}, "result": "아티팩트 제작키트", "region": "생명의 숲"},
    
    # [아르카워드 제도]
    "cloud_snack": {"need": {"구름 한 줌": 2, "초코과자": 1, "바람깃펜": 3, "무지개 한조각": 1, "찬란한 유리병": 3}, "result": "구름다리 스낵", "region": "아르카워드 제도"},
    "archaward_glory": {"need": {"아르카워드의 문장": 1, "하늘잉크": 1, "두루마리 종이": 1, "창공의 은혜": 3, "태양 선글라스": 1}, "result": "아르카워드의 영광", "region": "아르카워드 제도"},
    "small_wind": {"need": {"구름 한 줌": 5, "따스한 목도리": 1, "형상각인기": 3}, "result": "자그마한 바람", "region": "아르카워드 제도"},
    "cotton_candy": {"need": {"구름 한 줌": 3}, "result": "솜사탕", "region": "아르카워드 제도"},
    "painting_set": {"need": {"바람깃펜": 1, "하늘잉크": 2}, "result": "그림세트", "region": "아르카워드 제도"},
    "cloud_cookie": {"need": {"구름다리 스낵": 1}, "result": "구름과자 낱개", "count": 3, "region": "아르카워드 제도"},
    "sky_mark": {"need": {"창공의 은혜": 2, "아르카워드의 문장": 3}, "result": "창공마크", "region": "아르카워드 제도"},
    "pretty_box": {"need": {"낡은 보물상자": 2}, "result": "예쁜 선물상자", "region": "아르카워드 제도"},

    # [노드 해역]
    "win_charm": {"need": {"눈꽃팬던트": 1, "따스한 목도리": 5, "삶의 흔적": 5, "물고기 비늘": 3}, "result": "건승의 부적", "region": "노드 해역"},
    "happy_charm": {"need": {"얼음썬캐쳐": 1, "따스한 목도리": 5, "태양 선글라스": 2, "물고기 비늘": 3}, "result": "행복의 부적", "region": "노드 해역"},
    "success_charm": {"need": {"일한산의 정수": 1, "따스한 목도리": 5, "별자리 망원경": 2, "물고기 비늘": 3}, "result": "성공의 부적", "region": "노드 해역"},
    "scale_necklace": {"need": {"물고기 비늘": 2, "나뭇가지": 3}, "result": "비늘 목걸이", "region": "노드 해역"},
    "sashimi": {"need": {"물고기 비늘": 3, "창공마크": 1}, "result": "바닷물고기 회", "region": "노드 해역"},
    "kai_mercy": {"need": {"자그마한 바람": 1, "정교한 나무조각상": 2, "물고기 비늘": 2}, "result": "카이의 자비", "region": "노드 해역"},
    "lucky_charm": {"need": {"장식용 열쇠": 3, "반짝가루": 5, "물고기 비늘": 5}, "result": "행운의 부적", "region": "노드 해역"},

    # [공간의 신전]
    "party_set": {"need": {"간단한 다과": 3, "구름다리 스낵": 1, "파티용 모자": 4, "눈 스프레이": 2}, "result": "파티 풀세트", "region": "공간의 신전"},
    "snack_set": {"need": {"간단한 다과": 3, "악몽 프라페": 2, "오렌지 주스": 6}, "result": "다과 풀세트", "region": "공간의 신전"},
    "painting_full": {"need": {"바람깃펜": 5, "하늘잉크": 5, "경계꽃 꽃잎": 2, "대리석 씨앗": 2, "정교한 나무조각상": 1}, "result": "그림 풀세트", "region": "공간의 신전"},
    "fireworks": {"need": {"부유석": 1, "무지개 한조각": 2, "소멸의 흔적": 3, "나뭇가지": 6, "새보눈 씨앗": 6}, "result": "불꽃놀이 세트", "region": "공간의 신전"},
    "snow_syrup": {"need": {"흐린 꿈": 6, "설국 열매": 1, "혹한의 눈꽃": 2, "초코과자": 6}, "result": "수제 설국청", "region": "공간의 신전"},
    "kindness_spoon": {"need": {"친절함 한 스푼": 1, "희미한 친절함": 2, "새보눈 씨앗": 6}, "result": "친절함 한 스푼", "count": 3, "region": "공간의 신전"},
    "affection_spoon": {"need": {"다정함 한 스푼": 1, "희미한 다정함": 2, "새보눈 씨앗": 6}, "result": "다정함 한 스푼", "count": 3, "region": "공간의 신전"},
    "nightmare_frappe_2": {"need": {"악몽 프라페": 1, "경계꽃 꽃잎": 1, "흐린 꿈": 10}, "result": "악몽 프라페", "count": 2, "region": "공간의 신전"},
}

# ==================================================================================
# 5. 스탯 상승 아이템 효과 정의
# ==================================================================================
STAT_UP_ITEMS = {
    # [기존 스탯 아이템]
    "추억사진첩": {"stat": "attack", "value": 3, "max_stat": 30},
    "찬란한 유리병": {"stat": "attack", "value": 2, "max_stat": 20},
    "허술한 장식품": {"stat": "attack", "value": 1, "max_stat": 10},
    "투명한 조화": {"stat": "defense", "value": 1, "max_stat": 10},
    "신전의 등불": {"stat": "defense", "value": 2, "max_stat": 20},
    "눈꽃팬던트": {"stat": "max_mental", "value": 10, "max_stat": 200},
    "얼음썬캐쳐": {"stat": "max_hp", "value": 20, "max_stat": 300},
    "눈사람": {"stat": "max_mental", "value": 15, "max_stat": 250},
    "일한산의 정수": {"stat": "defense", "value": 3, "max_stat": 40},
    "친절함 한 스푼": {"stat": "attack", "value": 2, "max_stat": 40},
    "다정함 한 스푼": {"stat": "defense", "value": 1, "max_stat": 50},
    "별자리 망원경": {"stat": "max_hp", "value": 20, "max_stat": 320},
    "태양 선글라스": {"stat": "max_mental", "value": 15, "max_stat": 300},
    
    # [고급 스탯 아이템]
    "삶의 문장": {"stat": "attack", "value": 3, "max_stat": 55},
    "순환의 문장": {"stat": "defense", "value": 2, "max_stat": 55},
    "형상각인기": {"stat": "defense_rate", "value": 1, "max_stat": 10}, 
    "구름다리 스낵": {"stat": "attack", "value": 1, "max_stat": 62},
    "아르카워드의 영광": {"stat": "defense", "value": 1, "max_stat": 62},
    "자그마한 바람": {"stat": "defense_rate", "value": 1, "max_stat": 15},

    # [신규 버프형 아이템 - battle.py에서 duration 처리 필요]
    "행운의 부적": {"stat": "success_rate", "value": 5, "duration": 10},
    "건승의 부적": {"stat": "attack", "value": 10, "duration": 3},
    "행복의 부적": {"stat": "defense", "value": 10, "duration": 3},
    "성공의 부적": {"stat": "success_rate", "value": 10, "duration": 30},
    "카이의 자비": {"stat": "defense_rate", "value": 1, "max_stat": 20},
    "파티 풀세트": {"stat": "attack", "value": 15, "duration": 3},
    "다과 풀세트": {"stat": "defense", "value": 15, "duration": 3},
    "그림 풀세트": {"stat": "success_rate", "value": 15, "duration": 30}
}