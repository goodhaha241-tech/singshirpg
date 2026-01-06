# Discord RPG Bot Project

이 프로젝트는 Python(`discord.py`)과 MySQL(`aiomysql`)을 기반으로 제작된 디스코드 RPG 봇입니다.
캐릭터 육성, 전투, 인벤토리 시스템, 그리고 마이홈(정원, 낚시, 공방) 콘텐츠를 포함하고 있습니다.

## 📋 사전 요구 사항 (Prerequisites)

이 봇을 실행하기 위해서는 다음 프로그램들이 필요합니다.

*   **Python 3.8** 이상
*   **MySQL Server 8.0** 이상
*   (선택 사항) **LogMeIn Hamachi** 또는 **Radmin VPN** (로컬 협업 시 필요)

## 🛠️ 설치 방법 (Installation)

1.  **프로젝트 다운로드 (Clone)**
    ```bash
    git clone <저장소_주소>
    cd <프로젝트_폴더>
    ```

2.  **필수 라이브러리 설치**
    `requirements.txt`에 명시된 패키지들을 설치합니다.
    ```bash
    pip install -r requirements.txt
    ```

## ⚙️ 환경 설정 (Configuration)

보안을 위해 봇 토큰과 데이터베이스 정보는 `.env` 파일로 관리합니다.
프로젝트 루트 폴더에 `.env` 파일을 생성하고 아래 내용을 본인의 환경에 맞게 수정하여 입력하세요.

```env
DISCORD_TOKEN=여기에_봇_토큰을_입력하세요
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASS=설정한_비밀번호
DB_NAME=discord_bot_db
```

*   **로컬 실행 시**: `DB_HOST=localhost`
*   **협업(팀원) 실행 시**: `DB_HOST=호스트의_하마치_IP_주소`

## 🗄️ 데이터베이스 설정

봇을 처음 실행하면 `data_manager.py`가 자동으로 데이터베이스(`discord_bot_db`)와 필요한 테이블을 생성합니다.
별도의 SQL 파일을 수동으로 실행할 필요는 없으나, MySQL 서버는 켜져 있어야 합니다.

## ▶️ 실행 방법 (Usage)

설정이 완료되었다면 아래 명령어로 봇을 실행합니다.

```bash
python main.py
```

정상적으로 실행되면 콘솔에 `Logged in as ...` 및 `✅ 데이터베이스 연결 성공` 메시지가 출력됩니다.

## 🤝 하마치(Hamachi) 협업 가이드

**호스트 (DB를 공유하는 사람)**
1.  `my.ini` 파일에서 `bind-address = 0.0.0.0` 설정 확인.
2.  윈도우 방화벽에서 **3306 포트(TCP)** 인바운드 규칙 허용.
3.  MySQL에서 외부 접속용 계정(`friend`) 생성 및 권한 부여.
4.  하마치 네트워크 생성 및 친구 초대.

**게스트 (접속하는 사람)**
1.  하마치 네트워크 가입.
2.  `.env` 파일의 `DB_HOST`에 호스트의 **하마치 IPv4 주소** 입력.