#!/usr/bin/env python3
"""Apply portable Codex preferences while retaining each machine's local settings."""

import argparse
from copy import deepcopy
from datetime import date, datetime, time
import json
import os
from pathlib import Path
import tempfile

try:
    import tomllib
except ModuleNotFoundError:
    raise SystemExit("Codex preference sync requires Python 3.11 or newer; nothing was changed.")


SHARED = Path(__file__).resolve().parents[1] / "codex/config.toml"
PORTABLE = {
    "personality": None,
    "model": None,
    "model_reasoning_effort": None,
    "web_search": None,
    "model_context_window": None,
    "model_auto_compact_token_limit": None,
    "plan_mode_reasoning_effort": None,
    "service_tier": None,
    "features": {"worktrees"},
    "tui": {
        "notifications", "notification_method", "notification_condition",
        "mouse_scroll_speed", "status_line", "status_line_use_colors", "theme",
    },
}


def portable_preferences(config):
    result = {}
    for key, children in PORTABLE.items():
        if key not in config:
            continue
        if children is None:
            if isinstance(config[key], dict):
                raise ValueError(f"Expected a preference value for {key}")
            result[key] = config[key]
        else:
            if not isinstance(config[key], dict):
                raise ValueError(f"Expected a preference table for {key}")
            result[key] = {k: v for k, v in config[key].items() if k in children}
    return result


def toml_value(value):
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(
            f"{toml_value(key)} = {toml_value(item)}" for key, item in value.items()
        ) + " }"
    raise ValueError(f"Unsupported TOML value type: {type(value).__name__}")


def serialize(config):
    lines = []

    def table(values, path=()):
        if path:
            lines.extend(["", "[" + ".".join(toml_value(key) for key in path) + "]"])
        for key, value in values.items():
            if not isinstance(value, dict):
                lines.append(f"{toml_value(key)} = {toml_value(value)}")
        for key, value in values.items():
            if isinstance(value, dict):
                table(value, (*path, key))

    table(config)
    result = "\n".join(lines).lstrip("\n") + "\n"
    if tomllib.loads(result) != config:
        raise ValueError("TOML round trip changed settings; leaving configuration unchanged")
    return result.encode()


def replace_file(path, original, updated, *, backup):
    if path.is_symlink():
        raise ValueError(f"Refusing to replace a symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (path.read_bytes() if path.exists() else b"") != original:
        raise ValueError(f"Configuration changed during sync; retry: {path}")
    if backup and path.exists():
        fd, _ = tempfile.mkstemp(prefix=".config.toml.before-dotfiles-", dir=path.parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(original)
    fd, temporary = tempfile.mkstemp(prefix=".codex-preferences-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        if (path.read_bytes() if path.exists() else b"") != original:
            raise ValueError(f"Configuration changed during sync; retry: {path}")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def sync(shared, local, *, capture=False):
    source, destination = (local, shared) if capture else (shared, local)
    preferences = tomllib.loads(source.read_text())
    selected = portable_preferences(preferences)
    if not capture and selected != preferences:
        raise ValueError("Shared config contains non-portable settings; nothing was changed")
    original = destination.read_bytes() if destination.exists() else b""
    existing = tomllib.loads(original.decode())
    if capture:
        updated = selected
    else:
        updated = deepcopy(existing)
        for key, value in selected.items():
            if isinstance(value, dict):
                current = updated.setdefault(key, {})
                if not isinstance(current, dict):
                    raise ValueError(f"Local {key} must be a table; nothing was changed")
                current.update(value)
            else:
                updated[key] = value
    if updated == existing:
        return False
    replace_file(destination, original, serialize(updated), backup=not capture)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shared", type=Path, default=SHARED)
    config_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    parser.add_argument("--local", type=Path, default=config_home / "config.toml")
    parser.add_argument("--capture", action="store_true", help="capture local portable preferences")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    try:
        changed = sync(args.shared, args.local, capture=args.capture)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Codex preference sync failed: {error}\n")
    if not args.quiet:
        print("Codex preferences updated." if changed else "Codex preferences already match.")


if __name__ == "__main__":
    main()
