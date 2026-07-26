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
    p.setdefault("collection", {k: [] for k in ("crops", "fish", "stones", "gems", "foods", "artifact_effects", "tools")})
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

    @discord.ui.button(label="도감 보상", style=discord.ButtonStyle.success)
    async def collection_reward(self, interaction, button):
        ok, message = claim_collection_rewards(self.user_data)
        if ok:
            await self._save()
        await interaction.response.edit_message(content=message, embed=self.get_embed(), view=self)

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
