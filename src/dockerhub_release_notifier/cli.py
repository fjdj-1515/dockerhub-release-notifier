"""コマンドラインの入口と、1 回分の処理の流れ。"""

import argparse
import logging
import os
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any

from . import discord, http
from .config import ConfigError, Image, load_dotenv, load_images
from .discord import FetchFailure, Update
from .dockerhub import REQUEST_INTERVAL, iter_tags
from .state import ImageState, State, StateError, load_state, save_state
from .timeutil import now as utc_now
from .versions import eligible_versions, find_new_versions, parse_tag

log = logging.getLogger("dockerhub_release_notifier")

WEBHOOK_ENV = "DISCORD_WEBHOOK_URL"
# 前回チェック時刻よりこれだけ古いタグまで遡って取得する
LOOKBACK_MARGIN = timedelta(days=2)


@dataclass
class RunResult:
    updates: list[Update] = field(default_factory=list)
    failures: list[FetchFailure] = field(default_factory=list)
    state: State = field(default_factory=State)


def check_images(
    images: Sequence[Image],
    state: State,
    fetch_json: Callable[[str], Any],
    *,
    now: datetime,
    sleep: Callable[[float], None] = time.sleep,
) -> RunResult:
    """全イメージを確認し、通知内容と更新後の状態を返す（state 自体は変更しない）。"""
    result = RunResult(state=State(dict(state.images)))

    for i, image in enumerate(images):
        if i > 0:
            sleep(REQUEST_INTERVAL)
        prev = state.images.get(image.name)
        stop_before = None if prev is None else prev.last_checked - LOOKBACK_MARGIN

        try:
            tags = list(iter_tags(image.name, fetch_json, stop_before=stop_before, sleep=sleep))
        except http.HttpError as e:
            reason = "イメージが見つかりません (HTTP 404)" if e.status == 404 else str(e)
            log.error("%s: %s", image.name, reason)
            result.failures.append(FetchFailure(image, reason))
            continue
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            log.error("%s: unexpected API response: %r", image.name, e)
            result.failures.append(FetchFailure(image, "想定外のレスポンス"))
            continue

        fetched = {v for t in tags if (v := parse_tag(t.name)) is not None}

        if prev is None:
            known = eligible_versions(fetched, set())
            log.info("%s: first run, recorded %d version(s) without notifying", image.name, len(known))
            result.state.images[image.name] = ImageState(now, known)
            continue

        new = find_new_versions(fetched, prev.known_versions)
        if new:
            log.info("%s: new version(s): %s", image.name, ", ".join(map(str, new)))
            result.updates.append(Update(image, new))
        else:
            log.info("%s: no new versions", image.name)
        known = prev.known_versions | eligible_versions(fetched, prev.known_versions)
        result.state.images[image.name] = ImageState(now, known)

    return result


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="dockerhub-release-notifier",
        description="Docker Hub のイメージに新しいバージョンが出たら Discord に通知する",
    )
    p.add_argument("--config", type=Path, default=Path("images.toml"), help="監視するイメージの一覧 (default: images.toml)")
    p.add_argument("--state", type=Path, default=Path("state.json"), help="記録ファイル (default: state.json)")
    p.add_argument("--env-file", type=Path, default=Path(".env"), help="環境変数ファイル (default: .env)")
    p.add_argument("--dry-run", action="store_true", help="Discord に送らず内容を表示し、記録も更新しない")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    load_dotenv(args.env_file)
    webhook_url = os.environ.get(WEBHOOK_ENV, "").strip()
    if not webhook_url and not args.dry_run:
        print(f"error: {WEBHOOK_ENV} is not set", file=sys.stderr)
        return 1

    try:
        images = load_images(args.config)
        state = load_state(args.state)
    except (ConfigError, StateError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    fetch_json = partial(http.request_json, "GET")
    result = check_images(images, state, fetch_json, now=utc_now())
    messages = discord.build_messages(result.updates, result.failures)

    if args.dry_run:
        if messages:
            print("\n\n".join(discord.render_text(m) for m in messages))
        else:
            print("(通知なし)")
        return 0

    if messages:
        try:
            discord.send(webhook_url, messages, partial(http.request_json, "POST"))
        except http.HttpError as e:
            log.error("failed to send Discord notification: %s (state not updated)", e)
            return 1
        log.info("sent %d Discord message(s)", len(messages))
    else:
        log.info("nothing to notify")

    save_state(args.state, result.state)
    return 0
