import discord
from discord.ext import commands
import sys
import io
import os
import logging
import asyncio

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
        except Exception as e:
            logger.error(f"❌ 확장 로드 실패: {e}")
        
        # 2. 파일 감시 태스크 시작
        self.loop.create_task(watch_files())

intents = discord.Intents.default()
intents.message_content = True
bot = MyBot(command_prefix="!", intents=intents)

async def watch_files():
    """파일 변경을 감지하여 봇을 자동으로 재시작합니다."""
    watched_extensions = ('.py', '.sql')
    files_mtime = {}

    def get_watched_files():
        for root, _, files in os.walk(current_dir):
            for file in files:
                if file.endswith(watched_extensions):
                    yield os.path.join(root, file)

    # 초기 상태 기록
    for path in get_watched_files():
        try:
            files_mtime[path] = os.path.getmtime(path)
        except OSError as e:
            logger.warning(f"파일 '{path}'의 수정 시간을 가져올 수 없습니다: {e}")

    while True:
        await asyncio.sleep(2)  # 2초 간격으로 체크
        for path in get_watched_files():
            try:
                current_mtime = os.path.getmtime(path)
                if path not in files_mtime or current_mtime > files_mtime[path]:
                    logger.info(f"🔄 파일 변경 감지됨 ({os.path.basename(path)}). 봇을 재시작합니다...")
                    os.execv(sys.executable, [sys.executable] + sys.argv)
            except OSError as e:
                logger.warning(f"파일 '{path}' 감지 중 오류 발생: {e}")

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