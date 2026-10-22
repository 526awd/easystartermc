"""Manage files belonging to installed Minecraft versions."""
import os
import shutil
from pathlib import Path


def delete_version(root: Path, version_id: str) -> None:
    """Remove one version directory while keeping shared assets and libraries."""
    if (not version_id or version_id in (".", "..") or
            Path(version_id).name != version_id or "/" in version_id or
            "\\" in version_id or "\0" in version_id):
        raise ValueError("无效的游戏版本编号。")

    versions_dir = root / "versions"
    target = versions_dir / version_id
    if not target.is_dir():
        raise FileNotFoundError(f"找不到已安装版本：{version_id}")

    if target.is_symlink() or getattr(os.path, "isjunction", lambda _path: False)(target):
        raise ValueError("版本目录是链接，拒绝删除以保护目录外的文件。")

    base_resolved = versions_dir.resolve()
    target_resolved = target.resolve()
    expected_target = base_resolved / version_id
    if target_resolved != expected_target or target_resolved.parent != base_resolved:
        raise ValueError("版本目录不在游戏目录的 versions 文件夹中，已拒绝删除。")

    shutil.rmtree(target)
