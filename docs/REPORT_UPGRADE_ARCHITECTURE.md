# Report Upgrade Evidence Architecture

## Data flow

```text
SearchGateway / search skill
  -> agent raw search envelope
  -> ResultAggregator.raw_search_results
  -> ReportEvidenceContext
  -> ChapterCoverageChecker
  -> ReportEvidenceAcquirer (only when existing evidence is insufficient)
  -> ChapterWriter / revision loop
  -> ReportDefenseAudit + ReportIntegrityChecker
  -> HTML/DOCX output
```

## Evidence contract

Every usable evidence item should preserve:

- `title`, `url`, `snippet` or `evidence_excerpt`;
- `evidence_id`, `provenance_id`;
- `locator`, `task_id`, `request_id`, `retrieved_at` when available;
- section and subsection ownership when the source is assigned to a claim.

Legacy sources are assigned deterministic identities at the report boundary.
The identity material includes the task id for `provenance_id`, so the same
URL in two tasks does not silently share provenance.

## Evidence acquisition order

1. Current chapter structured data;
2. Parent and sibling structured data;
3. Aggregated raw search results;
4. Global evidence registry;
5. `SearchGateway` with `report_generation` or `report_revision` scope.

Search failure produces an insufficient-evidence result. It must never create
a numeric value without a source.

## Quality gates

- L1-L5 issues are normalized with `section_id`, `sub_section_id`, `metric`,
  and `required_action`.
- `ReportIntegrityChecker` assigns stable `claim_id` values and reports
  duplicate claims with their primary section.
- A quantitative claim is not verified without source URL, evidence identity,
  and an evidence excerpt or locator.
- Real E2E must record evidence hit count, external search count, issue delta,
  evidence identity completeness, duplicate claims, and output section rate.

## Legacy compatibility

`DataRepairAgent` remains only as a compatibility adapter for old callers that
construct an orchestrator without a `SearchGateway`. Production report and
revision entry points inject the gateway and use `ReportEvidenceAcquirer`.

## Real E2E prerequisites

The real report-generation resume test requires:

1. a persisted interrupted run with chapter checkpoints;
2. a configured `ANYSEARCH_API_KEY` when external supplementation is needed;
3. an output directory writable by the test process.

When these are absent, the test must report `skipped` rather than being
counted as a successful real-search validation.
