# MC TUI

使用 Python 标准库编写的 Minecraft Java 版终端启动器。代码按功能拆分到 `mc_launcher/`，每个功能模块各一个文件。

## 启动

需要 Python 3.10+ 和已安装的 Java。运行：

```powershell
python .\mc_tui.py
```

从主菜单选择 **I 安装官方版本**，下载版本清单中的正式版，或输入版本 ID/快照 ID；安装器会获取客户端 JAR、运行库、资源索引和资源文件，并按官方元数据校验 SHA-1。单个下载失败会自动重试 3 次。启动时也会检查运行库，发现缺失或校验失败的依赖会尝试重新下载。然后在 **A 账号档案** 创建离线档案或配置正版档案，再选择 **L 启动游戏**。

## 账号

离线档案只需输入 1–16 位英文、数字或下划线玩家名。UUID 按 `OfflinePlayer:<玩家名>` 规则生成。离线档案适合单人游戏及允许离线玩家的服务器；需要正版验证的服务器不会接受离线档案。

正版档案需要填写玩家名和 UUID，并在启动前设置有效的 Minecraft `accessToken`。令牌只从当前进程环境读取，不会保存到配置文件：

```powershell
$env:MC_ACCESS_TOKEN = "有效的 Minecraft access token"
python .\mc_tui.py
```

Linux/macOS 可使用 `export MC_ACCESS_TOKEN='…'`。本项目暂不包含 Microsoft OAuth 登录及令牌刷新。

## 设置与模块

默认游戏目录：Windows `%APPDATA%\.minecraft`；macOS `~/Library/Application Support/minecraft`；Linux `$XDG_DATA_HOME/minecraft` 或 `~/.local/share/minecraft`。也可用 `MINECRAFT_DIR` 覆盖目录，使用 `JAVA_HOME` 指定 Java。

- `tui.py`：菜单交互
- `accounts.py`：账号档案与启动身份
- `metadata.py`：Mojang 官方版本清单
- `downloader.py`：并发下载、SHA-1/大小校验、原子写入
- `installer.py`：客户端、依赖库和游戏资源安装
- `launcher.py`：版本参数生成、原生库提取与进程启动
- `platforms.py`：系统规则及原生库分类
- `config.py`：目录发现和本地设置

配置文件 `launcher.json` 仅存设置和档案，不存账号令牌。参考：[Minecraft Wiki 启动器教程](https://zh.minecraft.wiki/w/Tutorial:%E7%BC%96%E5%86%99%E5%90%AF%E5%8A%A8%E5%99%A8?variant=zh-cn)、[Mojang Piston 元数据版本清单](https://piston-meta.mojang.com/mc/game/version_manifest_v2.json)。
