import pymysql

class Database:
    def __init__(self):
        self.db_config = {
            'host': 'localhost',
            'user': 'root',
            'password': '52585623!', # MySQL 설치 시 설정한 비밀번호가 맞는지 확인하세요
            'database': 'discord_bot_db',
            'charset': 'utf8mb4',
            'cursorclass': pymysql.cursors.DictCursor,
            'autocommit': True
        }
        self.conn = None

    def connect(self):
        if self.conn is None or not self.conn.open:
            try:
                self.conn = pymysql.connect(**self.db_config)
                # print("데이터베이스 연결 성공") # 콘솔 도배 방지를 위해 주석 처리
            except pymysql.MySQLError as e:
                print(f"데이터베이스 연결 실패: {e}")
                print("👉 database.py 파일의 'password' 항목이 실제 DB 비밀번호와 일치하는지 확인해주세요.")
                raise

    def get_cursor(self):
        self.connect()
        return self.conn.cursor()

    def execute(self, query, args=None):
        self.connect()
        with self.conn.cursor() as cursor:
            cursor.execute(query, args)
            return cursor.lastrowid

    def execute_many(self, query, args=None):
        self.connect()
        with self.conn.cursor() as cursor:
            cursor.executemany(query, args)

    def fetch_one(self, query, args=None):
        self.connect()
        with self.conn.cursor() as cursor:
            cursor.execute(query, args)
            return cursor.fetchone()

    def fetch_all(self, query, args=None):
        self.connect()
        with self.conn.cursor() as cursor:
            cursor.execute(query, args)
            return cursor.fetchall()

    def close(self):
        if self.conn and self.conn.open:
            self.conn.close()

db = Database()