import json
import os
from typing import List
import zipfile
from app import gdscripts
from app.stroge import Storge
import boto3
from botocore.config import Config
from pathlib import Path
import subprocess
import shutil
from app.platform_utils import resolve_godot_executable, resolve_wechat_cli


class Exporter:
    def __init__(self) -> None:
        self.storage: Storge = Storge()

    @staticmethod
    def _engine_pack_path(export_path: str) -> str:
        return os.path.join(export_path, "engine", "godot.zip")

    @staticmethod
    def _subpack_path(export_path: str, pack_name: str) -> str:
        return os.path.join(export_path, "subpacks", f"{pack_name}.zip")

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
                    s3client = boto3.client(
                        "s3",
                        aws_access_key_id=settings["cdn_access_key_id"],
                        aws_secret_access_key=settings["cdn_secret_access_key"],
                        endpoint_url=settings["cdn_endpoint"],
                        config=Config(
                            s3={"addressing_style": "virtual"}, signature_version="v4"
                        ),
                    )

                    pckPath = os.path.join(tmpdir, f"{pack['name']}.zip")
                    self.export_pck(project_path, export_settings, pckPath)
                    upload_path = (
                        os.path.join(pack["cdn_path"], f"{pack['name']}.zip")
                        if pack["cdn_path"]
                        else f"{pack['name']}.zip"
                    )
                    s3client.upload_file(
                        pckPath, export_settings["cdn_bucket"], upload_path
                    )
            shutil.rmtree(tmpdir)
