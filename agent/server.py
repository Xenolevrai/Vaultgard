"""server.py — API + dashboard VaultGuard, durci pour être exposé sur Internet.

    python3 server.py                      -> http://localhost:8000 (mode local : admin autorisé depuis cette machine)
    python3 server.py --hash-password      -> génère ADMIN_PASSWORD_HASH pour la production

Sécurité (voir docs/SECURITE.md) :
  - écoute sur 127.0.0.1 par défaut ; liste blanche d'en-têtes Host (anti DNS rebinding)
  - sessions serveur (cookie HttpOnly, SameSite=Strict, Secure en prod) + jeton CSRF obligatoire sur chaque POST
  - JSON uniquement, corps <= 16 Ko, validation stricte des types, erreurs génériques (pas de fuite interne)
  - limitation de débit par IP, verrouillage après échecs de connexion, sockets avec timeout (anti slowloris)
  - en-têtes de sécurité : CSP à nonce, X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy, HSTS
  - chaque visiteur a son propre bac à sable ; seul l'admin agit sur le vrai coffre
"""
from __future__ import annotations

import argparse
import base64
import csv
import getpass
import hashlib
import hmac
import io
import ipaddress
import json
import logging
import os
import secrets
import sys
import threading
import time
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent import MODE_LABELS, MODES, make_chain, run, run_custom
from chain import ChainError
from firewall import CATALOG, scan_injection
from scenarios import SCENARIOS, addresses
try:
    from orgs import OrgError, require_role
except ImportError:
    from agent.orgs import OrgError, require_role

DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"
DASHBOARD = DASHBOARD_DIR / "index.html"
MAX_BODY = 16 * 1024
SESSION_TTL = 2 * 3600
MAX_SESSIONS = 500
CSV_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")

log = logging.getLogger("vaultguard")


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "oui"}


class Config:
    def __init__(self):
        self.host = os.environ.get("HOST", "127.0.0.1")
        self.port = int(os.environ.get("PORT", "8000"))
        self.allowed_hosts = {h.strip().lower() for h in
                              os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()}
        self.password_hash = os.environ.get("ADMIN_PASSWORD_HASH", "")
        self.cookie_secure = env_flag("COOKIE_SECURE")
        self.trust_proxy = env_flag("TRUST_PROXY")
        self.backend = os.environ.get("CHAIN", "mock") or "mock"
        self.llm = bool(os.environ.get("ANTHROPIC_API_KEY"))
        # Mode local : pas de mot de passe ET écoute en boucle locale -> l'admin est la personne devant la machine.
        self.local_admin = not self.password_hash and _is_loopback(self.host)


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


# ------------------------------------------------------------------ mots de passe (scrypt)

from db import hash_password, verify_password  # noqa: E402  (source unique, réexportée)


# ------------------------------------------------------------------ sessions & limitation de débit

class Sessions:
    def __init__(self):
        self._d: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, sid: str | None) -> dict | None:
        if not sid:
            return None
        with self._lock:
            s = self._d.get(sid)
            if not s or time.time() - s["last"] > SESSION_TTL:
                self._d.pop(sid, None)
                return None
            s["last"] = time.time()
            self._d.move_to_end(sid)
            return s

    def create(self, sid: str | None = None) -> tuple[str, dict]:
        if sid is None:
            sid = secrets.token_urlsafe(32)
        s = {"csrf": secrets.token_urlsafe(32), "admin": False, "last": time.time(), "chain": None,
             "mode": "full", "lock": threading.Lock()}
        with self._lock:
            self._d[sid] = s
            while len(self._d) > MAX_SESSIONS:  # mémoire bornée : on évince la plus ancienne
                self._d.popitem(last=False)
        return sid, s

    def drop(self, sid: str) -> None:
        with self._lock:
            self._d.pop(sid, None)


def _bind_account_session(token: str, user: dict) -> dict:
    """État mémoire (CSRF, bac à sable) d'une session de compte v3, lié à l'utilisateur en base.

    Le droit d'agir sur le coffre réel (« admin ») n'est donné qu'à un super-admin dont la 2FA est active.
    """
    _, s = SESSIONS.create(token)
    s["uid"] = user["id"]
    s["admin"] = bool(user.get("is_superadmin") and user.get("totp_enabled"))
    return s


class RateLimiter:
    """Seau à jetons par (IP, catégorie)."""

    LIMITS = {"get": (240, 60), "post": (60, 60), "run": (30, 60), "login": (5, 300), "llm": (5, 300)}

    def __init__(self):
        self._b: dict[tuple[str, str], tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, ip: str, kind: str) -> bool:
        cap, per = self.LIMITS[kind]
        now = time.time()
        with self._lock:
            if len(self._b) > 20_000:
                self._b.clear()
            tokens, ts = self._b.get((ip, kind), (cap, now))
            tokens = min(cap, tokens + (now - ts) * cap / per)
            if tokens < 1:
                self._b[(ip, kind)] = (tokens, now)
                return False
            self._b[(ip, kind)] = (tokens - 1, now)
            return True


class ApiError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code, self.message = code, message


# ------------------------------------------------------------------ état global

CFG: Config
SESSIONS = Sessions()
LIMITER = RateLimiter()
LIVE = {"chain": None, "lock": threading.Lock()}
SLOTS = threading.BoundedSemaphore(64)


def live_chain():
    """Le vrai coffre (CHAIN=web3) ou, en simulation, un coffre partagé par les admins."""
    with LIVE["lock"]:
        if LIVE["chain"] is None:
            LIVE["chain"] = make_chain("full")
        return LIVE["chain"]


def csv_cell(v) -> str:
    """Neutralise l'injection de formule dans Excel/LibreOffice (CWE-1236)."""
    s = "" if v is None else str(v)
    return "'" + s if s.startswith(CSV_DANGEROUS) else s


def audit_report(state: dict) -> dict:
    events = state.get("events", [])
    body = {"generated_at": int(time.time()), "network": state.get("network"), "vault": state.get("vault"),
            "policy": {k: state.get(k) for k in ("max_per_tx", "daily_limit", "threshold", "recipient_delay",
                                                  "max_blocked_per_day")},
            "events": events}
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return {"report": body, "sha256": hashlib.sha256(canonical.encode()).hexdigest()}


# ------------------------------------------------------------------ HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "VaultGuard"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = 15  # anti slowloris

    # ---- utilitaires
    def _ip(self) -> str:
        if CFG.trust_proxy:
            xff = self.headers.get("X-Forwarded-For", "")
            if xff:
                return xff.split(",")[-1].strip()
        return self.client_address[0]

    def _security_headers(self, nonce: str | None = None):
        csp = ("default-src 'none'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
               "form-action 'self'; frame-ancestors 'none'")
        if nonce:
            csp += f"; script-src 'nonce-{nonce}' 'self'; style-src 'nonce-{nonce}' 'self'"
        else:
            csp += "; script-src 'self'; style-src 'self'"
        self.send_header("Content-Security-Policy", csp)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        if CFG.cookie_secure:
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None, nonce: str | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers(nonce)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        if code >= 400:  # corps éventuellement non lu : on ferme pour ne pas désynchroniser la connexion
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, code=200, extra=None):
        self._send(code, json.dumps(data, ensure_ascii=False, default=str).encode(),
                   "application/json; charset=utf-8", extra)

    def _cookie_sid(self) -> str | None:
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "vg_sid":
                return v
        return None

    def _set_cookie(self, sid: str, max_age: int = SESSION_TTL) -> dict:
        flags = f"vg_sid={sid}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"
        if CFG.cookie_secure:
            flags += "; Secure"
        return {"Set-Cookie": flags}

    def _check_host(self):
        host = (self.headers.get("Host") or "").lower()
        name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        if name not in CFG.allowed_hosts:
            raise ApiError(421, "Hôte non autorisé")

    def _check_origin(self):
        origin = self.headers.get("Origin")
        if origin is None:
            return
        name = origin.split("://", 1)[-1].split("/")[0].rsplit(":", 1)[0].lower()
        if name not in CFG.allowed_hosts:
            raise ApiError(403, "Origine refusée")

    def _body(self) -> dict:
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            raise ApiError(415, "Content-Type application/json requis")
        raw_len = self.headers.get("Content-Length")
        try:
            n = int(raw_len)
        except (TypeError, ValueError):
            raise ApiError(411, "Content-Length requis") from None
        if n < 0 or n > MAX_BODY:
            raise ApiError(413, "Requête trop volumineuse")
        try:
            data = json.loads(self.rfile.read(n) or b"{}", parse_constant=lambda c: None)
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "JSON invalide") from None
        if not isinstance(data, dict):
            raise ApiError(400, "Objet JSON attendu")
        return data

    def _session(self, create: bool = False) -> tuple[str | None, dict | None, dict]:
        sid = self._cookie_sid()
        s = SESSIONS.get(sid)
        extra = {}
        if sid and (s is None or s.get("uid")):
            # Session de compte : la base fait foi à chaque requête. Une déconnexion globale, un changement de
            # mot de passe ou un compte désactivé coupent immédiatement aussi l'état gardé en mémoire.
            from auth import get_user_from_token
            auth_info = get_user_from_token(sid)
            if auth_info:
                s = s or _bind_account_session(sid, auth_info[0])
            elif s is not None:
                SESSIONS.drop(sid)
                s = None
        if s is None and create:
            sid, s = SESSIONS.create()
            extra = self._set_cookie(sid)
        if s is not None and CFG.local_admin and _is_loopback(self._ip()):
            s["admin"] = True
        return sid, s, extra

    def _require_csrf(self, s: dict | None):
        if s is None:
            raise ApiError(401, "Session expirée : rechargez la page")
        token = self.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(token, s["csrf"]):
            raise ApiError(403, "Jeton CSRF invalide")

    def _rate(self, kind: str):
        if not LIMITER.allow(self._ip(), kind):
            raise ApiError(429, "Trop de requêtes, patientez un instant")

    def _handle(self, fn):
        if not SLOTS.acquire(blocking=False):
            return self._json({"error": "Serveur occupé"}, 503)
        t0, rid = time.time(), uuid.uuid4().hex[:8]
        code = 200
        try:
            self._check_host()
            fn()
        except ApiError as e:
            code = e.code
            self._json({"error": e.message}, e.code)
        except ChainError as e:
            code = 409
            self._json({"error": str(e)}, 409)
        except OrgError as e:
            code = e.code
            self._json({"error": e.message}, e.code)
        except Exception:  # noqa: BLE001 — jamais de trace interne envoyée au client
            code = 500
            log.exception("erreur interne rid=%s", rid)
            self._json({"error": f"Erreur interne (réf. {rid})"}, 500)
        finally:
            SLOTS.release()
            log.info(json.dumps({"rid": rid, "ip": self._ip(), "m": self.command, "path": self.path[:100],
                                 "code": code, "ms": int((time.time() - t0) * 1000)}))

    # ---- routes
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self._handle(self._get)

    def do_POST(self):
        self._handle(self._post)

    def _method_not_allowed(self):
        self._handle(lambda: (_ for _ in ()).throw(ApiError(405, "Méthode non autorisée")))

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = do_CONNECT = _method_not_allowed

    def _app_context(self, min_role: str = "viewer") -> tuple[dict, dict, dict]:
        sid = self._cookie_sid()
        from auth import get_user_from_token
        auth_info = get_user_from_token(sid)
        if not auth_info:
            raise ApiError(401, "Non authentifié : veuillez vous connecter")
        user, org, sess = auth_info
        if not org:
            raise ApiError(404, "Aucune organisation active")
        membership = require_role(user["id"], org["id"], min_role)
        return user, org, membership

    def _get(self):
        self._rate("get")
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            nonce = secrets.token_urlsafe(16)
            sid, s, extra = self._session(create=True)
            html = (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8").replace("__NONCE__", nonce)
            return self._send(200, html.encode(), "text/html; charset=utf-8", extra, nonce=nonce)
        if path in ("/login", "/login.html"):
            nonce = secrets.token_urlsafe(16)
            sid, s, extra = self._session(create=True)
            html = (DASHBOARD_DIR / "login.html").read_text(encoding="utf-8").replace("__NONCE__", nonce)
            return self._send(200, html.encode(), "text/html; charset=utf-8", extra, nonce=nonce)
        if path in ("/signup", "/signup.html"):
            nonce = secrets.token_urlsafe(16)
            sid, s, extra = self._session(create=True)
            html = (DASHBOARD_DIR / "signup.html").read_text(encoding="utf-8").replace("__NONCE__", nonce)
            return self._send(200, html.encode(), "text/html; charset=utf-8", extra, nonce=nonce)
        if path in ("/app", "/app.html"):
            nonce = secrets.token_urlsafe(16)
            sid, s, extra = self._session(create=True)
            html = (DASHBOARD_DIR / "app.html").read_text(encoding="utf-8").replace("__NONCE__", nonce)
            return self._send(200, html.encode(), "text/html; charset=utf-8", extra, nonce=nonce)
        if path in ("/app.css", "/dashboard/app.css"):
            css = (DASHBOARD_DIR / "app.css").read_bytes()
            return self._send(200, css, "text/css; charset=utf-8")
        if path in ("/app.js", "/dashboard/app.js"):
            js = (DASHBOARD_DIR / "app.js").read_bytes()
            return self._send(200, js, "application/javascript; charset=utf-8")
        if path == "/healthz":
            return self._json({"ok": True})
        if path == "/api/session":
            sid, s, extra = self._session(create=True)
            return self._json({"csrf": s["csrf"], "admin": s["admin"], "local_admin": CFG.local_admin,
                               "login_enabled": bool(CFG.password_hash), "backend": CFG.backend,
                               "llm": CFG.llm}, extra=extra)
        if path == "/api/scenarios":
            return self._json({"scenarios": [{"name": k, "title": v["title"], "attack": v["attack"],
                                              "story": v["story"]} for k, v in SCENARIOS.items()],
                               "modes": [{"id": m, "label": MODE_LABELS[m]} for m in MODES],
                               "addresses": addresses(), "catalog": CATALOG})
        if path == "/api/auth/me":
            sid = self._cookie_sid()
            from auth import get_user_from_token
            res = get_user_from_token(sid)
            if not res:
                raise ApiError(401, "Non authentifié")
            user, org, _ = res
            _, s, _ = self._session(create=False)
            csrf_token = s["csrf"] if s else ""
            return self._json({
                "authenticated": True,
                "user": {
                    "id": user["id"],
                    "email": user["email"],
                    "is_superadmin": bool(user["is_superadmin"]),
                    "totp_enabled": bool(user["totp_enabled"]),
                },
                "org": {
                    "id": org["id"],
                    "name": org["name"],
                    "slug": org.get("slug"),
                } if org else None,
                "csrf": csrf_token,
            })
        if path.startswith("/api/app/"):
            import orgs
            if path == "/api/app/overview":
                user, org, _ = self._app_context("viewer")
                return self._json(orgs.get_overview(org["id"]))
            if path == "/api/app/payments":
                user, org, _ = self._app_context("viewer")
                q = self.path.split("?", 1)[1] if "?" in self.path else ""
                status_filter = None
                for part in q.split("&"):
                    if part.startswith("status="):
                        status_filter = part.split("=", 1)[1]
                return self._json(orgs.list_payments(org["id"], status=status_filter))
            if path.startswith("/api/app/payments/"):
                sub = path[len("/api/app/payments/"):].strip()
                if sub and sub not in ("approve", "reject"):
                    user, org, _ = self._app_context("viewer")
                    return self._json(orgs.get_payment(org["id"], sub))
            if path == "/api/app/suppliers":
                user, org, _ = self._app_context("viewer")
                return self._json(orgs.list_suppliers(org["id"]))
            if path == "/api/app/policy":
                user, org, _ = self._app_context("viewer")
                return self._json(orgs.get_policy(org["id"]))
            if path == "/api/app/audit":
                user, org, _ = self._app_context("viewer")
                return self._json(orgs.get_audit_trail(org["id"]))
            if path == "/api/app/audit.csv":
                user, org, _ = self._app_context("viewer")
                csv_str = orgs.export_audit_csv(org["id"])
                return self._send(200, csv_str.encode("utf-8-sig"), "text/csv; charset=utf-8",
                                  {"Content-Disposition": 'attachment; filename="vaultguard-audit-org.csv"'})
            if path == "/api/app/team/members":
                user, org, _ = self._app_context("viewer")
                return self._json(orgs.list_members(org["id"]))
            if path == "/api/app/team/invites":
                user, org, _ = self._app_context("admin")
                return self._json(orgs.list_invites(org["id"]))
            if path == "/api/app/api-keys":
                user, org, _ = self._app_context("viewer")
                return self._json(orgs.list_api_keys(org["id"]))
            if path == "/api/app/orgs":
                sid = self._cookie_sid()
                from auth import get_user_from_token
                auth_info = get_user_from_token(sid)
                if not auth_info:
                    raise ApiError(401, "Non authentifié")
                user, org, _ = auth_info
                if org:
                    require_role(user["id"], org["id"], "viewer")
                return self._json(orgs.list_user_orgs(user["id"], active_org_id=org["id"] if org else None))
            if path == "/api/app/settings":
                user, org, _ = self._app_context("viewer")
                return self._json(orgs.get_settings(org["id"]))
            raise ApiError(404, "Introuvable")
        _, s, _ = self._session()
        if path == "/api/state":
            target = self._target_from_query(s)
            return self._json(self._chain_for(s, target).state())
        if path in ("/api/audit.csv", "/api/audit.json"):
            target = self._target_from_query(s)
            state = self._chain_for(s, target).state()
            if path.endswith(".json"):
                return self._json(audit_report(state), extra={"Content-Disposition": 'attachment; filename="vaultguard-audit.json"'})
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["event", "block_or_time", "to", "amount", "reason", "memo", "tx"])
            for e in state.get("events", []):
                w.writerow([csv_cell(e.get(k)) for k in ("event", "block", "to", "amount", "reason", "memo", "tx")]
                           if "block" in e else
                           [csv_cell(e.get(k)) for k in ("event", "ts", "to", "amount", "reason", "memo", "tx")])
            return self._send(200, buf.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8",
                              {"Content-Disposition": 'attachment; filename="vaultguard-audit.csv"'})
        raise ApiError(404, "Introuvable")

    def _target_from_query(self, s: dict | None) -> str:
        q = self.path.split("?", 1)[1] if "?" in self.path else ""
        return "live" if "target=live" in q.split("&") else "sandbox"

    def _chain_for(self, s: dict | None, target: str):
        if target == "live":
            if not (s and s["admin"]):
                raise ApiError(403, "Réservé à l'administrateur")
            return live_chain()
        if s is None:
            raise ApiError(401, "Session expirée : rechargez la page")
        if s["chain"] is None:
            s["chain"] = make_chain(s["mode"], force_mock=True)
        return s["chain"]

    def _post(self):
        self._rate("post")
        self._check_origin()
        path = self.path.split("?", 1)[0]
        sid, s, _ = self._session()

        # ---- Routes d'authentification v3
        if path == "/api/auth/signup":
            self._require_csrf(s)
            b = self._body()
            email = b.get("email")
            password = b.get("password")
            org_name = b.get("org_name")
            invite_token = b.get("invite_token") or b.get("token")
            if not isinstance(email, str) or not isinstance(password, str):
                raise ApiError(400, "Email et mot de passe requis")
            from auth import AuthError, signup as auth_signup
            try:
                res = auth_signup(email, password, org_name=org_name, invite_token=invite_token,
                                  ip=self._ip(), user_agent=self.headers.get("User-Agent"))
            except AuthError as e:
                raise ApiError(e.code, e.message)
            if sid:
                SESSIONS.drop(sid)
            new_token = res["token"]
            from auth import get_user_from_token
            ns = _bind_account_session(new_token, get_user_from_token(new_token)[0])
            return self._json({
                "ok": True,
                "user": res["user"],
                "org": res["org"],
                "csrf": ns["csrf"],
            }, code=201, extra=self._set_cookie(new_token))

        if path == "/api/auth/login":
            self._rate("login")
            self._require_csrf(s)
            b = self._body()
            email = b.get("email")
            password = b.get("password")
            totp_code = b.get("totp_code") or b.get("code")
            if not isinstance(email, str) or not isinstance(password, str):
                raise ApiError(400, "Email et mot de passe requis")
            from auth import AuthError, login as auth_login
            try:
                res = auth_login(email, password, totp_code=totp_code,
                                 ip=self._ip(), user_agent=self.headers.get("User-Agent"))
            except AuthError as e:
                raise ApiError(e.code, e.message)
            if res.get("totp_required"):
                return self._json({"ok": False, "totp_required": True, "email": res["email"]})
            if sid:
                SESSIONS.drop(sid)
            new_token = res["token"]
            from auth import get_user_from_token
            ns = _bind_account_session(new_token, get_user_from_token(new_token)[0])
            return self._json({
                "ok": True,
                "user": res["user"],
                "org_id": res.get("org_id"),
                "csrf": ns["csrf"],
            }, extra=self._set_cookie(new_token))

        if path == "/api/auth/logout":
            self._require_csrf(s)
            from auth import delete_session as auth_delete_session
            if sid:
                auth_delete_session(sid, ip=self._ip())
                SESSIONS.drop(sid)
            return self._json({"ok": True}, extra=self._set_cookie("", 0))

        if path == "/api/auth/logout-all":
            self._require_csrf(s)
            from auth import get_user_from_token, delete_all_sessions as auth_delete_all_sessions
            auth_info = get_user_from_token(sid)
            if not auth_info:
                raise ApiError(401, "Non authentifié")
            user, _, _ = auth_info
            auth_delete_all_sessions(user["id"], ip=self._ip())
            if sid:
                SESSIONS.drop(sid)
            return self._json({"ok": True}, extra=self._set_cookie("", 0))

        if path == "/api/auth/2fa/setup":
            self._require_csrf(s)
            from auth import get_user_from_token, setup_2fa as auth_setup_2fa, AuthError
            auth_info = get_user_from_token(sid)
            if not auth_info:
                raise ApiError(401, "Non authentifié")
            user, _, _ = auth_info
            try:
                res = auth_setup_2fa(user["id"], ip=self._ip())
            except AuthError as e:
                raise ApiError(e.code, e.message)
            return self._json(res)

        if path == "/api/auth/2fa/enable":
            self._require_csrf(s)
            b = self._body()
            code = b.get("code") or b.get("totp_code")
            if not isinstance(code, str) or not code.strip():
                raise ApiError(400, "Code TOTP requis")
            from auth import get_user_from_token, enable_2fa as auth_enable_2fa, AuthError
            auth_info = get_user_from_token(sid)
            if not auth_info:
                raise ApiError(401, "Non authentifié")
            user, _, _ = auth_info
            try:
                res = auth_enable_2fa(user["id"], code.strip(), ip=self._ip())
            except AuthError as e:
                raise ApiError(e.code, e.message)
            return self._json(res)

        if path == "/api/auth/invite/accept":
            self._require_csrf(s)
            b = self._body()
            token = b.get("token") or b.get("invite_token")
            password = b.get("password")
            if not isinstance(token, str) or not token.strip():
                raise ApiError(400, "Jeton d'invitation requis")
            from auth import get_user_from_token, accept_invite as auth_accept_invite, AuthError
            auth_info = get_user_from_token(sid)
            user_id = auth_info[0]["id"] if auth_info else None
            try:
                res = auth_accept_invite(token.strip(), password=password, user_id=user_id,
                                         ip=self._ip(), user_agent=self.headers.get("User-Agent"))
            except AuthError as e:
                raise ApiError(e.code, e.message)
            if sid:
                SESSIONS.drop(sid)
            new_token = res["token"]
            from auth import get_user_from_token
            ns = _bind_account_session(new_token, get_user_from_token(new_token)[0])
            return self._json({
                "ok": True,
                "user_id": res["user_id"],
                "org_id": res["org_id"],
                "role": res["role"],
                "csrf": ns["csrf"],
            }, extra=self._set_cookie(new_token))

        if path in ("/api/auth/password", "/api/auth/change-password"):
            self._require_csrf(s)
            b = self._body()
            old_password = b.get("old_password")
            new_password = b.get("new_password")
            if not isinstance(old_password, str) or not isinstance(new_password, str):
                raise ApiError(400, "Ancien et nouveau mot de passe requis")
            from auth import get_user_from_token, change_password as auth_change_password, AuthError
            auth_info = get_user_from_token(sid)
            if not auth_info:
                raise ApiError(401, "Non authentifié")
            user, _, _ = auth_info
            try:
                res = auth_change_password(user["id"], old_password, new_password,
                                           current_token=sid, ip=self._ip())
            except AuthError as e:
                raise ApiError(e.code, e.message)
            return self._json(res)

        if path == "/api/login":
            self._rate("login")
            self._require_csrf(s)
            b = self._body()
            pw = b.get("password")
            if not CFG.password_hash or not isinstance(pw, str) or len(pw) > 200:
                raise ApiError(401, "Identifiants invalides")
            if not verify_password(pw, CFG.password_hash):
                log.warning(json.dumps({"event": "login_failed", "ip": self._ip()}))
                raise ApiError(401, "Identifiants invalides")
            SESSIONS.drop(sid)  # nouvelle session après connexion (anti fixation de session)
            new_sid, ns = SESSIONS.create()
            ns["admin"] = True
            return self._json({"ok": True, "csrf": ns["csrf"]}, extra=self._set_cookie(new_sid))

        self._require_csrf(s)
        b = self._body()

        if path == "/api/logout":
            SESSIONS.drop(sid)
            return self._json({"ok": True}, extra=self._set_cookie("", 0))

        if path.startswith("/api/app/"):
            import orgs
            if path == "/api/app/payments/approve":
                user, org, _ = self._app_context("approver")
                pid = b.get("id") or b.get("payment_id")
                if not isinstance(pid, str) or not pid:
                    raise ApiError(400, "Identifiant de paiement requis")
                return self._json(orgs.approve_payment(org["id"], user["id"], pid, ip=self._ip()))
            if path == "/api/app/payments/reject":
                user, org, _ = self._app_context("approver")
                pid = b.get("id") or b.get("payment_id")
                if not isinstance(pid, str) or not pid:
                    raise ApiError(400, "Identifiant de paiement requis")
                return self._json(orgs.reject_payment(org["id"], user["id"], pid, ip=self._ip()))
            if path == "/api/app/suppliers":
                user, org, _ = self._app_context("admin")
                name = b.get("name")
                address = b.get("address")
                if not isinstance(name, str) or not isinstance(address, str):
                    raise ApiError(400, "Nom et adresse requis")
                return self._json(orgs.add_supplier(org["id"], user["id"], name, address, ip=self._ip()), code=201)
            if path in ("/api/app/suppliers/remove", "/api/app/suppliers/delete"):
                user, org, _ = self._app_context("admin")
                sid_sup = b.get("id") or b.get("supplier_id")
                if not isinstance(sid_sup, str) or not sid_sup:
                    raise ApiError(400, "Identifiant de fournisseur requis")
                return self._json(orgs.remove_supplier(org["id"], user["id"], sid_sup, ip=self._ip()))
            if path == "/api/app/policy":
                user, org, _ = self._app_context("admin")
                return self._json(orgs.update_policy(
                    org["id"], user["id"],
                    max_tx_gwei=b.get("max_tx_gwei"),
                    max_daily_gwei=b.get("max_daily_gwei"),
                    human_threshold_gwei=b.get("human_threshold_gwei"),
                    activation_delay=b.get("activation_delay"),
                    circuit_breaker_limit=b.get("circuit_breaker_limit"),
                    ip=self._ip()
                ))
            if path == "/api/app/audit/verify":
                user, org, _ = self._app_context("viewer")
                return self._json(orgs.verify_audit_chain_for_org(org["id"]))
            if path == "/api/app/audit/anchor":
                user, org, _ = self._app_context("admin")
                chain = self._chain_for(s, "live" if org.get("network") != "mock" else "sandbox")
                # On scelle l'empreinte du journal de l'organisation (et non l'état de la démo).
                digest = hashlib.sha256(orgs.export_audit_csv(org["id"]).encode("utf-8")).hexdigest()
                r = chain.anchor_report(digest, f"vaultguard-audit-{org['id']}")
                from auth import log_audit
                log_audit("audit.anchor", org_id=org["id"], user_id=user["id"],
                          details={"sha256": digest}, ip=self._ip())
                return self._json({"sha256": digest, **vars(r)})
            if path == "/api/app/team/members/role":
                user, org, _ = self._app_context("admin")
                mid = b.get("member_id") or b.get("id")
                role = b.get("role")
                if not isinstance(mid, str) or not isinstance(role, str):
                    raise ApiError(400, "member_id et rôle requis")
                return self._json(orgs.change_member_role(org["id"], user["id"], mid, role, ip=self._ip()))
            if path in ("/api/app/team/members/remove", "/api/app/team/members/delete"):
                user, org, _ = self._app_context("admin")
                mid = b.get("member_id") or b.get("id")
                if not isinstance(mid, str) or not mid:
                    raise ApiError(400, "member_id requis")
                return self._json(orgs.remove_member(org["id"], user["id"], mid, ip=self._ip()))
            if path == "/api/app/team/invites":
                user, org, _ = self._app_context("admin")
                email = b.get("email")
                role = b.get("role")
                if not isinstance(email, str) or not isinstance(role, str):
                    raise ApiError(400, "Email et rôle requis")
                return self._json(orgs.invite_member(org["id"], user["id"], email, role, ip=self._ip()), code=201)
            if path == "/api/app/team/invites/revoke":
                user, org, _ = self._app_context("admin")
                iid = b.get("invite_id") or b.get("id")
                if not isinstance(iid, str) or not iid:
                    raise ApiError(400, "invite_id requis")
                return self._json(orgs.revoke_invite(org["id"], user["id"], iid, ip=self._ip()))
            if path == "/api/app/api-keys":
                user, org, _ = self._app_context("admin")
                name = b.get("name")
                if not isinstance(name, str):
                    raise ApiError(400, "Nom de clé requis")
                return self._json(orgs.create_api_key(org["id"], user["id"], name, ip=self._ip()), code=201)
            if path == "/api/app/api-keys/revoke":
                user, org, _ = self._app_context("admin")
                kid = b.get("id") or b.get("key_id")
                if not isinstance(kid, str) or not kid:
                    raise ApiError(400, "Identifiant de clé requis")
                return self._json(orgs.revoke_api_key(org["id"], user["id"], kid, ip=self._ip()))
            if path == "/api/app/orgs/switch":
                sid = self._cookie_sid()
                from auth import get_user_from_token
                auth_info = get_user_from_token(sid)
                if not auth_info:
                    raise ApiError(401, "Non authentifié")
                user, curr_org, sess = auth_info
                target_org_id = b.get("org_id")
                if not isinstance(target_org_id, str) or not target_org_id:
                    raise ApiError(400, "org_id requis")
                require_role(user["id"], target_org_id, "viewer")
                return self._json(orgs.switch_org(user["id"], target_org_id, sess["id"], ip=self._ip()))
            if path == "/api/app/settings":
                user, org, _ = self._app_context("admin")
                return self._json(orgs.update_settings(
                    org["id"], user["id"],
                    name=b.get("name"),
                    network=b.get("network"),
                    vault_address=b.get("vault_address"),
                    canary_address=b.get("canary_address"),
                    ip=self._ip()
                ))
            raise ApiError(404, "Introuvable")

        target = b.get("target", "sandbox")
        if target not in ("sandbox", "live"):
            raise ApiError(400, "Cible invalide")
        if target == "live" and not s["admin"]:
            raise ApiError(403, "Réservé à l'administrateur")

        if path in ("/api/run", "/api/compare", "/api/playground"):
            self._rate("run")
            mode = b.get("mode", "full")
            if mode not in MODES:
                raise ApiError(400, "Mode invalide")
            llm = b.get("llm") is True
            if llm:
                if not (CFG.llm and s["admin"]):
                    raise ApiError(403, "LLM réel réservé à l'administrateur")
                self._rate("llm")
            if path == "/api/compare":
                name = b.get("scenario")
                if name not in SCENARIOS:
                    raise ApiError(400, "Scénario invalide")
                out = {}
                for m in MODES:
                    r = run(name, m, chain=make_chain(m, force_mock=True))
                    out[m] = {**r["summary"], "paused": r["state"]["paused"]}
                return self._json(out)
            with s["lock"]:
                if target == "live":
                    chain = live_chain()
                else:
                    s["mode"] = mode
                    chain = s["chain"] = make_chain(mode, force_mock=True)
                if path == "/api/run":
                    name = b.get("scenario")
                    if name not in SCENARIOS:
                        raise ApiError(400, "Scénario invalide")
                    return self._json(run(name, mode, llm=llm, chain=chain))
                user, inbox = b.get("user"), b.get("inbox")
                if not isinstance(user, str) or not isinstance(inbox, str) or not inbox.strip():
                    raise ApiError(400, "Texte de facture requis")
                if len(user) > 500 or len(inbox) > 4000:
                    raise ApiError(413, "Texte trop long (4000 caractères max)")
                res = run_custom({"user": user, "inbox": [inbox]}, mode, llm=llm, chain=chain)
                res["detected"] = scan_injection(inbox)
                return self._json(res)

        chain = self._chain_for(s, target)
        if path in ("/api/approve", "/api/reject"):
            pid = b.get("id")
            if not isinstance(pid, int) or isinstance(pid, bool) or not 0 <= pid < 2**63:
                raise ApiError(400, "Identifiant invalide")
            r = chain.approve(pid) if path.endswith("approve") else chain.reject(pid)
            return self._json(vars(r))
        if path == "/api/pause":
            paused = b.get("paused")
            if not isinstance(paused, bool):
                raise ApiError(400, "Valeur invalide")
            chain.set_paused(paused)
            return self._json(chain.state())
        if path == "/api/reset":
            if target == "live":
                raise ApiError(400, "Le vrai coffre ne se réinitialise pas")
            s["chain"] = make_chain(s["mode"], force_mock=True)
            return self._json(s["chain"].state())
        if path == "/api/anchor":
            rep = audit_report(chain.state())
            r = chain.anchor_report(rep["sha256"], "vaultguard-audit")
            return self._json({"sha256": rep["sha256"], **vars(r)})
        raise ApiError(404, "Introuvable")

    def log_message(self, *_):
        pass  # journal structuré dans _handle (sans corps de requête ni secrets)


def main():
    global CFG
    ap = argparse.ArgumentParser()
    ap.add_argument("--hash-password", action="store_true", help="générer ADMIN_PASSWORD_HASH")
    ap.add_argument("--create-admin", action="store_true", help="créer le super-administrateur de la plateforme")
    args = ap.parse_args()
    if args.hash_password:
        pw = getpass.getpass("Mot de passe admin (12 caractères min.) : ")
        if len(pw) < 12:
            sys.exit("Trop court.")
        print("ADMIN_PASSWORD_HASH=" + hash_password(pw))
        return
    if args.create_admin:
        email = input("Email du super-administrateur : ").strip()
        if not email or "@" not in email:
            sys.exit("Email invalide.")
        pw = getpass.getpass("Mot de passe admin (12 caractères min.) : ")
        if len(pw) < 12:
            sys.exit("Trop court (12 caractères min.).")
        pw_confirm = getpass.getpass("Confirmez le mot de passe : ")
        if pw != pw_confirm:
            sys.exit("Les mots de passe ne correspondent pas.")
        from auth import AuthError, create_superadmin
        try:
            admin_info = create_superadmin(email, pw)
            print(f"Super-administrateur créé : {admin_info['email']} (id={admin_info['id']})")
        except AuthError as e:
            sys.exit(f"Erreur : {e.message}")
        return
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    CFG = Config()
    if not _is_loopback(CFG.host) and not CFG.password_hash:
        log.warning("Exposé sur le réseau SANS ADMIN_PASSWORD_HASH : actions admin désactivées.")
    import db
    db.init_db()
    srv = ThreadingHTTPServer((CFG.host, CFG.port), Handler)
    srv.daemon_threads = True
    print(f"VaultGuard -> http://localhost:{CFG.port}  (backend={CFG.backend}, écoute {CFG.host}, "
          f"admin={'local' if CFG.local_admin else ('mot de passe' if CFG.password_hash else 'désactivé')})")
    srv.serve_forever()


CFG = Config()

if __name__ == "__main__":
    main()
