"""把 render.py 產生的 Markdown 轉成 Jira Cloud 要的格式（ADF）。

Jira Cloud 的 API 不直接接受 Markdown。它要的是一種叫 ADF（Atlassian Document
Format）的 JSON 結構：整份文件是一個 "doc"，裡面是一個個「節點」（標題、段落、
清單、程式碼區塊）。

這裡不是通用的 Markdown 轉換器，只處理 render.py 會輸出的幾種寫法：

    # 標題 / ## 標題      → heading
    | 欄位 | 內容 | 表格   → 條列（每列變成「欄位：內容」）
    - 項目 / 1. 項目      → bulletList / orderedList（支援縮排一層的子項目）
    ```text ... ```       → codeBlock
    其他文字              → paragraph
    `行內程式碼`          → 帶 code 標記的文字

如果你改了 render.py 的排版而用到別種 Markdown 寫法，這裡不認得的內容會被當成
一般段落原樣送出，不會出錯，只是在 Jira 上不會有對應的樣式。
"""
from __future__ import annotations

import re

_LIST_ITEM_RE = re.compile(r"^(?P<indent>\s*)(?P<marker>-|\d+\.)\s+(?P<text>.*)$")
_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.*)$")
_TABLE_SEPARATOR_RE = re.compile(r"^\|\s*:?-{3,}")


# ---- 行內 -------------------------------------------------------------------

def inline(text: str) -> list[dict]:
    """把一行文字轉成 ADF 的文字節點；成對的反引號之間標成行內程式碼。"""
    nodes: list[dict] = []
    for index, part in enumerate(text.split("`")):
        if not part:
            continue                      # ADF 不接受空字串的文字節點
        node: dict = {"type": "text", "text": part}
        if index % 2 == 1:
            node["marks"] = [{"type": "code"}]
        nodes.append(node)
    return nodes


def paragraph(text: str) -> dict:
    return {"type": "paragraph", "content": inline(text)}


def heading(text: str, level: int) -> dict:
    return {"type": "heading", "attrs": {"level": level}, "content": inline(text)}


def code_block(text: str, language: str = "text") -> dict:
    node: dict = {"type": "codeBlock", "attrs": {"language": language or "text"}}
    if text:
        node["content"] = [{"type": "text", "text": text}]
    return node


def bullet_list(items: list[str]) -> dict:
    return {"type": "bulletList", "content": [_list_item(text) for text in items if text]}


def _list_item(text: str) -> dict:
    return {"type": "listItem", "content": [paragraph(text)]}


def document(nodes: list[dict]) -> dict:
    return {"type": "doc", "version": 1, "content": nodes}


# ---- 區塊 -------------------------------------------------------------------

def _table_rows_to_items(lines: list[str]) -> list[str]:
    """把 Markdown 表格的每一列變成「欄位：內容」。第一列是表頭，略過。"""
    items: list[str] = []
    body = [ln for ln in lines if not _TABLE_SEPARATOR_RE.match(ln)][1:]
    for line in body:
        cells = [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        cells = [c for c in cells if c]
        if cells:
            items.append("：".join(cells[:2]) if len(cells) >= 2 else cells[0])
    return items


def _build_list(lines: list[str]) -> list[dict]:
    """連續的清單列 → 一或多個清單節點。縮排的項目掛在上一個項目底下。"""
    nodes: list[dict] = []
    current: dict | None = None            # 目前的清單節點
    for line in lines:
        match = _LIST_ITEM_RE.match(line)
        if not match or not match.group("text").strip():
            continue
        kind = "bulletList" if match.group("marker") == "-" else "orderedList"
        text = match.group("text").strip()
        if match.group("indent") and current and current["content"]:
            parent = current["content"][-1]                 # 上一個項目
            if parent["content"][-1]["type"] != "bulletList":
                parent["content"].append({"type": "bulletList", "content": []})
            parent["content"][-1]["content"].append(_list_item(text))
            continue
        if current is None or current["type"] != kind:
            current = {"type": kind, "content": []}
            nodes.append(current)
        current["content"].append(_list_item(text))
    return nodes


def markdown_to_adf(markdown: str, skip_first_heading: bool = True) -> dict:
    """Markdown → ADF 文件。

    skip_first_heading：報告的第一行是大標題，Jira 的 Summary 欄位已經有了，
    內文裡預設不重複。
    """
    nodes: list[dict] = []
    lines = (markdown or "").splitlines()
    i = 0
    skipped_heading = not skip_first_heading
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if stripped.startswith("```"):                       # 程式碼區塊
            language = stripped[3:].strip()
            body: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            i += 1                                           # 跳過結尾的 ```
            nodes.append(code_block("\n".join(body), language))
            continue

        match = _HEADING_RE.match(stripped)
        if match:                                            # 標題
            i += 1
            if not skipped_heading and len(match.group("hashes")) == 1:
                skipped_heading = True
                continue
            if match.group("text").strip():
                nodes.append(heading(match.group("text").strip(), len(match.group("hashes"))))
            continue

        if stripped.startswith("|"):                         # 表格
            block: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i].strip())
                i += 1
            items = _table_rows_to_items(block)
            if items:
                nodes.append(bullet_list(items))
            continue

        if _LIST_ITEM_RE.match(line):                        # 清單
            block = []
            while i < len(lines) and _LIST_ITEM_RE.match(lines[i]):
                block.append(lines[i])
                i += 1
            nodes.extend(_build_list(block))
            continue

        nodes.append(paragraph(stripped))                    # 一般段落
        i += 1

    return document(nodes or [paragraph("（沒有內容）")])
