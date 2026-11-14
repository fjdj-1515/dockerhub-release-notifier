# dockerhub-release-notifier 仕様

Docker Hub 上の指定イメージに新しいバージョン（`x.y.z` 形式、または `x.y` 形式のタグ）が公開されたら、Discord に通知する。

## 前提

- 実行環境: 自宅 Linux サーバ、cron で 1 日 1 回実行
- 言語: Python 3.15（stable の最新。標準ライブラリのみで実装し、外部依存なし）
- 実行・Python バージョン管理: [uv](https://docs.astral.sh/uv/)
- 通知先: Discord Webhook

## プロジェクト構成（uv）

- `uv init --package` で作成した構成（`src/dockerhub_release_notifier/`）を使う。
- `pyproject.toml` に `requires-python = ">=3.15"` と、コマンド `dockerhub-release-notifier` のエントリポイントを定義する。
- `.python-version` は `3.15` とする。サーバに入っている Python のバージョンに関係なく、uv が 3.15 系の最新パッチ版を用意する。新しい stable が出たら、このファイルと `requires-python` を上げる。
- 実行時の外部依存はなし（`dependencies = []`）。開発用ツール（テストなど）は必要になったら dev 依存として追加する。
- `uv.lock` はリポジトリにコミットする。

## ファイル構成

| ファイル | 書く人 | 形式 | 内容 |
|---|---|---|---|
| `images.toml` | 人 | TOML | 監視するイメージ一覧 |
| `state.json` | プログラム | JSON | イメージごとの既知バージョン |
| `.env` または環境変数 | 人 | — | `DISCORD_WEBHOOK_URL` |

## images.toml

```toml
[[images]]
name = "traefik"            # 公式イメージは "library/" を省略可

[[images]]
name = "nginx"

[[images]]
name = "requarks/wiki"
```

- `name`（必須）: `namespace/repo`。`/` を含まなければ `library/` を補う。
- タグの判定条件は全イメージ共通（下記）。個別の設定項目は当面設けない。

## 通知対象のタグ

正規表現 `^v?(\d+)\.(\d+)(?:\.(\d+))?$` に一致するタグ（`x.y.z` または `x.y`）だけを対象とする。

| 例 | 対象か | 理由 |
|---|---|---|
| `1.31.8`, `3.3.1` | ○ | |
| `v3.7.19` | ○ | 先頭の `v` は外して `3.7.19` として扱う |
| `4.0` | 条件付き | 下記「`x.y` タグの扱い」を参照 |
| `3`, `latest`, `stable`, `mainline` | × | `x.y.z` / `x.y` 形式ではない |
| `1.31.8-alpine`, `1.30.6-perl` | × | 後ろに付加情報がある |
| `v3.7.19-nanoserver-ltsc2025` | × | 同上 |
| `3.8.0-rc.3`, `3.3.1-dev.9575873` | × | プレリリース |

- `v3.7.19` と `3.7.19` は同じバージョンとみなし、1件として扱う。
- 複数のメジャーバージョンが並行してリリースされる場合（例: traefik の 2.11.x と 3.7.x）も、それぞれ通知する。

### `x.y` タグの扱い

新しいメジャーバージョンが `x.y` 形式のタグだけで公開されることがあるため、`x.y` も対象にする。ただし `x.y` タグは通常、その系列の最新 `x.y.z` を指す別名（例: nginx の `1.31` は `1.31.8` と同じもの）として毎回更新されるため、次の条件で絞り込む。

- 同じ `x.y` 系列の `x.y.z` が 1 つでもある場合（既知のバージョン、または今回取得したタグのいずれか）、`x.y` タグは無視する。
- `x.y.z` がまだない場合に限り、`x.y` を新しいバージョンとして通知する。
- 一度通知した `x.y` は `known_versions` に記録し、二度は通知しない。
- その後 `x.y.z`（例: `4.0.0`、`4.0.1`）が出た場合は、通常どおり `x.y.z` として通知する。

例:

| 状況 | 通知 |
|---|---|
| `4.0` だけが公開された | `4.0` |
| その後 `4.0.1` が公開され、`4.0` も更新された | `4.0.1` だけ |
| `1.32` と `1.32.0` が同時に公開された | `1.32.0` だけ |

## state.json

```json
{
  "version": 1,
  "images": {
    "library/traefik": {
      "last_checked": "2026-11-14T00:00:00Z",
      "known_versions": ["2.11.63", "3.7.18", "3.7.19"]
    }
  }
}
```

- `known_versions`: これまでに確認した対象バージョンの一覧（バージョン順に並べる）。通知した `x.y` も含む。
  - 並べるときは `x.y` を `x.y.z` より前に置く（例: `4.0` → `4.0.0` → `4.0.1`）。
- 書き込みは一時ファイルに書いてから `rename` で置き換え、途中で失敗してもファイルが壊れないようにする。
- ファイルがなければ空として扱う。

## 処理の流れ

1. `images.toml` と `state.json` を読み込む。
2. イメージごとに Docker Hub API からタグを取得する。
   - `GET https://hub.docker.com/v2/repositories/{ns}/{repo}/tags?page_size=100&ordering=last_updated`
   - **初回**（`state.json` にそのイメージがない）: 全ページを取得する。
   - **2回目以降**: ページの最後のタグの `last_updated` が `last_checked` より 2 日以上前になった時点で取得を止める。上限は 10 ページ。
   - リクエストの間隔は 1 秒空ける。
3. 対象タグに絞り込み、バージョン番号に正規化する。`x.y` タグは「`x.y` タグの扱い」の条件で絞り込む。
4. `known_versions` に含まれていないものを新しいバージョンとする。
   - 古いタグが再ビルドされて `last_updated` が新しくなっても、`known_versions` に含まれていれば通知しない。
5. **初回のイメージ**: 取得したバージョンを記録するだけで、通知しない。
6. 全イメージの新しいバージョンと取得エラーを 1 通にまとめて Discord に送る。
   - 新しいバージョンもエラーもなければ、何も送らない。
7. Discord への送信に成功したら `state.json` を更新する。
   - 送信に失敗した場合は更新しない。次回の実行で同じ内容を通知し直す。

## Discord 通知

1 回の実行で 1 メッセージを送る。Embed は 1 つとし、イメージごとにフィールドを 1 つ作る。

```
🐳 Docker Hub 新バージョン

library/traefik
  2.11.64, 3.7.20
  https://hub.docker.com/_/traefik/tags

requarks/wiki
  3.3.2
  https://hub.docker.com/r/requarks/wiki/tags

⚠️ 取得失敗
  library/nginx: HTTP 503
```

- 各イメージのバージョンは昇順で並べる。
- Discord の制限（フィールド数は 25 まで、合計 6000 文字まで）を超えた場合は、メッセージを分けて送る。

## エラー処理

| 状況 | 動作 |
|---|---|
| 特定イメージの API 取得失敗（ネットワークエラー、HTTP 4xx/5xx） | 最大 3 回再試行する。それでも失敗したら、そのイメージの記録は更新せず、通知にエラーとして含める |
| HTTP 429（レート制限） | `Retry-After` に従って待ってから再試行する |
| イメージが存在しない（404） | 再試行せず、エラーとして通知する |
| `images.toml` の書式エラー | 終了コード 1 で終了し、stderr に出力する（通知はしない） |
| `DISCORD_WEBHOOK_URL` が未設定 | 終了コード 1 で終了する |
| Discord への送信失敗 | 終了コード 1 で終了し、`state.json` は更新しない |

## 実行方法

```sh
uv run dockerhub-release-notifier --config images.toml --state state.json
```

- `--config` / `--state` は省略可能で、省略時はカレントディレクトリの `images.toml` / `state.json` を使う。
- `--dry-run`: Discord には送らず、送る内容を標準出力に表示する。`state.json` も更新しない。
- ログは標準出力に出し、cron 側でファイルにリダイレクトする想定。

crontab の例（cron の `PATH` には uv が入っていないことが多いので、uv は絶対パスで指定する）:

```
0 9 * * * cd /opt/dockerhub-release-notifier && $HOME/.local/bin/uv run dockerhub-release-notifier >> notifier.log 2>&1
```

## 対象外（当面やらないこと）

- ダイジェストの追跡（同じタグのまま中身が変わった場合の通知）
- イメージごとのタグ条件の指定
- Docker Hub 以外のレジストリ（GHCR など）
