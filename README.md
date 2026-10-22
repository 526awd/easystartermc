# [**easystartermc**](https://github.com/526awd/easystartermc)

使用 Python 编写的 Minecraft Java 版终端启动器。代码按功能拆分到 `mc_launcher/`，每个功能模块各一个文件；Microsoft OAuth 使用系统凭据库保存刷新令牌。

## 启动

需要 Python 3.10+、已安装的 Java，以及 Microsoft 登录依赖。先安装依赖，再运行：

```powershell
python -m pip install -r requirements.txt
python .\mc_tui.py
```

从主菜单选择 **I 安装官方版本**，下载版本清单中的正式版，或输入版本 ID/快照 ID；安装器会获取客户端 JAR、运行库、资源索引和资源文件，并按官方元数据校验 SHA-1。单个下载失败会自动重试 3 次。启动时也会检查运行库，发现缺失或校验失败的依赖会尝试重新下载。然后在 **A 账号档案** 创建离线档案或登录 Microsoft 账号，再选择 **L 启动游戏**。

## 跨平台发行包

GitHub Actions 会在推送、Pull Request 或手动触发时并行构建 Windows、Linux，以及 macOS Intel 和 Apple Silicon 版本。构建产物会包含运行所需的 DLL/动态库：Windows 下载 ZIP，Linux 下载 tar.gz，macOS 下载 `.pkg` 安装包。在仓库的 **Actions** 页面打开 **Build desktop packages** 运行，从 **Artifacts** 下载对应平台的产物。Windows 和 Linux 解压后运行 `easystartermc`；macOS 安装后可在终端运行 `easystartermc`。macOS 安装包未签名，首次安装可能需要在系统提示中手动确认。Windows/Linux 配置保存在程序目录，macOS 配置保存在 `~/Library/Application Support/MC TUI/launcher.json`。

推送版本标签（例如 `v1.2`）会自动构建四个平台的发行包，并创建 GitHub Release、生成发布说明和上传所有安装文件。可通过 `git tag -s v1.2 -m "v1.2"` 创建签名标签，再运行 `git push origin v1.2` 发布。

## 账号

离线档案只需输入 1–16 位英文、数字或下划线玩家名。UUID 按 `OfflinePlayer:<玩家名>` 规则生成。离线档案适合单人游戏及允许离线玩家的服务器；需要正版验证的服务器不会接受离线档案。

选择 **A 账号档案 → O Microsoft OAuth 登录**。自定义 Entra 客户端 ID（GUID）使用授权码 + PKCE，并通过本机回环地址自动接收浏览器回调。默认 Minecraft Launcher 客户端继续使用其旧版授权码端点，完成登录后需将地址栏里的重定向 URL 粘贴回终端。OAuth 完成后，启动器会依次换取 Xbox Live、XSTS 和 Minecraft token，并读取 Java 档案。正版令牌不会写入 `launcher.json`；refresh token 保存在系统凭据库（Windows Credential Manager、macOS Keychain 或 Linux Secret Service）。启动游戏时会静默刷新登录并重新获取短期 Minecraft token。

选择 **A 账号档案 → Y 第三方登录**，输入遵循 Yggdrasil/authlib-injector 规范的认证服务器 API 地址、账号和密码。服务器地址缺少协议时按 HTTPS 处理；公网 HTTP 会被拒绝，本机回环地址可使用 HTTP。密码只用于登录请求，不会保存；`accessToken` 和 `clientToken` 存入系统凭据库。启动前会校验令牌，失效时尝试刷新，并自动下载官方 authlib-injector 构件、校验 SHA-256 后用于接入该认证服务器。删除档案时会一并尝试删除令牌。

默认使用 Minecraft Launcher 的公开客户端 ID。若需覆盖，可设置 `MC_MICROSOFT_CLIENT_ID`，或在 **S 设置** 中填写客户端 ID。客户端 ID 是公开标识，不要填写客户端密钥。自定义应用须配置为公共客户端，并将 `http://localhost` 添加为移动和桌面应用的重定向 URI；Minecraft Services 也可能拒绝未获准的 OAuth 应用。首次登录及刷新需要网络。删除 Microsoft 档案时会尝试从系统凭据库中移除该账号。

若应用注册被配置为机密客户端，启动器也会在授权码兑换和令牌刷新时发送环境变量 `MC_MICROSOFT_CLIENT_SECRET`。不要把 Secret 写入源码或 `launcher.json`；桌面程序无法保护硬编码的 Secret。优先把应用注册为公共客户端。如果必须使用机密客户端，请在本机进程环境中设置该变量，并在 Secret 泄露时先撤销并重新生成。

## 设置与模块

默认游戏目录：Windows `%APPDATA%\.minecraft`；macOS `~/Library/Application Support/minecraft`；Linux `$XDG_DATA_HOME/minecraft` 或 `~/.local/share/minecraft`。也可用 `MINECRAFT_DIR` 覆盖目录，使用 `JAVA_HOME` 指定 Java。

- `tui.py`：Rich 菜单、表格和安装进度展示
- `accounts.py`：账号档案与启动身份
- `auth_microsoft.py`：授权码 OAuth、PKCE、本机回调、Xbox/XSTS/Minecraft 换票
- `auth_yggdrasil.py`：Yggdrasil 第三方登录、令牌管理与 authlib-injector
- `metadata.py`：Mojang 官方版本清单
- `downloader.py`：并发下载、SHA-1/大小校验、原子写入
- `installer.py`：客户端、依赖库和游戏资源安装
- `launcher.py`：版本参数生成、原生库提取与进程启动
- `platforms.py`：系统规则及原生库分类
- `config.py`：目录发现和本地设置

配置文件 `launcher.json` 仅存设置和档案，不存账号令牌。参考：[Microsoft 授权码流程与 PKCE](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow)、[authlib-injector 启动器技术规范](https://yushijinhun.github.io/authlib-injector/en/launcher-technical-specification.html)、[Yggdrasil 服务端技术规范](https://yushijinhun.github.io/authlib-injector/en/yggdrasil-server-technical-specification.html)、[Minecraft Wiki 启动器教程](https://zh.minecraft.wiki/w/Tutorial:%E7%BC%96%E5%86%99%E5%90%AF%E5%8A%A8%E5%99%A8?variant=zh-cn)。
