# fintokei-ctrader-bridge

cTrader アカウントと Devin をつなぐ **MCP ブリッジサーバー**です。
相場データの取得と、**人間の承認付きの指値注文**だけを提供します。

## 安全設計（このサーバーの約束）

- **指値注文のみ**。成行注文の機能はコード上に一切存在しません。
- **TP/SL 必須**。stop_loss と take_profit なしの注文は必ず拒否されます。
- **ロット上限**。`CTRADER_MAX_LOTS`（デフォルト 0.1 lot）を超える注文はサーバー側で拒否。
- **承認フラグ必須**。`confirm=true` がないと発注されません。流れは「AI が指値・TP/SL・ロットを提案 → あなたが承認 → confirm=true で発注」。
- **認証情報は環境変数のみ**。この repo に秘密情報は一切書きません。
- **デモ優先**。`CTRADER_HOST=live` を使うには `CTRADER_ALLOW_LIVE=true` の明示が必要です。

## 提供ツール

| ツール | 種別 | 内容 |
|---|---|---|
| `get_account_status` | 読み取り | ポジション・未約定注文の一覧 |
| `list_symbols` | 読み取り | 取扱シンボル一覧（フィルタ可） |
| `get_quote` | 読み取り | 最新 bid/ask |
| `get_candles` | 読み取り | OHLC ローソク足（M1〜MN1） |
| `preview_limit_order` | 検証のみ | 発注内容のバリデーション＋プレビュー（発注しない） |
| `place_limit_order` | 発注 | 指値注文（上記ガード全適用） |
| `cancel_order` | 発注 | 未約定注文のキャンセル |

## セットアップ

### 1. cTrader Open API の認証情報を発行（あなたの作業）

1. https://help.ctrader.com/open-api/creating-new-app/ でアプリを作成
   → `CLIENT_ID` / `CLIENT_SECRET` を取得
2. アカウントのアクセストークンを発行 → `ACCESS_TOKEN`
3. cTrader の口座番号 → `ACCOUNT_ID`

**まずはデモ口座で発行してください。**

### 2. 環境変数を設定

```bash
export CTRADER_CLIENT_ID=...
export CTRADER_CLIENT_SECRET=...
export CTRADER_ACCESS_TOKEN=...
export CTRADER_ACCOUNT_ID=...
export CTRADER_HOST=demo           # live にするには下のフラグも必要
# export CTRADER_ALLOW_LIVE=true   # 本番口座で動かす時だけ
# export CTRADER_MAX_LOTS=0.1      # ロット上限（デフォルト 0.1）
```

ローカル実行なら repo 直下の `.env` でも読み込めます（`.env` は gitignore 済み）。

### 3. 起動

```bash
pip install .
python -m ctrader_bridge
```

STDIO 型の MCP サーバーとして起動します。

## セットアップの詳しい手順

→ [docs/SETUP_GUIDE_JA.md](docs/SETUP_GUIDE_JA.md)（認証情報の発行からDevin登録・使い方まで、初心者向けに順番で解説）

## Devin への接続（B案: セッション内 STDIO）

Devin の組織設定にカスタム MCP サーバーとして登録します。
認証情報は Devin の Secrets（`CTRADER_*`）に保存すれば、セッション内の
プロセスが環境変数として引き継ぎます。

## 使い方の流れ

1. スマホまたは PC から Devin に「XAUUSD の相場を分析して」
2. Devin が `get_quote` / `get_candles` でデータ取得 → 考察
3. Devin が `preview_limit_order` で指値・TP/SL・ロットの案を提示
4. あなたが「発注して」と承認
5. Devin が `place_limit_order(confirm=true)` で発注

## 免責

- 発注は自己責任で。必ずデモ口座で動作確認してから本番に進んでください。
- Fintokei のルール（プラン・大会ごとの EA/自動化制限）は利用者側で確認してください。
