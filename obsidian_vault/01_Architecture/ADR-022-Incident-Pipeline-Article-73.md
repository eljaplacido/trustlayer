---
adr: 22
title: Art. 73 Incident Pipeline
date: 2026-08-02
status: proposed
---

# ADR-022 — Art. 73 Incident Pipeline

## Context

Art. 73 obliges providers of high-risk AI systems to report serious
incidents to the market surveillance authority without undue delay, under
hard deadlines:

| Trigger | Deadline from awareness |
|---|---|
| Serious incident (general) | **15 days** |
| Death of a person may have been caused | **10 days** |
| Widespread infringement, or serious disruption of critical infrastructure | **2 days** |

The Commission published draft guidance and a reporting template
(consultation closed 2025-11-07). With the Digital Omnibus deferral,
Art. 73 travels with the high-risk obligations to 2027-12-02, but the
template and the guidance exist now — and a pipeline that only starts
collecting when the obligation bites has no incident history to draw on.

TrustLayer has no incident concept at all (G6). Guardian already observes
the signals that would trigger one; nothing turns them into a tracked
record with a clock.

## Decision

### 1. An incident is a record with a lifecycle, not an event

Trace events are immutable facts. An incident is a mutable case that moves
through states and accrues human determinations. Modelling it as an event
type would be a category error.

`compliance/incidents/<system-id>/<incident-id>.json`, schema at
`compliance/schemas/incident.schema.json`:

```
DETECTED → ASSESSING → { NOT_REPORTABLE | REPORTABLE } → REPORTED → CLOSED
```

Each transition records who made it and when. `NOT_REPORTABLE` requires a
rationale — deciding *not* to report is the decision most likely to be
scrutinised later, so it is the one the schema forces you to justify.

### 2. The clock starts at awareness, which is a human field

```python
class Incident(BaseModel):
    incident_id: UUID
    system_id: str
    detected_at: datetime               # machine: when a signal fired
    awareness_at: datetime | None       # human: when the provider became aware
    severity_class: SeverityClass | None # human: legal determination
    deadline_at: datetime | None        # derived from the two above
    ...
```

`awareness_at` and `severity_class` are **required human inputs**.
`deadline_at` is derived and is `null` until both exist — the tool never
guesses when a legal clock started. An incident with a null
`severity_class` is shown as "unclassified — clock not running", never as
compliant.

Once set, the countdown surfaces in the CLI (`trustlayer-incidents list`,
non-zero exit when any deadline is inside 48h), the dashboard, and an
optional webhook. Deadlines are computed in calendar days per the
regulation, with the applicable timezone recorded.

### 3. Triggers propose; they never file

Three sources create a `DETECTED` incident:

1. **Guardian signals** — a policy rule may carry
   `incident_candidate: true`, so a `FAIL` on a designated rule opens a
   candidate.
2. **Workflow critic findings** (ADR-020) above a severity threshold.
3. **Operator action** — `trustlayer-incidents open`.

All three produce a candidate requiring human assessment. Nothing
auto-classifies as serious, nothing auto-files, and no integration submits
to an authority. The platform's job ends at a complete, evidenced draft
(P4).

### 4. Evidence attaches by reference, and integrity is checked

An incident cites `trace_id`s and a `seq_range`. On transition to
`REPORTABLE`, the pipeline verifies the integrity chain over that range
(ADR-017) and records the result. An incident whose evidence chain fails
verification is flagged prominently — that is exactly the circumstance in
which someone would have had a motive to alter the log, and it must never
be a quiet field.

Incident evidence is also **pinned against retention**: cited events are
exempt from eviction regardless of the retention target, until the
incident reaches `CLOSED` plus the Art. 18 horizon.

### 5. Template export

`compliance/templates/eu-incident-report.yaml` maps incident fields to the
Commission template's fields. Export produces Markdown and JSON plus a
completeness check listing missing mandatory fields. The mapping file is
versioned and dated, because the template is still draft — a version bump
is a visible change, not a silent reinterpretation.

The `document_author` role (ADR-020) drafts narrative sections; every
drafted section is marked unapproved per ADR-021 §3.

## Consequences

- New CLI `trustlayer-incidents` and a dashboard surface. Both display
  countdowns with the "clock not running" state made explicit rather than
  rendered as zero or blank.
- Retention pinning introduces a second reason an event cannot be evicted,
  alongside ADR-017's floor. Both are reported by the same metric family
  so operators see one coherent picture of what is holding storage.
- The `NOT_REPORTABLE` path deliberately creates a record of a negative
  decision. Some users will find this uncomfortable; it is the correct
  behaviour and `compliance/README.md` explains why.
- **Limits stated in-product:** whether an event is a "serious incident"
  under Art. 3(49) is a legal determination. TrustLayer computes
  deadlines, assembles evidence, and drafts reports. It does not classify
  incidents and it does not submit them.
