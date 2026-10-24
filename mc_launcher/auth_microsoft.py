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

from .localization import tr

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
        raise RuntimeError(tr('auth_microsoft.microsoft_sign_in_dependencies_are_missing_run_python_m_pip_install_r_requirements_txt')) from exc
    try:
        backend = keyring.get_keyring()
        if backend.priority <= 0:
            raise RuntimeError(tr('auth_microsoft.no_system_credential_store_is_available_install_and_configure_windows_credential_manager_macos_keychain_or_secret_service'))
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(tr('auth_microsoft.could_not_access_the_system_credential_store', v_a=exc)) from exc
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
                raise RuntimeError(tr('auth_microsoft.the_authentication_service_returned_an_unrecognized_response'))
            return result
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1200]
        if exc.code == 404 and url == MINECRAFT_PROFILE_URL:
            raise RuntimeError(tr('auth_microsoft.this_microsoft_account_has_no_minecraft_java_profile_or_game_entitlement')) from exc
        if exc.code == 403 and "minecraftservices.com" in url:
            raise RuntimeError(tr('auth_microsoft.minecraft_services_rejected_the_oauth_application_check_whether_the_app_is_approved_for_minecraft_services_third_party_client_ids_may_require_microsoft_mojang_review')) from exc
        raise RuntimeError(tr('auth_microsoft.authentication_request_failed_http', v_a=exc.code, v_b=detail)) from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(tr('auth_microsoft.could_not_connect_to_the_authentication_service', v_a=exc)) from exc


def _request_form(url: str, payload: dict[str, str]) -> dict[str, Any]:
    request = Request(url, data=urlencode(payload).encode("utf-8"), headers={
        "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "MC-TUI/0.3",
    })
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
            if not isinstance(result, dict):
                raise RuntimeError(tr('auth_microsoft.microsoft_oauth_returned_an_unrecognized_response'))
            return result
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1200]
        raise RuntimeError(tr('auth_microsoft.microsoft_oauth_request_failed_http', v_a=exc.code, v_b=detail)) from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(tr('auth_microsoft.could_not_connect_to_microsoft_oauth', v_a=exc)) from exc


def _is_legacy_client(client_id: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{16}", client_id))


def _legacy_authorize(client_id: str, show_message: Callable[[str], None],
                      read_redirect: Callable[[], str] | None) -> dict[str, Any]:
    if read_redirect is None:
        raise RuntimeError(tr('auth_microsoft.legacy_minecraft_launcher_oauth_requires_you_to_paste_the_redirect_url_after_signing_in'))
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
    show_message(tr('auth_microsoft.microsoft_sign_in_opened_in_your_browser_after_signing_in_copy_the_full_redirect_url_from_the_address_bar_and_paste_it_into_the_terminal'))
    returned_url = read_redirect().strip()
    query = parse_qs(urlparse(returned_url).query)
    if "error" in query:
        raise RuntimeError(tr('auth_microsoft.microsoft_sign_in_did_not_complete', v_a=query.get('error_description', query['error'])[0]))
    codes = query.get("code", [])
    if not codes:
        raise RuntimeError(tr('auth_microsoft.the_redirect_url_does_not_contain_an_authorization_code_paste_the_full_url_from_your_browser_address_bar'))
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
                received["error"] = tr('auth_microsoft.oauth_callback_state_did_not_match_the_response_was_rejected')
            elif query.get("error"):
                received["error"] = query.get("error_description", query["error"])[0]
            elif query.get("code"):
                received["code"] = query["code"][0]
            else:
                received["error"] = tr('auth_microsoft.the_oauth_callback_did_not_contain_an_authorization_code')
            body = tr('auth_microsoft.microsoft_sign_in_is_complete_you_can_close_this_page_and_return_to_the_launcher') if received.get('code') else tr('auth_microsoft.microsoft_sign_in_did_not_complete_return_to_the_launcher_for_details')
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
        raise RuntimeError(tr('auth_microsoft.could_not_start_the_local_oauth_callback_server', v_a=exc)) from exc
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
    show_message(tr('auth_microsoft.a_browser_will_open_for_microsoft_authorization_the_page_will_return_to_the_launcher_when_sign_in_is_complete'))
    try:
        opened = webbrowser.open(url)
    except Exception as exc:
        server.server_close()
        raise RuntimeError(tr('auth_microsoft.could_not_open_a_browser_automatically', v_a=exc)) from exc
    if not opened:
        server.server_close()
        raise RuntimeError(tr('auth_microsoft.could_not_open_a_browser_automatically_check_your_browser_settings_and_try_again'))
    try:
        for _ in range(300):
            if event.is_set():
                break
            server.handle_request()
    finally:
        server.server_close()
    if not event.is_set():
        raise RuntimeError(tr('auth_microsoft.timed_out_waiting_for_the_microsoft_sign_in_callback_please_try_again'))
    if received.get("error"):
        raise RuntimeError(tr('auth_microsoft.microsoft_sign_in_failed', v_a=received['error']))
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
        raise RuntimeError(tr('auth_microsoft.xbox_live_did_not_return_a_user_token_make_sure_xbox_identity_is_enabled_for_this_account')) from exc

    xsts = _request_json(XSTS_URL, {
        "Properties": {"SandboxId": "RETAIL", "UserTokens": [user_token]},
        "RelyingParty": "rp://api.minecraftservices.com/",
        "TokenType": "JWT",
    })
    try:
        identity_token = "XBL3.0 x=" + user_hash + ";" + xsts["Token"]
    except KeyError as exc:
        raise RuntimeError(tr('auth_microsoft.xbox_xsts_did_not_return_an_authorization_token')) from exc

    minecraft = _request_json(MINECRAFT_LOGIN_URL, {
        "identityToken": identity_token,
        "ensureLegacyEnabled": True,
    })
    access_token = minecraft.get("access_token")
    if not access_token:
        raise RuntimeError(tr('auth_microsoft.minecraft_services_did_not_return_an_accesstoken'))
    profile = _request_json(MINECRAFT_PROFILE_URL, bearer=access_token)
    if not profile.get("id") or not profile.get("name"):
        raise RuntimeError(tr('auth_microsoft.this_microsoft_account_has_no_minecraft_java_profile_or_game_entitlement_you_may_not_own_minecraft_java_edition'))
    return profile, access_token


def sign_in(client_id: str, show_message: Callable[[str], None],
            read_redirect: Callable[[], str] | None = None) -> dict[str, str]:
    if _is_legacy_client(client_id):
        keyring = _dependencies()
        msa_tokens = _legacy_authorize(client_id, show_message, read_redirect)
        if not msa_tokens.get("access_token"):
            raise RuntimeError(tr('auth_microsoft.microsoft_oauth_did_not_return_an_access_token'))
        profile, _ = _minecraft_exchange(msa_tokens["access_token"], legacy_client=True)
        refresh_token = msa_tokens.get("refresh_token")
        if not refresh_token:
            raise RuntimeError(tr('auth_microsoft.microsoft_did_not_return_a_refresh_token_sign_in_again_and_grant_xbox_sign_in_permission'))
        _store_refresh(keyring, client_id, profile["id"], refresh_token)
        return {"name": profile["name"], "uuid": profile["id"], "type": "microsoft",
                "client_id": client_id, "auth_mode": "legacy"}

    keyring = _dependencies()
    result = _authorization_code(client_id, show_message)
    if not result.get("access_token"):
        error = result.get("error_description") or result.get("error") or tr('auth_microsoft.authorization_code_exchange_did_not_return_an_access_token')
        raise RuntimeError(tr('auth_microsoft.microsoft_sign_in_failed', v_a=error))
    profile, _ = _minecraft_exchange(result["access_token"])
    refresh_token = result.get("refresh_token")
    if not refresh_token:
        raise RuntimeError(tr('auth_microsoft.microsoft_did_not_return_a_refresh_token_authorize_again_and_grant_offline_access'))
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
            raise RuntimeError(tr('auth_microsoft.could_not_read_the_system_credential_store', v_a=exc)) from exc
        if not refresh_token:
            raise RuntimeError(tr('auth_microsoft.microsoft_refresh_token_is_missing_sign_in_again_from_the_accounts_menu'))
        msa_tokens = _request_form("https://login.live.com/oauth20_token.srf", {
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        })
        if not msa_tokens.get("access_token"):
            raise RuntimeError(tr('auth_microsoft.could_not_refresh_the_microsoft_session_please_sign_in_again'))
        _store_refresh(keyring, client_id, profile["uuid"],
                       msa_tokens.get("refresh_token") or refresh_token)
        # Live's refresh endpoint issues an RPS ticket in the modern form even
        # when the initial authorization used the legacy desktop redirect.
        minecraft_profile, access_token = _minecraft_exchange(msa_tokens["access_token"])
        if minecraft_profile.get("id", "").replace("-", "").lower() != profile.get("uuid", "").replace("-", "").lower():
            raise RuntimeError(tr('auth_microsoft.the_current_microsoft_session_does_not_match_the_selected_minecraft_profile_sign_in_to_that_account_again'))
        return {"name": minecraft_profile["name"], "uuid": minecraft_profile["id"].replace("-", ""),
                "token": access_token, "user_type": "msa"}

    keyring = _dependencies()
    refresh_key = _refresh_key(client_id, profile["uuid"])
    try:
        refresh_token = keyring.get_password(LEGACY_REFRESH_SERVICE, refresh_key)
    except Exception as exc:
        raise RuntimeError(tr('auth_microsoft.could_not_read_the_system_credential_store', v_a=exc)) from exc
    if not refresh_token:
        raise RuntimeError(tr('auth_microsoft.microsoft_refresh_token_is_missing_sign_in_again_from_the_accounts_menu'))
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
        detail = result.get("error_description") or result.get("error") or tr('auth_microsoft.the_token_has_expired')
        raise RuntimeError(tr('auth_microsoft.could_not_refresh_the_microsoft_session_sign_in_again', v_a=detail))
    _store_refresh(keyring, client_id, profile["uuid"],
                   result.get("refresh_token") or refresh_token)
    minecraft_profile, access_token = _minecraft_exchange(result["access_token"])
    if minecraft_profile.get("id", "").replace("-", "").lower() != profile.get("uuid", "").replace("-", "").lower():
        raise RuntimeError(tr('auth_microsoft.the_current_microsoft_session_does_not_match_the_selected_minecraft_profile_sign_in_to_that_account_again'))
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
            raise RuntimeError(tr('auth_microsoft.could_not_remove_the_microsoft_refresh_token_from_the_system_credential_store', v_a=exc)) from exc
        return
    keyring = _dependencies()
    try:
        name = _refresh_key(client_id, profile["uuid"])
        if keyring.get_password(LEGACY_REFRESH_SERVICE, name):
            keyring.delete_password(LEGACY_REFRESH_SERVICE, name)
    except Exception as exc:
        raise RuntimeError(tr('auth_microsoft.could_not_remove_the_microsoft_refresh_token_from_the_system_credential_store', v_a=exc)) from exc


def _refresh_key(client_id: str, profile_id: str) -> str:
    return f"{client_id}:{profile_id.replace('-', '').lower()}"


def _store_refresh(keyring: Any, client_id: str, profile_id: str, token: str) -> None:
    try:
        keyring.set_password(LEGACY_REFRESH_SERVICE, _refresh_key(client_id, profile_id), token)
    except Exception as exc:
        raise RuntimeError(tr('auth_microsoft.could_not_safely_store_the_refresh_token_in_the_system_credential_store', v_a=exc)) from exc
