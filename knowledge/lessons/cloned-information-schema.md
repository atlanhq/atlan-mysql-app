# Lessons — MySQL clonedInformationSchema Enhancement

**Date**: 2026-04-24
**Trigger**: REQ-925
**PRs**: connector app (#35), marketplace-packages (#25777), customer docs (#920)

## What went well

- Redshift `clonedPgCatalogSchema` precedent provided a clear, proven pattern — reduced design ambiguity significantly.
- The existing `_replace_database_placeholder()` pattern in both activities and handler gave a natural extension point.
- MySQL views on `INFORMATION_SCHEMA` provide live data (no cron refresh needed) — simpler DBA setup than Redshift's materialized table approach.
- All 29 original tests continued passing without modification — strong backward compatibility signal.

## What was missed (caught in review)

### 1. Application SDK version bump

The initial implementation pinned SDK v2.1.1, but the stable guidance is v2.8.7. Upgrading surfaced a dependency chain issue (protobuf 5.x to 6.x, grpcio 1.72 to 1.80) that required manual resolution.

**Lesson**: Always check the current stable SDK version guidance before starting implementation.

### 2. Marketplace-packages configmap (Crossover mode)

The `workflow.json` changes (adding `control-config-strategy`, `control-config`, and `anyOf` rules) were not mirrored to the marketplace-packages repo (`atlan-mysql-config.yaml` + `atlan-mysql.yaml`). In Crossover mode, both the app's `workflow.json` and the marketplace package's configmap must stay in sync.

**Lesson**: For any workflow template change in a Crossover-mode connector, always create a corresponding PR in `marketplace-packages`.

### 3. SQL identifier validation

The code review bot (mothership-ai) flagged that `clonedInformationSchema` was user-supplied with no sanitization. Added `re.match(r"^[a-zA-Z0-9_]+$")` guard.

**Lesson**: Any user-supplied value that ends up in SQL (even as a schema name, not just a WHERE clause value) must be validated — treat it as an injection vector.

### 4. Retro lessons file not created

The retro was only posted to Linear (APP-2052) but the `knowledge/lessons/` directory was left empty, despite the acceptance criteria requiring "Lessons captured in `knowledge/lessons/*.md`" and PROGRESS.md claiming "Lessons captured."

**Lesson**: When the harness specifies a file artifact as an acceptance criterion, verify the file actually exists — don't mark the step done after only completing the Linear comment.

## What to watch

- **Handler SQL from SDK base class**: `metadata_sql` and `tables_check_sql` come from `BaseSQLHandler` in the SDK. If SDK updates change these, the placeholder insertion may break. Pin SDK version and re-verify after upgrades.
- **Managed MySQL services**: Views on `information_schema` may not work identically in all managed MySQL services (Aurora, Cloud SQL, etc.). The DBA script includes a `CREATE TABLE AS SELECT` alternative as a fallback.

## Key design decisions

1. Default to `"information_schema."` (with trailing dot) — critical MySQL vs Redshift difference.
2. Two placeholders (`{cloned_information_schema}` + `{cloned_schema_exclusion}`) vs Redshift's single `{cloned_schema}`.
3. All 7 SQL files get placeholders (vs Redshift's 3/17) — MySQL needs broader coverage.

## Metrics

- 19 files changed, 2037 insertions, 26 deletions
- 58 new tests (including 4 validation tests), 87 total passing
- 10 enhancement SPEC PRD checks addressed
- Full SDLC cycle: Steps 0 through 8 completed
- 3 PRs total across 3 repos
