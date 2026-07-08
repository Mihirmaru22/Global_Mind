"""Path-safety helpers for handling untrusted, caller-supplied path fragments.

Kept dependency-free (stdlib only) so it can be imported by the lightweight
API layer and unit-tested without pulling in the heavy ingestion stack.

Two distinct needs:
  * Uploads collapse an untrusted filename to a bare basename inside a single
    directory — nested paths are never desired, so we flatten them.
  * Static serving allows nested sub-paths (assets/index-abc.js) but must never
    escape the served root.

Both are vulnerable to the same classes of traversal:
  - ``"../../etc/passwd"``     → dot-dot escape
  - ``"/etc/passwd"``          → absolute path resets a ``Path`` join entirely
  - ``"a/../../b"``            → escape after a legitimate-looking prefix
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["safe_basename", "contained_path"]


def safe_basename(filename: str) -> str | None:
    """Reduce an untrusted filename to a safe basename.

    Strips every directory component (so ``"../x"``, ``"/etc/x"`` and
    ``"a/b/x"`` all collapse to ``"x"``) and rejects values that are empty or
    resolve to a traversal token.

    Returns the safe basename, or ``None`` if the input can't be made safe and
    the caller should reject the request.
    """
    if not filename:
        return None
    # Path(...).name keeps only the final component and drops any directory
    # parts, including a leading "/" that would otherwise reset a join.
    name = Path(filename).name
    if not name or name in {".", ".."}:
        return None
    # Defense in depth: a NUL byte can truncate the path in lower layers.
    if "\x00" in name:
        return None
    return name


def contained_path(root: Path, relpath: str) -> Path | None:
    """Resolve ``root / relpath`` and return it only if it stays within ``root``.

    Both sides are fully resolved (symlinks included) before the containment
    check, so ``".."`` segments and absolute paths can't escape ``root``.

    Returns the resolved path, or ``None`` if it would escape ``root`` (or can't
    be resolved), in which case the caller should not serve it.
    """
    if not relpath or "\x00" in relpath:
        return None
    root_resolved = root.resolve()
    try:
        candidate = (root_resolved / relpath).resolve()
    except (ValueError, OSError):
        return None
    if candidate == root_resolved or candidate.is_relative_to(root_resolved):
        return candidate
    return None
