# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Credential-safe connection configuration, independent of database drivers.

A profile declares its fields/defaults and environment aliases. Only the selected
profile is read; templates are documentation, never runtime configuration.
"""
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values


class DatabaseConfigError(ValueError):
    """Configuration error whose message never contains a configured value."""


@dataclass(frozen=True)
class DatabaseProfile:
    defaults: dict
    env: dict
    secrets: dict = field(default_factory=dict)
    required: tuple = ()
    integers: dict = field(default_factory=dict)
    paths: tuple = ()


def environment(root):
    """Process values win over .env, including explicitly empty values."""
    return {**dotenv_values(Path(root) / ".env", interpolate=False), **os.environ}


def config_directory(root, env=None):
    env = environment(root) if env is None else env
    directory = Path(env.get("DATABASE_CONFIG_DIR") or "etc/conf/db")
    return directory if directory.is_absolute() else Path(root) / directory


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DatabaseConfigError("Duplicate database configuration field")
        result[key] = value
    return result


def read_profile_file(profile_name, root, env=None):
    path = config_directory(root, env) / (profile_name + ".json")
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8-sig"),
                          object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise DatabaseConfigError(f"Cannot read db/{profile_name}.json; check JSON syntax and permissions") from None
    if not isinstance(data, dict):
        raise DatabaseConfigError(f"db/{profile_name}.json must contain an object")
    return data


def load_profile(name, profile, root):
    """Resolve process env > .env > selected JSON > provider defaults.

    Aliases are evaluated separately in each layer so a process generic DB_HOST
    beats a vendor-specific host in .env. A custom secret reference is exclusive:
    unrelated generic credentials cannot replace it.
    """
    root = Path(root)
    dotenv = dotenv_values(root / ".env", interpolate=False)
    env = {**dotenv, **os.environ}
    raw = read_profile_file(name, root, env)
    path = config_directory(root, env) / (name + ".json")
    allowed = set(profile.defaults) | set(profile.env) | {
        secret + "_env" for secret in profile.secrets}
    if set(raw) - allowed or any(secret in raw for secret in profile.secrets):
        raise DatabaseConfigError(f"Unsupported or literal-secret field in db/{name}.json")
    config = {**profile.defaults, **raw}
    for layer in (dotenv, os.environ):
        for key, aliases in profile.env.items():
            for alias in aliases:
                if alias in layer and layer[alias] is not None:
                    config[key] = layer[alias]
                    break
    for secret, aliases in profile.secrets.items():
        reference = raw.get(secret + "_env")
        if secret + "_env" in raw and (not isinstance(reference, str) or
                                     not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", reference)):
            raise DatabaseConfigError(f"db/{name}.json: invalid {secret}_env reference")
        names = (reference,) if reference else aliases
        value = None
        for layer in (dotenv, os.environ):
            for alias in names:
                if alias in layer and layer[alias] is not None:
                    value = layer[alias]
                    break
        if value is None and secret in profile.required:
            raise DatabaseConfigError(f"db/{name}.json: {names[0]} is not set")
        if value is not None:
            config[secret] = value
        config.pop(secret + "_env", None)
    for key in profile.required:
        value = config.get(key)
        if key in profile.secrets:
            continue  # An explicitly empty password supports passwordless local DBs.
        if not isinstance(value, str) or not value.strip() or value.startswith("<"):
            raise DatabaseConfigError(f"db/{name}.json: configure {key}")
    for key, bounds in profile.integers.items():
        if key not in config:
            continue
        try:
            value = config[key]
            if isinstance(value, bool):
                raise ValueError
            number = int(value)
            if str(number) != str(value).strip() or not bounds[0] <= number <= bounds[1]:
                raise ValueError
        except (ValueError, TypeError):
            raise DatabaseConfigError(f"db/{name}.json: invalid {key}") from None
        config[key] = number
    if "pool_min" in config and config["pool_min"] > config["pool_max"]:
        raise DatabaseConfigError(f"db/{name}.json: pool_min exceeds pool_max")
    for key in profile.paths:
        if key in config and not isinstance(config[key], str):
            raise DatabaseConfigError(f"db/{name}.json: invalid {key}")
        if config.get(key) and not Path(config[key]).is_absolute():
            config[key] = str(root / config[key])
    if config.get("uri"):
        try:
            uri = urlsplit(config["uri"])
        except (ValueError, TypeError, AttributeError):
            raise DatabaseConfigError(f"db/{name}.json: invalid uri") from None
        if uri.username or uri.password:
            raise DatabaseConfigError(f"db/{name}.json: credentials in uri are not allowed")
    return config
