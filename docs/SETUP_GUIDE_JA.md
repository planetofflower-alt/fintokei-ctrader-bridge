# セットアップガイド（初心者向け）

このブリッジを実際に動かすまでの手順を、順番に説明します。

## 全体の流れ

```
① cTraderでAPI認証情報を発行（あなた：10分）
② DevinのSecretsに登録（あなた：5分）
③ Devin組織にMCPサーバーを登録（Devinが実行済み）
④ スマホ/PCから「相場を分析して」→ AIが考察 → 指値・TP/SL・ロットを提案
⑤ あなたが「発注して」と承認 → 発注実行
```

## ① cTrader Open API の認証情報を発行する

**まずはデモ口座でやってください。**

1. cTrader ID でログインできるサイト https://openapi.ctrader.com/ を開く
   （公式案内: https://help.ctrader.com/open-api/creating-new-app/ ）
2. 「Applications」→ 新しいアプリを作成
   - アプリ名は自由（例: `my-devin-bridge`）
   - Redirect URI は `http://localhost` など仮のものでOK
3. アプリができたら **Client ID** と **Client Secret** が表示される
   → これが `CTRADER_CLIENT_ID` / `CTRADER_CLIENT_SECRET`
4. アカウントのアクセストークンを発行する
   （cTraderアプリの設定画面、または openapi サイト上の案内に従う）
   → これが `CTRADER_ACCESS_TOKEN`
5. 発注したい口座（まずは **デモ口座**）の口座番号を控える
   → これが `CTRADER_ACCOUNT_ID`

## ② DevinのSecretsに登録する

1. https://app.devin.ai/settings/secrets を開く
2. 以下を1つずつ登録（Organizationスコープで）:

| Secret名 | 中身 |
|---|---|
| `CTRADER_CLIENT_ID` | ①の Client ID |
| `CTRADER_CLIENT_SECRET` | ①の Client Secret |
| `CTRADER_ACCESS_TOKEN` | ①の Access Token |
| `CTRADER_ACCOUNT_ID` | ①の口座番号（数字のみ） |
| `CTRADER_HOST` | `demo` |

オプション:
- `CTRADER_MAX_LOTS` … 発注ロットの上限（未設定なら `0.1`）
- `CTRADER_ALLOW_LIVE` … 本番口座で動かす時だけ `true`（**デモで十分に試してから**）

## ③ MCPサーバーの登録（済み）

Devin組織にカスタムMCP「ctrader-bridge」として登録済みです。
セッション開始時にこのリポジトリから自動インストールされます。

## ④ 使い方（スマホでも同じ）

1. https://app.devin.ai を開いてセッション開始（スマホはSafari→「ホーム画面に追加」が便利）
2. 例: 「XAUUSDのH1足を見て相場考察して」
   → Devinが `get_quote` / `get_candles` で最新データを取得して考察
3. 「ロングの指値案を出して」
   → Devinが `preview_limit_order` で案を提示（指値・TP/SL・ロット・根拠）
4. 納得したら「この内容で発注して」
   → Devinが `place_limit_order(confirm=true)` を呼んで発注
5. 未約定の確認や取消は「注文一覧を見せて」「order_id 123をキャンセルして」

## 安全の仕組み（何が起きても大丈夫な設計）

- **成行注文は存在しない** — コード上に機能自体がありません
- **TP/SLなしは100%拒否** — サーバー側で強制
- **ロット上限超えは拒否** — `CTRADER_MAX_LOTS` で制御
- **`confirm=true` がないと発注しない** — AIが勝手に発注することはありません
- **live接続には `CTRADER_ALLOW_LIVE=true` が必要** — 設定しない限りdemo固定

## トラブル時

- 「not_connected」と出る → Secretsの4つが揃っているか確認
- 「unknown symbol」と出る → 口座の取扱シンボル名を `list_symbols` で確認
- 発注が拒否される → 拒否理由がJSONの `reason` に書かれています

## 本番（live口座）に進む前のチェックリスト

- [ ] デモ口座で「考察→指値→承認→発注→キャンセル」まで一通り動いた
- [ ] `CTRADER_MAX_LOTS` を自分の許容範囲に設定した
- [ ] Fintokeiのプラン/大会ルールでこの形（自作の発注補助ツール）が許可されているか確認した
- [ ] `CTRADER_HOST=live` + `CTRADER_ALLOW_LIVE=true` を設定（両方必要）
