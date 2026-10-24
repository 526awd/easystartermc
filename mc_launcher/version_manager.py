"""Manage files belonging to installed Minecraft versions."""
import os
import shutil
from pathlib import Path

from .localization import tr


def delete_version(root: Path, version_id: str) -> None:
    """Remove one version directory while keeping shared assets and libraries."""
    if (not version_id or version_id in (".", "..") or
            Path(version_id).name != version_id or "/" in version_id or
            "\\" in version_id or "\0" in version_id):
        raise ValueError(tr('version_manager.invalid_game_version_id'))

    versions_dir = root / "versions"
    target = versions_dir / version_id
    if not target.is_dir():
        raise FileNotFoundError(tr('version_manager.installed_version_not_found', v_a=version_id))

    if target.is_symlink() or getattr(os.path, "isjunction", lambda _path: False)(target):
        raise ValueError(tr('version_manager.the_version_directory_is_a_symlink_deletion_was_refused_to_protect_files_outside_the_game_directory'))

    base_resolved = versions_dir.resolve()
    target_resolved = target.resolve()
    expected_target = base_resolved / version_id
    if target_resolved != expected_target or target_resolved.parent != base_resolved:
        raise ValueError(tr('version_manager.the_version_directory_is_outside_the_game_s_versions_folder_deletion_was_refused'))

    shutil.rmtree(target)
