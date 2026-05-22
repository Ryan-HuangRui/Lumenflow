#!/usr/bin/env python3
"""Incrementally ingest X posts from approved photographer accounts.

This script is intentionally read-only against X. It fetches public posts for a
user-approved whitelist, writes source records under knowledge/source_records,
and keeps a small sync state so scheduled runs are idempotent.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

API_BASE_URL = "https://api.x.com/2"
DEFAULT_OUTPUT_DIR = Path("knowledge/source_records")
DEFAULT_SYNC_STATE_PATH = DEFAULT_OUTPUT_DIR / "x_sync_state.json"

DEFAULT_TWEET_FIELDS = [
    "attachments",
    "author_id",
    "created_at",
    "entities",
    "lang",
    "possibly_sensitive",
    "public_metrics",
    "referenced_tweets",
    "text",
]
DEFAULT_USER_FIELDS = [
    "created_at",
    "description",
    "id",
    "location",
    "name",
    "profile_image_url",
    "public_metrics",
    "url",
    "username",
    "verified",
]
DEFAULT_MEDIA_FIELDS = [
    "alt_text",
    "duration_ms",
    "height",
    "media_key",
    "preview_image_url",
    "public_metrics",
    "type",
    "url",
    "width",
]


class XApiError(RuntimeError):
    """Raised when the X API returns an error response."""


@dataclass(frozen=True)
class AccountConfig:
    username: str
    max_results: int
    pages: int
    exclude: list[str]
    only_with_media: bool


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_username(username: str) -> str:
    return username.strip().lstrip("@")


def load_config(path: Path) -> dict[str, Any]:
    config = read_json(path, None)
    if not isinstance(config, dict):
        raise SystemExit(f"Config must be a JSON object: {path}")
    return config


def parse_account_configs(config: dict[str, Any]) -> list[AccountConfig]:
    defaults = config.get("defaults", {})
    raw_accounts = config.get("accounts", [])
    if not isinstance(raw_accounts, list) or not raw_accounts:
        raise SystemExit("Config must include a non-empty accounts array.")

    account_configs: list[AccountConfig] = []
    for raw_account in raw_accounts:
        if isinstance(raw_account, str):
            raw_account = {"username": raw_account}
        if not isinstance(raw_account, dict):
            raise SystemExit("Each account must be a username string or object.")

        username = normalize_username(str(raw_account.get("username", "")))
        if not username:
            raise SystemExit("Each account must include username.")

        max_results = int(raw_account.get("max_results", defaults.get("max_results", 10)))
        pages = int(raw_account.get("pages", defaults.get("pages", 1)))
        exclude = raw_account.get("exclude", defaults.get("exclude", ["retweets", "replies"]))
        only_with_media = bool(raw_account.get("only_with_media", defaults.get("only_with_media", True)))

        if max_results < 5:
            max_results = 5
        if max_results > 100:
            max_results = 100
        if pages < 1:
            pages = 1

        account_configs.append(
            AccountConfig(
                username=username,
                max_results=max_results,
                pages=pages,
                exclude=list(exclude),
                only_with_media=only_with_media,
            )
        )

    return account_configs


def build_url(path: str, params: dict[str, str | int]) -> str:
    query = urllib.parse.urlencode(params)
    return f"{API_BASE_URL}{path}?{query}"


def api_get(url: str, bearer_token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {bearer_token}",
            "User-Agent": "lumenflow-x-source-ingest/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise XApiError(f"X API HTTP {error.code}: {detail[:500]}") from error
    except urllib.error.URLError as error:
        raise XApiError(f"X API request failed: {error}") from error

    payload = json.loads(body)
    if payload.get("errors") and not payload.get("data"):
        raise XApiError(json.dumps(payload["errors"], ensure_ascii=False)[:500])
    return payload


def get_user(username: str, bearer_token: str) -> dict[str, Any]:
    url = build_url(
        f"/users/by/username/{urllib.parse.quote(username)}",
        {"user.fields": ",".join(DEFAULT_USER_FIELDS)},
    )
    payload = api_get(url, bearer_token)
    user = payload.get("data")
    if not isinstance(user, dict):
        raise XApiError(f"User not found: {username}")
    return user


def get_user_posts(
    user_id: str,
    account: AccountConfig,
    bearer_token: str,
    since_id: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    posts: list[dict[str, Any]] = []
    newest_id: str | None = None
    pagination_token: str | None = None

    for _page in range(account.pages):
        params: dict[str, str | int] = {
            "max_results": account.max_results,
            "tweet.fields": ",".join(DEFAULT_TWEET_FIELDS),
            "user.fields": ",".join(DEFAULT_USER_FIELDS),
            "media.fields": ",".join(DEFAULT_MEDIA_FIELDS),
            "expansions": "attachments.media_keys,author_id",
        }
        if account.exclude:
            params["exclude"] = ",".join(account.exclude)
        if since_id:
            params["since_id"] = since_id
        if pagination_token:
            params["pagination_token"] = pagination_token

        url = build_url(f"/users/{user_id}/tweets", params)
        payload = api_get(url, bearer_token)
        posts.extend(build_records_from_response(payload, account))
        page_newest_id = payload.get("meta", {}).get("newest_id")
        if page_newest_id and (newest_id is None or int(page_newest_id) > int(newest_id)):
            newest_id = page_newest_id

        pagination_token = payload.get("meta", {}).get("next_token")
        if not pagination_token:
            break

    return posts, newest_id


def build_records_from_response(payload: dict[str, Any], account: AccountConfig) -> list[dict[str, Any]]:
    media_by_key = {
        media["media_key"]: media
        for media in payload.get("includes", {}).get("media", [])
        if isinstance(media, dict) and media.get("media_key")
    }
    users_by_id = {
        user["id"]: user
        for user in payload.get("includes", {}).get("users", [])
        if isinstance(user, dict) and user.get("id")
    }

    records = []
    for post in payload.get("data", []) or []:
        media_keys = post.get("attachments", {}).get("media_keys", [])
        media_items = [media_by_key[key] for key in media_keys if key in media_by_key]
        if account.only_with_media and not media_items:
            continue

        author = users_by_id.get(post.get("author_id"), {})
        records.append(
            {
                "schema_version": 1,
                "source_type": "x_post",
                "source_id": post["id"],
                "source_url": f"https://x.com/{account.username}/status/{post['id']}",
                "fetched_at": utc_now_iso(),
                "account": {
                    "username": account.username,
                    "id": post.get("author_id"),
                    "name": author.get("name"),
                    "verified": author.get("verified"),
                    "public_metrics": author.get("public_metrics", {}),
                },
                "post": post,
                "media": media_items,
                "analysis": {
                    "status": "pending_agent_review",
                    "visual_style_summary": "",
                    "style_card_candidates": [],
                    "notes": "",
                },
            }
        )
    return records


def load_sync_state(path: Path) -> dict[str, Any]:
    state = read_json(path, {"schema_version": 1, "accounts": {}})
    if "accounts" not in state or not isinstance(state["accounts"], dict):
        state["accounts"] = {}
    return state


def update_sync_state(
    state: dict[str, Any],
    username: str,
    user: dict[str, Any],
    records: list[dict[str, Any]],
    newest_id: str | None,
) -> None:
    account_state = state["accounts"].setdefault(username, {})
    account_state["user_id"] = user["id"]
    account_state["last_checked_at"] = utc_now_iso()
    if newest_id:
        previous = account_state.get("since_id")
        if previous is None or int(newest_id) > int(previous):
            account_state["since_id"] = newest_id
    account_state["last_new_records"] = len(records)


def source_record_path(output_dir: Path, record: dict[str, Any]) -> Path:
    username = record["account"]["username"].lower()
    source_id = record["source_id"]
    return output_dir / f"x_{username}_{source_id}.json"


def run(config_path: Path, dry_run: bool, bearer_token_env: str) -> dict[str, Any]:
    config = load_config(config_path)
    output_dir = Path(config.get("output_dir", DEFAULT_OUTPUT_DIR))
    sync_state_path = Path(config.get("sync_state_path", DEFAULT_SYNC_STATE_PATH))
    bearer_token = os.environ.get(bearer_token_env)

    if not bearer_token:
        raise SystemExit(f"Missing {bearer_token_env}. Set it to an X API Bearer Token.")

    state = load_sync_state(sync_state_path)
    summary = {
        "dry_run": dry_run,
        "config_path": str(config_path),
        "output_dir": str(output_dir),
        "sync_state_path": str(sync_state_path),
        "accounts": [],
    }

    for account in parse_account_configs(config):
        user = get_user(account.username, bearer_token)
        since_id = state["accounts"].get(account.username, {}).get("since_id")
        records, newest_id = get_user_posts(user["id"], account, bearer_token, since_id)

        existing_count = 0
        written_count = 0
        would_write = []
        for record in records:
            path = source_record_path(output_dir, record)
            if path.exists():
                existing_count += 1
                continue
            would_write.append(str(path))
            if not dry_run:
                write_json(path, record)
                written_count += 1

        update_sync_state(state, account.username, user, records, newest_id)
        summary["accounts"].append(
            {
                "username": account.username,
                "user_id": user["id"],
                "since_id_before": since_id,
                "since_id_after": newest_id or since_id,
                "fetched_new_records": len(records),
                "existing_records": existing_count,
                "written_records": written_count,
                "would_write": would_write if dry_run else [],
            }
        )

    if not dry_run:
        write_json(sync_state_path, state)

    return summary


def print_config_example() -> None:
    example = {
        "defaults": {
            "max_results": 10,
            "pages": 1,
            "exclude": ["retweets", "replies"],
            "only_with_media": True,
        },
        "accounts": [
            {"username": "example_photographer", "max_results": 10},
            "@another_photographer",
        ],
        "output_dir": "knowledge/source_records",
        "sync_state_path": "knowledge/source_records/x_sync_state.json",
    }
    print(json.dumps(example, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest X posts from a photographer whitelist.")
    parser.add_argument("--config", type=Path, default=Path("knowledge/source_records/x_sources.json"))
    parser.add_argument("--bearer-token-env", default="X_BEARER_TOKEN")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--print-config-example", action="store_true")
    args = parser.parse_args()

    if args.print_config_example:
        print_config_example()
        return

    try:
        summary = run(args.config, args.dry_run, args.bearer_token_env)
    except XApiError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
