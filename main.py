"""
main.py — ToolStack Pipeline Orchestrator

Usage:
    python main.py run               # Discover tools, queue, and auto-generate scripts
    python main.py generate          # Generate scripts for all queued tools not yet scripted
    python main.py queue             # Show what is in the queue
    python main.py stats             # Pipeline stats
    python main.py schedule          # Run automatically every 6 hours
"""
import os
import sys
import time
import schedule
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from toolstack.config import MIN_SCORE_THRESHOLD, ANTHROPIC_API_KEY, PEXELS_API_KEY
from toolstack.models import ToolCandidate
from toolstack.connectors import hackernews, reddit, github, producthunt
from toolstack.filters import gap_check
from toolstack.scoring import scorer
from toolstack.queue import manager
from toolstack.utils import script_generator

console = Console()


def step_discover() -> list[ToolCandidate]:
    console.print("\n[bold cyan]Step 1 — Discovery[/bold cyan]")
    all_candidates: list[ToolCandidate] = []

    sources = [
        ("Hacker News",  hackernews.fetch,  {"max_results": 50}),
        ("Reddit",       reddit.fetch,       {"max_per_sub": 25}),
        ("GitHub",       github.fetch,       {"max_results": 60}),
        ("Product Hunt", producthunt.fetch,  {"max_results": 40}),
    ]

    for name, fn, kwargs in sources:
        try:
            results = fn(**kwargs)
            console.print(f"  {name}: [green]{len(results)} candidates[/green]")
            all_candidates.extend(results)
        except Exception as e:
            console.print(f"  {name}: [red]Error — {e}[/red]")

    seen: set[str] = set()
    unique = []
    for c in all_candidates:
        if c.url not in seen:
            seen.add(c.url)
            unique.append(c)

    console.print(f"\n  Total unique: [bold]{len(unique)}[/bold]")
    return unique


def step_pre_filter(candidates: list[ToolCandidate]) -> list[ToolCandidate]:
    console.print("\n[bold cyan]Step 2 — Pre-filter[/bold cyan]")
    filtered = []
    for c in candidates:
        if manager.already_seen(c.url):
            continue
        if not c.description.strip():
            c.skipped = True; c.skip_reason = "no description"
            manager.upsert(c); manager.mark_skipped(c.url, c.skip_reason)
            continue
        if len(c.name.strip()) < 3:
            c.skipped = True; c.skip_reason = "name too short"
            manager.upsert(c); manager.mark_skipped(c.url, c.skip_reason)
            continue
        filtered.append(c)
    console.print(f"  After pre-filter: [bold]{len(filtered)}[/bold] new candidates")
    return filtered


def step_gap_check(candidates: list[ToolCandidate]) -> list[ToolCandidate]:
    console.print("\n[bold cyan]Step 3 — YouTube gap check[/bold cyan]")
    if not candidates:
        console.print("  Nothing to check.")
        return []
    gap_check.check_batch(candidates)
    passed = [c for c in candidates if c.yt_gap_passed]
    failed = [c for c in candidates if c.yt_gap_passed is False]
    for c in failed:
        c.skipped = True
        c.skip_reason = f"yt_gap: {c.yt_video_count} videos, max {c.yt_max_views:,} views"
    console.print(f"  Passed: [green]{len(passed)}[/green]  Failed: [red]{len(failed)}[/red]")
    return candidates


def step_score_and_queue(candidates: list[ToolCandidate]) -> list[ToolCandidate]:
    console.print("\n[bold cyan]Step 4 — Scoring & queueing[/bold cyan]")
    scorer.score_batch(candidates)
    queued_count = 0
    for c in candidates:
        manager.upsert(c)
        if c.skipped:
            manager.mark_skipped(c.url, c.skip_reason)
            continue
        if c.yt_gap_passed and c.score >= MIN_SCORE_THRESHOLD:
            c.queued = True
            manager.mark_queued(c.url)
            queued_count += 1
        else:
            c.skipped = True
            c.skip_reason = f"score too low ({c.score:.1f} < {MIN_SCORE_THRESHOLD})"
            manager.mark_skipped(c.url, c.skip_reason)
    console.print(f"  Queued this run: [bold green]{queued_count}[/bold green]")
    return candidates


def show_queue():
    items = manager.get_queue(limit=20)
    if not items:
        console.print("[yellow]Queue is empty.[/yellow]")
        return
    t = Table(title="Script Queue", box=box.SIMPLE_HEAD, show_lines=False)
    t.add_column("Score", style="bold green", width=7)
    t.add_column("Name", width=28)
    t.add_column("Source", width=12)
    t.add_column("YT vids", width=8)
    t.add_column("URL", style="dim", overflow="fold", width=35)
    for item in items:
        t.add_row(str(item["score"]), item["name"], item["source"],
                  str(item["yt_video_count"]), item["url"])
    console.print(t)


def show_stats():
    stats = manager.get_stats()
    console.print(Panel(
        f"Total seen:     [bold]{stats['total_seen']}[/bold]\n"
        f"Queued:         [bold green]{stats['queued']}[/bold green]\n"
        f"Scripted:       [bold blue]{stats['scripted']}[/bold blue]\n"
        f"Skipped:        [bold red]{stats['skipped']}[/bold red]\n"
        f"Pipeline runs:  [bold]{stats['pipeline_runs']}[/bold]",
        title="Pipeline Stats", expand=False,
    ))


def step_generate_scripts(newly_queued: list[ToolCandidate]) -> None:
    """Auto-generate .docx scripts for every tool queued in this run."""
    api_key = ANTHROPIC_API_KEY
    if not api_key:
        console.print("\n[yellow]ANTHROPIC_API_KEY not set -- skipping script generation[/yellow]")
        return
    if not newly_queued:
        console.print("\n[dim]No new tools queued — nothing to script.[/dim]")
        return

    top = sorted(newly_queued, key=lambda c: c.score, reverse=True)[:5]
    console.print(f"\n[bold cyan]Step 5 -- Script Generation (top {len(top)} of {len(newly_queued)} queued)[/bold cyan]")
    for candidate in top:
        path = script_generator.generate_script(candidate, api_key, pexels_api_key=PEXELS_API_KEY)
        if path:
            manager.mark_script_generated(candidate.url)
            console.print(f"  [green]OK[/green] {candidate.name} -> {path.name}")
        else:
            console.print(f"  [red]FAIL[/red] {candidate.name} -- script generation failed")


def run_pipeline():
    start = datetime.utcnow()
    console.print(Panel(
        f"[bold]ToolStack Discovery Pipeline[/bold]\n"
        f"Started at {start.strftime('%Y-%m-%d %H:%M UTC')}",
        style="cyan",
    ))
    manager.init_db()
    candidates = step_discover()
    candidates = step_pre_filter(candidates)
    candidates = step_gap_check(candidates)
    candidates = step_score_and_queue(candidates)
    newly_queued = [c for c in candidates if c.queued]
    queued  = len(newly_queued)
    skipped = sum(1 for c in candidates if c.skipped)
    manager.log_run(
        found=len(candidates), gap_checked=len([c for c in candidates if c.yt_gap_passed is not None]),
        queued=queued, skipped=skipped,
    )
    elapsed = (datetime.utcnow() - start).seconds
    console.print(f"\n[bold green]Done in {elapsed}s[/bold green] -- {queued} queued, {skipped} skipped\n")
    step_generate_scripts(newly_queued)
    show_queue()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"

    if cmd == "run":
        run_pipeline()

    elif cmd == "queue":
        manager.init_db(); show_queue()

    elif cmd == "stats":
        manager.init_db(); show_stats()

    elif cmd == "script":
        if len(sys.argv) < 3:
            console.print("[red]Usage: python main.py script <tool_url>[/red]")
            sys.exit(1)
        api_key = ANTHROPIC_API_KEY or os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            console.print("[red]ANTHROPIC_API_KEY not set in .env[/red]")
            sys.exit(1)
        manager.init_db()
        url = sys.argv[2]
        items = manager.get_queue(limit=100)
        match = next((i for i in items if i["url"] == url), None)
        if not match:
            console.print(f"[red]URL not found in queue: {url}[/red]")
            sys.exit(1)
        candidate = ToolCandidate(
            name=match["name"], url=match["url"], source=match["source"],
            source_url=match["source_url"] or "", description=match["description"] or "",
            score=match["score"],
        )
        path = script_generator.generate_script(candidate, api_key, pexels_api_key=PEXELS_API_KEY)
        if path:
            manager.mark_script_generated(url)
            console.print(f"[green]Script ready: {path}[/green]")

    elif cmd == "generate":
        # Generate scripts for every queued tool that doesn't have one yet
        api_key = ANTHROPIC_API_KEY or os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            console.print("[red]ANTHROPIC_API_KEY not set in .env[/red]")
            sys.exit(1)
        manager.init_db()
        items = manager.get_queue(limit=200)
        pending = [i for i in items if not i.get("script_generated")]
        if not pending:
            console.print("[yellow]No unscripted tools in queue.[/yellow]")
            sys.exit(0)
        console.print(f"[cyan]Generating scripts for {len(pending)} queued tools...[/cyan]\n")
        for item in pending:
            candidate = ToolCandidate(
                name=item["name"], url=item["url"], source=item["source"],
                source_url=item["source_url"] or "", description=item["description"] or "",
                score=item["score"],
            )
            try:
                path = script_generator.generate_script(candidate, api_key, pexels_api_key=PEXELS_API_KEY)
            except Exception as e:
                console.print(f"  [red]FAIL[/red] {item['name']} -- {type(e).__name__}: {e}")
                continue
            if path:
                manager.mark_script_generated(item["url"])
                console.print(f"  [green]OK[/green] {item['name']} -> {path.name}")
            else:
                console.print(f"  [red]FAIL[/red] {item['name']} -- failed")

    elif cmd == "schedule":
        console.print("[cyan]Running on schedule — every 6 hours[/cyan]")
        schedule.every(6).hours.do(run_pipeline)
        run_pipeline()
        while True:
            schedule.run_pending()
            time.sleep(60)

    else:
        console.print(f"[red]Unknown command: {cmd}[/red]")
        console.print("Usage: python main.py [run|generate|queue|stats|schedule]")
