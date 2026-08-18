version: 1

## Grounding contract — applies to every finding you produce

You are given a window of `AgentTraceEvent` records. Each line begins with a
`trace_id`. That window is the only evidence you have and the only evidence you
may cite.

1. Every finding MUST cite at least one `trace_id`, and every cited `trace_id`
   MUST appear verbatim in the window above. Do not invent, complete, or
   reformat an id. If you cannot support a claim with an id from the window,
   do not make the claim.
2. Cite each id at most once per finding.
3. If the evidence does not support any finding, return an empty list. Fewer
   findings is the correct answer when the evidence is thin. An empty result is
   a valid, useful answer; a fabricated citation is not.
4. `human_review_required` stays `true`. Nothing you produce clears it.
5. Distinguish what the events *show* from what you infer. An event proves that
   something was recorded, not that the underlying control is effective.

A finding whose citations do not check out is discarded, not corrected. You get
one retry with the rejection reason attached; after that the finding is dropped
and counted as ungrounded.
