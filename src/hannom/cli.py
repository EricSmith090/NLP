"""Command-line interface for the Hán Nôm pipeline."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .config import load_config
from .orchestrator import (
    PipelineError,
    build_report,
    load_environment,
    open_state,
    run_pilot,
    stage_align,
    stage_classify,
    stage_clean,
    stage_evaluate,
    stage_extract,
    stage_intake,
    stage_labels,
    stage_map,
    stage_ocr,
    stage_package,
    stage_package_all,
    recompute_text_diff,
    build_source_zip,
)
from .align import write_alignment_csv
from .dictionary.book_lexicon import BookLexicon
from .orchestrator import load_rows_for_evaluation
from .dictionary.index import build_dictionary_index
from .package import split_submission_zip, validate_book_package, validate_source_zip
from .report import build_report_pdf, load_report_config, validate_report_data

app = typer.Typer(add_completion=False, help="Local-first Hán Nôm–Quốc ngữ pipeline")
console = Console()


def _project(config: str = "configs/project.yaml"):
    path = Path(config).resolve()
    project = load_config(path)
    load_environment(project.root)
    return project


def _books(project, book: Optional[str]):
    return project.selected_books(book)


@app.command()
def intake(config: str = "configs/project.yaml", book: Optional[str] = None):
    """Lock scope and record checksums. No mass OCR happens here."""
    project = _project(config)
    with open_state(project) as state:
        for item in _books(project, book):
            manifest = stage_intake(project, item, state)
            console.print(f"[green]{item.book_id}[/] locked: {manifest['inspection']['page_count']} pages")


@app.command()
def extract(config: str = "configs/project.yaml", book: Optional[str] = None, force: bool = False):
    """Extract native-resolution JPEGs, one per PDF page."""
    project = _project(config)
    with open_state(project) as state:
        for item in _books(project, book):
            pages = stage_extract(project, item, state, force=force)
            console.print(f"[green]{item.book_id}[/]: {len(pages)} images")


@app.command()
def classify(config: str = "configs/project.yaml", book: Optional[str] = None):
    """Classify page script and section boundaries."""
    project = _project(config)
    with open_state(project) as state:
        for item in _books(project, book):
            _, summary = stage_classify(project, item, state)
            console.print(f"[green]{item.book_id}[/]: {summary['counts']} nom_run={summary['nom_run']}")


@app.command()
def map(config: str = "configs/project.yaml", book: Optional[str] = None):
    """Build the T1 Nôm↔Quốc ngữ image map."""
    project = _project(config)
    with open_state(project) as state:
        for item in _books(project, book):
            data = stage_map(project, item, state)
            console.print(f"[green]{item.book_id}[/]: {len(data['pairs'])} pairs")


@app.command()
def ocr(
    config: str = "configs/project.yaml",
    book: Optional[str] = None,
    engine: Optional[list[str]] = typer.Option(None, "--engine", help="Override engine list"),
    limit: Optional[int] = None,
    force: bool = False,
):
    """Run local OCR; Kim Hán Nôm is only used if configured and available."""
    project = _project(config)
    with open_state(project) as state:
        for item in _books(project, book):
            results = stage_ocr(project, item, state, engines=engine, force=force, limit=limit)
            console.print(f"[green]{item.book_id}[/]: OCR results {len(results)}")


@app.command()
def labels(config: str = "configs/project.yaml", book: Optional[str] = None):
    """Generate PPOCRLabel Label.txt and fileState.txt."""
    project = _project(config)
    with open_state(project) as state:
        for item in _books(project, book):
            counts = stage_labels(project, item, state)
            console.print(f"[green]{item.book_id}[/]: {counts}")


@app.command()
def clean(config: str = "configs/project.yaml", book: Optional[str] = None):
    """NFC-normalize and conservatively clean OCR text."""
    project = _project(config)
    with open_state(project) as state:
        for item in _books(project, book):
            summary = stage_clean(project, item, state)
            console.print(f"[green]{item.book_id}[/]: {summary}")


@app.command()
def align(config: str = "configs/project.yaml", book: Optional[str] = None):
    """Segment sentences, align, learn lexicon, and write the draft CSV."""
    project = _project(config)
    with open_state(project) as state:
        for item in _books(project, book):
            rows, summary = stage_align(project, item, state)
            console.print(f"[green]{item.book_id}[/]: {len(rows)} rows")


@app.command("textdiff")
def textdiff(
    config: str = "configs/project.yaml",
    book: Optional[str] = None,
    force_recompute: bool = typer.Option(False, "--force-recompute", help="Re-score rows the aligner left unscored (default keeps nulls)."),
):
    """Recompute text_diff from cleaned text and the learned book lexicon."""
    project = _project(config)
    with open_state(project) as state:
        for item in _books(project, book):
            csv_path = project.data_dir / "align" / item.book_id / f"{item.book_name}.csv"
            rows, blocking_issues, _audit = load_rows_for_evaluation(project, item)
            if blocking_issues:
                console.print(f"[yellow]integrity issues: {len(blocking_issues)}[/] {blocking_issues[:3]}")
            dictionary = build_dictionary_index(project.root, project.dictionary_config, book_id=item.book_id)
            lexicon = BookLexicon(project.data_dir / "dictionary" / "book_lexicons" / f"{item.book_id}.json")
            rows = recompute_text_diff(rows, lexicon=lexicon, dictionary=dictionary, force_recompute=force_recompute)
            write_alignment_csv(csv_path, rows)
            console.print(f"[green]{item.book_id}[/]: {len(rows)} rows")


@app.command()
def evaluate(config: str = "configs/project.yaml", book: Optional[str] = None):
    """Report similarity, yellow ratio, and null-row ratio per book."""
    project = _project(config)
    with open_state(project) as state:
        table = Table(title="Per-book quality gate")
        table.add_column("book")
        table.add_column("similarity", justify="right")
        table.add_column("yellow", justify="right")
        table.add_column("null", justify="right")
        table.add_column("gate")
        for item in _books(project, book):
            metrics = stage_evaluate(project, item, state)
            table.add_row(
                item.book_id,
                "n/a" if metrics.similarity is None else f"{metrics.similarity:.2f}%",
                "n/a" if metrics.yellow_ratio is None else f"{metrics.yellow_ratio:.2%}",
                "n/a" if metrics.null_ratio is None else f"{metrics.null_ratio:.2%}",
                "[green]PASS[/]" if metrics.passed else "[red]FAIL[/]",
            )
        console.print(table)


@app.command()
def package(
    config: str = "configs/project.yaml",
    book: Optional[str] = None,
    strict_gate: bool = True,
):
    """Build per-book folders after the quality gate passes."""
    project = _project(config)
    with open_state(project) as state:
        for item in _books(project, book):
            book_dir, _ = stage_package(project, item, state, strict_gate=strict_gate)
            console.print(f"[green]{item.book_id}[/]: {book_dir}")


@app.command()
def report(
    config: str = "configs/project.yaml",
    strict: bool = True,
    output: Optional[Path] = None,
):
    """Generate the one-PDF report from metrics and configured screenshots."""
    project = _project(config)
    metrics = []
    for item in project.books:
        path = project.data_dir / "evaluation" / item.book_id / "metrics.json"
        if path.exists():
            from .models import BookMetrics

            metrics.append(BookMetrics(**json.loads(path.read_text(encoding="utf-8"))))
    path, issues, _ = build_report(project, metrics, output_path=output, strict=strict)
    console.print(f"[green]report[/]: {path}")
    for issue in issues:
        console.print(f"[yellow]{issue}[/]")


@app.command("package-all")
def package_all(
    config: str = "configs/project.yaml",
    strict_gate: bool = True,
    strict_report: bool = True,
):
    """Build the full ZIP with three sibling book folders, report, and source."""
    project = _project(config)
    with open_state(project) as state:
        result = stage_package_all(project, state, strict_gate=strict_gate, strict_report=strict_report)
    console.print(json.dumps(result, ensure_ascii=False, indent=2))


@app.command()
def pilot(config: str = "configs/project.yaml", book: str = "T1_SuaLoiQuyen"):
    """Run the Book 3 pilot through the deterministic stages."""
    project = _project(config)
    result = run_pilot(project, book)
    console.print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


@app.command()
def validate(
    config: str = "configs/project.yaml",
    book: Optional[str] = None,
    source_zip: Optional[Path] = None,
):
    """Mirror the acceptance checklist; exit non-zero on blockers."""
    project = _project(config)
    issues = []
    for item in _books(project, book):
        book_dir = project.output_dir / item.book_name
        issues.extend(validate_book_package(project, item, book_dir))
    if source_zip and source_zip.exists():
        issues.extend(validate_source_zip(source_zip))
    warnings = [i for i in issues if i.severity == "warning"]
    blockers = [i for i in issues if i.severity != "warning"]
    for issue in warnings:
        console.print(f"[yellow]{issue.code}[/] {issue.message} ({issue.path})")
    if blockers:
        for issue in blockers[:50]:
            console.print(f"[red]{issue.code}[/] {issue.message} ({issue.path})")
        raise typer.Exit(code=1)
    console.print("[green]validation passed[/]")


@app.command()
def status(config: str = "configs/project.yaml"):
    """Show recorded stages and metrics without running anything."""
    project = _project(config)
    table = Table(title="Pipeline status")
    table.add_column("book")
    table.add_column("pages")
    table.add_column("metrics")
    table.add_column("gate")
    for item in project.books:
        metrics_path = project.data_dir / "evaluation" / item.book_id / "metrics.json"
        metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
        table.add_row(
            item.book_id,
            str(item.expected_pages),
            "yes" if metrics else "no",
            ("PASS" if metrics.get("passed") else "FAIL") if metrics else "-",
        )
    console.print(table)


@app.command()
def review(config: str = "configs/project.yaml", book: str = "T1_SuaLoiQuyen"):
    """Launch the local Streamlit review app."""
    project = _project(config)
    app_path = project.root / "src" / "hannom" / "review" / "app.py"
    env = dict(**__import__("os").environ)
    env["HANNOM_PROJECT"] = str(project.root)
    env["HANNOM_BOOK"] = book
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(app_path)],
        check=False,
        env=env,
    )


@app.command()
def split(
    config: str = "configs/project.yaml",
    zip_path: Optional[Path] = None,
):
    """Create one ZIP per book from a full submission ZIP."""
    project = _project(config)
    source = zip_path or (project.data_dir / "output" / f"{project.zip_stem}.zip")
    created = split_submission_zip(project, source)
    for path in created:
        console.print(str(path))


@app.command("source-zip")
def source_zip(config: str = "configs/project.yaml"):
    """Build source.zip only (no data, models, PDFs, or tokens)."""
    project = _project(config)
    path = build_source_zip(project)
    console.print(str(path))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
