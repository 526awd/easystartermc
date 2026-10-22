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

from . import accounts, config, installer, launcher, metadata, version_manager
from .download_sources import BMCLAPI, OFFICIAL, label as source_label
from .tui_selection import prompt_session, select_item

console = Console(highlight=False)


def _pause(message: str = "回车返回菜单。") -> None:
    input(f"\n{message}")


def _clear() -> None:
    if console.is_terminal:
        console.clear()


def _profiles(settings: dict[str, Any]) -> list[dict[str, Any]]:
    value = settings.setdefault("profiles", [])
    return value if isinstance(value, list) else []


def _profile_kind(profile: dict[str, Any]) -> str:
    if profile.get("type") == "offline":
        return "离线"
    if profile.get("type") == "yggdrasil":
        return f"第三方 ({profile.get('auth_server', '')})"
    return "Microsoft OAuth" if profile.get("client_id") else "Microsoft 手动令牌"


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
            table.add_row(str(index), marker, str(profile.get("name", "")), _profile_kind(profile))
        if profiles:
            console.print(table)
        console.print(Panel("[A] 添加离线档案   [O] Microsoft 登录   [Y] 第三方登录   [M] 手动档案\n[S] 选择当前档案   [数字] 快速切换   [D] 删除   [Enter] 返回",
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
                    selected = select_item(
                        list(enumerate(available)), title="选择游戏档案",
                        columns=("玩家名", "UUID"),
                        render=lambda pair: (str(pair[1].get("name", "")),
                                             str(pair[1].get("id", ""))),
                        console=console, prompt="选择档案 > ")
                    if selected is None:
                        raise ValueError("已取消游戏档案选择。")
                    return selected[1]

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
                _pause("没有可删除的账号档案。")
                continue
            selected_item = select_item(
                list(enumerate(profiles)), title="选择要删除的账号档案",
                columns=("玩家", "类型"),
                render=lambda pair: (str(pair[1].get("name", "")),
                                     _profile_kind(pair[1])),
                console=console, prompt="删除档案 > ")
            if selected_item is not None:
                index, candidate = selected_item
                confirmation = input(
                    f"确认删除档案 {candidate.get('name', '')}？输入 y 确认 (默认取消) > "
                ).strip().lower()
                if confirmation != "y":
                    _pause("已取消删除。")
                    continue
                removed = profiles.pop(index)
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
        elif choice == "s":
            if not profiles:
                _pause("没有可切换的账号档案。")
                continue
            selected_item = select_item(
                list(enumerate(profiles)), title="选择当前账号档案",
                columns=("玩家", "类型"),
                render=lambda pair: (str(pair[1].get("name", "")),
                                     _profile_kind(pair[1])),
                console=console, prompt="当前账号 > ")
            if selected_item is not None:
                selected = selected_item[1]
                settings["active_profile"] = selected.get("profile_key", selected["name"])
                config.save(settings)
        elif choice.isdigit() and 1 <= int(choice) <= len(profiles):
            selected = profiles[int(choice) - 1]
            settings["active_profile"] = selected.get("profile_key", selected["name"])
            config.save(settings)
        else:
            _pause("选项无效，请输入菜单字母、有效编号或按 Enter 返回。")


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
    releases = [item for item in versions if item.get("type") == "release"]
    installed_ids = {name for name, _ in launcher.versions(root)}
    page_size = 18
    page = 0
    search = ""
    status_filter: str | None = None
    notice = ""
    selected_index = 0
    choice_session = prompt_session()
    if choice_session is None:
        console.print(
            "[yellow]未安装 prompt_toolkit：可输入 n/p 翻页；安装 requirements.txt 后可用 PageUp/PageDown。[/yellow]")

    while True:
        _clear()
        console.print(Panel(
            f"最新正式版  [bold green]{latest.get('release', '?')}[/bold green]    最新快照  [cyan]{latest.get('snapshot', '?')}[/cyan]",
            title="官方版本", border_style="cyan"))
        visible = [item for item in releases
                   if search.casefold() in item.get("id", "").casefold()
                   and (status_filter is None
                        or (item.get("id") in installed_ids) == (status_filter == "installed"))]
        page_count = max(1, (len(visible) + page_size - 1) // page_size)
        page = min(page, page_count - 1)
        start = page * page_size
        page_items = visible[start:start + page_size]
        if page_items:
            selected_index = min(selected_index, len(page_items) - 1)
        table = Table(box=box.SIMPLE_HEAVY, header_style="bold cyan")
        table.add_column("", no_wrap=True)
        table.add_column("编号", justify="right", style="dim", no_wrap=True)
        table.add_column("版本", style="bold")
        table.add_column("状态")
        for index, item in enumerate(page_items, 1):
            installed = item.get("id") in installed_ids
            status = "[green]已安装[/green]" if installed else "待安装"
            if item.get("id") == latest.get("release"):
                status += " [cyan]最新[/cyan]"
            marker = ("[bold green]›[/bold green]"
                      if choice_session is not None and index - 1 == selected_index else "")
            table.add_row(marker, str(index), item["id"], status)
        console.print(table)
        filter_name = {None: "全部", "installed": "已安装", "available": "未安装"}[status_filter]
        console.print(
            f"第 {page + 1}/{page_count} 页 · 共 {len(visible)} 个版本 · 状态：{filter_name}"
            + (f" · 搜索：{search}" if search else ""))
        if notice:
            console.print(f"[yellow]{notice}[/yellow]")
            notice = ""
        if choice_session is not None:
            console.print("操作：↑/↓ 选择 · Enter 安装 · PageUp/PageDown 换页 · Esc 返回")
        else:
            console.print("操作：输入编号并按 Enter 安装 · n/p 换页 · Enter 返回")
        console.print("搜索：/关键词 · installed 或 available 筛选 · all 清除筛选")
        console.print("其他：s:版本ID 选择快照 · 也可直接输入官方版本 ID")
        if choice_session is None:
            choice = input("安装版本 > ").strip()
        else:
            choice = choice_session.prompt("安装版本 > ").strip()
        lowered = choice.casefold()
        if lowered == "back":
            return
        if not choice:
            if choice_session is None:
                return
            if page_items:
                version_id = page_items[selected_index]["id"]
                break
            notice = "当前筛选没有版本可选。"
            continue
        if lowered == "move-down":
            if selected_index + 1 < len(page_items):
                selected_index += 1
            elif page + 1 < page_count:
                page += 1
                selected_index = 0
            else:
                notice = "已经是最后一个版本。"
            continue
        if lowered == "move-up":
            if selected_index > 0:
                selected_index -= 1
            elif page > 0:
                page -= 1
                selected_index = page_size - 1
            else:
                notice = "已经是第一个版本。"
            continue
        if lowered in ("n", "next"):
            if page + 1 < page_count:
                page += 1
                selected_index = 0
            else:
                notice = "已经是最后一页。"
            continue
        if lowered in ("p", "prev"):
            if page > 0:
                page -= 1
                selected_index = 0
            else:
                notice = "已经是第一页。"
            continue
        if lowered.startswith("/"):
            search = choice[1:].strip()
            page = 0
            selected_index = 0
            continue
        if lowered == "installed":
            status_filter = "installed"
            page = 0
            selected_index = 0
            continue
        if lowered == "available":
            status_filter = "available"
            page = 0
            selected_index = 0
            continue
        if lowered == "all":
            search = ""
            status_filter = None
            page = 0
            selected_index = 0
            continue

        if choice.startswith("s:"):
            version_id = choice[2:].strip()
        elif choice.isdigit():
            if not 1 <= int(choice) <= len(page_items):
                notice = "编号无效；请输入当前页显示的编号。"
                continue
            version_id = page_items[int(choice) - 1]["id"]
        else:
            version_id = choice
            if not any(item.get("id") == version_id for item in versions):
                notice = f"清单中没有版本 {version_id}；可输入 /关键词 搜索。"
                continue
        break

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


def _delete_menu(root: Path) -> None:
    installed = launcher.versions(root)
    if not installed:
        _pause("没有可删除的已安装版本。")
        return

    selected = select_item(
        installed, title="选择要删除的已安装版本",
        columns=("版本", "类型"),
        render=lambda item: (item[0], str(item[1].get("type", "custom"))),
        console=console, prompt="删除版本 > ")
    if selected is None:
        return
    version_id = selected[0]
    confirmation = input(f"确认删除版本 {version_id} 的本地文件？输入 y 确认 (默认取消) > ").strip().lower()
    if confirmation != "y":
        _pause("已取消删除。")
        return

    version_manager.delete_version(root, version_id)
    console.print(Panel(
        f"已删除版本 {version_id}。共享游戏资源和运行库保留。",
        border_style="green"))
    _pause()


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
        console.print(Panel("[bold green]L[/bold green] 启动游戏   [bold cyan]I[/bold cyan] 安装版本   [bold magenta]D[/bold magenta] 删除版本   [bold yellow]A[/bold yellow] 账号档案   [bold blue]S[/bold blue] 设置   [bold red]Q[/bold red] 退出",
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
            elif choice == "d":
                _delete_menu(root)
            elif choice == "l":
                if not found:
                    _pause("没有已安装版本；请先选择 I 安装。")
                    continue
                if not profile:
                    _pause("请先选择 A 添加或选择账号档案。")
                    continue
                selected_version = select_item(
                    found, title="可启动版本", columns=("版本", "类型"),
                    render=lambda item: (item[0], str(item[1].get("type", "custom"))),
                    console=console, prompt="启动版本 > ")
                if selected_version is None:
                    continue
                memory = int(settings.get("memory_mb", 4096))
                java = settings.get("java", "")
                identity = accounts.launch_identity(
                    profile,
                    os.environ.get("MC_MICROSOFT_CLIENT_ID") or settings.get("microsoft_client_id"),
                )
                with Progress(
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(), TaskProgressColumn(), TimeRemainingColumn(),
                    console=console, transient=True,
                ) as progress_display:
                    task = progress_display.add_task("检查游戏运行库", total=1)

                    def report(done: int, total: int, filename: str) -> None:
                        progress_display.update(
                            task, total=max(total, 1), completed=done,
                            description=filename)

                    def libraries_ready() -> None:
                        progress_display.update(
                            task, total=1, completed=1, description="运行库已就绪")
                        progress_display.stop()

                    status = launcher.launch(
                        root, *selected_version, identity, memory, java,
                        settings.get("download_source", OFFICIAL),
                        progress_callback=report,
                        on_libraries_ready=libraries_ready,
                    )
                _pause(f"Minecraft 已退出，状态码 {status}。")
            else:
                _pause("选项无效，请选择 L、I、D、A、S 或 Q。")
        except (OSError, ValueError, RuntimeError, KeyError, zipfile.BadZipFile) as exc:
            _pause(f"操作失败：{exc}")
        except KeyboardInterrupt:
            print("\n已取消当前操作。")
