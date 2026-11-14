"""state.json の読み書き。"""

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .timeutil import format_time, parse_time
from .versions import Version, parse_version

STATE_VERSION = 1


class StateError(Exception):
    pass


@dataclass
class ImageState:
    last_checked: datetime
    known_versions: set[Version] = field(default_factory=set)


@dataclass
class State:
    images: dict[str, ImageState] = field(default_factory=dict)


def load_state(path: Path) -> State:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return State()
    except json.JSONDecodeError as e:
        raise StateError(f"invalid JSON in {path}: {e}") from None

    if raw.get("version") != STATE_VERSION:
        raise StateError(f"{path}: unsupported state version {raw.get('version')!r}")

    try:
        images = {
            name: ImageState(
                last_checked=parse_time(entry["last_checked"]),
                known_versions={parse_version(v) for v in entry["known_versions"]},
            )
            for name, entry in raw.get("images", {}).items()
        }
    except (KeyError, TypeError, ValueError) as e:
        raise StateError(f"{path}: malformed state: {e}") from None
    return State(images)


def save_state(path: Path, state: State) -> None:
    """一時ファイルに書いてから置き換え、途中で失敗しても元のファイルを壊さない。"""
    raw = {
        "version": STATE_VERSION,
        "images": {
            name: {
                "last_checked": format_time(s.last_checked),
                "known_versions": [str(v) for v in sorted(s.known_versions)],
            }
            for name, s in sorted(state.images.items())
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
