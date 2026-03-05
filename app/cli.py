import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.exporter import Exporter
from app.stroge import Storge
from app import utils


DEFAULT_CONFIG: Dict[str, Any] = {
    "project": {
        "path": "/absolute/path/to/your-godot-project",
        "name": "My Godot Game",
        "description": "",
    },
    "settings": {
        "godot_execute": "",
        "wechat_execute": "",
        "cdn_endpoint": "",
        "cdn_access_key_id": "",
        "cdn_secret_access_key": "",
    },
    "export": {
        "appid": "",
        "device_orientation": "portrait",
        "export_template": "minigame.2d.full_4.4.zip",
        "export_path": "/absolute/path/to/export-output",
        "export_perset": "Web",
        "cdn_bucket": "",
        "auto_subpack": {
            "max_pack_size_mb": 4,
            "pack_name_prefix": "auto-inner",
            "cdn_path": "",
        },
    },
}

SUBPACK_TYPES = {"main", "inner_subpack", "cdn_subpack"}


class CliError(Exception):
    pass


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _prepare_runtime_cwd() -> None:
    os.chdir(_repo_root())


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise CliError(f"配置文件不存在: {path}") from error
    except json.JSONDecodeError as error:
        raise CliError(f"配置文件不是合法 JSON: {path}\n{error}") from error


def _resolve_path(path_str: str, base_dir: Path) -> Path:
    raw = Path(path_str).expanduser()
    if raw.is_absolute():
        return raw.resolve()
    return base_dir.joinpath(raw).resolve()


def _require_string(data: Dict[str, Any], key: str, scope: str) -> str:
    value = str(data.get(key, "")).strip()
    if not value:
        raise CliError(f"缺少必填项: {scope}.{key}")
    return value


def _split_resources_by_size(
    project_root: Path, resources: List[str], max_bytes: int
) -> List[List[str]]:
    groups: List[List[str]] = []
    current_group: List[str] = []
    current_size = 0

    for resource in resources:
        relative_path = resource.removeprefix("res://")
        absolute_path = project_root.joinpath(relative_path)
        size = absolute_path.stat().st_size if absolute_path.exists() else 0

        if current_group and current_size + size > max_bytes:
            groups.append(current_group)
            current_group = []
            current_size = 0

        current_group.append(resource)
        current_size += size

    if current_group:
        groups.append(current_group)

    return groups


def _build_auto_subpacks(
    project_root: Path,
    auto_cfg: Dict[str, Any],
    pack_type: str,
) -> Tuple[List[Dict[str, Any]], utils.AutoSubpackPlan]:
    plan = utils.generate_auto_subpack_plan(project_root)
    if not plan.main_resources:
        raise CliError("自动分包失败：未识别到可导出资源。")

    if pack_type not in {"inner_subpack", "cdn_subpack"}:
        raise CliError(f"自动分包类型非法: {pack_type}")
    max_mb = int(auto_cfg.get("max_pack_size_mb", 4))
    if max_mb <= 0:
        raise CliError("auto_subpack.max_pack_size_mb 必须大于 0")
    max_bytes = max_mb * 1024 * 1024
    prefix = str(auto_cfg.get("pack_name_prefix", "auto-inner")).strip() or "auto-inner"
    cdn_path = str(auto_cfg.get("cdn_path", "")).strip()

    subpacks: List[Dict[str, Any]] = [
        {
            "name": "main",
            "subpack_type": "main",
            "subpack_resource": plan.main_resources,
            "cdn_path": "",
        }
    ]

    if plan.inner_resources:
        groups = _split_resources_by_size(project_root, plan.inner_resources, max_bytes)
        for idx, group in enumerate(groups):
            suffix = _short_pack_hash(project_root, group)
            pack_name = (
                f"{prefix}-{suffix}"
                if len(groups) == 1
                else f"{prefix}-{idx + 1}-{suffix}"
            )
            subpacks.append(
                {
                    "name": pack_name,
                    "subpack_type": pack_type,
                    "subpack_resource": group,
                    "cdn_path": cdn_path if pack_type == "cdn_subpack" else "",
                }
            )

    return subpacks, plan


def _short_pack_hash(project_root: Path, resources: List[str]) -> str:
    digest = hashlib.sha1()
    for resource in sorted(resources):
        digest.update(resource.encode("utf-8"))
        file_path = project_root.joinpath(resource.removeprefix("res://"))
        if file_path.exists():
            stat = file_path.stat()
            digest.update(str(stat.st_size).encode("utf-8"))
            digest.update(str(stat.st_mtime_ns).encode("utf-8"))
    return digest.hexdigest()[:8]


def _select_pack_type(settings_cfg: Dict[str, Any], export_settings: Dict[str, Any]) -> str:
    endpoint = str(settings_cfg.get("cdn_endpoint", "")).strip()
    bucket = str(export_settings.get("cdn_bucket", "")).strip()
    if not endpoint or not bucket:
        return "inner_subpack"

    is_local_endpoint = Exporter._is_local_endpoint(endpoint)
    key_id = str(settings_cfg.get("cdn_access_key_id", "")).strip()
    key_secret = str(settings_cfg.get("cdn_secret_access_key", "")).strip()
    if is_local_endpoint:
        return "cdn_subpack"
    if key_id and key_secret:
        return "cdn_subpack"
    return "inner_subpack"


def _validate_subpacks(subpacks: List[Dict[str, Any]]) -> None:
    if not subpacks:
        return

    names = set()
    has_main = False
    for pack in subpacks:
        name = str(pack.get("name", "")).strip()
        ptype = str(pack.get("subpack_type", "")).strip()
        resources = pack.get("subpack_resource", [])
        if not name:
            raise CliError("subpack_config 中存在空包名。")
        if name in names:
            raise CliError(f"subpack_config 包名重复: {name}")
        names.add(name)
        if ptype not in SUBPACK_TYPES:
            raise CliError(f"subpack_config 类型非法: {ptype}")
        if ptype == "main":
            has_main = True
        if not isinstance(resources, list) or len(resources) == 0:
            raise CliError(f"subpack_config.{name} 缺少资源列表")

    if not has_main:
        raise CliError("开启分包时必须包含一个 main 主包。")


def _normalize_export_config(
    config_path: Path, data: Dict[str, Any]
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], List[str]]:
    base_dir = config_path.parent.resolve()

    project_cfg = data.get("project", {})
    if not isinstance(project_cfg, dict):
        raise CliError("project 配置格式错误，应为对象。")
    project_path = _resolve_path(
        _require_string(project_cfg, "path", "project"),
        base_dir,
    )
    if not project_path.joinpath("project.godot").exists():
        raise CliError(f"project.path 不是有效 Godot 项目目录: {project_path}")
    project_name = str(project_cfg.get("name", "")).strip() or project_path.name
    project_description = str(project_cfg.get("description", "")).strip()

    export_cfg = data.get("export", {})
    if not isinstance(export_cfg, dict):
        raise CliError("export 配置格式错误，应为对象。")
    export_path = _resolve_path(
        _require_string(export_cfg, "export_path", "export"),
        base_dir,
    )
    export_settings: Dict[str, Any] = {
        "appid": _require_string(export_cfg, "appid", "export"),
        "device_orientation": str(export_cfg.get("device_orientation", "portrait")).strip() or "portrait",
        "export_template": _require_string(export_cfg, "export_template", "export"),
        "export_path": export_path.as_posix(),
        "export_perset": _require_string(export_cfg, "export_perset", "export"),
        "subpack_config": [],
        "cdn_bucket": str(export_cfg.get("cdn_bucket", "")).strip(),
    }
    if export_settings["device_orientation"] not in {"portrait", "landscape"}:
        raise CliError("export.device_orientation 仅支持 portrait 或 landscape")

    settings_cfg = data.get("settings", {})
    if not isinstance(settings_cfg, dict):
        raise CliError("settings 配置格式错误，应为对象。")

    auto_cfg = export_cfg.get("auto_subpack", {})
    if auto_cfg is None:
        auto_cfg = {}
    if not isinstance(auto_cfg, dict):
        raise CliError("export.auto_subpack 配置格式错误，应为对象。")

    warnings: List[str] = []
    if "subpack_config" in export_cfg:
        warnings.append("CLI 已固定自动分包，已忽略 export.subpack_config。")

    selected_pack_type = _select_pack_type(settings_cfg, export_settings)
    auto_subpacks, plan = _build_auto_subpacks(project_path, auto_cfg, selected_pack_type)
    export_settings["subpack_config"] = auto_subpacks
    if selected_pack_type == "inner_subpack":
        warnings.append("CDN 配置不完整，自动回退为内分包。")
    else:
        warnings.append("检测到完整 CDN 配置，自动使用 CDN 分包。")
    warnings.extend(plan.warnings)
    _validate_subpacks(export_settings["subpack_config"])

    if any(i.get("subpack_type") == "cdn_subpack" for i in export_settings["subpack_config"]):
        if not export_settings["cdn_bucket"]:
            raise CliError("存在 CDN 分包时，export.cdn_bucket 不能为空。")

    project = {
        "path": project_path.as_posix(),
        "name": project_name,
        "description": project_description,
    }
    return project, export_settings, settings_cfg, auto_cfg, warnings


def _save_settings(settings_cfg: Dict[str, Any]) -> Dict[str, Any]:
    storage = Storge()
    merged = {
        "godot_execute": str(settings_cfg.get("godot_execute", "")).strip(),
        "wechat_execute": str(settings_cfg.get("wechat_execute", "")).strip(),
        "cdn_endpoint": str(settings_cfg.get("cdn_endpoint", "")).strip(),
        "cdn_access_key_id": str(settings_cfg.get("cdn_access_key_id", "")).strip(),
        "cdn_secret_access_key": str(settings_cfg.get("cdn_secret_access_key", "")).strip(),
    }

    if not merged["godot_execute"]:
        raise CliError(
            "缺少 settings.godot_execute。CLI 不依赖 GUI 设置，请在配置文件中填写。"
        )

    storage.save("settings.json", merged)
    return merged


def _cmd_init_config(args: argparse.Namespace) -> int:
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成配置模板: {output}")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    _prepare_runtime_cwd()
    config_path = Path(args.config).expanduser().resolve()
    data = _load_json(config_path)
    project, export_settings, settings_cfg, auto_cfg, warnings = _normalize_export_config(config_path, data)
    merged_settings = _save_settings(settings_cfg)
    exporter = Exporter()

    template_names = {i["filename"] for i in exporter.get_tempalte_json()}
    if export_settings["export_template"] not in template_names:
        raise CliError(
            f"export.export_template 不存在: {export_settings['export_template']}，可选: {sorted(template_names)}"
        )

    if any(i.get("subpack_type") == "cdn_subpack" for i in export_settings["subpack_config"]):
        if not merged_settings.get("cdn_endpoint"):
            raise CliError("存在 CDN 分包，但 settings.cdn_endpoint 为空。")
        is_local_endpoint = Exporter._is_local_endpoint(str(merged_settings.get("cdn_endpoint", "")))
        if not is_local_endpoint:
            if not merged_settings.get("cdn_access_key_id"):
                raise CliError("存在 CDN 分包，但 settings.cdn_access_key_id 为空。")
            if not merged_settings.get("cdn_secret_access_key"):
                raise CliError("存在 CDN 分包，但 settings.cdn_secret_access_key 为空。")

    export_path = Path(export_settings["export_path"])
    export_path.mkdir(parents=True, exist_ok=True)

    total = len(export_settings["subpack_config"])
    print(f"[auto-subpack] 已生成分包数量: {total}")
    if warnings:
        print("[auto-subpack] 提示:")
        for warning in warnings:
            print(f"- {warning}")

    print(f"[export] project: {project['path']}")
    print(f"[export] output : {export_settings['export_path']}")
    exporter.export_project(export_settings, project)
    print("[export] 导出完成。")

    if args.preview:
        wechat_execute = str(merged_settings.get("wechat_execute", "")).strip()
        if not wechat_execute:
            raise CliError("使用 --preview 需要配置 settings.wechat_execute。")
        exporter.preview_project(export_settings)
        print("[preview] 已尝试打开微信开发者工具。")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-love-wechat-cli",
        description="Godot 微信小游戏导出 CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-config", help="生成配置模板 JSON")
    init_parser.add_argument(
        "-o",
        "--output",
        default="./wechat.export.json",
        help="输出配置文件路径，默认 ./wechat.export.json",
    )
    init_parser.set_defaults(func=_cmd_init_config)

    export_parser = subparsers.add_parser("export", help="按配置执行导出")
    export_parser.add_argument(
        "-c",
        "--config",
        required=True,
        help="配置文件路径（JSON）",
    )
    export_parser.add_argument(
        "--preview",
        action="store_true",
        help="导出后用微信开发者工具打开项目",
    )
    export_parser.set_defaults(func=_cmd_export)

    return parser


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except CliError as error:
        print(f"[error] {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
