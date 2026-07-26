# completion-v6-progression
# rollback-guard-appraisal-gems-v8
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import discord

from balance_config_v6 import KOREA_TIMEZONE
from life_system import PURE_HOPE_ITEM, ensure_life_data


def korea_today():
    return datetime.now(ZoneInfo(KOREA_TIMEZONE)).date()


def current_week_key():
    y, w, _ = korea_today().isocalendar()
    return f"{y}-W{w:02d}"


def ensure_progression(user_data: dict[str, Any]) -> dict[str, Any]:
    life = ensure_life_data(user_data)
    p = life.setdefault("progression", {})
    p.setdefault("attendance", {"last_date": None, "streak": 0, "total": 0})
    p.setdefault("weekly", {"week_key": current_week_key(), "progress": {}, "claimed": []})
    p.setdefault("collection", {k: [] for k in (
        "items", "seeds", "fingerlings", "crops", "fish", "stones",
        "gems", "foods", "artifact_effects", "tools", "titles",
    )})
    for key in (
        "items", "seeds", "fingerlings", "crops", "fish", "stones",
        "gems", "foods", "artifact_effects", "tools", "titles",
    ):
        p["collection"].setdefault(key, [])
    p.setdefault("achievements", [])
    p.setdefault("secret_achievements", [])
    p.setdefault("notifications", [])
    p.setdefault("notification_keys", [])
    p.setdefault("collection_rewards", [])
    p.setdefault("achievement_rewards", [])
    p.setdefault("dungeon_hope_rewards", [])
    p.setdefault("hidden_tutorial", False)
    return p


def add_collection(user_data, category, name):
    p = ensure_progression(user_data)
    values = p["collection"].setdefault(category, [])
    if name not in values:
        values.append(name)
        return True
    return False


def add_notification(user_data, message):
    notes = ensure_progression(user_data)["notifications"]
    notes.append({"message": str(message), "read": False, "date": str(korea_today())})
    del notes[:-30]


def sync_life_notifications(user_data):
    """Create one in-game notification per completed long-running task."""
    life = ensure_life_data(user_data)
    progression = ensure_progression(user_data)
    keys = progression["notification_keys"]
    states = {
        "crop_ready": (
            bool((life.get("vegetable_garden", {}).get("plot") or {}).get("complete")),
            "채소밭의 작물을 수확할 수 있습니다.",
        ),
        "fish_ready": (
            bool((life.get("fish_farm", {}).get("tank") or {}).get("complete")),
            "양어장의 물고기를 출하할 수 있습니다.",
        ),
    }
    for slot_index, appraisal in enumerate(life.get("appraisal_slots", [])):
        if not appraisal:
            continue
        now = int(user_data.get("myhome", {}).get("total_turns", 0) or 0)
        start = int(appraisal.get("start_turn", now))
        required = int(appraisal.get("required_turns", 30))
        states[f"appraisal_ready_{slot_index}"] = (
            now - start >= required,
            f"{slot_index + 1}번 원석 감정이 완료되었습니다.",
        )
    for key, (ready, message) in states.items():
        if ready and key not in keys:
            add_notification(user_data, message)
            keys.append(key)
        elif not ready and key in keys:
            keys.remove(key)


def claim_attendance(user_data):
    p = ensure_progression(user_data)
    a = p["attendance"]
    today = korea_today()
    if a.get("last_date") == str(today):
        return False, "오늘 출석 보상을 이미 받았습니다."
    try:
        previous = datetime.strptime(a["last_date"], "%Y-%m-%d").date() if a.get("last_date") else None
    except ValueError:
        previous = None
    a["streak"] = int(a.get("streak", 0)) + 1 if previous == today - timedelta(days=1) else 1
    a["total"] = int(a.get("total", 0)) + 1
    a["last_date"] = str(today)
    reward = 20_000 + min(a["streak"], 7) * 5_000
    user_data["money"] = int(user_data.get("money", 0)) + reward
    if a["streak"] % 7 == 0:
        inv = user_data.setdefault("inventory", {})
        inv[PURE_HOPE_ITEM] = int(inv.get(PURE_HOPE_ITEM, 0)) + 1
        return True, f"{a['streak']}일 연속 출석! {reward:,}원과 순수한 희망 1개를 받았습니다."
    return True, f"출석 완료! {reward:,}원을 받았습니다. 연속 {a['streak']}일"


def weekly_progress(user_data, key, amount=1):
    w = ensure_progression(user_data)["weekly"]
    now = current_week_key()
    if w.get("week_key") != now:
        w.clear()
        w.update({"week_key": now, "progress": {}, "claimed": []})
    w["progress"][key] = int(w["progress"].get(key, 0)) + max(0, int(amount))


ACHIEVEMENTS = {
    "first_crop": "첫 작물 수확",
    "first_fish": "첫 양식 수확",
    "first_appraisal": "첫 원석 감정",
    "first_gem": "첫 젬 완성",
    "five_star_gem": "처음으로 5성 젬 완성",
    "first_tool_breakthrough": "세공 도구 첫 돌파",
    "max_tool": "세공 도구 최대 돌파",
    "first_food": "첫 요리",
    "masterpiece_food": "첫 걸작 요리",
    "first_research": "첫 레시피 연구 성공",
    "first_battle": "첫 전투 승리",
    "first_great_investigation": "첫 조사 대성공",
    "first_artifact_reroll": "첫 아티팩트 재조정",
}

SECRET_ACHIEVEMENTS = {
    "zero_star_finish": "미완의 아름다움",
    "no_cooling_finish": "불길을 두려워하지 않는 자",
    "overheated_five_star": "태양을 벼리다",
    "ten_normal_foods": "평범함의 달인",
    "first_try_research": "천재 요리사",
    "one_hp_victory": "마지막 한 걸음",
}

WEEKLY_MISSIONS = {
    "investigation_turns": ("조사 30턴", 30),
    "battle_wins": ("전투 5회 승리", 5),
    "crop_harvests": ("작물 3회 수확", 3),
    "fish_harvests": ("양식 3회 출하", 3),
    "foods_cooked": ("음식 5회 제작", 5),
    "recipe_research": ("레시피 연구 2회", 2),
    "gem_craft_actions": ("젬 세공 10행동", 10),
}

COLLECTION_REWARDS = {
    5: ("money", 50_000),
    15: ("hope", 1),
    30: ("stone", 1),
}


def claim_weekly_reward(user_data):
    p = ensure_progression(user_data)
    weekly_progress(user_data, "_refresh", 0)
    weekly = p["weekly"]
    completed = sum(
        int(weekly["progress"].get(key, 0)) >= target
        for key, (_, target) in WEEKLY_MISSIONS.items()
    )
    inventory = user_data.setdefault("inventory", {})
    messages = []
    if completed >= 4 and "main" not in weekly["claimed"]:
        weekly["claimed"].append("main")
        user_data["money"] = int(user_data.get("money", 0)) + 100_000
        inventory[PURE_HOPE_ITEM] = int(inventory.get(PURE_HOPE_ITEM, 0)) + 1
        messages.append("주간 기본 보상 100,000원과 순수한 희망 1개")
    if completed == len(WEEKLY_MISSIONS) and "perfect" not in weekly["claimed"]:
        weekly["claimed"].append("perfect")
        inventory[PURE_HOPE_ITEM] = int(inventory.get(PURE_HOPE_ITEM, 0)) + 1
        messages.append("주간 전체 완료 보너스 순수한 희망 1개")
    if not messages:
        if completed < 4:
            return False, f"주간 미션을 4개 완료해야 합니다. 현재 {completed}개"
        if completed < len(WEEKLY_MISSIONS):
            return False, (
                "기본 주간 보상은 받았습니다. 모든 주간 미션을 완료하면 "
                "순수한 희망 1개를 추가로 받을 수 있습니다."
            )
        return False, "이번 주의 모든 보상을 이미 받았습니다."
    return True, " · ".join(messages) + "를 받았습니다."


def claim_achievement_and_dungeon_rewards(user_data):
    p = ensure_progression(user_data)
    inventory = user_data.setdefault("inventory", {})
    claimed = []

    achievement_count = len(p["achievements"])
    for threshold in (5, 10):
        if achievement_count >= threshold and threshold not in p["achievement_rewards"]:
            p["achievement_rewards"].append(threshold)
            inventory[PURE_HOPE_ITEM] = int(inventory.get(PURE_HOPE_ITEM, 0)) + 1
            claimed.append(f"일반 업적 {threshold}개")

    best_depth = int(user_data.get("myhome", {}).get("max_subjugation_depth", 0) or 0)
    for threshold in (10, 25, 50):
        if best_depth >= threshold and threshold not in p["dungeon_hope_rewards"]:
            p["dungeon_hope_rewards"].append(threshold)
            inventory[PURE_HOPE_ITEM] = int(inventory.get(PURE_HOPE_ITEM, 0)) + 1
            claimed.append(f"던전 최고 {threshold}층")

    if not claimed:
        return False, "지금 받을 수 있는 새 업적·던전 기록 보상이 없습니다."
    return True, (
        f"{', '.join(claimed)} 달성 보상으로 "
        f"순수한 희망 {len(claimed)}개를 받았습니다."
    )


def claim_collection_rewards(user_data):
    p = ensure_progression(user_data)
    total = sum(len(values) for values in p["collection"].values())
    inventory = user_data.setdefault("inventory", {})
    claimed_now = []
    for threshold, (kind, amount) in COLLECTION_REWARDS.items():
        if total < threshold or threshold in p["collection_rewards"]:
            continue
        p["collection_rewards"].append(threshold)
        claimed_now.append(threshold)
        if kind == "money":
            user_data["money"] = int(user_data.get("money", 0)) + amount
        elif kind == "hope":
            inventory[PURE_HOPE_ITEM] = int(inventory.get(PURE_HOPE_ITEM, 0)) + amount
        else:
            inventory["원석"] = int(inventory.get("원석", 0)) + amount
    if not claimed_now:
        return False, "지금 받을 수 있는 새 도감 보상이 없습니다."
    return True, f"도감 {', '.join(map(str, claimed_now))}종 구간 보상을 받았습니다."


WIKI_CATEGORY_LABELS = {
    "items": "일반 아이템", "seeds": "씨앗·종균", "fingerlings": "치어·유생",
    "crops": "작물", "fish": "물고기", "stones": "원석", "gems": "젬",
    "foods": "요리", "artifact_effects": "아티팩트 효과",
    "tools": "세공 도구", "titles": "업적·칭호",
}

ITEM_TYPE_LABELS = {
    "material": "일반 재료",
    "rare_mat": "희귀 재료",
    "mythic": "신화 재료",
    "fish": "물고기",
    "consumable": "소비품",
    "crafted": "제작품",
    "box": "보물상자",
    "box_key": "열쇠",
    "special": "특수 아이템",
}

ARTIFACT_EFFECT_WIKI = {
    "reuse_last_dice": ("꼼꼼한", "비어 있는 행동에서 직전의 유효 주사위를 다시 활용하는 공용 효과입니다."),
    "fierce_attack": ("맹렬한", "일정 주기마다 공격 주사위의 위력을 크게 높이는 공용 효과입니다."),
    "sturdy_defense": ("견고한", "방어 주사위가 유효할 때 체력을 회복하는 공용 효과입니다."),
    "reflection": ("앙심품은", "실제로 받은 피해의 일부를 공격자에게 되돌리는 공용 효과입니다."),
    "escalation": ("고조된", "주기적으로 주사위에 무작위 추가 위력을 부여하는 공용 효과입니다."),
    "immortality": ("불멸의", "전투 불능에 이르렀을 때 전투당 한 번 부활하는 공용 효과입니다."),
    "youngsan_gold": ("황금의", "영산의 금전 소비 기술을 강화하는 캐릭터 전용 효과입니다."),
    "luude_imprint": ("악몽의", "루우데가 주사위를 파괴할 때 회복 또는 누적 피해 효과를 일으킵니다."),
    "earthreg_faith": ("믿음어린", "어즈렉의 방어 운용을 강화하는 캐릭터 전용 효과입니다."),
    "sensho_star": ("별똥별의", "센쇼의 별의 은총에 특별한 강화 판정을 추가합니다."),
    "Sensho_star": ("별똥별의", "센쇼의 별의 은총에 특별한 강화 판정을 추가합니다."),
    "kaian_time": ("시간의", "카이안의 시간가속과 시간술식 효과를 강화합니다."),
    "shayla_light": ("빛나는", "샤일라의 밀키워킹에 적 행동 파괴 효과를 추가합니다."),
}


def _wiki_display_name(category, name):
    if category == "titles":
        return ACHIEVEMENTS.get(name) or SECRET_ACHIEVEMENTS.get(name) or name
    if category == "artifact_effects":
        return ARTIFACT_EFFECT_WIKI.get(name, (name, ""))[0]
    return name


def _wiki_detail(category, name):
    """획득 기록을 기반으로 출처·용도·운용 힌트를 만든다."""
    if category in {"seeds", "fingerlings", "crops", "fish", "stones", "gems", "tools"}:
        from life_system import CROPS, FISH_SPECIES, SEED_ITEMS, FINGERLING_ITEMS, STONE_GEMS, TOOL_DEFS
        if category == "seeds":
            crop = next((key for key, item in SEED_ITEMS.items() if item == name), None)
            info = CROPS.get(crop, {})
            water = info.get("water", ("?", "?"))
            return (
                f"**재배 대상:** {crop or '알 수 없음'}\n"
                f"**기본 기간:** {info.get('turns', '?')}턴\n"
                f"**알맞은 수분:** {water[0]}~{water[1]}\n"
                "**고품질 힌트:** 수분을 알맞은 범위에 두고 영양 25 이상, "
                "건강 80 이상을 유지하세요. 건강할 때 가지치기를 하면 품질이 크게 오르고, "
                "햇빛 조절도 품질을 조금 높입니다. 스트레스 70 이상은 피하는 편이 좋습니다.\n"
                "생활 관리 → 채소밭에서 파종합니다."
            )
        if category == "fingerlings":
            fish = next((key for key, item in FINGERLING_ITEMS.items() if item == name), None)
            info = FISH_SPECIES.get(fish, {})
            water = info.get("water", ("?", "?"))
            return (
                f"**양식 대상:** {fish or '알 수 없음'}\n"
                f"**기본 기간:** {info.get('turns', '?')}턴\n"
                f"**알맞은 수질:** {water[0]}~{water[1]}\n"
                "**고품질 힌트:** 포만도를 30~85로 유지하면서 알맞은 수질을 맞추세요. "
                "관찰은 품질을 직접 높이며, 산소 공급은 스트레스를 낮춥니다. "
                "스트레스 70 이상과 질병 누적은 피하고 먹이 뒤에는 수질을 확인하세요.\n"
                "생활 관리 → 양어장에서 입식합니다."
            )
        if category == "crops":
            return f"채소밭 생산물입니다. 요리·납품에 사용합니다.\n기본 재배 기간: {CROPS.get(name, {}).get('turns', '?')}턴"
        if category == "fish":
            return f"낚시 또는 양어장 생산물입니다. 요리·납품에 사용합니다.\n기본 양식 기간: {FISH_SPECIES.get(name, {}).get('turns', '?')}턴"
        if category == "stones":
            entries = STONE_GEMS.get(name, [])
            choices = [entry.get("name", str(entry)) if isinstance(entry, dict) else str(entry) for entry in entries]
            return "젬 세공에서 다음 젬 중 하나를 선택합니다.\n" + (", ".join(choices) or "등록된 젬 없음")
        if category == "gems":
            for stone, entries in STONE_GEMS.items():
                for entry in entries:
                    if isinstance(entry, dict) and entry.get("name") == name:
                        return f"**계열:** {stone}\n{entry.get('description') or entry.get('summary') or '아티팩트 소켓에 장착하는 젬입니다.'}"
            return "아티팩트 소켓에 장착합니다. 정비 화면에서 실제 보정 수치를 확인하세요."
        if category == "tools":
            info = TOOL_DEFS.get(name, {})
            return info.get("description") or "젬 세공 전에 편성하는 영구 도구입니다."
    if category == "foods":
        from cooking_system_v6 import RECIPES
        info = RECIPES.get(name, {})
        ingredients = ", ".join(f"{item} ×{count}" for item, count in info.get("ingredients", {}).items())
        return f"**필요 재료:** {ingredients or '정보 없음'}\n**효과:** {info.get('description') or info.get('effect') or '요리 효과 정보 없음'}"
    if category == "titles":
        return f"달성한 업적 기록입니다.\n**{ACHIEVEMENTS.get(name) or SECRET_ACHIEVEMENTS.get(name) or name}**"
    if category == "artifact_effects":
        label, detail = ARTIFACT_EFFECT_WIKI.get(
            name,
            (name, "아티팩트에 기록된 고유 효과입니다."),
        )
        return f"**{label}**\n{detail}\n아티팩트 정비에서 현재 적용값을 확인하세요."
    if category == "items":
        from items import ITEM_CATEGORIES, REGIONS
        item_info = ITEM_CATEGORIES.get(name, {})
        raw_type = item_info.get("type", "기타")
        item_type = ITEM_TYPE_LABELS.get(raw_type, "기타")
        sources = [
            region for region, info in REGIONS.items()
            if name in info.get("common", []) or name in info.get("rare", [])
        ]
        if item_info.get("area") and item_info["area"] not in sources:
            sources.insert(0, item_info["area"])
        return f"**분류:** {item_type}\n**발견 지역:** {', '.join(sources[:5]) or '상점·제작·특수 보상'}\n제작소와 생활 메뉴에서 사용처를 확인하세요."
    return "아직 상세 설명이 준비되지 않은 획득 기록입니다."


class ObtainedWikiView(discord.ui.View):
    PAGE_SIZE = 8

    def __init__(self, author, user_data, save_func, parent_view):
        super().__init__(timeout=180)
        self.author, self.user_data, self.save_func = author, user_data, save_func
        self.parent_view = parent_view
        self.category, self.page, self.selected = "items", 0, None
        self.rebuild()

    def _names(self):
        return sorted(ensure_progression(self.user_data)["collection"].get(self.category, []))

    def rebuild(self):
        self.clear_items()
        categories = discord.ui.Select(
            placeholder="위키 분류 선택",
            options=[discord.SelectOption(label=label, value=key, default=key == self.category) for key, label in WIKI_CATEGORY_LABELS.items()],
            row=0,
        )
        categories.callback = self.select_category
        self.add_item(categories)
        names = self._names()
        visible = names[self.page * self.PAGE_SIZE:(self.page + 1) * self.PAGE_SIZE]
        if visible:
            entries = discord.ui.Select(
                placeholder="설명을 볼 항목 선택",
                options=[
                    discord.SelectOption(
                        label=str(_wiki_display_name(self.category, name))[:100],
                        value=name,
                    )
                    for name in visible
                ],
                row=1,
            )
            entries.callback = self.select_entry
            self.add_item(entries)
        prev = discord.ui.Button(label="이전", disabled=self.page <= 0, row=2)
        nxt = discord.ui.Button(label="다음", disabled=(self.page + 1) * self.PAGE_SIZE >= len(names), row=2)
        reward = discord.ui.Button(label="도감 보상", style=discord.ButtonStyle.success, row=2)
        back = discord.ui.Button(label="도감·업적으로", style=discord.ButtonStyle.secondary, row=2)
        prev.callback, nxt.callback = self.prev_page, self.next_page
        reward.callback, back.callback = self.claim_reward, self.go_back
        for item in (prev, nxt, reward, back):
            self.add_item(item)

    def get_embed(self):
        names = self._names()
        pages = max(1, (len(names) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        visible = names[self.page * self.PAGE_SIZE:(self.page + 1) * self.PAGE_SIZE]
        embed = discord.Embed(
            title=f"📖 획득 위키 — {WIKI_CATEGORY_LABELS[self.category]}",
            description=(
                "\n".join(
                    f"• {_wiki_display_name(self.category, name)}"
                    for name in visible
                )
                or "아직 획득한 항목이 없습니다."
            ),
            color=discord.Color.teal(),
        )
        if self.selected in names:
            embed.add_field(
                name=_wiki_display_name(self.category, self.selected),
                value=_wiki_detail(self.category, self.selected)[:1024],
                inline=False,
            )
        embed.set_footer(text=f"{self.page + 1}/{pages}페이지 · 획득 기록은 소비 후에도 유지됩니다.")
        return embed

    async def select_category(self, interaction):
        self.category, self.page, self.selected = interaction.data["values"][0], 0, None
        self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def select_entry(self, interaction):
        self.selected = interaction.data["values"][0]
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def prev_page(self, interaction):
        self.page, self.selected = max(0, self.page - 1), None
        self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def next_page(self, interaction):
        self.page, self.selected = self.page + 1, None
        self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def claim_reward(self, interaction):
        ok, message = claim_collection_rewards(self.user_data)
        if ok:
            try:
                await self.save_func(self.author.id, self.user_data)
            except TypeError:
                await self.save_func(self.user_data)
        await interaction.response.edit_message(content=message, embed=self.get_embed(), view=self)

    async def go_back(self, interaction):
        await interaction.response.edit_message(content=None, embed=self.parent_view.get_embed(), view=self.parent_view)


class ProgressionView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=180)
        self.author, self.user_data, self.save_func = author, user_data, save_func

    def get_embed(self):
        p = ensure_progression(self.user_data)
        weekly_progress(self.user_data, "_refresh", 0)
        sync_life_notifications(self.user_data)
        collection = p["collection"]
        e = discord.Embed(title="📚 도감·업적", color=discord.Color.blurple())
        e.add_field(
            name="도감",
            value="\n".join(f"{k}: {len(v)}종" for k, v in collection.items()),
            inline=False,
        )
        completed = [ACHIEVEMENTS.get(a, a) for a in p["achievements"]]
        e.add_field(name="일반 업적", value="\n".join(completed) or "아직 없음", inline=False)
        secrets = [SECRET_ACHIEVEMENTS.get(a, a) for a in p["secret_achievements"]]
        e.add_field(name="비밀 업적", value="\n".join(secrets) or "？？？？？", inline=False)
        weekly = p["weekly"]["progress"]
        weekly_lines = [
            f"{'✅' if int(weekly.get(key, 0)) >= target else '▫️'} "
            f"{label}: {min(int(weekly.get(key, 0)), target)}/{target}"
            for key, (label, target) in WEEKLY_MISSIONS.items()
        ]
        e.add_field(name=f"주간 미션 · {p['weekly']['week_key']}", value="\n".join(weekly_lines), inline=False)
        e.add_field(
            name="순수한 희망 기록 보상",
            value=(
                f"일반 업적 {len(p['achievements'])}개 · "
                f"던전 최고 {int(self.user_data.get('myhome', {}).get('max_subjugation_depth', 0) or 0)}층\n"
                "업적 5·10개 / 던전 10·25·50층에서 각각 1개"
            ),
            inline=False,
        )
        e.add_field(name="알림", value=f"읽지 않음 {sum(not n['read'] for n in p['notifications'])}개", inline=True)
        return e

    async def _save(self):
        try:
            await self.save_func(self.author.id, self.user_data)
        except TypeError:
            await self.save_func(self.user_data)

    @discord.ui.button(label="획득 위키", style=discord.ButtonStyle.success)
    async def collection_reward(self, interaction, button):
        view = ObtainedWikiView(self.author, self.user_data, self.save_func, self)
        await interaction.response.edit_message(content=None, embed=view.get_embed(), view=view)

    @discord.ui.button(label="주간 보상", style=discord.ButtonStyle.primary)
    async def weekly_reward(self, interaction, button):
        ok, message = claim_weekly_reward(self.user_data)
        if ok:
            await self._save()
        await interaction.response.edit_message(content=message, embed=self.get_embed(), view=self)

    @discord.ui.button(label="업적·던전 기록 보상", style=discord.ButtonStyle.success)
    async def achievement_reward(self, interaction, button):
        ok, message = claim_achievement_and_dungeon_rewards(self.user_data)
        if ok:
            await self._save()
        await interaction.response.edit_message(content=message, embed=self.get_embed(), view=self)

    @discord.ui.button(label="알림 모두 읽음", style=discord.ButtonStyle.secondary)
    async def read_notifications(self, interaction, button):
        for note in ensure_progression(self.user_data)["notifications"]:
            note["read"] = True
        await self._save()
        await interaction.response.edit_message(content="알림을 모두 읽었습니다.", embed=self.get_embed(), view=self)
