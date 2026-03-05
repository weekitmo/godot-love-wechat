import re
from PIL import Image
import os
from pathlib import Path, PurePosixPath
from typing import Union, Dict, List, Set
from dataclasses import dataclass, field
from collections import deque


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


TEXT_RESOURCE_EXTENSIONS = {
    ".gd",
    ".gdshader",
    ".shader",
    ".tscn",
    ".scn",
    ".tres",
    ".res",
    ".cfg",
    ".json",
}
ASSET_RESOURCE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".svg",
    ".bmp",
    ".tga",
    ".dds",
    ".ktx",
    ".wav",
    ".ogg",
    ".mp3",
    ".flac",
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".csv",
    ".txt",
    ".xml",
    ".bin",
    ".glb",
    ".gltf",
    ".obj",
    ".fbx",
    ".dae",
    ".stl",
    ".mesh",
}
SENSITIVE_FILE_EXTENSIONS = {
    ".keystore",
    ".jks",
    ".p12",
    ".pem",
    ".key",
    ".crt",
    ".cer",
}
EXPORTABLE_RESOURCE_EXTENSIONS = TEXT_RESOURCE_EXTENSIONS.union(
    ASSET_RESOURCE_EXTENSIONS
)
IGNORED_FILE_EXTENSIONS = {".import", ".uid", ".escn"}
IGNORED_FILE_NAMES = {"export_presets.cfg", "minigame.export.json"}
IGNORED_TOP_LEVEL_DIRS = {
    ".git",
    ".github",
    ".godot",
    "__pycache__",
    "dist",
    "tmp",
    "build",
}
RESOURCE_REF_PATTERN = re.compile(r"res://[^\s\"'`\),\]]+")
SCENE_UID_PATTERN = re.compile(r'\[gd_scene[^\]]*uid="([^"]+)"')


@dataclass
class AutoSubpackPlan:
    main_resources: List[str] = field(default_factory=list)
    inner_resources: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)


def _normalize_res_path(resource_path: str) -> str:
    normalized = resource_path.strip().strip('"').replace("\\", "/")
    idx = normalized.find("res://")
    if idx == -1:
        return ""
    normalized = normalized[idx:]
    normalized = normalized.split("::", maxsplit=1)[0]
    normalized = normalized.split("#", maxsplit=1)[0]
    normalized = normalized.split("?", maxsplit=1)[0]
    rel_path = normalized.removeprefix("res://").lstrip("/")
    if not rel_path:
        return ""
    return f"res://{PurePosixPath(rel_path).as_posix()}"


def _is_ignored_dir(relative_dir: Path) -> bool:
    parts = relative_dir.parts
    if not parts:
        return False
    if parts[0] in IGNORED_TOP_LEVEL_DIRS:
        return True
    return any(part.startswith(".") for part in parts)


def _is_ignored_file(project_root: Path, file_path: Path) -> bool:
    relative_path = file_path.relative_to(project_root)
    if _is_ignored_dir(relative_path.parent):
        return True
    if relative_path.parts and relative_path.parts[0] in IGNORED_TOP_LEVEL_DIRS:
        return True
    if any(part.startswith(".") for part in relative_path.parts):
        return True
    if file_path.name in IGNORED_FILE_NAMES:
        return True
    if file_path.suffix.lower() in IGNORED_FILE_EXTENSIONS:
        return True
    return False


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _is_exportable_resource_file(file_path: Path) -> bool:
    if file_path.name == "project.godot":
        return True
    suffix = file_path.suffix.lower()
    if suffix in SENSITIVE_FILE_EXTENSIONS:
        return False
    return suffix in EXPORTABLE_RESOURCE_EXTENSIONS


def _extract_resource_refs(file_path: Path) -> Set[str]:
    if file_path.suffix.lower() not in TEXT_RESOURCE_EXTENSIONS and file_path.name != "project.godot":
        return set()

    content = _read_text(file_path)
    refs = set()
    for match in RESOURCE_REF_PATTERN.findall(content):
        normalized = _normalize_res_path(match)
        if normalized:
            refs.add(normalized)
    return refs


def _build_scene_uid_map(project_root: Path) -> Dict[str, str]:
    uid_map: Dict[str, str] = {}
    for suffix in ("*.tscn", "*.scn"):
        for scene_path in project_root.rglob(suffix):
            if _is_ignored_file(project_root, scene_path):
                continue
            content = _read_text(scene_path)
            match = SCENE_UID_PATTERN.search(content)
            if not match:
                continue
            uid_map[match.group(1)] = f"res://{scene_path.relative_to(project_root).as_posix()}"
    return uid_map


def _resolve_main_scene_path(project_root: Path, config: Dict) -> tuple[str, List[str]]:
    warnings: List[str] = []
    app_cfg = config.get("application", {})
    main_scene = app_cfg.get("run/main_scene", "")
    if not main_scene:
        return "", ["project.godot 未配置 run/main_scene。"]

    normalized = _normalize_res_path(main_scene)
    if normalized:
        return normalized, warnings

    if main_scene.startswith("uid://"):
        scene_uid_map = _build_scene_uid_map(project_root)
        resolved = scene_uid_map.get(main_scene)
        if resolved:
            return resolved, warnings
        warnings.append(f"无法解析 run/main_scene 的 UID: {main_scene}")
        return "", warnings

    warnings.append(f"无法解析 run/main_scene: {main_scene}")
    return "", warnings


def _resolve_autoload_roots(config: Dict) -> List[str]:
    roots: Set[str] = set()
    autoload_cfg = config.get("autoload", {})
    for _, value in autoload_cfg.items():
        value_str = value.strip()
        idx = value_str.find("res://")
        if idx == -1:
            continue
        normalized = _normalize_res_path(value_str[idx:])
        if normalized:
            roots.add(normalized)
    return sorted(roots)


def _collect_project_resources(project_root: Path) -> List[str]:
    resources: List[str] = []
    for current_root, dirs, files in os.walk(project_root):
        current_path = Path(current_root)
        relative_dir = current_path.relative_to(project_root)
        dirs[:] = [d for d in dirs if not _is_ignored_dir(relative_dir.joinpath(d))]

        for file_name in files:
            file_path = current_path.joinpath(file_name)
            if _is_ignored_file(project_root, file_path):
                continue
            if not _is_exportable_resource_file(file_path):
                continue
            resources.append(f"res://{file_path.relative_to(project_root).as_posix()}")

    return sorted(resources)


def _collect_dependency_closure(
    project_root: Path, dependency_roots: List[str]
) -> tuple[Set[str], List[str]]:
    warnings: List[str] = []
    queue: deque[str] = deque(dependency_roots)
    visited: Set[str] = set()
    closure: Set[str] = set()

    while queue:
        resource_path = queue.popleft()
        if resource_path in visited:
            continue
        visited.add(resource_path)

        absolute_path = project_root.joinpath(resource_path.removeprefix("res://"))
        if not absolute_path.exists():
            warnings.append(f"资源不存在: {resource_path}")
            continue
        if _is_ignored_file(project_root, absolute_path):
            continue

        closure.add(resource_path)
        refs = _extract_resource_refs(absolute_path)
        for ref in refs:
            ref_path = project_root.joinpath(ref.removeprefix("res://"))
            if not ref_path.exists():
                warnings.append(f"引用不存在: {ref} (from {resource_path})")
                continue
            if _is_ignored_file(project_root, ref_path):
                continue

            closure.add(ref)
            if ref_path.suffix.lower() in TEXT_RESOURCE_EXTENSIONS or ref_path.name == "project.godot":
                queue.append(ref)

    unique_warnings = sorted(set(warnings))
    return closure, unique_warnings


def generate_auto_subpack_plan(project_root: Union[str, Path]) -> AutoSubpackPlan:
    root = Path(project_root).resolve()
    project_file = root.joinpath("project.godot")
    if not project_file.exists():
        return AutoSubpackPlan(
            main_resources=[],
            inner_resources=[],
            warnings=["缺少 project.godot，无法自动分包。"],
            stats={"all_count": 0, "main_count": 0, "inner_count": 0},
        )

    config = parse_godot_project(project_file.as_posix())
    all_resources = _collect_project_resources(root)
    main_scene_path, warnings = _resolve_main_scene_path(root, config)

    # If run/main_scene cannot be resolved, boot glue can't route to game scene safely.
    if not main_scene_path:
        return AutoSubpackPlan(
            main_resources=all_resources,
            inner_resources=[],
            warnings=sorted(set(warnings + ["已回退为不拆分（全部放主包）。"])),
            stats={
                "all_count": len(all_resources),
                "main_count": len(all_resources),
                "inner_count": 0,
            },
        )

    autoload_roots = _resolve_autoload_roots(config)
    autoload_closure, autoload_warnings = _collect_dependency_closure(root, autoload_roots)
    warnings.extend(autoload_warnings)

    main_resource_set: Set[str] = set()
    if not _is_ignored_file(root, project_file):
        main_resource_set.add("res://project.godot")

    default_bus = root.joinpath("default_bus_layout.tres")
    if default_bus.exists() and not _is_ignored_file(root, default_bus):
        main_resource_set.add("res://default_bus_layout.tres")

    # Keep autoload dependency closure in main package so boot scene can run safely.
    main_resource_set.update(autoload_closure)

    main_resources = sorted(set(all_resources).intersection(main_resource_set))
    inner_resources = sorted(set(all_resources).difference(main_resources))

    return AutoSubpackPlan(
        main_resources=main_resources,
        inner_resources=inner_resources,
        warnings=sorted(set(warnings)),
        stats={
            "all_count": len(all_resources),
            "main_count": len(main_resources),
            "inner_count": len(inner_resources),
        },
    )
