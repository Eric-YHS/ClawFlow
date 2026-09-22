from __future__ import annotations

import json
import re
import statistics
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from clawflow.core.schema import ToolResult
from clawflow.tools.base import BaseTool, ToolContext
from clawflow.tools.file_tools import safe_path


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


_LINK = re.compile(r"(!?\[[^\]]*]\()([^)\s]+)(\))")


def _rebase_relative_links(markdown: str, root: Path, depth: int = 1) -> str:
    """把相对仓库根目录写的 markdown 链接改成相对生成文档所在的目录。

    项目摘要里直接嵌了 README 原文，README 里的图片路径是相对仓库根目录的
    （docs/assets/...）。同样的文字写进 outputs/research_summary.md 后，这些链接
    指向的就是不存在的 outputs/docs/...，CI 的 markdown 链接检查会报错。
    只改「相对根目录确实存在」的目标，已经是 ../ 或外链的不动。
    """
    prefix = "../" * depth

    def rewrite(match: re.Match[str]) -> str:
        dest = match.group(2)
        if dest.startswith(("http://", "https://", "mailto:", "data:", "#", "/", "../", "./", prefix)):
            return match.group(0)
        if not (root / dest.split("#", 1)[0]).exists():
            return match.group(0)
        return f"{match.group(1)}{prefix}{dest}{match.group(3)}"

    return _LINK.sub(rewrite, markdown)


def _workspace_overview(root: Path, max_files: int = 300) -> dict[str, Any]:
    ignore = {".git", ".venv", "__pycache__", ".pytest_cache", "node_modules"}
    files: list[str] = []
    suffix_count: dict[str, int] = {}
    for path in root.rglob("*"):
        if any(part in ignore for part in path.parts):
            continue
        if path.is_file():
            rel = str(path.relative_to(root))
            files.append(rel)
            suffix = path.suffix or "[no_ext]"
            suffix_count[suffix] = suffix_count.get(suffix, 0) + 1
            if len(files) >= max_files:
                break
    return {"files": files, "file_count": len(files), "suffix_count": suffix_count}


class CreateTodoTool(BaseTool):
    name = "create_todo"
    description = "Generate a TODO markdown file from task context and current workspace gaps."
    risk_level = "low"

    def run(self, args: dict, context: ToolContext) -> ToolResult:
        output = safe_path(context.settings.root_dir, args.get("path", "outputs/TODO.md"))
        overview = _workspace_overview(context.settings.root_dir)
        missing = []
        for required in ["README.md", "docs/technical_report.md", "slides/ClawFlow_presentation.pptx", "tests"]:
            if not (context.settings.root_dir / required).exists():
                missing.append(required)
        lines = [
            "# ClawFlow TODO",
            "",
            f"Source task: {args.get('task', context.user_input)}",
            "",
            "## Infrastructure checks",
        ]
        lines += [f"- [ ] Fill or verify `{item}`" for item in missing] or ["- [x] Core project packaging files detected"]
        lines += [
            "",
            "## Next engineering work",
            "- [ ] Expand API examples and SDK snippets",
            "- [ ] Add production vector store adapter",
            "- [ ] Add cloud deployment profile",
            "",
            f"Workspace file sample: {', '.join(overview['files'][:20])}",
        ]
        _write(output, "\n".join(lines) + "\n")
        return ToolResult(ok=True, data={"path": str(output), "missing": missing}, artifacts=[str(output)])


class CreateMarkdownReportTool(BaseTool):
    name = "create_markdown_report"
    description = "Write a markdown report with caller-provided content."
    risk_level = "low"
    input_schema = {"path": "output path", "title": "title", "content": "markdown"}

    def run(self, args: dict, context: ToolContext) -> ToolResult:
        path = safe_path(context.settings.root_dir, args.get("path", "outputs/report.md"))
        title = args.get("title", "ClawFlow Report")
        content = str(args.get("content", ""))
        _write(path, f"# {title}\n\n{content}\n")
        return ToolResult(ok=True, data={"path": str(path)}, artifacts=[str(path)])


class GenerateDailyPlanTool(BaseTool):
    name = "generate_daily_plan"
    description = "Generate a data-backed daily learning plan and persist it to outputs/daily_plan.md."
    risk_level = "low"

    def run(self, args: dict, context: ToolContext) -> ToolResult:
        tomorrow = date.today() + timedelta(days=1)
        task = str(args.get("task", context.user_input))
        memory_hits = context.memory.search_memory(task, limit=5)
        content = [
            "# Daily Plan",
            "",
            f"Date: {tomorrow.isoformat()}",
            f"Task source: {task}",
            "",
            "## Focus blocks",
            "- 09:00-10:30 Review Agent Runtime architecture and trace lifecycle.",
            "- 10:45-12:00 Run ClawFlow applications and inspect checkpoints.",
            "- 14:00-15:30 Improve technical report and PPT screenshots.",
            "- 16:00-17:00 Write reflection notes into Memory Layer.",
            "",
            "## Memory signals",
        ]
        if memory_hits:
            content += [f"- Memory #{hit['id']}: {hit['text'][:120]}" for hit in memory_hits]
        else:
            content.append("- No previous matching memory; this plan creates the first long-term memory entry.")
        path = safe_path(context.settings.root_dir, args.get("path", "outputs/daily_plan.md"))
        _write(path, "\n".join(content) + "\n")
        memory_id = context.memory.add_memory(
            f"Daily learning plan for {tomorrow.isoformat()}: {task}",
            {"type": "daily_plan", "path": str(path), "run_id": context.run_id},
        )
        return ToolResult(ok=True, data={"path": str(path), "memory_id": memory_id}, artifacts=[str(path)])


class GenerateProjectSummaryTool(BaseTool):
    name = "generate_project_summary"
    description = "Analyze the live workspace and generate research summary, report outline, and TODO artifacts."
    risk_level = "low"

    def run(self, args: dict, context: ToolContext) -> ToolResult:
        root = context.settings.root_dir
        overview = _workspace_overview(root, max_files=500)
        readme = root / "README.md"
        readme_text = readme.read_text(encoding="utf-8", errors="ignore")[:2500] if readme.exists() else ""
        # 摘要写在 outputs/ 下，嵌进来的 README 片段要按这个目录重算相对链接
        readme_text = _rebase_relative_links(readme_text, root=root)
        source_dirs = [p for p in ["clawflow", "applications", "docs", "scripts", "tests"] if (root / p).exists()]
        summary = [
            "# Research Summary",
            "",
            "ClawFlow is structured as a lightweight Agent Runtime / AgentOS infrastructure prototype.",
            f"The current workspace contains {overview['file_count']} sampled files across {', '.join(source_dirs) or 'no source directories yet'}.",
            "",
            "## File type distribution",
        ]
        for suffix, count in sorted(overview["suffix_count"].items(), key=lambda item: (-item[1], item[0]))[:12]:
            summary.append(f"- `{suffix}`: {count}")
        summary += [
            "",
            "## README signal",
            readme_text[:1200] if readme_text else "README.md is not present yet; generation pipeline should create it.",
            "",
            "## Framework capability mapping",
            "- Runtime: planner, executor, tool calling, checkpoint, resume.",
            "- Governance: risk-level policy, approval events, audit log.",
            "- Observability: run table, structured trace events, replay export.",
            "- Applications: downstream tasks must use the unified Runtime instead of isolated demo scripts.",
        ]
        outline = [
            "# Technical Report Outline",
            "",
            "1. 摘要",
            "2. 项目背景与意义：从 Chatbot 到 AgentOS",
            "3. 总体架构：Agent Runtime、Gateway、Memory、Trace、Governance",
            "4. AgentOS Kernel 与状态迁移模型",
            "5. Workflow Orchestration、Checkpoint & Resume",
            "6. Tool Sandbox 与 Permission Governance",
            "7. Memory Layer、RAG、Plugin Registry",
            "8. Example Applications 的统一 Runtime 验证",
            "9. Benchmark、截图与可复现实验",
            "10. 开源协议与社区治理",
        ]
        todo = [
            "# TODO",
            "",
            "- [ ] Run all Example Applications through AgentRuntime.",
            "- [ ] Generate benchmark figures from real run metrics.",
            "- [ ] Embed Web Dashboard screenshots into README, report, and PPT.",
            "- [ ] Review high-risk tool policies and audit coverage.",
        ]
        paths = [
            _write(root / "outputs" / "research_summary.md", "\n".join(summary) + "\n"),
            _write(root / "outputs" / "report_outline.md", "\n".join(outline) + "\n"),
            _write(root / "outputs" / "TODO.md", "\n".join(todo) + "\n"),
        ]
        context.memory.add_memory(
            "Generated live project research summary and report outline.",
            {"type": "research_summary", "run_id": context.run_id, "files": [str(p) for p in paths]},
        )
        return ToolResult(ok=True, data={"overview": overview, "paths": [str(p) for p in paths]}, artifacts=[str(p) for p in paths])


class DeleteFileDryRunTool(BaseTool):
    name = "delete_file_dry_run"
    description = "Preview files that would be deleted without deleting anything."
    risk_level = "high"

    def run(self, args: dict, context: ToolContext) -> ToolResult:
        base = safe_path(context.settings.root_dir, args.get("path", "."))
        patterns = args.get("patterns", ["*.tmp", "*.temp", "*~", ".DS_Store"])
        matches: list[str] = []
        for pattern in patterns:
            matches.extend(str(path.relative_to(context.settings.root_dir)) for path in base.rglob(pattern) if path.is_file())
        report = safe_path(context.settings.root_dir, "outputs/delete_dry_run.md")
        lines = ["# Delete Dry-run Report", "", "No files were deleted.", "", "## Candidate files"]
        lines += [f"- `{item}`" for item in sorted(set(matches))] or ["- No matching temporary files found."]
        _write(report, "\n".join(lines) + "\n")
        return ToolResult(ok=True, data={"dry_run": True, "matches": sorted(set(matches)), "report": str(report)}, artifacts=[str(report)])


class CreateRagNoteTool(BaseTool):
    name = "create_rag_note"
    description = "Persist a note into the Memory Layer."
    risk_level = "low"

    def run(self, args: dict, context: ToolContext) -> ToolResult:
        memory_id = context.memory.add_memory(str(args.get("text", "")), args.get("metadata", {"type": "rag_note"}))
        return ToolResult(ok=True, data={"memory_id": memory_id})


class GenerateSlideOutlineTool(BaseTool):
    name = "generate_slide_outline"
    description = "Generate a slide outline markdown artifact from the current project state."
    risk_level = "low"

    def run(self, args: dict, context: ToolContext) -> ToolResult:
        path = safe_path(context.settings.root_dir, args.get("path", "slides/ppt_outline.md"))
        outline = [
            "# ClawFlow Presentation Outline",
            "",
            "1. ClawFlow: Lightweight Agent Runtime",
            "2. From Chatbot to AgentOS",
            "3. Runtime, Workflow, Memory, Trace, Governance",
            "4. Unified Example Applications",
            "5. Benchmark and Evaluation",
            "6. Open-source Community Roadmap",
        ]
        _write(path, "\n".join(outline) + "\n")
        return ToolResult(ok=True, data={"path": str(path)}, artifacts=[str(path)])


class GenerateReportSectionTool(BaseTool):
    name = "generate_report_section"
    description = "Generate a technical report section based on a requested topic and live workspace state."
    risk_level = "low"

    def run(self, args: dict, context: ToolContext) -> ToolResult:
        topic = str(args.get("topic", "runtime"))
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", topic).strip("_").lower() or "section"
        path = safe_path(context.settings.root_dir, args.get("path", f"outputs/report_section_{slug}.md"))
        overview = _workspace_overview(context.settings.root_dir, max_files=80)
        content = [
            f"# {topic.title()}",
            "",
            f"This section is generated from the live ClawFlow workspace with {overview['file_count']} sampled files.",
            "It emphasizes Agent Runtime infrastructure, real persistence, trace replay, checkpointing, and developer reuse.",
            "",
            "## Evidence",
        ]
        content += [f"- `{file}`" for file in overview["files"][:20]]
        _write(path, "\n".join(content) + "\n")
        return ToolResult(ok=True, data={"path": str(path)}, artifacts=[str(path)])


class BenchmarkTaskRunnerTool(BaseTool):
    name = "benchmark_task_runner"
    description = "Summarize benchmark result files generated by scripts/run_benchmark.py."
    risk_level = "low"

    def run(self, args: dict, context: ToolContext) -> ToolResult:
        path = context.settings.root_dir / "outputs" / "benchmark_results.json"
        if not path.exists():
            return ToolResult(ok=False, error="benchmark_results.json not found; run scripts/run_benchmark.py first")
        data = json.loads(path.read_text(encoding="utf-8"))
        latencies = [task.get("latency", 0) for task in data.get("tasks", [])]
        summary = {
            "total_tasks": data.get("total_tasks", 0),
            "success_rate": data.get("success_rate", 0),
            "average_latency": statistics.mean(latencies) if latencies else 0,
        }
        return ToolResult(ok=True, data=summary)


class MultiAgentProjectAnalysisTool(BaseTool):
    name = "multi_agent_project_analysis"
    description = "Run a local multi-agent collaboration flow through the unified Tool Registry context."
    risk_level = "low"

    def run(self, args: dict, context: ToolContext) -> ToolResult:
        from clawflow.core.multi_agent import MultiAgentCoordinator

        coordinator = MultiAgentCoordinator(context)
        return coordinator.run(args)

