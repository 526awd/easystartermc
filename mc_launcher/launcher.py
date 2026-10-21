"""Build JVM arguments from Mojang metadata and start an installed version."""
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

from .installer import ensure_libraries
from .platforms import allowed, native_artifact


def versions(root: Path) -> list[tuple[str, dict[str, Any]]]:
    result = []
    base = root / "versions"
    if not base.is_dir():
        return result
    for folder in sorted(base.iterdir(), key=lambda p: p.name.lower()):
        metadata_path = folder / f"{folder.name}.json"
        jar_path = folder / f"{folder.name}.jar"
        if not metadata_path.is_file() or not jar_path.is_file():
            continue
        try:
            import json
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata.get("mainClass"):
                result.append((folder.name, metadata))
        except (OSError, ValueError):
            continue
    return result


def _value(text: str, substitutions: dict[str, str]) -> str:
    return re.sub(r"\$\{([^}]+)\}", lambda match: substitutions.get(match.group(1), match.group(0)), text)


def _expand(argument: Any, substitutions: dict[str, str], output: list[str]) -> None:
    if isinstance(argument, str):
        output.append(_value(argument, substitutions))
    elif isinstance(argument, dict) and allowed(argument.get("rules")):
        values = argument.get("value", [])
        for item in values if isinstance(values, list) else [values]:
            _expand(item, substitutions, output)


def _extract_natives(root: Path, version: str, metadata: dict[str, Any]) -> Path:
    native_dir = root / "versions" / version / f"{version}-natives"
    native_dir.mkdir(parents=True, exist_ok=True)
    for library in metadata.get("libraries", []):
        if not allowed(library.get("rules")):
            continue
        artifact = native_artifact(library)
        if not artifact:
            continue
        archive = root / "libraries" / Path(artifact["path"])
        if not archive.is_file():
            continue
        excludes = library.get("extract", {}).get("exclude", [])
        with zipfile.ZipFile(archive) as bundle:
            for entry in bundle.infolist():
                normalized = entry.filename.replace("\\", "/")
                if entry.is_dir() or normalized.startswith("META-INF/") or any(normalized.startswith(x) for x in excludes):
                    continue
                relative = Path(normalized)
                if relative.is_absolute() or ".." in relative.parts:
                    continue
                output = native_dir / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(bundle.read(entry))
    return native_dir


def build_command(root: Path, version: str, metadata: dict[str, Any], identity: dict[str, str],
                  memory_mb: int, java_path: str = "") -> tuple[list[str], Path]:
    if not java_path:
        java_path = os.environ.get("JAVA_HOME", "")
        if java_path and Path(java_path).is_dir():
            java_path = str(Path(java_path) / "bin" / ("java.exe" if platform.system() == "Windows" else "java"))
        java_path = java_path or shutil.which("java") or ""
    if not java_path or not Path(java_path).is_file():
        raise RuntimeError("找不到 Java。请安装与游戏版本兼容的 Java，并配置 JAVA_HOME 或启动器设置。")
    version_dir = root / "versions" / version
    jar_id = metadata.get("jar", version)
    client = root / "versions" / jar_id / f"{jar_id}.jar"
    if not client.is_file():
        raise RuntimeError(f"缺少客户端 JAR：{client}。请重新安装该版本。")
    native_dir = _extract_natives(root, version, metadata)
    classpath_parts = []
    for library in metadata.get("libraries", []):
        if not allowed(library.get("rules")):
            continue
        downloads = library.get("downloads", {})
        artifact = downloads.get("artifact")
        if artifact:
            path = root / "libraries" / Path(artifact["path"])
        elif library.get("name") and not downloads:
            parts = library["name"].split(":")
            group, artifact_name, revision = parts[:3]
            filename = f"{artifact_name}-{revision}" + (f"-{parts[3]}" if len(parts) > 3 else "") + ".jar"
            path = root / "libraries" / Path(group.replace(".", "/")) / artifact_name / revision / filename
        else:
            continue
        if not path.is_file():
            raise RuntimeError(f"缺少运行库：{path}。请重新安装该版本。")
        classpath_parts.append(str(path.resolve()))
    classpath_parts.append(str(client.resolve()))
    classpath = os.pathsep.join(classpath_parts)
    asset_index = metadata.get("assetIndex", {}).get("id", metadata.get("assets", ""))
    substitutions = {
        "auth_player_name": identity["name"], "version_name": version,
        "game_directory": str(root.resolve()), "assets_root": str((root / "assets").resolve()),
        "assets_index_name": asset_index, "auth_uuid": identity["uuid"],
        "auth_access_token": identity["token"], "clientid": "", "auth_xuid": "",
        "user_type": identity["user_type"], "version_type": metadata.get("type", "release"),
        "natives_directory": str(native_dir.resolve()), "launcher_name": "mc-tui",
        "launcher_version": "0.2.0", "classpath": classpath,
        "classpath_separator": os.pathsep, "library_directory": str((root / "libraries").resolve()),
        "resolution_width": "854", "resolution_height": "480", "user_properties": "{}",
        "game_assets": str((root / "assets" / "virtual" / asset_index).resolve()),
    }
    jvm_args: list[str] = []
    game_args: list[str] = []
    arguments = metadata.get("arguments")
    if isinstance(arguments, dict):
        for item in arguments.get("jvm", []):
            _expand(item, substitutions, jvm_args)
        for item in arguments.get("game", []):
            _expand(item, substitutions, game_args)
    else:
        import shlex
        game_args = [_value(item, substitutions) for item in shlex.split(metadata.get("minecraftArguments", ""))]
    jvm_args.append(f"-Djava.library.path={native_dir.resolve()}")
    jvm_args.append(f"-Xmx{memory_mb}M")
    if "${classpath}" not in str(arguments):
        jvm_args.extend(["-cp", classpath])
    jvm_args.append(metadata["mainClass"])
    log_info = metadata.get("logging", {}).get("client", {})
    log_file = log_info.get("file", {})
    if log_file.get("id"):
        config_path = root / "assets" / "log_configs" / log_file["id"]
        if config_path.is_file():
            log_arg = log_info.get("argument", "-Dlog4j.configurationFile=${path}")
            jvm_args.insert(0, log_arg.replace("${path}", str(config_path.resolve())))
    return [java_path, *jvm_args, *game_args], version_dir


def launch(root: Path, version: str, metadata: dict[str, Any], identity: dict[str, str],
           memory_mb: int, java_path: str = "") -> int:
    print("检查游戏运行库；缺失或校验失败的文件会尝试从元数据地址补下。")

    def progress(done: int, total: int, filename: str) -> None:
        print(f"\r运行库检查 {done}/{total}  {filename[:48]:48}", end="", flush=True)

    ensure_libraries(root, metadata, progress)
    print(file=sys.stdout)
    command, cwd = build_command(root, version, metadata, identity, memory_mb, java_path)
    print("\n启动游戏；日志会显示在此终端。按 Ctrl+C 可结束进程。\n")
    return subprocess.call(command, cwd=root)
