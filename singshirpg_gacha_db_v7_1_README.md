# SingshiRPG DB 경고·세공 도구 뽑기 v7.1

현재 `H:\디코봇`의 UI v7 적용 상태를 기준으로 만든 후속 패치입니다.

## 변경 내용

### 시작 경고 정리

- 이미 존재하는 길드·생활 테이블에는 `CREATE TABLE`을 다시 실행하지 않습니다.
- 다음 `Table ... already exists` 경고가 반복되지 않습니다.
  - `guilds`
  - `guild_members`
  - `guild_inventory`
  - `guild_stored_artifacts`
  - `guild_log`
  - `user_life_data`
- `requirements.txt`에 `PyNaCl`을 추가합니다.

PyNaCl은 파일만 교체한다고 설치되지는 않으므로 패치 후 한 번 설치해야 합니다.

### 세공 도구 뽑기

- 1회당 등장 확률:
  - 원석: 65%
  - 세공 도구: 35%
- 원석 당첨 시 미감정 `원석 ×1`을 지급합니다.
- 세공 도구 당첨 시 기존 규칙대로 신규 획득 또는 중복 자동 돌파가 적용됩니다.
- 기존의 `도구 확정 + 원석 5% 보너스` 방식은 제거됩니다.
- 뽑기 화면에서 보유 도구 전체 목록과 초과 중복 누적 로그를 제거합니다.
- 1회·10회 뽑기 모두 이번에 나온 결과만 간단하게 표시합니다.

DB 스키마 자체를 변경하지는 않습니다.

## 적용

ZIP 전체를 `H:\디코봇`에 풉니다.

```powershell
Set-Location "H:\디코봇"

python .\apply_singshirpg_gacha_db_v7_1.py --check
python .\apply_singshirpg_gacha_db_v7_1.py --apply
python -m pip install -r .\requirements.txt
python -m compileall -q .
python .\main.py
```

`--check` 결과가 모두 `READY` 또는 `ALREADY`일 때만 적용됩니다.

## 되돌리기

```powershell
python .\apply_singshirpg_gacha_db_v7_1.py --revert
```

PyNaCl 패키지 설치 자체는 되돌리기에서 제거하지 않습니다. 설치된 상태여도 음성 기능을 사용하지 않으면 게임 동작에는 영향이 없습니다.

## 적용 후 확인

1. 봇 시작 시 `Table ... already exists` 경고가 사라졌는지 확인합니다.
2. `PyNaCl is not installed` 경고가 사라졌는지 확인합니다.
3. 세공 도구 뽑기 화면에 `원석 65% · 세공 도구 35%`가 표시되는지 확인합니다.
4. 뽑기 후 이번 결과만 표시되고 전체 보유 도구 목록이 길게 붙지 않는지 확인합니다.
5. 도구 중복 당첨 시 기존처럼 자동 돌파되는지 확인합니다.
