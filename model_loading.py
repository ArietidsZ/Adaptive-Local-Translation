"""Resolve complete ASR snapshots before Qwen loads model and processor."""

from pathlib import Path

from config import Config


def resolve_model_directory(model: str, cfg: Config) -> str:
    path = Path(model).expanduser()
    if path.is_dir():
        return str(path.resolve())
    # Qwen 0.0.6 does not forward loader kwargs to AutoProcessor. A local
    # snapshot path applies the same cache/offline boundary to both loaders.
    from huggingface_hub import snapshot_download

    return snapshot_download(
        repo_id=model,
        cache_dir=cfg.model_cache_dir,
        local_files_only=cfg.offline_only,
    )
