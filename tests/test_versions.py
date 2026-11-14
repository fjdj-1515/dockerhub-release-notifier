import pytest

from dockerhub_release_notifier.versions import (
    Version,
    eligible_versions,
    find_new_versions,
    parse_tag,
)


def V(s: str) -> Version:
    v = parse_tag(s)
    assert v is not None
    return v


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("1.31.8", Version(1, 31, 8)),
        ("v3.7.19", Version(3, 7, 19)),
        ("4.0", Version(4, 0)),
        ("v4.0", Version(4, 0)),
        ("3", None),
        ("latest", None),
        ("stable", None),
        ("1.31.8-alpine", None),
        ("1.30.6-perl", None),
        ("v3.7.19-nanoserver-ltsc2025", None),
        ("3.8.0-rc.3", None),
        ("3.3.1-dev.9575873", None),
        ("1.2.3.4", None),
        ("mimolette", None),
    ],
)
def test_parse_tag(tag, expected):
    assert parse_tag(tag) == expected


def test_v_prefix_is_same_version():
    assert V("v3.7.19") == V("3.7.19")
    assert len({V("v3.7.19"), V("3.7.19")}) == 1


def test_ordering_puts_xy_before_xyz():
    assert sorted([V("4.0.1"), V("4.0.0"), V("4.0"), V("3.9.9")]) == [
        V("3.9.9"),
        V("4.0"),
        V("4.0.0"),
        V("4.0.1"),
    ]
    assert str(V("4.0")) == "4.0"
    assert str(V("v4.0.1")) == "4.0.1"


def test_new_full_versions():
    known = {V("2.11.63"), V("3.7.19")}
    fetched = {V("2.11.63"), V("2.11.64"), V("3.7.19"), V("3.7.20")}
    assert find_new_versions(fetched, known) == [V("2.11.64"), V("3.7.20")]


def test_xy_only_release_is_notified():
    known = {V("3.7.19")}
    assert find_new_versions({V("4.0"), V("3.7.19")}, known) == [V("4.0")]


def test_xy_already_notified_is_not_repeated():
    known = {V("3.7.19"), V("4.0")}
    assert find_new_versions({V("4.0")}, known) == []


def test_xyz_after_xy_notifies_only_xyz():
    known = {V("3.7.19"), V("4.0")}
    assert find_new_versions({V("4.0"), V("4.0.1")}, known) == [V("4.0.1")]


def test_xy_and_xyz_together_notifies_only_xyz():
    known = {V("1.31.8")}
    assert find_new_versions({V("1.32"), V("1.32.0")}, known) == [V("1.32.0")]


def test_floating_xy_alias_is_ignored_when_series_known():
    # nginx の 1.31 は 1.31.8 の別名として何度も更新される
    known = {V("1.31.8")}
    assert find_new_versions({V("1.31")}, known) == []


def test_rebuilt_old_patch_is_not_notified():
    # 初回の 1,000 件に入らなかった古いタグが再ビルドされて上位に出てきた場合
    known = {V("2.11.63"), V("3.7.19")}
    fetched = {V("2.11.10"), V("3.7.19"), V("3.7.20")}
    assert find_new_versions(fetched, known) == [V("3.7.20")]
    assert V("2.11.10") in eligible_versions(fetched, known)


def test_eligible_for_baseline():
    fetched = {V("1.31"), V("1.31.8"), V("4.0")}
    assert eligible_versions(fetched, set()) == {V("1.31.8"), V("4.0")}
