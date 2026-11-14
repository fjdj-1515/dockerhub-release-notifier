"""Discord Webhook に送るメッセージの組み立てと送信。"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
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
    versions = ", ".join(f"`{v}`" for v in sorted(u.versions))
    link = f"\n[Tags]({u.image.hub_tags_url})"
    room = MAX_FIELD_VALUE - len(link)
    if len(versions) > room:
        versions = versions[: room - 1] + "…"
    return {"name": u.image.name, "value": versions + link, "inline": False}


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


def render_text(message: dict[str, Any]) -> str:
    """--dry-run で表示するためのテキスト表現。"""
    out = []
    for embed in message["embeds"]:
        out.append(embed["title"])
        for f in embed["fields"]:
            out.append("")
            out.append(f["name"])
            out.extend("  " + line for line in f["value"].splitlines())
    return "\n".join(out)


def send(webhook_url: str, messages: Sequence[dict[str, Any]], post_json: Callable[[str, Any], Any]) -> None:
    for message in messages:
        post_json(webhook_url, message)
