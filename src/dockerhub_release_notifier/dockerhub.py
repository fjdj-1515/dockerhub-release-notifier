"""Docker Hub API からタグを取得する。"""

import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote

from .timeutil import parse_time

log = logging.getLogger(__name__)

API_BASE = "https://hub.docker.com/v2/repositories"
PAGE_SIZE = 100
REQUEST_INTERVAL = 1.0
# 匿名リクエストでは 10 ページ（page_size=100 で 1,000 件）より先を取得できない
# （11 ページ目で HTTP 403 "pagination offset too large for anonymous requests"）
MAX_PAGES = 10

FetchJson = Callable[[str], Any]


@dataclass(frozen=True)
class Tag:
    name: str
    last_updated: datetime | None


def tags_url(image_name: str) -> str:
    namespace, repo = image_name.split("/", 1)
    return (
        f"{API_BASE}/{quote(namespace)}/{quote(repo)}/tags"
        f"?page_size={PAGE_SIZE}&ordering=last_updated"
    )


def iter_tags(
    image_name: str,
    fetch_json: FetchJson,
    *,
    stop_before: datetime | None,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[Tag]:
    """更新日時の新しい順にタグを返す。

    stop_before が None なら取得できる上限まで（初回）、指定があればページ末尾の
    タグがそれより古くなった時点で止める（2 回目以降）。
    """
    url: str | None = tags_url(image_name)
    page = 0
    while url is not None and page < MAX_PAGES:
        if page > 0:
            sleep(REQUEST_INTERVAL)
        data = fetch_json(url)
        page += 1
        tags = [_to_tag(r) for r in data.get("results", [])]
        yield from tags

        if stop_before is not None and tags:
            oldest = tags[-1].last_updated
            if oldest is not None and oldest < stop_before:
                break
        url = data.get("next")
    else:
        if url is not None and stop_before is not None:
            log.warning("%s: stopped after %d pages (limit)", image_name, page)
    log.info("%s: fetched %d page(s)", image_name, page)


def _to_tag(raw: dict[str, Any]) -> Tag:
    updated = raw.get("last_updated")
    return Tag(name=raw["name"], last_updated=parse_time(updated) if updated else None)
