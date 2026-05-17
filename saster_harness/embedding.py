"""Shared sentence-transformer embedder factory.

The session baseline and the induced detectors all want to embed
short text via the same model (default ``all-MiniLM-L6-v2``). v0.1
ships them as independent consumers — each lazy-loads its own
SentenceTransformer instance on first use. That works but pays the
~5–15 s model-load penalty twice when both code paths are active in
the same harness process, plus uses 2× the RAM.

This module exposes a tiny factory that constructs a callable
``str -> np.ndarray`` closing over a single SentenceTransformer
instance, lazy-loaded on first call. :class:`MonitoringHarness`
constructs one factory at startup and threads the resulting
callable through :class:`SessionBaseline` and any induced detector
that supports ``set_embedder``.

The model isn't loaded until the first ``embed()`` call. Callers
that want to pre-warm it can invoke ``embed("warmup")`` once during
startup; the harness does this from a background thread after the
proxy starts (see :class:`HarnessAddon.running`).

Importing sentence-transformers can be expensive on its own — the
factory delays that import too. If the package is unavailable the
factory raises ``ImportError`` at the moment of first ``embed()``
call, not at construction time, so the rest of the harness can
boot in stub-only mode.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def build_shared_embedder(model_name: str = "all-MiniLM-L6-v2") -> Callable[[str], np.ndarray]:
    """Return a callable that embeds one text per call, sharing a
    single SentenceTransformer instance across all callers.

    The closure carries the lazy-load state. First ``embed(text)``
    call constructs the model; subsequent calls reuse it.
    Thread-safe — uses a lock around the lazy-load step."""
    state: dict[str, Any] = {"model": None}
    lock = threading.Lock()

    def embed(text: str) -> np.ndarray:
        model = state["model"]
        if model is None:
            with lock:
                model = state["model"]
                if model is None:
                    try:
                        from sentence_transformers import SentenceTransformer
                    except ImportError as exc:  # pragma: no cover
                        raise ImportError(
                            "sentence-transformers is required for the "
                            "shared embedder. Install it via "
                            "`pip install saster-harness[dev]` or "
                            "`pip install sentence-transformers`."
                        ) from exc
                    logger.info("Loading shared embedder model %s …", model_name)
                    model = SentenceTransformer(model_name)
                    state["model"] = model
                    logger.info("Shared embedder ready.")
        result = model.encode([text], show_progress_bar=False)[0]
        return np.asarray(result, dtype=np.float32)

    return embed
