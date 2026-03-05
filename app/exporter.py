import json
import os
from typing import List, Dict
import zipfile
import tempfile
import re
from app import gdscripts
from app.stroge import Storge
import boto3
from botocore.config import Config
from pathlib import Path
import subprocess
import shutil
from app.platform_utils import resolve_godot_executable, resolve_wechat_cli
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


class Exporter:
    def __init__(self) -> None:
        self.storage: Storge = Storge()

    @staticmethod
    def _engine_pack_path(export_path: str) -> str:
        return os.path.join(export_path, "engine", "godot.zip")

    @staticmethod
    def _subpack_path(export_path: str, pack_name: str) -> str:
        return os.path.join(export_path, "subpacks", f"{pack_name}.zip")

    @staticmethod
    def _resolve_s3_addressing_style(endpoint_url: str) -> str:
        endpoint = str(endpoint_url or "").strip()
        if not endpoint:
            return "virtual"
        try:
            parsed = urlparse(endpoint)
            host = (parsed.hostname or "").lower()
        except Exception:
            host = ""
        if host in {"127.0.0.1", "localhost", "::1"} or host.endswith(".localhost"):
            return "path"
        return "virtual"

    @staticmethod
    def _is_local_endpoint(endpoint_url: str) -> bool:
        endpoint = str(endpoint_url or "").strip()
        if not endpoint:
            return False
        try:
            parsed = urlparse(endpoint)
            host = (parsed.hostname or "").lower()
        except Exception:
            return False
        return host in {"127.0.0.1", "localhost", "::1"} or host.endswith(".localhost")

    @staticmethod
    def _build_local_upload_url(endpoint_url: str, bucket: str, object_key: str) -> str:
        endpoint = str(endpoint_url or "").rstrip("/")
        bucket_path = quote(str(bucket).strip().strip("/"), safe="")
        safe_key = "/".join(quote(part, safe="") for part in object_key.split("/"))
        return f"{endpoint}/{bucket_path}/{safe_key}"

    def _upload_to_local_endpoint(
        self,
        endpoint_url: str,
        bucket: str,
        object_key: str,
        local_file_path: str,
    ) -> None:
        upload_url = self._build_local_upload_url(endpoint_url, bucket, object_key)
        with open(local_file_path, "rb") as pck_file:
            body = pck_file.read()
        request = Request(
            upload_url,
            data=body,
            method="PUT",
            headers={"Content-Type": "application/zip"},
        )
        with urlopen(request, timeout=120) as response:
            status_code = int(getattr(response, "status", 0) or response.getcode())
            if status_code < 200 or status_code >= 300:
                raise RuntimeError(
                    f"mock CDN upload failed: status={status_code}, url={upload_url}"
                )

    def get_tempalte_json(self):
        with open("./templates/template.json", "rb") as f:
            templates = json.loads(f.read())
        return templates

    def get_export_settings(self, project: dict):
        p = os.path.join(project["path"], "minigame.export.json")
        if not os.path.exists(p):
            return {}
        with open(p, "rb") as f:
            export_settings = json.loads(f.read())
            export_settings["export_path"] = os.path.join(
                project["path"], export_settings["export_path"]
            )
        return export_settings

    def export_project(self, export_settings: dict, project: dict):
        exported = self._has_base_template(export_settings["export_path"])
        self.save_export_settings(export_settings, project["path"])
        settings = self.storage.get("settings.json")

        if exported and settings:
            if export_settings["subpack_config"]:
                self.export_subpack(
                    export_settings["subpack_config"],
                    export_settings,
                    project["path"],
                    settings["godot_execute"],
                )
            else:
                gdscripts.set_export_presets(
                    settings["godot_execute"],
                    project["path"],
                    export_settings["export_perset"],
                    config_index=None,
                )
                pckPath = self._engine_pack_path(export_settings["export_path"])
                self.export_pck(project["path"], export_settings, pckPath)
        else:
            with zipfile.ZipFile(
                f"./templates/{export_settings['export_template']}"
            ) as zf:
                zf.extractall(export_settings["export_path"])

        self.replace_gamejson(export_settings)
        self.replace_privatejson(project, export_settings)
        self.replace_projectconfig(project, export_settings)
        self._patch_sdk_bridge(export_settings["export_path"])

        if not (exported and settings):
            pckPath = self._engine_pack_path(export_settings["export_path"])
            if export_settings["subpack_config"]:
                self.export_subpack(
                    export_settings["subpack_config"],
                    export_settings,
                    project["path"],
                    settings["godot_execute"],  # pyright: ignore
                )
            else:
                gdscripts.set_export_presets(
                    settings["godot_execute"],  # pyright: ignore
                    project["path"],
                    export_settings["export_perset"],
                    config_index=None,
                )
                pckPath = self._engine_pack_path(export_settings["export_path"])
                self.export_pck(project["path"], export_settings, pckPath)

    def _patch_sdk_bridge(self, export_path: str) -> None:
        loader_path = Path(export_path).joinpath("js", "loader.js")
        if not loader_path.exists():
            return

        try:
            loader_text = loader_path.read_text(encoding="utf-8")
        except OSError:
            return

        if "window.godotSdk = godotSdk;" in loader_text:
            return

        anchor = "GameGlobal.godotSdk = godotSdk;"
        injection = """GameGlobal.godotSdk = godotSdk;
if (typeof window !== "undefined") {
  window.godotSdk = godotSdk;
}
if (typeof globalThis !== "undefined") {
  globalThis.godotSdk = godotSdk;
}
"""

        if anchor in loader_text:
            patched = loader_text.replace(anchor, injection, 1)
        else:
            fallback_anchor = "const godotSdk = new GodotSDK()"
            fallback_injection = """const godotSdk = new GodotSDK()
if (typeof window !== "undefined") {
  window.godotSdk = godotSdk;
}
if (typeof globalThis !== "undefined") {
  globalThis.godotSdk = godotSdk;
}
"""
            if fallback_anchor not in loader_text:
                return
            patched = loader_text.replace(fallback_anchor, fallback_injection, 1)

        try:
            loader_path.write_text(patched, encoding="utf-8")
        except OSError:
            return

    def replace_gamejson(self, export_settings: dict):
        path = os.path.join(export_settings["export_path"], "game.json")
        gamejson = {}
        if os.path.exists(path):
            with open(path, "rb") as f:
                gamejson = json.loads(f.read())
        gamejson["deviceOrientation"] = export_settings["device_orientation"]
        with open(path, "w+", encoding="utf-8") as f:
            f.write(json.dumps(gamejson, indent=2))

    def replace_privatejson(self, project: dict, export_settings: dict):
        path = os.path.join(
            export_settings["export_path"], "project.private.config.json"
        )
        privatejson = {}
        if os.path.exists(path):
            with open(path, "rb") as f:
                privatejson = json.loads(f.read())
        privatejson["projectname"] = project.get("name", "")
        privatejson["description"] = project.get("description", "")
        privatejson["appid"] = export_settings.get("appid", "")
        with open(path, "w+", encoding="utf-8") as f:
            f.write(json.dumps(privatejson, indent=2))

    def replace_projectconfig(self, project: dict, export_settings: dict):
        path = os.path.join(export_settings["export_path"], "project.config.json")
        project_config = {}
        if os.path.exists(path):
            with open(path, "rb") as f:
                project_config = json.loads(f.read())

        project_config["compileType"] = "game"
        project_config["projectname"] = project.get("name", "")
        project_config["appid"] = export_settings.get("appid", "")
        project_config["libVersion"] = project_config.get("libVersion", "latest")
        project_config["setting"] = project_config.get("setting", {"urlCheck": False})
        project_config["condition"] = project_config.get("condition", {})

        with open(path, "w+", encoding="utf-8") as f:
            f.write(json.dumps(project_config, indent=2))

    def save_export_settings(self, export_settings: dict, project_path: str):
        projectpath = Path(project_path)
        with open(projectpath.joinpath("minigame.export.json"), "w+") as f:
            f.write(json.dumps(export_settings, indent=2))

    def _has_base_template(self, export_path: str) -> bool:
        game_json = os.path.join(export_path, "game.json")
        project_config = os.path.join(export_path, "project.config.json")
        return os.path.exists(game_json) and os.path.exists(project_config)

    def export_pck(self, project_path: str, export_settings: dict, packPath: str):
        settings = self.storage.get("settings.json")
        if settings:
            godot_execute = resolve_godot_executable(settings["godot_execute"])
            result = subprocess.run(
                [
                    godot_execute,
                    "--headless",
                    "--path",
                    project_path,
                    "--export-pack",
                    export_settings["export_perset"],
                    packPath,
                ]
            )
            print(result)

    def preview_project(self, export_settings: dict):
        export_path = export_settings["export_path"]
        settings = self.storage.get("settings.json")
        if settings:
            wechat_execute = resolve_wechat_cli(settings["wechat_execute"])
            # Clear possible stale project cache in WeChat DevTools, then reopen.
            subprocess.run(
                [wechat_execute, "close", "--project", export_path],
                capture_output=True,
                text=True,
            )
            result = subprocess.run(
                [wechat_execute, "open-other", "--project", export_path]
            )
            print(result)

    def export_subpack(
        self,
        subpacks: List[dict],
        export_settings: dict,
        project_path: str,
        godot_execute: str,
    ):
        localpath = Path().absolute().resolve().as_posix()
        tmpdir = os.path.join(localpath, "tmp")
        if not os.path.exists(tmpdir):
            os.mkdir(tmpdir)
        settings = self.storage.get("settings.json")
        if settings:
            for i, pack in enumerate(subpacks):
                gdscripts.set_export_presets(
                    godot_execute, project_path, export_settings["export_perset"], i
                )
                if pack["subpack_type"] == "main":
                    pckPath = self._engine_pack_path(export_settings["export_path"])
                    self.export_pck(project_path, export_settings, pckPath)
                if pack["subpack_type"] == "inner_subpack":
                    pckPath = self._subpack_path(
                        export_settings["export_path"], pack["name"]
                    )
                    self.export_pck(project_path, export_settings, pckPath)

                if pack["subpack_type"] == "cdn_subpack":
                    endpoint_url = str(settings.get("cdn_endpoint", "") or "")
                    pckPath = os.path.join(tmpdir, f"{pack['name']}.zip")
                    self.export_pck(project_path, export_settings, pckPath)
                    remote_dir = self._normalize_remote_path(
                        str(pack.get("cdn_path", "") or "")
                    )
                    upload_path = (
                        f"{remote_dir}/{pack['name']}.zip"
                        if remote_dir
                        else f"{pack['name']}.zip"
                    )

                    if self._is_local_endpoint(endpoint_url):
                        self._upload_to_local_endpoint(
                            endpoint_url,
                            export_settings["cdn_bucket"],
                            upload_path,
                            pckPath,
                        )
                    else:
                        addressing_style = self._resolve_s3_addressing_style(endpoint_url)
                        s3client = boto3.client(
                            "s3",
                            aws_access_key_id=settings["cdn_access_key_id"],
                            aws_secret_access_key=settings["cdn_secret_access_key"],
                            endpoint_url=endpoint_url,
                            config=Config(
                                s3={"addressing_style": addressing_style},
                                signature_version="s3v4",
                            ),
                        )
                        with open(pckPath, "rb") as pck_file:
                            s3client.put_object(
                                Bucket=export_settings["cdn_bucket"],
                                Key=upload_path,
                                Body=pck_file,
                                ContentType="application/zip",
                            )

            self._inject_subpack_bootstrap(
                export_settings["export_path"],
                subpacks,
                export_settings,
                settings,
                project_path,
            )
            shutil.rmtree(tmpdir)

    @staticmethod
    def _normalize_remote_path(path: str) -> str:
        return path.strip().replace("\\", "/").strip("/")

    def _build_cdn_pack_url(
        self, pack: Dict, export_settings: Dict, settings: Dict
    ) -> str:
        pack_name = f"{pack['name']}.zip"
        cdn_path = str(pack.get("cdn_path", "") or "").strip()
        if cdn_path.startswith(("http://", "https://")):
            if cdn_path.endswith(".zip"):
                return cdn_path
            return f"{cdn_path.rstrip('/')}/{pack_name}"

        endpoint = str(settings.get("cdn_endpoint", "") or "").rstrip("/")
        bucket = str(export_settings.get("cdn_bucket", "") or "").strip().strip("/")
        if not endpoint or not bucket:
            return ""

        remote_dir = self._normalize_remote_path(cdn_path)
        object_key = f"{remote_dir}/{pack_name}" if remote_dir else pack_name
        return f"{endpoint}/{bucket}/{object_key}"

    @staticmethod
    def _resolve_main_scene_path(project_path: str, scene_ref: str) -> str:
        if scene_ref.startswith("res://"):
            return scene_ref
        if not scene_ref.startswith("uid://"):
            return scene_ref

        uid_pattern = re.compile(r'\[gd_scene[^\]]*uid="([^"]+)"')
        project_root = Path(project_path)
        for suffix in ("*.tscn", "*.scn"):
            for scene_file in project_root.rglob(suffix):
                try:
                    content = scene_file.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    content = scene_file.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue

                match = uid_pattern.search(content)
                if not match:
                    continue
                if match.group(1) == scene_ref:
                    return f"res://{scene_file.relative_to(project_root).as_posix()}"

        return scene_ref

    def _inject_subpack_bootstrap(
        self,
        export_path: str,
        subpacks: List[dict],
        export_settings: Dict,
        settings: Dict,
        project_path: str,
    ) -> None:
        local_inner_packs = [
            f"subpacks/{pack['name']}.zip"
            for pack in subpacks
            if pack.get("subpack_type") == "inner_subpack"
        ]
        cdn_pack_urls = [
            self._build_cdn_pack_url(pack, export_settings, settings)
            for pack in subpacks
            if pack.get("subpack_type") == "cdn_subpack"
        ]
        cdn_pack_urls = [url for url in cdn_pack_urls if url]

        if not local_inner_packs and not cdn_pack_urls:
            return

        main_pack_path = self._engine_pack_path(export_path)
        if not os.path.exists(main_pack_path):
            return

        with tempfile.TemporaryDirectory() as temp_dir:
            unpack_dir = Path(temp_dir).joinpath("main_pack")
            unpack_dir.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(main_pack_path, "r") as zf:
                zf.extractall(unpack_dir.as_posix())

            project_file = unpack_dir.joinpath("project.godot")
            if not project_file.exists():
                return

            project_text = project_file.read_text(encoding="utf-8")
            main_scene_match = re.search(r"(?m)^run/main_scene=(.+)$", project_text)
            if not main_scene_match:
                return

            original_main_scene = main_scene_match.group(1).strip().strip('"')
            if not original_main_scene:
                return
            boot_scene_res = "res://.wechat_subpack/subpack_boot.tscn"
            if original_main_scene == boot_scene_res:
                previous_manifest_path = unpack_dir.joinpath(
                    ".wechat_subpack", "subpack_manifest.json"
                )
                if previous_manifest_path.exists():
                    try:
                        previous_manifest = json.loads(
                            previous_manifest_path.read_text(encoding="utf-8")
                        )
                        previous_main_scene = str(
                            previous_manifest.get("main_scene", "")
                        ).strip()
                        if previous_main_scene:
                            original_main_scene = previous_main_scene
                    except (json.JSONDecodeError, OSError):
                        pass

            main_scene_path = self._resolve_main_scene_path(project_path, original_main_scene)

            bootstrap_dir = unpack_dir.joinpath(".wechat_subpack")
            bootstrap_dir.mkdir(parents=True, exist_ok=True)
            project_text = re.sub(
                r"(?m)^run/main_scene=.*$",
                f'run/main_scene="{boot_scene_res}"',
                project_text,
                count=1,
            )
            project_file.write_text(project_text, encoding="utf-8")
            # Godot export includes project.binary, which may override project.godot
            # at runtime. Remove it so injected run/main_scene is honored.
            project_binary = unpack_dir.joinpath("project.binary")
            if project_binary.exists():
                project_binary.unlink()

            manifest_path = bootstrap_dir.joinpath("subpack_manifest.json")
            manifest_path.write_text(
                json.dumps(
                    {
                        "main_scene": main_scene_path,
                        "local_packs": local_inner_packs,
                        "cdn_packs": cdn_pack_urls,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            bootstrap_script = bootstrap_dir.joinpath("subpack_boot.gd")
            bootstrap_script.write_text(self._subpack_boot_script(), encoding="utf-8")

            bootstrap_scene = bootstrap_dir.joinpath("subpack_boot.tscn")
            bootstrap_scene.write_text(
                """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://.wechat_subpack/subpack_boot.gd" id="1_subpack_boot"]

[node name="SubpackBoot" type="Node"]
script = ExtResource("1_subpack_boot")
""",
                encoding="utf-8",
            )

            with zipfile.ZipFile(main_pack_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for file_path in sorted(unpack_dir.rglob("*")):
                    if not file_path.is_file():
                        continue
                    archive_name = file_path.relative_to(unpack_dir).as_posix()
                    zf.write(file_path, archive_name)

    @staticmethod
    def _subpack_boot_script() -> str:
        return """extends Node

const MANIFEST_PATH := "res://.wechat_subpack/subpack_manifest.json"
const SDK_RETRY_MAX := 90

var _main_scene := ""
var _local_packs: Array = []
var _cdn_packs: Array = []
var _cdn_index := 0
var _sdk = null
var _sdk_retry_count := 0
var _cb_local_success = null
var _cb_local_error = null
var _cb_cdn_success = null
var _cb_cdn_error = null


func _ready() -> void:
	print("[wechat-subpack] boot scene entered.")
	if not _load_manifest():
		push_error("[wechat-subpack] Failed to load manifest.")
		return

	if _local_packs.is_empty() and _cdn_packs.is_empty():
		_enter_main_scene()
		return

	await _start_download_pipeline()


func _start_download_pipeline() -> void:
	_sdk = JavaScriptBridge.get_interface("godotSdk")
	if _sdk == null:
		if _sdk_retry_count < SDK_RETRY_MAX:
			_sdk_retry_count += 1
			await get_tree().process_frame
			await _start_download_pipeline()
			return
		push_error("[wechat-subpack] godotSdk unavailable, fallback to local mount.")
		_mount_local_packs()
		_enter_main_scene()
		return

	print("[wechat-subpack] godotSdk ready, start downloading subpacks.")

	if _local_packs.is_empty():
		_start_cdn_download()
		return

	_cb_local_success = JavaScriptBridge.create_callback(_on_local_download_success)
	_cb_local_error = JavaScriptBridge.create_callback(_on_local_download_error)
	_sdk.downloadSubpcks(_cb_local_success, _cb_local_error)


func _load_manifest() -> bool:
	if not FileAccess.file_exists(MANIFEST_PATH):
		return false

	var file := FileAccess.open(MANIFEST_PATH, FileAccess.READ)
	if file == null:
		return false

	var json_text := file.get_as_text()
	file.close()

	var parsed = JSON.parse_string(json_text)
	if typeof(parsed) != TYPE_DICTIONARY:
		return false

	_main_scene = str(parsed.get("main_scene", ""))
	if _main_scene == "":
		return false

	var packs = parsed.get("local_packs", [])
	if typeof(packs) == TYPE_ARRAY:
		for pack in packs:
			_local_packs.append(str(pack))

	var cdn_packs = parsed.get("cdn_packs", [])
	if typeof(cdn_packs) == TYPE_ARRAY:
		for url in cdn_packs:
			_cdn_packs.append(str(url))

	return true


func _on_local_download_success(_args) -> void:
	print("[wechat-subpack] local subpacks downloaded.")
	await get_tree().process_frame
	_mount_local_packs()
	_start_cdn_download()


func _on_local_download_error(args) -> void:
	push_error("[wechat-subpack] downloadSubpcks failed: %s" % str(args))
	_mount_local_packs()
	_start_cdn_download()


func _start_cdn_download() -> void:
	if _cdn_packs.is_empty():
		_enter_main_scene()
		return

	_cdn_index = 0
	_download_next_cdn_pack()


func _download_next_cdn_pack() -> void:
	if _cdn_index >= _cdn_packs.size():
		_enter_main_scene()
		return

	var pack_url = str(_cdn_packs[_cdn_index])
	if pack_url == "":
		_cdn_index += 1
		_download_next_cdn_pack()
		return

	_cb_cdn_success = JavaScriptBridge.create_callback(_on_cdn_download_success)
	_cb_cdn_error = JavaScriptBridge.create_callback(_on_cdn_download_error)
	_sdk.downloadCDNSubpcks(pack_url, _cb_cdn_success, _cb_cdn_error)


func _on_cdn_download_success(_args) -> void:
	await get_tree().process_frame
	var pack_url = str(_cdn_packs[_cdn_index])
	_mount_cdn_pack(pack_url)
	_cdn_index += 1
	_download_next_cdn_pack()


func _on_cdn_download_error(args) -> void:
	var pack_url = str(_cdn_packs[_cdn_index])
	push_error("[wechat-subpack] downloadCDNSubpcks failed: %s, url=%s" % [str(args), pack_url])
	_cdn_index += 1
	_download_next_cdn_pack()


func _mount_cdn_pack(pack_url: String) -> void:
	var raw_filename = pack_url.get_file()
	if raw_filename == "":
		push_error("[wechat-subpack] Invalid CDN pack url: %s" % pack_url)
		return

	var clean_url = pack_url
	var query_index = clean_url.find("?")
	if query_index != -1:
		clean_url = clean_url.substr(0, query_index)
	var hash_index = clean_url.find("#")
	if hash_index != -1:
		clean_url = clean_url.substr(0, hash_index)
	var clean_filename = clean_url.get_file()

	var pack_refs: Array = []
	pack_refs.append("subpacks/%s" % raw_filename)
	if clean_filename != "" and clean_filename != raw_filename:
		pack_refs.append("subpacks/%s" % clean_filename)

	var candidates: Array = []
	for ref in pack_refs:
		candidates.append_array(_candidate_pack_paths(str(ref)))

	if not _try_load_pack_paths(candidates):
		push_error("[wechat-subpack] load_resource_pack failed for CDN pack: %s, candidates=%s" % [pack_url, str(candidates)])


func _candidate_pack_paths(pack_ref: String) -> Array:
	var clean = pack_ref.strip_edges()
	var candidates: Array = []
	if clean == "":
		return candidates

	if clean.begins_with("res://"):
		var rel = clean.trim_prefix("res://")
		candidates.append(clean)
		candidates.append(rel)
		candidates.append("/" + rel)
		return candidates

	if clean.begins_with("/"):
		var no_prefix = clean.trim_prefix("/")
		candidates.append(clean)
		candidates.append(no_prefix)
		candidates.append("res://" + no_prefix)
		return candidates

	candidates.append(clean)
	candidates.append("/" + clean)
	candidates.append("res://" + clean)
	return candidates


func _try_load_pack_paths(candidates: Array) -> bool:
	for value in candidates:
		var path = str(value).strip_edges()
		if path == "":
			continue
		if ProjectSettings.load_resource_pack(path):
			return true
	return false


func _mount_local_packs() -> void:
	for pack_ref in _local_packs:
		var candidates = _candidate_pack_paths(str(pack_ref))
		if _try_load_pack_paths(candidates):
			print("[wechat-subpack] local pack mounted: %s" % str(pack_ref))
		else:
			push_error("[wechat-subpack] load_resource_pack failed: %s, candidates=%s" % [str(pack_ref), str(candidates)])


func _enter_main_scene() -> void:
	await get_tree().process_frame
	var scene = load(_main_scene)
	if scene is PackedScene:
		get_tree().change_scene_to_packed(scene)
		return
	get_tree().change_scene_to_file(_main_scene)
"""
