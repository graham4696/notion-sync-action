# 実装計画書：GitHub README → Notion 自動同期（Composite Action）

## 概要

GitHubリポジトリへのpushをトリガーに、`README.md` の内容をNotionの対応ページへ自動同期するGitHub Composite Actionを実装する。

複数リポジトリでの使い回しを前提とし、「どのリポジトリ → どのNotionページ」の対応付けはNotion DB上で管理する。

---

## アーキテクチャ

```
各リポジトリ (repo-A, repo-B, ...)
    │
    │  push (README.md 変更時)
    ▼
GitHub Actions
    │
    │  uses: [your-org]/notion-sync-action@main
    ▼
共通リポジトリ: notion-sync-action
    │
    │  1. NOTION_DB_IDでDBを検索
    │  2. github.repositoryでページを特定
    │  3. 既存ブロックを全削除
    │  4. MarkdownをNotionブロックに変換して追記
    ▼
Notion API
```

---

## リポジトリ構成

### 共通リポジトリ `notion-sync-action`（新規作成）

```
notion-sync-action/
├── action.yml
├── requirements.txt
└── sync_to_notion.py
```

### 各利用リポジトリ（既存リポジトリへの追加）

```
[any-repo]/
└── .github/
    └── workflows/
        └── sync-notion.yml   ← このファイルのみ追加
```

---

## 実装ファイル詳細

### 1. `action.yml`（Composite Action定義）

```yaml
name: "Sync README to Notion"
description: "Syncs README.md to a Notion page, resolved from a Notion DB by GitHub repository name"

inputs:
  notion_token:
    description: "Notion Integration Token"
    required: true
  notion_db_id:
    description: "Notion Database ID that maps GitHub repo names to pages"
    required: true
  readme_path:
    description: "Path to README.md (default: README.md)"
    required: false
    default: "README.md"
  github_repository:
    description: "GitHub repository (owner/repo format, e.g. your-org/repo-name)"
    required: true

runs:
  using: "composite"
  steps:
    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: "3.11"

    - name: Install dependencies
      shell: bash
      run: pip install -r ${{ github.action_path }}/requirements.txt

    - name: Sync to Notion
      shell: bash
      env:
        NOTION_TOKEN: ${{ inputs.notion_token }}
        NOTION_DB_ID: ${{ inputs.notion_db_id }}
        README_PATH: ${{ inputs.readme_path }}
        GITHUB_REPOSITORY_NAME: ${{ inputs.github_repository }}
      run: python ${{ github.action_path }}/sync_to_notion.py
```

### 2. `requirements.txt`

```
requests
```

### 3. `sync_to_notion.py`

#### 環境変数（入力）

| 変数名                   | 内容                                       |
| ------------------------ | ------------------------------------------ |
| `NOTION_TOKEN`           | Notion Integration Token                   |
| `NOTION_DB_ID`           | プロジェクト管理DBのID                     |
| `README_PATH`            | README.mdのパス（デフォルト: `README.md`） |
| `GITHUB_REPOSITORY_NAME` | `owner/repo` 形式のリポジトリ名            |

#### 処理フロー

```
1. README_PATH から README.md を読み込む
2. NOTION_DB_ID に対してDBクエリを実行
   - フィルタ: "GitHubリポジトリ名" プロパティ == GITHUB_REPOSITORY_NAME
3. 結果が0件 → エラー終了（sys.exit(1)）
4. 結果の results[0]["id"] をページIDとして取得
5. そのページの既存ブロックをすべて取得・削除
6. README.md の内容を Notion ブロック形式に変換
7. 変換したブロックを100件ずつ分割してページに追加
```

#### Markdown → Notion ブロック変換仕様

| Markdown                    | Notionブロックtype           |
| --------------------------- | ---------------------------- |
| `# テキスト`                | `heading_1`                  |
| `## テキスト`               | `heading_2`                  |
| `### テキスト`              | `heading_3`                  |
| ` ```lang ... ``` `         | `code`（言語マッピングあり） |
| `> テキスト`                | `quote`                      |
| `- テキスト` / `* テキスト` | `bulleted_list_item`         |
| `1. テキスト`               | `numbered_list_item`         |
| `---` / `***` / `___`       | `divider`                    |
| 空行                        | スキップ                     |
| その他                      | `paragraph`                  |

インラインの装飾（`**bold**`、`*italic*`、`` `code` ``）は `rich_text` の `annotations` で対応する。

#### 言語名マッピング（コードブロック用）

```python
NOTION_LANG_MAP = {
    "js":   "javascript",
    "ts":   "typescript",
    "py":   "python",
    "sh":   "shell",
    "bash": "shell",
    "yml":  "yaml",
    "yaml": "yaml",
    "json": "json",
    "sql":  "sql",
    "html": "html",
    "css":  "css",
    "":     "plain text",
}
```

#### エラーハンドリング

- DBクエリで対象ページが見つからない場合 → メッセージを出力して `sys.exit(1)`
- Notion APIレスポンスが200系以外 → `response.raise_for_status()` で例外
- コードブロックの内容が2000文字超の場合 → 2000文字で切り捨て（Notion API制限）

### 4. 各リポジトリ側ワークフロー `.github/workflows/sync-notion.yml`

```yaml
name: Sync README to Notion

on:
  push:
    branches:
      - main
    paths:
      - "README.md"

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Sync README to Notion
        uses: your-org/notion-sync-action@main
        with:
          notion_token: ${{ secrets.NOTION_TOKEN }}
          notion_db_id: ${{ secrets.NOTION_DB_ID }}
          github_repository: ${{ github.repository }}
          # readme_path: docs/README.md  # デフォルト以外の場合のみ指定
```

---

## Notion側の事前準備

### DBプロパティの追加

既存のプロジェクト管理DBに以下のプロパティを追加する。

| プロパティ名         | 型                    | 値の例               |
| -------------------- | --------------------- | -------------------- |
| `GitHubリポジトリ名` | テキスト（rich_text） | `your-org/repo-name` |

### Notion Integrationの設定

1. https://www.notion.so/my-integrations でIntegrationを作成
2. 必要な権限：**Read content** / **Update content** / **Insert content**
3. プロジェクト管理DBのページにIntegrationを接続（ページ右上「…」→「Connections」）

---

## GitHub Secrets の設定

### Organization Secrets（全リポジトリ共通）

| Secret名       | 値                                          |
| -------------- | ------------------------------------------- |
| `NOTION_TOKEN` | Notion Integrationトークン（`ntn_xxxx...`） |
| `NOTION_DB_ID` | プロジェクト管理DBのID（URLの末尾32文字）   |

Organization Secretsが使えない場合は、各リポジトリのRepository Secretsに同じ値を登録する。

---

## 制約・注意事項

- ページの既存ブロックは**毎回全削除**して再構築される。Notionで手動編集した内容は上書きされるため、同期対象ページはREADME.mdの内容のみを置くページとして使用すること。
- Notionの子ページ（ネストしたページ）はブロック削除対象に含まれるため、同期先ページの直下に子ページを作成しないこと。
- Markdownのテーブル・画像・HTMLタグは変換非対応（無視される）。
- コードブロックは2000文字で切り捨て（Notion API制限）。

---

## 動作確認手順

1. `notion-sync-action` リポジトリを作成し、3ファイルをpush
2. NotionのプロジェクトDBに `GitHubリポジトリ名` プロパティを追加し、テスト対象リポジトリ名を入力
3. Organization（またはRepository）Secretsに `NOTION_TOKEN` と `NOTION_DB_ID` を登録
4. テスト対象リポジトリに `.github/workflows/sync-notion.yml` を追加してpush
5. GitHub ActionsのログでSync completeが出力されることを確認
6. Notionページが更新されていることを確認
