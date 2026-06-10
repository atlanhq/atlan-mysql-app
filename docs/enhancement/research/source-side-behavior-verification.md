# internal-ref — source-side behavior verification

> Required artifact per the enhance-harness silent-no-op gate
> (validator.md `full` profile, check #6b). The activity-success signal
> is not sufficient — we verify the new code path actually executed by
> probing the source DB directly.

## Tenant + run identifiers

- **Tenant**: `<tenant-domain>` (vcluster `<vcluster-name>`)
- **Source MySQL**: `atlan-mysql.crmgvlgwn1cx.ap-south-1.rds.amazonaws.com:3306`
- **Connection**: `default/mysql/1779432936` (Atlan connection name `test2`)
- **AE workflow**: `mysql-FT5sr9pr`

## Verification protocol — drop-and-rerun probe

The mirror-schema flow's contract is:
> When `control-config-strategy = "custom"` and
> `control-config = {"clonedInformationSchema": "<schema>"}` are submitted,
> every templated SQL query is rewritten from `information_schema.<table>`
> to `<schema>.<table>` before execution.

If the rewrite **fires**, the connector queries `atlan_meta.SCHEMATA` /
`TABLES` / `COLUMNS` / `ROUTINES` instead of `information_schema.*`.
If it does **not** fire (silent no-op — the bug we just fixed), the
connector queries native `information_schema.*` regardless.

The cheapest binary probe: **drop the target schema**. If the rewrite
fires, extract activities fail loudly with `Unknown database
'atlan_meta'`. If it doesn't fire, extract succeeds against native
information_schema (the false-positive failure mode that bit production).

## Verification matrix

| Phase | Build SHA | `atlan_meta` exists? | Expected | Observed | Verdict |
|---|---|---|---|---|---|
| A (prior) | `3a33ab1` (no fix) | ✅ | resolver no-op → success | extract Succeeded, 1 db / 24 schemas / 160 tables / 3490 cols | inconclusive — both rewrite-fired and rewrite-skipped paths can succeed when atlan_meta has the same data |
| B (prior fix) | `a82d5a0` (stash-on-self) | ❌ dropped | resolver fires → activity fails | extract **Succeeded** (silent no-op) | **bug exposed** — stash-on-self does not survive workflow→activity worker boundary |
| **B (real fix)** | `a8f6e87` | ❌ dropped | resolver fires → activity fails | extract **Failed** with `(1049, "Unknown database 'atlan_meta'")` | **✅ FIX VERIFIED** |
| **A (real fix)** | `a8f6e87` | ✅ recreated | resolver fires → success against mirror | extract Succeeded with the same counts on the mirror | **✅ HAPPY PATH VERIFIED** |

## Why the prior fix silently no-op'd

`MySQLApp.run()` stashed `self._control_config = extract_control_config(input)`
before dispatching extract tasks. But each `@task` invocation runs on a
fresh `app_instance = app_cls()` (per the SDK's
`application_sdk/app/base.py:1478`). The stash was set on the workflow
worker's instance and was invisible to the activity worker's instance.
The activity's `_prepare_sql` saw `self._control_config = {}` (class
default) and the resolver was a no-op.

## Why the real fix works

Three reinforcing changes:

1. `MySQLExtractionTaskInput(ExtractionTaskInput,
   allow_unbounded_fields=True)` declares `control_config_strategy` and
   `control_config` as typed fields.
2. `MySQLApp.build_task_input` overrides the SDK staticmethod to
   construct `MySQLExtractionTaskInput` populated from the workflow
   input — so control-config travels ON the task input, not on `self`.
3. The five `extract_*` `@task` methods are overridden with annotation
   `MySQLExtractionTaskInput` — only then does activity-side pydantic
   reconstruction preserve the typed fields (the SDK base
   `ExtractionTaskInput` defaults to `extra='ignore'` and would strip
   them).

`_prepare_sql` reads `extract_control_config(input)` from the task
input arg — which now carries the typed fields across the worker
boundary.

## Raw evidence

### Probe A: drop `atlan_meta`, expect activity failure

```sql
mysql> DROP DATABASE atlan_meta;
Query OK, 8 rows affected (0.02 sec)
mysql> SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='atlan_meta';
+----------+
| COUNT(*) |
+----------+
|        0 |
+----------+
```

```text
# AE run a7beb89c-5cbd-4ea4-bff1-45757563314a (Phase B on a8f6e87)
AE status: Failed
  extract: Failed
     err: (1049, "Unknown database 'atlan_meta'")
  qi:      Failed
  publish: Failed

# Temporal extract activity
2026-05-22T10:13:30 ACTIVITY FAILED — Error executing SQL query
worker: 20@mysql-worker-twd-aisdlc-internal-ref-cloned-information-schema-dqp2z
```

### Probe B: re-create `atlan_meta`, expect activity success on mirror

```sql
mysql> SELECT TABLE_NAME FROM information_schema.TABLES
       WHERE TABLE_SCHEMA='atlan_meta';
COLUMNS, KEY_COLUMN_USAGE, PARTITIONS, ROUTINES,
SCHEMATA, TABLES, TABLE_CONSTRAINTS, VIEWS
```

```text
# AE run b0979699-a394-4ea8-8082-29e1fe611ac0 (Phase A on a8f6e87)
# Temporal extract activity record counts (queries against atlan_meta.*):
  mysql:extract_databases:  records=1
  mysql:extract_schemas:    records=25
  mysql:extract_tables:     records=168
  mysql:extract_columns:    records=3624
  mysql:extract_procedures: records=1

# Workflow result payload:
WORKFLOW COMPLETED — connection_qualified_name='default/mysql/1779432936'
  transformed_data_prefix=artifacts/apps/mysql/workflows/b0979699-…-extract/…
  storage_bucket=<vcluster-bucket>

worker: 20@mysql-worker-twd-aisdlc-internal-ref-cloned-information-schema-dqp2z
```

## Final

| Check | Status |
|---|---|
| Build `a8f6e87` deployed to `apps-typedef` (HelmRelease `mysql-app`, revision 348+) | ✅ |
| Drop-probe — activity fails loudly with `Unknown database 'atlan_meta'` | ✅ |
| Recreate-probe — activity succeeds against `atlan_meta.*` mirror views | ✅ |
| Backward-compat — default code path (no control-config) still queries native `information_schema` | ✅ (covered by `tests/unit/test_mysql_app.py::test_prepare_sql_resolves_default_information_schema` and `tests/integration/test_mirror_schema.py::TestDefaultPathStillWorks`) |

internal-ref mirror-schema flow is wired end-to-end and verified on the
live tenant by direct source-DB probe. Silent-no-op failure mode is
covered by two new regression tests in `tests/unit/test_mysql_app.py`:

- `test_build_task_input_threads_control_config_to_task` — asserts the
  override upgrades `ExtractionTaskInput` to the MySQL subclass with
  fields populated.
- `test_extract_task_signatures_use_mysql_subclass` — asserts the five
  `extract_*` @task methods declare `MySQLExtractionTaskInput`, so
  activity-side pydantic round-trip preserves control-config.
