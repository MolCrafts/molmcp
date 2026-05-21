"""GitHub source resolution.

Resolves a ``github:owner/repo[@ref]`` spec to an immutable snapshot by
resolving the ref to a commit SHA (the snapshot id) and downloading that
commit's tarball. All network access is stdlib ``urllib`` and is
confined to this module, so a restricted-network deployment can disable
GitHub and keep local discovery fully working.
"""

from __future__ import annotations

import io
import json
import shutil
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..config import DiscoveryConfig
from .resolver import Snapshot, SnapshotId, SourceError
from .walk import walk_files

_API = "https://api.github.com"
_CODELOAD = "https://codeload.github.com"
_TIMEOUT = 30


def _parse_github_spec(spec: str) -> tuple[str, str, str | None]:
    body = spec[len("github:"):] if spec.startswith("github:") else spec
    ref: str | None = None
    if "@" in body:
        body, ref = body.rsplit("@", 1)
    parts = [p for p in body.strip("/").split("/") if p]
    if len(parts) != 2:
        raise SourceError(
            f"invalid github spec {spec!r} "
            "(expected github:owner/repo[@ref])"
        )
    return parts[0], parts[1], (ref or None)


def _http_get(
    url: str,
    token: str | None = None,
    accept: str = "application/vnd.github+json",
) -> bytes:
    headers = {"User-Agent": "molmcp-discovery", "Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise SourceError(
            f"GitHub request failed ({exc.code}) for {url}"
        ) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise SourceError(f"GitHub request failed for {url}: {exc}") from exc


def resolve_ref(
    owner: str, repo: str, ref: str | None, config: DiscoveryConfig
) -> str:
    """Resolve a branch/tag/ref (or the default branch) to a commit SHA."""
    token = config.github_token
    if ref is None:
        info = json.loads(_http_get(f"{_API}/repos/{owner}/{repo}", token))
        ref = info.get("default_branch", "HEAD")
    payload = json.loads(
        _http_get(f"{_API}/repos/{owner}/{repo}/commits/{ref}", token)
    )
    sha = payload.get("sha")
    if not sha:
        raise SourceError(f"could not resolve {owner}/{repo}@{ref}")
    return sha


def latest_commit(spec: str, config: DiscoveryConfig) -> str:
    """Return the current commit SHA a github spec points at."""
    owner, repo, ref = _parse_github_spec(spec)
    return resolve_ref(owner, repo, ref, config)


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    try:
        tar.extractall(dest, filter="data")  # py3.12+: blocks traversal
    except TypeError:  # pragma: no cover - older Python
        tar.extractall(dest)


def _download_source(
    owner: str, repo: str, sha: str, raw_dir: Path, config: DiscoveryConfig
) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    url = f"{_CODELOAD}/{owner}/{repo}/tar.gz/{sha}"
    data = _http_get(url, config.github_token, accept="application/octet-stream")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        _safe_extract(tar, raw_dir)
    subdirs = sorted(d for d in raw_dir.iterdir() if d.is_dir())
    if not subdirs:
        raise SourceError("GitHub tarball contained no source directory")
    return subdirs[0]


def _ensure_source(
    owner: str, repo: str, sha: str, raw_dir: Path, config: DiscoveryConfig
) -> Path:
    """Return the extracted source root, downloading it once if needed."""
    marker = raw_dir / ".extracted"
    if marker.is_file():
        root = Path(marker.read_text(encoding="utf-8").strip())
        if root.is_dir():
            return root
    if raw_dir.exists():
        shutil.rmtree(raw_dir, ignore_errors=True)
    root = _download_source(owner, repo, sha, raw_dir, config)
    marker.write_text(str(root), encoding="utf-8")
    return root


def resolve_github(spec: str, config: DiscoveryConfig) -> Snapshot:
    """Resolve a ``github:owner/repo[@ref]`` spec to a snapshot."""
    from ..cache.snapshotcache import SnapshotCache

    owner, repo, ref = _parse_github_spec(spec)
    sha = resolve_ref(owner, repo, ref, config)
    snapshot_id = SnapshotId("github", "commit", sha)
    raw_dir = SnapshotCache(config).raw_dir(str(snapshot_id))
    root = _ensure_source(owner, repo, sha, raw_dir, config)
    files = tuple(walk_files(root, config))
    return Snapshot(
        snapshot_id=str(snapshot_id),
        origin="github",
        spec=spec,
        root_dir=root,
        scope=None,
        ref=ref,
        commit=sha,
        created_at=time.time(),
        files=files,
    )
