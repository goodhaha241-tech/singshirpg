import sys
import io
import os
import logging
import asyncio
import discord
from discord.ext import commands

# -------------------------------------------------------------------------
# 1. 환경 설정 및 모듈 경로 잡기
# -------------------------------------------------------------------------
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
elif sys.stdout and hasattr(sys.stdout, 'detach'):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding = 'utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding = 'utf-8')
    except Exception as e:
        pass

# 하위 폴더 모듈 경로 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
for root, dirs, files in os.walk(current_dir):
    dirs[:] = [d for d in dirs if not d.startswith('.') and not d.startswith('__')]
    if root not in sys.path:
        sys.path.append(root)

# -------------------------------------------------------------------------
# 2. 필수 모듈 임포트
# -------------------------------------------------------------------------
try:
    # config.py에서 TOKEN을 가져옵니다.
    from config import TOKEN
    from data_manager import get_db_pool
except ImportError as e:
    print(f"❌ 필수 모듈 로드 실패: {e}")
    sys.exit(1)

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Main")

# -------------------------------------------------------------------------
# 3. 봇 초기화
# -------------------------------------------------------------------------
class MyBot(commands.Bot):
    async def setup_hook(self):
        """봇 시작 시 초기 설정을 수행합니다. (on_ready보다 먼저 실행됨)"""
        # 1. 확장 로드
        try:
            if "rpg_commands" not in self.extensions:
                await self.load_extension("rpg_commands")
            logger.info("✅ rpg_commands 확장 로드 완료")

            # [신규] 지속성 뷰 등록
            from info import InfoView
            from rpg_commands import OutingMenuView, ManagementMenuView
            from subjugation import SubjugationRegionView, DungeonMainView
            from data_manager import save_user_data
            self.add_view(InfoView(save_func=save_user_data, timeout=None))
            self.add_view(OutingMenuView(save_func=save_user_data, timeout=None))
            self.add_view(ManagementMenuView(save_func=save_user_data, timeout=None))
            self.add_view(SubjugationRegionView(None, None, save_user_data, timeout=None))
            self.add_view(DungeonMainView(None, None, save_user_data, timeout=None))
        except Exception as e:
            logger.error(f"❌ 확장 로드 실패: {e}")
        

intents = discord.Intents.default()
intents.message_content = True
bot = MyBot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    """봇 시작 시 실행"""
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    
    # 1. DB 연결 풀 생성 확인
    try:
        await get_db_pool()
        logger.info("✅ 데이터베이스 연결 성공")
    except Exception as e:
        logger.error(f"❌ 데이터베이스 연결 실패: {e}")

    print("🤖 봇이 성공적으로 실행되었습니다! (준비 완료)")

@bot.command(name="sync")
@commands.is_owner()
async def sync_commands(ctx):
    """슬래시 커맨드를 수동으로 동기화합니다. (봇 소유자 전용)"""
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"✅ {len(synced)}개의 슬래시 커맨드가 동기화되었습니다.")
    except Exception as e:
        await ctx.send(f"❌ 동기화 실패: {e}")

# -------------------------------------------------------------------------
# 4. 실행
# -------------------------------------------------------------------------
if __name__ == "__main__":
    if not TOKEN:
        logger.error("config.py에 TOKEN이 설정되지 않았습니다.")
    else:
        bot.run(TOKEN)