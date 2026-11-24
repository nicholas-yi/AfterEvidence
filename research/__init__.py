"""Controlled agent-memory research, separate from the demonstration application."""

from pathlib import Path

RESEARCH = (
    Path(__file__).resolve().parent
)  # research/: data, docs, and the git-ignored runs, vendor
REPOSITORY = RESEARCH.parent
