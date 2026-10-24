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
from rich.text import Text

from . import accounts, config, installer, launcher, metadata, version_manager
from .download_sources import BMCLAPI, OFFICIAL, label as source_label
from .localization import tr, language_name, set_locale
from .tui_selection import prompt_session, select_item

console = Console(highlight=False)


def _pause(message: str | None = None) -> None:
    if message is None:
        message = tr('ui.press_enter_to_return_to_the_menu')
    input(f"\n{message}")


def _clear() -> None:
    if console.is_terminal:
        console.clear()


def _profiles(settings: dict[str, Any]) -> list[dict[str, Any]]:
    value = settings.setdefault("profiles", [])
    return value if isinstance(value, list) else []


def _profile_kind(profile: dict[str, Any]) -> str:
    if profile.get("type") == "offline":
        return tr('ui.offline')
    if profile.get("type") == "yggdrasil":
        return tr('ui.third_party_a', v_a=profile.get('auth_server', ''))
    return "Microsoft OAuth" if profile.get("client_id") else tr('ui.microsoft_manual_token')


def accounts_menu(settings: dict[str, Any]) -> None:
    while True:
        _clear()
        profiles = _profiles(settings)
        active = settings.get("active_profile", "")
        console.print(Panel(tr('ui.account_profiles'), border_style="cyan", box=box.ROUNDED))
        if not profiles:
            console.print(tr('ui.dim_no_account_profiles_yet_dim'))
        table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan")
        table.add_column(tr('ui.no'), justify="right", style="dim", no_wrap=True)
        table.add_column(tr('ui.status'), justify="center", no_wrap=True)
        table.add_column(tr('ui.player'), style="bold")
        table.add_column(tr('ui.type'))
        for index, profile in enumerate(profiles, 1):
            marker = "★" if profile.get("profile_key", profile.get("name")) == active else " "
            table.add_row(str(index), marker, Text(str(profile.get("name", ""))), _profile_kind(profile))
        if profiles:
            console.print(table)
        console.print(Panel(tr('ui.a_add_offline_profile_o_microsoft_sign_in_y_third_party_sign_in_m_manual_profile_s_select_current_profile_number_switch_d_delete_enter_back'),
                            border_style="blue", padding=(0, 1)))
        choice = input("> ").strip().lower()
        if not choice:
            return
        if choice == "a":
            try:
                profile = accounts.offline_profile(input(tr('ui.offline_player_name')))
                profiles[:] = [item for item in profiles if item.get("name") != profile["name"]]
                profiles.append(profile)
                settings["active_profile"] = profile.get("profile_key", profile["name"])
                config.save(settings)
                print(tr('ui.added_offline_profile', v_a=profile['name'], v_b=profile['uuid']))
                _pause()
            except ValueError as exc:
                _pause(str(exc))
        elif choice == "o":
            try:
                from . import auth_microsoft
                client_id = (os.environ.get("MC_MICROSOFT_CLIENT_ID")
                             or settings.get("microsoft_client_id")
                             or auth_microsoft.OFFICIAL_CLIENT_ID)
                print(tr('ui.starting_microsoft_oauth_sign_in'))
                profile = auth_microsoft.sign_in(
                    client_id,
                    lambda message: print("\n" + message + "\n", flush=True),
                    lambda: input(tr('ui.paste_the_full_redirect_url')),
                )
                profiles[:] = [item for item in profiles
                               if item.get("uuid", "").replace("-", "").lower() != profile["uuid"].replace("-", "").lower()]
                profiles.append(profile)
                settings["active_profile"] = profile.get("profile_key", profile["name"])
                config.save(settings)
                _pause(tr('ui.signed_in_to_minecraft_profile', v_a=profile['name']))
            except (OSError, ValueError, RuntimeError) as exc:
                _pause(tr('ui.sign_in_failed', v_a=exc))
        elif choice == "y":
            try:
                from . import auth_yggdrasil
                server = input(tr('ui.yggdrasil_authentication_server_api_url_for_example_https_example_com_api_yggdrasil')).strip()
                username = input(tr('ui.account')).strip()
                password = getpass.getpass(tr('ui.password_not_saved'))

                def choose_profile(available: list[dict[str, Any]]) -> dict[str, Any]:
                    selected = select_item(
                        list(enumerate(available)), title=tr('ui.select_a_game_profile'),
                        columns=(tr('ui.player_name'), "UUID"),
                        render=lambda pair: (str(pair[1].get("name", "")),
                                             str(pair[1].get("id", ""))),
                        console=console, prompt=tr('ui.select_profile'))
                    if selected is None:
                        raise ValueError(tr('ui.game_profile_selection_cancelled'))
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
                _pause(tr('ui.signed_in_to_third_party_account', v_a=profile['name']))
            except (OSError, ValueError, RuntimeError) as exc:
                _pause(tr('ui.sign_in_failed', v_a=exc))
        elif choice == "m":
            name = input(tr('ui.premium_account_player_name')).strip()
            player_uuid = input(tr('ui.premium_account_uuid')).strip()
            if not name or not player_uuid:
                _pause(tr('ui.player_name_and_uuid_are_required'))
                continue
            profile = {"name": name, "uuid": player_uuid, "type": "microsoft"}
            profiles[:] = [item for item in profiles if item.get("name") != name]
            profiles.append(profile)
            settings["active_profile"] = profile.get("profile_key", name)
            config.save(settings)
            _pause(tr('ui.saved_provide_the_token_through_the_mc_access_token_environment_variable'))
        elif choice == "d":
            if not profiles:
                _pause(tr('ui.there_are_no_account_profiles_to_delete'))
                continue
            selected_item = select_item(
                list(enumerate(profiles)), title=tr('ui.select_an_account_profile_to_delete'),
                columns=(tr('ui.player'), tr('ui.type')),
                render=lambda pair: (str(pair[1].get("name", "")),
                                     _profile_kind(pair[1])),
                console=console, prompt=tr('ui.delete_profile'))
            if selected_item is not None:
                index, candidate = selected_item
                confirmation = input(
                    tr('ui.delete_profile_enter_y_to_confirm_cancel_by_default', v_a=candidate.get('name', ''))
                ).strip().lower()
                if confirmation != "y":
                    _pause(tr('ui.deletion_cancelled'))
                    continue
                removed = profiles.pop(index)
                if removed.get("type") == "microsoft" and removed.get("client_id"):
                    try:
                        from .auth_microsoft import remove_account
                        remove_account(removed)
                    except (OSError, RuntimeError) as exc:
                        print(tr('ui.profile_deleted_but_credential_cleanup_failed', v_a=exc))
                elif removed.get("type") == "yggdrasil":
                    try:
                        from .auth_yggdrasil import remove_account
                        remove_account(removed)
                    except (OSError, RuntimeError, ValueError) as exc:
                        print(tr('ui.profile_deleted_but_credential_cleanup_failed', v_a=exc))
                if settings.get("active_profile") in (removed.get("profile_key"), removed.get("name")):
                    settings["active_profile"] = (profiles[0].get("profile_key", profiles[0]["name"])
                                                   if profiles else "")
                config.save(settings)
        elif choice == "s":
            if not profiles:
                _pause(tr('ui.there_are_no_account_profiles_to_switch_to'))
                continue
            selected_item = select_item(
                list(enumerate(profiles)), title=tr('ui.select_the_active_account_profile'),
                columns=(tr('ui.player'), tr('ui.type')),
                render=lambda pair: (str(pair[1].get("name", "")),
                                     _profile_kind(pair[1])),
                console=console, prompt=tr('ui.active_account_a'))
            if selected_item is not None:
                selected = selected_item[1]
                settings["active_profile"] = selected.get("profile_key", selected["name"])
                config.save(settings)
        elif choice.isdigit() and 1 <= int(choice) <= len(profiles):
            selected = profiles[int(choice) - 1]
            settings["active_profile"] = selected.get("profile_key", selected["name"])
            config.save(settings)
        else:
            _pause(tr('ui.invalid_choice_enter_a_menu_letter_a_valid_number_or_press_enter_to_return'))


def _install_menu(root: Path, settings: dict[str, Any]) -> None:
    source = settings.get("download_source", OFFICIAL)
    if source not in (OFFICIAL, BMCLAPI):
        source = OFFICIAL
    console.print(Panel(
        tr('ui.loading_the_version_manifest_official_downloads_will_be_used_if_the_mirror_is_unavailable_or_a_file_is_missing', v_a=source_label(source)),
        border_style="cyan"))
    manifest = metadata.version_list(source)
    versions = manifest.get("versions", [])
    if not versions:
        raise RuntimeError(tr('ui.the_official_version_manifest_contains_no_versions'))
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
            tr('ui.yellow_prompt_toolkit_is_not_installed_use_n_p_to_change_pages_install_requirements_txt_to_use_pageup_pagedown_yellow'))

    while True:
        _clear()
        console.print(Panel(
            tr('ui.latest_release_bold_green_bold_green_latest_snapshot_cyan_cyan', v_a=latest.get('release', '?'), v_b=latest.get('snapshot', '?')),
            title=tr('ui.minecraft_versions'), border_style="cyan"))
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
        table.add_column(tr('ui.no'), justify="right", style="dim", no_wrap=True)
        table.add_column(tr('ui.version'), style="bold")
        table.add_column(tr('ui.status'))
        for index, item in enumerate(page_items, 1):
            installed = item.get("id") in installed_ids
            status = tr('ui.green_installed_green') if installed else tr('ui.not_installed')
            if item.get("id") == latest.get("release"):
                status += tr('ui.cyan_latest_cyan')
            marker = ("[bold green]›[/bold green]"
                      if choice_session is not None and index - 1 == selected_index else "")
            table.add_row(marker, str(index), item["id"], status)
        console.print(table)
        filter_name = {None: tr('ui.all'), "installed": tr('ui.installed'), "available": tr('ui.available')}[status_filter]
        console.print(
            tr('ui.page_versions_status', v_a=page + 1, v_b=page_count, v_c=len(visible), v_d=filter_name, v_e=tr('ui.search', v_a=search) if search else ''))
        if notice:
            console.print(f"[yellow]{notice}[/yellow]")
            notice = ""
        if choice_session is not None:
            console.print(tr('ui.controls_select_enter_install_pageup_pagedown_change_page_esc_back'))
        else:
            console.print(tr('ui.controls_enter_a_number_and_press_enter_to_install_n_p_change_page_enter_back'))
        console.print(tr('ui.search_keyword_filter_with_installed_or_available_all_clears_filters'))
        console.print(tr('ui.other_s_version_id_selects_a_snapshot_you_can_also_enter_an_official_version_id'))
        if choice_session is None:
            choice = input(tr('ui.install_version')).strip()
        else:
            choice = choice_session.prompt(tr('ui.install_version')).strip()
        lowered = choice.casefold()
        if lowered == "back":
            return
        if not choice:
            if choice_session is None:
                return
            if page_items:
                version_id = page_items[selected_index]["id"]
                break
            notice = tr('ui.no_versions_match_the_current_filters')
            continue
        if lowered == "move-down":
            if selected_index + 1 < len(page_items):
                selected_index += 1
            elif page + 1 < page_count:
                page += 1
                selected_index = 0
            else:
                notice = tr('ui.this_is_the_last_version')
            continue
        if lowered == "move-up":
            if selected_index > 0:
                selected_index -= 1
            elif page > 0:
                page -= 1
                selected_index = page_size - 1
            else:
                notice = tr('ui.this_is_the_first_version')
            continue
        if lowered in ("n", "next"):
            if page + 1 < page_count:
                page += 1
                selected_index = 0
            else:
                notice = tr('ui.this_is_the_last_page')
            continue
        if lowered in ("p", "prev"):
            if page > 0:
                page -= 1
                selected_index = 0
            else:
                notice = tr('ui.this_is_the_first_page')
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
                notice = tr('ui.invalid_number_enter_a_number_shown_on_this_page')
                continue
            version_id = page_items[int(choice) - 1]["id"]
        else:
            version_id = choice
            if not any(item.get("id") == version_id for item in versions):
                notice = tr('ui.version_is_not_in_the_manifest_search_with_keyword', v_a=version_id)
                continue
        break

    console.print(Panel(tr('ui.installing_bold_bold_from_official_source_will_be_tried_if_this_fails', v_a=version_id, v_b=source_label(source)),
                        border_style="yellow"))
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(), TaskProgressColumn(), TimeRemainingColumn(),
        console=console, transient=True,
    ) as progress_display:
        task = progress_display.add_task(tr('ui.preparing_files'), total=1)

        def report(done: int, total: int, filename: str) -> None:
            progress_display.update(task, total=max(total, 1), completed=done,
                                    description=filename)

        installer.install(root, version_id, manifest, report, source=source)
    console.print(Panel(tr('ui.version_installed', v_a=version_id), border_style="green"))


def _delete_menu(root: Path) -> None:
    installed = launcher.versions(root)
    if not installed:
        _pause(tr('ui.there_are_no_installed_versions_to_delete'))
        return

    selected = select_item(
        installed, title=tr('ui.select_an_installed_version_to_delete'),
        columns=(tr('ui.version'), tr('ui.type')),
        render=lambda item: (item[0], str(item[1].get("type", "custom"))),
        console=console, prompt=tr('ui.delete_version'))
    if selected is None:
        return
    version_id = selected[0]
    confirmation = input(tr('ui.delete_local_files_for_version_enter_y_to_confirm_cancel_by_default', v_a=version_id)).strip().lower()
    if confirmation != "y":
        _pause(tr('ui.deletion_cancelled'))
        return

    version_manager.delete_version(root, version_id)
    console.print(Panel(
        tr('ui.deleted_version_shared_game_assets_and_libraries_were_kept', v_a=version_id),
        border_style="green"))
    _pause()


def _settings_menu(settings: dict[str, Any]) -> None:
    current_language = settings.get("language", "auto")
    print(tr('ui.interface_language_simplified_chinese_english_system_default', v_a=language_name(current_language)))
    value = input(tr('ui.language_enter_keeps_current')).strip().lower()
    language_choices = {"1": "zh_CN", "zh": "zh_CN", "zh_cn": "zh_CN",
                        "2": "en_US", "en": "en_US", "en_us": "en_US",
                        "3": "auto", "auto": "auto", "system": "auto"}
    if value in language_choices:
        settings["language"] = language_choices[value]
        set_locale(settings["language"])

    root = config.game_dir(settings)
    print(tr('ui.minecraft_directory', v_a=root))
    value = input("> ").strip()
    if value:
        settings["minecraft_dir"] = str(Path(value).expanduser())
    print(tr('ui.java_executable', v_a=settings.get('java') or tr('ui.automatically_select_a_compatible_version')))
    value = input(tr('ui.path_enter_keeps_current_enter_auto_to_select_automatically')).strip()
    if value.lower() == "auto":
        settings["java"] = ""
    elif value:
        settings["java"] = value
    current_source = settings.get("download_source", OFFICIAL)
    if current_source not in (OFFICIAL, BMCLAPI):
        current_source = OFFICIAL
    print(tr('ui.download_source_official_mojang_bmclapi_mirror', v_a=source_label(current_source)))
    value = input(tr('ui.choice_enter_keeps_current')).strip().lower()
    if value in ("1", "official"):
        settings["download_source"] = OFFICIAL
    elif value in ("2", "bmclapi"):
        settings["download_source"] = BMCLAPI
    from .auth_microsoft import OFFICIAL_CLIENT_ID
    print(f"Microsoft OAuth Client ID [{settings.get('microsoft_client_id', OFFICIAL_CLIENT_ID)}]")
    value = input(tr('ui.leave_blank_to_use_the_official_minecraft_launcher_id')).strip()
    if value:
        settings["microsoft_client_id"] = value
    try:
        current = int(settings.get("memory_mb", 4096))
        value = input(tr('ui.maximum_memory_in_mib', v_a=current)).strip()
        if value:
            memory = int(value)
            if memory < 512 or memory > 65536:
                raise ValueError
            settings["memory_mb"] = memory
    except ValueError:
        print(tr('ui.invalid_memory_value_keeping_the_current_setting'))
    config.save(settings)


def main() -> int:
    settings = config.load()
    set_locale(settings.get("language", "auto"))
    # Migrate old single-account config to a profile without losing settings.
    accounts.current_profile(settings)
    if settings.get("profiles"):
        config.save(settings)
    while True:
        _clear()
        root = config.game_dir(settings)
        profile = accounts.current_profile(settings)
        found = launcher.versions(root)
        kind = (tr('ui.offline') if profile.get("type") == "offline" else
                tr('ui.third_party') if profile.get("type") == "yggdrasil" else "Microsoft")
        details = Table.grid(padding=(0, 2))
        details.add_column(style="dim")
        details.add_column(style="bold")
        details.add_row(tr('ui.game_directory'), str(root))
        details.add_row(tr('ui.download_source'), source_label(settings.get("download_source", OFFICIAL)))
        profile_name = str(profile.get("name") or tr('ui.not_set')) if profile else tr('ui.not_set')
        account_display = Text(profile_name)
        account_display.append(f" ({kind if profile else tr('ui.none')})")
        details.add_row(tr('ui.active_account'), account_display)
        details.add_row(tr('ui.installed'), tr('ui.versions', v_a=len(found)))
        console.print(Panel(details, title=tr('ui.bold_green_easystartermc_minecraft_launcher_bold_green'),
                            border_style="green", box=box.DOUBLE))
        console.print(Panel(tr('ui.bold_green_l_bold_green_launch_bold_cyan_i_bold_cyan_install_bold_magenta_d_bold_magenta_delete_bold_yellow_a_bold_yellow_accounts_bold_blue_s_bold_blue_settings_bold_red_q_bold_red_quit'),
                            border_style="green", padding=(0, 1)))
        choice = input(tr('ui.select')).strip().lower()
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
                    _pause(tr('ui.no_installed_versions_choose_i_to_install_one_first'))
                    continue
                if not profile:
                    _pause(tr('ui.choose_a_to_add_or_select_an_account_profile_first'))
                    continue
                selected_version = select_item(
                    found, title=tr('ui.launchable_versions'), columns=(tr('ui.version'), tr('ui.type')),
                    render=lambda item: (item[0], str(item[1].get("type", "custom"))),
                    console=console, prompt=tr('ui.launch_version'))
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
                    task = progress_display.add_task(tr('ui.checking_game_libraries'), total=1)

                    def report(done: int, total: int, filename: str) -> None:
                        progress_display.update(
                            task, total=max(total, 1), completed=done,
                            description=filename)

                    def libraries_ready() -> None:
                        progress_display.update(
                            task, total=1, completed=1, description=tr('ui.libraries_are_ready'))
                        progress_display.stop()

                    status = launcher.launch(
                        root, *selected_version, identity, memory, java,
                        settings.get("download_source", OFFICIAL),
                        progress_callback=report,
                        on_libraries_ready=libraries_ready,
                    )
                _pause(tr('ui.minecraft_exited_with_status_code', v_a=status))
            else:
                _pause(tr('ui.invalid_choice_select_l_i_d_a_s_or_q'))
        except (OSError, ValueError, RuntimeError, KeyError, zipfile.BadZipFile) as exc:
            _pause(tr('ui.operation_failed', v_a=exc))
        except KeyboardInterrupt:
            print(tr('ui.the_current_operation_was_cancelled'))
