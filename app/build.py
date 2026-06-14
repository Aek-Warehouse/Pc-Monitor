from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
ENTRYPOINT = APP_DIR / "main.py"
DIST_DIR = APP_DIR / "dist"
BUILD_DIR = APP_DIR / "build"
SPEC_FILE = APP_DIR / "PCMonitor.spec"


def clean_previous_build() -> None:
    shutil.rmtree(DIST_DIR, ignore_errors=True)
    shutil.rmtree(BUILD_DIR, ignore_errors=True)
    SPEC_FILE.unlink(missing_ok=True)


def main() -> int:
    clean_previous_build()

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        "PCMonitor",
        "--hidden-import",
        "tkinter",
        "--hidden-import",
        "mss",
        "--hidden-import",
        "PIL.Image",
        "--hidden-import",
        "imageio_ffmpeg",
        "--collect-all",
        "imageio_ffmpeg",
        "--collect-all",
        "tzdata",
        "--copy-metadata",
        "imageio-ffmpeg",
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
        "--specpath",
        str(APP_DIR),
        str(ENTRYPOINT),
    ]

    build_result = subprocess.run(command, check=False)
    if build_result.returncode != 0:
        return build_result.returncode

    executable = DIST_DIR / ("PCMonitor.exe" if sys.platform.startswith("win") else "PCMonitor")
    if not executable.exists():
        print(f"Build finished, but {executable} was not found.")
        return 1

    print("\nRunning packaged self-test...")
    test_result = subprocess.run([str(executable), "--self-test"], check=False)
    return test_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
