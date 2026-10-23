"""Microsoft OAuth and the Xbox/XSTS-to-Minecraft token exchange."""
import base64
import hashlib
import json
import os
import re
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

SCOPES = "XboxLive.SignIn offline_access"
AUTHORITY = "https://login.microsoftonline.com/consumers"
TOKEN_URL = AUTHORITY + "/oauth2/v2.0/token"
AUTHORIZE_URL = AUTHORITY + "/oauth2/v2.0/authorize"
OFFICIAL_CLIENT_ID = "b51e631c-7fa8-40e0-8398-487b1bdb451e"
LEGACY_REFRESH_SERVICE = "mc-tui-microsoft-refresh-token"
LEGACY_SCOPE = "service::user.auth.xboxlive.com::MBI_SSL"
XBOX_USER_URL = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
MINECRAFT_LOGIN_URL = "https://api.minecraftservices.com/authentication/login_with_xbox"
MINECRAFT_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"


def _dependencies() -> Any:
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError("Microsoft 登录依赖未安装。请运行：python -m pip install -r requirements.txt") from exc
    try:
        backend = keyring.get_keyring()
        if backend.priority <= 0:
            raise RuntimeError("没有可用的系统安全凭据库；请安装并配置 Windows Credential Manager、macOS Keychain 或 Secret Service。")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"无法访问系统凭据库：{exc}") from exc
    return keyring


def _request_json(url: str, payload: dict[str, Any] | None = None,
                  bearer: str = "") -> dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": "MC-TUI/0.3"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    if "xboxlive.com" in url:
        headers["x-xbl-contract-version"] = "1"
    request = Request(url, data=data, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
            if not isinstance(result, dict):
                raise RuntimeError("认证服务返回了无法识别的数据。")
            return result
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1200]
        if exc.code == 404 and url == MINECRAFT_PROFILE_URL:
            raise RuntimeError("该 Microsoft 账号没有 Minecraft Java 档案或游戏权限。") from exc
        if exc.code == 403 and "minecraftservices.com" in url:
            raise RuntimeError("Minecraft 服务拒绝了 OAuth 应用 (403)。请检查应用是否获准访问 Minecraft Services；第三方客户端 ID 可能需要 Microsoft/Mojang 审核。") from exc
        raise RuntimeError(f"认证请求失败 (HTTP {exc.code})：{detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"无法连接认证服务：{exc}") from exc


def _request_form(url: str, payload: dict[str, str]) -> dict[str, Any]:
    request = Request(url, data=urlencode(payload).encode("utf-8"), headers={
        "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "MC-TUI/0.3",
    })
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
            if not isinstance(result, dict):
                raise RuntimeError("Microsoft OAuth 返回了无法识别的数据。")
            return result
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1200]
        raise RuntimeError(f"Microsoft OAuth 请求失败 (HTTP {exc.code})：{detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"无法连接 Microsoft OAuth：{exc}") from exc


def _is_legacy_client(client_id: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{16}", client_id))


def _legacy_authorize(client_id: str, show_message: Callable[[str], None],
                      read_redirect: Callable[[], str] | None) -> dict[str, Any]:
    if read_redirect is None:
        raise RuntimeError("旧版 Minecraft Launcher OAuth 需要粘贴浏览器登录后的重定向地址。")
    redirect_uri = "https://login.live.com/oauth20_desktop.srf"
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": LEGACY_SCOPE,
        "display": "touch",
        "locale": "en",
    }
    login_url = "https://login.live.com/oauth20_authorize.srf?" + urlencode(params)
    webbrowser.open(login_url)
    show_message("浏览器已打开 Microsoft 登录。登录完成后，复制地址栏中的完整重定向 URL 并粘贴到终端。")
    returned_url = read_redirect().strip()
    query = parse_qs(urlparse(returned_url).query)
    if "error" in query:
        raise RuntimeError("Microsoft 登录未完成：" + query.get("error_description", query["error"])[0])
    codes = query.get("code", [])
    if not codes:
        raise RuntimeError("重定向地址中没有授权码。请粘贴浏览器地址栏中的完整 URL。")
    return _request_form("https://login.live.com/oauth20_token.srf", {
        "client_id": client_id,
        "code": codes[0],
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
        "scope": LEGACY_SCOPE,
    })


def _authorization_code(client_id: str, show_message: Callable[[str], None]) -> dict[str, Any]:
    """Run the public-client authorization-code flow with PKCE and a loopback callback."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    state = secrets.token_urlsafe(32)
    received: dict[str, Any] = {}
    event = threading.Event()

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            query = parse_qs(urlparse(self.path).query)
            if not secrets.compare_digest(query.get("state", [""])[0], state):
                received["error"] = "OAuth 回调 state 不匹配，已拒绝此响应。"
            elif query.get("error"):
                received["error"] = query.get("error_description", query["error"])[0]
            elif query.get("code"):
                received["code"] = query["code"][0]
            else:
                received["error"] = "OAuth 回调中没有授权码。"
            body = ("Microsoft 登录完成。可以关闭此页面并返回启动器。"
                    if received.get("code") else "Microsoft 登录未完成。请返回启动器查看错误信息。")
            encoded = body.encode("utf-8")
            self.send_response(200 if received.get("code") else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            event.set()

        def log_message(self, *_args: Any) -> None:
            return

    try:
        server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
    except OSError as exc:
        raise RuntimeError(f"无法启动本机 OAuth 回调服务：{exc}") from exc
    server.timeout = 1
    # Microsoft accepts a loopback localhost redirect with a dynamically chosen port.
    redirect_uri = f"http://localhost:{server.server_port}"
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = AUTHORIZE_URL + "?" + urlencode(params)
    show_message("即将打开浏览器进行 Microsoft 授权。完成后页面会自动返回启动器。")
    try:
        opened = webbrowser.open(url)
    except Exception as exc:
        server.server_close()
        raise RuntimeError(f"无法自动打开浏览器：{exc}") from exc
    if not opened:
        server.server_close()
        raise RuntimeError("无法自动打开浏览器；请检查系统浏览器设置后重试。")
    try:
        for _ in range(300):
            if event.is_set():
                break
            server.handle_request()
    finally:
        server.server_close()
    if not event.is_set():
        raise RuntimeError("等待 Microsoft 登录回调超时，请重新登录。")
    if received.get("error"):
        raise RuntimeError("Microsoft 登录失败：" + received["error"])
    token_request = {
        "client_id": client_id,
        "grant_type": "authorization_code",
        "code": received["code"],
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
        "scope": SCOPES,
    }
    client_secret = os.environ.get("MC_MICROSOFT_CLIENT_SECRET", "").strip()
    if client_secret:
        token_request["client_secret"] = client_secret
    return _request_form(TOKEN_URL, token_request)


def _minecraft_exchange(ms_access_token: str, legacy_client: bool = False) -> tuple[dict[str, Any], str]:
    user = _request_json(XBOX_USER_URL, {
        "Properties": {
            "AuthMethod": "RPS",
            "SiteName": "user.auth.xboxlive.com",
            "RpsTicket": ms_access_token if legacy_client else "d=" + ms_access_token,
        },
        "RelyingParty": "http://auth.xboxlive.com",
        "TokenType": "JWT",
    })
    try:
        user_token = user["Token"]
        user_hash = user["DisplayClaims"]["xui"][0]["uhs"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Xbox Live 没有返回用户令牌。请确认账号已启用 Xbox 身份。") from exc

    xsts = _request_json(XSTS_URL, {
        "Properties": {"SandboxId": "RETAIL", "UserTokens": [user_token]},
        "RelyingParty": "rp://api.minecraftservices.com/",
        "TokenType": "JWT",
    })
    try:
        identity_token = "XBL3.0 x=" + user_hash + ";" + xsts["Token"]
    except KeyError as exc:
        raise RuntimeError("Xbox XSTS 没有返回授权令牌。") from exc

    minecraft = _request_json(MINECRAFT_LOGIN_URL, {
        "identityToken": identity_token,
        "ensureLegacyEnabled": True,
    })
    access_token = minecraft.get("access_token")
    if not access_token:
        raise RuntimeError("Minecraft Services 没有返回 accessToken。")
    profile = _request_json(MINECRAFT_PROFILE_URL, bearer=access_token)
    if not profile.get("id") or not profile.get("name"):
        raise RuntimeError("该 Microsoft 账号没有可用的 Minecraft Java 档案或游戏权限,你很可能没有购买我的世界正版。")
    return profile, access_token


def sign_in(client_id: str, show_message: Callable[[str], None],
            read_redirect: Callable[[], str] | None = None) -> dict[str, str]:
    if _is_legacy_client(client_id):
        keyring = _dependencies()
        msa_tokens = _legacy_authorize(client_id, show_message, read_redirect)
        if not msa_tokens.get("access_token"):
            raise RuntimeError("Microsoft OAuth 没有返回访问令牌。")
        profile, _ = _minecraft_exchange(msa_tokens["access_token"], legacy_client=True)
        refresh_token = msa_tokens.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("Microsoft 没有返回 refresh token；请重新登录并确认同意 Xbox 登录权限。")
        _store_refresh(keyring, client_id, profile["id"], refresh_token)
        return {"name": profile["name"], "uuid": profile["id"], "type": "microsoft",
                "client_id": client_id, "auth_mode": "legacy"}

    keyring = _dependencies()
    result = _authorization_code(client_id, show_message)
    if not result.get("access_token"):
        error = result.get("error_description") or result.get("error") or "授权码兑换没有返回访问令牌。"
        raise RuntimeError("Microsoft 登录失败：" + error)
    profile, _ = _minecraft_exchange(result["access_token"])
    refresh_token = result.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("Microsoft 没有返回 refresh token；请重新授权并同意离线访问权限。")
    _store_refresh(keyring, client_id, profile["id"], refresh_token)
    return {"name": profile["name"], "uuid": profile["id"],
            "type": "microsoft", "client_id": client_id, "auth_mode": "pkce"}


def minecraft_identity(profile: dict[str, str], client_id: str) -> dict[str, str]:
    if _is_legacy_client(client_id):
        keyring = _dependencies()
        refresh_key = _refresh_key(client_id, profile["uuid"])
        try:
            refresh_token = keyring.get_password(LEGACY_REFRESH_SERVICE, refresh_key)
        except Exception as exc:
            raise RuntimeError(f"无法读取系统凭据库：{exc}") from exc
        if not refresh_token:
            raise RuntimeError("Microsoft refresh token 不存在。请在账号菜单重新登录。")
        msa_tokens = _request_form("https://login.live.com/oauth20_token.srf", {
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        })
        if not msa_tokens.get("access_token"):
            raise RuntimeError("Microsoft 会话刷新失败；请重新登录。")
        _store_refresh(keyring, client_id, profile["uuid"],
                       msa_tokens.get("refresh_token") or refresh_token)
        # Live's refresh endpoint issues an RPS ticket in the modern form even
        # when the initial authorization used the legacy desktop redirect.
        minecraft_profile, access_token = _minecraft_exchange(msa_tokens["access_token"])
        if minecraft_profile.get("id", "").replace("-", "").lower() != profile.get("uuid", "").replace("-", "").lower():
            raise RuntimeError("当前 Microsoft 会话与所选 Minecraft 档案不匹配，请重新登录该账号。")
        return {"name": minecraft_profile["name"], "uuid": minecraft_profile["id"].replace("-", ""),
                "token": access_token, "user_type": "msa"}

    keyring = _dependencies()
    refresh_key = _refresh_key(client_id, profile["uuid"])
    try:
        refresh_token = keyring.get_password(LEGACY_REFRESH_SERVICE, refresh_key)
    except Exception as exc:
        raise RuntimeError(f"无法读取系统凭据库：{exc}") from exc
    if not refresh_token:
        raise RuntimeError("Microsoft refresh token 不存在。请在账号菜单重新登录。")
    token_request = {
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": SCOPES,
    }
    client_secret = os.environ.get("MC_MICROSOFT_CLIENT_SECRET", "").strip()
    if client_secret:
        token_request["client_secret"] = client_secret
    result = _request_form(TOKEN_URL, token_request)
    if not result.get("access_token"):
        detail = result.get("error_description") or result.get("error") or "令牌已失效。"
        raise RuntimeError("Microsoft 会话刷新失败，请重新登录：" + detail)
    _store_refresh(keyring, client_id, profile["uuid"],
                   result.get("refresh_token") or refresh_token)
    minecraft_profile, access_token = _minecraft_exchange(result["access_token"])
    if minecraft_profile.get("id", "").replace("-", "").lower() != profile.get("uuid", "").replace("-", "").lower():
        raise RuntimeError("当前 Microsoft 会话与所选 Minecraft 档案不匹配，请重新登录该账号。")
    return {"name": minecraft_profile["name"], "uuid": minecraft_profile["id"].replace("-", ""),
            "token": access_token, "user_type": "msa"}


def remove_account(profile: dict[str, str]) -> None:
    client_id = profile.get("client_id", OFFICIAL_CLIENT_ID)
    if _is_legacy_client(client_id):
        keyring = _dependencies()
        try:
            name = _refresh_key(client_id, profile["uuid"])
            if keyring.get_password(LEGACY_REFRESH_SERVICE, name):
                keyring.delete_password(LEGACY_REFRESH_SERVICE, name)
        except Exception as exc:
            raise RuntimeError(f"无法从系统凭据库删除 Microsoft refresh token：{exc}") from exc
        return
    keyring = _dependencies()
    try:
        name = _refresh_key(client_id, profile["uuid"])
        if keyring.get_password(LEGACY_REFRESH_SERVICE, name):
            keyring.delete_password(LEGACY_REFRESH_SERVICE, name)
    except Exception as exc:
        raise RuntimeError(f"无法从系统凭据库删除 Microsoft refresh token：{exc}") from exc


def _refresh_key(client_id: str, profile_id: str) -> str:
    return f"{client_id}:{profile_id.replace('-', '').lower()}"


def _store_refresh(keyring: Any, client_id: str, profile_id: str, token: str) -> None:
    try:
        keyring.set_password(LEGACY_REFRESH_SERVICE, _refresh_key(client_id, profile_id), token)
    except Exception as exc:
        raise RuntimeError(f"无法将 refresh token 安全写入系统凭据库：{exc}") from exc
