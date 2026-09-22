"""检查仓库里所有 markdown 的相对链接是否真的存在。

CI 里以前是一段写在 workflow 里的内联 Python。逻辑本身很短，但生成类文档
（outputs/research_summary.md 会把 README 原文嵌进去）很容易把「相对仓库根目录」
写的链接搬到别的目录去，这种问题最好在本地跑测试时就能撞到，所以逻辑挪到这里，
由 pytest（tests/test_markdown_links.py）和 CI 共用一份实现。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple


ROOT = Path(__file__).resolve().parents[1]

# markdown inline link / image: [text](dest) 或 ![alt](dest)
LINK = re.compile(r"!?(?:\[[^\]]*\])\(([^)\s]+)")

# 依赖目录与生成产物目录不参与检查（.git 由 rglob 天然排除）
SKIP_DIRS = {"node_modules", ".next", ".venv", "site-packages", ".git", "__pycache__"}

EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "data:", "tel:", "#")


class BrokenLink(NamedTuple):
    source: str
    dest: str

    def __str__(self) -> str:  # pragma: no cover - 只用于报错输出
        return f"{self.source}: {self.dest}"


def iter_markdown_files(root: Path = ROOT) -> list[Path]:
    return [
        path
        for path in sorted(root.rglob("*.md"))
        if not SKIP_DIRS.intersection(path.relative_to(root).parts)
    ]


def find_broken_links(root: Path = ROOT) -> list[BrokenLink]:
    """返回所有指向仓库内不存在路径的相对链接（外链、锚点、data URI 一律跳过）。"""
    broken: list[BrokenLink] = []
    for md in iter_markdown_files(root):
        text = md.read_text(encoding="utf-8", errors="replace")
        for match in LINK.finditer(text):
            # 先去掉 #anchor 与 ?query，剩下的才是真实文件路径
            dest = match.group(1).split("#", 1)[0].split("?", 1)[0].strip()
            if not dest or dest.startswith(EXTERNAL_PREFIXES) or dest.startswith("/"):
                continue
            if not (md.parent / dest).resolve().is_file():
                broken.append(BrokenLink(str(md.relative_to(root)), match.group(1)))
    return broken


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    broken = find_broken_links(args.root.resolve())
    if broken:
        print("Broken relative markdown links:")
        for item in broken:
            print(f"  {item}")
        print(
            "\n提示：链接是相对所在的 .md 文件解析的。把仓库根目录的内容（例如 README 摘要）"
            "嵌进子目录里的文档时，目标要加上相应层数的 ../。"
        )
        return 1
    print(f"ok  {len(iter_markdown_files(args.root.resolve()))} 个 markdown 文件的相对链接全部存在")
    return 0


if __name__ == "__main__":
    sys.exit(main())
