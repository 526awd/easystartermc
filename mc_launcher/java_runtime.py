"""Find an installed Java runtime matching a Minecraft version's requirement."""
import glob
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from .localization import tr


def required_major(version: str, metadata: dict[str, Any]) -> int:
    requirement = metadata.get("javaVersion", {})
    major = requirement.get("majorVersion") if isinstance(requirement, dict) else None
    if isinstance(major, int) and major > 0:
        return major

    # Legacy version manifests do not always contain javaVersion.
    match = re.match(r"^1\.(\d+)(?:\.(\d+))?", version)
    if match:
        minor = int(match.group(1))
        patch = int(match.group(2) or 0)
        if minor <= 16:
            return 8
        if minor == 17:
            return 16
        if minor == 20 and patch >= 5:
            return 21
        if minor >= 18:
            return 17 if minor < 20 or (minor == 20 and patch < 5) else 21

    raise RuntimeError(tr('java_runtime.could_not_determine_the_java_version_required_by_minecraft_check_the_version_metadata', v_a=version))


def _executables(value: str) -> list[Path]:
    if not value:
        return []
    path = Path(os.path.expandvars(value)).expanduser()
    result: list[Path] = []
    if path.is_dir():
        binary = "java.exe" if platform.system() == "Windows" else "java"
        result.extend((path / "bin" / binary, path / "Contents" / "Home" / "bin" / binary))
    elif path.is_file():
        result.append(path)
    else:
        found = shutil.which(value)
        if found:
            result.append(Path(found))
    return result


def _candidates(preferred: str = "") -> list[Path]:
    paths: list[Path] = []
    paths.extend(_executables(preferred))
    paths.extend(_executables(os.environ.get("JAVA_HOME", "")))

    binary = "java.exe" if platform.system() == "Windows" else "java"
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if directory:
            candidate = Path(directory).expanduser() / binary
            if candidate.is_file():
                paths.append(candidate)

    system = platform.system()
    patterns: list[str] = []
    if system == "Windows":
        for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(variable)
            if base:
                patterns.extend([
                    str(Path(base) / "Java" / "*" / "bin" / "java.exe"),
                    str(Path(base) / "Eclipse Adoptium" / "*" / "bin" / "java.exe"),
                    str(Path(base) / "Microsoft" / "*" / "bin" / "java.exe"),
                    str(Path(base) / "Zulu" / "*" / "bin" / "java.exe"),
                    str(Path(base) / "Amazon Corretto" / "*" / "bin" / "java.exe"),
                ])
    elif system == "Darwin":
        patterns.extend([
            "/Library/Java/JavaVirtualMachines/*/Contents/Home/bin/java",
            str(Path.home() / "Library/Java/JavaVirtualMachines/*/Contents/Home/bin/java"),
        ])
    else:
        patterns.extend([
            "/usr/lib/jvm/*/bin/java",
            "/usr/java/*/bin/java",
            "/opt/java/*/bin/java",
            str(Path.home() / ".sdkman/candidates/java/*/bin/java"),
        ])
    for pattern in patterns:
        paths.extend(Path(item) for item in glob.glob(pattern))

    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        if not path.is_file():
            continue
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path.absolute()
        key = str(resolved).casefold()
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    return unique


def major_version(java_path: Path) -> int | None:
    try:
        result = subprocess.run(
            [str(java_path), "-version"], capture_output=True, text=True,
            timeout=8, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stdout or "") + "\n" + (result.stderr or "")
    match = re.search(r'version\s+"([0-9]+(?:\.[0-9]+)*)', output, re.IGNORECASE)
    if not match:
        match = re.search(r"\b(?:openjdk|java)\s+([0-9]+(?:\.[0-9]+)*)", output, re.IGNORECASE)
    if not match:
        return None
    parts = match.group(1).split(".")
    try:
        return int(parts[1]) if parts[0] == "1" and len(parts) > 1 else int(parts[0])
    except ValueError:
        return None


def select_java(version: str, metadata: dict[str, Any], preferred: str = "") -> tuple[str, int]:
    required = required_major(version, metadata)
    detected: list[tuple[Path, int]] = []
    for path in _candidates(preferred):
        major = major_version(path)
        if major is not None:
            detected.append((path, major))
            if major == required:
                return str(path), major

    available = sorted({major for _, major in detected})
    available_text = ", ".join(str(major) for major in available) or tr('java_runtime.no_java_installations_detected')
    raise RuntimeError(
        tr('java_runtime.minecraft_requires_java_detected_install_java_or_set_its_path_in_settings_enter_auto_to_restore_automatic_selection', v_a=version, v_b=required, v_c=available_text, v_d=required)
    )


def resolve_java(root: Path, version: str, metadata: dict[str, Any], preferred: str = "",
                 progress_callback: Callable[[int, int, str], None] | None = None) -> tuple[str, int]:
    """Select an installed exact match or install a compatible Microsoft JDK privately."""
    try:
        return select_java(version, metadata, preferred)
    except RuntimeError as missing_error:
        required = required_major(version, metadata)
        from .java_downloader import compatible_major, ensure_microsoft_jdk

        jdk_major = compatible_major(required)
        if jdk_major is None:
            raise RuntimeError(
                tr('java_runtime.microsoft_build_of_openjdk_has_no_supported_lts_release_for_java', v_a=missing_error, v_b=required)
            ) from missing_error
        for path in _candidates(preferred):
            if major_version(path) == jdk_major:
                return str(path.resolve()), jdk_major
        try:
            path, actual_major = ensure_microsoft_jdk(
                required, root / "runtime", progress_callback
            )
        except (OSError, RuntimeError) as download_error:
            raise RuntimeError(
                tr('java_runtime.automatic_download_of_microsoft_jdk_failed', v_a=missing_error, v_b=jdk_major, v_c=download_error)
            ) from download_error
        return str(path.resolve()), actual_major
