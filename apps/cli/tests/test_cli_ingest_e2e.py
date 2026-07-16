"""M5 end-to-end through the real binary surface: a transcript is ingested by the
pipeline (fake provider — deterministic, no model needed), a proposal opens, a
human reviews/approves/merges, the spine commands move confidence, and replay
reproduces everything."""

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from engram_cli.main import app

runner = CliRunner()

_QUOTE = "my colleague Sarah Chen is joining the kahnya project"

_TRANSCRIPT = f"""USER: Quick intro — {_QUOTE}.
ASSISTANT: Great, noted.
"""

_RESPONSES = {
    "evidence-extraction": json.dumps(
        [{"quote": _QUOTE, "evidence_type": "quote", "reason": "a person enters the graph"}]
    ),
    "candidate-generation": json.dumps(
        [
            {
                "kind": "person",
                "title": "Sarah Chen",
                "content": "Colleague on the kahnya project.",
                "attributes": {"full_name": "Sarah Chen"},
                "evidence_quotes": [_QUOTE],
                "links": [],
            }
        ]
    ),
}


def _extract(pattern: str, output: str) -> str:
    match = re.search(pattern, output)
    assert match, output
    return match.group(1)


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ENGRAM_DATA_DIR", str(tmp_path / "engram"))
    monkeypatch.setenv("ENGRAM_DB_PATH", str(tmp_path / "engram" / "engram.db"))
    responses = tmp_path / "responses.json"
    responses.write_text(json.dumps(_RESPONSES), encoding="utf-8")
    monkeypatch.setenv("ENGRAM_LLM_PROVIDER", "fake")
    monkeypatch.setenv("ENGRAM_LLM_FAKE_RESPONSES", str(responses))
    assert runner.invoke(app, ["init"]).exit_code == 0
    return tmp_path


@pytest.mark.integration
def test_ingest_to_merged_memory_end_to_end(space: Path) -> None:
    transcript = space / "conversation.txt"
    transcript.write_text(_TRANSCRIPT, encoding="utf-8")

    result = runner.invoke(
        app, ["ingest", str(transcript), "--actor", "claude", "--session", "s-1"]
    )
    assert result.exit_code == 0, result.output
    proposal_id = _extract(r"opened proposal ([0-9a-f-]{36})", result.output)

    # Nothing exists until a human merges — the pipeline only proposed.
    result = runner.invoke(app, ["list"])
    assert "Sarah Chen" not in result.output

    result = runner.invoke(app, ["proposals", "show", proposal_id])
    assert result.exit_code == 0, result.output
    assert "create_memory" in result.output
    assert "add_evidence" in result.output

    assert runner.invoke(app, ["proposals", "approve", proposal_id, "-n", "ok"]).exit_code == 0
    result = runner.invoke(app, ["proposals", "merge", proposal_id])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["list"])
    assert "Sarah Chen" in result.output
    result = runner.invoke(app, ["search", "kind:person Sarah"])
    assert result.exit_code == 0
    memory_id = _extract(r"([0-9a-f-]{36})", result.output)

    # The merge carried the evidence in the same atomic batch.
    show = runner.invoke(app, ["show", memory_id])
    assert show.exit_code == 0
    assert "MemoryEvidenceAdded" in show.output

    # Spine commands: confirm raises confidence, contradict decays it.
    before = float(_extract(r"confidence: (\d\.\d+)", show.output))
    confirmed = runner.invoke(app, ["confirm", memory_id, "-n", "met her"])
    assert confirmed.exit_code == 0, confirmed.output
    after = float(_extract(r"confidence (\d\.\d+)", confirmed.output))
    assert after > before

    result = runner.invoke(app, ["importance", memory_id, "--pin", "--weight", "0.9"])
    assert result.exit_code == 0 and "pinned" in result.output

    result = runner.invoke(app, ["show", memory_id, "--track"])
    assert result.exit_code == 0
    assert "1 access(es)" in result.output

    # Replay determinism across the whole M5 lifecycle.
    result = runner.invoke(app, ["rebuild"])
    assert result.exit_code == 0, result.output
    rebuilt = runner.invoke(app, ["show", memory_id])
    assert f"confidence: {after:.2f}" in rebuilt.output
    assert "pinned" in rebuilt.output
    status = runner.invoke(app, ["status"])
    assert status.exit_code == 0 and "DRIFTED" not in status.output


@pytest.mark.integration
def test_ingest_with_nothing_durable_writes_nothing(space: Path) -> None:
    transcript = space / "smalltalk.txt"
    transcript.write_text("USER: nice weather!\nASSISTANT: indeed.\n", encoding="utf-8")
    responses = space / "responses.json"
    responses.write_text(json.dumps({"evidence-extraction": "[]"}), encoding="utf-8")

    result = runner.invoke(app, ["ingest", str(transcript)])
    assert result.exit_code == 0, result.output
    assert "nothing to propose" in result.output
    assert runner.invoke(app, ["proposals", "list"]).output.startswith("no proposals")
