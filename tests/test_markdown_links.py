from scripts.check_markdown_links import ROOT, find_broken_links


def test_relative_markdown_links_resolve():
    """仓库里的相对链接必须真的存在。

    生成类文档最容易踩：outputs/research_summary.md 会把 README 原文嵌进来，
    README 里的链接是相对仓库根目录写的，换到 outputs/ 下就全断了。
    以前这条检查只写在 .github/workflows/ci.yml 里，本地跑 pytest 看不到，
    所以逻辑挪进了 scripts/check_markdown_links.py，CI 和测试共用一份实现。
    """
    assert not find_broken_links(ROOT)
