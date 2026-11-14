"""タグ名からバージョンを取り出し、新しいバージョンを判定する。"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

_TAG_RE = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")


@dataclass(frozen=True)
class Version:
    """`x.y.z` または `x.y` のバージョン。

    `patch` が None のものは `x.y` タグを表す。並べたときは同じ系列の
    `x.y.z` より前に来る（例: 4.0 < 4.0.0 < 4.0.1）。
    """

    major: int
    minor: int
    patch: int | None = None

    def __lt__(self, other: "Version") -> bool:
        return self._key() < other._key()

    def __le__(self, other: "Version") -> bool:
        return self._key() <= other._key()

    def __gt__(self, other: "Version") -> bool:
        return self._key() > other._key()

    def __ge__(self, other: "Version") -> bool:
        return self._key() >= other._key()

    def _key(self) -> tuple[int, int, int]:
        return (self.major, self.minor, -1 if self.patch is None else self.patch)

    @property
    def series(self) -> tuple[int, int]:
        return (self.major, self.minor)

    @property
    def is_full(self) -> bool:
        return self.patch is not None

    def __str__(self) -> str:
        if self.patch is None:
            return f"{self.major}.{self.minor}"
        return f"{self.major}.{self.minor}.{self.patch}"


def parse_tag(tag: str) -> Version | None:
    """対象のタグなら Version を、対象外なら None を返す。先頭の `v` は外す。"""
    m = _TAG_RE.match(tag)
    if m is None:
        return None
    major, minor, patch = m.groups()
    return Version(int(major), int(minor), None if patch is None else int(patch))


def parse_version(text: str) -> Version:
    """state.json に保存した文字列を Version に戻す。"""
    v = parse_tag(text)
    if v is None:
        raise ValueError(f"invalid version string: {text!r}")
    return v


def eligible_versions(fetched: Iterable[Version], known: Iterable[Version]) -> set[Version]:
    """取得したバージョンのうち、記録・通知の対象になるものを返す。

    `x.y.z` はすべて対象。`x.y` は、同じ系列の `x.y.z` が既知のバージョンにも
    今回取得したバージョンにもない場合だけ対象にする。
    """
    fetched = set(fetched)
    known = set(known)
    series_with_full = {v.series for v in fetched | known if v.is_full}
    return {v for v in fetched if v.is_full or v.series not in series_with_full}


def find_new_versions(fetched: Iterable[Version], known: Iterable[Version]) -> list[Version]:
    """新しく通知すべきバージョンを昇順で返す。

    同じ系列の既知の `x.y.z` よりパッチ番号が小さい `x.y.z` は、古いタグの
    再ビルドとみなして通知しない（記録には eligible_versions 側で含める）。
    """
    known = set(known)
    max_patch: dict[tuple[int, int], int] = {}
    for v in known:
        if v.patch is not None:
            max_patch[v.series] = max(max_patch.get(v.series, -1), v.patch)
    return sorted(
        v
        for v in eligible_versions(fetched, known) - known
        if v.patch is None or v.patch > max_patch.get(v.series, -1)
    )
