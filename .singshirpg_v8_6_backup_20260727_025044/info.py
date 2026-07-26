# info.py
# appraisal-gem-affixes-v8.1
# gem-visibility-tools-v8.3
import discord
from character import (
    Character,
    artifact_effective_stats,
    gem_main_stat_bonuses,
)
from items import ITEM_CATEGORIES
from data_manager import get_user_data
from decorators import auto_defer
from gem_manager import gem_detail_text

class InventoryPaginationView(discord.ui.View):
    """인벤토리 페이지 넘김을 담당하는 뷰"""
    def __init__(self, author, pages_data):
        super().__init__(timeout=60)
        self.author = author
        self.pages = pages_data 
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.prev_btn.disabled = (self.current_page == 0)
        self.next_btn.disabled = (self.current_page == len(self.pages) - 1)
        self.counter_btn.label = f"{self.current_page + 1} / {len(self.pages)}"

    def get_current_embed(self):
        page_data = self.pages[self.current_page]
        embed = discord.Embed(title=f"🎒 {self.author.name}의 가방", color=discord.Color.blue())
        items_text = "\n".join(page_data["items"]) if page_data["items"] else "비어 있음"
        embed.add_field(name=page_data["title"], value=items_text, inline=False)
        return embed

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.primary)
    @auto_defer()
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.edit_original_response(embed=self.get_current_embed(), view=self)

    @discord.ui.button(label="...", style=discord.ButtonStyle.secondary, disabled=True)
    async def counter_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.primary)
    @auto_defer()
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.edit_original_response(embed=self.get_current_embed(), view=self)

async def info_command(ctx, load_data, get_user_data, save_data):
    # [수정] load_data가 None이므로 호출하지 않습니다. (DB 사용으로 변경됨)
    data = None
    # [수정] get_user_data 호출 시 불필요한 data 인자를 제거하고, main.py와 동일하게 display_name을 사용합니다.
    user_stat = await get_user_data(ctx.author.id, ctx.author.display_name)

    embed = discord.Embed(title=f"👤 {ctx.author.name}님의 정보", color=discord.Color.blue())
    embed.add_field(name="💰 보유 자산", value=f"머니: {user_stat.get('money', 0):,}원\n포인트: {user_stat.get('pt', 0):,}pt", inline=False)
    
    # 캐릭터 정보 요약
    chars = user_stat.get("characters", [])
    if chars:
        char_text = ""
        for c in chars:
            char_text += f"• **{c['name']}** (HP: {c['current_hp']}/{c['hp']})\n"
        embed.add_field(name="⚔️ 보유 캐릭터", value=char_text, inline=False)

    view = InfoMainView(ctx.author, user_stat, save_data)
    await ctx.send(embed=embed, view=view)

class InfoMainView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func

        # 캐릭터 상태 버튼 추가
        status_btn = discord.ui.Button(label="📊 캐릭터 상태", style=discord.ButtonStyle.primary)
        status_btn.callback = self.show_character_status
        self.add_item(status_btn)


    @discord.ui.button(label="🎒 가방 확인", style=discord.ButtonStyle.success)
    @auto_defer()
    async def open_inventory(self, interaction: discord.Interaction, button: discord.ui.Button):
        
        inventory = self.user_data.get("inventory", {})
        if not inventory:
            return await interaction.followup.send("🎒 가방이 비어있습니다.", ephemeral=True)

        categories = {
            "consumable": {"title": "🧪 소비품", "items": []},
            "crafted": {"title": "⚒️ 제작 아이템", "items": []},
            "box": {"title": "📦 상자/열쇠", "items": []},
            "special": {"title": "✨ 특별한 재료", "items": []},
            "material": {"title": "🌿 일반 재료", "items": []}
        }

        for item_name, count in inventory.items():
            if count <= 0: continue
            info = ITEM_CATEGORIES.get(item_name, {"type": "material"})
            itype = info.get("type", "material")

            target = "material"
            if itype == "consumable": target = "consumable"
            elif itype == "crafted": target = "crafted"
            elif itype in ["box", "box_key"]: target = "box"
            elif itype in ["rare_mat", "mythic"]: target = "special"
            
            item_str = f"**{item_name}** x{count}" if target == "special" else f"{item_name} x{count}"
            categories[target]["items"].append(item_str)

        ITEMS_PER_PAGE = 7
        pages_data = []
        for key in ["consumable", "crafted", "box", "special", "material"]:
            items = categories[key]["items"]
            if items:
                for i in range(0, len(items), ITEMS_PER_PAGE):
                    chunk = items[i:i + ITEMS_PER_PAGE]
                    title = categories[key]["title"]
                    if len(items) > ITEMS_PER_PAGE:
                        title += f" ({(i // ITEMS_PER_PAGE) + 1}/{(len(items) - 1) // ITEMS_PER_PAGE + 1})"
                    pages_data.append({"title": title, "items": chunk})

        if not pages_data:
            await interaction.followup.send("🎒 가방이 비어있습니다.", ephemeral=True)
        else:
            view = InventoryPaginationView(self.author, pages_data)
            await interaction.followup.send(embed=view.get_current_embed(), view=view, ephemeral=True)

    @auto_defer()
    async def show_character_status(self, interaction: discord.Interaction):
        # 캐릭터 상세 정보 뷰로 전환
        view = InfoView(self.author, self.user_data, self.save_func)
        embed = view.create_status_embed()
        await interaction.response.edit_message(embed=embed, view=view)

class InfoView(discord.ui.View):
    """캐릭터 상세 정보 및 상태창 복귀를 위한 뷰"""
    INFO_PAGE_LABELS = ("개요", "일반 장비", "전용 장비", "버프")

    def __init__(self, author=None, user_data=None, save_func=None, char_index=0, timeout=600):
        super().__init__(timeout=timeout)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.char_index = char_index
        self.info_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()

        # 캐릭터 페이지네이션 버튼
        char_list = self.user_data.get("characters", []) if self.user_data else []
        # [수정] 지속성 등록(user_data is None)이거나 캐릭터가 여러 개일 때 버튼 추가
        if self.user_data is None or len(char_list) > 1:
            prev_char_btn = discord.ui.Button(label="◀️ 이전", style=discord.ButtonStyle.secondary, row=0, disabled=(self.char_index == 0), custom_id="info:char_prev")
            prev_char_btn.callback = self.prev_char
            self.add_item(prev_char_btn)

            next_char_btn = discord.ui.Button(label="다음 ▶️", style=discord.ButtonStyle.secondary, row=0, disabled=(self.char_index >= len(char_list) - 1), custom_id="info:char_next")
            next_char_btn.callback = self.next_char
            self.add_item(next_char_btn)

        prev_info_btn = discord.ui.Button(
            label="◀ 정보",
            style=discord.ButtonStyle.secondary,
            row=0,
            disabled=self.info_page == 0,
            custom_id="info:detail_prev",
        )
        prev_info_btn.callback = self.prev_info_page
        self.add_item(prev_info_btn)

        self.add_item(discord.ui.Button(
            label=f"{self.info_page + 1}/{len(self.INFO_PAGE_LABELS)} {self.INFO_PAGE_LABELS[self.info_page]}",
            style=discord.ButtonStyle.secondary,
            row=0,
            disabled=True,
            custom_id="info:detail_counter",
        ))

        next_info_btn = discord.ui.Button(
            label="정보 ▶",
            style=discord.ButtonStyle.secondary,
            row=0,
            disabled=self.info_page >= len(self.INFO_PAGE_LABELS) - 1,
            custom_id="info:detail_next",
        )
        next_info_btn.callback = self.next_info_page
        self.add_item(next_info_btn)

        # 기능 버튼들 (StatusMenuView 기능 통합)
        btn_inv = discord.ui.Button(label="🎒 가방", style=discord.ButtonStyle.secondary, row=1, custom_id="info:inventory")
        btn_inv.callback = self.open_inventory
        self.add_item(btn_inv)

        btn_use = discord.ui.Button(label="🧪 사용", style=discord.ButtonStyle.secondary, row=1, custom_id="info:use")
        btn_use.callback = self.use_item_callback
        self.add_item(btn_use)

        btn_card = discord.ui.Button(label="🃏 카드", style=discord.ButtonStyle.secondary, row=1, custom_id="info:card")
        btn_card.callback = self.card_manage_callback
        self.add_item(btn_card)

        btn_home = discord.ui.Button(label="🏡 정비", style=discord.ButtonStyle.success, row=1, custom_id="info:home")
        btn_home.callback = self.myhome_callback
        self.add_item(btn_home)

    @auto_defer(reload_data=True)
    async def use_item_callback(self, interaction: discord.Interaction):
        from use_item import ItemUseView
        view = ItemUseView(self.author, self.user_data, self.save_func, self.char_index)
        embed = discord.Embed(title="🎒 아이템 사용", description="사용할 아이템을 선택하세요.", color=discord.Color.blue())
        await interaction.edit_original_response(content=None, embed=embed, view=view)

    @auto_defer(reload_data=True)
    async def card_manage_callback(self, interaction: discord.Interaction):
        from card_manager import CardManageView
        view = CardManageView(self.author, self.user_data, self.save_func, char_index=self.char_index)
        await interaction.edit_original_response(content=None, embed=view.create_embed(), view=view)

    @auto_defer(reload_data=True)
    async def myhome_callback(self, interaction: discord.Interaction):
        from myhome import MyHomeView
        view = MyHomeView(self.author, self.user_data, self.save_func)
        await interaction.edit_original_response(content=None, embed=view.get_embed(), view=view)

    @auto_defer(reload_data=True)
    async def prev_char(self, interaction: discord.Interaction):
        self.char_index -= 1
        self.info_page = 0
        self.update_buttons()
        await interaction.edit_original_response(embed=self.create_status_embed(), view=self)

    @auto_defer(reload_data=True)
    async def next_char(self, interaction: discord.Interaction):
        self.char_index += 1
        self.info_page = 0
        self.update_buttons()
        await interaction.edit_original_response(embed=self.create_status_embed(), view=self)

    @auto_defer(reload_data=True)
    async def prev_info_page(self, interaction: discord.Interaction):
        self.info_page = max(0, self.info_page - 1)
        self.update_buttons()
        await interaction.edit_original_response(embed=self.create_status_embed(), view=self)

    @auto_defer(reload_data=True)
    async def next_info_page(self, interaction: discord.Interaction):
        self.info_page = min(len(self.INFO_PAGE_LABELS) - 1, self.info_page + 1)
        self.update_buttons()
        await interaction.edit_original_response(embed=self.create_status_embed(), view=self)

    @auto_defer(reload_data=True)
    async def go_back(self, interaction: discord.Interaction):
        view = InfoMainView(self.author, self.user_data, self.save_func)
        embed = discord.Embed(title=f"👤 {self.author.name}님의 정보", color=discord.Color.blue())
        embed.add_field(name="💰 보유 자산", value=f"머니: {self.user_data.get('money', 0):,}원\n포인트: {self.user_data.get('pt', 0):,}pt", inline=False)
        chars = self.user_data.get("characters", [])
        if chars:
            char_text = "\n".join([f"• **{c['name']}** (HP: {c['current_hp']}/{c['hp']})" for c in chars])
            embed.add_field(name="⚔️ 보유 캐릭터", value=char_text, inline=False)
        await interaction.edit_original_response(embed=embed, view=view)

    @auto_defer(reload_data=True)
    async def open_inventory(self, interaction: discord.Interaction):
        inventory = self.user_data.get("inventory", {})
        if not inventory:
            return await interaction.followup.send("🎒 가방이 비어있습니다.", ephemeral=True)

        categories = {
            "consumable": {"title": "🧪 소비품", "items": []},
            "crafted": {"title": "⚒️ 제작 아이템", "items": []},
            "box": {"title": "📦 상자/열쇠", "items": []},
            "special": {"title": "✨ 특별한 재료", "items": []},
            "material": {"title": "🌿 일반 재료", "items": []}
        }

        for item_name, count in inventory.items():
            if count <= 0: continue
            info = ITEM_CATEGORIES.get(item_name, {"type": "material"})
            itype = info.get("type", "material")

            target = "material"
            if itype == "consumable": target = "consumable"
            elif itype == "crafted": target = "crafted"
            elif itype in ["box", "box_key"]: target = "box"
            elif itype in ["rare_mat", "mythic"]: target = "special"
            
            item_str = f"**{item_name}** x{count}" if target == "special" else f"{item_name} x{count}"
            categories[target]["items"].append(item_str)

        ITEMS_PER_PAGE = 7
        pages_data = []
        for key in ["consumable", "crafted", "box", "special", "material"]:
            items = categories[key]["items"]
            if items:
                # 10개씩 나누어 페이지 생성
                for i in range(0, len(items), ITEMS_PER_PAGE):
                    chunk = items[i:i + ITEMS_PER_PAGE]
                    title = categories[key]["title"]
                    if len(items) > ITEMS_PER_PAGE:
                        title += f" ({(i // ITEMS_PER_PAGE) + 1}/{(len(items) - 1) // ITEMS_PER_PAGE + 1})"
                    pages_data.append({"title": title, "items": chunk})

        if not pages_data:
            await interaction.followup.send("🎒 가방이 비어있습니다.", ephemeral=True)
        else:
            view = InventoryPaginationView(self.author, pages_data)
            await interaction.followup.send(embed=view.get_current_embed(), view=view, ephemeral=True)

    def create_status_embed(self):
        if not self.user_data:
            return discord.Embed(title="데이터 로드 중...", description="잠시만 기다려주세요.", color=discord.Color.orange())
            
        chars = self.user_data.get("characters", [])
        if not chars:
            return discord.Embed(title="캐릭터 없음", description="보유한 캐릭터가 없습니다.", color=discord.Color.red())
        
        if self.char_index >= len(chars): self.char_index = 0
        char_data = chars[self.char_index]
        
        self.info_page = max(0, min(self.info_page, len(self.INFO_PAGE_LABELS) - 1))
        page_label = self.INFO_PAGE_LABELS[self.info_page]
        embed = discord.Embed(
            title=f"📊 {char_data['name']} · {page_label}",
            color=discord.Color.blue(),
        )
        
        # 1. 아티팩트 스탯 계산
        art_stats = {"max_hp": 0, "max_mental": 0, "attack": 0, "defense": 0, "defense_rate": 0}
        engraved_stats = {"max_hp": 0, "max_mental": 0, "attack": 0, "defense": 0, "defense_rate": 0}

        art = char_data.get("equipped_artifact")
        if art and isinstance(art, dict):
            for key, value in artifact_effective_stats(art).items():
                if value > 0:
                    art_stats[key] = art_stats.get(key, 0) + value
        
        # [신규] 각인 아티팩트 스탯 합산 (분리)
        engraved_art = char_data.get("equipped_engraved_artifact")
        if engraved_art and isinstance(engraved_art, dict):
            for key, value in artifact_effective_stats(engraved_art).items():
                if value > 0:
                    engraved_stats[key] = engraved_stats.get(key, 0) + value

        equipped_artifacts = [
            artifact
            for artifact in (art, engraved_art)
            if isinstance(artifact, dict)
        ]
        post_artifact_stats = {
            "max_hp": int(char_data.get("hp", 0)) + art_stats["max_hp"] + engraved_stats["max_hp"],
            "max_mental": int(char_data.get("max_mental", 90)) + art_stats["max_mental"] + engraved_stats["max_mental"],
            "attack": int(char_data.get("attack", 0)) + art_stats["attack"] + engraved_stats["attack"],
            "defense": int(char_data.get("defense", 0)) + art_stats["defense"] + engraved_stats["defense"],
            "defense_rate": int(char_data.get("defense_rate", 0)) + art_stats["defense_rate"] + engraved_stats["defense_rate"],
        }
        gem_stats = gem_main_stat_bonuses(post_artifact_stats, equipped_artifacts)

        # 2. 버프 스탯 계산 (카페 음식 및 부적 등)
        buff_stats = {"max_hp": 0, "max_mental": 0, "attack": 0, "defense": 0, "defense_rate": 0, "success_rate": 0}
        buffs = self.user_data.get("buffs", {})
        for b_key, b_info in buffs.items():
            # [추가] 캐릭터 전용 버프 필터링 (타겟 정보가 있으면 현재 캐릭터와 일치하는지 확인)
            target = b_info.get("target")
            if target != char_data['name']:
                continue

            # trade.py(카페)는 'stat' 키를 사용하고, use_item.py(부적)는 키 자체가 스탯명일 수 있음
            s_name = b_info.get("stat", b_key)
            if s_name in buff_stats:
                buff_stats[s_name] += b_info.get("value", 0)

        # 표시 형식: 기본 → 아티팩트 보조 적용 → 젬 주 능력 → 음식·기타 버프
        def format_stat(base, art, engraved, gem, buff, is_percent=False):
            total = base + art + engraved + gem + buff
            unit = "%" if is_percent else ""
            if art > 0 or engraved > 0 or gem > 0 or buff > 0:
                parts = [str(base)]
                if art > 0: parts.append(f"💍{art}")
                if engraved > 0: parts.append(f"🔮{engraved}")
                if gem > 0: parts.append(f"💎{gem}")
                if buff > 0: parts.append(f"☕{buff}")
                return f"{total}{unit} ({'+'.join(parts)}){unit}"
            return f"{total}{unit}"

        # HP 및 멘탈 표시
        hp_val_str = format_stat(char_data.get('hp', 0), art_stats["max_hp"], engraved_stats["max_hp"], gem_stats["max_hp"], buff_stats["max_hp"])
        hp_str = f"{char_data.get('current_hp')}/{hp_val_str}"

        mental_val_str = format_stat(char_data.get('max_mental', 90), art_stats["max_mental"], engraved_stats["max_mental"], gem_stats["max_mental"], buff_stats["max_mental"])
        mental_str = f"{char_data.get('current_mental')}/{mental_val_str}"
        
        if self.info_page == 0:
            embed.add_field(name="상태", value=f"❤️ HP: {hp_str}\n🔮 멘탈: {mental_str}", inline=True)
        
        # 전투 능력치 표시
        atk_str = format_stat(char_data.get('attack', 0), art_stats["attack"], engraved_stats["attack"], gem_stats["attack"], buff_stats["attack"])
        dfs_str = format_stat(char_data.get('defense', 0), art_stats["defense"], engraved_stats["defense"], gem_stats["defense"], buff_stats["defense"])
        dr_str = format_stat(char_data.get('defense_rate', 0), art_stats["defense_rate"], engraved_stats["defense_rate"], gem_stats["defense_rate"], buff_stats["defense_rate"], True)
        sr_str = f"+{buff_stats['success_rate']}%" if buff_stats['success_rate'] > 0 else "0%"

        ability_value = f"⚔️ 공격력: {atk_str}\n🛡️ 방어력: {dfs_str}\n✨ 피해감소: {dr_str}\n🍀 조사보정: {sr_str}"
        if self.info_page == 0:
            embed.add_field(name="능력치", value=ability_value, inline=True)
        
        # 장비 정보
        cards = char_data.get("equipped_cards", [])
        card_str = ", ".join(cards) if cards else "없음"
        if self.info_page == 0:
            embed.add_field(name="🎴 장착 카드", value=card_str, inline=False)
        
        art_str = "없음"
        if art:
            art_name = f"{art.get('name')} (+{art.get('level', 0)})"
            art_desc = art.get('description', '설명 없음')
            art_str = f"**{art_name}**\n{art_desc}"
        if self.info_page == 1:
            embed.add_field(name="💍 일반 아티팩트", value=art_str, inline=False)

        # [신규] 각인 아티팩트 표시
        engraved_str = "없음"
        if engraved_art:
            e_name = f"{engraved_art.get('name')} (+{engraved_art.get('level', 0)})"
            e_desc = engraved_art.get('description', '설명 없음')
            engraved_str = f"**{e_name}**\n{e_desc}"
        if self.info_page == 2:
            embed.add_field(
                name="🔮 전용 아티팩트 · 고정 3성/3소켓",
                value=engraved_str,
                inline=False,
            )

        # 장착한 모든 젬의 실제 수치와 3성·5성 해금 내용을 상태창에서도 확인한다.
        visible_artifacts = ()
        if self.info_page == 1:
            visible_artifacts = (("일반", art),)
        elif self.info_page == 2:
            visible_artifacts = (("전용", engraved_art),)
        for artifact_label, artifact in visible_artifacts:
            if not isinstance(artifact, dict):
                continue
            for socket_index, gem in enumerate(artifact.get("gems", [])):
                if not isinstance(gem, dict):
                    continue
                embed.add_field(
                    name=f"💎 {artifact_label} {socket_index + 1}번 · {gem.get('name', '젬')}",
                    value=gem_detail_text(gem)[:1024],
                    inline=False,
                )
        
        # 활성화된 버프 목록 표시
        if self.info_page == 3 and buffs:
            buff_lines = []
            for b_name, b_info in buffs.items():
                # 표시할 때도 해당 캐릭터의 버프만 필터링
                if b_info.get("target") and b_info.get("target") != char_data['name']:
                    continue
                buff_lines.append(f"• **{b_name}**: {b_info.get('duration')}회 남음")
            if buff_lines:
                embed.add_field(name="☕ 활성화된 버프", value="\n".join(buff_lines), inline=False)
        if self.info_page == 3 and not embed.fields:
            embed.add_field(name="☕ 활성화된 버프", value="현재 적용 중인 버프가 없습니다.", inline=False)

        embed.set_footer(
            text=(
                f"캐릭터 {self.char_index + 1}/{len(chars)} · "
                f"정보 {self.info_page + 1}/{len(self.INFO_PAGE_LABELS)}"
            )
        )

        return embed
