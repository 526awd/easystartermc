# [**easystartermc**](https://github.com/526awd/easystartermc)

一个用于 Minecraft Java 版的终端启动器。可以从 Mojang 官方元数据安装游戏，使用离线、Microsoft 或 Yggdrasil 第三方账号启动。

## 安装

打开 [GitHub Releases](https://github.com/526awd/easystartermc/releases)，下载与你的系统和处理器匹配的最新发行包。预编译发行包不需要安装 Python；所有平台都需要另外安装与所选 Minecraft 版本兼容的 Java。启动器不会替你安装 Java。

| 系统 | 下载文件 | 安装与启动 |
| --- | --- | --- |
| Windows x64 | easystartermc-windows-x64.zip[https://github.com/526awd/easystartermc/releases/download/latest/easystartermc-windows-x64.zip] | 解压整个 ZIP 文件夹，然后运行 `easystartermc.exe`。请保留同目录中的 DLL 和其他文件。 |
| Linux x64 | easystartermc-linux-x64.tar.gz[https://github.com/526awd/easystartermc/releases/download/latest/easystartermc-linux-x64.tar.gz] | 解压后进入 `easystartermc` 文件夹，在终端运行 `./easystartermc`。若提示没有执行权限，运行 `chmod +x easystartermc` 后再启动。该程序包在 Ubuntu 22.04 上构建。 |
| macOS Intel | easystartermc-macos-x64.pkg[https://github.com/526awd/easystartermc/releases/download/latest/easystartermc-macos-x64.pkg] | 下载并打开 PKG，按安装器提示完成安装，然后在终端运行 `easystartermc`。 |
| macOS Apple Silicon | easystartermc-macos-arm64.pkg[https://github.com/526awd/easystartermc/releases/download/latest/easystartermc-macos-arm64.pkg] | 下载并打开 PKG，按安装器提示完成安装，然后在终端运行 `easystartermc`。 |

Windows ZIP 和 Linux 压缩包需要完整解压后运行，不能只复制主程序文件。macOS 安装器会将文件安装到 `/usr/local/lib/easystartermc`，并在 `/usr/local/bin` 创建启动命令。

### macOS 首次打开

当前 macOS 安装包未签名和公证。若 Gatekeeper 阻止打开，先确认安装包来自本项目的 GitHub Releases，并确认你愿意运行它；然后打开“系统设置 → 隐私与安全性”，在安全性区域选择“仍要打开”。请只对你信任且来源明确的软件这样操作。更多说明见 [Apple 支持：安全地在 Mac 上打开 App](https://support.apple.com/zh-cn/102445)。

## 首次启动

1. 确认已安装与目标 Minecraft 版本兼容的 Java。启动时，启动器会读取版本元数据要求并从用户设置、`JAVA_HOME`、`PATH` 和常见安装目录中自动选择对应主版本；用户设置的 Java 只有在版本匹配时才优先使用。若未检测到所需版本，请安装它，或在 **S 设置** 中填写 Java 可执行文件路径。输入 `auto` 可清除固定路径并恢复自动选择。
2. 选择 **I 安装版本**，在分页清单中用 ↑/↓ 选择、按 Enter 安装，或用 PageUp/PageDown 换页；按 Esc 返回。也可用 `/关键词` 搜索，或输入 `installed`/`available` 筛选状态。未安装 `prompt_toolkit` 时，可输入编号并用 `n`/`p` 翻页。启动器会从所选下载源获取版本元数据、客户端、运行库和游戏资源，并校验下载文件。首次安装需要网络和足够的磁盘空间。
3. 选择 **A 账号档案**，添加离线账号、登录 Microsoft，或登录 Yggdrasil 第三方认证服务器。
4. 返回主菜单，选择 **L 启动游戏**，再选已安装的版本。

启动版本、删除版本和账号档案选择也支持相同的方向键操作；按 Esc 可取消选择并返回。

在主菜单选择 **D 删除版本**，选中要移除的已安装版本并输入 `y` 确认。此操作只删除该版本目录；共享游戏资源和运行库会保留。

启动游戏时会检查运行库；缺失或校验失败的文件会尝试重新下载，单个文件最多重试 3 次。

### 下载源

在 **S 设置** 中可选择 **Mojang 官方源** 或 **BMCLAPI 国内镜像**。默认使用 Mojang 官方源；选择 BMCLAPI 后，版本清单、版本元数据、游戏资源和 Minecraft Maven 库会优先从镜像获取。镜像请求失败或文件校验不通过时，启动器会重试并回退到官方 URL；下载文件仍按元数据中的 SHA-1 和文件大小校验。安装界面会显示当前所用来源。BMCLAPI 是社区镜像服务，详见 [BMCLAPI 文档](https://bmclapidoc.bangbang93.com/)。

## 账号

- **离线账号**：输入 1–16 位英文、数字或下划线玩家名。适合单人游戏及允许离线玩家的服务器；需要正版验证的服务器不会接受离线账号。
- **Microsoft 账号**：在账号菜单选择 **O Microsoft 登录**，浏览器完成授权后，启动器会获取 Minecraft Java 档案。登录令牌保存在系统凭据库，不写入 `launcher.json`。
- **Yggdrasil 第三方账号**：选择 **Y 第三方登录**，输入认证服务器 API 地址、账号和密码。密码只用于登录请求，不会保存；令牌保存在系统凭据库。登录需要兼容 Yggdrasil/authlib-injector 规范的认证服务器。启动时启动器会校验令牌，并在需要时尝试刷新。

第三方认证地址默认使用 HTTPS；公网 HTTP 会被拒绝，本机回环地址可使用 HTTP。首次登录和令牌刷新需要网络。Linux 上使用 Microsoft 或第三方账号时，系统需要有可用的 Secret Service 凭据库。

## Java、游戏目录与配置

Java 版本要求取决于你选择的 Minecraft 版本。启动器会根据版本 JSON 中的 `javaVersion.majorVersion` 选择已安装的匹配版本；旧版本元数据缺少此字段时，会根据 Minecraft 版本号推断。启动器不会捆绑或自动安装 Java；若缺少所需主版本，请先安装，再通过 **S 设置**、`JAVA_HOME` 或 `PATH` 提供给启动器。

默认游戏目录：Windows `%APPDATA%\.minecraft`；macOS `~/Library/Application Support/minecraft`；Linux `$XDG_DATA_HOME/minecraft` 或 `~/.local/share/minecraft`。可用 `MINECRAFT_DIR` 覆盖游戏目录。

配置文件 `launcher.json` 只保存设置和账号档案，不保存登录令牌。Windows/Linux 发行包将配置保存在程序目录；macOS 配置保存在 `~/Library/Application Support/MC TUI/launcher.json`。删除账号档案时，启动器会尝试从系统凭据库删除相应令牌。

## 从源码运行

源码运行需要 Python 3.10+ 和兼容所选游戏版本的 Java：

```bash
git clone https://github.com/526awd/easystartermc.git
cd easystartermc
python -m venv .venv
```

激活虚拟环境并安装依赖：

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# Linux 或 macOS
source .venv/bin/activate
```

然后运行：

```bash
python -m pip install -r requirements.txt
python mc_tui.py
```

## 发行流程

推送以 `v` 开头的版本标签（例如 `v1.2`）会自动构建 Windows、Linux、macOS Intel 和 Apple Silicon 安装包，并创建 GitHub Release、生成发布说明和上传产物。创建签名标签并推送：

```bash
git tag -s v1.2 -m "v1.2"
git push origin v1.2
```

若标签构建失败，可在 **Actions → Build desktop packages → Run workflow** 中填写 `release_tag`（例如 `v1.1.2`），重新构建并发布已有标签。

## 项目模块

- `tui.py`：终端菜单、表格和安装进度
- `tui_selection.py`：可复用的方向键列表选择和文本输入回退
- `accounts.py`：账号档案与启动身份
- `auth_microsoft.py`：Microsoft OAuth、PKCE、Xbox/XSTS/Minecraft 换票
- `auth_yggdrasil.py`：Yggdrasil 登录、令牌管理与 authlib-injector
- `download_sources.py`：官方源与 BMCLAPI 镜像地址映射
- `java_runtime.py`：扫描并选择与 Minecraft 版本匹配的 Java
- `metadata.py`：Mojang 官方版本清单
- `downloader.py`：并发下载、文件校验与原子写入
- `installer.py`：客户端、依赖库和游戏资源安装
- `version_manager.py`：删除指定版本目录并保护共享文件
- `launcher.py`：启动参数、原生库提取与游戏进程启动
- `platforms.py`：操作系统规则及原生库分类
- `config.py`：游戏目录和本地设置

相关资料：[Minecraft 启动器教程](https://zh.minecraft.wiki/w/Tutorial:%E7%BC%96%E5%86%99%E5%90%AF%E5%8A%A8%E5%99%A8?variant=zh-cn)、[Microsoft 授权码流程与 PKCE](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow)、[authlib-injector 启动器技术规范](https://yushijinhun.github.io/authlib-injector/en/launcher-technical-specification.html)、[Yggdrasil 服务端技术规范](https://yushijinhun.github.io/authlib-injector/en/yggdrasil-server-technical-specification.html)。

## Star History

<a href="https://www.star-history.com/?repos=526awd%2Feasystartermc&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=526awd/easystartermc&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=526awd/easystartermc&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=526awd/easystartermc&type=date&legend=top-left" />
 </picture>
</a>
