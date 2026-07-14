"""Helpers for inspecting supported files in the uploads directory."""

from __future__ import annotations

from pathlib import Path

SUPPORTED_UPLOAD_SUFFIXES: frozenset[str] = frozenset(
    {
        ".bmp",
        ".csv",
        ".doc",
        ".docx",
        ".gif",
        ".htm",
        ".html",
        ".jpeg",
        ".jpg",
        ".json",
        ".markdown",
        ".md",
        ".pdf",
        ".png",
        ".ppt",
        ".pptx",
        ".svg",
        ".tif",
        ".tiff",
        ".tsv",
        ".txt",
        ".webp",
        ".xls",
        ".xlsx",
        ".xml",
    }
)


def is_supported_upload_file(path: Path) -> bool:
    """Return True when ``path`` is a supported upload file."""
    return path.is_file() and path.suffix.lower() in SUPPORTED_UPLOAD_SUFFIXES


def count_supported_upload_files(directory: Path) -> int:
    """Count supported files directly under ``directory``."""
    return sum(1 for entry in directory.iterdir() if is_supported_upload_file(entry))


def directory_has_supported_files(directory: Path) -> bool:
    """Return True when ``directory`` contains at least one supported file."""
    return count_supported_upload_files(directory) > 0

