import os
import sys
import re
import subprocess
from pathlib import Path


def is_windows() -> bool:
    return sys.platform.startswith("win")


def is_macos() -> bool:
    return sys.platform == "darwin"


def godot_file_types() -> tuple[str, ...]:
    if is_windows():
        return ("Godot Execute (*.exe)",)
    if is_macos():
        return ("Godot Execute (*.app)", "Executable (*)")
    return ("Executable (*)",)


def resolve_godot_executable(godot_execute: str) -> str:
    if not godot_execute:
        return godot_execute

    path = Path(godot_execute).expanduser()
    if not is_macos():
        return str(path)

    if path.is_file():
        return str(path)

    app_path = path if path.suffix.lower() == ".app" else None
    if app_path is None and path.is_dir():
        app_entries = sorted(path.glob("*.app"))
        if app_entries:
            app_path = app_entries[0]

    if app_path is None:
        return str(path)

    macos_dir = app_path / "Contents" / "MacOS"
    if not macos_dir.exists():
        return str(path)

    preferred_names = ("Godot", "godot", "Godot_mono", "godot_mono")
    for name in preferred_names:
        candidate = macos_dir / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    executables = [
        candidate
        for candidate in macos_dir.iterdir()
        if candidate.is_file() and os.access(candidate, os.X_OK)
    ]
    if executables:
        executables.sort(key=lambda item: (not item.name.lower().startswith("godot"), item.name.lower()))
        return str(executables[0])

    return str(path)


def resolve_wechat_cli(wechat_execute: str) -> str:
    if not wechat_execute:
        return wechat_execute

    path = Path(wechat_execute).expanduser()
    if is_windows():
        if path.name.lower() == "cli.bat":
            return str(path)
        return str(path.joinpath("cli.bat"))

    if is_macos():
        candidates = [path]
        if path.name != "cli":
            candidates.append(path.joinpath("cli"))
        candidates.append(path.joinpath("Contents", "MacOS", "cli"))
        candidates.append(path.joinpath("wechatwebdevtools.app", "Contents", "MacOS", "cli"))
        candidates.append(path.joinpath("微信开发者工具.app", "Contents", "MacOS", "cli"))

        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)

        if path.suffix.lower() == ".app":
            return str(path.joinpath("Contents", "MacOS", "cli"))
        return str(path.joinpath("cli"))

    if path.name == "cli":
        return str(path)
    return str(path.joinpath("cli"))


def get_godot_version(godot_execute: str) -> str:
    executable = resolve_godot_executable(godot_execute)
    if not executable:
        return ""

    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return ""

    output = f"{result.stdout}\n{result.stderr}".strip()
    match = re.search(r"\d+\.\d+(?:\.\d+)?", output)
    return match.group(0) if match else ""
