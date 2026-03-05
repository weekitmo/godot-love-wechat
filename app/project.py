from pathlib import Path
from typing import List
from nicegui import run, ui, app
from nicegui.elements.dialog import Dialog
from nicegui.elements.tree import Tree
import webview
import os
import re
from app import gdscripts, utils
from app.stroge import Storge
from app.exporter import Exporter
from dataclasses import dataclass, field
from app.platform_utils import get_godot_version


@dataclass
class ProjectsStorge:
    storge: Storge = field(default_factory=Storge)
    export_loading: bool = False

    def get_project_by_id(self, id: str):
        projects = self.storge.get("projects.json")
        if not projects:
            return None
        for project in projects:
            if project["id"] == id:
                return project

    def get_get_execute(self):
        settings = self.storge.get("settings.json")
        if settings:
            return settings.get("godot_execute")


@dataclass
class ExportSettings:
    appid: str = field(default="")
    device_orientation: str = field(default="portrait")
    export_template: str = field(default="")
    export_path: str = field(default="")
    export_perset: str = field(default="")
    subpack_config: List[dict] = field(default_factory=list)
    cdn_bucket: str = field(default="")

    def to_dict(self):
        return {
            "appid": self.appid,
            "device_orientation": self.device_orientation,
            "export_template": self.export_template,
            "export_path": self.export_path,
            "export_perset": self.export_perset,
            "subpack_config": self.subpack_config,
            "cdn_bucket": self.cdn_bucket,
        }

    def from_dict(self, settings: dict):
        self.appid = settings["appid"]
        self.device_orientation = settings["device_orientation"]
        self.export_template = settings["export_template"]
        self.export_path = settings["export_path"]
        self.export_perset = settings.get("export_perset", "")
        self.subpack_config = settings.get("subpack_config", [])
        self.cdn_bucket = settings.get("cdn_bucket", "")


stroge = ProjectsStorge()
export_settings = ExportSettings()
exporter = Exporter()


def project_info(project):
    async def on_click_export():
        export_button.disable()
        export_button.props(add="loading")
        subpack_types = [i["subpack_type"] for i in export_settings.subpack_config]
        settings = stroge.storge.get("settings.json")
        if not settings:
            ui.notify("没有进行设置，无法导出！", type="negative")
            return
        if not export_settings.export_path:
            ui.notify("未填写导出目录", type="negative")
            return
        if not export_settings.export_template:
            ui.notify("未选择导出模板", type="negative")
            return
        if not export_settings.appid:
            ui.notify("未填写APPID", type="negative")
            return
        if not export_settings.export_perset:
            ui.notify("未填写导出预设", type="negative")
            return
        if export_settings.subpack_config and "main" not in subpack_types:
            ui.notify("未能填写主包", type="negative")
            return
        if "cdn_subpack" in subpack_types and export_settings.cdn_bucket == "":
            ui.notify("包含CDN包，但未填写CDN的Bucket")
            return
        if "cdn_subpack" in subpack_types:
            if not settings.get("cdn_endpoint"):
                ui.notify("包含CDN包，但未设置CDN的Endpoint", type="negative")
                return

            if not settings.get("cdn_access_key_id"):
                ui.notify("包含CDN包，但未设置CDN的Access Key ID", type="negative")
                return

            if not settings.get("cdn_secret_access_key"):
                ui.notify("包含CDN包，但未设置CDN的Secret Access_key", type="negative")
                return

        await run.io_bound(exporter.export_project, export_settings.to_dict(), project)
        export_button.enable()
        export_button.props(remove="loading")
        ui.notify("导出成功", type="positive")

    async def preview_project():
        if not os.path.exists(os.path.join(export_settings.export_path, "game.json")):
            ui.notify("请先导出项目再预览", type="negative")
        await run.io_bound(exporter.preview_project, export_settings.to_dict())

    with ui.row(align_items="center").classes("w-full"):
        icon = project.get("icon", "/assets/logo.svg")
        if icon != "/assets/logo.svg" and not os.path.exists(icon):
            icon = "/assets/logo.svg"
        with ui.column(align_items="center").classes("w-1/5"):
            ui.image(icon).classes("w-32 h-32")
        with ui.column(align_items="baseline").classes("w-2/5 mt-2"):
            ui.label(project["name"]).classes("text-h6")
            ui.label(f"Version: {project["version"]}").classes("text-subtitle2")
            ui.label(project["description"]).classes("text-caption")

        ui.space()
        with ui.column(align_items="start").classes("w-1/5 p-4"):
            with ui.button(
                "导出", on_click=on_click_export, icon="import_export"
            ) as export_button:
                export_button.add_slot(
                    "loading",
                    """
                                   <q-spinner-facebook />
                                   """,
                )
            ui.button("预览", icon="play_arrow", on_click=preview_project)
            ui.button(
                "返回", icon="arrow_back", on_click=lambda: ui.navigate.to("/")
            ).props("outline")


def export_config(project):
    templates = exporter.get_tempalte_json()
    templates_options = {i["filename"]: i["name"] for i in templates}
    project_export_settings = exporter.get_export_settings(project)
    export_presets = gdscripts.get_export_presets(
        stroge.get_get_execute(), project["path"]  # pyright: ignore
    )
    if not export_presets:
        ui.notify("未能找到导出预设，请设置", type="negative")

    if project_export_settings:
        export_settings.from_dict(project_export_settings)

    async def chosse_export_path():
        file = await app.native.main_window.create_file_dialog(dialog_type=webview.FOLDER_DIALOG, allow_multiple=False, file_types=())  # type: ignore
        if file:
            export_settings.export_path = file[0]

    with ui.row(align_items="start").classes("w-full border-b p-4"):
        ui.label("导出设置")
    with ui.column(align_items="start").classes("w-full p-4"):
        with ui.row(align_items="center").classes("border-b w-full p-2"):
            ui.label("APPID")
            ui.space()
            ui.input().props("outlined outlined dense").classes("w-64").bind_value(
                export_settings, "appid"
            )
        with ui.row(align_items="center").classes("border-b w-full p-2"):
            ui.label("屏幕方向")
            ui.space()
            ui.select({"portrait": "竖向", "landscape": "横向"}).props(
                "outlined outlined dense"
            ).classes("w-64").bind_value(export_settings, "device_orientation")
        with ui.row(align_items="center").classes("border-b w-full p-2"):
            ui.label("导出预设")
            ui.space()
            ui.select(export_presets).props("outlined outlined dense").classes(
                "w-64"
            ).bind_value(export_settings, "export_perset")
        with ui.row(align_items="center").classes("border-b w-full p-2"):
            ui.label("导出模板")
            ui.space()
            ui.select(templates_options).props("outlined outlined dense").classes(
                "w-64"
            ).bind_value(export_settings, "export_template")

        with ui.row(align_items="center").classes("border-b w-full p-2"):
            ui.label("CDN Bucket")
            ui.space()
            ui.input(placeholder="上传CDN的Bucket名称").props(
                "outlined outlined dense"
            ).classes("w-64").bind_value(export_settings, "cdn_bucket")

        with ui.row(align_items="center").classes("border-b w-full p-2"):
            ui.label("导出目录")
            ui.space()
            with (
                ui.input()
                .props("outlined outlined dense")
                .classes("w-64")
                .bind_value(export_settings, "export_path")
            ):
                ui.button(icon="folder_open", on_click=chosse_export_path).props(
                    "flat dense"
                )


@dataclass
class SubpackConfig:
    change_mode = False
    change_index = 0
    subpack_resource: List[str] = field(default_factory=lambda: [])
    subpack_type: str = field(default="")
    name: str = field(default="")
    cdn_path: str = field(default="")

    def clear(self):
        self.change_mode = False
        self.change_index = 0
        self.subpack_resource = []
        self.subpack_type = ""
        self.name = ""
        self.cdn_path = ""


subpack_type = {
    "main": "主包",
    "inner_subpack": "内分包",
    "cdn_subpack": "CDN分包",
}


subpack_cfg = SubpackConfig()
AUTO_INNER_SUBPACK_MAX_BYTES = 4 * 1024 * 1024


@ui.refreshable
def subpacks_ui(modal: Dialog, tree: Tree):
    def on_delete(i):
        export_settings.subpack_config.pop(i)
        subpacks_ui.refresh()

    def on_edit(i):
        subpack_cfg.change_mode = True
        subpack_cfg.change_index = i
        tree.untick()
        task = export_settings.subpack_config[i]
        subpack_cfg.name = task["name"]
        subpack_cfg.subpack_type = task["subpack_type"]
        subpack_cfg.subpack_resource = task["subpack_resource"]
        subpack_cfg.cdn_path = task["cdn_path"]
        if not task["cdn_path"]:
            subpack_cfg.cdn_path = None  # pyright: ignore

        tree.tick(task["subpack_resource"])
        modal.open()

    with ui.column(align_items="start").classes("w-full p-4"):
        for i, task in enumerate(export_settings.subpack_config):
            with ui.row(align_items="center").classes("border-b w-full p-2"):
                ui.label(task["name"])
                ui.badge(subpack_type[task["subpack_type"]])
                if task.get("cdn_path"):
                    cdn_path = os.path.join(
                        task.get("cdn_path", ""), f"{task["name"]}.zip"
                    )
                    ui.label(f"CDN目录: {cdn_path}")
                ui.space()
                ui.button("修改", on_click=lambda i=i: on_edit(i)).props("flat")
                ui.button(on_click=lambda: on_delete(i), icon="delete").props(
                    "flat fab-mini color=grey"
                )


def subpack_config(project):
    project_path = Path(project["path"]).resolve()
    file_tree = utils.build_tree_dict(project_path)
    modal = ui.dialog().classes("max-w-[800px]")

    def split_resources_by_size(resources: List[str]) -> List[List[str]]:
        groups: List[List[str]] = []
        current_group: List[str] = []
        current_size = 0

        for resource in resources:
            relative_path = resource.removeprefix("res://")
            absolute_path = project_path.joinpath(relative_path)
            size = absolute_path.stat().st_size if absolute_path.exists() else 0

            if (
                current_group
                and current_size + size > AUTO_INNER_SUBPACK_MAX_BYTES
            ):
                groups.append(current_group)
                current_group = []
                current_size = 0

            current_group.append(resource)
            current_size += size

        if current_group:
            groups.append(current_group)

        return groups

    def on_tick(e):
        subpack_cfg.subpack_resource = e.value

    def on_add_pck():
        if subpack_cfg.name == "":
            ui.notify("未填写包名", type="negative")
            return
        if subpack_cfg.subpack_type == "":
            ui.notify("未填写包类型", type="negative")
            return
        if len(subpack_cfg.subpack_resource) == 0:
            ui.notify("未选择资源", type="negative")
            return

        new_pack = {
            "name": subpack_cfg.name,
            "subpack_type": subpack_cfg.subpack_type,
            "subpack_resource": subpack_cfg.subpack_resource.copy(),
            "cdn_path": subpack_cfg.cdn_path,
        }
        if subpack_cfg.change_mode:
            export_settings.subpack_config[subpack_cfg.change_index] = new_pack
        else:
            export_settings.subpack_config.append(new_pack)
        tree.untick()  # pyright: ignore
        subpack_cfg.clear()
        subpacks_ui.refresh()
        modal.close()

    async def on_auto_subpack():
        plan = await run.io_bound(utils.generate_auto_subpack_plan, project_path)
        if not plan.main_resources:
            ui.notify("自动分包失败：未识别到可导出资源", type="negative")
            return

        subpacks = [
            {
                "name": "main",
                "subpack_type": "main",
                "subpack_resource": plan.main_resources,
                "cdn_path": "",
            }
        ]
        if plan.inner_resources:
            grouped_inner_resources = split_resources_by_size(plan.inner_resources)
            for idx, group in enumerate(grouped_inner_resources):
                pack_name = (
                    "auto-inner"
                    if len(grouped_inner_resources) == 1
                    else f"auto-inner-{idx + 1}"
                )
                subpacks.append(
                    {
                        "name": pack_name,
                        "subpack_type": "inner_subpack",
                        "subpack_resource": group,
                        "cdn_path": "",
                    }
                )
        export_settings.subpack_config = subpacks
        subpacks_ui.refresh()

        stats = plan.stats
        inner_pack_count = max(0, len(subpacks) - 1)
        ui.notify(
            f"自动分包完成：主包 {stats.get('main_count', 0)} 项，子包 {stats.get('inner_count', 0)} 项（共 {inner_pack_count} 个分包）",
            type="positive",
        )
        if plan.warnings:
            ui.notify(
                f"自动分包提示：{plan.warnings[0]}",
                type="warning",
            )

    with modal, ui.card().style("width: 800px; max-width: None"):
        with ui.row(align_items="start").classes("w-full h-96"):
            with ui.column().classes("h-full overflow-auto w-[360px]"):
                tree = (
                    ui.tree(
                        [file_tree],  ## pyright: ignore
                        label_key="label",
                        tick_strategy="leaf",
                    )
                    .expand()
                    .on_tick(on_tick)
                )
            with ui.column().classes("h-full w-[350px]"):
                ui.input("名称").props("outlined").classes("w-full").bind_value(
                    subpack_cfg, "name"
                )
                ui.select(subpack_type).props("outlined").classes("w-full").bind_value(
                    subpack_cfg, "subpack_type"
                )
                ui.input(
                    "CDN上传目录",
                    placeholder="上传到CDN的目录，选填",
                ).props(
                    "outlined"
                ).classes("w-full").bind_value(subpack_cfg, "cdn_path")
        with ui.row(align_items="end").classes("w-full"):
            ui.space()
            ui.button("确定").on_click(on_add_pck)
            ui.button("取消").on_click(lambda: modal.close())

    with ui.row(align_items="center").classes("w-full border-b p-4 justify-between"):
        ui.label("分包配置")
        with ui.row(align_items="center"):
            ui.button("自动分包", on_click=on_auto_subpack).props("outline")
            ui.button("新增分包", on_click=modal.open)

    subpacks_ui(modal, tree)  # pyright: ignore


def project(id: str):
    project = stroge.get_project_by_id(id)
    with ui.column(align_items="start").classes("w-full p-2 overflow-auto"):
        with ui.card(align_items="start").tight().classes("w-full"):
            project_info(project)
        with ui.card(align_items="start").tight().classes("w-full"):
            export_config(project)
        with ui.card(align_items="start").tight().classes("w-full"):
            subpack_config(project)
