#!/usr/bin/env python3
"""Joltic — single-file SSH selector with an optional config wizard."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Sequence

CONFIG_UI_SENTINEL = "__CONFIG_UI__"
DEFAULT_CONFIG: Dict[str, Any] = {
    "aliases": {"SIT": ["QA", "TEST"], "UAT": ["STAGING"], "PFIX": []},
    "servers": {
        "SIT": {
            "batches": [
                {"name": "batch1", "host": "sit-batch1.company.com", "user": "ec2-user"},
                {"name": "batch2", "host": "sit-batch2.company.com", "user": "ec2-user"},
            ],
            "webapps": [
                {"name": "web1", "host": "sit-web1.company.com", "user": "ec2-user"},
            ],
        },
        "UAT": {
            "batches": [
                {"name": "batch1", "host": "uat-batch1.company.com", "user": "ubuntu"},
            ],
        },
        "PFIX": {
            "webapps": [
                {"name": "web1", "host": "pfix-web1.company.com", "user": "ubuntu"},
            ]
        },
    },
}

try:
    import questionary
except ImportError:  # pragma: no cover - optional dependency
    questionary = None  # type: ignore


def get_app_dir() -> Path:
    custom = os.environ.get("JOLTIC_HOME")
    if custom:
        path = Path(custom).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path

    default = Path.home() / ".joltic"
    if ensure_writable_dir(default):
        return default

    fallback = Path.cwd() / ".joltic"
    if ensure_writable_dir(fallback):
        return fallback

    raise RuntimeError("Unable to determine a writable configuration directory")


def ensure_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False

    try:
        with tempfile.NamedTemporaryFile(dir=str(path)):
            return True
    except OSError:
        return False


def configure_logging(level: int = logging.INFO, stream: bool = True) -> Path:
    log_path = get_app_dir() / "connect.log"
    try:
        with log_path.open("a", encoding="utf-8"):
            pass
    except (OSError, PermissionError):
        fallback = Path.cwd() / ".joltic" / "connect.log"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        with fallback.open("a", encoding="utf-8"):
            pass
        log_path = fallback

    handlers = [logging.FileHandler(log_path, encoding="utf-8")]
    if stream:
        handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
        force=True,
    )

    logging.debug("Logging to %s", log_path)
    return log_path


def prompt_select(message: str, choices: Sequence[str]) -> str:
    options = list(choices)
    if not options:
        raise ValueError("No options to select from")
    if questionary:
        result = questionary.select(message, choices=options).ask()
        if result is None:
            raise RuntimeError("Selection cancelled")
        return result

    print(message)
    for idx, choice in enumerate(options, start=1):
        print(f"{idx}. {choice}")
    while True:
        answer = input("Enter choice number: ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        print("Invalid selection, try again.")


def prompt_text(message: str, default: str | None = None) -> str:
    if questionary:
        result = questionary.text(message, default=default).ask()
        if result is None:
            return default or ""
        return result
    prompt = f"{message}"
    if default:
        prompt += f" [{default}]"
    prompt += ": "
    value = input(prompt).strip()
    return value or (default or "")


def prompt_confirm(message: str, default: bool = True) -> bool:
    if questionary:
        result = questionary.confirm(message, default=default).ask()
        if result is None:
            return default
        return result
    suffix = "Y/n" if default else "y/N"
    while True:
        value = input(f"{message} ({suffix}): ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Please answer y or n.")


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")


def validate_config(config: MutableMapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(config, MutableMapping):
        raise ValueError("Configuration must be a mapping")

    aliases = config.setdefault("aliases", {})
    servers = config.setdefault("servers", {})

    if not isinstance(aliases, Mapping):
        raise ValueError("'aliases' must be an object")
    if not isinstance(servers, Mapping):
        raise ValueError("'servers' must be an object")

    for env, alias_list in aliases.items():
        if not isinstance(alias_list, list) or not all(isinstance(a, str) for a in alias_list):
            raise ValueError(f"Aliases for {env} must be a list of strings")

    for env, categories in servers.items():
        if not isinstance(categories, Mapping):
            raise ValueError(f"Environment '{env}' must map to categories")
        for category, entries in categories.items():
            if not isinstance(entries, list):
                raise ValueError(f"Category '{category}' must be a list of servers")
            for server in entries:
                if not isinstance(server, Mapping):
                    raise ValueError("Server entries must be objects")
                if "name" not in server or "host" not in server:
                    raise ValueError("Server entries need 'name' and 'host'")
    return dict(config)


def clone_default_config() -> Dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_CONFIG))


def load_config(path: Path | None = None) -> Dict[str, Any]:
    if path:
        return validate_config(load_json(path.expanduser()))

    user_path = get_app_dir() / "config.json"
    if user_path.exists():
        return validate_config(load_json(user_path))
    return clone_default_config()


def save_config(config: Mapping[str, Any], path: Path | None = None) -> Path:
    target = path.expanduser() if path else get_app_dir() / "config.json"
    validate_config(dict(config))
    save_json(target, config)
    logging.info("Configuration saved to %s", target)
    return target


def run_config_wizard(path: Path | None = None) -> None:
    logging.info("Starting configuration wizard")
    config: Dict[str, Any] = {"aliases": {}, "servers": {}}

    while True:
        env = prompt_text("Environment name (blank to finish)").strip()
        if not env:
            break
        alias_text = prompt_text(f"Aliases for '{env}' (comma separated)", default="")
        aliases = [a.strip() for a in alias_text.split(",") if a.strip()]
        config["aliases"][env] = aliases
        config["servers"][env] = collect_category_entries(env)

    if not config["servers"]:
        logging.warning("No environments captured; nothing to save")
        return

    if not prompt_confirm("Save this configuration?", default=True):
        logging.info("Configuration wizard cancelled")
        return

    save_config(config, path)


def collect_category_entries(env: str) -> Dict[str, List[Dict[str, Any]]]:
    categories: Dict[str, List[Dict[str, Any]]] = {}
    while True:
        category = prompt_text(f"Category for '{env}' (blank to finish)").strip()
        if not category:
            break
        entries: List[Dict[str, Any]] = []
        while True:
            name = prompt_text(f"  Server label for '{category}' (blank to finish)").strip()
            if not name:
                break
            host = prompt_text("    Hostname or IP").strip()
            user = prompt_text("    Username (optional)", default="").strip()
            port = prompt_text("    Port (optional)", default="").strip()
            payload: Dict[str, Any] = {"name": name, "host": host}
            if user:
                payload["user"] = user
            if port:
                payload["port"] = int(port) if port.isdigit() else port
            entries.append(payload)
        categories[category] = entries
    return categories


def resolve_environment(config: Mapping[str, Any], hint: str | None) -> str:
    servers = config.get("servers", {})
    if not isinstance(servers, Mapping) or not servers:
        raise RuntimeError("No environments configured")

    alias_index: Dict[str, str] = {}
    for env in servers:
        alias_index[env.lower()] = env
    for env, alias_list in config.get("aliases", {}).items():
        if isinstance(alias_list, list):
            for alias in alias_list:
                alias_index[str(alias).lower()] = env

    if hint:
        env = alias_index.get(hint.lower())
        if not env:
            raise RuntimeError(f"Unknown environment '{hint}'")
        return env

    unique_envs = sorted(set(alias_index.values()))
    choice = prompt_select("Select environment", unique_envs)
    return choice


def resolve_category(config: Mapping[str, Any], env: str, hint: str | None) -> str:
    servers = config.get("servers", {})
    categories = servers.get(env) if isinstance(servers, Mapping) else None
    if not isinstance(categories, Mapping) or not categories:
        raise RuntimeError(f"Environment '{env}' has no categories")

    if hint:
        if hint in categories:
            return hint
        raise RuntimeError(f"Category '{hint}' not available for environment '{env}'")

    if len(categories) == 1:
        return next(iter(categories))
    return prompt_select(f"Select category for {env}", sorted(categories.keys()))


def resolve_server(config: Mapping[str, Any], env: str, category: str) -> Mapping[str, Any]:
    servers = config.get("servers", {})
    categories = servers.get(env) if isinstance(servers, Mapping) else None
    entries = categories.get(category) if isinstance(categories, Mapping) else None
    if not isinstance(entries, list) or not entries:
        raise RuntimeError(f"No servers for {env}/{category}")

    if len(entries) == 1:
        return entries[0]

    labels = [f"{entry.get('name')} ({entry.get('host')})" for entry in entries]
    selection = prompt_select(f"Select server from {env}/{category}", labels)
    return entries[labels.index(selection)]


def build_ssh_command(server: Mapping[str, Any], extra_args: Sequence[str] | None = None) -> List[str]:
    host = server.get("host")
    if not host:
        raise RuntimeError("Server definition missing 'host'")
    user = server.get("user")
    port = server.get("port")

    destination = f"{user}@{host}" if user else str(host)
    command = ["ssh"]
    if port:
        command.extend(["-p", str(port)])
    if extra_args:
        command.extend(extra_args)
    command.append(destination)
    return command


def run_ssh(command: Sequence[str]) -> int:
    logging.info("Launching SSH command: %s", " ".join(shlex.quote(arg) for arg in command))
    try:
        return subprocess.call(command)
    except OSError as exc:  # pragma: no cover - depends on system availability
        logging.error("Failed to execute ssh: %s", exc)
        return 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Joltic SSH launcher")
    parser.add_argument("environment", nargs="?", help="Environment or alias (e.g. SIT, QA)")
    parser.add_argument("category", nargs="?", help="Category within the environment")
    parser.add_argument(
        "--config",
        nargs="?",
        const=CONFIG_UI_SENTINEL,
        metavar="PATH",
        help="Load config from PATH or launch the interactive wizard if omitted",
    )
    parser.add_argument(
        "--ssh-arg",
        action="append",
        dest="ssh_args",
        help="Extra argument to forward to ssh (repeatable)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved ssh command instead of executing it",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging()

    if args.config == CONFIG_UI_SENTINEL:
        run_config_wizard()
        return 0

    if args.config:
        source = Path(args.config).expanduser()
        try:
            imported_config = load_config(source)
        except (OSError, ValueError) as exc:
            logging.error("Unable to load configuration from %s: %s", source, exc)
            return 2

        try:
            target = save_config(imported_config)
        except (OSError, ValueError, RuntimeError) as exc:
            logging.error("Unable to persist configuration: %s", exc)
            return 2

        message = f"Configuration imported from {source} and stored at {target}"
        print(message)
        logging.info(message)
        return 0

    try:
        config = load_config()
    except (OSError, ValueError) as exc:
        logging.error("Unable to load configuration: %s", exc)
        return 2

    try:
        env = resolve_environment(config, args.environment)
        category = resolve_category(config, env, args.category)
        server = resolve_server(config, env, category)
    except RuntimeError as exc:
        logging.error("%s", exc)
        return 3

    command = build_ssh_command(server, args.ssh_args)
    command_str = " ".join(shlex.quote(arg) for arg in command)
    logging.info("Resolved SSH command: %s", command_str)

    if args.dry_run:
        print(command_str)
        return 0

    return run_ssh(command)


if __name__ == "__main__":
    sys.exit(main())
