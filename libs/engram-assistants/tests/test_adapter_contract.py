"""The shared integration contract (ADR-0020): every adapter, one behavior.

Each provider adapter is exercised through its own wire shapes; the canonical
payload extracted from each provider's result must be identical — different
envelopes, same memory substrate, same guarantees."""

import json
import re
import tempfile
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from assistants_harness import CONVERSATION, USER, AssistantSpace, build_assistant_space
from engram_assistants.adapters import ChatGPTAdapter, ClaudeAdapter, GeminiAdapter
from engram_assistants.contract import AssistantContext, Capability
from engram_assistants.gateway import AssistantGateway

from engram_core.application.dto import CreateMemoryInput
from engram_core.domain.values import MemoryKind, ProposalId

CONTEXT = AssistantContext(session_id="conv-1", model="test-model")


@dataclass(frozen=True)
class Driver:
    """Provider-specific glue for the shared suite: wrap a call, unwrap a result."""

    name: str
    build: Callable[[AssistantGateway, frozenset[Capability] | None], object]
    make_call: Callable[[str, dict[str, Any]], dict[str, Any]]
    payload: Callable[[Mapping[str, Any]], dict[str, Any]]
    is_error: Callable[[Mapping[str, Any]], bool]


def _chatgpt(gateway: AssistantGateway, caps: frozenset[Capability] | None) -> ChatGPTAdapter:
    return ChatGPTAdapter(gateway, capabilities=caps) if caps else ChatGPTAdapter(gateway)


def _claude(gateway: AssistantGateway, caps: frozenset[Capability] | None) -> ClaudeAdapter:
    return ClaudeAdapter(gateway, capabilities=caps) if caps else ClaudeAdapter(gateway)


def _gemini(gateway: AssistantGateway, caps: frozenset[Capability] | None) -> GeminiAdapter:
    return GeminiAdapter(gateway, capabilities=caps) if caps else GeminiAdapter(gateway)


DRIVERS = [
    Driver(
        name="chatgpt",
        build=_chatgpt,
        make_call=lambda name, args: {
            "id": "call_1",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)},
        },
        payload=lambda result: dict(json.loads(str(result["content"]))),
        is_error=lambda result: "error" in json.loads(str(result["content"])),
    ),
    Driver(
        name="claude",
        build=_claude,
        make_call=lambda name, args: {
            "type": "tool_use",
            "id": "tu_1",
            "name": name,
            "input": args,
        },
        payload=lambda result: dict(json.loads(result["content"][0]["text"])),  # type: ignore[index]
        is_error=lambda result: bool(result.get("is_error")),
    ),
    Driver(
        name="gemini",
        build=_gemini,
        make_call=lambda name, args: {"functionCall": {"name": name, "args": args}},
        payload=lambda result: dict(result["functionResponse"]["response"]),  # type: ignore[index]
        is_error=lambda result: "error" in result["functionResponse"]["response"],  # type: ignore[index]
    ),
]

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_SLUG_SUFFIX = re.compile(r"-[0-9a-f]{8}\b")


def _normalize(value: object) -> object:
    """Erase minted identities so cross-adapter outputs are comparable."""
    text = json.dumps(value, sort_keys=True)
    return _SLUG_SUFFIX.sub("-<hex>", _UUID.sub("<uuid>", text))


@pytest.fixture
def space(tmp_path: Path) -> AssistantSpace:
    return build_assistant_space(tmp_path / "engram.db")


def _seed_fact(space: AssistantSpace) -> None:
    space.commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind.FACT,
            title="User prefers dark mode",
            content="always dark themes",
            attributes={"statement": "User prefers dark mode"},
            tags=("ui",),
        ),
        USER,
    )


@pytest.mark.integration
def test_every_adapter_exposes_the_same_five_tools(space: AssistantSpace) -> None:
    expected = {
        "engram_search",
        "engram_recall",
        "engram_remember",
        "engram_proposal_status",
        "engram_timeline",
    }
    chatgpt = ChatGPTAdapter(space.gateway).tool_definitions()
    claude = ClaudeAdapter(space.gateway).tool_definitions()
    gemini = GeminiAdapter(space.gateway).tool_definitions()
    assert {d["function"]["name"] for d in chatgpt} == expected  # type: ignore[index]
    assert {d["name"] for d in claude} == expected
    assert {f["name"] for f in gemini[0]["functionDeclarations"]} == expected  # type: ignore[index]
    # And no tool NAME carries a review verb — approval lives on human surfaces only.
    for name in expected:
        for verb in ("approve", "reject", "merge", "undo"):
            assert verb not in name


@pytest.mark.integration
@pytest.mark.parametrize("driver", DRIVERS, ids=lambda d: d.name)
def test_search_returns_the_canonical_payload_in_the_provider_shape(
    space: AssistantSpace, driver: Driver
) -> None:
    _seed_fact(space)
    adapter = driver.build(space.gateway, None)
    result = adapter.handle_tool_call(  # type: ignore[attr-defined]
        driver.make_call("engram_search", {"query": "dark mode"}), CONTEXT
    )
    payload = driver.payload(result)
    assert payload["count"] == 1
    assert payload["memories"][0]["title"] == "User prefers dark mode"
    # The recall left its audit signal, attributed to this assistant.
    hit = space.query.list_memories(kind=MemoryKind.FACT).items[0]
    assert hit.access_count >= 1


@pytest.mark.integration
def test_identical_inputs_produce_identical_canonical_behavior() -> None:
    """The directive's core demand: same input through three different wire
    formats → the same search results and the same proposal drafts, differing
    only in freshly minted identities."""
    search_payloads: list[object] = []
    remember_payloads: list[object] = []
    drafts: list[object] = []
    for driver in DRIVERS:
        with_space = build_assistant_space(Path(tempfile.mkdtemp()) / f"{driver.name}.db")
        _seed_fact(with_space)
        adapter = driver.build(with_space.gateway, None)
        search = adapter.handle_tool_call(  # type: ignore[attr-defined]
            driver.make_call("engram_search", {"query": "dark mode"}), CONTEXT
        )
        search_payloads.append(_normalize(driver.payload(search)))
        remember = adapter.handle_tool_call(  # type: ignore[attr-defined]
            driver.make_call("engram_remember", {"conversation": CONVERSATION}), CONTEXT
        )
        payload = driver.payload(remember)
        proposal_id = ProposalId(uuid.UUID(str(payload["proposal_id"])))
        remember_payloads.append(_normalize({**payload, "proposal_id": None}))
        detail = with_space.proposal_queries.get_proposal(proposal_id)
        drafts.append(_normalize(list(detail.drafts)))
    assert len(set(map(str, search_payloads))) == 1
    assert len(set(map(str, remember_payloads))) == 1
    assert len(set(map(str, drafts))) == 1


@pytest.mark.integration
@pytest.mark.parametrize("driver", DRIVERS, ids=lambda d: d.name)
def test_nothing_exists_until_a_human_merges(space: AssistantSpace, driver: Driver) -> None:
    adapter = driver.build(space.gateway, None)
    remember = adapter.handle_tool_call(  # type: ignore[attr-defined]
        driver.make_call("engram_remember", {"conversation": CONVERSATION}), CONTEXT
    )
    payload = driver.payload(remember)
    assert payload["proposal_id"] is not None
    assert "pending review" in str(payload["status"])

    # The pipeline proposed; the substrate is untouched.
    assert not space.query.list_memories(kind=MemoryKind.PERSON).items

    # Only the human surface can execute it.
    proposal_id = ProposalId(uuid.UUID(str(payload["proposal_id"])))
    space.proposals.approve_proposal(proposal_id, "ok", USER)
    space.proposals.merge_proposal(proposal_id, USER)

    found = adapter.handle_tool_call(  # type: ignore[attr-defined]
        driver.make_call("engram_search", {"query": "kind:person Sarah"}), CONTEXT
    )
    found_payload = driver.payload(found)
    assert found_payload["count"] == 1

    status = adapter.handle_tool_call(  # type: ignore[attr-defined]
        driver.make_call("engram_proposal_status", {"proposal_id": str(proposal_id)}),
        CONTEXT,
    )
    assert driver.payload(status)["status"] == "merged"


@pytest.mark.integration
@pytest.mark.parametrize("driver", DRIVERS, ids=lambda d: d.name)
def test_malformed_arguments_come_back_as_wellformed_errors(
    space: AssistantSpace, driver: Driver
) -> None:
    adapter = driver.build(space.gateway, None)
    cases = [
        ("engram_search", {"query": 42}),  # type violation
        ("engram_search", {"query": "x", "surprise": True}),  # unknown key
        ("engram_search", {}),  # missing required
        ("engram_totally_unknown", {"query": "x"}),  # unknown tool
        ("engram_recall", {"memory_id": "not-a-uuid"}),  # invalid id
    ]
    for name, args in cases:
        result = adapter.handle_tool_call(driver.make_call(name, args), CONTEXT)  # type: ignore[attr-defined]
        assert driver.is_error(result), (name, args, result)


@pytest.mark.integration
@pytest.mark.parametrize("driver", DRIVERS, ids=lambda d: d.name)
def test_ungranted_capabilities_degrade_cleanly(space: AssistantSpace, driver: Driver) -> None:
    retrieval_only = frozenset({Capability.RETRIEVAL, Capability.TOOL_CALLING})
    adapter = driver.build(space.gateway, retrieval_only)
    _seed_fact(space)

    search = adapter.handle_tool_call(  # type: ignore[attr-defined]
        driver.make_call("engram_search", {"query": "dark"}), CONTEXT
    )
    assert not driver.is_error(search)

    remember = adapter.handle_tool_call(  # type: ignore[attr-defined]
        driver.make_call("engram_remember", {"conversation": CONVERSATION}), CONTEXT
    )
    assert driver.is_error(remember)
    error_payload = driver.payload(remember)
    assert error_payload["error_type"] == "CapabilityError"
    # And nothing was written by the refused attempt.
    assert not space.proposal_queries.list_proposals().items
