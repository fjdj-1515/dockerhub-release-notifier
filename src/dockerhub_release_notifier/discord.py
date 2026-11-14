"""Discord Webhook に送るメッセージの組み立てと送信。"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .config import Image
from .versions import Version

TITLE = "🐳 Docker Hub 新バージョン"
ERROR_FIELD_NAME = "⚠️ 取得失敗"
COLOR = 0x1D63ED

# Discord の制限
MAX_FIELDS = 25
MAX_FIELD_VALUE = 1024
MAX_EMBED_TOTAL = 6000
# タイトルや余白の分を残しておく
EMBED_BUDGET = MAX_EMBED_TOTAL - 200


@dataclass(frozen=True)
class Update:
    image: Image
    versions: Sequence[Version]
    # バージョンごとの Docker Hub への push 日時（わからなければ含めない）
    pushed_at: Mapping[Version, datetime] = field(default_factory=dict)


@dataclass(frozen=True)
class FetchFailure:
    image: Image
    reason: str


def build_messages(updates: Sequence[Update], failures: Sequence[FetchFailure]) -> list[dict[str, Any]]:
    """送るメッセージ（Webhook の JSON）の一覧を返す。何もなければ空リスト。"""
    fields = [_update_field(u) for u in updates if u.versions]
    fields += _failure_fields(failures)
    if not fields:
        return []

    chunks: list[list[dict[str, Any]]] = [[]]
    size = len(TITLE)
    for f in fields:
        f_size = len(f["name"]) + len(f["value"])
        if chunks[-1] and (len(chunks[-1]) >= MAX_FIELDS or size + f_size > EMBED_BUDGET):
            chunks.append([])
            size = len(TITLE)
        chunks[-1].append(f)
        size += f_size

    messages = []
    for i, chunk in enumerate(chunks, 1):
        title = TITLE if len(chunks) == 1 else f"{TITLE} ({i}/{len(chunks)})"
        messages.append({"embeds": [{"title": title, "color": COLOR, "fields": chunk}]})
    return messages


def _update_field(u: Update) -> dict[str, Any]:
    """1 バージョン 1 行。push 日時は Discord のタイムスタンプ書式で、見る人の
    タイムゾーンで表示される。"""
    lines = []
    for v in sorted(u.versions):
        pushed = u.pushed_at.get(v)
        if pushed is None:
            lines.append(f"`{v}`")
        else:
            # 日本語の Discord では「2026/11/14」と表示され、ホバーで時刻も見られる
            lines.append(f"`{v}` release: <t:{int(pushed.timestamp())}:d>")

    link = f"[Tags]({u.image.hub_tags_url})"
    shown: list[str] = []
    for i, line in enumerate(lines):
        rest = len(lines) - i - 1
        more = f"…ほか {rest} 件" if rest else ""
        if len("\n".join([*shown, line, more, link])) > MAX_FIELD_VALUE:
            shown.append(f"…ほか {len(lines) - i} 件")
            break
        shown.append(line)
    return {"name": u.image.name, "value": "\n".join([*shown, link]), "inline": False}


def _failure_fields(failures: Sequence[FetchFailure]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    lines: list[str] = []
    for f in failures:
        line = f"`{f.image.name}`: {f.reason}"[: MAX_FIELD_VALUE]
        if lines and len("\n".join([*lines, line])) > MAX_FIELD_VALUE:
            fields.append({"name": ERROR_FIELD_NAME, "value": "\n".join(lines), "inline": False})
            lines = []
        lines.append(line)
    if lines:
        fields.append({"name": ERROR_FIELD_NAME, "value": "\n".join(lines), "inline": False})
    return fields


_TIMESTAMP_RE = re.compile(r"<t:(-?\d+):([a-zA-Z])>")
_TIMESTAMP_FORMATS = {"d": "%Y/%m/%d", "t": "%-H:%M"}


def render_text(message: dict[str, Any]) -> str:
    """--dry-run で表示するためのテキスト表現。タイムスタンプは実行環境の
    タイムゾーンの日時に置き換える。"""
    def local_time(m: re.Match[str]) -> str:
        fmt = _TIMESTAMP_FORMATS.get(m.group(2), "%Y/%m/%d %-H:%M")
        return datetime.fromtimestamp(int(m.group(1))).astimezone().strftime(fmt)

    out = []
    for embed in message["embeds"]:
        out.append(embed["title"])
        for f in embed["fields"]:
            out.append("")
            out.append(f["name"])
            out.extend("  " + _TIMESTAMP_RE.sub(local_time, line) for line in f["value"].splitlines())
    return "\n".join(out)


def send(webhook_url: str, messages: Sequence[dict[str, Any]], post_json: Callable[[str, Any], Any]) -> None:
    for message in messages:
        post_json(webhook_url, message)
