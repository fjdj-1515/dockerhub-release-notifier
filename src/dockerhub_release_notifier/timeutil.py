import re
from datetime import UTC, datetime

_FRACTION_RE = re.compile(r"\.(\d+)")


def parse_time(text: str) -> datetime:
    """ISO 8601 の日時を UTC の aware datetime にする。

    Docker Hub は小数秒を 9 桁で返すことがあるため、6 桁に切り詰めてから解析する。
    """
    text = _FRACTION_RE.sub(lambda m: "." + m.group(1)[:6].ljust(6, "0"), text, count=1)
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def format_time(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def now() -> datetime:
    return datetime.now(UTC)
