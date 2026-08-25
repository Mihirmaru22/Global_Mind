#!/usr/bin/env python3
"""CLI tool for safely managing feature flags in config/feature_flags.yaml."""

from __future__ import annotations

import argparse
import datetime
import logging
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
CONFIG_DIR = PROJECT_ROOT / "config"
FLAG_FILE = CONFIG_DIR / "feature_flags.yaml"
BACKUP_DIR = CONFIG_DIR / "backups"

TARGET_FLAGS = [
    "delta_repair_enabled",
    "token_budget_enabled",
    "schema_compaction_enabled",
    "sql_safety_enabled",
    "zero_row_handling_enabled",
    "fast_path_enabled",
    "provider_routing_v2_enabled",
]


def create_backup(flag_file: Path, backup_dir: Path | None = None) -> Path | None:
    """Safely back up feature_flags.yaml before modification."""
    if not flag_file.exists():
        return None
    target_backup_dir = backup_dir or (flag_file.parent / "backups")
    target_backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = target_backup_dir / f"{flag_file.name}.bak.{timestamp}"
    shutil.copy2(flag_file, backup_path)
    return backup_path


def load_flags(flag_file: Path) -> dict[str, Any]:
    """Load flags from yaml file."""
    if not flag_file.exists():
        return {"features": {k: False for k in TARGET_FLAGS}}
    with open(flag_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {"features": {k: False for k in TARGET_FLAGS}}
    if "features" not in data:
        data = {"features": data}
    return data


def save_flags(flag_file: Path, data: dict[str, Any]) -> None:
    """Save flags to yaml file with backup."""
    create_backup(flag_file)
    flag_file.parent.mkdir(parents=True, exist_ok=True)
    with open(flag_file, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def cmd_status(flag_file: Path) -> int:
    """Print the current state of all optimization flags."""
    data = load_flags(flag_file)
    features = data.get("features", {})

    print("\n==================================================")
    print("        OPTIMIZATION FEATURE FLAGS STATUS         ")
    print("==================================================")
    for flag in TARGET_FLAGS:
        val = bool(features.get(flag, False))
        status_str = "[ENABLED]" if val else "[DISABLED]"
        print(f"  • {flag:35} : {status_str}")
    print("==================================================\n")
    return 0


def cmd_enable(flag_file: Path, flag_name: str) -> int:
    """Turn a specific flag to True."""
    if flag_name not in TARGET_FLAGS:
        print(f"Error: Unknown flag '{flag_name}'. Valid flags are:\n  - " + "\n  - ".join(TARGET_FLAGS), file=sys.stderr)
        return 1
    data = load_flags(flag_file)
    if "features" not in data:
        data["features"] = {}
    data["features"][flag_name] = True
    save_flags(flag_file, data)
    print(f"✓ Flag '{flag_name}' successfully set to True.")
    return 0


def cmd_enable_all(flag_file: Path) -> int:
    """Turn all 7 optimization flags to True."""
    data = load_flags(flag_file)
    if "features" not in data:
        data["features"] = {}
    for flag in TARGET_FLAGS:
        data["features"][flag] = True
    save_flags(flag_file, data)
    print("✓ All 7 optimization feature flags successfully set to True (100% Rollout).")
    return 0


def cmd_disable_all(flag_file: Path) -> int:
    """Revert all 7 optimization flags to False (emergency rollback)."""
    data = load_flags(flag_file)
    if "features" not in data:
        data["features"] = {}
    for flag in TARGET_FLAGS:
        data["features"][flag] = False
    save_flags(flag_file, data)
    print("✓ All 7 optimization feature flags reverted to False (Rollback complete).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage optimization feature flags.")
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    subparsers.add_parser("status", help="Show current flag status")
    enable_parser = subparsers.add_parser("enable", help="Enable a specific flag")
    enable_parser.add_argument("flag", help="Name of the flag to enable")
    subparsers.add_parser("enable_all", help="Enable all optimization flags")
    subparsers.add_parser("disable_all", help="Disable all optimization flags")

    parser.add_argument("--config", default=str(FLAG_FILE), help="Path to feature_flags.yaml")

    args = parser.parse_args(argv)
    flag_path = Path(args.config)

    if args.command == "status" or not args.command:
        return cmd_status(flag_path)
    elif args.command == "enable":
        return cmd_enable(flag_path, args.flag)
    elif args.command == "enable_all":
        return cmd_enable_all(flag_path)
    elif args.command == "disable_all":
        return cmd_disable_all(flag_path)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
