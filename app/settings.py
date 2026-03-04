from dataclasses import dataclass, field
from nicegui import ui, app, run
from app.stroge import Storge
from app.platform_utils import godot_file_types, is_windows
import webview


@dataclass
class SettingsItem:
    godot_execute: str
    wechat_execute: str
    cdn_endpoint: str = field(default="")
    cdn_access_key_id: str = field(default="")
    cdn_secret_access_key: str = field(default="")
    cdn_session_token: str = field(default="")


def settings():
    setting_item = SettingsItem(godot_execute="", wechat_execute="")
    storge = Storge()
    settings_data = storge.get("settings.json")

    if settings_data:
        setting_item.godot_execute = settings_data["godot_execute"]
        setting_item.wechat_execute = settings_data["wechat_execute"]
        setting_item.cdn_endpoint = settings_data.get("cdn_endpoint")
        setting_item.cdn_access_key_id = settings_data.get("cdn_access_key_id")
        setting_item.cdn_secret_access_key = settings_data.get("cdn_secret_access_key")

    async def save_settings():
        await run.io_bound(
            storge.save,
            "settings.json",
            {
                "godot_execute": setting_item.godot_execute,
                "wechat_execute": setting_item.wechat_execute,
                "cdn_endpoint": setting_item.cdn_endpoint,
                "cdn_access_key_id": setting_item.cdn_access_key_id,
                "cdn_secret_access_key": setting_item.cdn_secret_access_key,
            },
        )
        ui.notify("保存成功！")

    async def choose_godot():
        file_types = godot_file_types()
        file = await app.native.main_window.create_file_dialog(dialog_type=webview.OPEN_DIALOG, allow_multiple=False, file_types=file_types)  # type: ignore
        if file:
            setting_item.godot_execute = file[0]

    async def choose_wechat():
        dialog_type = webview.FOLDER_DIALOG if is_windows() else webview.OPEN_DIALOG
        file_types = () if is_windows() else ("Wechat DevTools (*.app)", "Executable (*)")
        file = await app.native.main_window.create_file_dialog(dialog_type=dialog_type, allow_multiple=False, file_types=file_types)  # type: ignore
        if file:
            setting_item.wechat_execute = file[0]

    with ui.column(align_items="start").classes("w-full p-2"):
        with ui.row().classes("border-b pb-2 w-full"):
            ui.markdown("### 设置")
        with ui.input(
            placeholder="godot引擎的执行目录，用来导出pck包", label="godot引擎"
        ).classes("w-full") as i:
            i.bind_value(setting_item, "godot_execute")
            ui.button(icon="folder_open", on_click=choose_godot).props("flat dense")

        with ui.input(
            placeholder="微信开发者工具目录，用来预览小游戏", label="微信开发者工具目录"
        ).classes("w-full") as i:
            i.bind_value(setting_item, "wechat_execute")
            ui.button(icon="folder_open", on_click=choose_wechat).props("flat dense")

        with ui.input(
            placeholder="你的支持S3协议CDN地址,咨询你的CDN服务商",
            label="S3 EndPoint",
        ).classes("w-full") as i:
            i.bind_value(setting_item, "cdn_endpoint")

        with ui.input(
            placeholder="你的支持S3协议CDN Access Key ID", label="Access Key ID"
        ).classes("w-full") as i:
            i.bind_value(setting_item, "cdn_access_key_id")

        with ui.input(
            placeholder="你的支持S3协议CDN Secret Access Key", label="Secret Access Key"
        ).classes("w-full") as i:
            i.bind_value(setting_item, "cdn_secret_access_key")

        with ui.column(align_items="end").classes("w-full mt-4"):
            ui.button("保存", icon="save", on_click=save_settings)
