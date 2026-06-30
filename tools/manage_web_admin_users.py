#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from web_admin_app import auth, database


def required_env(name):
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"缺少环境变量：{name}")
    return value


def main():
    parser = argparse.ArgumentParser(description="MES Web administrator maintenance")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init")
    reset_parser = subparsers.add_parser("reset")
    reset_parser.add_argument("--username", choices=("admin", "super_admin"), required=True)
    subparsers.add_parser("validate")
    args = parser.parse_args()

    database.init_db()
    auth.ensure_session_secret()

    if args.command == "init":
        if auth.get_user_by_username("admin") or auth.get_user_by_username("super_admin"):
            raise SystemExit("管理账号已存在；如需改密请使用 reset 命令")
        created = auth.bootstrap_builtin_accounts(
            required_env("MES_ADMIN_INITIAL_PASSWORD"),
            required_env("MES_SUPER_ADMIN_INITIAL_PASSWORD"),
        )
        print("管理账号初始化完成：" + ", ".join(created))
        return

    if args.command == "reset":
        auth.reset_password_from_server(
            args.username,
            required_env("MES_WEB_ADMIN_NEW_PASSWORD"),
            allow_super_admin=args.username == "super_admin",
        )
        print(f"{args.username} 密码哈希已更新")
        return

    auth.validate_builtin_accounts()
    print("管理账号状态正常")


if __name__ == "__main__":
    main()
