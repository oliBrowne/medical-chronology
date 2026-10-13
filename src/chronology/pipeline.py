"""Orchestrator: runs the stages in order, fans pages out in parallel, joins."""

from __future__ import annotations

from pathlib import Path


def run(case_dir: Path, out_dir: Path) -> None:
    """Process every PDF under ``case_dir``. ``out_dir`` must be gitignored."""
    raise NotImplementedError
