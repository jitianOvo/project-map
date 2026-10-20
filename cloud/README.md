# 项目航图 · 安卓与云服务

这是项目航图的安卓客户端与服务器工程。Windows 云功能已经合并进同级 `项目航图` 项目的原有本地编辑器，不再维护第二套 Windows 编辑界面。手机通过同一账户同步电脑的 Markdown 和图片。

## 开始使用

1. 电脑继续启动 `../项目航图/dist/项目航图.exe`，在“设置”→“数据目录”选择大纲与图片目录，在“云同步”登录并启用同步。旧云端 exe 与本目录启动脚本也会转到这个统一程序，不再开另一套项目库。
2. 安卓手机安装 `dist/项目航图-云端.apk`，点击「登录」，默认服务器地址是 `https://jitian666.me/project-map/`。首次账户信息在本地 `.secrets/云端首次登录.txt`。
3. 两端登录同一个账户，电脑当前 Markdown 文件夹中的大纲会自动参与同步，无需再导入到独立的 Windows 云端工作区。
4. 也可直接使用 HTTPS 网页版。网页版没有打包离线界面，重新打开页面需要网络；已打开页面的编辑内容仍先保存在本机。

## 自动登录（v4.1.0）

电脑云同步设置和手机登录窗口都默认勾选“记住登录，下次自动登录”。首次输入账号密码登录后，重开应用直接恢复登录；普通会话过期时自动续期。取消勾选只登录本次；退出账号会清除本机记住的登录，不删除本地大纲。

自动登录与自动云同步是独立选项。记住的是随机登录令牌，不保存密码：电脑由 Windows 系统保护，手机由 Android Keystore 的 AES-GCM 加密保存；网页版使用当前浏览器的本地存储。普通会话有效 30 天，自动登录凭据在续期时更新其 180 天有效期，长期未使用、被撤销或损坏后仍需重新输入密码。断网不会清除记住的账号。

Windows 的统一数据默认放在项目航图外层 `Markdown`、`Media`、`Data`、`Backups`。源码版与内层单文件版共用配置，也可以手动选择其他大纲与缓存文件夹。原有两份资料已先备份再合并，重复以内层常用版为准。首次连接云账号前，只在本机保存，不自动上传。

## 已有功能

- 项目新建、属性、分组、置顶、拖动排序、搜索、回收站与恢复。同名项目以 UUID 区分。
- 编辑 / 预览 / 分栏，实时 Markdown 渲染，独立缩放，自动换行选择，浅色 / 深色主题，目录 / 任务 / 信息面板。
- H1–H6、粗体、斜体、删除线、下划线、列表、任务、引用、代码块、链接、分隔线、文字优先级；再次使用可取消对应格式。
- 标准序号回车续写，Shift+回车插入并重排，Tab 纠正非标准编号后缩进，Shift+Tab 批量取消缩进。
- Vn / 子版本插入与后续编号调整，查找替换，快速工具和格式工具排序及隐藏。
- 图片选择、图片粘贴（取决于系统剪贴板支持）、本地缓存、同步，预览整体缩放，双击图片后独立缩放 / 手机双指缩放。
- 本机自动保存，项目光标与滚动位置记忆，云端历史版本恢复，Markdown 导出、完整备份导入导出。

手机没有鼠标时，点击格式工具即可完成常用操作；工具栏放不下时横向滑动。项目排序可长按拖动，也可通过项目属性和置顶管理。连接实体键盘时，编辑快捷键同样可用。

## 同步和数据保护

每个项目都有独立 ID、基础版本和本地修改。设备先写本地数据库，再发送一个带唯一操作 ID 的完整快照；断网会延迟重试，不丢掉未同步内容。

- 不同段落的同时修改：服务器尝试三方合并。
- 同一处修改、同时改成不同属性、删除与编辑冲突：保留原项目和「冲突副本」，不静默覆盖。
- 网络请求期间继续输入：返回后重新对照最新本地内容，不把请求发出之后的新输入抹掉。
- 修改很大的文档无法可靠合并时：优先保留副本。不是字符级实时协同，也不会显示另一端光标。
- 当前客户端大约每 5 秒检查更新；本地变动会提前安排同步，失败后退避到最长 60 秒。网页退到后台或手机休眠时，系统可暂停网络；重新进入会继续同步。

优先级、置顶、排序、分组和正文随项目同步。主题、布局、光标和滚动位置属于各设备，不互相覆盖。

## 图片与迁移

插入的图片按 SHA-256 去重，并使用 `Media/<图片哈希>.<扩展名>` 的相对 Markdown 地址。图片实际保存在本机数据库和服务端 `runtime/media`；不依赖 Windows 临时目录。

单独导出的 `.md` 不包含图片文件。跨设备完整迁移，请用「导出备份」生成 JSON，里面包含项目和本机已缓存的图片；导入后生成独立项目，不覆盖现有大纲。导入外部 Markdown 时，原文件里的电脑绝对图片路径不会自动读取；请重新插入图片，或从云端版导出的完整备份导入。

每个大纲最多 2 MB，单张图片最多 12 MB。完整备份会先补齐程序管理的图片；如果有图片未同步，提示联网重试，不静默生成缺图备份。云端服务端的完整备份应包含数据库、图片和账户配置，详见 [部署说明](docs/部署与维护.md)。

## 目录

| 目录 | 用途 |
|---|---|
| `server/` | Python 标准库 HTTP 服务、账户、SQLite、版本与合并 |
| `web/` | 共享编辑界面，按保存 / 同步 / 编辑 / 预览 / 项目管理分模块 |
| `android/` | Java Android WebView 外壳、离线资源、图标 |
| `windows/` | 兼容旧路径的统一入口，转到原项目航图单文件程序 |
| `deploy/` | 专属 Nginx 路由与 systemd 服务 |
| `scripts/` | 构建、打包和上线验证 |
| `tests/` | 合并、幂等、编辑规则、两端协作与界面测试 |
| `.secrets/` | 本地首次登录信息和 APK 更新签名密钥；不公开 |
| `dist/` | APK 与 Windows 运行目录 |

## 构建

本轮使用现有 Python 3.11、Node.js、Android Studio JBR 21、Android SDK 32 / Build Tools 30.0.3，没有修改 SDK 安装目录。为兼容 JBR，在本项目 `.toolchains` 中使用固定版本 Google R8 9.5.22，并校验哈希。

```powershell
npm ci --ignore-scripts --cache .cache/npm
python scripts/build_assets.py
pwsh -NoProfile -File scripts/build_android.ps1
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r windows/requirements-build.txt --cache-dir .cache/pip
pwsh -NoProfile -File scripts/build_windows.ps1
python -m pytest tests --basetemp .cache/tests
npm test
python tests/qt_smoke.py
```

Android 支持 Android 8.0 及以上，目标 SDK 为 32，供自行安装验证。后续升级 APK 必须保留 `.secrets/android-release.jks` 及其密码，否则无法覆盖安装。Windows 主程序仍为原项目航图的单文件 EXE；这里的兼容入口只是启动它，不使用旧 `_internal` 云编辑器。

兼容入口使用本项目的独立环境和 PyInstaller 6.22.3 构建；统一主程序的构建在 `../项目航图/scripts/build.ps1`。历史缓存保留供迁移回溯，不再作为当前 Windows 数据源。Android 设备仍需可用的现代 Android System WebView；过旧时会提示更新。

已获授权并在 RMX3850 / Android 15 真机完成 ADB 测试：原生回车续号、密码输入和登录点击、强制关闭后自动登录、过期续期、取消记住与退出、图片显示和查看器缩放、后台切换、断网编辑重开、与 Windows 单文件程序同步。详细范围与证据见 [v4.1.0 测试记录](docs/2026-10-07_自动登录与真机测试.md)。

测试用独立测试服务器和公开示例，没有修改私人项目。正式 APK 不包含可用调试入口，仅测试包开启 WebView 调试与本机 HTTP 测试。Windows 下旧版 aapt2 将资源路径打包成反斜杠的问题已修复，构建时统一为 Android 规范路径并校验 CRC，避免出现“网页无法打开”。

## 参考

离线优先和保留冲突副本的设计参考 [Android 离线优先架构](https://developer.android.com/topic/architecture/data-layer/offline-first) 与 [CouchDB 冲突处理](https://docs.couchdb.org/en/stable/replication/conflicts.html)，没有引入 CouchDB 服务。Android 离线界面采用 HTTPS 资源来源，参考 [Android 本地 Web 内容指南](https://developer.android.com/develop/ui/views/layout/webapps/load-local-content)。渲染使用 Markdown-it 15.0.2，HTML 清洗使用 DOMPurify 3.4.16，其许可证随离线资源保留。
