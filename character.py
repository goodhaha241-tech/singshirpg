# character.py
import json

# ==================================================================================
# 1. 기본 플레이어 데이터 템플릿
# ==================================================================================
DEFAULT_PLAYER_DATA = {
    "name": "플레이어",
    # [수정] 레벨(level)과 경험치(xp) 제거됨
    
    # [체력/정신력]
    "hp": 170,          # 기본 최대 체력 (Save Key: hp) - 베이스 스탯
    "current_hp": 170,
    "max_hp": 170,      # 실제 최대 체력 (인메모리 계산용, 저장 안 함)
    
    # [수정] 키 이름을 저장 로직과 통일 (mental -> max_mental)
    "max_mental": 90,   # 기본 최대 정신력 (Save Key: max_mental) - 베이스 스탯
    "current_mental": 90,
    "max_mental_real": 90, # 실제 최대 정신력 (인메모리 계산용)
    
    # [전투 스탯]
    "attack": 5,
    "defense": 3,
    "defense_rate": 0,  # 받는 피해 % 감소 (3성 아티팩트/각인 효과)
    "speed": 10,        # 턴 순서 (확장 대비)
    
    # [장비/덱]
    "card_slots": 4,
    "equipped_cards": ["기본공격", "기본방어", "기본반격"],
    "equipped_artifact": None,          # 일반 아티팩트
    "equipped_engraved_artifact": None, # [신규] 각인 아티팩트
    
    # [상태]
    "status_effects": {"bleed": 0},
    "is_down": False,    # 전투 불능 상태 여부
    "is_recruited": False
}

# ==================================================================================
# 2. 캐릭터 클래스 정의
# ==================================================================================
class Character:
    def __init__(self, name, hp, max_hp, mental, max_mental, attack, defense,
                 defense_rate=0, speed=10, card_slots=4,
                 equipped_cards=None, equipped_artifact=None, equipped_engraved_artifact=None,
                 current_hp=None, current_mental=None, status_effects=None, is_recruited=False, is_down=False):
        
        self.name = name
        # [수정] 레벨/경험치 초기화 로직 삭제
        
        # [체력 설정]
        self.base_max_hp = hp  # 저장된 '기본' 최대치 (베이스)
        self.max_hp = max_hp   # 버프 포함 '현재' 최대치 (전투 시 변동)
        self.current_hp = current_hp if current_hp is not None else self.max_hp
        
        # [정신력 설정]
        self.base_max_mental = mental # 저장된 '기본' 최대치
        self.max_mental = max_mental  # 버프 포함 '현재' 최대치
        self.current_mental = current_mental if current_mental is not None else self.max_mental
        
        # [기본 스탯]
        self.attack = attack
        self.defense = defense
        self.defense_rate = defense_rate
        self.speed = speed
        
        # [장비 및 카드]
        self.card_slots = card_slots
        self.equipped_cards = equipped_cards if equipped_cards else ["기본공격", "기본방어", "기본반격"]
        self.equipped_artifact = equipped_artifact
        self.equipped_engraved_artifact = equipped_engraved_artifact
        
        # [상태 정보]
        self.status_effects = status_effects if status_effects else {"bleed": 0}
        self.is_recruited = is_recruited
        self.is_down = is_down
        
        # [전투 로직용 플래그] (저장되지 않음)
        self.has_artifact_buff = False # 전투 진입 시 스탯 중복 적용 방지
        self.runtime_cooldowns = {}    # 아티팩트 특수효과 쿨타임 관리

    @classmethod
    def from_dict(cls, data):
        """딕셔너리 데이터로부터 Character 객체 생성"""
        
        # 1. 체력 데이터 로드
        base_hp = data.get("hp", 170)
        current_hp = data.get("current_hp")
        
        # 2. 정신력 데이터 로드 (구버전 호환성 체크)
        # 구버전은 'mental' 키를 썼고, 신버전은 'max_mental' 키를 사용함
        if "max_mental" in data:
            base_mental = data["max_mental"]
        elif "mental" in data:
            base_mental = data["mental"]
        else:
            base_mental = 90
            
        current_mental = data.get("current_mental")

        # 3. 객체 생성 및 반환
        return cls(
            name=data.get("name", "Unknown"),
            # [수정] level, xp 전달 삭제
            
            hp=base_hp,          # base_max_hp로 할당
            max_hp=base_hp,      # 초기화 시점에는 베이스와 동일
            current_hp=current_hp, 
            
            mental=base_mental,     # base_max_mental로 할당
            max_mental=base_mental, # 초기화 시점에는 베이스와 동일
            current_mental=current_mental,
            
            attack=data.get("attack", 5),
            defense=data.get("defense", 3),
            defense_rate=data.get("defense_rate", 0),
            speed=data.get("speed", 10),
            card_slots=data.get("card_slots", 4),
            
            equipped_cards=data.get("equipped_cards", []),
            equipped_artifact=data.get("equipped_artifact"),
            equipped_engraved_artifact=data.get("equipped_engraved_artifact"),
            
            status_effects=data.get("status_effects", {}).copy(),
            is_recruited=data.get("is_recruited", False),
            is_down=data.get("is_down", False)
        )

    def to_dict(self):
        """Character 객체를 저장 가능한 딕셔너리로 변환"""
        # [수정] 레벨, 경험치 저장 로직 삭제됨
        return {
            "name": self.name,
            
            "hp": self.base_max_hp,       # 기본 스탯 저장 (아티팩트 버프 제외)
            "current_hp": self.current_hp,
            
            "max_mental": self.base_max_mental, # 기본 스탯 저장
            "current_mental": self.current_mental,
            
            "attack": self.attack,
            "defense": self.defense,
            "defense_rate": self.defense_rate,
            "speed": self.speed,
            "card_slots": self.card_slots,
            
            "equipped_cards": self.equipped_cards,
            "equipped_artifact": self.equipped_artifact,
            "equipped_engraved_artifact": self.equipped_engraved_artifact,
            
            "status_effects": self.status_effects,
            "is_recruited": self.is_recruited,
            "is_down": self.is_down
        }

    def apply_battle_start_buffs(self):
        """
        전투 시작 시 아티팩트(일반+각인) 스탯을 적용합니다.
        BattleView에서 호출하여 사용합니다.
        """
        # [중요 수정] 안전장치 추가: 이미 버프가 있다면 먼저 제거 후 다시 적용
        # (전투 중 튕겨서 버프가 해제되지 않은 상태로 재시작하는 경우 방지)
        if self.has_artifact_buff: 
            self.remove_battle_buffs()

        # 1. 일반 아티팩트
        if self.equipped_artifact and isinstance(self.equipped_artifact, dict):
            stats = self.equipped_artifact.get("stats", {})
            self._add_stats(stats)

        # 2. 각인 아티팩트 (중복 적용 가능)
        if self.equipped_engraved_artifact and isinstance(self.equipped_engraved_artifact, dict):
            stats = self.equipped_engraved_artifact.get("stats", {})
            self._add_stats(stats)

        self.has_artifact_buff = True

    def remove_battle_buffs(self):
        """전투 종료 후 아티팩트 스탯을 제거합니다."""
        if not self.has_artifact_buff: return

        if self.equipped_artifact and isinstance(self.equipped_artifact, dict):
            stats = self.equipped_artifact.get("stats", {})
            self._remove_stats(stats)

        if self.equipped_engraved_artifact and isinstance(self.equipped_engraved_artifact, dict):
            stats = self.equipped_engraved_artifact.get("stats", {})
            self._remove_stats(stats)

        self.has_artifact_buff = False

    def _add_stats(self, stats):
        """스탯 적용 내부 함수"""
        hp_bonus = stats.get("max_hp", 0)
        mental_bonus = stats.get("max_mental", 0)

        self.max_hp += hp_bonus
        
        self.max_mental += mental_bonus
        
        self.attack += stats.get("attack", 0)
        self.defense += stats.get("defense", 0)
        self.defense_rate += stats.get("defense_rate", 0)

    def _remove_stats(self, stats):
        """스탯 제거 내부 함수"""
        hp_bonus = stats.get("max_hp", 0)
        mental_bonus = stats.get("max_mental", 0)

        self.max_hp -= hp_bonus
        # 버프 해제 시 현재 체력이 최대 체력을 넘지 않도록 조정
        if self.current_hp > self.max_hp:
            self.current_hp = self.max_hp
        
        self.max_mental -= mental_bonus
        if self.current_mental > self.max_mental:
            self.current_mental = self.max_mental
        
        self.attack -= stats.get("attack", 0)
        self.defense -= stats.get("defense", 0)
        self.defense_rate -= stats.get("defense_rate", 0)

    def is_alive(self):
        return self.current_hp > 0