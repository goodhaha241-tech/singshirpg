import discord
# completion-v6 command routes
from discord import app_commands
from discord.ext import commands
from datetime import date
import logging

logger = logging.getLogger(__name__)

# [DB 및 데이터 매니저]
from data_manager import get_db_pool, get_user_data, save_user_data
from decorators import auto_defer

# [각 기능별 View 임포트]
from myhome import MyHomeView
from investigation import InvestigationView
from shop import ShopView
from trade import CafeView
from crafting import CraftView
from subjugation import SubjugationRegionView
from guild import GuildMainView, RaidBattleView
from recruitment import RecruitSelectView
from use_item import ItemUseView
from card_manager import CardManageView
from pvp import PVPInviteView
from info import InfoView
from story import MainStoryView
from monsters import get_raid_boss
from life_overhaul_v5 import LifeHubView
from artifact_overhaul_v5 import ArtifactHubView
from gem_manager import GemManagerView
from progression_system_v6 import claim_attendance

# ==============================================================================
# 1. 상태 메뉴 View (정보, 사용, 카드, 정비)
# ==============================================================================
class StatusMenuView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func

    @discord.ui.button(label="정보", style=discord.ButtonStyle.primary, emoji="📜")
    @auto_defer(reload_data=True)
    async def info_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        char_list = self.user_data.get("characters", [])
        idx = self.user_data.get("investigator_index", 0)
        if idx >= len(char_list): idx = 0
        main_char = char_list[idx] if char_list else {"name": "알 수 없음", "hp": 0, "max_mental": 0}

        embed = discord.Embed(title=f"📜 {self.author.display_name}님의 정보", color=discord.Color.blue())
        embed.add_field(name="💰 재화", value=f"{self.user_data['money']:,}원", inline=True)
        embed.add_field(name="⚡ 포인트", value=f"{self.user_data['pt']:,}pt", inline=True)
        embed.add_field(name="🗡️ 대표 캐릭터", value=f"{main_char.get('name')} (Lv.{main_char.get('level', 0)})", inline=False)
        stats = f"HP: {main_char.get('hp')} | 멘탈: {main_char.get('max_mental')}\n공격: {main_char.get('attack')} | 방어: {main_char.get('defense')}"
        embed.add_field(name="스탯 정보", value=stats, inline=False)
        
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="사용", style=discord.ButtonStyle.secondary, emoji="🎒")
    @auto_defer(reload_data=True)
    async def use_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ItemUseView(self.author, self.user_data, self.save_func)
        embed = discord.Embed(title="🎒 아이템 사용", description="사용할 아이템을 선택하세요.", color=discord.Color.blue())
        await interaction.edit_original_response(content=None, embed=embed, view=view)

    @discord.ui.button(label="카드", style=discord.ButtonStyle.secondary, emoji="🃏")
    @auto_defer(reload_data=True)
    async def card_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = CardManageView(self.author, self.user_data, self.save_func, char_index=0)
        await interaction.edit_original_response(content=None, embed=view.create_embed(), view=view)

    @discord.ui.button(label="정비(마이홈)", style=discord.ButtonStyle.success, emoji="🏡")
    @auto_defer(reload_data=True)
    async def myhome_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = MyHomeView(self.author, self.user_data, self.save_func)
        await interaction.edit_original_response(content=None, embed=view.get_embed(), view=view)

# ==============================================================================
# 2. 외출 메뉴 View (조사, 대련, 던전, 카페)
# ==============================================================================
class OutingMenuView(discord.ui.View):
    def __init__(self, author=None, user_data=None, save_func=None, timeout=600):
        super().__init__(timeout=timeout)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func

    @discord.ui.button(label="조사", style=discord.ButtonStyle.danger, emoji="🔍", custom_id="menu:outing:invest")
    @auto_defer(reload_data=True)
    async def invest_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = InvestigationView(self.author, self.user_data, self.save_func)
        await interaction.edit_original_response(content=None, embed=view.get_embed(), view=view)

    @discord.ui.button(label="대련", style=discord.ButtonStyle.primary, emoji="⚔️", custom_id="menu:outing:pvp")
    @auto_defer(reload_data=True)
    async def pvp_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PVPInviteView(self.author, get_user_data, save_user_data)
        embed = discord.Embed(title="⚔️ 대련", description="대련 상대를 선택해주세요.", color=discord.Color.red())
        await interaction.edit_original_response(content=None, embed=embed, view=view)

    @discord.ui.button(label="던전", style=discord.ButtonStyle.danger, emoji="🏰", custom_id="menu:outing:dungeon")
    @auto_defer(reload_data=True)
    async def subjugation_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = SubjugationRegionView(self.author, self.user_data, self.save_func)
        embed = discord.Embed(title="🏰 던전", description="향할 던전이 있는 지역을 선택하세요.", color=discord.Color.dark_red())
        await interaction.edit_original_response(content=None, embed=embed, view=view)

    @discord.ui.button(label="카페", style=discord.ButtonStyle.success, emoji="☕", custom_id="menu:outing:cafe")
    @auto_defer(reload_data=True)
    async def cafe_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = CafeView(self.author, self.user_data, get_user_data, self.save_func)
        embed = discord.Embed(title="☕ 카페", description="카페에 오신 것을 환영합니다.", color=discord.Color.gold())
        await interaction.edit_original_response(content=None, embed=embed, view=view)

    @discord.ui.button(label="길드", style=discord.ButtonStyle.primary, emoji="🛡️", custom_id="menu:outing:guild")
    @auto_defer(reload_data=True)
    async def guild_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # [수정] 인자 없이 초기화
        view = GuildMainView() 
        embed = await view.get_embed(interaction.user.id, interaction.user.display_name)
        await interaction.edit_original_response(content=None, embed=embed, view=view)

# ==============================================================================
# 3. 관리 메뉴 View (상점, 제작, 스토리, 영입)
# ==============================================================================
class ManagementMenuView(discord.ui.View):
    def __init__(self, author=None, user_data=None, save_func=None, timeout=600):
        super().__init__(timeout=timeout)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func

    @discord.ui.button(label="상점", style=discord.ButtonStyle.primary, emoji="🛒", custom_id="menu:manage:shop")
    @auto_defer(reload_data=True)
    async def shop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ShopView(self.author, self.user_data, self.save_func)
        await interaction.edit_original_response(content=None, embed=view.get_embed(), view=view)

    @discord.ui.button(label="제작", style=discord.ButtonStyle.secondary, emoji="⚒️", custom_id="menu:manage:craft")
    @auto_defer(reload_data=True)
    async def craft_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = CraftView(self.author, self.user_data, self.save_func)
        embed = discord.Embed(title="⚒️ 제작", description="제작할 아이템의 지역을 선택하세요.", color=discord.Color.orange())
        await interaction.edit_original_response(content=None, embed=embed, view=view)

    @discord.ui.button(label="스토리", style=discord.ButtonStyle.secondary, emoji="📖", custom_id="menu:manage:story")
    @auto_defer(reload_data=True)
    async def story_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = MainStoryView(self.author, self.user_data, self.save_func)
        await interaction.edit_original_response(content=None, embed=view.create_story_embed(), view=view)

    @discord.ui.button(label="영입", style=discord.ButtonStyle.success, emoji="🤝", custom_id="menu:manage:recruit")
    @auto_defer(reload_data=True)
    async def recruit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        
        async def back_callback(i):
            if not i.response.is_done():
                await i.response.defer()
            view = ManagementMenuView(self.author, self.user_data, self.save_func)
            embed = discord.Embed(title="🛠️ 관리 메뉴", description="수행할 작업을 선택해주세요.", color=discord.Color.blue())
            await i.edit_original_response(content=None, embed=embed, view=view)

        view = RecruitSelectView(self.author, self.user_data, self.save_func, back_callback)
        embed = discord.Embed(title="🕵️ 영입소", description="함께할 동료를 찾아보세요.", color=discord.Color.blue())
        await interaction.edit_original_response(content=None, embed=embed, view=view)


# ==============================================================================
# 메인 Cog 클래스
# ==============================================================================
class RPGCommands(commands.Cog):
    admin = app_commands.Group(name="관리자", description="관리자 전용 명령어입니다.", guild_only=True)

    def __init__(self, bot):
        self.bot = bot

    async def save_wrapper(self, user_id, user_data):
        await save_user_data(user_id, user_data)

    # ---------------------------------------------------------------------
    # 1. 상태 커맨드
    # ---------------------------------------------------------------------
    @app_commands.command(name="상태", description="[메뉴] 정보, 사용, 카드, 정비 기능을 엽니다.")
    async def status_menu(self, interaction: discord.Interaction):
        try: await interaction.response.defer(ephemeral=False)
        except: return
        user_data = await get_user_data(interaction.user.id, interaction.user.display_name)
        async def bound_save(uid_or_all, data=None):
            if data is None: await self.save_wrapper(interaction.user.id, user_data)
            else: await self.save_wrapper(uid_or_all, data)
        view = InfoView(interaction.user, user_data, bound_save)
        await interaction.followup.send(embed=view.create_status_embed(), view=view)

    # ---------------------------------------------------------------------
    # 2. 외출 커맨드
    # ---------------------------------------------------------------------
    @app_commands.command(name="외출", description="[메뉴] 조사, 대련, 던전, 카페 기능을 엽니다.")
    async def outing_menu(self, interaction: discord.Interaction):
        try: await interaction.response.defer(ephemeral=False)
        except: return
        user_data = await get_user_data(interaction.user.id, interaction.user.display_name)
        async def bound_save(uid_or_all, data=None):
            if data is None: await self.save_wrapper(interaction.user.id, user_data)
            else: await self.save_wrapper(uid_or_all, data)
        view = OutingMenuView(interaction.user, user_data, bound_save)
        embed = discord.Embed(title="🚀 외출 메뉴", description="어디로 떠나시겠습니까?", color=discord.Color.red())
        await interaction.followup.send(embed=embed, view=view)

    # ---------------------------------------------------------------------
    # 3. 관리 커맨드
    # ---------------------------------------------------------------------
    @app_commands.command(name="관리", description="[메뉴] 상점, 제작, 스토리, 영입 기능을 엽니다.")
    async def manage_menu(self, interaction: discord.Interaction):
        try: await interaction.response.defer(ephemeral=False)
        except: return
        user_data = await get_user_data(interaction.user.id, interaction.user.display_name)
        async def bound_save(uid_or_all, data=None):
            if data is None: await self.save_wrapper(interaction.user.id, user_data)
            else: await self.save_wrapper(uid_or_all, data)
        view = ManagementMenuView(interaction.user, user_data, bound_save)
        embed = discord.Embed(title="🛠️ 관리 메뉴", description="수행할 작업을 선택해주세요.", color=discord.Color.blue())
        await interaction.followup.send(embed=embed, view=view)

    # ---------------------------------------------------------------------
    # 4. 출석
    # ---------------------------------------------------------------------
    @app_commands.command(name="출석", description="매일 접속 보상을 받습니다.")
    async def checkin_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        user_data = await get_user_data(interaction.user.id, interaction.user.display_name)
        ok, message = claim_attendance(user_data)
        if not ok:
            return await interaction.followup.send(message, ephemeral=True)
        await save_user_data(interaction.user.id, user_data)
        embed = discord.Embed(title="📅 출석 완료!", description=message, color=discord.Color.green())
        await interaction.followup.send(embed=embed)

    # ---------------------------------------------------------------------
    # 5. 단축 커맨드
    # ---------------------------------------------------------------------
    async def _open_feature(self, interaction, view_class, title=None, desc=None, color=None):
        try: await interaction.response.defer(ephemeral=False)
        except: pass
        user_data = await get_user_data(interaction.user.id, interaction.user.display_name)
        async def bound_save(uid_or_all, data=None):
            if data is None: await self.save_wrapper(interaction.user.id, user_data)
            else: await self.save_wrapper(uid_or_all, data)
        view = view_class(interaction.user, user_data, bound_save)
        if view_class is LifeHubView:
            # 최초 생활 허브 진입 보급과 v6 기본값을 즉시 영구 저장한다.
            await bound_save(interaction.user.id, user_data)
        embed = None
        if hasattr(view, 'get_embed'): embed = view.get_embed()
        elif hasattr(view, 'create_shop_embed'): embed = view.create_shop_embed()
        if not embed and title: embed = discord.Embed(title=title, description=desc, color=color)
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="마이홈", description="마이홈 관리 화면을 엽니다.")
    async def shortcut_myhome(self, interaction: discord.Interaction):
        await self._open_feature(interaction, MyHomeView)

    @app_commands.command(name="생활", description="생활 관리 허브를 엽니다.")
    async def shortcut_life(self, interaction: discord.Interaction):
        await self._open_feature(interaction, LifeHubView)

    @app_commands.command(name="조사", description="[단축] 조사 지역 선택 화면으로 이동합니다.")
    async def shortcut_invest(self, interaction: discord.Interaction):
        await self._open_feature(interaction, InvestigationView)

    @app_commands.command(name="던전", description="[단축] 던전 지역 선택 화면으로 이동합니다.")
    async def shortcut_dungeon(self, interaction: discord.Interaction):
        await self._open_feature(interaction, SubjugationRegionView, "🏰 던전", "향할 던전이 있는 지역을 선택하세요.", discord.Color.dark_red())

    @app_commands.command(name="상점", description="[단축] 상점으로 이동합니다.")
    async def shortcut_shop(self, interaction: discord.Interaction):
        await self._open_feature(interaction, ShopView)

    @app_commands.command(name="제작", description="[단축] 제작소로 이동합니다.")
    async def shortcut_craft(self, interaction: discord.Interaction):
        await self._open_feature(interaction, CraftView, "⚒️ 제작", "제작할 아이템의 지역을 선택하세요.", discord.Color.orange())

    @app_commands.command(name="길드", description="[단축] 길드 화면으로 이동합니다.")
    async def shortcut_guild(self, interaction: discord.Interaction):
        # [수정] _open_feature 대신 직접 처리 (인자 구조 차이)
        try: await interaction.response.defer(ephemeral=False)
        except: pass
        view = GuildMainView()
        embed = await view.get_embed(interaction.user.id, interaction.user.display_name)
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="대련", description="[단축] 대련 상대를 선택합니다.")
    async def shortcut_pvp(self, interaction: discord.Interaction):
        try: await interaction.response.defer(ephemeral=False)
        except: pass
        view = PVPInviteView(interaction.user, get_user_data, save_user_data)
        embed = discord.Embed(title="⚔️ 대련", description="대련 상대를 선택해주세요.", color=discord.Color.red())
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="카페", description="[단축] 카페로 이동합니다.")
    async def shortcut_cafe(self, interaction: discord.Interaction):
        try: await interaction.response.defer(ephemeral=False)
        except: pass
        user_data = await get_user_data(interaction.user.id, interaction.user.display_name)
        async def bound_save(uid_or_all, data=None):
            if data is None: await self.save_wrapper(interaction.user.id, user_data)
            else: await self.save_wrapper(uid_or_all, data)
        view = CafeView(interaction.user, user_data, get_user_data, bound_save)
        embed = discord.Embed(title="☕ 카페", description="카페에 오신 것을 환영합니다.", color=discord.Color.gold())
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="영입", description="[단축] 영입소로 이동합니다.")
    async def shortcut_recruit(self, interaction: discord.Interaction):
        try: await interaction.response.defer(ephemeral=False)
        except: pass
        user_data = await get_user_data(interaction.user.id, interaction.user.display_name)
        async def bound_save(uid_or_all, data=None):
            if data is None: await self.save_wrapper(interaction.user.id, user_data)
            else: await self.save_wrapper(uid_or_all, data)
        async def back_callback(i):
            await i.response.edit_message(content="영입소를 나갔습니다.", embed=None, view=None)
        view = RecruitSelectView(interaction.user, user_data, bound_save, back_callback)
        embed = discord.Embed(title="🕵️ 영입소", description="함께할 동료를 찾아보세요.", color=discord.Color.blue())
        await interaction.followup.send(embed=embed, view=view)

    # ---------------------------------------------------------------------
    # 6. 관리자 커맨드
    # ---------------------------------------------------------------------
    @admin.command(name="지급", description="[관리자] 특정 유저에게 재화를 지급합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(currency=[
        app_commands.Choice(name="돈", value="money"),
        app_commands.Choice(name="포인트", value="pt"),
    ])
    async def admin_give_currency(self, interaction: discord.Interaction, target: discord.User, currency: str, amount: int):
        await interaction.response.defer(ephemeral=False)
        target_data = await get_user_data(target.id, target.display_name)
        target_data[currency] = target_data.get(currency, 0) + amount
        await save_user_data(target.id, target_data)
        unit = "원" if currency == "money" else "pt"
        embed = discord.Embed(title="✅ 관리자 지급 완료", description=f"**{target.display_name}**님에게 재화를 지급했습니다.", color=discord.Color.gold())
        embed.add_field(name="지급액", value=f"{amount:,}{unit}", inline=False)
        await interaction.followup.send(embed=embed)

    @admin.command(name="전체즉시완료", description="[관리자] 모든 유저의 작물 성장 및 물고기 해체를 즉시 완료시킵니다.")
    @app_commands.checks.has_permissions(administrator=True)
    async def admin_complete_all(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE garden_slots SET stage = 3 WHERE planted = TRUE")
                await cur.execute("UPDATE fishing_slots SET start_count = start_count - 1000")
                await conn.commit()
        embed = discord.Embed(title="✅ 전체 즉시 완료 처리", description="모든 유저의 작물과 물고기 해체가 즉시 완료 상태로 변경되었습니다.", color=discord.Color.gold())
        await interaction.followup.send(embed=embed)

    @admin.command(name="길드설정", description="[관리자] 길드 등급을 설정하고 가입 처리합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(rank=[
        app_commands.Choice(name="Bronze", value="Bronze"),
        app_commands.Choice(name="Silver", value="Silver"),
        app_commands.Choice(name="Gold", value="Gold"),
        app_commands.Choice(name="Platinum", value="Platinum"),
        app_commands.Choice(name="Diamond", value="Diamond"),
        app_commands.Choice(name="미가입 (초기화)", value="None")
    ])
    async def admin_set_guild_rank(self, interaction: discord.Interaction, rank: str):
        await interaction.response.defer(ephemeral=True)
        user_data = await get_user_data(interaction.user.id, interaction.user.display_name)
        if rank == "None":
            user_data["guild_rank"] = None
            user_data["guild_data"] = {}
            msg = "✅ 길드 정보를 초기화했습니다. (미가입 상태)"
        else:
            user_data["guild_rank"] = rank
            if "guild_data" not in user_data or not isinstance(user_data["guild_data"], dict) or not user_data["guild_data"]:
                user_data["guild_data"] = {
                    "tokens": {"wood": 100, "iron": 100, "magic": 100, "sorcery": 100},
                    "activities": {"process": 0, "refine": 0, "delivery": 0, "host_coop": 0, "join_coop": 0, "shop_soldout": 0},
                    "daily_delivery": {"date": "", "done": False, "items": {}},
                    "daily_shop": {"date": "", "stock": {}}
                }
            else:
                tokens = user_data["guild_data"].setdefault("tokens", {})
                for t in ["wood", "iron", "magic", "sorcery"]:
                    tokens[t] = max(tokens.get(t, 0), 100)
            msg = f"✅ 길드 등급을 **{rank}**로 설정했습니다. (테스트용 토큰 100개씩 지급됨)"
        await save_user_data(interaction.user.id, user_data)
        await interaction.followup.send(msg)

    @admin.command(name="모의레이드", description="[관리자] 선택한 등급의 레이드를 즉시 시작합니다 (1인 모의전).")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(rank=[
        app_commands.Choice(name="Gold", value="Gold"),
        app_commands.Choice(name="Platinum", value="Platinum"),
        app_commands.Choice(name="Diamond", value="Diamond"),
    ])
    async def admin_mock_raid(self, interaction: discord.Interaction, rank: str):
        await interaction.response.defer(ephemeral=False)
        user_data = await get_user_data(interaction.user.id, interaction.user.display_name)
        members = {interaction.user.id: {"user": interaction.user, "data": user_data, "ready": True}}
        boss = get_raid_boss(rank)
        battle_view = RaidBattleView(members, boss, self.save_wrapper, rank)
        msg = await interaction.followup.send(content="⚔️ **모의 레이드 전투 시작!**", embed=battle_view.get_embed(), view=battle_view)
        battle_view.message = msg

async def setup(bot):
    await bot.add_cog(RPGCommands(bot))
