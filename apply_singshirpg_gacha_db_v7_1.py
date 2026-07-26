from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import py_compile
import shutil
import sys
from datetime import datetime
from pathlib import Path


PATCH_NAME = "singshirpg-gacha-db-v7.1"
PAYLOAD_DIRNAME = "singshirpg_gacha_db_v7_1_payload"
STATE_FILENAME = ".singshirpg_gacha_db_v7_1_state.json"

FILES = {
    "data_manager.py": {
        "before": "f95f075e0e758b3c56711eb0455ca27b10441705767953846738d6d787c03b7a",
        "after": "ef5b7447335b0e0f951657df79f9006f9369b1ddfbf373416c015c4666d9d227",
    },
    "life_system.py": {
        "before": "fe68bce08df6bec49edb476a28e66668a16528e7402d1440b1cdc61bd8f0103a",
        "after": "99413886daac28c0ed9ff037d2d91c564086f62d14bcbf6fab51ff70ff6e39a5",
    },
    "requirements.txt": {
        "before": "f327e5016c0e3e1318355f12c1c4b27605254a5b4b8969a02201e3ad3a61ef2d",
        "after": "3747483535f93f588f7349d2dd0b20c6321e74e2265c36de91be35b4a7f30845",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_target(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    script_dir = Path(__file__).resolve().parent
    if (script_dir / "main.py").is_file():
        return script_dir
    current = Path.cwd().resolve()
    if (current / "main.py").is_file():
        return current
    raise SystemExit(
        "봇 저장소를 찾지 못했습니다. 압축을 H:\\디코봇에 풀거나 "
        "--target \"H:\\디코봇\"을 지정하세요."
    )


def payload_root() -> Path:
    root = Path(__file__).resolve().parent / PAYLOAD_DIRNAME
    if not root.is_dir():
        raise SystemExit(f"패치 payload 폴더가 없습니다: {root}")
    return root


def validate_payload(root: Path) -> None:
    for name, hashes in FILES.items():
        source = root / name
        if not source.is_file() or sha256(source) != hashes["after"]:
            raise SystemExit(f"패치 파일 무결성 오류: {name}")
        if source.suffix == ".py":
            py_compile.compile(str(source), doraise=True)


def status_for(target: Path, name: str, hashes: dict) -> str:
    path = target / name
    if not path.is_file():
        return "MISSING"
    actual = sha256(path)
    if actual == hashes["after"]:
        return "ALREADY"
    if actual == hashes["before"]:
        return "READY"
    return "CONFLICT"


def inspect(target: Path) -> dict[str, str]:
    return {name: status_for(target, name, hashes) for name, hashes in FILES.items()}


def print_status(target: Path, statuses: dict[str, str]) -> None:
    print(f"[{PATCH_NAME}] 대상: {target}")
    for name, state in statuses.items():
        print(f"  {state:8} {name}")


def atomic_copy(source: Path, destination: Path) -> None:
    temporary = destination.with_name(destination.name + ".v7_1.tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


def restore(target: Path, records: list[dict]) -> None:
    for record in reversed(records):
        atomic_copy(Path(record["backup"]), target / record["name"])


def apply(target: Path, payload: Path) -> None:
    statuses = inspect(target)
    print_status(target, statuses)
    blocked = [name for name, state in statuses.items() if state in {"MISSING", "CONFLICT"}]
    if blocked:
        raise SystemExit(
            "현재 파일이 검사한 UI v7 상태와 달라 적용하지 않았습니다: "
            + ", ".join(blocked)
        )
    pending = [name for name, state in statuses.items() if state == "READY"]
    if not pending:
        print("이미 모두 적용되어 있습니다.")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = target / ".patch_backups" / f"gacha_db_v7_1_{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    records = []
    try:
        for name in pending:
            backup = backup_dir / name
            shutil.copy2(target / name, backup)
            records.append({"name": name, "backup": str(backup)})
        for name in pending:
            atomic_copy(payload / name, target / name)
        for name, hashes in FILES.items():
            if sha256(target / name) != hashes["after"]:
                raise RuntimeError(f"적용 후 해시 검증 실패: {name}")
            if Path(name).suffix == ".py":
                py_compile.compile(str(target / name), doraise=True)
        (target / STATE_FILENAME).write_text(
            json.dumps(
                {
                    "patch": PATCH_NAME,
                    "applied_at": datetime.now().isoformat(timespec="seconds"),
                    "records": records,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        restore(target, records)
        raise

    print("파일 적용과 문법 검사가 완료되었습니다.")
    if importlib.util.find_spec("nacl") is None:
        print("PyNaCl 경고 제거를 위해 다음 명령도 실행하세요:")
        print(f'  "{sys.executable}" -m pip install -r "{target / "requirements.txt"}"')
    print("그다음 봇을 완전히 재시작하세요.")


def revert(target: Path) -> None:
    state_path = target / STATE_FILENAME
    if not state_path.is_file():
        raise SystemExit("이 패치의 복구 기록이 없습니다.")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("patch") != PATCH_NAME:
        raise SystemExit("복구 기록의 패치 이름이 일치하지 않습니다.")
    changed = [
        name for name, hashes in FILES.items()
        if not (target / name).is_file() or sha256(target / name) != hashes["after"]
    ]
    if changed:
        raise SystemExit(
            "패치 후 파일이 다시 수정되어 안전하게 되돌릴 수 없습니다: "
            + ", ".join(changed)
        )
    restore(target, state["records"])
    state_path.unlink()
    print("패치 적용 전 상태로 되돌렸습니다.")


def main() -> None:
    parser = argparse.ArgumentParser(description="SingshiRPG DB 경고·도구 뽑기 v7.1 패치")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--check", action="store_true")
    actions.add_argument("--apply", action="store_true")
    actions.add_argument("--revert", action="store_true")
    parser.add_argument("--target", help="봇 저장소 경로. 예: H:\\디코봇")
    args = parser.parse_args()

    target = resolve_target(args.target)
    if not (target / "main.py").is_file():
        raise SystemExit(f"main.py가 없는 경로입니다: {target}")
    payload = payload_root()
    validate_payload(payload)

    if args.check:
        statuses = inspect(target)
        print_status(target, statuses)
        if any(state in {"MISSING", "CONFLICT"} for state in statuses.values()):
            raise SystemExit(2)
        print("검사 완료: 안전하게 적용할 수 있습니다.")
    elif args.apply:
        apply(target, payload)
    else:
        revert(target)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"오류: {exc}", file=sys.stderr)
        raise
