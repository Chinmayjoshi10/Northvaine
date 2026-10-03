"""Standards and constants shared project-wide (ISO/UN-LOCODE/HS helpers land here too, later).

`EMBED_DIM_EXPECTED` is the single source of the embedding vector dimension. It must agree with
schema.sql, migrations/versions/0003_embeddings_and_llm_calls.py and `Settings.embed_dim` — an
offline test (T2.1a) proves schema.sql and this migration agree with the number below.
"""

from __future__ import annotations

from northvaine.core.settings import ConfigError, Settings, get_settings

# Confirmed live against Token Factory, probe P3, 2026-10-03 (docs/integrations/
# nemotron-embeddings-and-the-vector-dimension.md; DECISIONS.md D7, D14). Qwen/Qwen3-Embedding-8B
# natively returns 4096 floats, which pgvector cannot index at all (limit 2,000 for `vector`,
# 4,000 for `halfvec`); requesting `dimensions=1024` returns exactly 1024 floats, L2-normalized,
# which fits a plain HNSW `vector_cosine_ops` index.
EMBED_DIM_EXPECTED: int = 1024


def validate_embed_dim(settings: Settings | None = None) -> None:
    """Raise `ConfigError` naming EMBED_DIM when it is set and disagrees with the expected value."""
    settings = settings or get_settings()
    if settings.embed_dim is not None and settings.embed_dim != EMBED_DIM_EXPECTED:
        raise ConfigError(
            f"EMBED_DIM={settings.embed_dim} does not match the expected {EMBED_DIM_EXPECTED} "
            "(see northvaine/core/standards.py)"
        )
