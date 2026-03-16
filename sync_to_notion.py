import os
import re
import sys

import requests

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DB_ID = os.environ["NOTION_DB_ID"]
README_PATH = os.environ.get("README_PATH", "README.md")
GITHUB_REPOSITORY_NAME = os.environ["GITHUB_REPOSITORY_NAME"]

NOTION_API = "https://api.notion.com/v1"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

NOTION_SUPPORTED_LANGS = {
    "abap", "arduino", "bash", "basic", "c", "clojure", "coffeescript", "c++",
    "c#", "css", "dart", "diff", "docker", "elixir", "elm", "erlang", "flow",
    "fortran", "f#", "gherkin", "glsl", "go", "graphql", "groovy", "haskell",
    "html", "java", "javascript", "json", "julia", "kotlin", "latex", "less",
    "lisp", "livescript", "lua", "makefile", "markdown", "markup", "matlab",
    "mermaid", "nix", "objective-c", "ocaml", "pascal", "perl", "php",
    "plain text", "powershell", "prolog", "protobuf", "python", "r", "reason",
    "ruby", "rust", "sass", "scala", "scheme", "scss", "shell", "sql", "swift",
    "typescript", "vb.net", "verilog", "vhdl", "visual basic", "webassembly",
    "xml", "yaml", "java/c/c++/c#", "notranslate",
}

NOTION_LANG_ALIAS = {
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "sh": "shell",
    "yml": "yaml",
    "dockerfile": "docker",
    "rb": "ruby",
    "rs": "rust",
    "cs": "c#",
    "cpp": "c++",
    "objc": "objective-c",
    "tex": "latex",
    "md": "markdown",
    "ps1": "powershell",
    "xml": "xml",
}


def resolve_lang(lang_raw):
    lang_raw = lang_raw.strip().lower()
    if not lang_raw:
        return "plain text"
    if lang_raw in NOTION_SUPPORTED_LANGS:
        return lang_raw
    if lang_raw in NOTION_LANG_ALIAS:
        return NOTION_LANG_ALIAS[lang_raw]
    return "plain text"

CODE_BLOCK_MAX_CHARS = 2000


def find_page_id():
    url = f"{NOTION_API}/databases/{NOTION_DB_ID}/query"
    payload = {
        "filter": {
            "property": "GitHubリポジトリ名",
            "rich_text": {"equals": GITHUB_REPOSITORY_NAME},
        }
    }
    resp = requests.post(url, headers=HEADERS, json=payload)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if not results:
        print(f"Error: No page found for repository '{GITHUB_REPOSITORY_NAME}' in DB {NOTION_DB_ID}")
        sys.exit(1)
    return results[0]["id"]


def get_child_blocks(page_id):
    blocks = []
    url = f"{NOTION_API}/blocks/{page_id}/children"
    has_more = True
    start_cursor = None
    while has_more:
        params = {}
        if start_cursor:
            params["start_cursor"] = start_cursor
        resp = requests.get(url, headers=HEADERS, params=params)
        resp.raise_for_status()
        data = resp.json()
        blocks.extend(data.get("results", []))
        has_more = data.get("has_more", False)
        start_cursor = data.get("next_cursor")
    return blocks


def delete_blocks(blocks):
    for block in blocks:
        url = f"{NOTION_API}/blocks/{block['id']}"
        resp = requests.delete(url, headers=HEADERS)
        resp.raise_for_status()


def parse_inline(text):
    """Parse inline markdown (bold, italic, inline code) into Notion rich_text."""
    rich_text = []
    pattern = re.compile(
        r"(`[^`]+`)"
        r"|(\*\*\*[^*]+\*\*\*)"
        r"|(\*\*[^*]+\*\*)"
        r"|(\*[^*]+\*)"
    )
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            rich_text.append(_plain(text[pos:m.start()]))
        matched = m.group()
        if m.group(1):
            rich_text.append(_annotated(matched[1:-1], code=True))
        elif m.group(2):
            rich_text.append(_annotated(matched[3:-3], bold=True, italic=True))
        elif m.group(3):
            rich_text.append(_annotated(matched[2:-2], bold=True))
        elif m.group(4):
            rich_text.append(_annotated(matched[1:-1], italic=True))
        pos = m.end()
    if pos < len(text):
        rich_text.append(_plain(text[pos:]))
    return rich_text if rich_text else [_plain("")]


def _plain(content):
    return {"type": "text", "text": {"content": content}}


def _annotated(content, bold=False, italic=False, code=False):
    return {
        "type": "text",
        "text": {"content": content},
        "annotations": {
            "bold": bold,
            "italic": italic,
            "strikethrough": False,
            "underline": False,
            "code": code,
            "color": "default",
        },
    }


def markdown_to_blocks(md_text):
    lines = md_text.split("\n")
    blocks = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Code block
        if line.strip().startswith("```"):
            lang_raw = line.strip()[3:].strip()
            lang = resolve_lang(lang_raw)
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            code_content = "\n".join(code_lines)[:CODE_BLOCK_MAX_CHARS]
            blocks.append({
                "object": "block",
                "type": "code",
                "code": {
                    "rich_text": [_plain(code_content)],
                    "language": lang,
                },
            })
            i += 1
            continue

        # Empty line
        if not line.strip():
            i += 1
            continue

        # Divider
        stripped = line.strip()
        if stripped in ("---", "***", "___"):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            i += 1
            continue

        # Headings
        if stripped.startswith("### "):
            blocks.append(_heading_block("heading_3", stripped[4:]))
            i += 1
            continue
        if stripped.startswith("## "):
            blocks.append(_heading_block("heading_2", stripped[3:]))
            i += 1
            continue
        if stripped.startswith("# "):
            blocks.append(_heading_block("heading_1", stripped[2:]))
            i += 1
            continue

        # Quote
        if stripped.startswith("> "):
            blocks.append({
                "object": "block",
                "type": "quote",
                "quote": {"rich_text": parse_inline(stripped[2:])},
            })
            i += 1
            continue

        # Bulleted list
        if re.match(r"^[-*] ", stripped):
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": parse_inline(stripped[2:])},
            })
            i += 1
            continue

        # Numbered list
        m = re.match(r"^\d+\.\s+", stripped)
        if m:
            blocks.append({
                "object": "block",
                "type": "numbered_list_item",
                "numbered_list_item": {"rich_text": parse_inline(stripped[m.end():])},
            })
            i += 1
            continue

        # Paragraph (default)
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": parse_inline(stripped)},
        })
        i += 1

    return blocks


def _heading_block(heading_type, text):
    return {
        "object": "block",
        "type": heading_type,
        heading_type: {"rich_text": parse_inline(text)},
    }


def append_blocks(page_id, blocks):
    url = f"{NOTION_API}/blocks/{page_id}/children"
    for start in range(0, len(blocks), 100):
        chunk = blocks[start:start + 100]
        resp = requests.patch(url, headers=HEADERS, json={"children": chunk})
        if not resp.ok:
            print(f"Error appending blocks {start}-{start+len(chunk)}: {resp.status_code}")
            print(resp.text)
            resp.raise_for_status()


def main():
    with open(README_PATH, "r", encoding="utf-8") as f:
        md_text = f.read()

    print(f"Finding Notion page for '{GITHUB_REPOSITORY_NAME}'...")
    page_id = find_page_id()
    print(f"Found page: {page_id}")

    print("Deleting existing blocks...")
    existing_blocks = get_child_blocks(page_id)
    delete_blocks(existing_blocks)
    print(f"Deleted {len(existing_blocks)} blocks")

    print("Converting markdown to Notion blocks...")
    blocks = markdown_to_blocks(md_text)
    print(f"Generated {len(blocks)} blocks")

    print("Appending blocks to Notion page...")
    append_blocks(page_id, blocks)
    print("Sync complete!")


if __name__ == "__main__":
    main()
