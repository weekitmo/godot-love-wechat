import re
from PIL import Image
import os
from pathlib import Path
from typing import Union, Dict, List


def parse_godot_project(file_path):
    """使用正则表达式解析 Godot project.godot 文件"""
    # 定义正则表达式
    section_pattern = re.compile(r"^\[(.+?)\]$")  # 匹配 [section]
    key_value_pattern = re.compile(r"^([\w/]+)=(.+)$")  # 匹配 key=value

    # 存储解析结果
    result = {}
    current_section = None

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            # 去掉空行和注释
            line = line.strip()
            if not line or line.startswith(";"):
                continue

            # 检查是否是一个 section
            section_match = section_pattern.match(line)
            if section_match:
                current_section = section_match.group(1)
                result[current_section] = {}
                continue

            # 检查是否是一个 key=value 对
            key_value_match = key_value_pattern.match(line)
            if key_value_match and current_section:
                key, value = key_value_match.groups()
                # 去掉两侧的引号
                value = value.strip().strip('"')
                result[current_section][key] = value

    return result


def read_icon_to_base64(icon_path):
    with Image.open(icon_path) as img:
        img = img.convert("RGB")
    return img


def resolve_project_icon(project_root: str, icon_value: str | None) -> str:
    fallback = "/assets/logo.svg"
    root = Path(project_root)

    candidates: List[str] = []
    if icon_value:
        raw = icon_value.strip().strip('"')
        if raw.startswith("res://"):
            raw = raw.removeprefix("res://")
        elif raw.startswith("uid://"):
            raw = ""

        raw = raw.lstrip("/\\")
        if raw:
            candidates.append(raw)

    # Common defaults for Godot projects.
    candidates.extend(["icon.svg", "icon.png", "icon.webp", "icon.jpg", "icon.jpeg"])

    for candidate in candidates:
        candidate_path = Path(candidate)
        icon_path = candidate_path if candidate_path.is_absolute() else root.joinpath(candidate)
        if icon_path.is_file():
            return str(icon_path)

    return fallback


def build_tree_dict(
    root_path: Union[str, Path],
    excludes: List[str] = [".import", ".uid", ".escn", ".godot"],
    depth: int = 0,
    max_depth: int = 10,
    base_path: Union[str, Path] | None = None,
) -> Dict | None:
    path = Path(root_path)

    if base_path is None:
        base_path = path

    _, extension = os.path.splitext(path.name)

    if path.name.startswith("."):
        return None

    if path.name in ["export_presets.cfg", "minigame.export.json"]:
        return None
    if extension in excludes:
        return None

    relative_path = (
        f"res://{path.relative_to(base_path).as_posix()}"
        if path != base_path
        else "res://"
    )
    node = {
        "id": relative_path,
        "icon": "folder" if path.is_dir() else "description",
        "label": path.name,
    }

    if path.is_dir() and depth < max_depth:
        children = []
        for child in sorted(os.listdir(path)):
            if child in excludes:
                continue
            child_node = build_tree_dict(
                path / child, excludes, depth + 1, max_depth, base_path
            )
            if child_node:
                children.append(child_node)
        if children:
            node["children"] = children  # pyright: ignore

    return node
