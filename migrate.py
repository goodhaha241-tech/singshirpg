import json
import asyncio
import os
import sys
import io
import logging
from datetime import datetime
from data_manager import get_db_pool, save_user_data, check_schema

# [Fix] 콘솔 출력 인코딩 설정
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
elif sys.stdout and hasattr(sys.stdout, 'detach'):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding = 'utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding = 'utf-8')
    except Exception:
        pass


# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# 파일 경로
JSON_FILE_PATH = "user_data.json"

async def reset_database(pool):
    """데이터베이스의 모든 테이블을 삭제하여 초기화합니다."""
    logger.warning("⚠️ 데이터베이스 초기화를 시작합니다. 모든 테이블이 삭제됩니다...")
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SET FOREIGN_KEY_CHECKS = 0")
                await cur.execute("SHOW TABLES")
                tables = await cur.fetchall()
                for table_row in tables:
                    table_name = table_row[0]
                    logger.info(f"🗑️ 테이블 삭제 중: {table_name}")
                    await cur.execute(f"DROP TABLE IF EXISTS `{table_name}`")
                await cur.execute("SET FOREIGN_KEY_CHECKS = 1")
        logger.info("✅ 데이터베이스 초기화 완료.")
        return True
    except Exception as e:
        logger.error(f"❌ 데이터베이스 초기화 실패: {e}")
        return False

async def run_migration():
    if not os.path.exists(JSON_FILE_PATH):
        logger.error(f"파일을 찾을 수 없습니다: {JSON_FILE_PATH}")
        return

    logger.info("📂 JSON 파일 로딩 중...")
    try:
        with open(JSON_FILE_PATH, "r", encoding="utf-8") as f:
            all_data = json.load(f)
    except Exception as e:
        logger.error(f"JSON 파싱 실패: {e}")
        return

    logger.info(f"총 {len(all_data)}명의 유저 데이터를 발견했습니다. 마이그레이션 시작...")
    
    # DB 풀 초기화
    try:
        pool = await get_db_pool()
    except Exception as e:
        logger.error(f"DB 연결 실패: {e}")
        logger.error("config.py의 설정(비밀번호, 포트 등)을 확인하거나, MySQL 서버가 켜져 있는지 확인하세요.")
        return

    # 데이터베이스 리셋
    if not await reset_database(pool):
        return
        
    # 스키마 재생성
    logger.info("🔄 스키마를 새로 생성합니다...")
    await check_schema(pool)
    logger.info("✅ 스키마 생성 완료.")

    success_count = 0
    fail_count = 0

    for user_id, user_data in all_data.items():
        try:
            # 'global_trades'와 같은 비-유저 키를 건너뜁니다.
            if not user_id.isdigit():
                logger.warning(f"'{user_id}'는 유저 ID가 아니므로 건너뜁니다.")
                continue

            # save_user_data가 모든 테이블 분산 저장을 담당합니다.
            # user_data 딕셔너리를 그대로 넘깁니다.
            await save_user_data(user_id, user_data)
            
            success_count += 1
            if success_count % 10 == 0:
                print(f"✅ {success_count}명 처리 완료...", end='\r')
                
        except Exception as e:
            fail_count += 1
            logger.error(f"\n❌ User {user_id} 실패: {e}")

    print(f"\n\n{'='*30}")
    print(f"🎉 마이그레이션 완료")
    print(f"성공: {success_count}명")
    print(f"실패: {fail_count}명")
    print(f"{'='*30}")
    
    # 연결 종료
    pool.close()
    await pool.wait_closed()

if __name__ == "__main__":
    try:
        asyncio.run(run_migration())
    except KeyboardInterrupt:
        print("\n중단됨.")