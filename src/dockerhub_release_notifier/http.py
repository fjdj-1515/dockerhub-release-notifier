"""標準ライブラリだけで書いた小さな HTTP クライアント（再試行つき）。"""

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from . import __version__

log = logging.getLogger(__name__)

USER_AGENT = f"dockerhub-release-notifier/{__version__}"
TIMEOUT = 30
MAX_ATTEMPTS = 3
MAX_RETRY_AFTER = 300


class HttpError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def request_json(
    method: str,
    url: str,
    body: Any = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """JSON を送受信する。429・5xx・通信エラーは最大 MAX_ATTEMPTS 回まで試す。

    4xx（429 以外）はすぐに HttpError を投げる。レスポンスが空なら None を返す。
    """
    data = None if body is None else json.dumps(body).encode()
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"

    for attempt in range(1, MAX_ATTEMPTS + 1):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                payload = resp.read()
            return json.loads(payload) if payload else None
        except urllib.error.HTTPError as e:
            status = e.code
            if status != 429 and status < 500:
                raise HttpError(f"HTTP {status}", status) from None
            if attempt == MAX_ATTEMPTS:
                raise HttpError(f"HTTP {status}", status) from None
            wait = _retry_after(e) if status == 429 else 2**attempt
            log.warning("%s %s -> HTTP %d, retrying in %.0fs", method, _short(url), status, wait)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            reason = getattr(e, "reason", e)
            if attempt == MAX_ATTEMPTS:
                raise HttpError(f"connection error: {reason}") from None
            wait = 2**attempt
            log.warning("%s %s -> %s, retrying in %.0fs", method, _short(url), reason, wait)
        sleep(wait)
    raise AssertionError("unreachable")


def _retry_after(e: urllib.error.HTTPError) -> float:
    value = e.headers.get("Retry-After") if e.headers else None
    try:
        seconds = float(value) if value is not None else 5.0
    except ValueError:
        seconds = 5.0
    return min(max(seconds, 1.0), MAX_RETRY_AFTER)


def _short(url: str) -> str:
    """ログに Webhook のトークンを出さないよう、パスの末尾を伏せる。"""
    if "/api/webhooks/" in url:
        return url.split("/api/webhooks/")[0] + "/api/webhooks/***"
    return url
