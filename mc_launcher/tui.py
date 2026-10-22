"""Interactive terminal menus for accounts, installation, settings and launch."""
import sys
import zipfile
import os
from pathlib import Path
from typing import Any

from . import accounts, config, installer, launcher, metadata


def _pause(message: str = "回车返回菜单。") -> None:
    input(f"\n{message}")


def _clear() -> None:
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")


def _profiles(settings: dict[str, Any]) -> list[dict[str, Any]]:
    value = settings.setdefault("profiles", [])
    return value if isinstance(value, list) else []


def accounts_menu(settings: dict[str, Any]) -> None:
    while True:
        _clear()
        profiles = _profiles(settings)
        active = settings.get("active_profile", "")
        print("══ 账号档案 ══")
        if not profiles:
            print("尚无账号档案。")
        for index, profile in enumerate(profiles, 1):
            marker = "★" if profile.get("name") == active else " "
            kind = "离线" if profile.get("type") == "offline" else (
                "Microsoft OAuth" if profile.get("client_id") else "Microsoft 手动令牌"
            )
            print(f"{index}. {marker} {profile.get('name')} ({kind})")
        print("\n[A] 添加离线档案  [O] Microsoft OAuth 登录  [M] 手动档案  [数字] 设为当前  [D] 删除  [Enter] 返回")
        choice = input("> ").strip().lower()
        if not choice:
            return
        if choice == "a":
            try:
                profile = accounts.offline_profile(input("离线玩家名 > "))
                profiles[:] = [item for item in profiles if item.get("name") != profile["name"]]
                profiles.append(profile)
                settings["active_profile"] = profile["name"]
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
                settings["active_profile"] = profile["name"]
                config.save(settings)
                _pause(f"已登录 Minecraft 档案：{profile['name']}。")
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
            settings["active_profile"] = name
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
                if settings.get("active_profile") == removed.get("name"):
                    settings["active_profile"] = profiles[0]["name"] if profiles else ""
                config.save(settings)
        elif choice.isdigit() and 1 <= int(choice) <= len(profiles):
            settings["active_profile"] = profiles[int(choice) - 1]["name"]
            config.save(settings)


def _install_menu(root: Path) -> None:
    print("正在读取 Mojang 官方版本清单…")
    manifest = metadata.version_list()
    versions = manifest.get("versions", [])
    if not versions:
        raise RuntimeError("官方版本清单没有版本。")
    latest = manifest.get("latest", {})
    print(f"最新版正式版：{latest.get('release', '?')}    最新快照：{latest.get('snapshot', '?')}")
    print("\n最近的正式版：")
    releases = [v for v in versions if v.get("type") == "release"][:18]
    for i, item in enumerate(releases, 1):
        suffix = "  [已安装]" if (root / "versions" / item["id"] / f"{item['id']}.jar").is_file() else ""
        print(f"{i:2}. {item['id']}{suffix}")
    print("\n输入编号、官方版本 ID，或以 s: 开头选快照 (例如 s:25w14a)。Enter 返回。")
    choice = input("安装版本 > ").strip()
    if not choice:
        return
    if choice.startswith("s:"):
        version_id = choice[2:].strip()
    elif choice.isdigit() and 1 <= int(choice) <= len(releases):
        version_id = releases[int(choice) - 1]["id"]
    else:
        version_id = choice

    def progress(done: int, total: int, filename: str) -> None:
        width = 28
        filled = width * done // max(total, 1)
        print(f"\r[{'#' * filled}{'.' * (width - filled)}] {done}/{total}  {filename[:48]:48}", end="", flush=True)

    print(f"\n安装 {version_id}（从 Mojang 官方清单和下载服务器获取）…")
    installer.install(root, version_id, manifest, progress)
    print("\n安装完成。")


def _settings_menu(settings: dict[str, Any]) -> None:
    root = config.game_dir(settings)
    print(f"Minecraft 目录 [{root}]")
    value = input("> ").strip()
    if value:
        settings["minecraft_dir"] = str(Path(value).expanduser())
    print(f"Java 可执行文件 [{settings.get('java', '自动检测 / JAVA_HOME')}]")
    value = input("> ").strip()
    if value:
        settings["java"] = value
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
        kind = "离线" if profile.get("type") == "offline" else "Microsoft"
        print("╔══════════════════════════════════════════════╗")
        print("║             MC TUI · Java 启动器             ║")
        print("╚══════════════════════════════════════════════╝")
        print(f"游戏目录  {root}")
        print(f"当前账号  {profile.get('name', '未设置')} ({kind if profile else '无'})")
        print(f"已安装    {len(found)} 个版本\n")
        print("[L] 启动游戏   [I] 安装官方版本   [A] 账号档案   [S] 设置   [Q] 退出")
        choice = input("\n选择 > ").strip().lower()
        try:
            if choice == "q":
                return 0
            if choice == "a":
                accounts_menu(settings)
            elif choice == "s":
                _settings_menu(settings)
            elif choice == "i":
                _install_menu(root)
                _pause()
            elif choice == "l":
                if not found:
                    _pause("没有已安装版本；请先选择 I 安装。")
                    continue
                if not profile:
                    _pause("请先选择 A 添加或选择账号档案。")
                    continue
                print("\n可启动版本：")
                for index, (name, meta) in enumerate(found, 1):
                    print(f"{index:2}. {name} ({meta.get('type', 'custom')})")
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
                status = launcher.launch(root, *found[int(selected) - 1], identity, memory, java)
                _pause(f"Minecraft 已退出，状态码 {status}。")
        except (OSError, ValueError, RuntimeError, KeyError, zipfile.BadZipFile) as exc:
            _pause(f"操作失败：{exc}")
        except KeyboardInterrupt:
            print("\n已取消当前操作。")
