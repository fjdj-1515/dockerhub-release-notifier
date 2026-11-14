import json
import os
from datetime import UTC, datetime

import pytest

from dockerhub_release_notifier.config import ConfigError, Image, load_dotenv, load_images
from dockerhub_release_notifier.state import ImageState, State, load_state, save_state
from dockerhub_release_notifier.versions import parse_tag


def test_load_images_normalizes_official_names(tmp_path):
    p = tmp_path / "images.toml"
    p.write_text('[[images]]\nname = "nginx"\n\n[[images]]\nname = "requarks/wiki"\n')
    assert load_images(p) == [Image("library/nginx"), Image("requarks/wiki")]


@pytest.mark.parametrize(
    "content",
    [
        "",
        "[[images]]\nfoo = 1\n",
        '[[images]]\nname = "a/b/c"\n',
        '[[images]]\nname = "nginx"\n[[images]]\nname = "library/nginx"\n',
        "not = [toml",
    ],
)
def test_load_images_errors(tmp_path, content):
    p = tmp_path / "images.toml"
    p.write_text(content)
    with pytest.raises(ConfigError):
        load_images(p)


def test_hub_tags_url():
    assert Image("library/nginx").hub_tags_url == "https://hub.docker.com/_/nginx/tags"
    assert Image("requarks/wiki").hub_tags_url == "https://hub.docker.com/r/requarks/wiki/tags"


def test_state_roundtrip_and_sorted_output(tmp_path):
    p = tmp_path / "state.json"
    assert load_state(p) == State()

    checked = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
    versions = {parse_tag(s) for s in ["4.0.1", "4.0", "3.10.0", "3.9.1"]}
    save_state(p, State({"library/traefik": ImageState(checked, versions)}))

    raw = json.loads(p.read_text())
    assert raw == {
        "version": 1,
        "images": {
            "library/traefik": {
                "last_checked": "2026-11-14T09:00:00Z",
                "known_versions": ["3.9.1", "3.10.0", "4.0", "4.0.1"],
            }
        },
    }
    assert load_state(p) == State({"library/traefik": ImageState(checked, versions)})
    assert [f.name for f in tmp_path.iterdir()] == ["state.json"]  # 一時ファイルが残らない


def test_load_dotenv_does_not_override(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text('# comment\nexport FOO_A="hello"\nFOO_B=world\n')
    monkeypatch.delenv("FOO_A", raising=False)
    monkeypatch.setenv("FOO_B", "keep")
    load_dotenv(p)
    assert os.environ["FOO_A"] == "hello"
    assert os.environ["FOO_B"] == "keep"
    monkeypatch.delenv("FOO_A")
