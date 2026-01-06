# Discord Bot Token
TOKEN = "YOUR_BOT_TOKEN_HERE"

# Remote MySQL Database Connection Info
DB_HOST = "DATABASE_SERVER_PUBLIC_IP_ADDRESS" # 예: 211.123.45.67
DB_PORT = 3306
DB_USER = "your_username" # 2번 단계에서 생성한 사용자 이름
DB_PASSWORD = "your_password" # 2번 단계에서 설정한 비밀번호
DB_NAME = "discord_bot_db"

# aiomysql용 DB 설정 딕셔너리
DB_CONFIG = {
    'host': DB_HOST,
    'port': DB_PORT,
    'user': DB_USER,
    'password': DB_PASSWORD,
    'db': DB_NAME,
    'autocommit': True
}