from __future__ import annotations

import json
import socket
import urllib.request
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


def nested_get(data: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def common_config_paths() -> list[Path]:
    paths: list[Path] = []
    for drive in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        root = Path(f"{drive}:/")
        if not root.exists():
            continue
        paths.extend(
            [
                root / "Program Files/ONLYOFFICE/DocumentServer/config/local.json",
                root / "Program Files (x86)/ONLYOFFICE/DocumentServer/config/local.json",
            ]
        )
    paths.extend(
        [
            Path("/etc/onlyoffice/documentserver/local.json"),
            Path("/var/www/onlyoffice/documentserver/server/Common/config/local.json"),
            Path("/var/lib/onlyoffice/documentserver/App_Data/config/local.json"),
        ]
    )
    seen = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def detect_lan_ip() -> str:
    candidates: list[str] = []
    try:
        host = socket.gethostname()
        candidates.extend(socket.gethostbyname_ex(host)[2])
    except OSError:
        pass
    for ip in candidates:
        if ip.startswith(("10.", "172.", "192.168.")):
            return ip
    return "127.0.0.1"


def read_env(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def upsert_env(lines: list[str], key: str, value: str) -> list[str]:
    prefix = f"{key}="
    replaced = False
    output: list[str] = []
    for line in lines:
        if line.startswith(prefix):
            output.append(f"{key}={value}")
            replaced = True
        else:
            output.append(line)
    if not replaced:
        if output and output[-1].strip():
            output.append("")
        output.append(f"{key}={value}")
    return output


class Command(BaseCommand):
    help = "Detect ONLYOFFICE Document Server settings and optionally sync them into .env."

    def add_arguments(self, parser):
        parser.add_argument("--config", default="", help="Path to ONLYOFFICE DocumentServer config/local.json.")
        parser.add_argument("--server-url", default="", help="Document Server URL visible to browser clients.")
        parser.add_argument("--env-file", default=str(settings.BASE_DIR / ".env"), help="Target .env path.")
        parser.add_argument("--write-env", action="store_true", help="Write detected values into .env.")
        parser.add_argument("--no-url-check", action="store_true", help="Skip api.js reachability check.")

    def handle(self, *args, **options):
        config_path = self._find_config(options["config"])
        config = self._load_config(config_path)
        token_enabled = bool(nested_get(config, "services.CoAuthoring.token.enable.browser", False))
        jwt_secret = self._detect_secret(config)
        server_url = self._detect_server_url(options["server_url"])
        api_status = self._check_api(server_url, skip=options["no_url_check"])

        self.stdout.write(f"ONLYOFFICE config: {config_path}")
        self.stdout.write(f"Document Server URL: {server_url}")
        self.stdout.write(f"Browser JWT enabled: {'yes' if token_enabled else 'no'}")
        self.stdout.write(f"JWT secret detected: {'yes' if jwt_secret else 'no'}")
        if api_status is None:
            self.stdout.write("api.js reachable: skipped")
        else:
            self.stdout.write(f"api.js reachable: {'yes' if api_status else 'no'}")

        if token_enabled and not jwt_secret:
            raise CommandError("ONLYOFFICE enabled browser JWT, but no JWT secret was found in local.json.")

        if options["write_env"]:
            env_path = Path(options["env_file"]).resolve()
            lines = read_env(env_path)
            lines = upsert_env(lines, "ONLYOFFICE_DOCUMENT_SERVER_URL", server_url.rstrip("/"))
            lines = upsert_env(lines, "ONLYOFFICE_JWT_SECRET", jwt_secret if token_enabled else "")
            env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Updated {env_path}"))
            if token_enabled:
                self.stdout.write("JWT secret was written but not printed.")

    def _find_config(self, configured: str) -> Path:
        if configured:
            path = Path(configured).expanduser().resolve()
            if not path.exists():
                raise CommandError(f"ONLYOFFICE config not found: {path}")
            return path
        for path in common_config_paths():
            if path.exists():
                return path.resolve()
        raise CommandError("ONLYOFFICE config/local.json was not found. Use --config to specify it.")

    def _load_config(self, path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"Unable to read ONLYOFFICE config: {exc}") from exc

    def _detect_secret(self, config: dict[str, Any]) -> str:
        for path in (
            "services.CoAuthoring.secret.browser.string",
            "services.CoAuthoring.secret.inbox.string",
            "services.CoAuthoring.secret.session.string",
        ):
            value = str(nested_get(config, path, "") or "").strip()
            if value:
                return value
        return ""

    def _detect_server_url(self, configured: str) -> str:
        value = configured.strip() or getattr(settings, "ONLYOFFICE_DOCUMENT_SERVER_URL", "").strip()
        if value:
            return value.rstrip("/")
        return f"http://{detect_lan_ip()}"

    def _check_api(self, server_url: str, *, skip: bool) -> bool | None:
        if skip:
            return None
        url = f"{server_url.rstrip('/')}/web-apps/apps/api/documents/api.js"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return 200 <= response.status < 400
        except Exception:
            return False
