# ADR-0025: Projection logic bugs are caught by differential rebuild, not a second source of truth

- **Status**: Accepted
- **Date**: 2026-08-14

## Context

`engram status` already detects *drift*: a projection whose checkpoint trails the log
head (status.py, `ProjectionHealth.lag`). That catches a crash between append and
apply, or a projection added after a migration. It cannot catch the other failure
mode: a projection that is fully caught up (`lag == 0`) but computed the *wrong*
state — an off-by-one in a merge rule, a field mapping bug, a case an event handler
never accounted for. Checkpoint tracks *position* in the log, never *content*; a
buggy projection reports exactly as healthy as a correct one, forever, under lag
alone. This was a standing M9 hardening finding (P1).

The obvious-looking fix — keep an independent, second computation of "what the state
should be" to compare against — is exactly what the architecture's disposability
contract (a projection is disposable and reconstructable from the event log, never a
second source of truth) rules out: an independent oracle can itself drift, and now
there are two things to keep correct instead of one.

## Decision

Detect content corruption with a **differential rebuild**, not a second oracle:
replay the identical event log into a fresh, throwaway copy of `StateProjection` and
compare a deterministic content fingerprint (`StateProjection.fingerprint()`, a
sha256 over every row in canonical order) against the live projection's fingerprint.

Both fingerprints come from the *same* projection code reading the *same* log — one
built incrementally as live writes happened, one in a single bulk pass, right now. A
mismatch is the projection's own logic disagreeing with itself, not disagreement with
an independent implementation — so there is nothing new to keep in sync, and the
scratch copy (`verify_projection_fidelity`, `engram_storage_sqlite.maintenance`) is
discarded immediately after each check.

The comparison is only meaningful when both sides replayed the identical prefix of
the log (`ProjectionFidelityReport.comparable`, i.e. equal checkpoints) — a lagging
live projection is expected to disagree with a full rebuild and that is not evidence
of a logic bug, just of the lag `status.py` already reports.

Surfaced as `engram status --verify`: opt-in, not automatic, because it costs what a
full `engram rebuild` costs (a complete log replay). Ordinary `engram status` stays
cheap (checkpoint reads only).

## Consequences

- A projection logic bug is now provably detectable without trusting "it looked fine
  in review" — a real invariant, not developer discipline. ✔
- No second source of truth was introduced; the mechanism is self-consistency of one
  implementation against itself, matching the existing disposability contract. ✔
- `--verify` is O(log size) — expensive on a large space. Deliberately opt-in, not
  wired into ordinary `status`, CI, or a background job. Accepted; the alternative
  (running it unconditionally) would make routine `status` calls slow for no benefit
  on the overwhelmingly common healthy case.
- Detects that content diverged and gives fingerprints to compare, not *which* event
  or field caused it — root-causing a real finding is still a manual investigation
  aided by `engram_storage_sqlite.projections.state`'s per-event-type dispatch, not
  automated by this ADR.

## Alternatives considered

- **Independent read-model computation (e.g. a second, differently-implemented
  projection) as ground truth**: exactly the "second source of truth that can itself
  drift" the disposability contract rejects, and doubles the surface area needing
  maintenance for no proportional benefit over a bulk rebuild of the same code.
- **Event-derived assertions embedded per event handler** (e.g. invariant checks
  inside `_apply_event`): catches some bugs but only ones anticipated when writing
  the assertion — no better than the existing tests, and scatters verification logic
  across every event case instead of one general-purpose check.
- **Continuous background verification**: real-time confidence, but distributed
  scheduling infrastructure this project's ADRs (and M9's explicit scope) rule out
  for a local-first, single-process system. On-demand opt-in serves the same need
  without it.
