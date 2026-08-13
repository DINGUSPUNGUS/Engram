/**
 * A draft intent is an arbitrary, versioned, op-discriminated dict
 * (`engram_core.application.commands.drafts.to_dict`) — the dashboard
 * never interprets its meaning, but every draft shape names its target
 * memory under one of these three keys (`memory_id` for single-memory
 * ops, `source_id`/`target_id` for link ops). Reading a key that's
 * already part of the public wire format is presentation, not a decision.
 */
export function draftTargetId(draft: Record<string, unknown>): string | undefined {
  const id = draft.memory_id ?? draft.source_id ?? draft.target_id;
  return typeof id === "string" ? id : undefined;
}
