"""Yggdrasil third-party authentication and authlib-injector integration."""
import base64
import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

TOKEN_SERVICE = "mc-tui-yggdrasil-tokens"
INJECTOR_API = "https://authlib-injector.yushi.moe/artifact/latest.json"


def _keyring() -> Any:
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError("第三方登录需要 keyring，请安装 requirements.txt 中的依赖。") from exc
    try:
        if keyring.get_keyring().priority <= 0:
            raise RuntimeError("没有可用的系统安全凭据库，请配置 Windows Credential Manager、macOS Keychain 或 Secret Service。")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"无法访问系统凭据库：{exc}") from exc
    return keyring


def _validate_url(url: str) -> str:
    url = url.strip()
    if not url:
        raise ValueError("认证服务器地址不能为空。")
    if "://" not in url:
        url = "https://" + url
    parsed = urlsplit(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("认证服务器地址必须是有效的 HTTP(S) URL。")
    if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("认证服务器必须使用 HTTPS；仅允许本机回环地址使用 HTTP。")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") + "/", "", ""))


def _get(url: str) -> tuple[bytes, Any]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "MC-TUI/0.3"})
    try:
        with urlopen(request, timeout=30) as response:
            final_url = _validate_url(response.geturl())
            if urlsplit(final_url).scheme == "http" and urlsplit(final_url).hostname not in (
                    "localhost", "127.0.0.1", "::1"):
                raise RuntimeError("认证服务器重定向到不安全的公网 HTTP，已拒绝连接。")
            if urlsplit(response.geturl()).scheme != "https" and urlsplit(url).scheme == "https":
                raise RuntimeError("认证服务器将 HTTPS 请求重定向到不安全的 HTTP，已拒绝连接。")
            return response.read(), response.headers
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"认证服务器请求失败 (HTTP {exc.code})：{detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"无法连接认证服务器：{exc}") from exc


def resolve_server(address: str) -> tuple[str, dict[str, Any]]:
    """Resolve an authlib-injector API root and fetch its metadata."""
    url = _validate_url(address)
    body, headers = _get(url)
    indication = headers.get("X-Authlib-Injector-API-Location")
    if indication:
        target = urljoin(url, indication)
        target = _validate_url(target)
        if target != url:
            url = target
            body, _ = _get(url)
    try:
        metadata = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("认证服务器地址没有返回有效的 Yggdrasil 元数据。") from exc
    if not isinstance(metadata, dict):
        raise RuntimeError("认证服务器元数据格式无效。")
    return url, metadata


def _request(url: str, payload: dict[str, Any], allow_empty: bool = False) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers={
        "Accept": "application/json", "Content-Type": "application/json",
        "User-Agent": "MC-TUI/0.3",
    })
    try:
        with urlopen(request, timeout=30) as response:
            final_url = _validate_url(response.geturl())
            if urlsplit(final_url).scheme == "http" and urlsplit(final_url).hostname not in (
                    "localhost", "127.0.0.1", "::1"):
                raise RuntimeError("Yggdrasil 请求被重定向到不安全的公网 HTTP，已拒绝发送凭据。")
            if urlsplit(url).scheme == "https" and urlsplit(response.geturl()).scheme != "https":
                raise RuntimeError("Yggdrasil 服务将 HTTPS 请求降级到 HTTP，已拒绝发送凭据。")
            raw = response.read()
    except HTTPError as exc:
        raw = exc.read()
        try:
            error = json.loads(raw.decode("utf-8"))
            message = error.get("errorMessage") or error.get("error") or raw.decode("utf-8", errors="replace")[:1000]
        except ValueError:
            message = raw.decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"Yggdrasil 登录请求失败 (HTTP {exc.code})：{message}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"无法连接 Yggdrasil 认证服务：{exc}") from exc
    if not raw and allow_empty:
        return {}
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("Yggdrasil 认证服务返回了无效响应。") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Yggdrasil 认证服务返回了无法识别的数据。")
    return result


def _endpoint(server: str, path: str) -> str:
    return urljoin(server, path)


def _profile_id(profile: dict[str, Any]) -> str:
    # Authentication responses use `id`; launcher profile records use `uuid`.
    value = str(profile.get("id") or profile.get("uuid", "")).replace("-", "")
    if not re.fullmatch(r"[0-9a-fA-F]{32}", value):
        raise RuntimeError("Yggdrasil 服务返回了无效的 Minecraft UUID。")
    return value.lower()


def _token_key(server: str, player_uuid: str) -> str:
    return hashlib.sha256(f"{server}\n{player_uuid.lower()}".encode()).hexdigest()


def _save_tokens(keyring: Any, server: str, player_uuid: str, tokens: dict[str, str]) -> None:
    try:
        keyring.set_password(TOKEN_SERVICE, _token_key(server, player_uuid), json.dumps(tokens))
    except Exception as exc:
        raise RuntimeError(f"无法将登录令牌保存到系统凭据库：{exc}") from exc


def sign_in(server_address: str, username: str, password: str,
            choose_profile: Callable[[list[dict[str, Any]]], dict[str, Any]] | None = None) -> dict[str, str]:
    if not username.strip() or not password:
        raise ValueError("账号和密码不能为空。")
    server, _ = resolve_server(server_address)
    keyring = _keyring()
    client_token = str(uuid.uuid4())
    response = _request(_endpoint(server, "authserver/authenticate"), {
        "agent": {"name": "Minecraft", "version": 1}, "username": username.strip(),
        "password": password, "clientToken": client_token, "requestUser": True,
    })
    access_token = response.get("accessToken")
    if not access_token:
        raise RuntimeError("Yggdrasil 服务没有返回 accessToken。")
    client_token = str(response.get("clientToken") or client_token)
    selected = response.get("selectedProfile")
    if not selected:
        profiles = response.get("availableProfiles") or []
        if not profiles:
            raise RuntimeError("该账号没有可用的 Minecraft 档案。")
        if len(profiles) == 1:
            selected = profiles[0]
        elif choose_profile:
            selected = choose_profile(profiles)
        else:
            raise RuntimeError("账号有多个游戏档案，请在启动器中选择档案。")
        response = _request(_endpoint(server, "authserver/refresh"), {
            "accessToken": access_token, "clientToken": client_token,
            "selectedProfile": {"id": selected["id"], "name": selected["name"]},
            "requestUser": True,
        })
        access_token = response.get("accessToken") or access_token
        client_token = str(response.get("clientToken") or client_token)
        selected = response.get("selectedProfile") or selected
    player_uuid = _profile_id(selected)
    name = str(selected.get("name", ""))
    if not name:
        raise RuntimeError("Yggdrasil 服务没有返回游戏档案名称。")
    _save_tokens(keyring, server, player_uuid, {"accessToken": str(access_token), "clientToken": client_token})
    return {"name": name, "uuid": player_uuid, "type": "yggdrasil", "auth_server": server,
            "profile_key": "yggdrasil:" + _token_key(server, player_uuid)}


def minecraft_identity(profile: dict[str, Any]) -> dict[str, str]:
    server = _validate_url(str(profile.get("auth_server", "")))
    player_uuid = _profile_id(profile)
    keyring = _keyring()
    try:
        raw = keyring.get_password(TOKEN_SERVICE, _token_key(server, player_uuid))
    except Exception as exc:
        raise RuntimeError(f"无法读取系统凭据库：{exc}") from exc
    if not raw:
        raise RuntimeError("第三方账号令牌不存在，请在账号菜单重新登录。")
    try:
        tokens = json.loads(raw)
        access_token, client_token = tokens["accessToken"], tokens["clientToken"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("第三方账号令牌缓存损坏，请重新登录。") from exc
    try:
        _request(_endpoint(server, "authserver/validate"), {
            "accessToken": access_token, "clientToken": client_token,
        }, allow_empty=True)
    except RuntimeError:
        refreshed = _request(_endpoint(server, "authserver/refresh"), {
            "accessToken": access_token, "clientToken": client_token,
            "selectedProfile": {"id": player_uuid, "name": profile["name"]},
            "requestUser": True,
        })
        access_token = str(refreshed.get("accessToken", ""))
        client_token = str(refreshed.get("clientToken") or client_token)
        if not access_token:
            raise RuntimeError("第三方账号令牌刷新失败，请重新登录。")
        selected = refreshed.get("selectedProfile") or {}
        if selected and _profile_id(selected) != player_uuid:
            raise RuntimeError("认证服务返回的档案与当前账号不匹配，请重新登录。")
        _save_tokens(keyring, server, player_uuid, {"accessToken": access_token, "clientToken": client_token})
    return {"name": profile["name"], "uuid": player_uuid, "token": str(access_token), "user_type": "mojang",
            "auth_server": server}


def remove_account(profile: dict[str, Any]) -> None:
    keyring = _keyring()
    server = _validate_url(str(profile.get("auth_server", "")))
    player_uuid = _profile_id(profile)
    name = _token_key(server, player_uuid)
    try:
        if keyring.get_password(TOKEN_SERVICE, name):
            keyring.delete_password(TOKEN_SERVICE, name)
    except Exception as exc:
        raise RuntimeError(f"无法从系统凭据库删除第三方登录令牌：{exc}") from exc


def ensure_injector(root: Path) -> Path:
    """Download the official authlib-injector artifact and verify its SHA-256."""
    raw, _ = _get(INJECTOR_API)
    try:
        artifact = json.loads(raw.decode("utf-8"))
        expected = str(artifact["checksums"]["sha256"]).lower()
        url = str(artifact["download_url"])
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("authlib-injector 下载元数据格式无效。") from exc
    if urlsplit(url).scheme != "https" or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise RuntimeError("authlib-injector 下载元数据缺少有效 HTTPS 地址或 SHA-256。")
    path = root / "libraries" / "authlib-injector.jar"
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
        return path
    data, _ = _get(url)
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise RuntimeError(f"authlib-injector SHA-256 校验失败：期望 {expected}，实际 {actual}。")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".jar.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)
    return path


def prefetched_metadata(server: str) -> str:
    _, metadata = resolve_server(server)
    return base64.b64encode(json.dumps(metadata, separators=(",", ":")).encode("utf-8")).decode("ascii")
