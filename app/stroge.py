import os
import json
import sys
from pathlib import Path

class Storge:
    def __init__(self) -> None:
        self.path = self._resolve_storage_path()

    def _resolve_storage_path(self) -> str:
        if sys.platform.startswith("win"):
            base_dir = (
                os.environ.get("LOCALAPPDATA")
                or os.environ.get("APPDATA")
                or str(Path.home() / "AppData" / "Local")
            )
        elif sys.platform == "darwin":
            base_dir = str(Path.home() / "Library" / "Application Support")
        else:
            base_dir = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))

        return os.path.join(base_dir, "godot-love-wechat")

    def save(self, file, data):
        print(self.path)
        if not os.path.exists(self.path):
            os.makedirs(self.path, exist_ok=True)
        _data = json.dumps(data, indent=2)
        path = os.path.join(self.path, file)
        with open(path, "w+", encoding="utf-8") as f:
            f.write(_data)

    def get(self, file):
        path = os.path.join(self.path, file)
        if not os.path.exists(path):
            return
        with open(path, "rb") as f:
            data = json.loads(f.read())
        return data
