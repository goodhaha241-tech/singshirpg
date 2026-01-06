import discord
from discord import app_commands
from discord.ext import commands
from datetime import date
import logging

# [DB 및 데이터 매니저]
from data_manager import get_db_pool, get_user_data, save_user_data

# [각 기능별 View 임포트]
# 파일이 없거나 이름이 다를 경우 에러가 날 수 있으니 파일명을 확인해주세요.
from myhome import MyHomeView
from investigation import InvestigationView
from shop import ShopView
from trade import CafeView              # 카페
from crafting import CraftView          # 제작
from subjugation import SubjugationRegionView # 토벌
from recruitment import RecruitSelectView # 영입
from use_item import ItemUseView        # 사용 (아이템 사용)
from card_manager import CardManageView # 카드
from pvp import PVPInviteView           # 대련
from info import InfoView               # [수정] InfoView 임포트 추가
from story import MainStoryView         # [수정] MainStoryView 임포트 추가

# 로깅 설정
logger = logging.getLogger("RPGCommands")

# ==============================================================================
# 1. 상태 메뉴 View (정보, 사용, 카드, 정비)
# ==============================================================================
class StatusMenuView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.fake_all_data = {str(author.id): user_data} # 기존 코드 호환용

    @discord.ui.button(label="정보", style=discord.ButtonStyle.primary, emoji="📜")
    async def info_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author: return
        
        # 정보 임베드 생성
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
        
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="사용", style=discord.ButtonStyle.secondary, emoji="🎒")
    async def use_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author: return
        view = ItemUseView(self.author, self.user_data, self.fake_all_data, self.save_func)
        embed = discord.Embed(title="🎒 아이템 사용", description="사용할 아이템을 선택하세요.", color=discord.Color.blue())
        await interaction.response.edit_message(content=None, embed=embed, view=view)

    @discord.ui.button(label="카드", style=discord.ButtonStyle.secondary, emoji="🃏")
    async def card_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author: return
        # 카드 관리는 캐릭터 인덱스 0번(대표) 기준으로 엽니다.
        view = CardManageView(self.author, self.user_data, self.fake_all_data, self.save_func, char_index=0)
        await interaction.response.edit_message(content=None, embed=view.create_embed(), view=view)

    @discord.ui.button(label="정비(마이홈)", style=discord.ButtonStyle.success, emoji="🏡")
    async def myhome_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author: return
        view = MyHomeView(self.author, self.user_data, self.fake_all_data, self.save_func)
        await interaction.response.edit_message(content=None, embed=view.get_embed(), view=view)

# ==============================================================================
# 2. 외출 메뉴 View (조사, 대련, 토벌, 카페)
# ==============================================================================
class OutingMenuView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.fake_all_data = {str(author.id): user_data}

    @discord.ui.button(label="조사", style=discord.ButtonStyle.danger, emoji="🔍")
    async def invest_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author: return
        view = InvestigationView(self.author, self.user_data, self.fake_all_data, self.save_func)
        await interaction.response.edit_message(content=None, embed=view.get_embed(), view=view)

    @discord.ui.button(label="대련", style=discord.ButtonStyle.primary, emoji="⚔️")
    async def pvp_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author: return
        # PVP는 상대방 데이터를 로드해야 하므로 load_func(get_user_data)를 넘겨줍니다.
        view = PVPInviteView(self.author, get_user_data, save_user_data)
        embed = discord.Embed(title="⚔️ 대련", description="대련 상대를 선택해주세요.", color=discord.Color.red())
        await interaction.response.edit_message(content=None, embed=embed, view=view)

    @discord.ui.button(label="토벌", style=discord.ButtonStyle.danger, emoji="👹")
    async def subjugation_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author: return
        view = SubjugationRegionView(self.author, self.user_data, self.fake_all_data, self.save_func)
        embed = discord.Embed(title="👹 토벌", description="토벌할 지역을 선택하세요.", color=discord.Color.dark_red())
        await interaction.response.edit_message(content=None, embed=embed, view=view)

    @discord.ui.button(label="카페", style=discord.ButtonStyle.success, emoji="☕")
    async def cafe_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author: return
        view = CafeView(self.author, self.user_data, get_user_data, self.save_func)
        embed = discord.Embed(title="☕ 카페", description="카페에 오신 것을 환영합니다.", color=discord.Color.gold())
        await interaction.response.edit_message(content=None, embed=embed, view=view)

# ==============================================================================
# 3. 관리 메뉴 View (상점, 제작, 스토리, 영입)
# ==============================================================================
class ManagementMenuView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.fake_all_data = {str(author.id): user_data}

    @discord.ui.button(label="상점", style=discord.ButtonStyle.primary, emoji="🛒")
    async def shop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author: return
        view = ShopView(self.author, self.user_data, self.fake_all_data, self.save_func)
        await interaction.response.edit_message(content=None, embed=view.get_embed(), view=view)

    @discord.ui.button(label="제작", style=discord.ButtonStyle.secondary, emoji="⚒️")
    async def craft_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author: return
        view = CraftView(self.author, self.user_data, self.fake_all_data, self.save_func)
        embed = discord.Embed(title="⚒️ 제작", description="제작할 아이템의 지역을 선택하세요.", color=discord.Color.orange())
        await interaction.response.edit_message(content=None, embed=embed, view=view)

    @discord.ui.button(label="스토리", style=discord.ButtonStyle.secondary, emoji="📖")
    async def story_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author: return
        
        view = MainStoryView(self.author, self.user_data, self.fake_all_data, self.save_func)
        await interaction.response.edit_message(content=None, embed=view.create_story_embed(), view=view)

    @discord.ui.button(label="영입", style=discord.ButtonStyle.success, emoji="🤝")
    async def recruit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author: return
        
        async def back_callback(i):
            view = ManagementMenuView(self.author, self.user_data, self.save_func)
            embed = discord.Embed(title="🛠️ 관리 메뉴", description="수행할 작업을 선택해주세요.", color=discord.Color.blue())
            await i.response.edit_message(content=None, embed=embed, view=view)

        view = RecruitSelectView(self.author, self.user_data, self.fake_all_data, self.save_func, back_callback)
        embed = discord.Embed(title="🕵️ 영입소", description="함께할 동료를 찾아보세요.", color=discord.Color.blue())
        await interaction.response.edit_message(content=None, embed=embed, view=view)


# ==============================================================================
# 메인 Cog 클래스
# ==============================================================================
class RPGCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def save_wrapper(self, user_id, user_data):
        """View에서 호출할 DB 저장 래퍼 함수"""
        await save_user_data(user_id, user_data)

    # ---------------------------------------------------------------------
    # 1. 상태 커맨드 (정보, 사용, 카드, 정비)
    # ---------------------------------------------------------------------
    @app_commands.command(name="상태", description="[메뉴] 정보, 사용, 카드, 정비 기능을 엽니다.")
    async def status_menu(self, interaction: discord.Interaction):
        user_data = await get_user_data(interaction.user.id, interaction.user.display_name)
        
        # 래퍼 함수 (user_id 고정)
        async def bound_save(data_ignored):
            await self.save_wrapper(interaction.user.id, user_data)
            
        # [수정] StatusMenuView 대신 InfoView를 바로 호출하여 상세 정보를 표시
        # InfoView에 메뉴 버튼들이 통합되었습니다.
        view = InfoView(interaction.user, user_data, {str(interaction.user.id): user_data}, bound_save)
        
        await interaction.response.send_message(embed=view.create_status_embed(), view=view, ephemeral=False)

    # ---------------------------------------------------------------------
    # 2. 외출 커맨드 (조사, 대련, 토벌, 카페)
    # ---------------------------------------------------------------------
    @app_commands.command(name="외출", description="[메뉴] 조사, 대련, 토벌, 카페 기능을 엽니다.")
    async def outing_menu(self, interaction: discord.Interaction):
        user_data = await get_user_data(interaction.user.id, interaction.user.display_name)
        
        async def bound_save(data_ignored):
            await self.save_wrapper(interaction.user.id, user_data)

        view = OutingMenuView(interaction.user, user_data, bound_save)
        
        embed = discord.Embed(title="🚀 외출 메뉴", description="어디로 떠나시겠습니까?", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    # ---------------------------------------------------------------------
    # 3. 관리 커맨드 (상점, 제작, 스토리, 영입)
    # ---------------------------------------------------------------------
    @app_commands.command(name="관리", description="[메뉴] 상점, 제작, 스토리, 영입 기능을 엽니다.")
    async def manage_menu(self, interaction: discord.Interaction):
        user_data = await get_user_data(interaction.user.id, interaction.user.display_name)
        
        async def bound_save(data_ignored):
            await self.save_wrapper(interaction.user.id, user_data)

        view = ManagementMenuView(interaction.user, user_data, bound_save)
        
        embed = discord.Embed(title="🛠️ 관리 메뉴", description="수행할 작업을 선택해주세요.", color=discord.Color.blue())
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    # ---------------------------------------------------------------------
    # 4. 출석 (독립 커맨드)
    # ---------------------------------------------------------------------
    @app_commands.command(name="출석", description="매일 접속 보상을 받습니다.")
    async def checkin_cmd(self, interaction: discord.Interaction):
        user_data = await get_user_data(interaction.user.id, interaction.user.display_name)
        
        last_date_str = user_data.get("last_checkin")
        today_str = str(date.today())
        
        if last_date_str == today_str:
            embed = discord.Embed(title="✅ 출석 완료", description="오늘은 이미 출석을 완료했습니다.", color=discord.Color.red())
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        
        reward_money = 3000
        reward_pt = 10
        
        user_data["money"] += reward_money
        user_data["pt"] += reward_pt
        user_data["last_checkin"] = today_str
        
        await save_user_data(interaction.user.id, user_data)
        
        embed = discord.Embed(title="📅 출석 완료!", description=f"오늘의 보상을 수령했습니다.", color=discord.Color.green())
        embed.add_field(name="💰 머니", value=f"+{reward_money:,}원", inline=True)
        embed.add_field(name="⚡ 포인트", value=f"+{reward_pt:,}pt", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    # (관리자용 커맨드는 유지)
    @app_commands.command(name="관리자_지급", description="[관리자] 특정 유저에게 재화를 지급합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    async def admin_give_money(self, interaction: discord.Interaction, target: discord.User, amount: int):
        target_data = await get_user_data(target.id, target.display_name)
        target_data["money"] += amount
        await save_user_data(target.id, target_data)
        embed = discord.Embed(title="✅ 관리자 지급 완료", description=f"**{target.display_name}**님에게 재화를 지급했습니다.", color=discord.Color.gold())
        embed.add_field(name="지급액", value=f"{amount:,}원", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="리로드", description="[관리자] 봇의 기능 모듈을 다시 로드합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    async def reload_modules(self, interaction: discord.Interaction):
        """봇의 기능 모듈(cogs)을 다시 로드하여 코드 변경사항을 적용합니다."""
        extensions_to_reload = ["rpg_commands"] # 리로드할 확장 기능 목록
        reloaded_extensions = []
        failed_extensions = {}

        for extension in extensions_to_reload:
            try:
                await self.bot.reload_extension(extension)
                reloaded_extensions.append(extension)
            except Exception as e:
                logger.error(f"🔄 '{extension}' 리로드 실패: {e}")
                failed_extensions[extension] = str(e)

        # 커맨드 트리 동기화
        try:
            synced = await self.bot.tree.sync()
            sync_message = f"🔄 {len(synced)}개의 슬래시 커맨드 동기화 완료"
            logger.info(sync_message)
        except Exception as e:
            sync_message = f"❌ 커맨드 동기화 실패: {e}"
            logger.error(sync_message)

        # 결과 메시지 생성
        if not failed_extensions:
            embed = discord.Embed(title="✅ 모듈 리로드 성공", description=f"다음 모듈을 성공적으로 다시 불러왔습니다:\n- `{'`, `'.join(reloaded_extensions)}`\n\n{sync_message}", color=discord.Color.green())
        else:
            fail_desc = "\n".join([f"- **{ext}**: {err}" for ext, err in failed_extensions.items()])
            embed = discord.Embed(title="⚠️ 모듈 리로드 중 오류 발생", description=f"**성공:** `{'`, `'.join(reloaded_extensions)}`\n\n**실패:**\n{fail_desc}\n\n{sync_message}", color=discord.Color.orange())
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(RPGCommands(bot))