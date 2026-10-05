"""极简 Markdown → HTML（够用就好，不引第三方库）。

大模型的输出（会议纪要、问答）是 Markdown，而界面上是 QTextBrowser，
原先只是 `html.escape` + 换行，于是 ``## 标题``、``**加粗**``、``| 表格 |``
都会原样显示出来，纪要很丑。这里只支持我们提示词里用到的那几种子集：

* ``## 标题`` / ``### 小标题``
* ``**加粗**``
* ``- 项目`` / ``· 项目`` 无序列表
* ``1. 项目`` 有序列表
* ``| a | b |`` 表格（自动跳过 ``|---|---|`` 分隔行）
* 空行分段

安全性：先做 HTML 转义，再套标签，因此模型输出的任何 HTML 都不会被当标签执行。
"""
from __future__ import annotations

import html
import re

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_TABLE_SEP = re.compile(r"^\|[\s:\-|]+\|$")


def _inline(text: str) -> str:
    """行内格式（输入必须已完成 HTML 转义）。"""
    return _BOLD.sub(r"<b>\1</b>", text)


def _is_table_row(line: str) -> bool:
    return line.startswith("|") and line.count("|") >= 2


def _cells(line: str) -> list[str]:
    parts = line.strip().strip("|").split("|")
    return [p.strip() for p in parts]


def to_html(text: str, palette: dict) -> str:
    """把 Markdown 子集转成 HTML 片段（颜色取自主题 palette）。"""
    p = palette
    lines = (text or "").replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = html.escape(raw).rstrip()
        stripped = raw.strip()

        # 表格：连续的 | 行合并成一个 <table>
        if _is_table_row(stripped):
            rows: list[list[str]] = []
            while i < len(lines) and _is_table_row(lines[i].strip()):
                if not _TABLE_SEP.match(lines[i].strip()):
                    rows.append([html.escape(c) for c in _cells(lines[i])])
                i += 1
            if rows:
                head, *body = rows
                out.append(
                    f'<table cellspacing="0" cellpadding="5" width="100%" '
                    f'style="border-collapse:collapse;margin:6px 0;">'
                    f'<tr>' + "".join(
                        f'<td style="border:1px solid {p["card_border"]};'
                        f'background:{p["surface_2"]};font-weight:700;'
                        f'color:{p["text"]};">{c}</td>' for c in head) + '</tr>'
                    + "".join(
                        '<tr>' + "".join(
                            f'<td style="border:1px solid {p["card_border"]};'
                            f'color:{p["text"]};">{c}</td>' for c in r) + '</tr>'
                        for r in body)
                    + '</table>')
            continue

        if not stripped:
            out.append('<div style="height:6px;"></div>')
        elif stripped.startswith("### "):
            out.append(f'<div style="color:{p["accent"]};font-weight:700;'
                       f'margin:8px 0 3px 0;">{_inline(line.replace("###", "", 1).strip())}</div>')
        elif stripped.startswith("## "):
            out.append(f'<div style="color:{p["text"]};font-weight:700;'
                       f'font-size:1.06em;margin:9px 0 4px 0;">'
                       f'{_inline(line.replace("##", "", 1).strip())}</div>')
        elif stripped.startswith("# "):
            out.append(f'<div style="color:{p["text"]};font-weight:700;'
                       f'font-size:1.1em;margin:10px 0 4px 0;">'
                       f'{_inline(line.replace("#", "", 1).strip())}</div>')
        elif stripped[:2] in ("- ", "* ") or stripped.startswith(("· ", "• ")):
            out.append(f'<div style="margin:1px 0 1px 10px;color:{p["text"]};">'
                       f'• {_inline(line[2:].strip() if stripped[:2] in ("- ", "* ") else stripped[1:].strip())}</div>')
        elif re.match(r"^\d+\.\s", stripped):
            num, _, rest = stripped.partition(".")
            out.append(f'<div style="margin:1px 0 1px 10px;color:{p["text"]};">'
                       f'{num}. {_inline(html.escape(rest.strip()))}</div>')
        else:
            out.append(f'<div style="color:{p["text"]};margin:2px 0;">{_inline(line)}</div>')
        i += 1
    return "".join(out)
