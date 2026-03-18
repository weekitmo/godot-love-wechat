# Godot小游戏转换工具

# 项目声明
Fork [原仓库](https://github.com/yuchenyang1994/godot-love-wechat)

裁剪或关闭了以下模块：

- 高级文本服务
- 关闭了webrtc
- 关闭了webxr
- 关闭了Openxr
- 关闭了javascript_eval: 本来小游戏就不让eval

导出模板维护地址[https://github.com/yuchenyang1994/godot-minigame-template](https://github.com/yuchenyang1994/godot-minigame-template)

## RoadMap

- [x] 分离导出模板与打包的
- [x] 文件系统解决方案
- [x] 分包管理
- [ ] pck文件brotil压缩与加载


## 支持系统

- Windows 11 因为用了webview2的依赖
- Macos

## 文件系统解决方案

wasm的文件系统方案，godot在web平台的方案是使用indexedb，然后将内存文件系统在合适时机同步到indexedb，小游戏环境并不存在这种东西。所以我的方案是定时将内存的文件系统定时同步到微信的文件系统。
然后在引擎启动后将微信的文件系统文件再同步到wasm的内存文件系统。所以这个方案有个缺点，如果你进行了存档等操作，可能要手动强制同步一下。这个api将在后面版本中提供

## 关于最近小程序开发者工具无法预览的问题！

最近腾讯升级了开发者工具，突然导致无法预览小游戏了。这里给个解决方案

1. 先下载旧版本的开发者工具：[https://developers.weixin.qq.com/community/minihome/doc/000a2202be8d7842ac423d8ff66c01](https://developers.weixin.qq.com/community/minihome/doc/000a2202be8d7842ac423d8ff66c01)
2. 按照下面的方式设置开发者工具并预览游戏

3. 预览后正常后可以照常升级开发者工具就能预览了

## 如何使用

### Godot编辑器设置

打开Godot的导出设置并添加Web导出
![](./pictures/godot1.png)

将你不需要被打包的文件夹或者文件进行过滤, 在Filters to exclude files里面

![](./pictures/godot2.png)

### 导出小工具设置

打开导出工具

![](./pictures/tools1.png)

设置godot引擎目录，和微信开发者工具的地址

![](./pictures/tools2.png)

打开项目列表导入你的项目

![](./pictures/tools3.png)

点击转换
![](./pictures/tools4.png)

单击导出即可

### 微信开发者工具设置

**重点！！！**，想要微信开发者工具预览小游戏你必须做以下设置

1. 打开开发者工具目录中的`code\package.nw\package.json`并进行编辑,并在chromium-args添加--experimental-wasm-eh标志，并重启电脑！
   ![](./pictures/package.json.png)
2. 打开实验性wasm设置，新版本应该都打开了
   ![](./pictures/wasm_exper.png)

3. 导入导出的项目后在安全设置-安全设置中打开服务端口，这样你在导出工具里直接可以按预览按钮即可预览
   ![](./pictures/wechat.png)
   ![](./pictures/wechat2.png)

4. 在设置/通用设置中确保打开GPU加速
   ![](./pictures/wechat3.png)

5. 确保右边项目详情把这些都打开
   ![](./pictures/wchat4.png)

### 文件系统同步

用户文件下的会定时每5秒同步到微信小游戏的文件系统，并在游戏开始前将本地文件复制到内存文件系统中，如果你在游戏中有保存文件的情况请使用API来强制同步一下确保文件落盘。
JavaScript 依赖于垃圾回收，而 Godot 使用引用计数进行内存管理。这意味着你必须显式创建回调（它们本身作为 JavaScriptObjects 返回）并且必须保留它们的引用

```gdscript
var sdk = JavaScriptBridge.get_interface("godotSdk")
var _on_sucess = JavaScriptBridge.create_callback(on_sync_sucess)
var _on_error = JavaScriptBridge.create_callback(on_sync_error)

func _ready():
    sdk.syncfs(_on_sucess, _on_error)

func on_sync_sucess(args):
    # 成功回调

func on_sync_error(error):
    # 失败回调
```

### 分包管理
分包管理有些复杂具体情况可以看视频讲解
[https://www.bilibili.com/video/BV18rRhYmEvd](https://www.bilibili.com/video/BV18rRhYmEvd)

#### 自动分包（通用策略）

工具内“自动分包”按钮会按以下规则生成：

1. 主包：最小主包策略，默认只保留 `project.godot`、`default_bus_layout.tres` 和 `autoload` 依赖闭包；
2. 子包：其余资源自动归入 `auto-inner`，并按 4MB 自动拆分为 `auto-inner-1/2/...`；
3. 兜底：如果无法识别 `run/main_scene`，会自动回退为“不拆分”（全部放主包），避免导出不可运行。

> 注意：自动分包基于静态依赖分析。运行时字符串拼接路径、网络下载资源等动态加载场景无法 100% 推断，建议在关键场景自行验证。

自动分包完成后，导出器会自动注入启动胶水层（无需手写 `["subpacks/xxx.zip"]`）：

1. 将原 `run/main_scene` 改为一个临时启动场景；
2. 启动场景通过 `godotSdk.downloadSubpcks` 下载并写入所有本地内分包；
3. 若存在 CDN 分包，按清单调用 `godotSdk.downloadCDNSubpcks` 下载；
4. 按清单逐个 `ProjectSettings.load_resource_pack(...)` 挂载；
5. 最后跳转回原始主场景。

支持多个内分包（例如 `auto-inner-1`, `auto-inner-2`, ...）。

#### 分包运行机制说明（为什么 Network 看不到 auto-inner.zip）

这是微信小游戏分包机制本身的表现，不是没生效：

1. 模板先调用 `wx.loadSubpackage({ name: "subpacks" })`，拉取的是整个 `subpacks` 子包；
2. 子包代码里再用 `fs.readFile("subpacks/*.zip")` 读取 zip，并写入 Godot 的虚拟文件系统；
3. Godot 启动胶水层执行 `ProjectSettings.load_resource_pack(...)` 挂载 zip；
4. 挂载成功后再切回原始主场景。

所以你通常会看到 `subpacks/game.js` 的加载，不一定会看到单独 `auto-inner.zip` 的网络请求。

### CLI 导出（配置文件 + 命令）

除了 GUI，也支持 CLI 批处理导出，适合自动化构建。

1. 安装依赖：

```bash
uv sync
```

2. 生成配置模板：

```bash
uv run python -m app.cli init-config -o ./wechat.export.json
```

3. 编辑 `wechat.export.json`（只填必要字段：`project`、`settings`、`export`）；

4. 执行导出：

```bash
uv run python -m app.cli export -c ./wechat.export.json
```

5. 导出后自动打开微信开发者工具（可选）：

```bash
uv run python -m app.cli export -c ./wechat.export.json --preview
```

CLI 固定为自动分包模式，会自动生成主包 + 子包（默认 4MB 切分，支持多包），无需手写 `subpack_config`。
分包类型自动判定：CDN 配置完整则走 `cdn_subpack`，否则自动回退 `inner_subpack`。
每个自动子包名会带短 hash（例如 `auto-inner-1-a1b2c3d4`）用于版本区分。

### 本地模拟 CDN 分包（Node.js）

如果你暂时没有真实 CDN，可以直接在仓库目录启动一个本地 mock CDN：

```bash
node ./tools/mock-cdn-server.mjs
```

默认监听 `http://127.0.0.1:39090`，文件落盘在 `./mock-cdn-data`。

导出配置建议：

1. `settings.cdn_endpoint = "http://127.0.0.1:39090"`
2. `settings.cdn_access_key_id/cdn_secret_access_key` 可填任意占位值（本地 mock 不校验）
3. `export.cdn_bucket = "test-bucket"`
4. 无需配置 `pack_type`，CLI 会自动判定是否使用 CDN 分包
5. 如需“上传走内网地址、运行时走公网别名”，可额外设置 `settings.cdn_public_endpoint`（留空则默认使用 `settings.cdn_endpoint`）

导出时会把 zip 上传到：

```txt
http://127.0.0.1:39090/<cdn_bucket>/<cdn_path>/<pack_name>.zip
```

运行时会通过 `downloadCDNSubpcks(url)` 发起网络请求，你会在开发者工具 Network 里看到对应 URL。

## 常见问题

1. 打开报错

   ```txt
   CompileError: WebAssembly.instantiate(): unexpected section (enable with --experimental-wasm-eh)
   @+58331(env: Windows,mg,1.06.2409140; lib: 3.6.6)
   ```

参考上面的微信开发者工具设置，需要你修改下微信开发者工具，后面好像小游戏开发者工具自带

2. 打开报错类似这样

   ```txt
   godot.js? [sm]:483 USER ERROR: Cannot get class 'SubViewportContainer'.
   godot.js:6883 USER SCRIPT ERROR: Parse Error: Could not find base class "RichTextLabel".
   ```

   精简版导出模板去除了高级gui，如果你项目使用了高级GUI,那么就会导致这样的错误，可以使用完整版模板导出，**注意，导出工具只有在第一次导出时会将整个模板导出，后续只会导出pck，所以如果发生这样的问题，请将导出目录下的所有文件删除，或者删除game.json**

3. 如何调用微信的api工具？

   参考文档：https://docs.godotengine.org/en/stable/classes/class_javascriptbridge.html 使用godot的js bridge 来进行，也可以自己尝试封装一些sdk
   目前来说，对于http请求，websocket这些都可以直接使用godot内置的工具，都进行了适配，如果不行就参考文档通过jsbridge进行封装

4. IOS手机预览后无法打开

   IOS需要在微信开放平台打开高性能+模式后才能开启WEBGL2的支持，Godot4最低支持到WEBGL2, WEBGL不再支持了。

5. 为什么不支持C#？

   这个问题主要是Godot4全面转向.netcore,与unity不同，unity依然使用mono来执行c#，而且unity（这里指的团结，他那个是解释C#速度比gds还慢）也不是完整的C#，这里主要是微软那边对于动态链接wasm没有提供入口。
   据说呢，要等到.net9才能完成这项工作，godot官方不想因为马上就要有的工作而浪费大量时间适配，所以暂时或者很长一段时间是不会支持C#的。而且在小游戏环境当中，如果再带一个C#运行时并不是一件划算的事情。
   在小游戏有限的空间内已经没办法再放下一个C#运行时了，小游戏的限制：所有分包大小不能超过30M，所有本地存储不能超过100M。

6. 是否支持第三方插件？

   如果你的第三方插件是纯gds写的那肯定是支持的，如果你的插件是C++写的大概率不会支持，开启C++需要额外的wasm库进行动态链接，如果开启wasm动态链接需要支持多线程，小游戏平台是不能开启wasm多线程的！
