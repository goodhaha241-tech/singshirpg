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
    except Exception:
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
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

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

    # 2. 명령어 파일(Extension) 로드 및 동기화
    try:
        await bot.load_extension("rpg_commands")
        synced = await bot.tree.sync()
        logger.info(f"✅ {len(synced)}개의 슬래시 커맨드 동기화 완료")
    except Exception as e:
        logger.error(f"❌ 커맨드 로드/동기화 실패: {e}")

    print("🤖 봇이 성공적으로 실행되었습니다! (준비 완료)")

# -------------------------------------------------------------------------
# 4. 실행
# -------------------------------------------------------------------------
if __name__ == "__main__":
    if not TOKEN:
        logger.error("config.py에 TOKEN이 설정되지 않았습니다.")
    else:
        bot.run(TOKEN)