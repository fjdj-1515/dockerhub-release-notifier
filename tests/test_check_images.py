from datetime import UTC, datetime, timedelta

from dockerhub_release_notifier import discord, http
from dockerhub_release_notifier.cli import check_images
from dockerhub_release_notifier.config import Image
from dockerhub_release_notifier.state import ImageState, State
from dockerhub_release_notifier.versions import parse_tag

NOW = datetime(2026, 11, 14, 0, 0, tzinfo=UTC)


def V(s):
    return parse_tag(s)


def page(tags, next_url=None):
    return {
        "next": next_url,
        "results": [{"name": name, "last_updated": updated} for name, updated in tags],
    }


class FakeHub:
    """URL ごとに用意したレスポンスを返す。呼ばれた URL を記録する。"""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        for key, value in self.responses.items():
            if key in url:
                resp = value.pop(0) if isinstance(value, list) else value
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(f"unexpected url {url}")


def no_sleep(_):
    pass


def test_first_run_records_without_notifying_and_fetches_all_pages():
    hub = FakeHub(
        {
            # 先に一致したキーが使われるので、2 ページ目を先に書く
            "page=2": page([("1.31.8", "2020-01-01T00:00:00.123456789Z"), ("1.30.6", "2020-01-01T00:00:00Z")]),
            "library/nginx/tags?": page(
                [("1.31.8-alpine", "2026-11-13T00:00:00Z"), ("1.31", "2026-11-13T00:00:00Z")],
                next_url="https://hub.docker.com/v2/repositories/library/nginx/tags?page=2",
            ),
        }
    )
    image = Image("library/nginx")
    result = check_images([image], State(), hub, now=NOW, sleep=no_sleep)

    assert result.updates == []
    assert result.failures == []
    assert len(hub.calls) == 2
    assert result.state.images["library/nginx"] == ImageState(NOW, {V("1.31.8"), V("1.30.6")})


def test_incremental_run_notifies_new_and_stops_paging_at_old_tags():
    prev_checked = NOW - timedelta(days=1)
    state = State({"library/traefik": ImageState(prev_checked, {V("3.7.19"), V("2.11.63")})})
    hub = FakeHub(
        {
            "library/traefik/tags?": page(
                [
                    ("v3.7.20-nanoserver-ltsc2025", "2026-11-13T12:00:00Z"),
                    ("v3.7.20", "2026-11-13T12:00:00Z"),
                    ("3.7.20", "2026-11-13T12:00:00Z"),
                    ("v3.7", "2026-11-13T12:00:00Z"),
                    ("3.8.0-rc.3", "2026-11-13T12:00:00Z"),
                    ("v3.7.19", "2026-11-01T00:00:00Z"),
                ],
                next_url="https://example.invalid/should-not-be-called",
            ),
        }
    )
    result = check_images([Image("library/traefik")], state, hub, now=NOW, sleep=no_sleep)

    assert len(hub.calls) == 1  # 最後のタグが 2 日以上前なので次のページは取らない
    assert [(u.image.name, u.versions) for u in result.updates] == [("library/traefik", [V("3.7.20")])]
    assert result.state.images["library/traefik"] == ImageState(NOW, {V("2.11.63"), V("3.7.19"), V("3.7.20")})
    # 元の state は変更しない
    assert state.images["library/traefik"].last_checked == prev_checked


def test_failure_keeps_previous_state_and_other_images_continue():
    prev = ImageState(NOW - timedelta(days=1), {V("1.31.8")})
    state = State({"library/nginx": prev, "requarks/wiki": ImageState(NOW - timedelta(days=1), {V("3.3.1")})})
    hub = FakeHub(
        {
            "library/nginx/": http.HttpError("HTTP 503", 503),
            "requarks/wiki/": page([("3.3.2", "2026-11-13T00:00:00Z"), ("3.3.1", "2026-10-01T00:00:00Z")]),
        }
    )
    images = [Image("library/nginx"), Image("requarks/wiki")]
    result = check_images(images, state, hub, now=NOW, sleep=no_sleep)

    assert [(f.image.name, f.reason) for f in result.failures] == [("library/nginx", "HTTP 503")]
    assert result.state.images["library/nginx"] is prev
    assert [(u.image.name, u.versions) for u in result.updates] == [("requarks/wiki", [V("3.3.2")])]


def test_not_found_message():
    hub = FakeHub({"foo/bar/": http.HttpError("HTTP 404", 404)})
    result = check_images([Image("foo/bar")], State(), hub, now=NOW, sleep=no_sleep)
    assert result.failures[0].reason == "イメージが見つかりません (HTTP 404)"
    assert "foo/bar" not in result.state.images


def test_messages_built_only_when_something_happened():
    assert discord.build_messages([], []) == []

    msgs = discord.build_messages(
        [discord.Update(Image("library/traefik"), [V("3.7.20"), V("2.11.64")])],
        [discord.FetchFailure(Image("library/nginx"), "HTTP 503")],
    )
    assert len(msgs) == 1
    fields = msgs[0]["embeds"][0]["fields"]
    assert fields[0]["name"] == "library/traefik"
    assert fields[0]["value"].startswith("`2.11.64`, `3.7.20`")
    assert "https://hub.docker.com/_/traefik/tags" in fields[0]["value"]
    assert fields[1]["name"] == discord.ERROR_FIELD_NAME
    assert "`library/nginx`: HTTP 503" in fields[1]["value"]


def test_messages_split_when_too_many_fields():
    updates = [discord.Update(Image(f"ns/img{i}"), [V("1.0.0")]) for i in range(30)]
    msgs = discord.build_messages(updates, [])
    assert [len(m["embeds"][0]["fields"]) for m in msgs] == [25, 5]
    assert msgs[1]["embeds"][0]["title"].endswith("(2/2)")
