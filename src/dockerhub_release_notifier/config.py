"""images.toml と環境変数の読み込み。"""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Image:
    name: str  # 常に "namespace/repo" の形

    @property
    def hub_tags_url(self) -> str:
        namespace, repo = self.name.split("/", 1)
        if namespace == "library":
            return f"https://hub.docker.com/_/{repo}/tags"
        return f"https://hub.docker.com/r/{self.name}/tags"


def normalize_image_name(name: str) -> str:
    name = name.strip()
    if not name or name.count("/") > 1 or name.startswith("/") or name.endswith("/"):
        raise ConfigError(f"invalid image name: {name!r}")
    return name if "/" in name else f"library/{name}"


def load_images(path: Path) -> list[Image]:
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML in {path}: {e}") from None

    entries = data.get("images")
    if not isinstance(entries, list) or not entries:
        raise ConfigError(f"{path}: at least one [[images]] entry is required")

    images: list[Image] = []
    seen: set[str] = set()
    for i, entry in enumerate(entries, 1):
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise ConfigError(f"{path}: images #{i} must have a string 'name'")
        name = normalize_image_name(entry["name"])
        if name in seen:
            raise ConfigError(f"{path}: duplicate image {name!r}")
        seen.add(name)
        images.append(Image(name))
    return images


def load_dotenv(path: Path) -> None:
    """KEY=VALUE 形式の .env を読み、未設定の環境変数だけを埋める。"""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key, value)
