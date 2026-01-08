# artifacts.py
import random
import uuid

# ==================================================================================
# 1. 데이터 정의
# ==================================================================================

# 아티팩트 종류
ARTIFACT_TYPES = ["목걸이", "반지", "부적", "브로치", "귀걸이", "지팡이", "검집", "망토", "모자", "나침반"]
ARTIFACT_TYPES_3STAR = ["티아라", "투구", "보주", "성배", "왕관"]

# 등급별 접두사 목록
PREFIXES = {
    1: ["낡은", "손상된", "오래된", "망가진", "먼지쌓인", "흔한"],
    2: ["섬세한", "온전한", "평범한", "깔끔한", "멀끔한", "빛나는"],
    3: [
        "꼼꼼한",   # 주사위 재사용
        "맹렬한",   # 공격력 비례 추가 피해
        "견고한",   # 방어력 비례 회복
        "앙심품은", # 피해 반사
        "고조된",   # 주사위 값 폭주
        "불멸의",   # 1회 부활
        "황금의",   # (히든/각인) 영산 전용
        "악몽의"    # (히든/각인) 루우데 전용
    ]
}

# 3성 접두사별 특수 능력 코드 매핑
SPECIAL_EFFECTS = {
    "꼼꼼한": "reuse_last_dice",
    "맹렬한": "fierce_attack",
    "견고한": "sturdy_defense",
    "앙심품은": "reflection",
    "고조된": "escalation",
    "불멸의": "immortality",
    "황금의": "youngsan_gold", # 영산 각인 전용
    "악몽의": "luude_imprint"  # 루우데 각인 전용
}

# ==================================================================================
# 2. 핵심 로직 함수
# ==================================================================================

def _generate_stats(rank):
    """
    등급에 따른 랜덤 스탯 딕셔너리 반환
    Rank 1: 단일 스탯 (낮음)
    Rank 2: 복합 스탯 (중간)
    Rank 3: 복합 스탯 (높음) + 확률적 방어율(Defense Rate)
    """
    stats = {"max_hp": 0, "max_mental": 0, "attack": 0, "defense": 0, "defense_rate": 0}
    
    if rank == 1:
        # HP/Mental 중 하나 or Atk/Def 중 하나
        if random.random() < 0.6:
            stats[random.choice(["max_hp", "max_mental"])] = random.randint(15, 35)
        else:
            stats[random.choice(["attack", "defense"])] = random.randint(1, 3)

    elif rank == 2:
        # HP/Mental 중 하나 + Atk/Def 중 하나
        s1 = random.choice(["max_hp", "max_mental"])
        stats[s1] = random.randint(20, 50)
        s2 = random.choice(["attack", "defense"])
        stats[s2] = random.randint(2, 5)

    elif rank == 3:
        # 높은 수치
        s1 = random.choice(["max_hp", "max_mental"])
        stats[s1] = random.randint(40, 80)
        
        # 20% 확률로 '방어율(%)' 스탯 부여, 아니면 공격/방어
        if random.random() < 0.2:
            stats["defense_rate"] = random.randint(3, 8) # 3~8% 데미지 감소
        else:
            s2 = random.choice(["attack", "defense"])
            stats[s2] = random.randint(4, 9)
            
    return stats

def apply_upgrade_bonus(stats):
    """
    강화 시 스탯 증가 로직 (리롤 시 레벨 보정에 사용)
    """
    # 존재하는 스탯 중 하나를 강화
    valid_keys = [k for k, v in stats.items() if v > 0 and k != "defense_rate"]
    if not valid_keys: 
        valid_keys = ["max_hp"] # 예외 처리
        
    # [수정] 강화 시 2개의 스탯이 동시에 상승하도록 변경
    for _ in range(2):
        target = random.choice(valid_keys)
        
        if target in ["max_hp", "max_mental"]:
            stats[target] += random.randint(20, 40)
        else:
            stats[target] += random.randint(5, 9)
        
    return stats

def _make_description(stats, special=None):
    """스탯과 특수 효과를 기반으로 설명 텍스트 생성"""
    desc_parts = []
    
    # [특수 효과 설명]
    effect_desc = {
        "reuse_last_dice": "🎲 **[꼼꼼한]** 상대가 공격하지 않을 때, 이전 주사위 재사용",
        "fierce_attack": "🔥 **[맹렬한]** 2턴마다 공격 시, 공격력만큼 추가 피해",
        "sturdy_defense": "🛡️ **[견고한]** 2턴마다 방어 시, 방어값의 2/3만큼 체력 회복",
        "reflection": "💢 **[앙심]** 받는 피해의 3/4을 상대에게 반사 (정신력 소모 없음)",
        "escalation": "⚡ **[고조]** 합 승리 시 일정 확률로 다음 주사위 위력 폭주 (+1~30)",
        "immortality": "👼 **[불멸]** 전투 불능 시 1회 부활 (HP 100% 회복)",
        "youngsan_gold": "💰 **[황금]** '돈을 사용하는' 기술 카드의 소모 비용 50% 감소",
        "luude_imprint": "👁️ **[악몽]** 주사위 파괴 시, 파괴한 개수당 10% 정신력 회복 또는 적에게 피해"
    }
    
    if special in effect_desc:
        desc_parts.append(effect_desc[special])
    
    # [스탯 설명]
    stat_map = {
        "max_hp": "체력", "max_mental": "정신력", 
        "attack": "공격력", "defense": "방어력", 
        "defense_rate": "피해감소"
    }
    
    stat_texts = []
    for k, v in stats.items():
        if v > 0:
            unit = "%" if k == "defense_rate" else ""
            stat_texts.append(f"{stat_map[k]} +{v}{unit}")
            
    if stat_texts:
        desc_parts.append(" | ".join(stat_texts))

    return "\n".join(desc_parts)

def generate_artifact(rank=None):
    """
    새로운 아티팩트를 생성합니다.
    """
    if rank is None:
        roll = random.randint(1, 100)
        if roll <= 60: rank = 1
        elif roll <= 85: rank = 2
        else: rank = 3

    # 이름 생성
    pool = ARTIFACT_TYPES
    if rank == 3: pool += ARTIFACT_TYPES_3STAR
    
    base_name = random.choice(pool)
    prefix = random.choice(PREFIXES[rank])
    # 3성은 황금의(히든) 제외하고 생성
    if rank == 3 and prefix == "황금의": prefix = "고조된" 
    
    full_name = f"{'⭐'*rank} {prefix} {base_name}"

    # 특수 효과 결정 (3성만)
    special = None
    if rank == 3:
        special = SPECIAL_EFFECTS.get(prefix)

    # 스탯 생성
    stats = _generate_stats(rank)
    description = _make_description(stats, special)

    return {
        "id": str(uuid.uuid4()),
        "name": full_name,
        "rank": rank,
        "grade": rank, 
        "level": 0,    
        "prefix": prefix,
        "stats": stats,
        "special": special,
        "description": description
    }

def reroll_artifact_stats(artifact_data):
    """
    아티팩트의 옵션을 재설정합니다 (리롤).
    - 등급(Rank) 유지
    - 현재 강화 레벨(Level)만큼 스탯 재성장 적용
    - 접두사(Prefix)는 변경되지 않음 (수식어 변경 기능은 별도)
    - 따라서 특수 능력(Special)도 유지됨
    """
    # rank와 grade 키 모두 대응하도록 수정
    rank = artifact_data.get("rank") or artifact_data.get("grade") or 1
    level = artifact_data.get("level", 0)
    
    # 1. 베이스 스탯 재설정
    new_stats = _generate_stats(rank)
    
    # 2. 기존 레벨만큼 강화 재적용
    for _ in range(level):
        apply_upgrade_bonus(new_stats)
        
    artifact_data["stats"] = new_stats
    
    # 설명 업데이트 (특수 능력은 그대로)
    special = artifact_data.get("special")
    artifact_data["description"] = _make_description(new_stats, special)
    
    return artifact_data