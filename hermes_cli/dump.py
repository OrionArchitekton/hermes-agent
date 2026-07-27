"""
Dump command for hermes CLI.

Outputs a compact, plain-text summary of the user's Hermes setup
that can be copy-pasted into Discord/GitHub/Telegram for support context.
No ANSI colors, no checkmarks — just data.
"""

import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

from hermes_cli.config import get_hermes_home, get_env_path, get_project_root, load_config
from hermes_cli.env_loader import load_hermes_dotenv
from hermes_constants import display_hermes_home
from agent.skill_utils import is_excluded_skill_path


def _dotenv_key_names() -> set[str]:
    """Return the set of env-var names assigned a non-empty value in ~/.hermes/.env.

    The managed backends (launchd / systemd / the desktop-spawned ``serve``
    process) load credentials from this file — NOT from an interactive shell's
    exports. ``hermes debug share`` runs in a terminal, so ``os.getenv`` reflects
    the shell's environment, which can include exported keys the managed backend
    never sees. Comparing against this set lets the dump flag that mismatch (the
    exact trap behind #48504-style "no web_search" reports: key exported in the
    shell, absent from .env, invisible to the launchd backend).
    """
    try:
        env_path = get_env_path()
        text = env_path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeError):
        return set()

    names: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("export "):
            line = line[len("export "):].lstrip()
        name, _, value = line.partition("=")
        name = name.strip()
        # A bare `KEY=` (empty value) is effectively unset for the backend.
        if name and value.strip().strip("'\""):
            names.add(name)
    return names


def _get_git_commit(project_root: Path) -> str:
    """Return short git commit hash, or '(unknown)'.

    Source installs and dev images resolve this live via ``git rev-parse``.
    The published Docker image excludes ``.git`` from the build context, so
    that lookup always fails — we fall back to the baked-in build SHA written
    to ``<project_root>/.hermes_build_sha`` by the Dockerfile's
    ``HERMES_GIT_SHA`` build-arg (see ``hermes_cli/build_info.py``).
    The output format is identical regardless of source.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=8", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=str(project_root),
        )
        if result.returncode == 0:
            value = result.stdout.strip()
            if value:
                return value
    except Exception:
        pass

    # Fall back to the build-time baked SHA (populated in published Docker
    # images, absent otherwise).  Defers the import so the dump module
    # stays cheap on non-dump code paths.
    try:
        from hermes_cli.build_info import get_build_sha
        baked = get_build_sha(short=8)
        if baked:
            return baked
    except Exception:
        pass

    return "(unknown)"


def _get_git_commit_date(project_root: Path) -> str:
    """Return the date the HEAD commit was authored (YYYY-MM-DD), or ''.

    Resolves live via ``git log`` on source installs.  The published Docker
    image excludes ``.git``, so this returns '' there — the dump line simply
    drops the date suffix in that case (the baked SHA still identifies the
    build).
    """
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cd", "--date=short", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=str(project_root),
        )
        if result.returncode == 0:
            value = result.stdout.strip()
            if value:
                return value
    except Exception:
        pass

    return ""


def _redact(value: str) -> str:
    """Redact all but first 4 and last 4 chars.

    Thin wrapper over :func:`agent.redact.mask_secret`. Returns ``""`` for
    an empty value (matches the historical behavior of this helper —
    ``hermes dump`` formats empty values as blank, not as ``"(not set)"``).
    """
    from agent.redact import mask_secret
    return mask_secret(value)


def _gateway_status() -> str:
    """Return a short gateway status string."""
    try:
        from hermes_cli.gateway import get_gateway_runtime_snapshot

        snapshot = get_gateway_runtime_snapshot()
        if snapshot.running:
            mode = snapshot.manager
            if snapshot.has_process_service_mismatch:
                mode = "manual"
            return f"running ({mode}, pid {snapshot.gateway_pids[0]})"
        if snapshot.service_installed and not snapshot.service_running:
            return f"stopped ({snapshot.manager})"
        return f"stopped ({snapshot.manager})"
    except Exception:
        return "unknown" if sys.platform.startswith(("linux", "darwin")) else "N/A"


def _count_skills(hermes_home: Path) -> int:
    """Count installed skills."""
    skills_dir = hermes_home / "skills"
    if not skills_dir.is_dir():
        return 0
    count = 0
    for item in skills_dir.rglob("SKILL.md"):
        if is_excluded_skill_path(item):
            continue
        count += 1
    return count


def _count_mcp_servers(config: dict) -> int:
    """Count configured MCP servers."""
    mcp = config.get("mcp", {})
    servers = mcp.get("servers", {})
    return len(servers)


def _cron_summary(hermes_home: Path) -> str:
    """Return cron jobs summary."""
    jobs_file = hermes_home / "cron" / "jobs.json"
    if not jobs_file.exists():
        return "0"
    try:
        # utf-8-sig: same dialect as cron/jobs.load_jobs — Windows editors
        # may leave a UTF-8 BOM that plain utf-8 json.load rejects.
        with open(jobs_file, encoding="utf-8-sig") as f:
            data = json.load(f)
        jobs = data.get("jobs", [])
        active = sum(1 for j in jobs if j.get("enabled", True))
        return f"{active} active / {len(jobs)} total"
    except Exception:
        return "(error reading)"


def _configured_platforms() -> list[str]:
    """Return list of configured messaging platform names."""
    checks = {
        "telegram": "TELEGRAM_BOT_TOKEN",
        "discord": "DISCORD_BOT_TOKEN",
        "slack": "SLACK_BOT_TOKEN",
        "whatsapp": "WHATSAPP_ENABLED",
        "signal": "SIGNAL_HTTP_URL",
        "email": "EMAIL_ADDRESS",
        "sms": "TWILIO_ACCOUNT_SID",
        "matrix": "MATRIX_HOMESERVER_URL",
        "mattermost": "MATTERMOST_URL",
        "homeassistant": "HASS_TOKEN",
        "dingtalk": "DINGTALK_CLIENT_ID",
        "feishu": "FEISHU_APP_ID",
        "wecom": "WECOM_BOT_ID",
        "wecom_callback": "WECOM_CALLBACK_CORP_ID",
        "weixin": "WEIXIN_ACCOUNT_ID",
        "qqbot": "QQ_APP_ID",
    }
    return [name for name, env in checks.items() if os.getenv(env)]


def _memory_provider(config: dict) -> str:
    """Return the active memory provider name."""
    mem = config.get("memory", {})
    provider = mem.get("provider", "")
    return provider if provider else "built-in"


def _get_model_and_provider(config: dict) -> tuple[str, str]:
    """Extract model and provider from config."""
    model_cfg = config.get("model", "")
    if isinstance(model_cfg, dict):
        model = model_cfg.get("default") or model_cfg.get("model") or model_cfg.get("name") or "(not set)"
        provider = model_cfg.get("provider") or "(auto)"
    elif isinstance(model_cfg, str):
        model = model_cfg or "(not set)"
        provider = "(auto)"
    else:
        model = "(not set)"
        provider = "(auto)"
    return model, provider


_FALLBACK_DIAGNOSTIC_FIELDS = (
    "provider",
    "model",
    "base_url",
    "api_mode",
    "transport",
    "key_env",
    "api_key_env",
    "api_key",
)
_FALLBACK_DIAGNOSTIC_FIELD_SET = frozenset(_FALLBACK_DIAGNOSTIC_FIELDS)
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}\Z")
_OPAQUE_TOKEN_RE = re.compile(r"[A-Za-z0-9+/=_-]{20,}\Z")
_UUID_TOKEN_RE = re.compile(
    r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}\Z",
    re.IGNORECASE,
)
_SAFE_MODEL_NAMESPACE_RE = re.compile(
    r"(?:[a-z][a-z0-9]*(?:-[a-z0-9]+)*|"
    r"MiniMaxAI|NousResearch|Qwen|XiaomiMiMo)\Z",
)
_BEARER_VALUE_RE = re.compile(r"(?i)(?:basic|bearer)\s+\S+\Z")
_SAFE_API_MODES = frozenset({
    "anthropic_messages",
    "bedrock_converse",
    "chat_completions",
    "codex_app_server",
    "codex_responses",
})
_SAFE_TRANSPORTS = _SAFE_API_MODES | {"auto", "openai_chat"}
_SAFE_BASE_PATH_SEGMENTS = frozenset({
    "anthropic",
    "api",
    "chat",
    "completions",
    "models",
    "openai",
    "responses",
})
_SAFE_BASE_VERSION_SEGMENT_RE = re.compile(r"v\d+(?:alpha\d*|beta\d*)?\Z", re.IGNORECASE)


def _secret_display(value: Any, *, show_keys: bool) -> str:
    """Render a secret with the dump command's existing display semantics."""
    value_type = type(value)
    if value is None:
        return "not set"
    if value_type is str and value == "":
        return "not set"
    if not show_keys:
        return "set"
    try:
        if value_type is str:
            return _redact(value)
        if value_type in (bytes, bytearray):
            return _redact(bytes(value).decode("utf-8", errors="replace"))
        if value_type in (bool, float, int):
            return _redact(str(value))
    except Exception:
        pass
    # Do not call repr()/str() on arbitrary credential objects. Their custom
    # representation can itself expose the material this boundary protects.
    return "***"


def _redacted_text(value: str) -> str:
    """Apply the strict, non-optional text redactor at this support boundary."""
    from agent.redact import redact_sensitive_text

    return redact_sensitive_text(
        value,
        force=True,
        redact_url_credentials=True,
    )


def _looks_like_secret_value(value: str) -> bool:
    """Detect recognizable credentials even when their field name is unknown."""
    if _BEARER_VALUE_RE.fullmatch(value.strip()):
        return True
    try:
        return _redacted_text(value) != value
    except Exception:
        # Diagnostic output must fail closed. A redactor failure is not
        # permission to print the original scalar.
        return True


def _looks_like_opaque_token(value: str) -> bool:
    """Conservatively recognize high-entropy-looking literal credentials."""
    candidate = value.strip()
    if not _OPAQUE_TOKEN_RE.fullmatch(candidate):
        return False
    if _UUID_TOKEN_RE.fullmatch(candidate):
        return True
    if (
        len(candidate) >= 20
        and re.fullmatch(r"[a-z0-9]+", candidate, re.IGNORECASE)
        and any(char.isalpha() for char in candidate)
        and any(char.isdigit() for char in candidate)
    ):
        return True
    has_upper = any(char.isupper() for char in candidate)
    has_lower = any(char.islower() for char in candidate)
    has_digit = any(char.isdigit() for char in candidate)
    if has_upper and has_lower and has_digit:
        return True
    return (
        has_upper
        and has_digit
        and "_" not in candidate
        and "-" not in candidate
    )


def _looks_like_structured_namespaced_model(value: str) -> bool:
    """Recognize shipped vendor/model syntax without accepting arbitrary '/'."""
    if value.count("/") != 1:
        return False
    namespace, model = value.split("/", 1)
    if not _SAFE_MODEL_NAMESPACE_RE.fullmatch(namespace):
        return False
    separators = re.findall(r"[-._:]", model)
    words = re.split(r"[-._:]+", model)
    return (
        len(separators) >= 2
        and any(len(word) >= 3 and word.isalpha() for word in words)
    )


def _safe_identifier(value: Any, *, allow_namespaced_model: bool = False) -> str:
    """Render a provider/model identifier without coercing arbitrary objects."""
    if not isinstance(value, str):
        return "<invalid>"
    candidate = value.strip()
    if not candidate:
        return "(not set)"
    if not _IDENTIFIER_RE.fullmatch(candidate):
        return "<invalid>"
    looks_like_opaque_token = (
        _looks_like_opaque_token(candidate)
        and not (
            allow_namespaced_model
            and _looks_like_structured_namespaced_model(candidate)
        )
    )
    if _looks_like_secret_value(candidate) or looks_like_opaque_token:
        return "<redacted>"
    return candidate


def _safe_enum(value: Any, *, allowed: frozenset[str]) -> str:
    """Render a documented routing enum and suppress unexpected scalar data."""
    if isinstance(value, str) and value in allowed:
        return value
    return "<invalid>"


def _safe_env_reference(value: Any) -> str:
    """Report reference presence without trying to distinguish names from keys."""
    if value is None or (isinstance(value, str) and value == ""):
        return "not set"
    # A credential can be deliberately or accidentally shaped exactly like an
    # uppercase environment name. No syntax test can authorize its bytes.
    return "configured"


def _safe_base_url(value: Any) -> str:
    """Retain endpoint routing without URL-carried credentials or private data."""
    if not isinstance(value, str):
        return "<invalid>"
    candidate = value.strip()
    if not candidate:
        return "(not set)"
    try:
        parsed = urlsplit(candidate)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return "<invalid>"
        hostname = parsed.hostname
        if any(
            _looks_like_secret_value(label) or _looks_like_opaque_token(label)
            for label in hostname.split(".")
        ):
            return "<redacted endpoint>"
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        port = parsed.port
        netloc = f"{hostname}:{port}" if port is not None else hostname

        path = parsed.path
        if path and path != "/":
            segments = [unquote(segment) for segment in path.split("/") if segment]
            if all(
                segment.lower() in _SAFE_BASE_PATH_SEGMENTS
                or _SAFE_BASE_VERSION_SEGMENT_RE.fullmatch(segment)
                for segment in segments
            ):
                path = "/" + "/".join(segments)
            else:
                path = "/<path-omitted>"

        # Userinfo is removed while rebuilding netloc. Query strings and
        # fragments are omitted wholesale because custom gateways commonly
        # carry opaque credentials in names that no denylist can enumerate.
        return urlunsplit((parsed.scheme.lower(), netloc, path, "", ""))
    except Exception:
        return "<invalid>"


def _sanitize_fallback_entry(
    entry: Any,
    *,
    show_keys: bool,
) -> dict[str, Any] | str:
    """Return only runtime-relevant fallback fields from a plain YAML mapping."""
    if type(entry) is not dict:
        return "<invalid fallback entry>"

    sanitized: dict[str, Any] = {}
    for field in _FALLBACK_DIAGNOSTIC_FIELDS:
        if field not in entry:
            continue
        value = entry[field]
        if field in {"provider", "model"}:
            sanitized[field] = _safe_identifier(
                value,
                allow_namespaced_model=field == "model",
            )
        elif field == "base_url":
            sanitized[field] = _safe_base_url(value)
        elif field == "api_mode":
            sanitized[field] = _safe_enum(value, allowed=_SAFE_API_MODES)
        elif field == "transport":
            sanitized[field] = _safe_enum(value, allowed=_SAFE_TRANSPORTS)
        elif field in {"key_env", "api_key_env"}:
            sanitized[field] = _safe_env_reference(value)
        else:
            sanitized[field] = _secret_display(value, show_keys=show_keys)

    omitted_fields = sum(
        1
        for key in entry
        if not isinstance(key, str) or key not in _FALLBACK_DIAGNOSTIC_FIELD_SET
    )
    if omitted_fields:
        sanitized["omitted_fields"] = omitted_fields
    return sanitized


def _sanitize_fallback_providers(value: Any, *, show_keys: bool) -> Any:
    """Sanitize the accepted dict/list shapes without traversing unknown data."""
    if type(value) is dict:
        return _sanitize_fallback_entry(value, show_keys=show_keys)
    if type(value) is list:
        return [
            _sanitize_fallback_entry(entry, show_keys=show_keys)
            for entry in value
        ]
    return "<invalid fallback_providers>"


def _config_overrides(config: dict, *, show_keys: bool = False) -> dict[str, str]:
    """Find non-default config values worth reporting.
    
    Returns a flat dict of dotpath -> value for interesting overrides.
    """
    from hermes_cli.config import DEFAULT_CONFIG

    overrides = {}

    # Sections with interesting user-facing overrides
    interesting_paths = [
        ("agent", "max_turns"),
        ("agent", "gateway_timeout"),
        ("agent", "tool_use_enforcement"),
        ("terminal", "backend"),
        ("terminal", "docker_image"),
        ("terminal", "persistent_shell"),
        ("browser", "allow_private_urls"),
        ("compression", "enabled"),
        ("compression", "threshold"),
        ("display", "streaming"),
        ("display", "skin"),
        ("display", "show_reasoning"),
        ("privacy", "redact_pii"),
        ("tts", "provider"),
    ]

    for section, key in interesting_paths:
        default_section = DEFAULT_CONFIG.get(section, {})
        user_section = config.get(section, {})
        if not isinstance(default_section, dict) or not isinstance(user_section, dict):
            continue
        default_val = default_section.get(key)
        user_val = user_section.get(key)
        if user_val is not None and user_val != default_val:
            overrides[f"{section}.{key}"] = str(user_val)

    # Toolsets (if different from default)
    default_toolsets = DEFAULT_CONFIG.get("toolsets", [])
    user_toolsets = config.get("toolsets", [])
    if user_toolsets != default_toolsets:
        overrides["toolsets"] = str(user_toolsets)

    # Fallback providers
    try:
        fallbacks = config.get("fallback_providers", [])
        has_fallbacks = (
            (type(fallbacks) in {dict, list} and len(fallbacks) > 0)
            or (type(fallbacks) not in {dict, list} and fallbacks is not None)
        )
        if has_fallbacks:
            sanitized_fallbacks = _sanitize_fallback_providers(
                fallbacks,
                show_keys=show_keys,
            )
            overrides["fallback_providers"] = json.dumps(
                sanitized_fallbacks,
                ensure_ascii=False,
            )
    except Exception:
        # Diagnostic output is a security boundary. A malformed custom
        # container must not turn its exception text into a second
        # stringification path for credential material.
        overrides["fallback_providers"] = '"<redaction failed>"'

    return overrides


def run_dump(args):
    """Output a compact, copy-pasteable setup summary."""
    show_keys = getattr(args, "show_keys", False)

    # Load env from .env file so key checks work
    env_path = get_env_path()
    load_hermes_dotenv(
        hermes_home=env_path.parent,
        project_env=get_project_root() / ".env",
    )

    project_root = get_project_root()
    hermes_home = get_hermes_home()

    try:
        from hermes_cli import __version__
    except ImportError:
        __version__ = "(unknown)"

    commit = _get_git_commit(project_root)
    commit_date = _get_git_commit_date(project_root)

    try:
        config = load_config()
    except Exception:
        config = {}

    model, provider = _get_model_and_provider(config)

    # Profile
    try:
        from hermes_cli.profiles import get_active_profile_name
        profile = get_active_profile_name() or "(default)"
    except Exception:
        profile = "(default)"

    # Terminal backend — report the EFFECTIVE backend, not just config.yaml.
    # ``terminal.backend`` in config.yaml is bridged to the TERMINAL_ENV env var,
    # but a TERMINAL_ENV set directly in .env / the shell overrides config and is
    # what terminal_tool actually uses (tools/terminal_tool.py reads TERMINAL_ENV).
    # Reporting only the config value hides that override and sends users chasing
    # the wrong cause when the agent runs in a docker/podman sandbox even though
    # config says "local" (and vice-versa). run_dump() has already loaded .env,
    # so os.environ reflects the real override here.
    terminal_cfg = config.get("terminal", {})
    config_backend = terminal_cfg.get("backend", "local")
    env_backend = (os.environ.get("TERMINAL_ENV") or "").strip().lower()
    if env_backend and env_backend != str(config_backend).strip().lower():
        backend = (
            f"{env_backend}  (TERMINAL_ENV overrides config.yaml "
            f"terminal.backend={config_backend})"
        )
    else:
        backend = config_backend

    # OpenAI SDK version
    try:
        import openai
        openai_ver = openai.__version__
    except ImportError:
        openai_ver = "not installed"

    # OS info
    os_info = f"{platform.system()} {platform.release()} {platform.machine()}"

    lines = []
    lines.append("--- hermes dump ---")
    # Identify the build by commit + the date that commit was made, resolved
    # live via git.  __release_date__ (the package release date) is
    # intentionally NOT shown here — it reads like a wall-clock timestamp and
    # confuses support triage.  The commit date is the real "as-of" date.
    ver_str = f"{__version__}"
    ver_str += f" [{commit}]"
    if commit_date:
        ver_str += f" ({commit_date})"
    lines.append(f"version:          {ver_str}")
    lines.append(f"os:               {os_info}")
    lines.append(f"python:           {sys.version.split()[0]}")
    lines.append(f"openai_sdk:       {openai_ver}")
    lines.append(f"profile:          {profile}")
    lines.append(f"hermes_home:      {display_hermes_home()}")
    lines.append(f"model:            {model}")
    lines.append(f"provider:         {provider}")
    lines.append(f"terminal:         {backend}")

    # API keys
    lines.append("")
    lines.append("api_keys:")
    api_keys = [
        ("OPENROUTER_API_KEY", "openrouter"),
        ("OPENAI_API_KEY", "openai"),
        ("ANTHROPIC_API_KEY", "anthropic"),
        ("ANTHROPIC_TOKEN", "anthropic_token"),
        ("NOUS_API_KEY", "nous"),
        ("GOOGLE_API_KEY", "google/gemini"),
        ("GEMINI_API_KEY", "gemini"),
        ("GLM_API_KEY", "glm/zai"),
        ("ZAI_API_KEY", "zai"),
        ("KIMI_API_KEY", "kimi"),
        ("MINIMAX_API_KEY", "minimax"),
        ("DEEPSEEK_API_KEY", "deepseek"),
        ("DASHSCOPE_API_KEY", "dashscope"),
        ("HF_TOKEN", "huggingface"),
        ("NVIDIA_API_KEY", "nvidia"),
        ("OPENCODE_ZEN_API_KEY", "opencode_zen"),
        ("OPENCODE_GO_API_KEY", "opencode_go"),
        ("KILOCODE_API_KEY", "kilocode"),
        ("FIRECRAWL_API_KEY", "firecrawl"),
        ("TAVILY_API_KEY", "tavily"),
        ("BROWSERBASE_API_KEY", "browserbase"),
        ("FAL_KEY", "fal"),
        ("ELEVENLABS_API_KEY", "elevenlabs"),
        ("GITHUB_TOKEN", "github"),
    ]

    dotenv_keys = _dotenv_key_names()

    for env_var, label in api_keys:
        val = os.getenv(env_var, "")
        if show_keys and val:
            display = _redact(val)
        else:
            display = "set" if val else "not set"
        # Set in this (shell) process but absent from ~/.hermes/.env: a managed
        # backend (launchd/systemd/desktop `serve`) loads .env, not the login
        # shell, so it likely can't see this key — even though the dump reads
        # "set". Flag it so support doesn't chase a phantom "key is configured"
        # (the actual cause of gated tools like web_search going missing).
        if val and env_var not in dotenv_keys:
            display += " (shell only — not in .env; managed/desktop backend may not see it)"
        # A credential added via `hermes auth add openrouter` lives in the
        # credential pool, not as an env var — surface it so the dump doesn't
        # misleadingly read "not set" while `hermes auth list` shows it (#42130).
        if not val and label == "openrouter":
            try:
                from agent.credential_pool import load_pool as _load_pool

                if _load_pool("openrouter").has_credentials():
                    display = "set (auth pool)"
            except Exception:
                pass
        lines.append(f"  {label:<20} {display}")

    # Features summary
    lines.append("")
    lines.append("features:")

    toolsets = config.get("toolsets", ["hermes-cli"])
    lines.append(f"  toolsets:           {', '.join(toolsets) if toolsets else '(default)'}")
    lines.append(f"  mcp_servers:        {_count_mcp_servers(config)}")
    lines.append(f"  memory_provider:    {_memory_provider(config)}")
    lines.append(f"  gateway:            {_gateway_status()}")

    platforms = _configured_platforms()
    lines.append(f"  platforms:          {', '.join(platforms) if platforms else 'none'}")
    lines.append(f"  cron_jobs:          {_cron_summary(hermes_home)}")
    lines.append(f"  skills:             {_count_skills(hermes_home)}")

    # Config overrides (non-default values)
    overrides = _config_overrides(config, show_keys=show_keys)
    if overrides:
        lines.append("")
        lines.append("config_overrides:")
        for key, val in overrides.items():
            lines.append(f"  {key}: {val}")

    lines.append("--- end dump ---")

    output = "\n".join(lines)
    print(output)
