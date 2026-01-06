# Discord Bot Token
TOKEN = "YOUR_BOT_TOKEN_HERE"

# Local MySQL Database Connection Info
DB_HOST = "localhost"
DB_PORT = 3306
DB_USER = "root"
DB_PASSWORD = "YOUR_DB_PASSWORD_HERE"
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