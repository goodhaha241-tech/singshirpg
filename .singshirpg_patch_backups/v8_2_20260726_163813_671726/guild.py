# rollback-guard-appraisal-gems-v8
import discord
# cumulative-v2: one shared guild, automatic membership
import random
import json
import asyncio
from discord.ui import View, Select, Button, Modal, TextInput
from data_manager import (
    get_user_data, get_db_pool, save_user_data,
    get_user_guild_info, create_guild, join_guild_by_id,
    deposit_guild_item, deposit_guild_artifact, get_guild_logs, get_guild_list,
    get_guild_items, withdraw_guild_item
)
from items import ITEM_CATEGORIES
from monsters import RAID_BOSS_DATA, Monster
from character import Character
from cards import get_card
import battle_engine

# guild-pvp-stability-v7.2

# --- 설정 데이터 (items.py 기준 통일) ---
ITEM_TOKEN_VALUES = {
    "목재": {"wood": 10}, "철괴": {"iron": 10}, "중급 마력석": {"magic": 10},
    "주술석": {"sorcery": 10}, "구름 블럭": {"wood": 20, "magic": 5},
    "양질 목재": {"wood": 30, "sorcery": 10},
    "강화 철강": {"iron": 20, "magic": 5},
    "상급 마력석": {"magic": 30},
    "고급 주술석": {"sorcery": 30},
    "응결 구름 블럭": {"wood": 40, "magic": 10},
    "낡은 열쇠": {"iron": 5},       
    "낡은 보물상자": {"wood": 15},  
    "평범한 나무판자": {"wood": 5},
    "녹슨 철": {"iron": 5},
}

RANK_NAMES = {1: "Bronze", 2: "Silver", 3: "Gold", 4: "Platinum", 5: "Diamond"}

# ==================================================================================
# 1. 물자 관리 (입/출고 통합)
# ==================================================================================

class QuantityModal(Modal):
    """수량 입력 모달 (입고/출고 공용)"""
    def __init__(self, mode, item_name, guild_id, user_data, parent_view):
        title = "납품 수량 입력" if mode == "deposit" else "수령 수량 입력"
        super().__init__(title=title)
        self.mode = mode
        self.item_name = item_name
        self.guild_id = guild_id
        self.user_data = user_data
        self.parent_view = parent_view
        self.amount = TextInput(label="수량", placeholder="숫자만 입력하세요", min_length=1)
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            qty = int(self.amount.value)
            if qty <= 0: raise ValueError
        except ValueError:
            return await interaction.response.send_message("❌ 올바른 숫자를 입력하세요.", ephemeral=True)

        if self.mode == "deposit":
            # 입고 로직
            inventory = self.user_data.get("inventory", {})
            if inventory.get(self.item_name, 0) < qty:
                return await interaction.response.send_message(f"❌ 보유 수량이 부족합니다. (보유: {inventory.get(self.item_name, 0)}개)", ephemeral=True)

            cat = "material"
            for c_name, items in ITEM_CATEGORIES.items():
                if self.item_name in items:
                    if c_name == "consumable": cat = "consumable"
                    break
            
            tokens_per_unit = ITEM_TOKEN_VALUES.get(self.item_name, {"wood": 1})
            total_tokens = {k: v * qty for k, v in tokens_per_unit.items()}
            
            success, msg = await deposit_guild_item(interaction.user.id, self.guild_id, self.item_name, qty, cat, total_tokens)
        else:
            # 출고 로직
            success, msg = await withdraw_guild_item(interaction.user.id, self.guild_id, self.item_name, qty)

        await interaction.response.send_message(msg, ephemeral=True)
        if success and hasattr(self.parent_view, 'refresh'):
            await self.parent_view.refresh(interaction)

class InventoryManageView(discord.ui.View):
    """길드 물자 관리 뷰 (입고/출고 탭)"""
    def __init__(self, author, guild_info, mode="deposit"):
        super().__init__(timeout=60)
        self.author = author
        self.guild_info = guild_info
        self.mode = mode # 'deposit' or 'withdraw'
        self.user_data = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인의 길드 납품 화면만 조작할 수 있습니다.", ephemeral=True)
        return False

    async def setup_view(self):
        self.clear_items()
        self.user_data = await get_user_data(self.author.id)
        
        # 상단 탭 버튼
        btn_dep = Button(label="📥 입고(납품)", style=discord.ButtonStyle.primary if self.mode=="deposit" else discord.ButtonStyle.secondary)
        btn_dep.callback = self.switch_to_deposit
        self.add_item(btn_dep)
        
        # 공용 길드의 자원은 개인 인벤토리로 출고하지 않는다.

        # 아이템 선택 메뉴
        if self.mode == "deposit":
            inventory = self.user_data.get("inventory", {})
            items = [(name, count) for name, count in inventory.items() if name in ITEM_TOKEN_VALUES and count > 0]
            placeholder = "납품할 자재 선택"
        else:
            # 출고: 길드 인벤토리 조회
            g_items = await get_guild_items(self.guild_info['guild_id'])
            items = [(i['item_name'], i['count']) for i in g_items]
            placeholder = "꺼낼 자재 선택"

        if not items:
            self.add_item(Button(label="가능한 아이템이 없습니다", disabled=True, row=1))
        else:
            options = []
            for name, count in items[:25]:
                options.append(discord.SelectOption(label=f"{name} (x{count})", value=name))
            
            select = Select(placeholder=placeholder, options=options, row=1)
            select.callback = self.on_select
            self.add_item(select)

    async def switch_to_deposit(self, interaction):
        self.mode = "deposit"
        await self.setup_view()
        await interaction.response.edit_message(content="📥 **자재 납품** 모드입니다.", view=self)

    async def switch_to_withdraw(self, interaction):
        await interaction.response.send_message(
            "📦 공용 자원은 개인 인벤토리로 출고할 수 없습니다.",
            ephemeral=True,
        )

    async def on_select(self, interaction):
        if interaction.user.id != self.author.id: return
        item_name = interaction.data["values"][0]
        await interaction.response.send_modal(
            QuantityModal(self.mode, item_name, self.guild_info['guild_id'], self.user_data, self)
        )
    
    async def refresh(self, interaction):
        await self.setup_view()
        # 메시지 갱신이 필요하면 여기서 처리 (보통 모달 후 메시지는 유지됨)

# ==================================================================================
# 2. 길드 미션 시스템
# ==================================================================================

class GuildMissionView(discord.ui.View):
    def __init__(self, author, guild_info):
        super().__init__(timeout=60)
        self.author = author
        self.guild_info = guild_info
        
    async def get_embed(self):
        # 미션 데이터가 없으면 랜덤 생성 (실제로는 DB나 매일 자정 갱신 로직 필요)
        # 여기서는 임시로 랜덤 표시
        missions = [
            {"title": "철괴 지원", "desc": "철괴 10개 납품", "reward": "🌲 목재 100"},
            {"title": "마력 비축", "desc": "중급 마력석 5개 납품", "reward": "💰 길드경험치 50"},
            {"title": "토벌 작전", "desc": "레이드 1회 참여", "reward": "💎 다이아몬드 1"},
        ]
        
        embed = discord.Embed(title=f"📜 {self.guild_info['name']} 길드 미션", color=discord.Color.green())
        for m in missions:
            embed.add_field(name=f"🔹 {m['title']}", value=f"{m['desc']}\n보상: {m['reward']}", inline=False)
        
        embed.set_footer(text="미션은 매일 자정에 갱신됩니다.")
        return embed

    @discord.ui.button(label="새로고침", style=discord.ButtonStyle.secondary)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=await self.get_embed())

# ==================================================================================
# 3. 길드 창고 및 아티팩트
# ==================================================================================

class ArtifactDepositSelectView(discord.ui.View):
    def __init__(self, author, user_data, guild_id, parent_view):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.guild_id = guild_id
        self.parent_view = parent_view
        self.artifacts = self.user_data.get("artifacts", [])
        self.add_select()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인의 아티팩트만 보관할 수 있습니다.", ephemeral=True)
        return False

    def add_select(self):
        if not self.artifacts:
            self.add_item(Button(label="❌ 보관할 아티팩트가 없습니다.", disabled=True))
            return

        options = []
        for i, art in enumerate(self.artifacts[:25]):
            label = f"{art['name']} (+{art.get('level', 0)})"
            desc = f"Rank: {art.get('rank_level', 1)} | {art.get('prefix', '')}"
            options.append(discord.SelectOption(label=label, description=desc, value=str(i)))

        select = discord.ui.Select(placeholder="길드 창고에 넣을 아티팩트 선택", options=options)
        select.callback = self.callback
        self.add_item(select)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id: return
        idx = int(interaction.data["values"][0])
        if idx >= len(self.artifacts): return
            
        artifact = self.artifacts.pop(idx)
        success, msg = await deposit_guild_artifact(self.author.id, self.guild_id, artifact)
        
        if success:
            # The DB helper moves the artifact atomically and increments the
            # snapshot revision. Reload instead of writing the old full snapshot.
            self.user_data = await get_user_data(self.author.id, self.author.display_name)
            self.artifacts = self.user_data.get("artifacts", [])
            await interaction.response.send_message(f"✅ **{artifact['name']}**을(를) 보관했습니다!", ephemeral=True)
        else:
            self.artifacts.insert(idx, artifact)
            await interaction.response.send_message(f"❌ 보관 실패: {msg}", ephemeral=True)

class GuildWarehouseView(discord.ui.View):
    def __init__(self, author, guild_info):
        super().__init__(timeout=120)
        self.author = author
        self.guild_info = guild_info
        self.category = "consumable"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인이 연 길드 창고 화면만 조작할 수 있습니다.", ephemeral=True)
        return False
        
    async def get_embed(self):
        new_info = await get_user_guild_info(self.author.id)
        if new_info: self.guild_info = new_info
        g = self.guild_info
        
        embed = discord.Embed(title=f"🏰 {g['name']} 길드 창고", color=discord.Color.blue())
        tokens = (
            f"🌲 목재: {g['token_wood']:,} | ⛓️ 철괴: {g['token_iron']:,}\n"
            f"🔮 마력: {g['token_magic']:,} | 🧿 주술: {g['token_sorcery']:,}"
        )
        embed.add_field(name="💰 길드 자금", value=tokens, inline=False)
        
        items = await get_guild_items(g['guild_id'], self.category)
        titles = {"consumable": "🍎 소모품", "material": "🪵 재료/제작품", "artifact": "💍 아티팩트"}
        content = ""
        
        if not items:
            content = "*(비어있음)*"
        else:
            if self.category == "artifact":
                lines = []
                for item in items[:15]:
                    data = item.get('data', {})
                    if isinstance(data, str):
                        try: data = json.loads(data)
                        except: data = {}
                    prefix = data.get('prefix', '')
                    lines.append(f"• **{item['name']}** (+{item.get('level', 0)}) [{prefix}]")
                content = "\n".join(lines)
                if len(items) > 15: content += f"\n...외 {len(items)-15}개"
            else:
                lines = [f"• **{i['item_name']}**: {i['count']}개" for i in items]
                content = "\n".join(lines)

        embed.add_field(name=f"📂 {titles[self.category]} 보관함", value=content, inline=False)
        return embed

    async def refresh(self, interaction):
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=await self.get_embed(), view=self)
        else:
            await interaction.response.edit_message(embed=await self.get_embed(), view=self)

    @discord.ui.button(label="🍎 소모품", style=discord.ButtonStyle.secondary)
    async def btn_consumable(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.category = "consumable"; await self.refresh(interaction)

    @discord.ui.button(label="🪵 재료", style=discord.ButtonStyle.secondary)
    async def btn_material(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.category = "material"; await self.refresh(interaction)

    @discord.ui.button(label="💍 아티팩트", style=discord.ButtonStyle.secondary)
    async def btn_artifact(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.category = "artifact"; await self.refresh(interaction)
    
    @discord.ui.button(label="📥 아티팩트 보관", style=discord.ButtonStyle.success, row=1)
    async def btn_deposit_art(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_data = await get_user_data(interaction.user.id)
        view = ArtifactDepositSelectView(interaction.user, user_data, self.guild_info['guild_id'], self)
        await interaction.response.send_message("보관할 아티팩트를 선택하세요.", view=view, ephemeral=True)

    @discord.ui.button(label="📜 로그", style=discord.ButtonStyle.primary, row=1)
    async def btn_logs(self, interaction: discord.Interaction, button: discord.ui.Button):
        logs = await get_guild_logs(self.guild_info['guild_id'])
        if not logs: return await interaction.response.send_message("기록이 없습니다.", ephemeral=True)
        text = ""
        for l in logs:
            action = "입고" if l['action_type'] == 'deposit' else "출고" if l['action_type'] == 'withdraw' else "보관"
            text += f"• [{action}] **{l['item_name']}** x{l['count']} ({l.get('user_name', '알수없음')})\n"
        await interaction.response.send_message(embed=discord.Embed(title="📋 최근 활동", description=text), ephemeral=True)

# ==================================================================================
# 4. 레이드 (기존 유지)
# ==================================================================================
class RaidCardSelectView(discord.ui.View):
    def __init__(self, author, cards, callback_func):
        super().__init__(timeout=60)
        self.author = author
        self.callback_func = callback_func
        options = []
        for card_name in cards:
            card_obj = get_card(card_name)
            desc = card_obj.description[:90] if card_obj else "효과 없음"
            options.append(discord.SelectOption(label=card_name, description=desc, value=card_name))
        self.select = discord.ui.Select(placeholder="카드 선택", options=options[:25])
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인의 카드만 선택할 수 있습니다.", ephemeral=True)
        return False

    async def on_select(self, interaction: discord.Interaction):
        await self.callback_func(interaction, self.select.values[0])
        return True

class RaidBattleView(discord.ui.View):
    def __init__(self, lobby_view, boss: Monster, message=None):
        super().__init__(timeout=600)
        self.lobby = lobby_view
        self.boss = boss
        self.participants = lobby_view.participants
        self.turn = 1
        self.logs = []
        self.selected_cards = {}
        self.shayla_triggers = {uid: False for uid in self.participants}
        self.boss_intent = None
        self.public_message = message
        self.resolve_lock = asyncio.Lock()
        self.finished = False
        self.decide_boss_action()

    def decide_boss_action(self):
        self.boss_intent = self.boss.decide_action()

    def get_status_embed(self):
        embed = discord.Embed(title=f"⚔️ 길드 레이드: {self.boss.name}", color=discord.Color.dark_red())
        p = self.boss.current_hp / self.boss.max_hp
        boss_hp_bar = "🟥" * int(p * 15) + "⬜" * (15 - int(p * 15))
        embed.add_field(name=f"👹 {self.boss.name}", value=f"❤️ {self.boss.current_hp}/{self.boss.max_hp}\n{boss_hp_bar}", inline=False)
        
        intent = f"**{self.boss_intent.name}**" + (" (☄️ 광역)" if self.boss_intent.is_aoe else " (🗡️ 단일)")
        embed.add_field(name="⚠️ 보스 의도", value=intent, inline=False)

        for uid, p in self.participants.items():
            char = p['char']
            st = "✅ 준비완료" if uid in self.selected_cards else "💭 고민중..."
            if char.current_hp <= 0: st = "💀 행동불가"
            embed.add_field(name=f"👤 {p['user'].display_name}", value=f"❤️ {char.current_hp} | {st}", inline=True)
        
        if self.logs:
            log_text = "\n".join(self.logs[-4:])
            if len(log_text) > 1000:
                log_text = "…(앞부분 생략)\n" + log_text[-980:]
            embed.add_field(name="📜 전투 로그", value=log_text, inline=False)
        return embed

    @discord.ui.button(label="🎴 카드 선택", style=discord.ButtonStyle.primary)
    async def btn_pick(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = interaction.user.id
        if uid not in self.participants: return await interaction.response.send_message("참여자가 아닙니다.", ephemeral=True)
        if self.finished: return await interaction.response.send_message("이미 종료된 레이드입니다.", ephemeral=True)
        if self.public_message is None:
            self.public_message = interaction.message
        
        char_info = self.participants[uid]
        if char_info['char'].current_hp <= 0: return await interaction.response.send_message("행동 불가 상태입니다.", ephemeral=True)
        if uid in self.selected_cards: return await interaction.response.send_message("이미 선택했습니다.", ephemeral=True)
        selected_turn = self.turn

        async def cb(i, val):
            should_resolve = False
            async with self.resolve_lock:
                if self.finished:
                    return await i.response.send_message("이미 종료된 레이드입니다.", ephemeral=True)
                if selected_turn != self.turn:
                    return await i.response.send_message("이 선택창은 이전 턴의 것입니다. 다시 선택해주세요.", ephemeral=True)
                if uid in self.selected_cards:
                    return await i.response.send_message("이미 이번 턴의 카드를 선택했습니다.", ephemeral=True)
                self.selected_cards[uid] = val
                alive = [u for u, p in self.participants.items() if p['char'].current_hp > 0]
                should_resolve = all(u in self.selected_cards for u in alive)
            await i.response.send_message(f"👌 **{val}** 선택!", ephemeral=True)
            if should_resolve:
                await self.resolve_turn(i)

        cards = list(getattr(char_info['char'], "equipped_cards", []) or [])
        if not cards:
            return await interaction.response.send_message("선택 가능한 카드가 없습니다.", ephemeral=True)
        view = RaidCardSelectView(interaction.user, cards, cb)
        await interaction.response.send_message("카드를 선택하세요.", view=view, ephemeral=True)

    async def resolve_turn(self, interaction):
        if self.finished:
            return
        self.logs.append(f"--- Turn {self.turn} ---")
        alive = [u for u, p in self.participants.items() if p['char'].current_hp > 0]
        if not alive: return await self.end_raid(interaction, False)

        boss_card = self.boss_intent
        targets = alive if boss_card.is_aoe else [random.choice(alive)]
        
        for uid in alive:
            char = self.participants[uid]['char']
            u_card_name = self.selected_cards[uid]
            u_card = get_card(u_card_name)
            
            boss_res = boss_card.use_card(self.boss.attack, self.boss.defense)
            boss_res = battle_engine.apply_stat_scaling(boss_res, self.boss)
            user_res = u_card.use_card(char.attack, char.defense, char.current_mental)
            user_res = battle_engine.apply_stat_scaling(user_res, char)
            
            u_effs = []
            art = getattr(char, "equipped_artifact", None)
            if art: u_effs.append(art.get("special"))
            
            art_log, next_trig = battle_engine.process_turn_start_artifacts(
                char, self.boss, user_res, boss_res, self.turn, self.shayla_triggers.get(uid, False), u_card_name
            )
            self.shayla_triggers[uid] = next_trig
            if art_log: self.logs.append(art_log)

            is_target = (uid in targets)
            if is_target:
                clash_log, dmg_p, dmg_b = battle_engine.process_clash_loop(char, self.boss, user_res, boss_res, u_effs, [], self.turn)
                self.logs.append(f"⚔️ **{char.name}** vs **보스**" + clash_log)
            else:
                for d in boss_res:
                    if d['type'] == 'attack': d['type'] = 'none'; d['value'] = 0
                clash_log, dmg_p, dmg_b = battle_engine.process_clash_loop(char, self.boss, user_res, boss_res, u_effs, [], self.turn)
                self.logs.append(f"🗡️ **{char.name}** 일방 공격!" + clash_log)

            if char.current_hp <= 0:
                char.current_hp = 0
                self.logs.append(f"💀 **{char.name}** 쓰러짐!")

        if self.boss.current_hp <= 0: return await self.end_raid(interaction, True)
        
        self.turn += 1
        self.selected_cards = {}
        self.decide_boss_action()
        
        if self.public_message:
            try:
                await self.public_message.edit(embed=self.get_status_embed(), view=self)
                return
            except (discord.NotFound, discord.HTTPException):
                self.public_message = None
        self.public_message = await interaction.channel.send(embed=self.get_status_embed(), view=self)

    async def end_raid(self, interaction, win):
        if self.finished:
            return
        self.finished = True
        self.clear_items()
        embed = None
        if win:
            rewards = self.boss.reward_tokens if hasattr(self.boss, 'reward_tokens') else {}
            guild_id = self.lobby.guild_info['guild_id']
            
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    set_c = [f"token_{k} = token_{k} + {v}" for k, v in rewards.items()]
                    if set_c:
                        await cur.execute(f"UPDATE guilds SET {', '.join(set_c)} WHERE guild_id=%s", (guild_id,))
                        await conn.commit()
            
            log_names = []
            for uid, p in self.participants.items():
                p['data']['money'] += 5000
                p['data']['pt'] += 1000
                p['char'].current_hp = p['char'].max_hp
                p['data']['characters'][p['char_idx']] = p['char'].to_dict()
                await save_user_data(uid, p['data'])
                log_names.append(p['user'].display_name)
            
            embed = discord.Embed(title="🎉 토벌 성공!", description=f"보스 **{self.boss.name}** 처치!", color=discord.Color.gold())
            embed.add_field(name="영웅들", value=", ".join(log_names))
        else:
            embed = discord.Embed(title="☠️ 토벌 실패", description="파티가 전멸했습니다...", color=discord.Color.dark_grey())
            for uid, p in self.participants.items():
                p['char'].current_hp = 1 
                p['data']['characters'][p['char_idx']] = p['char'].to_dict()
                await save_user_data(uid, p['data'])

        if self.public_message:
            try:
                await self.public_message.edit(embed=embed, view=None)
            except (discord.NotFound, discord.HTTPException):
                await interaction.channel.send(embed=embed)
        else:
            await interaction.channel.send(embed=embed)
        self.stop()

    async def on_timeout(self):
        if self.finished:
            return
        self.finished = True
        for child in self.children:
            child.disabled = True
        if self.public_message:
            try:
                await self.public_message.edit(content="⏱️ 레이드가 장시간 입력 없이 종료되었습니다.", view=self)
            except (discord.NotFound, discord.HTTPException):
                pass

class RaidLobbyView(discord.ui.View):
    def __init__(self, host, guild_info, boss_data):
        super().__init__(timeout=300)
        self.host = host
        self.guild_info = guild_info
        self.boss_data = boss_data
        self.participants = {}
        self.started = False
        self.state_lock = asyncio.Lock()
        self.public_message = None

    async def add_participant(self, user):
        async with self.state_lock:
            if self.started or user.id in self.participants or len(self.participants) >= 4:
                return False
            user_data = await get_user_data(user.id)
            idx = user_data.get("investigator_index", 0)
            chars = user_data.get("characters", [])
            char = Character.from_dict(chars[idx]) if chars and idx < len(chars) else Character.from_dict({"name": "모험가", "hp": 100, "attack":10, "defense":5})
            
            char.status_effects = {"bleed": 0, "paralysis": 0, "stun": 0}
            char.runtime_cooldowns = {}
            self.participants[user.id] = {"user": user, "char": char, "char_idx": idx, "data": user_data}
            return True

    def get_embed(self):
        embed = discord.Embed(title=f"🛡️ [{self.guild_info['name']}] 레이드 모집", description="같은 길드원만 참여 가능", color=discord.Color.orange())
        members = [f"{i+1}. {p['user'].display_name} (Lv.{p['char'].attack+p['char'].defense})" for i, p in enumerate(self.participants.values())]
        embed.add_field(name=f"파티원 ({len(self.participants)}/4)", value="\n".join(members), inline=False)
        return embed

    @discord.ui.button(label="✋ 참가", style=discord.ButtonStyle.success)
    async def btn_join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.started:
            return await interaction.response.send_message("이미 출발한 레이드입니다.", ephemeral=True)
        u_guild = await get_user_guild_info(interaction.user.id)
        if not u_guild or u_guild['guild_id'] != self.guild_info['guild_id']:
            return await interaction.response.send_message("❌ 같은 길드원이 아닙니다.", ephemeral=True)
        if await self.add_participant(interaction.user): await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else: await interaction.response.send_message("참가 실패 (이미 참가했거나 인원 초과)", ephemeral=True)

    @discord.ui.button(label="🚀 출발", style=discord.ButtonStyle.danger)
    async def btn_start(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host.id: return await interaction.response.send_message("호스트만 시작 가능", ephemeral=True)
        async with self.state_lock:
            if self.started:
                return await interaction.response.send_message("이미 출발한 레이드입니다.", ephemeral=True)
            if len(self.participants) < 2:
                return await interaction.response.send_message("최소 2명 필요", ephemeral=True)
            if not self.boss_data:
                return await interaction.response.send_message("레이드 보스 데이터를 찾지 못했습니다.", ephemeral=True)
            self.started = True

        boss = Monster(self.boss_data['name'], self.boss_data['hp'], self.boss_data['atk'], self.boss_data['def'], card_deck=self.boss_data['deck'])
        boss.reward_tokens = self.boss_data.get('reward_tokens', {})
        boss.status_effects = {"bleed": 0, "paralysis": 0, "stun": 0}
        
        view = RaidBattleView(self, boss, interaction.message)
        await interaction.response.edit_message(content="⚔️ **전투 시작!**", embed=view.get_status_embed(), view=view)

    async def on_timeout(self):
        if self.started:
            return
        for child in self.children:
            child.disabled = True
        if self.public_message:
            try:
                await self.public_message.edit(content="⏱️ 레이드 모집이 종료되었습니다.", view=self)
            except (discord.NotFound, discord.HTTPException):
                pass

# ==================================================================================
# 5. 메인 뷰 (동적 버튼 처리)
# ==================================================================================

class GuildJoinListView(discord.ui.View):
    def __init__(self, author, parent_view):
        super().__init__(timeout=60)
        self.author = author
        self.parent_view = parent_view
        self.page = 0
        self.guilds_per_page = 5

    async def load_and_update(self, interaction):
        guilds = await get_guild_list(self.guilds_per_page, self.page * self.guilds_per_page)
        self.clear_items()
        
        if guilds:
            opts = [discord.SelectOption(label=g['name'], description=f"Lv.{g['level']} | 멤버 {g['member_count']}명", value=str(g['guild_id'])) for g in guilds]
            sel = discord.ui.Select(placeholder="가입할 길드 선택", options=opts)
            sel.callback = self.on_select
            self.add_item(sel)

        self.add_item(Button(label="이전", disabled=(self.page==0), custom_id="prev"))
        self.add_item(Button(label="다음", disabled=(len(guilds)<self.guilds_per_page), custom_id="next"))
        
        desc = "\n".join([f"**{g['name']}** (ID: {g['guild_id']}) - Lv.{g['level']}" for g in guilds]) if guilds else "생성된 길드가 없습니다."
        embed = discord.Embed(title="📜 길드 목록", description=desc, color=discord.Color.blue())
        
        if interaction.response.is_done(): await interaction.edit_original_response(embed=embed, view=self)
        else: await interaction.response.send_message(embed=embed, view=self, ephemeral=True)

    async def on_select(self, interaction):
        try: gid = int(interaction.data["values"][0])
        except: return
        suc, msg = await join_guild_by_id(self.author.id, gid)
        if suc: 
            await interaction.response.send_message(f"✅ {msg}", ephemeral=True)
            await self.parent_view.refresh_ui(interaction)
        else: await interaction.response.send_message(f"❌ {msg}", ephemeral=True)

class GuildMainView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def get_embed(self, user_id, user_name):
        guild_info = await get_user_guild_info(user_id)
        self.clear_items()
        if not guild_info:
            return discord.Embed(
                title="🛡️ 공용 길드",
                description="길드 정보를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.",
                color=discord.Color.red(),
            )
        self.add_item(self.btn_mission)
        self.add_item(self.btn_warehouse)
        self.add_item(self.btn_raid)
        self.add_item(self.btn_manage)

        g = guild_info
        embed = discord.Embed(
            title=f"🛡️ {g['name']}",
            description=(
                "모든 조사원이 함께 성장시키는 공용 길드입니다.\n"
                f"등급: {RANK_NAMES.get(g['level'], 'Bronze')}\n"
                f"개인 공헌도: {g.get('contribution', 0):,}"
            ),
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="🏗️ 공용 자원",
            value=(
                f"🌲 {g['token_wood']:,} | ⛓️ {g['token_iron']:,} | "
                f"🔮 {g['token_magic']:,} | 🧿 {g['token_sorcery']:,}"
            ),
            inline=False,
        )
        embed.set_footer(text="생성·검색·탈퇴 없이 모든 이용자가 자동 소속됩니다.")
        return embed

    # --- 버튼 정의 (초기엔 모두 정의해두고 get_embed에서 add_item으로 선택적 추가) ---
    
    # [미가입용]
    @discord.ui.button(label="📝 가입", style=discord.ButtonStyle.primary, custom_id="guild_btn_join_create")
    async def btn_join_create(self, interaction: discord.Interaction, button: discord.ui.Button):
        await GuildJoinListView(interaction.user, self).load_and_update(interaction)

    @discord.ui.button(label="✨ 생성", style=discord.ButtonStyle.success, custom_id="guild_btn_create")
    async def btn_create(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(GuildCreateModal(self))

    # [가입자용]
    @discord.ui.button(label="🎯 미션", style=discord.ButtonStyle.success, custom_id="guild_btn_mission")
    async def btn_mission(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_info = await get_user_guild_info(interaction.user.id)
        if not guild_info: return
        view = GuildMissionView(interaction.user, guild_info)
        await interaction.response.send_message(embed=await view.get_embed(), view=view, ephemeral=True)

    @discord.ui.button(label="📦 창고", style=discord.ButtonStyle.secondary, custom_id="guild_btn_warehouse")
    async def btn_warehouse(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_info = await get_user_guild_info(interaction.user.id)
        if not guild_info: return
        view = GuildWarehouseView(interaction.user, guild_info)
        await interaction.response.send_message(embed=await view.get_embed(), view=view, ephemeral=True)

    @discord.ui.button(label="⚔️ 레이드", style=discord.ButtonStyle.danger, custom_id="guild_btn_raid")
    async def btn_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_info = await get_user_guild_info(interaction.user.id)
        if not guild_info: return
        boss_rank = RANK_NAMES.get(guild_info['level'], "Bronze")
        boss_data = RAID_BOSS_DATA.get(boss_rank) or RAID_BOSS_DATA.get("Gold")
        if not boss_data:
            return await interaction.response.send_message("레이드 보스 데이터를 찾지 못했습니다.", ephemeral=True)
        lobby = RaidLobbyView(interaction.user, guild_info, boss_data)
        await lobby.add_participant(interaction.user)
        await interaction.response.send_message(embed=lobby.get_embed(), view=lobby)
        try:
            lobby.public_message = await interaction.original_response()
        except (discord.NotFound, discord.HTTPException):
            pass
    
    @discord.ui.button(label="⚖️ 물자 관리", style=discord.ButtonStyle.secondary, custom_id="guild_btn_manage")
    async def btn_manage(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_info = await get_user_guild_info(interaction.user.id)
        if not guild_info: return
        view = InventoryManageView(interaction.user, guild_info)
        await view.setup_view()
        await interaction.response.send_message("📥 **자재 납품** 모드입니다.", view=view, ephemeral=True)

    async def refresh_ui(self, interaction):
        embed = await self.get_embed(interaction.user.id, interaction.user.display_name)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

class GuildCreateModal(Modal, title="길드 생성"):
    name = TextInput(label="이름", min_length=2)
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view
    async def on_submit(self, interaction: discord.Interaction):
        suc, msg = await create_guild(interaction.user.id, self.name.value)
        if suc: 
            await interaction.response.send_message(msg, ephemeral=True)
            await self.parent_view.refresh_ui(interaction)
        else: await interaction.response.send_message(msg, ephemeral=True)
