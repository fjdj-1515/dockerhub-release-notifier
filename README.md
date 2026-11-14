# dockerhub-release-notifier

Docker Hub のイメージに新しいバージョン（`x.y.z` / `x.y` タグ）が出たら、Discord に通知する。詳しい仕様は [docs/SPEC.md](docs/SPEC.md)。

## セットアップ

[uv](https://docs.astral.sh/uv/) が必要。Python は uv が用意する。

```sh
git clone <this repo> /opt/dockerhub-release-notifier
cd /opt/dockerhub-release-notifier
cp .env.example .env   # DISCORD_WEBHOOK_URL を設定する
```

監視するイメージは [images.toml](images.toml) に書く。

## 実行

```sh
uv run dockerhub-release-notifier            # 確認して、新しいバージョンがあれば通知
uv run dockerhub-release-notifier --dry-run  # 通知せず内容だけ表示（記録も更新しない）
```

初めて追加したイメージは、既存のバージョンを `state.json` に記録するだけで通知しない。

cron で 1 日 1 回実行する例:

```
0 9 * * * cd /opt/dockerhub-release-notifier && $HOME/.local/bin/uv run dockerhub-release-notifier >> notifier.log 2>&1
```

## 開発

```sh
uv run pytest
```
