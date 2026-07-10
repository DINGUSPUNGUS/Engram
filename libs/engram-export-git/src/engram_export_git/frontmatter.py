"""Markdown (de)serialization: YAML frontmatter + body.

The frontmatter always carries the immutable ``id``; everything else is
human-editable and round-tripped by the reconciler. Stubs.

Example document::

    ---
    id: 018fa48e-6f3c-7cc0-8f2e-3d9a1b2c4d5e
    type: preference
    title: Kahnya branding
    tags: [branding, kahnya]
    links:
      - target: 018fa48e-1111-7aaa-bbbb-cccccccccccc
        relation: relates_to
    created: 2026-07-10T12:00:00Z
    updated: 2026-07-10T12:34:56Z
    ---

    Prefers muted earth tones and lowercase logotypes.
"""

from engram_core.application.dto import MemoryReadModel


def render_document(memory: MemoryReadModel) -> str:
    """Serialize a read model into frontmatter + markdown body."""
    raise NotImplementedError


def parse_document(text: str) -> MemoryReadModel:
    """Parse a markdown document back into a read model.

    Raises:
        ValidationError: missing/invalid frontmatter or unknown ``id``.
    """
    raise NotImplementedError
