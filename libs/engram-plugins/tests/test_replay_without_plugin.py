"""The critical replay requirement (ADR-0024 §9): a historical event must
remain replayable after plugin removal, upgrade, downgrade, crash, or
unavailability — because replay never executes plugin code in the first
place. This module never imports the reference plugin's own module until the
merge is already complete, and asserts it is still absent from ``sys.modules``
across the rebuild, to prove replay does not (and cannot) reach for it.
"""

import sys
from pathlib import Path
from uuid import UUID

from plugins_harness import build_plugin_space

from engram_core.domain.values import MemoryKind, ProposalId
from engram_events import Provenance
from engram_plugins.contract import PluginContext

HUMAN = Provenance(actor="user")
_PLUGIN_MODULE = "engram_plugins.plugins.reference_url_evidence"


def test_replay_succeeds_with_the_plugin_module_never_imported(tmp_path: Path) -> None:
    sys.modules.pop(_PLUGIN_MODULE, None)  # start from a clean slate for this test

    space = build_plugin_space(tmp_path / "engram.db")
    memory_id = space.add_memory(
        MemoryKind.FACT,
        "engram repo",
        "The canonical repo lives at https://github.com/example/engram, see it.",
        statement="engram repo location",
    )
    space.rebuild()

    # Import happens here, once, to run the plugin — exactly one call site.
    from engram_plugins.plugins.reference_url_evidence import PLUGIN_ID, ReferenceUrlEvidencePlugin

    plugin = ReferenceUrlEvidencePlugin()
    space.registry.register(plugin)
    space.registry.enable(PLUGIN_ID)
    result = space.registry.run(PLUGIN_ID, space.gateway, PluginContext())
    proposal_id = ProposalId(UUID(str(result.proposal_id)))
    space.proposals.approve_proposal(proposal_id, None, HUMAN)
    space.proposals.merge_proposal(proposal_id, HUMAN)

    before = space.memory_queries.get_memory(memory_id)
    assert len(before.evidence) == 1
    before_events = list(space.store.read_stream(memory_id))

    # Simulate total plugin unavailability: remove it from the registry AND
    # from the interpreter, so nothing downstream could import it even by
    # accident.
    space.registry.remove(PLUGIN_ID)
    del sys.modules[_PLUGIN_MODULE]
    assert _PLUGIN_MODULE not in sys.modules

    applied = space.rebuild()  # drops + replays every projection from the raw log
    assert applied > 0
    assert _PLUGIN_MODULE not in sys.modules, "replay must never import plugin code"

    after = space.memory_queries.get_memory(memory_id)
    assert after.evidence == before.evidence
    assert after.content == before.content
    assert after.version == before.version

    after_events = list(space.store.read_stream(memory_id))
    assert [e.event_id for e in after_events] == [e.event_id for e in before_events]
    assert [e.payload for e in after_events] == [e.payload for e in before_events]


def test_replay_is_unaffected_by_a_plugin_version_change(tmp_path: Path) -> None:
    """Upgrading (or downgrading) the registered descriptor must not alter
    what already replayed — historical provenance is frozen at merge time."""
    from engram_plugins.plugins.reference_url_evidence import PLUGIN_ID, ReferenceUrlEvidencePlugin

    space = build_plugin_space(tmp_path / "engram.db")
    memory_id = space.add_memory(
        MemoryKind.FACT,
        "engram repo",
        "The canonical repo lives at https://github.com/example/engram, see it.",
        statement="engram repo location",
    )
    space.rebuild()

    v1 = ReferenceUrlEvidencePlugin(version="1.0.0")
    space.registry.register(v1)
    space.registry.enable(PLUGIN_ID)
    result = space.registry.run(PLUGIN_ID, space.gateway, PluginContext())
    proposal_id = ProposalId(UUID(str(result.proposal_id)))
    space.proposals.approve_proposal(proposal_id, None, HUMAN)
    space.proposals.merge_proposal(proposal_id, HUMAN)

    # The plugin's own provenance lives on the proposal's ProposalOpened event
    # (the merged memory event carries the human reviewer's provenance
    # instead — ADR-0018). That proposal event is what must stay frozen.
    before = next(
        e for e in space.proposal_queries.timeline(proposal_id) if e.event_type == "ProposalOpened"
    )

    # "Upgrade": register a new descriptor version under the same plugin_id.
    space.registry.register(ReferenceUrlEvidencePlugin(version="2.0.0"))
    space.rebuild()

    after = next(
        e for e in space.proposal_queries.timeline(proposal_id) if e.event_type == "ProposalOpened"
    )
    assert after.detail == before.detail  # still says "1.0.0" — frozen at merge time
    assert '"plugin_version": "1.0.0"' in (after.detail or "")

    # And the memory content itself is untouched by either the upgrade or the
    # rebuild — replay never re-derives anything from the plugin.
    memory = space.memory_queries.get_memory(memory_id)
    assert len(memory.evidence) == 1
