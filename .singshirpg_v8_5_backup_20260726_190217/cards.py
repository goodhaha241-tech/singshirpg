# cards.py
import random

EFFECT_DESCRIPTIONS = {
    "bleed_synergy": "대상의 출혈만큼 위력 증가",
    "destroy_next_on_hit": "적중 시 다음 상대 주사위 파괴",
    "lock_others": "이후 상대 주사위를 잠금",
    "absorb_hp": "준 피해 일부를 체력으로 흡수",
    "time_accel": "시간 가속 효과 발동",
    "morning_glory": "특수 조건에서 위력 강화",
    "self_major": "자신에게 메이저 부여: 주는 피해와 받는 피해 25% 증가",
    "self_minor": "자신에게 마이너 부여: 주는 피해와 받는 피해 25% 감소",
}


def describe_dice_effect(effect):
    """카드의 내부 효과 키를 이용자용 한국어 설명으로 변환한다."""
    if not effect:
        return ""
    if effect in EFFECT_DESCRIPTIONS:
        return EFFECT_DESCRIPTIONS[effect]
    parts = effect.split("_")
    if effect.startswith("bleed_") and parts[1].isdigit():
        target = "자신에게" if "self" in parts else "상대에게"
        condition = " (승리 시)" if "on" in parts and "win" in parts else ""
        return f"{target} 출혈 {parts[1]} 부여{condition}"
    if effect.startswith("paralysis_") and parts[1].isdigit():
        target = "자신에게" if "self" in parts else "상대에게"
        condition = " (승리 시)" if "on" in parts and "win" in parts else ""
        return f"{target} 마비 {parts[1]} 부여{condition}"
    if effect.startswith("stun_") and parts[1].isdigit():
        chance = ""
        if "prob" in parts:
            chance = f" ({parts[parts.index('prob') + 1]}% 확률)"
        return f"상대에게 기절 {parts[1]} 부여{chance}"
    if effect.startswith("dmg_by_para_"):
        return f"대상 마비 1당 고정 피해 {parts[-1]}"
    if effect.startswith("atk_boost_para_"):
        return f"대상 마비 1당 주사위 위력 +{parts[-1]}"
    if effect.startswith("self_dmg_by_para_"):
        return f"자신의 마비 1당 자해 피해 {parts[-1]}"
    if effect.startswith("self_dmg_") and len(parts) >= 4:
        return f"자신에게 {parts[2]}~{parts[3]} 피해"
    return effect


class Dice:
    """개별 행동(주사위)을 정의하는 클래스"""
    def __init__(self, action_type, d_min, d_max, effect=None):
        self.action_type = action_type  
        self.d_min = d_min
        self.d_max = d_max
        self.effect = effect # 특수 효과 (bleed_X_on_win, destroy_next_on_hit 등)

    def roll(self, attack_stat=0, defense_stat=0, current_mental=0):
        f_min, f_max = self.d_min, self.d_max
        
        if self.action_type == "attack":
            f_max += attack_stat
        elif self.action_type == "defense":
            f_max += defense_stat
        elif self.action_type == "counter":
            f_min += defense_stat
            f_max += attack_stat
        elif self.action_type in ["heal", "heal_hp"]:
            f_min += defense_stat
        elif self.action_type == "mental_heal":
            f_min += defense_stat

        f_min = min(f_min, self.d_max)
        f_max = max(f_min, f_max)

        return self.action_type, random.randint(f_min, f_max)

class SkillCard:
    def __init__(self, name, dice_list, is_aoe=False):
        self.name = name
        self.dice_list = dice_list
        self.is_aoe = is_aoe

    @property
    def description(self):
        desc_parts = []
        effect_lines = []
        for d in self.dice_list:
            emoji = {"attack": "⚔️", "defense": "🛡️", "counter": "⚡", "heal": "💚", "mental_heal": "🔮"}.get(d.action_type, "🎲")
            effect_desc = describe_dice_effect(d.effect)
            marker = " ✦" if effect_desc else ""
            desc_parts.append(f"{emoji}({d.d_min}~{d.d_max}){marker}")
            if effect_desc and effect_desc not in effect_lines:
                effect_lines.append(effect_desc)
        desc = " ➔ ".join(desc_parts)
        if self.is_aoe: desc = "📢 [광역] " + desc
        if effect_lines:
            desc += "\n" + "\n".join(f"• {line}" for line in effect_lines)
        return desc

    def use_card(self, attack_stat=0, defense_stat=0, current_mental=0, **kwargs):
        results = []
        for dice in self.dice_list:
            a_type, val = dice.roll(attack_stat, defense_stat, current_mental)
            results.append({"type": a_type, "value": val, "effect": dice.effect})
        return results

class GoldMechanicCard(SkillCard):
    def __init__(self, name, dice_configs):
        self.name = name
        self.dice_configs = dice_configs
        self.dice_list = [Dice(t, mn, mx) for t, mn, mx in dice_configs]

    @property
    def description(self):
        return "💰 100원당 최종 위력 +1 (최대 +7)"

    def use_card(self, attack_stat=0, defense_stat=0, current_mental=0, **kwargs):
        user_data = kwargs.get("user_data")
        character = kwargs.get("character")
        bonus = 0
        
        if user_data:
            current_money = user_data.get("money", 0)
            
            # [황금] 각인 효과: 비용 50% 감소 & 한도 7000으로 증가
            limit = 700
            cost_factor = 1.0
            is_youngsan = False
            
            if character:
                eng = getattr(character, "equipped_engraved_artifact", None)
                if eng and isinstance(eng, dict) and eng.get("special") == "youngsan_gold":
                    cost_factor = 0.5
                    limit = 7000
                    is_youngsan = True
            
            # 소지 금액으로 지불 가능한 최대 spend 계산
            affordable_spend = int(current_money / cost_factor)
            spend = min(affordable_spend, limit)
            spend = (spend // 100) * 100 
            
            real_cost = int(spend * cost_factor)
            
            if spend > 0:
                user_data["money"] -= real_cost
                bonus = spend // 100 
                
                # [황금] 누적 사용 금액 체크 (7만원마다 효과 발동)
                if is_youngsan:
                    acc = character.runtime_cooldowns.get("youngsan_accumulated", 0)
                    acc += real_cost
                    if acc >= 70000:
                        acc -= 70000
                        character.runtime_cooldowns["youngsan_nuke"] = True
                    character.runtime_cooldowns["youngsan_accumulated"] = acc
        
        results = []
        for (dtype, dmin, dmax) in self.dice_configs:
            f_min, f_max = dmin, dmax
            if dtype == "attack": f_max += attack_stat
            elif dtype == "defense": f_max += defense_stat
            elif dtype == "counter": f_min += defense_stat; f_max += attack_stat
            elif dtype == "heal": f_min += defense_stat
            elif dtype == "mental_heal": f_min += defense_stat
            
            f_min = min(f_min, f_max)
            val = random.randint(f_min, f_max)
            val += bonus
            results.append({"type": dtype, "value": val, "effect": None})
        return results

class InFightCard(SkillCard):
    def __init__(self, name):
        self.name = name
        self.dice_list = [
            Dice("defense", 1, 1),
            Dice("defense", 1, 1),
            Dice("attack", 20, 20)
        ]

    @property
    def description(self):
        return "🛡️(1) ➔ 🛡️(1) ➔ ⚔️(저번턴피해+20)"

    def use_card(self, attack_stat=0, defense_stat=0, current_mental=0, **kwargs):
        damage_taken = kwargs.get("damage_taken", 0)
        atk_val = damage_taken + 20 + attack_stat
        return [
            {"type": "defense", "value": 1, "effect": None},
            {"type": "defense", "value": 1, "effect": None},
            {"type": "attack", "value": atk_val, "effect": None}
        ]

class LuudeCard(SkillCard):
    def __init__(self, name):
        self.name = name
        if name == "사우전드웨이브":
            self.dice_list = [
                Dice("attack", 1, 13, effect="destroy_next_on_hit"), 
                Dice("attack", 3, 10), 
                Dice("heal", 20, 30)
            ]
        elif name == "잠금":
            self.dice_list = [Dice("mental_heal", 10, 10, effect="lock_others")]
        else:
            self.dice_list = []

    @property
    def description(self):
        if self.name == "사우전드웨이브":
            return "⚔️(1~13, 적중시 파괴) ➔ ⚔️(3~10) ➔ 💚(20~30)"
        elif self.name == "잠금":
            return "🔮(10, 적 후속 주사위 전체 파괴)"
        return super().description

    def use_card(self, attack_stat=0, defense_stat=0, current_mental=0, **kwargs):
        return super().use_card(attack_stat, defense_stat, current_mental, **kwargs)

class KaianCard(SkillCard):
    def __init__(self, name):
        self.name = name
        if name == "시간술식:기본형":
            self.dice_list = [
                Dice("defense", 10, 17),
                Dice("counter", 10, 13, effect="time_accel"),
                Dice("defense", 7, 13)
            ]
        elif name == "시간술식:1장":
            self.dice_list = [
                Dice("heal", 20, 30),
                Dice("heal", 20, 30),
                Dice("counter", 7, 10, effect="time_accel")
            ]
        elif name == "시간술식:1장 응용":
            self.dice_list = [
                Dice("counter", 7, 10, effect="time_accel"),
                Dice("counter", 7, 10, effect="time_accel"),
                Dice("heal", 20, 30)
            ]
        else:
            self.dice_list = []

    @property
    def description(self):
        base_desc = super().description
        if "시간술식" in self.name:
            base_desc += "\n⌛ [특수] 합 승리 시 다음 턴 모든값 +6"
        return base_desc

class SenshoCard(SkillCard):
    def __init__(self, name):
        self.name = name
        if name == "파멸의 소원":
            self.dice_list = [Dice("attack", 10, 17), Dice("attack", 10, 13)]
        else:
            self.dice_list = []

    @property
    def description(self):
        base = super().description
        return f"{base}\n[특수] 정신력 50% 이상일 때 3 소모하여 위력 +6"

    def use_card(self, attack_stat=0, defense_stat=0, current_mental=0, **kwargs):
        char = kwargs.get("character")
        bonus = 0
        if char and self.name == "파멸의 소원":
            if char.current_mental >= (char.max_mental / 2):
                char.current_mental = max(0, char.current_mental - 3)
                bonus = 6
        
        results = []
        for dice in self.dice_list:
            a_type, val = dice.roll(attack_stat, defense_stat, current_mental)
            val += bonus
            results.append({"type": a_type, "value": val, "effect": dice.effect})
        return results

class MorningGloryCard(SkillCard):
    def __init__(self, name):
        self.name = name
        self.dice_list = [
            Dice("attack", 1, 4, effect="morning_glory"),
            Dice("defense", 10, 13)
        ]

    @property
    def description(self):
        return "⚔️(1~4, 4가 나오면 +70) ➔ 🛡️(10~13)"

    def use_card(self, attack_stat=0, defense_stat=0, current_mental=0, **kwargs):
        results = []
        for dice in self.dice_list:
            if dice.effect == "morning_glory":
                # 능력치 미적용 롤
                val = random.randint(dice.d_min, dice.d_max)
                if val == 4:
                    val += 70
                results.append({"type": dice.action_type, "value": val, "effect": "morning_glory"})
            else:
                a_type, val = dice.roll(attack_stat, defense_stat, current_mental)
                results.append({"type": a_type, "value": val, "effect": dice.effect})
        return results


# --- 기술 카드 데이터베이스 ---
SKILL_CARDS = {
    # [기본 카드]
    "기본공격": SkillCard("기본공격", [Dice("attack", 5, 7)]),
    "기본방어": SkillCard("기본방어", [Dice("defense", 3, 5)]),
    "기본회복": SkillCard("기본회복", [Dice("heal", 15, 20)]),
    "기본반격": SkillCard("기본반격", [Dice("counter", 4, 6)]),
    "메이저 체인지": SkillCard("메이저 체인지", [Dice("defense", 1, 5, effect="self_major")]),
    "마이너 체인지": SkillCard("마이너 체인지", [Dice("defense", 1, 5, effect="self_minor")]),

    
    "복합공격": SkillCard("복합공격", [Dice("attack", 3, 5), Dice("attack", 2, 4)]),
    "복합반격": SkillCard("복합반격", [Dice("defense", 3, 5), Dice("counter", 3, 5)]),
    "숨고르기": SkillCard("숨고르기", [Dice("attack", 5, 8), Dice("heal", 10, 15)]),
    "기본집중": SkillCard("기본집중", [Dice("mental_heal", 5, 9)]),
    "깊은집중": SkillCard("깊은집중", [Dice("mental_heal", 6, 9), Dice("heal", 10, 14)]),
    "강한참격": SkillCard("강한참격", [Dice("attack", 7, 10), Dice("attack", 1, 6)]),
    "회전베기": SkillCard("회전베기", [Dice("attack", 6, 10), Dice("counter", 5, 9)]),
    "회피기동": SkillCard("회피기동", [Dice("defense", 7, 10), Dice("counter", 5, 8), Dice("defense", 7, 10)]),
    "육참골단": SkillCard("육참골단", [Dice("attack", 1, 3), Dice("defense", 1, 4), Dice("attack", 10, 12)]),
    "집중반격": SkillCard("집중반격", [Dice("counter", 5, 9), Dice("counter", 5, 9), Dice("mental_heal", 7, 9)]),
    "방어와 수복": SkillCard("방어와 수복", [Dice("defense", 5, 9), Dice("defense", 10, 12), Dice("heal", 12, 15)]),
    "방어와 침착": SkillCard("방어와 침착", [Dice("defense", 5, 9), Dice("defense", 10, 12), Dice("mental_heal", 10, 12)]),

    # [이루지 못한 꿈들의 별 신규]
    "자각몽": SkillCard("자각몽", [Dice("attack", 10, 15), Dice("defense", 7, 10)]),
    "꿈꾸기": SkillCard("꿈꾸기", [Dice("heal", 20, 30), Dice("attack", 13, 18), Dice("mental_heal", 1, 10)]),
    "중급회복": SkillCard("중급회복", [Dice("heal", 15, 20), Dice("heal", 8, 10), Dice("mental_heal", 2, 10)]),
    
    # [생명의 숲 신규] - 출혈 효과 적용
    "더러운 공격": SkillCard("더러운 공격", [Dice("attack", 1, 3, effect="bleed_2_on_win"), Dice("attack", 1, 3, effect="bleed_2_on_win"), Dice("defense", 10, 13)]),
    "상처 벌리기": SkillCard("상처 벌리기", [Dice("attack", 2, 4, effect="bleed_synergy"), Dice("attack", 1, 2, effect="bleed_3_on_win")]),
    "불안정한 재생": SkillCard("불안정한 재생", [Dice("heal", 50, 60, effect="bleed_1_self"), Dice("heal", 50, 60, effect="bleed_2_self")]),
    "연속내치기": SkillCard("연속내치기", [Dice("counter", 7, 9, effect="bleed_3_on_win"), Dice("counter", 7, 9, effect="bleed_3_on_win"), Dice("defense", 7, 9, effect="bleed_2_on_win")]),

    # [아르카워드 제도 신규]
    "폭풍": SkillCard("폭풍", [Dice("attack", 10, 12), Dice("attack", 7, 12), Dice("attack", 3, 10)]),
    "사이클론": SkillCard("사이클론", [Dice("counter", 10, 12), Dice("defense", 3, 10), Dice("counter", 10, 12)]),
    "산들바람": SkillCard("산들바람", [Dice("heal", 30, 35), Dice("mental_heal", 30, 35)]),

    # [신규 캐릭터 전용]
    "치유의 소원": SkillCard("치유의 소원", [Dice("defense", 7, 10), Dice("heal", 20, 25)]),
    "별의 은총": SkillCard("별의 은총", [Dice("attack", 7, 10), Dice("defense", 7, 14), Dice("heal", 20, 25)]),
    "쪼아대기": SkillCard("쪼아대기", [Dice("attack", 6, 13, effect="bleed_3_on_win"), Dice("attack", 10, 13)]),
    "밀키워킹": SkillCard("밀키워킹", [Dice("defense", 10, 16), Dice("heal", 20, 25), Dice("counter", 8, 13)]),

    # [공간의 신전 신규]
    "순간이동": SkillCard("순간이동", [
        Dice("defense", 10, 12, effect="paralysis_1"), 
        Dice("heal", 10, 20), 
        Dice("defense", 10, 12, effect="paralysis_1")
    ]),
    "차원베기": SkillCard("차원베기", [
        Dice("attack", 7, 10, effect="paralysis_3_on_win"), 
        Dice("attack", 7, 8, effect="paralysis_3_on_win"), 
        Dice("defense", 8, 15, effect="dmg_by_para_15")
    ]),
    "방울연발": SkillCard("방울연발", [
        Dice("counter", 10, 12, effect="paralysis_4_on_win"), 
        Dice("counter", 13, 15, effect="paralysis_3_on_win"), 
        Dice("mental_heal", 20, 30, effect="dmg_by_para_15")
    ]),
    "방울방울": SkillCard("방울방울", [
        Dice("heal", 30, 50, effect="paralysis_1_self"), 
        Dice("heal", 30, 50, effect="paralysis_2_self"), 
        Dice("heal", 10, 12, effect="self_dmg_by_para_30")
    ]),
    
    # [루트렌 뉴마 전용]
    "변수제거": SkillCard("변수제거", [Dice("attack", 5, 8), Dice("defense", 3, 4)]),
    "관측과 분석": SkillCard("관측과 분석", [Dice("heal", 20, 30), Dice("defense", 5, 7), Dice("mental_heal", 7, 9)]),

    # [미카엘 전용]
    "이스카리옷 유다의 입맞춤": SkillCard("이스카리옷 유다의 입맞춤", [Dice("heal", 10, 25), Dice("mental_heal", 1, 5)]),
    "성 미카엘, 용을 죽이다.": SkillCard("성 미카엘, 용을 죽이다.", [
        # 5분의 1 확률(20%)로 1턴간 무력화(stun)
        Dice("attack", 4, 7, effect="stun_1_prob_20"), 
        Dice("defense", 1, 2)
    ]),


# --- 로버드 전용 카드 ---
    "얼어붙는시선": SkillCard("얼어붙는시선", [
        Dice("attack", 1, 3),
        # type="none"은 합을 진행하지 않고 효과만 발동합니다.
        # effect="self_dmg_1_10": 1~10 사이의 자해 데미지
        Dice("none", 1, 10, effect="self_dmg_1_10"), 
        # effect="paralysis_5_prob_25": 25% 확률로 마비 5 부여
        Dice("attack", 10, 15, effect="paralysis_5_prob_25") 
    ]),
    "날개쉬기": SkillCard("날개쉬기", [
        Dice("heal", 20, 30),
        Dice("defense", 10, 15),
        Dice("mental_heal", 10, 30)
    ]),

    # --- 셰리안 전용 카드 ---
    "데이브레이크": SkillCard("데이브레이크", [
        Dice("heal", 12, 15),
        Dice("heal", 3, 5)
    ]),
    "퀀티제이션": SkillCard("퀀티제이션", [
        Dice("attack", 13, 17),
        Dice("defense", 3, 7)
    ]),

    # [몬스터 전용]
    "연속할퀴기": SkillCard("연속할퀴기", [Dice("attack", 4, 6), Dice("attack", 4, 6), Dice("attack", 4, 6)]),
    "작은원망": SkillCard("작은원망", [Dice("attack", 6, 10), Dice("attack", 2, 4)]),
    "섬세한 방어": SkillCard("섬세한 방어", [Dice("defense", 8, 12)]),
    "재생": SkillCard("재생", [Dice("heal", 3, 10)]),
    "겁나는얼굴": SkillCard("겁나는얼굴", [Dice("attack", 5, 8), Dice("attack", 5, 8)]),
    "비축분 던지기": SkillCard("비축분 던지기", [Dice("defense", 4, 8), Dice("counter", 3, 6)]),
    "먼지쓸기": SkillCard("먼지쓸기", [Dice("attack", 3, 7), Dice("defense", 3, 5)]),
    "기망": SkillCard("기망", [Dice("attack", 5, 10), Dice("heal", 10, 15)]),
    "책임": SkillCard("책임", [Dice("attack", 10, 15)]),
    "우주": SkillCard("우주", [Dice("heal", 6, 10), Dice("defense", 5, 10)]),
    "소명": SkillCard("소명", [Dice("attack", 1, 8), Dice("attack", 1, 8), Dice("counter", 1, 10)]),
    "후회": SkillCard("후회", [Dice("attack", 25, 40), Dice("heal", 10, 15)]),
    "떠올리기": SkillCard("떠올리기", [Dice("defense", 30, 45), Dice("attack", 10, 14)]),
    "트라우마 자극": SkillCard("트라우마 자극", [Dice("attack", 10, 14), Dice("attack", 12, 15), Dice("defense", 13, 20)]),
    "식탐": SkillCard("식탐", [Dice("attack", 1, 3), Dice("attack", 2, 4), Dice("attack", 10, 20, effect="absorb_hp")]),
    "괴상한바람": SkillCard("괴상한바람", [Dice("attack", 1, 40), Dice("attack", 1, 40)]),
    "아집": SkillCard("아집", [Dice("counter", 10, 13), Dice("counter", 10, 13)]),
    "찌릿찌릿": SkillCard("찌릿찌릿", [
        Dice("defense", 1, 1, effect="paralysis_2"), 
        Dice("defense", 1, 1, effect="paralysis_3"), 
        Dice("attack", 1, 1, effect="atk_boost_para_15")
    ])
}

# ==================================================================================
# [신규] 던전 보스 전용 스킬 (SKILL_CARDS에 병합)
# ==================================================================================
BOSS_CARDS = {
    # 1단계 보스용
    "강철타격": SkillCard("강철타격", [Dice("attack", 10, 20), Dice("attack", 10, 20)]),
    "광란": SkillCard("광란", [Dice("attack", 5, 10), Dice("attack", 5, 10), Dice("attack", 5, 10)]),
    "단단한껍질": SkillCard("단단한껍질", [Dice("defense", 15, 25), Dice("counter", 5, 15)]),
    "아쿠아건": SkillCard("아쿠아건", [Dice("attack", 12, 18), Dice("attack", 8, 12)]), # 폭풍의 세이렌용
    "만년설창": SkillCard("만년설창", [Dice("attack", 15, 25), Dice("defense", 5, 10)]), # 만년설의 정령용
    
    # 2단계 보스용
    "심연의주시": SkillCard("심연의주시", [Dice("mental_heal", 1, 1), Dice("attack", 15, 25)]), # mental_attack 대체
    "대지진": SkillCard("대지진", [Dice("attack", 20, 40, effect="stun_1")]),
    "시간역행": SkillCard("시간역행", [Dice("heal", 20, 40), Dice("defense", 20, 30)]),
    "맹독포자": SkillCard("맹독포자", [Dice("attack", 10, 15, effect="bleed_5"), Dice("attack", 10, 15, effect="bleed_5")]),

    # 3단계 보스용 (필살기급)
    "멸망의노래": SkillCard("멸망의노래", [Dice("attack", 30, 50), Dice("attack", 10, 20)]), # mental_attack 대체
    "공간절단": SkillCard("공간절단", [Dice("attack", 50, 80)]),
    "절대방어": SkillCard("절대방어", [Dice("defense", 50, 100), Dice("heal", 20, 50)]),
    "영혼수확": SkillCard("영혼수확", [Dice("attack", 30, 50, effect="absorb_hp")]), 
    "신성한심판": SkillCard("신성한심판", [Dice("attack", 40, 60), Dice("attack", 40, 60)]),

    # [레이드 보스 전용 - 광역]
    "대지진(광역)": SkillCard("대지진(광역)", [Dice("attack", 15, 25, effect="stun_1_prob_50")], is_aoe=True),
    "포효(광역)": SkillCard("포효(광역)", [Dice("mental_heal", 1, 1), Dice("attack", 10, 15)], is_aoe=True), # mental_heal 1은 더미(합 패배 유도용)
    "화염숨결(광역)": SkillCard("화염숨결(광역)", [Dice("attack", 20, 30, effect="bleed_5")], is_aoe=True),
}

def get_card(name):
    if name == "전부매입": 
        return GoldMechanicCard("전부매입", [("attack", 3, 7), ("defense", 3, 7)])
    elif name == "금융치료": 
        return GoldMechanicCard("금융치료", [("heal", 10, 17), ("heal", 3, 5)])
    elif name == "인파이트":
        return InFightCard("인파이트")
    elif name in ["사우전드웨이브", "잠금"]:
        return LuudeCard(name)
    elif name.startswith("시간술식"):
        return KaianCard(name)
    elif name == "파멸의 소원": 
        return SenshoCard(name)
    elif name == "모닝 글로리":
        return MorningGloryCard(name)
    
    card = SKILL_CARDS.get(name)
    if not card:
        card = BOSS_CARDS.get(name)
    return card

CARD_PRICES = {
    "기본공격": 700, "기본방어": 700, "기본회복": 1000, "기본반격": 1000,
    "메이저 체인지": 1800, "마이너 체인지": 1800,
    "복합공격": 1600, "복합반격": 1600, "숨고르기": 2000,
    "기본집중": 1600, "깊은집중": 2000, "강한참격": 2500, "회전베기": 2500,
    "회피기동": 2700, "육참골단": 2700, "집중반격": 2000,
    "자각몽": 3500, "꿈꾸기": 4500, "중급회복": 3500, "인파이트": 5000,
    "더러운 공격": 4000, "상처 벌리기": 4500, "불안정한 재생": 4000, "연속내치기": 5000,
    "폭풍": 5500, "사이클론": 5000, "산들바람": 4500, "모닝 글로리": 8000, "순간이동": 5500, 
    "차원베기": 5700, "방울연발": 5700, "방울방울": 5500, 
}
