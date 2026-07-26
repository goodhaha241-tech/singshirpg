# completion-v6-cooking
# rollback-guard-appraisal-gems-v8
# pve-gem-runtime-v8.2
# gem-visibility-tools-v8.3
# cooking-select-details-v8.6.5
from __future__ import annotations

import random
from typing import Any

import discord

from balance_config_v6 import (
    COOKING_QUALITY_MULTIPLIER,
    COOKING_QUALITY_WEIGHTS,
    DAILY_DELIVERY_TARGET,
    RECIPE_RESEARCH_PITY,
    RECIPE_RESEARCH_MATERIALS,
    RECIPE_RESEARCH_MONEY,
)
from life_system import PURE_HOPE_ITEM, ensure_life_data
from gem_effects import gem_final_effect_value


RECIPES = {
    "감자 수프": {"ingredients": {"새벽 감자": 2}, "price": 8_000, "effect": "체력 회복"},
    "토마토 샐러드": {"ingredients": {"별빛 토마토": 2}, "price": 10_000, "effect": "정신력 회복"},
    "양파 구이": {"ingredients": {"구름 양파": 2}, "price": 9_000, "effect": "다음 전투 방어력 증가"},
    "당근 볶음": {"ingredients": {"무지개 당근": 2}, "price": 18_000, "effect": "다음 전투 공격력 증가"},
    "호박 스튜": {"ingredients": {"시간 호박": 2}, "price": 28_000, "effect": "다음 전투 최대 체력 증가"},
    "버섯 차": {"ingredients": {"달빛 버섯": 2}, "price": 20_000, "effect": "조사 실패율 감소"},
    "빵잉어 구이": {"ingredients": {"빵잉어": 2}, "price": 10_000, "effect": "체력·정신력 회복"},
    "버들치 조림": {"ingredients": {"버들치": 2}, "price": 16_000, "effect": "조사 보상 증가"},
    "모래무지 튀김": {"ingredients": {"모래무지": 2}, "price": 15_000, "effect": "다음 전투 첫 피해 감소"},
    "새우 꼬치": {"ingredients": {"로운새우": 3}, "price": 17_000, "effect": "다음 전투 공격력 증가"},
    "등불오징어 볶음": {"ingredients": {"등불오징어": 2}, "price": 32_000, "effect": "조사 대성공률 증가"},
    "별비늘돔 만찬": {"ingredients": {"별비늘돔": 1, "별빛 토마토": 1}, "price": 70_000, "effect": "강력한 다음 전투 버프"},
}

STARTER_RECIPES = {"감자 수프", "토마토 샐러드", "빵잉어 구이", "버들치 조림"}
RESEARCH_POOLS = {
    "작물": list(RECIPES)[:6],
    "수산": list(RECIPES)[6:],
    "특수": ["별비늘돔 만찬", "등불오징어 볶음", "호박 스튜"],
}
INGREDIENT_QUALITY_BONUS = {
    "시든": -8,
    "보통": 0,
    "싱싱한": 4,
    "우수한": 8,
    "최상급": 14,
    "환상적인": 20,
}


def ensure_cooking_data(user_data: dict[str, Any]) -> dict[str, Any]:
    life = ensure_life_data(user_data)
    cooking = life.setdefault("cooking", {})
    cooking.setdefault("unlocked_recipes", sorted(STARTER_RECIPES))
    cooking.setdefault("foods", {})
    cooking.setdefault("research_failures", {"작물": 0, "수산": 0, "특수": 0})
    cooking.setdefault("delivery", {})
    cooking.setdefault("normal_quality_streak", 0)
    return cooking


def recipe_material_status(
    user_data: dict[str, Any],
    recipe_name: str,
    count: int = 1,
) -> list[tuple[str, int, int]]:
    """Return (material, current stock, required stock) rows for a recipe."""
    inventory = user_data.setdefault("inventory", {})
    count = max(1, int(count))
    return [
        (item, int(inventory.get(item, 0)), int(need) * count)
        for item, need in RECIPES[recipe_name]["ingredients"].items()
    ]


def can_cook_recipe(user_data: dict[str, Any], recipe_name: str, count: int = 1) -> bool:
    if recipe_name not in RECIPES:
        return False
    return all(have >= need for _, have, need in recipe_material_status(user_data, recipe_name, count))


def craftable_recipes(user_data: dict[str, Any], count: int = 1) -> list[str]:
    unlocked = ensure_cooking_data(user_data)["unlocked_recipes"]
    return [
        recipe_name
        for recipe_name in unlocked
        if recipe_name in RECIPES and can_cook_recipe(user_data, recipe_name, count)
    ]


def format_recipe_materials(user_data: dict[str, Any], recipe_name: str, count: int = 1) -> str:
    return " · ".join(
        f"{item} {have}/{need}"
        for item, have, need in recipe_material_status(user_data, recipe_name, count)
    )


def format_recipe_option(user_data: dict[str, Any], recipe_name: str, count: int = 1) -> str:
    materials = format_recipe_materials(user_data, recipe_name, count)
    effect = RECIPES.get(recipe_name, {}).get("effect", "효과 정보 없음")
    return f"재료 {materials} · 효과 {effect}"[:100]


def food_recipe_name(food_key: str) -> str:
    return food_key.split(" ", 1)[1] if " " in food_key else food_key


def food_quality(food_key: str) -> str:
    return food_key.split(" ", 1)[0] if " " in food_key else "보통"


def research_materials(category: str) -> list[str]:
    materials = []
    for recipe_name in RESEARCH_POOLS.get(category, []):
        for item in RECIPES[recipe_name]["ingredients"]:
            if item not in materials:
                materials.append(item)
    return materials


def research_available(user_data: dict[str, Any], category: str) -> bool:
    cooking = ensure_cooking_data(user_data)
    locked = [
        name for name in RESEARCH_POOLS.get(category, [])
        if name not in cooking["unlocked_recipes"]
    ]
    if not locked or int(user_data.get("money", 0)) < RECIPE_RESEARCH_MONEY:
        return False
    inventory = user_data.setdefault("inventory", {})
    return any(
        int(inventory.get(item, 0)) >= RECIPE_RESEARCH_MATERIALS
        for item in research_materials(category)
    )


def _roll_quality(bonus: int = 0, masterpiece_bonus: int = 0) -> str:
    normal = max(0, COOKING_QUALITY_WEIGHTS["보통"] - bonus)
    great = COOKING_QUALITY_WEIGHTS["훌륭함"] + bonus * 0.8
    master = COOKING_QUALITY_WEIGHTS["걸작"] + bonus * 0.2 + masterpiece_bonus
    return random.choices(["보통", "훌륭함", "걸작"], [normal, great, master], k=1)[0]


def _cooking_gem_bonus(user_data: dict[str, Any]) -> tuple[int, int]:
    characters = user_data.get("characters", [])
    if not characters:
        return 0, 0
    index = min(int(user_data.get("investigator_index", 0) or 0), len(characters) - 1)
    character = characters[index]
    artifacts = [
        character.get("equipped_artifact"),
        character.get("equipped_engraved_artifact"),
    ]
    matches = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        for gem in artifact.get("gems", []):
            if gem and gem.get("name") == "조리의 젬":
                matches.append(gem)
    if not matches:
        return 0, 0
    effect_total = sum(gem_final_effect_value(gem) for gem in matches)
    maximum_star = max(int(gem.get("star", 0) or 0) for gem in matches)
    great_bonus = 5 if maximum_star >= 3 else 0
    masterpiece_bonus = 3 if maximum_star >= 5 else 0
    return effect_total + great_bonus, masterpiece_bonus


def _consume_quality_records(user_data: dict[str, Any], item: str, count: int) -> list[int]:
    """Consume the highest-quality matching production records first."""
    life = ensure_life_data(user_data)
    stores = [
        life.get("vegetable_garden", {}).get("produce", {}),
        life.get("fish_farm", {}).get("produce", {}),
    ]
    remaining = count
    bonuses = []
    candidates = []
    for store in stores:
        for quality, bonus in INGREDIENT_QUALITY_BONUS.items():
            key = f"{quality} {item}"
            if int(store.get(key, 0)) > 0:
                candidates.append((bonus, store, key))
    for bonus, store, key in sorted(candidates, key=lambda row: row[0], reverse=True):
        used = min(remaining, int(store.get(key, 0)))
        store[key] -= used
        bonuses.extend([bonus] * used)
        remaining -= used
        if remaining <= 0:
            break
    bonuses.extend([0] * remaining)
    return bonuses


def cook(user_data: dict[str, Any], recipe_name: str, count: int = 1, quality_bonus: int = 0):
    cooking = ensure_cooking_data(user_data)
    if recipe_name not in cooking["unlocked_recipes"] or recipe_name not in RECIPES:
        return False, "해금되지 않은 레시피입니다.", []
    count = max(1, min(10, int(count)))
    inv = user_data.setdefault("inventory", {})
    recipe = RECIPES[recipe_name]
    for item, need in recipe["ingredients"].items():
        if int(inv.get(item, 0)) < need * count:
            return False, f"{item}이(가) 부족합니다.", []
    ingredient_bonuses = []
    for item, need in recipe["ingredients"].items():
        required = need * count
        inv[item] -= required
        ingredient_bonuses.extend(_consume_quality_records(user_data, item, required))
    ingredient_bonus = (
        round(sum(ingredient_bonuses) / len(ingredient_bonuses))
        if ingredient_bonuses else 0
    )
    cooking_bonus, masterpiece_bonus = _cooking_gem_bonus(user_data)
    final_quality_bonus = int(quality_bonus) + ingredient_bonus + cooking_bonus
    results = []
    for _ in range(count):
        quality = _roll_quality(final_quality_bonus, masterpiece_bonus)
        key = f"{quality} {recipe_name}"
        cooking["foods"][key] = int(cooking["foods"].get(key, 0)) + 1
        results.append(quality)
    try:
        from progression_system_v6 import add_collection, ensure_progression, weekly_progress
        add_collection(user_data, "foods", recipe_name)
        weekly_progress(user_data, "foods_cooked", count)
        progression = ensure_progression(user_data)
        if "first_food" not in progression["achievements"]:
            progression["achievements"].append("first_food")
        if "걸작" in results and "masterpiece_food" not in progression["achievements"]:
            progression["achievements"].append("masterpiece_food")
        for quality in results:
            cooking["normal_quality_streak"] = (
                cooking["normal_quality_streak"] + 1 if quality == "보통" else 0
            )
        if (
            cooking["normal_quality_streak"] >= 10
            and "ten_normal_foods" not in progression["secret_achievements"]
        ):
            progression["secret_achievements"].append("ten_normal_foods")
    except ImportError:
        pass
    return True, f"{recipe_name} {count}개를 완성했습니다.", results


def sell_food(user_data: dict[str, Any], food_key: str, count: int = 1):
    cooking = ensure_cooking_data(user_data)
    count = max(1, int(count))
    if cooking["foods"].get(food_key, 0) < count:
        return False, "보유한 요리가 부족합니다."
    quality, recipe_name = food_key.split(" ", 1)
    if recipe_name not in RECIPES:
        return False, "알 수 없는 요리입니다."
    reward = int(RECIPES[recipe_name]["price"] * COOKING_QUALITY_MULTIPLIER.get(quality, 1) * count)
    cooking["foods"][food_key] -= count
    user_data["money"] = int(user_data.get("money", 0)) + reward
    return True, f"{reward:,}원을 획득했습니다."


def use_food(user_data: dict[str, Any], food_key: str):
    cooking = ensure_cooking_data(user_data)
    if int(cooking["foods"].get(food_key, 0)) <= 0:
        return False, "보유한 요리가 없습니다."
    quality, recipe_name = food_key.split(" ", 1)
    recipe = RECIPES.get(recipe_name)
    if not recipe:
        return False, "알 수 없는 요리입니다."
    multiplier = COOKING_QUALITY_MULTIPLIER.get(quality, 1)
    characters = user_data.get("characters", [])
    index = min(int(user_data.get("investigator_index", 0) or 0), max(0, len(characters) - 1))
    character = characters[index] if characters else None
    effect = recipe["effect"]

    if "회복" in effect:
        if not character:
            return False, "효과를 받을 캐릭터가 없습니다."
        hp_amount = max(1, round(int(character.get("hp", 100)) * 0.15 * multiplier))
        mental_amount = max(1, round(int(character.get("max_mental", 50)) * 0.15 * multiplier))
        if "체력" in effect:
            character["current_hp"] = min(
                int(character.get("hp", 100)),
                int(character.get("current_hp", character.get("hp", 100))) + hp_amount,
            )
        if "정신력" in effect or "체력·정신력" in effect:
            character["current_mental"] = min(
                int(character.get("max_mental", 50)),
                int(character.get("current_mental", character.get("max_mental", 50))) + mental_amount,
            )
        message = f"{character.get('name', '캐릭터')}이(가) 회복했습니다."
    else:
        if not character:
            return False, "효과를 받을 캐릭터가 없습니다."
        stat, base, duration = "attack", 5, 1
        if "방어력" in effect:
            stat, base = "defense", 5
        elif "최대 체력" in effect:
            stat, base = "max_hp", 20
        elif "첫 피해" in effect:
            stat, base = "defense_rate", 5
        elif "조사" in effect:
            stat, base, duration = "success_rate", 5, 10
        elif "강력한" in effect:
            stat, base = "attack", 12
        value = max(1, round(base * multiplier))
        buffs = user_data.setdefault("buffs", {})
        buffs[f"음식:{recipe_name}"] = {
            "source": "food",
            "target": character.get("name"),
            "stat": stat,
            "value": value,
            "duration": duration,
        }
        message = f"{recipe_name} 효과가 적용되었습니다. ({stat} +{value})"

    cooking["foods"][food_key] -= 1
    return True, message


def delivery_points(quality: str) -> int:
    return {"보통": 1, "훌륭함": 2, "걸작": 3}.get(quality, 1)


def deliver_food(user_data: dict[str, Any], food_key: str, count: int, day_key: str):
    cooking = ensure_cooking_data(user_data)
    count = max(1, int(count))
    if cooking["foods"].get(food_key, 0) < count:
        return False, "보유한 요리가 부족합니다."
    quality, recipe_name = food_key.split(" ", 1)
    delivery = cooking["delivery"]
    if delivery.get("date") != day_key:
        delivery.clear()
        delivery.update({"date": day_key, "points": 0, "claimed": False})
    cooking["foods"][food_key] -= count
    points = delivery_points(quality) * count
    delivery["points"] += points
    money = int(RECIPES.get(recipe_name, {}).get("price", 0) * 0.8 * count)
    user_data["money"] = int(user_data.get("money", 0)) + money
    claimed = False
    if delivery["points"] >= DAILY_DELIVERY_TARGET and not delivery["claimed"]:
        inv = user_data.setdefault("inventory", {})
        inv[PURE_HOPE_ITEM] = int(inv.get(PURE_HOPE_ITEM, 0)) + 1
        delivery["claimed"] = True
        claimed = True
    suffix = " 순수한 희망 1개도 획득했습니다!" if claimed else ""
    return True, f"납품 실적 +{points}, {money:,}원 획득.{suffix}"


def research_recipe(user_data: dict[str, Any], category: str):
    cooking = ensure_cooking_data(user_data)
    locked = [r for r in RESEARCH_POOLS.get(category, []) if r not in cooking["unlocked_recipes"]]
    if not locked:
        return False, "이 계열의 모든 레시피를 연구했습니다."
    if int(user_data.get("money", 0)) < RECIPE_RESEARCH_MONEY:
        return False, f"연구비 {RECIPE_RESEARCH_MONEY:,}원이 필요합니다."
    candidate_materials = research_materials(category)
    inventory = user_data.setdefault("inventory", {})
    material = next(
        (item for item in candidate_materials if int(inventory.get(item, 0)) >= RECIPE_RESEARCH_MATERIALS),
        None,
    )
    if not material:
        return False, f"해당 계열 재료 {RECIPE_RESEARCH_MATERIALS}개가 필요합니다."
    user_data["money"] -= RECIPE_RESEARCH_MONEY
    inventory[material] -= RECIPE_RESEARCH_MATERIALS
    failures = cooking["research_failures"].get(category, 0)
    first_attempt = failures == 0
    try:
        from progression_system_v6 import weekly_progress
        weekly_progress(user_data, "recipe_research", 1)
    except ImportError:
        pass
    if failures + 1 >= RECIPE_RESEARCH_PITY or random.random() < 0.35:
        found = random.choice(locked)
        cooking["unlocked_recipes"].append(found)
        cooking["research_failures"][category] = 0
        try:
            from progression_system_v6 import ensure_progression
            progression = ensure_progression(user_data)
            if "first_research" not in progression["achievements"]:
                progression["achievements"].append("first_research")
            if first_attempt and "first_try_research" not in progression["secret_achievements"]:
                progression["secret_achievements"].append("first_try_research")
        except ImportError:
            pass
        return True, f"새 레시피 **{found}**을(를) 발견했습니다!"
    cooking["research_failures"][category] = failures + 1
    return False, f"연구 기록이 쌓였습니다. ({failures + 1}/{RECIPE_RESEARCH_PITY})"


async def _save(save_func, author, user_data):
    try:
        await save_func(author.id, user_data)
    except TypeError:
        await save_func(user_data)


# owner-isolated-ui-v8.6.4
async def _cooking_owner_only(view, interaction):
    parent = getattr(view, "parent", None)
    author = getattr(view, "author", None) or getattr(parent, "author", None)
    if author is not None and interaction.user.id == author.id:
        return True
    await interaction.response.send_message("❌ 본인의 요리 화면만 조작할 수 있습니다.", ephemeral=True)
    return False


async def _back_to_cooking(parent, interaction, message=None):
    parent._rebuild_menu()
    await interaction.response.edit_message(
        content=None,
        embed=parent.get_embed(message),
        view=parent,
    )


class CookingView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=180)
        self.author, self.user_data, self.save_func = author, user_data, save_func
        ensure_cooking_data(user_data)
        self.page = 0
        self._rebuild_menu()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _cooking_owner_only(self, interaction)

    def _rebuild_menu(self):
        self.clear_items()
        entries = [self.cook_one, self.cook_ten, self.research, self.sell, self.use]
        for item in entries[self.page * 3:self.page * 3 + 3]:
            self.add_item(item)
        page_button = discord.ui.Button(
            label="이전 메뉴" if self.page else "다음 메뉴",
            style=discord.ButtonStyle.secondary,
            row=3,
        )
        page_button.callback = self._toggle_page
        self.add_item(page_button)

    async def _toggle_page(self, interaction):
        self.page = 0 if self.page else 1
        self._rebuild_menu()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    def get_embed(self, message=None):
        c = ensure_cooking_data(self.user_data)
        available = craftable_recipes(self.user_data, 1)
        available_lines = [
            f"• **{name}** — {format_recipe_materials(self.user_data, name)}"
            for name in available
        ]
        recipe_lines = []
        for name in c["unlocked_recipes"]:
            if name not in RECIPES:
                continue
            marker = "✅" if can_cook_recipe(self.user_data, name) else "❌"
            recipe_lines.append(
                f"{marker} **{name}** — {format_recipe_materials(self.user_data, name)}"
            )
        foods = "\n".join(f"• {k} ×{v}" for k, v in c["foods"].items() if v) or "없음"
        e = discord.Embed(
            title="🍳 요리",
            description=message or "현재 재고로 만들 수 있는 요리만 조리 선택지에 표시됩니다.",
            color=discord.Color.orange(),
        )
        e.add_field(
            name="지금 만들 수 있는 요리",
            value=("\n".join(available_lines) or "현재 재료로 만들 수 있는 요리가 없습니다.")[:1024],
            inline=False,
        )
        e.add_field(
            name="필요 재료 / 현재 재고",
            value=("\n".join(recipe_lines) or "해금된 레시피가 없습니다.")[:1024],
            inline=False,
        )
        e.add_field(name="완성 요리", value=foods[:1024], inline=False)
        return e

    @discord.ui.button(label="레시피 1개 조리", style=discord.ButtonStyle.success)
    async def cook_one(self, interaction, button):
        recipes = craftable_recipes(self.user_data, 1)
        if not recipes:
            return await interaction.response.send_message(
                "현재 재료로 만들 수 있는 요리가 없습니다.",
                ephemeral=True,
            )
        await interaction.response.edit_message(
            content="조리할 레시피를 선택하세요.",
            embed=None,
            view=RecipeSelectView(self, recipes, 1),
        )

    @discord.ui.button(label="레시피 10개 조리", style=discord.ButtonStyle.primary)
    async def cook_ten(self, interaction, button):
        recipes = craftable_recipes(self.user_data, 10)
        if not recipes:
            return await interaction.response.send_message(
                "현재 재료로 10개 만들 수 있는 요리가 없습니다.",
                ephemeral=True,
            )
        await interaction.response.edit_message(
            content="조리할 레시피를 선택하세요.",
            embed=None,
            view=RecipeSelectView(self, recipes, 10),
        )

    @discord.ui.button(label="레시피 연구", style=discord.ButtonStyle.secondary)
    async def research(self, interaction, button):
        view = ResearchView(self)
        await interaction.response.edit_message(content=None, embed=view.get_embed(), view=view)

    @discord.ui.button(label="완성 요리 판매", style=discord.ButtonStyle.secondary)
    async def sell(self, interaction, button):
        await interaction.response.edit_message(
            content="판매할 완성 요리를 선택하세요.",
            embed=None,
            view=SellFoodView(self),
        )

    @discord.ui.button(label="완성 요리 먹기", style=discord.ButtonStyle.secondary)
    async def use(self, interaction, button):
        await interaction.response.edit_message(
            content="먹을 완성 요리를 선택하세요.",
            embed=None,
            view=UseFoodView(self),
        )


class SellFoodView(discord.ui.View):
    def __init__(self, parent):
        super().__init__(timeout=90)
        self.parent = parent
        foods = [
            (name, count)
            for name, count in ensure_cooking_data(parent.user_data)["foods"].items()
            if count
        ]
        self.foods, self.page = foods, 0
        self.rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _cooking_owner_only(self, interaction)

    def rebuild(self):
        self.clear_items()
        visible = self.foods[self.page * 8:self.page * 8 + 8]
        total_pages = max(1, (len(self.foods) + 7) // 8)
        if visible:
            select = discord.ui.Select(
                placeholder=f"판매할 완성 요리 선택 ({self.page + 1}/{total_pages})",
                options=[
                    discord.SelectOption(
                        label=f"{name} ×{count}",
                        value=name,
                        description=(
                            f"1개 판매가 "
                            f"{int(RECIPES.get(food_recipe_name(name), {}).get('price', 0) * COOKING_QUALITY_MULTIPLIER.get(food_quality(name), 1)):,}원"
                        )[:100],
                    )
                    for name, count in visible
                ],
            )
            select.callback = self.selected
            self.add_item(select)
        self._page_buttons()
        back = discord.ui.Button(label="요리로 돌아가기", style=discord.ButtonStyle.secondary, row=4)
        back.callback = lambda interaction: _back_to_cooking(self.parent, interaction)
        self.add_item(back)

    def _page_buttons(self):
        if len(self.foods) <= 8: return
        prev = discord.ui.Button(label="이전", disabled=self.page == 0)
        page = discord.ui.Button(
            label=f"{self.page + 1}/{(len(self.foods) + 7) // 8}",
            disabled=True,
        )
        nxt = discord.ui.Button(label="다음", disabled=(self.page + 1) * 8 >= len(self.foods))
        async def move(i, delta):
            self.page += delta; self.rebuild(); await i.response.edit_message(view=self)
        prev.callback = lambda i: move(i, -1); nxt.callback = lambda i: move(i, 1)
        self.add_item(prev); self.add_item(page); self.add_item(nxt)

    async def selected(self, interaction):
        food = interaction.data["values"][0]
        ok, message = sell_food(self.parent.user_data, food, 1)
        if ok:
            await _save(self.parent.save_func, self.parent.author, self.parent.user_data)
        await _back_to_cooking(self.parent, interaction, message)


class UseFoodView(discord.ui.View):
    def __init__(self, parent):
        super().__init__(timeout=90)
        self.parent = parent
        foods = [
            (name, count)
            for name, count in ensure_cooking_data(parent.user_data)["foods"].items()
            if count
        ]
        self.foods, self.page = foods, 0
        self.rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _cooking_owner_only(self, interaction)

    def rebuild(self):
        self.clear_items()
        visible = self.foods[self.page * 8:self.page * 8 + 8]
        total_pages = max(1, (len(self.foods) + 7) // 8)
        if visible:
            select = discord.ui.Select(
                placeholder=f"먹을 완성 요리 선택 ({self.page + 1}/{total_pages})",
                options=[
                    discord.SelectOption(
                        label=f"{name} ×{count}",
                        value=name,
                        description=(
                            f"효과: {RECIPES.get(food_recipe_name(name), {}).get('effect', '정보 없음')}"
                        )[:100],
                    )
                    for name, count in visible
                ],
            )
            select.callback = self.selected
            self.add_item(select)
        if len(self.foods) > 8:
            prev = discord.ui.Button(label="이전", disabled=self.page == 0)
            page = discord.ui.Button(
                label=f"{self.page + 1}/{total_pages}",
                disabled=True,
            )
            nxt = discord.ui.Button(label="다음", disabled=(self.page + 1) * 8 >= len(self.foods))
            async def move(i, delta):
                self.page += delta; self.rebuild(); await i.response.edit_message(view=self)
            prev.callback = lambda i: move(i, -1); nxt.callback = lambda i: move(i, 1)
            self.add_item(prev); self.add_item(page); self.add_item(nxt)
        back = discord.ui.Button(label="요리로 돌아가기", style=discord.ButtonStyle.secondary, row=4)
        back.callback = lambda interaction: _back_to_cooking(self.parent, interaction)
        self.add_item(back)

    async def selected(self, interaction):
        food = interaction.data["values"][0]
        ok, message = use_food(self.parent.user_data, food)
        if ok:
            await _save(self.parent.save_func, self.parent.author, self.parent.user_data)
        await _back_to_cooking(self.parent, interaction, message)


class RecipeSelectView(discord.ui.View):
    def __init__(self, parent, recipes, count):
        super().__init__(timeout=90)
        self.parent, self.count, self.recipes, self.page = parent, count, recipes, 0
        self.rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _cooking_owner_only(self, interaction)

    def rebuild(self):
        self.clear_items()
        visible = self.recipes[self.page * 8:self.page * 8 + 8]
        total_pages = max(1, (len(self.recipes) + 7) // 8)
        select = discord.ui.Select(
            placeholder=f"레시피 선택 · {self.count}개 조리 ({self.page + 1}/{total_pages})",
            options=[
                discord.SelectOption(
                    label=r,
                    value=r,
                    description=format_recipe_option(self.parent.user_data, r, self.count),
                )
                for r in visible
            ],
        )
        select.callback = self.selected
        self.add_item(select)
        if len(self.recipes) > 8:
            prev = discord.ui.Button(label="이전", disabled=self.page == 0)
            page = discord.ui.Button(
                label=f"{self.page + 1}/{total_pages}",
                disabled=True,
            )
            nxt = discord.ui.Button(label="다음", disabled=(self.page + 1) * 8 >= len(self.recipes))
            async def move(i, delta):
                self.page += delta; self.rebuild(); await i.response.edit_message(view=self)
            prev.callback = lambda i: move(i, -1); nxt.callback = lambda i: move(i, 1)
            self.add_item(prev); self.add_item(page); self.add_item(nxt)
        back = discord.ui.Button(label="요리로 돌아가기", style=discord.ButtonStyle.secondary, row=4)
        back.callback = lambda interaction: _back_to_cooking(self.parent, interaction)
        self.add_item(back)

    async def selected(self, interaction):
        recipe = interaction.data["values"][0]
        cooking_bonus, masterpiece_bonus = _cooking_gem_bonus(self.parent.user_data)
        ok, msg, results = cook(self.parent.user_data, recipe, self.count)
        if ok:
            await _save(self.parent.save_func, self.parent.author, self.parent.user_data)
            art = "  (  )\n (    )\n┌──────┐\n│ 요리 │\n└──────┘"
            msg = f"```text\n{art}\n```\n{msg}\n품질: {', '.join(results)}"
            if cooking_bonus or masterpiece_bonus:
                msg += (
                    f"\n💎 조리의 젬 적용: 품질 가중치 +{cooking_bonus}"
                    + (
                        f" · 걸작 가중치 +{masterpiece_bonus}"
                        if masterpiece_bonus else ""
                    )
                )
        await _back_to_cooking(self.parent, interaction, msg)


class ResearchView(discord.ui.View):
    def __init__(self, parent):
        super().__init__(timeout=90)
        self.parent = parent
        inventory = parent.user_data.setdefault("inventory", {})
        options = []
        for category in RESEARCH_POOLS:
            if not research_available(parent.user_data, category):
                continue
            stocks = ", ".join(
                f"{item} {int(inventory.get(item, 0))}/{RECIPE_RESEARCH_MATERIALS}"
                for item in research_materials(category)
            )
            options.append(
                discord.SelectOption(
                    label=f"{category} 연구",
                    value=category,
                    description=(
                        f"재료 {stocks or '없음'} · 연구비 {RECIPE_RESEARCH_MONEY:,}원"
                    )[:100],
                )
            )
        if options:
            category_select = discord.ui.Select(
                placeholder="연구 가능한 계열 선택",
                options=options[:8],
                row=0,
            )
            category_select.callback = self.select_category
            self.add_item(category_select)
        back = discord.ui.Button(label="요리로 돌아가기", style=discord.ButtonStyle.secondary, row=1)
        back.callback = lambda interaction: _back_to_cooking(self.parent, interaction)
        self.add_item(back)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _cooking_owner_only(self, interaction)

    def get_embed(self, message=None):
        cooking = ensure_cooking_data(self.parent.user_data)
        inventory = self.parent.user_data.setdefault("inventory", {})
        embed = discord.Embed(
            title="🔬 레시피 연구",
            description=message or (
                f"연구비 {RECIPE_RESEARCH_MONEY:,}원과 같은 계열 재료 "
                f"{RECIPE_RESEARCH_MATERIALS}개가 필요합니다."
            ),
            color=discord.Color.purple(),
        )
        for category in RESEARCH_POOLS:
            locked = [
                name for name in RESEARCH_POOLS[category]
                if name not in cooking["unlocked_recipes"]
            ]
            stocks = " · ".join(
                f"{item} {int(inventory.get(item, 0))}/{RECIPE_RESEARCH_MATERIALS}"
                for item in research_materials(category)
            ) or "사용 가능한 재료 없음"
            state = "연구 가능" if research_available(self.parent.user_data, category) else "연구 불가"
            if not locked:
                state = "연구 완료"
            embed.add_field(
                name=f"{category} — {state}",
                value=(
                    f"미발견 {len(locked)}종 · 기록 "
                    f"{int(cooking['research_failures'].get(category, 0))}/{RECIPE_RESEARCH_PITY}\n"
                    f"{stocks}"
                )[:1024],
                inline=False,
            )
        return embed

    async def run(self, interaction, category):
        ok, msg = research_recipe(self.parent.user_data, category)
        await _save(self.parent.save_func, self.parent.author, self.parent.user_data)
        refreshed = ResearchView(self.parent)
        await interaction.response.edit_message(content=None, embed=refreshed.get_embed(msg), view=refreshed)

    async def select_category(self, interaction):
        await self.run(interaction, interaction.data["values"][0])


class CookingDeliveryView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=180)
        self.author, self.user_data, self.save_func = author, user_data, save_func
        foods = [(name, count) for name, count in ensure_cooking_data(user_data)["foods"].items() if count]
        self.foods, self.page = foods, 0
        self.rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _cooking_owner_only(self, interaction)

    def rebuild(self):
        self.clear_items()
        visible = self.foods[self.page * 8:self.page * 8 + 8]
        total_pages = max(1, (len(self.foods) + 7) // 8)
        if visible:
            select = discord.ui.Select(
                placeholder=f"납품할 완성 요리 선택 ({self.page + 1}/{total_pages})",
                options=[
                    discord.SelectOption(
                        label=f"{name} ×{count}",
                        value=name,
                        description=(
                            f"1개당 실적 {delivery_points(food_quality(name))} · "
                            f"{int(RECIPES.get(food_recipe_name(name), {}).get('price', 0) * 0.8):,}원"
                        )[:100],
                    )
                    for name, count in visible
                ],
            )
            select.callback = self.deliver
            self.add_item(select)
        if len(self.foods) > 8:
            prev = discord.ui.Button(label="이전", disabled=self.page == 0)
            page = discord.ui.Button(
                label=f"{self.page + 1}/{total_pages}",
                disabled=True,
            )
            nxt = discord.ui.Button(label="다음", disabled=(self.page + 1) * 8 >= len(self.foods))
            async def move(i, delta):
                self.page += delta; self.rebuild(); await i.response.edit_message(view=self)
            prev.callback = lambda i: move(i, -1); nxt.callback = lambda i: move(i, 1)
            self.add_item(prev); self.add_item(page); self.add_item(nxt)

    def get_embed(self):
        from progression_system_v6 import korea_today
        c = ensure_cooking_data(self.user_data)
        d = c["delivery"]
        if d.get("date") != str(korea_today()):
            points, claimed = 0, False
        else:
            points, claimed = int(d.get("points", 0)), bool(d.get("claimed"))
        return discord.Embed(
            title="📦 요리 납품",
            description=(
                f"오늘 실적: {points}/{DAILY_DELIVERY_TARGET}\n"
                f"순수한 희망 수령: {'완료' if claimed else '미완료'}\n"
                "보통 1점 · 훌륭함 2점 · 걸작 3점"
            ),
            color=discord.Color.blue(),
        )

    async def deliver(self, interaction):
        from progression_system_v6 import korea_today
        food = interaction.data["values"][0]
        ok, msg = deliver_food(self.user_data, food, 1, str(korea_today()))
        if ok:
            await _save(self.save_func, self.author, self.user_data)
        await interaction.response.edit_message(content=msg, embed=self.get_embed(), view=self)
