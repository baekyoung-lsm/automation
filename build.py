#!/usr/bin/env python3
"""attools 를 한 파일(.pyz)로 묶는다. 나눠 주고 받아서 바로 쓰기 위한 것이다.

받는 쪽에 필요한 것은 파이썬 3.10 이상뿐이다 - 깔 것도, 인터넷도 필요 없다.
zipapp 은 표준 라이브러리다. 새 의존성을 넣지 않으려고 이 방법을 골랐다.

    python3 build.py                # dist/at.pyz
    python3 build.py -o ~/at.pyz

만든 뒤에는 그 파일로 실제 명령을 한 번 돌려 본다. 폴더로 두고 쓸 때는 되는데
묶으면 깨지는 자리가 있다 - data/ 를 Path 로 읽던 곳이 그랬다.
"""

from __future__ import annotations

import argparse
import compileall
import hashlib
import shutil
import subprocess
import sys
import tempfile
import zipapp
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKAGE = "attools"
ENTRY = "from attools.cli import main\nraise SystemExit(main())\n"
SKIP = {"__pycache__", ".pytest_cache", ".mypy_cache"}
MIN_PYTHON = (3, 10)


def stage(target: Path) -> None:
    """묶을 것만 임시 폴더에 모은다. 캐시는 빼고 data/ 는 넣는다."""
    shutil.copytree(HERE / PACKAGE, target / PACKAGE,
                    ignore=shutil.ignore_patterns(*SKIP))
    (target / "__main__.py").write_text(ENTRY, encoding="utf-8")


def build(out: Path, *, compress: bool = True) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp)
        stage(source)
        # 문법이 깨진 채로 묶이면 받는 쪽에서야 터진다. 여기서 먼저 본다.
        if not compileall.compile_dir(str(source), quiet=1, force=True):
            raise SystemExit("파이썬 문법 오류가 있어 묶지 않았습니다.")
        for cache in source.rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)
        zipapp.create_archive(source, target=out, compressed=compress,
                              interpreter="/usr/bin/env python3")
    out.chmod(0o755)
    return out


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def smoke(path: Path) -> None:
    """묶은 것으로 실제 명령을 돌려 본다. 묶을 때만 깨지는 자리가 있다."""
    for args in (["--version"], ["keys", "--group", "문서"], ["life", "dday", "2030-01-01"]):
        done = subprocess.run([sys.executable, str(path), *args],
                              capture_output=True, text=True, timeout=120)
        if done.returncode != 0:
            raise SystemExit(f"묶은 파일이 'at {' '.join(args)}' 에서 멎었습니다:\n"
                             f"{done.stdout}{done.stderr}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="attools 를 한 파일(.pyz)로 묶는다")
    parser.add_argument("-o", "--out", default=str(HERE / "dist" / "at.pyz"),
                        metavar="파일", help="만들 파일 (기본 dist/at.pyz)")
    parser.add_argument("--no-compress", action="store_true",
                        help="줄이지 않고 묶는다 (조금 빨리 뜬다)")
    parser.add_argument("--no-check", action="store_true",
                        help="만든 뒤 실제로 돌려 보지 않는다")
    a = parser.parse_args()

    if sys.version_info < MIN_PYTHON:
        print(f"파이썬 {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 이상에서 묶어 주세요.")
        return 1

    out = build(Path(a.out).expanduser(), compress=not a.no_compress)
    if not a.no_check:
        smoke(out)

    size = out.stat().st_size
    print(f"{out}  {size / 1024:.0f} KiB")
    print(f"sha256  {digest(out)}")
    print("받는 쪽에서는 이렇게 씁니다")
    print(f"  python3 {out.name} file sweep ~/다운로드")
    print("  (파이썬 3.10 이상만 있으면 됩니다. 따로 깔 것은 없습니다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
