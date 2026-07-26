import sys
import io
import os
import logging
import asyncio
import discord
from discord.ext import commands

# [중요] 지속성 뷰(Persistent View)를 위해 필요한 클래스 임포트
# 길드 뷰는 main.py에서 등록해야 재시작 후에도 버튼이 반응합니다.
from guild import GuildMainView 
from data_manager import get_db_pool, save_user_data

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
# 2. 필수 모듈 및 설정 로드
# -------------------------------------------------------------------------
try:
    from config import TOKEN
except ImportError as e:
    print(f"❌ 설정 파일 로드 실패: {e}")
    print("config.py 파일이 존재하는지 확인해주세요.")
    input("엔터 키를 누르면 종료합니다...")
    sys.exit(1)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout), 
        logging.FileHandler("bot.log", encoding="utf-8")
    ],
    force=True
)
logger = logging.getLogger("Main")

# -------------------------------------------------------------------------
# 3. 봇 클래스 정의
# -------------------------------------------------------------------------
class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix="!", 
            intents=intents,
            help_command=None # 기본 도움말 끄기 (필요시 커스텀)
        )

    async def setup_hook(self):
        """
        봇 시작 시 초기 설정을 수행합니다. (on_ready보다 먼저 실행됨)
        확장 모듈 로드 및 지속성 뷰(Persistent View) 등록을 여기서 처리합니다.
        """
        # 1. DB 연결 풀 초기화 (미리 연결)
        try:
            await get_db_pool()
            logger.info("✅ 데이터베이스 연결 풀 초기화 성공")
        except Exception as e:
            logger.error(f"❌ 데이터베이스 연결 실패: {e}")

        # 2. 확장 모듈(Commands) 로드
        try:
            if "rpg_commands" not in self.extensions:
                await self.load_extension("rpg_commands")
            logger.info("✅ rpg_commands 확장 로드 완료")
        except Exception as e:
            logger.error(f"❌ rpg_commands 로드 실패: {e}")

        # 3. 지속성 뷰(Persistent View) 등록
        # 봇이 재시작되어도 'custom_id'가 설정된 버튼들이 작동하게 합니다.
        try:
            # (1) 길드 메인 뷰 등록
            self.add_view(GuildMainView())
            logger.info("✅ GuildMainView 지속성 등록 완료")

            # (2) 던전/토벌 관련 뷰 등록 (필요한 경우)
            # 주의: 해당 뷰 클래스들이 timeout=None을 지원하도록 수정되었는지 확인 필요
            try:
                from subjugation import SubjugationRegionView, DungeonMainView
                # 인자가 필요한 경우 None 등을 넣어 초기화하되, 내부에서 데이터 로드 로직이 있어야 함
                self.add_view(SubjugationRegionView(None, None, save_user_data, timeout=None))
                logger.info("✅ SubjugationRegionView 지속성 등록 완료")
                self.add_view(DungeonMainView(None, None, save_user_data, timeout=None))
                logger.info("✅ DungeonMainView 지속성 등록 완료")
            except ImportError:
                pass # 해당 파일이 없거나 뷰가 없으면 패스
            except Exception as e:
                logger.warning(f"⚠️ 던전 뷰 등록 중 경고: {e}")

        except Exception as e:
            logger.error(f"❌ 지속성 뷰 등록 실패: {e}")
        
        # 4. v6에서 추가된 /마이홈·/생활 등의 진입점을 Discord에 반영한다.
        # 서버가 비정기적으로 실행되므로 시작할 때 한 번 동기화하는 편이
        # 수동 !sync 누락보다 안전하다.
        try:
            synced = await self.tree.sync()
            logger.info("Slash commands synced: %s", len(synced))
        except Exception as e:
            logger.error("Slash command sync failed: %s", e)

bot = MyBot()

# -------------------------------------------------------------------------
# 4. 이벤트 핸들러
# -------------------------------------------------------------------------
@bot.event
async def on_ready():
    """봇 준비 완료 시 실행"""
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("🤖 봇이 성공적으로 실행되었습니다! (준비 완료)")
    print("--------------------------------------------------")

# -------------------------------------------------------------------------
# 5. 관리자 커맨드
# -------------------------------------------------------------------------
@bot.command(name="sync")
@commands.is_owner()
async def sync_commands(ctx):
    """슬래시 커맨드를 수동으로 동기화합니다. (봇 소유자 전용)"""
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"✅ {len(synced)}개의 슬래시 커맨드가 동기화되었습니다.")
        logger.info(f"Command synced: {len(synced)}")
    except Exception as e:
        await ctx.send(f"❌ 동기화 실패: {e}")
        logger.error(f"Sync failed: {e}")

@bot.command(name="hard_reset")
@commands.is_owner()
async def hard_reset_commands(ctx):
    """커맨드를 완전히 초기화(삭제)한 후 다시 등록합니다."""
    msg = await ctx.send("🔄 커맨드 초기화 및 재등록 중... (시간이 걸릴 수 있습니다)")
    try:
        # 1. 로컬 트리 비우기 및 디스코드 동기화 (커맨드 삭제)
        bot.tree.clear_commands(guild=None)
        await bot.tree.sync()
        
        # 2. 확장 모듈 다시 로드 (커맨드 다시 채우기)
        await bot.reload_extension("rpg_commands")
        
        # 3. 최종 동기화 (커맨드 등록)
        synced = await bot.tree.sync()
        await msg.edit(content=f"✅ **완전 초기화 완료!**\n총 {len(synced)}개의 커맨드가 다시 등록되었습니다.")
        logger.info("Hard reset complete.")
    except Exception as e:
        await msg.edit(content=f"❌ 초기화 실패: {e}")
        logger.error(f"Hard reset failed: {e}")

# -------------------------------------------------------------------------
# 6. 실행
# -------------------------------------------------------------------------
if __name__ == "__main__":
    if not TOKEN:
        logger.error("config.py에 TOKEN이 설정되지 않았습니다.")
        input("엔터 키를 누르면 종료합니다...")
    else:
        try:
            bot.run(TOKEN)
        except Exception as e:
            logger.error(f"봇 실행 중 오류가 발생했습니다: {e}")
            logger.error("토큰이 올바른지, 인터넷 연결이 되어있는지 확인해주세요.")
            input("엔터 키를 누르면 종료합니다...")
