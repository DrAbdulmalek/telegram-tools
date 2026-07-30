"""
One-click uploader for ``ml_splits/`` directories to HuggingFace Hub.

Creates a dataset repo (private or public) on the fly and uploads every
``.tsv``, ``.jsonl`` and ``.txt`` file found under the given folder.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)

try:
    from huggingface_hub import HfApi, create_repo, login
    _HF_AVAILABLE = True
except ImportError:  # pragma: no cover
    _HF_AVAILABLE = False
    HfApi = None  # type: ignore
    create_repo = None  # type: ignore
    login = None  # type: ignore


_DEFAULT_FILE_EXTS: Tuple[str, ...] = ("tsv", "jsonl", "txt")


class HuggingFaceUploader:
    """Publish a folder of dataset files to the HuggingFace Hub.

    Parameters
    ----------
    token : str, optional
        HuggingFace access token (``hf_...``). Falls back to the
        ``HF_TOKEN`` environment variable if not provided.
    """

    def __init__(self, token: str | None = None) -> None:
        if not _HF_AVAILABLE:
            raise ImportError(
                "huggingface_hub is required for HuggingFaceUploader. "
                "Install with: pip install huggingface_hub"
            )

        self.token = token or os.environ.get("HF_TOKEN")
        if not self.token:
            raise ValueError(
                "HuggingFace token is required. Pass it explicitly or set "
                "the HF_TOKEN environment variable."
            )

        login(token=self.token)
        self.api = HfApi()

    def upload_dataset(
        self,
        folder_path: str | Path,
        repo_name: str,
        private: bool = True,
        file_types: Tuple[str, ...] = _DEFAULT_FILE_EXTS,
    ) -> str:
        """
        Upload every matching file under ``folder_path`` to a new or
        existing dataset repo.

        Parameters
        ----------
        folder_path : path-like
            Local folder containing the dataset files.
        repo_name : str
            Repo name (without the username prefix). The final repo ID
            will be ``{username}/{repo_name}``.
        private : bool
            ``True`` for a private repo (recommended for medical data),
            ``False`` for public.
        file_types : tuple of str
            File extensions to upload (without the leading dot).

        Returns
        -------
        str — URL of the uploaded dataset.
        """
        folder = Path(folder_path)
        if not folder.exists():
            raise FileNotFoundError(f"Folder not found: {folder}")

        username = self.api.whoami()["name"]
        repo_id = f"{username}/{repo_name}"

        # Create the repo (idempotent).
        create_repo(
            repo_id=repo_id,
            repo_type="dataset",
            private=private,
            exist_ok=True,
        )
        logger.info(
            "Repo ready: %s (visibility=%s)",
            repo_id,
            "private" if private else "public",
        )

        # Upload each matching file.
        uploaded = 0
        for ext in file_types:
            for file_path in folder.rglob(f"*.{ext}"):
                path_in_repo = file_path.relative_to(folder).as_posix()
                logger.info("  ↑ %s → %s", file_path, path_in_repo)
                self.api.upload_file(
                    path_or_fileobj=str(file_path),
                    path_in_repo=path_in_repo,
                    repo_id=repo_id,
                    repo_type="dataset",
                )
                uploaded += 1

        if uploaded == 0:
            logger.warning("No files matching %s found in %s", file_types, folder)

        url = f"https://huggingface.co/datasets/{repo_id}"
        logger.info("Upload complete: %s (%d files)", url, uploaded)
        return url
