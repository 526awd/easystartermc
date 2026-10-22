"""Interactive terminal menus for accounts, installation, settings and launch."""
import zipfile
import os
import getpass
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeRemainingColumn
from rich.table import Table

from . import accounts, config, installer, launcher, metadata
from .download_sources import BMCLAPI, OFFICIAL, label as source_label

console = Console(highlight=False)


def _pause(message: str = "回车返回菜单。") -> None:
    input(f"\n{message}")


def _clear() -> None:
    if console.is_terminal:
        console.clear()


def _profiles(settings: dict[str, Any]) -> list[dict[str, Any]]:
    value = settings.setdefault("profiles", [])
    return value if isinstance(value, list) else []


def accounts_menu(settings: dict[str, Any]) -> None:
    while True:
        _clear()
        profiles = _profiles(settings)
        active = settings.get("active_profile", "")
        console.print(Panel("账号档案", border_style="cyan", box=box.ROUNDED))
        if not profiles:
            console.print("[dim]尚无账号档案。[/dim]")
        table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan")
        table.add_column("编号", justify="right", style="dim", no_wrap=True)
        table.add_column("状态", justify="center", no_wrap=True)
        table.add_column("玩家", style="bold")
        table.add_column("类型")
        for index, profile in enumerate(profiles, 1):
            marker = "★" if profile.get("profile_key", profile.get("name")) == active else " "
            kind = "离线" if profile.get("type") == "offline" else (
                f"第三方 ({profile.get('auth_server', '')})" if profile.get("type") == "yggdrasil" else
                "Microsoft OAuth" if profile.get("client_id") else "Microsoft 手动令牌"
            )
            table.add_row(str(index), marker, str(profile.get("name", "")), kind)
        if profiles:
            console.print(table)
        console.print(Panel("[A] 添加离线档案   [O] Microsoft 登录   [Y] 第三方登录   [M] 手动档案\n[数字] 设为当前   [D] 删除   [Enter] 返回",
                            border_style="blue", padding=(0, 1)))
        choice = input("> ").strip().lower()
        if not choice:
            return
        if choice == "a":
            try:
                profile = accounts.offline_profile(input("离线玩家名 > "))
                profiles[:] = [item for item in profiles if item.get("name") != profile["name"]]
                profiles.append(profile)
                settings["active_profile"] = profile.get("profile_key", profile["name"])
                config.save(settings)
                print(f"已添加离线账号 {profile['name']}（{profile['uuid']}）。")
                _pause()
            except ValueError as exc:
                _pause(str(exc))
        elif choice == "o":
            try:
                from . import auth_microsoft
                client_id = (os.environ.get("MC_MICROSOFT_CLIENT_ID")
                             or settings.get("microsoft_client_id")
                             or auth_microsoft.OFFICIAL_CLIENT_ID)
                print("\n正在开始 Microsoft OAuth 登录。")
                profile = auth_microsoft.sign_in(
                    client_id,
                    lambda message: print("\n" + message + "\n", flush=True),
                    lambda: input("粘贴完整重定向 URL > "),
                )
                profiles[:] = [item for item in profiles
                               if item.get("uuid", "").replace("-", "").lower() != profile["uuid"].replace("-", "").lower()]
                profiles.append(profile)
                settings["active_profile"] = profile.get("profile_key", profile["name"])
                config.save(settings)
                _pause(f"已登录 Minecraft 档案：{profile['name']}。")
            except (OSError, ValueError, RuntimeError) as exc:
                _pause(f"登录失败：{exc}")
        elif choice == "y":
            try:
                from . import auth_yggdrasil
                server = input("Yggdrasil 认证服务器 API 地址 (例如 https://example.com/api/yggdrasil/) > ").strip()
                username = input("账号 > ").strip()
                password = getpass.getpass("密码（不会保存）> ")

                def choose_profile(available: list[dict[str, Any]]) -> dict[str, Any]:
                    options = Table(title="选择游戏档案", box=box.SIMPLE_HEAVY)
                    options.add_column("编号", justify="right")
                    options.add_column("玩家名")
                    options.add_column("UUID")
                    for number, item in enumerate(available, 1):
                        options.add_row(str(number), str(item.get("name", "")), str(item.get("id", "")))
                    console.print(options)
                    answer = input("档案编号 > ").strip()
                    if not answer.isdigit() or not 1 <= int(answer) <= len(available):
                        raise ValueError("档案编号无效。")
                    return available[int(answer) - 1]

                profile = auth_yggdrasil.sign_in(server, username, password, choose_profile)
                profiles[:] = [item for item in profiles if not (
                    item.get("type") == "yggdrasil"
                    and item.get("auth_server") == profile["auth_server"]
                    and item.get("uuid", "").replace("-", "").lower() == profile["uuid"].lower()
                )]
                profiles.append(profile)
                settings["active_profile"] = profile.get("profile_key", profile["name"])
                config.save(settings)
                _pause(f"已登录第三方账号：{profile['name']}。")
            except (OSError, ValueError, RuntimeError) as exc:
                _pause(f"登录失败：{exc}")
        elif choice == "m":
            name = input("正版玩家名 > ").strip()
            player_uuid = input("正版 UUID > ").strip()
            if not name or not player_uuid:
                _pause("玩家名和 UUID 都不能为空。")
                continue
            profile = {"name": name, "uuid": player_uuid, "type": "microsoft"}
            profiles[:] = [item for item in profiles if item.get("name") != name]
            profiles.append(profile)
            settings["active_profile"] = profile.get("profile_key", name)
            config.save(settings)
            _pause("已保存。令牌仍需通过 MC_ACCESS_TOKEN 环境变量提供。")
        elif choice == "d":
            if not profiles:
                continue
            index = input("要删除的编号 > ").strip()
            if index.isdigit() and 1 <= int(index) <= len(profiles):
                removed = profiles.pop(int(index) - 1)
                if removed.get("type") == "microsoft" and removed.get("client_id"):
                    try:
                        from .auth_microsoft import remove_account
                        remove_account(removed)
                    except (OSError, RuntimeError) as exc:
                        print(f"已删除档案；凭据缓存清理失败：{exc}")
                elif removed.get("type") == "yggdrasil":
                    try:
                        from .auth_yggdrasil import remove_account
                        remove_account(removed)
                    except (OSError, RuntimeError, ValueError) as exc:
                        print(f"已删除档案；凭据缓存清理失败：{exc}")
                if settings.get("active_profile") in (removed.get("profile_key"), removed.get("name")):
                    settings["active_profile"] = (profiles[0].get("profile_key", profiles[0]["name"])
                                                   if profiles else "")
                config.save(settings)
        elif choice.isdigit() and 1 <= int(choice) <= len(profiles):
            selected = profiles[int(choice) - 1]
            settings["active_profile"] = selected.get("profile_key", selected["name"])
            config.save(settings)


def _install_menu(root: Path, settings: dict[str, Any]) -> None:
    source = settings.get("download_source", OFFICIAL)
    if source not in (OFFICIAL, BMCLAPI):
        source = OFFICIAL
    console.print(Panel(
        f"正在读取 {source_label(source)} 版本清单。镜像不可用或文件缺失时会回退到官方源。",
        border_style="cyan"))
    manifest = metadata.version_list(source)
    versions = manifest.get("versions", [])
    if not versions:
        raise RuntimeError("官方版本清单没有版本。")
    latest = manifest.get("latest", {})
    console.print(Panel(f"最新正式版  [bold green]{latest.get('release', '?')}[/bold green]    最新快照  [cyan]{latest.get('snapshot', '?')}[/cyan]",
                        title="官方版本", border_style="cyan"))
    releases = [v for v in versions if v.get("type") == "release"][:18]
    table = Table(box=box.SIMPLE_HEAVY, header_style="bold cyan")
    table.add_column("编号", justify="right", style="dim", no_wrap=True)
    table.add_column("版本", style="bold")
    table.add_column("状态")
    for i, item in enumerate(releases, 1):
        installed = (root / "versions" / item["id"] / f"{item['id']}.jar").is_file()
        table.add_row(str(i), item["id"], "[green]已安装[/green]" if installed else "待安装")
    console.print(table)
    console.print("输入编号、官方版本 ID，或以 s: 开头选快照（例如 s:25w14a）。Enter 返回。")
    choice = input("安装版本 > ").strip()
    if not choice:
        return
    if choice.startswith("s:"):
        version_id = choice[2:].strip()
    elif choice.isdigit() and 1 <= int(choice) <= len(releases):
        version_id = releases[int(choice) - 1]["id"]
    else:
        version_id = choice

    console.print(Panel(f"正在安装 [bold]{version_id}[/bold]，下载源：{source_label(source)}（失败时尝试官方源）。",
                        border_style="yellow"))
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(), TaskProgressColumn(), TimeRemainingColumn(),
        console=console, transient=True,
    ) as progress_display:
        task = progress_display.add_task("准备文件", total=1)

        def report(done: int, total: int, filename: str) -> None:
            progress_display.update(task, total=max(total, 1), completed=done,
                                    description=filename)

        installer.install(root, version_id, manifest, report, source=source)
    console.print(Panel(f"版本 {version_id} 安装完成。", border_style="green"))


def _settings_menu(settings: dict[str, Any]) -> None:
    root = config.game_dir(settings)
    print(f"Minecraft 目录 [{root}]")
    value = input("> ").strip()
    if value:
        settings["minecraft_dir"] = str(Path(value).expanduser())
    print(f"Java 可执行文件 [{settings.get('java') or '自动选择兼容版本'}]")
    value = input("路径 (Enter 保持当前；输入 auto 自动选择) > ").strip()
    if value.lower() == "auto":
        settings["java"] = ""
    elif value:
        settings["java"] = value
    current_source = settings.get("download_source", OFFICIAL)
    if current_source not in (OFFICIAL, BMCLAPI):
        current_source = OFFICIAL
    print(f"下载源 [1] Mojang 官方源  [2] BMCLAPI 国内镜像 [{source_label(current_source)}]")
    value = input("选择 (Enter 保持当前) > ").strip().lower()
    if value in ("1", "official"):
        settings["download_source"] = OFFICIAL
    elif value in ("2", "bmclapi"):
        settings["download_source"] = BMCLAPI
    from .auth_microsoft import OFFICIAL_CLIENT_ID
    print(f"Microsoft OAuth Client ID [{settings.get('microsoft_client_id', OFFICIAL_CLIENT_ID)}]")
    value = input("(留空使用官方 Minecraft Launcher ID) > ").strip()
    if value:
        settings["microsoft_client_id"] = value
    try:
        current = int(settings.get("memory_mb", 4096))
        value = input(f"最大内存 MiB [{current}] > ").strip()
        if value:
            memory = int(value)
            if memory < 512 or memory > 65536:
                raise ValueError
            settings["memory_mb"] = memory
    except ValueError:
        print("内存值无效，保留原设置。")
    config.save(settings)


def main() -> int:
    settings = config.load()
    # Migrate old single-account config to a profile without losing settings.
    accounts.current_profile(settings)
    if settings.get("profiles"):
        config.save(settings)
    while True:
        _clear()
        root = config.game_dir(settings)
        profile = accounts.current_profile(settings)
        found = launcher.versions(root)
        kind = ("离线" if profile.get("type") == "offline" else
                "第三方" if profile.get("type") == "yggdrasil" else "Microsoft")
        details = Table.grid(padding=(0, 2))
        details.add_column(style="dim")
        details.add_column(style="bold")
        details.add_row("游戏目录", str(root))
        details.add_row("下载源", source_label(settings.get("download_source", OFFICIAL)))
        details.add_row("当前账号", f"{profile.get('name', '未设置')} ({kind if profile else '无'})")
        details.add_row("已安装", f"{len(found)} 个版本")
        console.print(Panel(details, title="[bold green]MC TUI · Java 启动器[/bold green]",
                            border_style="green", box=box.DOUBLE))
        console.print(Panel("[bold green]L[/bold green] 启动游戏   [bold cyan]I[/bold cyan] 安装版本   [bold yellow]A[/bold yellow] 账号档案   [bold blue]S[/bold blue] 设置   [bold red]Q[/bold red] 退出",
                            border_style="green", padding=(0, 1)))
        choice = input("\n选择 > ").strip().lower()
        try:
            if choice == "q":
                return 0
            if choice == "a":
                accounts_menu(settings)
            elif choice == "s":
                _settings_menu(settings)
            elif choice == "i":
                _install_menu(root, settings)
                _pause()
            elif choice == "l":
                if not found:
                    _pause("没有已安装版本；请先选择 I 安装。")
                    continue
                if not profile:
                    _pause("请先选择 A 添加或选择账号档案。")
                    continue
                versions_table = Table(title="可启动版本", box=box.SIMPLE_HEAVY,
                                       header_style="bold cyan")
                versions_table.add_column("编号", justify="right", style="dim", no_wrap=True)
                versions_table.add_column("版本", style="bold")
                versions_table.add_column("类型")
                for index, (name, meta) in enumerate(found, 1):
                    versions_table.add_row(str(index), name, str(meta.get("type", "custom")))
                console.print(versions_table)
                selected = input("版本编号 (Enter 返回) > ").strip()
                if not selected:
                    continue
                if not selected.isdigit() or not 1 <= int(selected) <= len(found):
                    _pause("编号无效。")
                    continue
                memory = int(settings.get("memory_mb", 4096))
                java = settings.get("java", "")
                identity = accounts.launch_identity(
                    profile,
                    os.environ.get("MC_MICROSOFT_CLIENT_ID") or settings.get("microsoft_client_id"),
                )
                status = launcher.launch(root, *found[int(selected) - 1], identity, memory, java,
                                        settings.get("download_source", OFFICIAL))
                _pause(f"Minecraft 已退出，状态码 {status}。")
        except (OSError, ValueError, RuntimeError, KeyError, zipfile.BadZipFile) as exc:
            _pause(f"操作失败：{exc}")
        except KeyboardInterrupt:
            print("\n已取消当前操作。")
