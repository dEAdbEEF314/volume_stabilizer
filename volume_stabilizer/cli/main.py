"""Volume Stabilizer CLI (vstab)."""

from __future__ import annotations

import sys
from pathlib import Path
import typer
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from volume_stabilizer.config import load_config
from volume_stabilizer.core.scanner import scan_directory
from volume_stabilizer.core.hasher import compute_audio_hash
from volume_stabilizer.core.analyzer import analyze_track
from volume_stabilizer.core.processor import process_audio
from volume_stabilizer.core.tagger import copy_metadata
from volume_stabilizer.core.backup import backup_existing_output
from volume_stabilizer.db.database import init_db
from volume_stabilizer.db.repository import Repository

app = typer.Typer(help="Volume Stabilizer: DJ Audio Library Loudness Normalizer (EBU R128)")
console = Console(width=160)


@app.command()
def scan(
    subpath: str = typer.Argument("", help="Subdirectory inside /music to scan"),
):
    """Scan directory and list detected audio tracks."""
    cfg = load_config()
    console.print(f"[bold cyan]Scanning:[/bold cyan] {cfg.input_root / subpath}")

    tracks = list(scan_directory(cfg.input_root, cfg.output_root, subpath))
    if not tracks:
        console.print("[yellow]No supported audio files found.[/yellow]")
        return

    table = Table(title=f"Detected Tracks ({len(tracks)})")
    table.add_column("Relative Path", style="cyan")
    table.add_column("Codec", style="magenta")
    table.add_column("Class", style="green")
    table.add_column("Output Format", style="yellow")
    table.add_column("Size", justify="right")

    for t in tracks:
        cls = "Lossy" if t.is_lossy else "Lossless"
        size_mb = f"{t.file_size / (1024 * 1024):.1f} MB"
        table.add_row(str(t.relative_path), t.codec, cls, t.output_format.upper(), size_mb)

    console.print(table)


@app.command()
def analyze(
    subpath: str = typer.Argument("", help="Subdirectory to analyze"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-analyze even if already processed"),
):
    """Stage 1: Analyze loudness (LUFS, True Peak) of tracks."""
    cfg = load_config()
    init_db(cfg.db_path)
    repo = Repository(cfg.db_path)

    tracks = list(scan_directory(cfg.input_root, cfg.output_root, subpath))
    if not tracks:
        console.print("[yellow]No audio tracks found to analyze.[/yellow]")
        return

    table = Table(title=f"Analysis Results (Target: {cfg.target_lufs} LUFS, Ceiling: {cfg.peak_ceiling_dbtp} dBTP)")
    table.add_column("Track", style="cyan")
    table.add_column("LUFS", justify="right")
    table.add_column("True Peak", justify="right")
    table.add_column("Target Gain", justify="right")
    table.add_column("Limiter?", justify="center")
    table.add_column("Status / Warning", style="yellow")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Analyzing audio tracks...", total=len(tracks))

        for t in tracks:
            # Hash to identify track
            audio_hash = compute_audio_hash(t.input_path)
            track_rec = repo.upsert_track(
                audio_hash=audio_hash,
                relative_path=str(t.relative_path),
                input_path=str(t.input_path),
                output_path=str(t.output_path),
                input_format=t.codec,
                output_format=t.output_format,
                file_size=t.file_size,
                mtime=t.mtime,
            )

            # Analyze loudness
            analysis = analyze_track(
                file_path=t.input_path,
                is_mp3=(t.output_format == "mp3"),
                target_lufs=cfg.target_lufs,
                peak_ceiling_dbtp=cfg.peak_ceiling_dbtp,
                max_limiter_reduction_db=cfg.max_limiter_reduction_db,
                bypass_tolerance_lu=cfg.bypass_tolerance_lu,
            )

            repo.save_analysis(
                track_id=track_rec.id,
                integrated_lufs=analysis.integrated_lufs,
                true_peak_dbtp=analysis.true_peak_dbtp,
                lra_lu=analysis.lra_lu,
                target_gain_db=analysis.target_gain_db,
                limiter_required=analysis.limiter_required,
                limiter_reduction_db=analysis.limiter_reduction_db,
                bypass_eligible=analysis.bypass_eligible,
                warning_code=analysis.warning_code,
            )

            warn_str = "[green]OK[/green]"
            if analysis.bypass_eligible:
                warn_str = "[bold blue]Bypass Eligible[/bold blue]"
            elif analysis.warning_code == "LOUDNESS_UNDER_TARGET":
                warn_str = "[bold red]Max Reduction Cap (3dB)[/bold red]"

            lim_str = f"[red]Yes (-{analysis.limiter_reduction_db:.1f}dB)[/red]" if analysis.limiter_required else "[green]No[/green]"

            table.add_row(
                str(t.relative_path),
                f"{analysis.integrated_lufs:.1f}",
                f"{analysis.true_peak_dbtp:.1f}",
                f"{analysis.target_gain_db:+.1f} dB",
                lim_str,
                warn_str,
            )
            progress.advance(task)

    console.print(table)


@app.command()
def convert(
    subpath: str = typer.Argument("", help="Subdirectory to convert"),
    force: bool = typer.Option(False, "--force", "-f", help="Force reprocessing even if already stabilized"),
):
    """Stage 2: Normalize and convert audio tracks with metadata and Serato cue preservation."""
    cfg = load_config()
    init_db(cfg.db_path)
    repo = Repository(cfg.db_path)

    tracks = list(scan_directory(cfg.input_root, cfg.output_root, subpath))
    if not tracks:
        console.print("[yellow]No audio tracks found to convert.[/yellow]")
        return

    console.print(f"[bold green]Starting Volume Stabilization (Force={force})...[/bold green]")

    skipped = 0
    converted = 0
    bypassed = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Processing tracks...", total=len(tracks))

        for t in tracks:
            audio_hash = compute_audio_hash(t.input_path)
            existing = repo.get_track_by_hash(audio_hash)

            # Check if already processed (Q10, Q20)
            if not force and existing and existing.status in ("converted", "bypassed") and t.output_path.exists():
                skipped += 1
                progress.advance(task)
                continue

            track_rec = repo.upsert_track(
                audio_hash=audio_hash,
                relative_path=str(t.relative_path),
                input_path=str(t.input_path),
                output_path=str(t.output_path),
                input_format=t.codec,
                output_format=t.output_format,
                file_size=t.file_size,
                mtime=t.mtime,
            )

            # Analyze loudness
            analysis = analyze_track(
                file_path=t.input_path,
                is_mp3=(t.output_format == "mp3"),
                target_lufs=cfg.target_lufs,
                peak_ceiling_dbtp=cfg.peak_ceiling_dbtp,
                max_limiter_reduction_db=cfg.max_limiter_reduction_db,
                bypass_tolerance_lu=cfg.bypass_tolerance_lu,
            )

            # If force and output exists, back up old output before overwriting (Q22)
            if force and t.output_path.exists():
                backed_up = backup_existing_output(t.output_path, cfg.backup_dir, t.output_path.relative_to(cfg.output_root))
                if backed_up:
                    repo.record_backup(track_rec.id, str(backed_up), backed_up.stat().st_size)

            # Process & Encode
            process_audio(
                input_path=t.input_path,
                output_path=t.output_path,
                analysis=analysis,
                output_format=t.output_format,
                peak_ceiling_dbtp=cfg.peak_ceiling_dbtp,
            )

            # Preserve metadata & Serato cues
            # If force, prefer cues that were on existing output file (Q22)
            copy_metadata(
                source_path=t.input_path,
                target_path=t.output_path,
                preserve_from_target=force,
            )

            status = "bypassed" if analysis.bypass_eligible else "converted"
            repo.update_track_status(track_rec.id, status)

            if analysis.bypass_eligible:
                bypassed += 1
            else:
                converted += 1

            progress.advance(task)

    console.print(
        f"[bold green]Done![/bold green] "
        f"Converted: [cyan]{converted}[/cyan], "
        f"Bypassed: [blue]{bypassed}[/blue], "
        f"Skipped (Unchanged): [yellow]{skipped}[/yellow]"
    )


@app.command()
def inspect(
    file_path: Path = typer.Argument(..., help="Path to audio file to inspect"),
):
    """Inspect audio file loudness, hash, and metadata."""
    if not file_path.exists():
        console.print(f"[red]File not found: {file_path}[/red]")
        sys.exit(1)

    cfg = load_config()
    audio_hash = compute_audio_hash(file_path)
    analysis = analyze_track(file_path, is_mp3=file_path.suffix.lower() == ".mp3", target_lufs=cfg.target_lufs)

    table = Table(title=f"File Inspection: {file_path.name}")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="magenta")

    table.add_row("Audio Stream Hash (SHA-256)", audio_hash)
    table.add_row("Integrated Loudness", f"{analysis.integrated_lufs:.2f} LUFS")
    table.add_row("True Peak", f"{analysis.true_peak_dbtp:.2f} dBTP")
    table.add_row("Loudness Range (LRA)", f"{analysis.lra_lu:.2f} LU")
    table.add_row("Target Gain (-10 LUFS)", f"{analysis.target_gain_db:+.2f} dB")
    table.add_row("Limiter Required", str(analysis.limiter_required))
    table.add_row("Limiter Reduction", f"{analysis.limiter_reduction_db:.2f} dB")
    table.add_row("Bypass Eligible", str(analysis.bypass_eligible))
    table.add_row("Warning", analysis.warning_code)

    console.print(table)


if __name__ == "__main__":
    app()
