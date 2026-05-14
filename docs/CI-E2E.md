# Connector CI: SDR + Full-DAG E2E

> **Audience:** Other connector teams using this repo as a reference when wiring up the two end-to-end test pipelines for their own app.
> **Canonical truth:** The composite action + reusable workflow live in [atlanhq/application-sdk](https://github.com/atlanhq/application-sdk) — this doc walks through the connector-side wiring using mysql-app as the example.

## The two pipelines

| Pipeline | What it validates | Stack | Wall time | Triggers |
|---|---|---|---|---|
| **SDR Integration Tests (testcontainer)** | SDR credential → secret-store → connector-client chain. Auth/preflight/extract workflow polled to `COMPLETED` against the CI tenant's Temporal. | Hermetic: sibling `mysql:8.0` testcontainer + worker + Dapr + Temporal. | ~3 min | Auto on every PR push |
| **E2E Full Tests (system apps)** | Full DAG: extract → publish → query-intelligence → lineage-app → lineage-publish. Asset counts + lineage assertions in Atlas. | Live: configurator-generated compose, worker on a dynamic Temporal queue, against the CI tenant's full Atlan stack. | ~20–40 min | Label-gated (`e2e-full`) |

Both pipelines call the same SDK-side composite action (`atlanhq/application-sdk/.github/actions/sdr-e2e@main`). They differ in test target, Dapr components, compose overlay, and secret-bundle shape.

---

## What this repo has (so you know what to copy)

```
atlan-mysql-app/
├── app.yaml                              # ← REQUIRED. atlan-configurator input. 3 lines.
├── .github/
│   ├── CODEOWNERS                        # auto-request connector owner on PRs
│   ├── workflows/
│   │   ├── sdr-integration-tests.yaml    # SDR pipeline wrapper (~110 LOC)
│   │   └── e2e-full.yaml                 # Full-DAG pipeline wrapper (~75 LOC)
│   └── e2e/
│       ├── docker-compose.ci.yml         # SDR overlay: sibling mysql:8.0 + seed mount
│       ├── e2e-full-docker-compose.yaml  # Full-DAG overlay: worker + ATLAN_AGENT_NAME + AWS env
│       ├── e2e-full-components/
│       │   └── objectstore.yaml          # S3 OAuth blobstorage binding for full-DAG only
│       ├── seed.sql                      # testcontainer seed data
│       ├── make-secrets.py               # SDR: NESTED bundle (mysql-credentials key, multi-key mode)
│       └── make-secrets-e2e-full.py      # Full-DAG: FLAT bundle (SDR_MYSQL_* top-level, single-key mode)
└── tests/
    ├── sdr/test_mysql_sdr.py             # SDR scenarios (auth_*, preflight_*, workflow_*)
    └── full_dag/test_mysql_full_dag.py   # ~60 LOC of mysql overrides on SQLAppE2EFullTest
```

Nothing in `.github/sdr-e2e/` — this repo uses the legacy `.github/e2e/` location, still accepted as a `$SDR_CONFIG_DIR` fallback by the SDK action.

---

## SDR (testcontainer) pipeline

### `app.yaml` at repo root

```yaml
app_name: mysql
app_image: ${APP_IMAGE}    # envsubst'd at run time after the action's docker build step
app_port: 8000
```

Required since SDK [#1746](https://github.com/atlanhq/application-sdk/pull/1746). The composite action does `envsubst < app.yaml > app-resolved.yaml` and feeds it to `atlan-configurator --app`.

### `.github/workflows/sdr-integration-tests.yaml`

Single job invoking the SDR composite action. Two paths:

- **Path A** (connector PRs): action ref pinned to `@main`, uses the SDK from your `pyproject.toml`.
- **Path B** (apps-sdk cross-repo dispatch): checks out `application-sdk` at the dispatched ref into `.application-sdk/`, then invokes the local action — exercises SDK changes end-to-end without a release.

The composite handles: GHCR image build, configurator download + invocation, Dapr component overrides, container start, pytest, Temporal link extraction, PR comment, teardown.

### Test scenarios

Subclass `BaseSDRIntegrationTest` (in the SDK), declare `Scenario(...)` instances. See [`tests/sdr/test_mysql_sdr.py`](../tests/sdr/test_mysql_sdr.py) — auth + preflight + workflow coverage with valid + invalid credentials + wrong-host edges.

### Secrets bundle (`make-secrets.py`)

Writes `.github/e2e/secrets/credentials.json` with a **nested** bundle:
```json
{"mysql-credentials": "{\"username\": \"e2e_user\", \"password\": \"e2e_pass\"}"}
```
Read by the Dapr `local.file` secret store under the `secret-path: mysql-credentials` ref in your agent_json. Multi-key bundle mode.

---

## Full-DAG (system apps) pipeline

### `.github/workflows/e2e-full.yaml`

Five-line wrapper around the reusable workflow:

```yaml
uses: atlanhq/application-sdk/.github/workflows/e2e-full-reusable.yaml@main
with:
  app-name: mysql
  app-image-name: atlan-mysql-app
  agent-name-override: ${{ inputs.agent_name_override }}
  application-sdk-ref: ${{ inputs.application_sdk_ref }}
  distinct-id: ${{ inputs.distinct_id }}
secrets: inherit
```

The reusable workflow ships the boilerplate (120-min job timeout, concurrency group, env + secret wiring, agent-name resolution, SDR composite invocation with full-DAG-specific component/compose overrides).

### Test class

Subclass `SQLAppE2EFullTest` (from `application_sdk.testing.full_dag.sql_app`). Override only connector-specific knobs:

```python
class TestMySQLFullDAG(SQLAppE2EFullTest):
    connector_short_name = "mysql"
    argo_package_name = "@atlan/mysql"
    argo_template_name = "atlan-mysql"
    mode = RunMode.AGENT
    app_service_url = "http://mysql.mysql-app.svc.cluster.local"

    include_filter = r"^def\.e2e_main$"        # mysql REGEXP form
    qi_input_prefix_field = "transformed_data_prefix"

    expected_min_asset_counts = {
        "Database": 1, "Schema": 1, "Table": 2, "View": 1, "Column": 10,
    }
    expect_lineage = True

    def database_spec(self) -> DatabaseSpec:
        return DatabaseSpec(
            host="mysql", port=3306,
            username="e2e_user", password="e2e_pass",
            connector_config_name="atlan-connectors-mysql",
        )
```

`agent_spec`, `connection_spec`, AE submit, DAG polling, Atlas inventory probe, lineage assertion, PR comment rendering — all live in `SQLAppE2EFullTest`.

### Compose overlay drives worker registration

`.github/e2e/e2e-full-docker-compose.yaml` sets `ATLAN_AGENT_NAME` on the worker container so it registers on the dynamic queue (`atlan-<connector>-e2e-full-ci-<run_id>`) the harness creates the workflow on. Without this, the worker polls the static default queue and no work flows through.

### Secrets bundle (`make-secrets-e2e-full.py`)

Writes `.github/e2e/secrets/credentials.json` with a **flat** bundle:
```json
{"SDR_MYSQL_USERNAME": "e2e_user", "SDR_MYSQL_PASSWORD": "e2e_pass"}
```
Single-key mode — the SDK's `build_ae_payload` emits `agent-json.basic.username = "SDR_MYSQL_USERNAME"` etc. as top-level secret-store key refs.

---

## Repo-level GitHub Actions secrets to set

| Secret | Used by | Notes |
|---|---|---|
| `SDR_TEST_TENANT` | both | DNS short name (e.g. `dev-tenant` for `<tenant-domain>`) |
| `SDR_CLIENT_ID` / `SDR_CLIENT_SECRET` | both | Configurator OAuth credentials |
| `ATLAN_BASE_URL` | full-DAG | Full URL (e.g. `https://<tenant-domain>`) |
| `ATLAN_API_KEY` | full-DAG | Bearer for AE-management calls. Service account must carry `realm-admin`. Rotates ~weekly — set a calendar reminder. |
| `SDR_OAUTH_CLIENT_ID` / `SDR_OAUTH_CLIENT_SECRET` | full-DAG | OAuth client for Dapr S3 binding via tenant's `/api/blobstorage` proxy + pyatlan asset queries. Optional — falls back to API key. |

Same set used by `atlan-mssql-app` — copy values from there, or grab from `internal-security-channel`.

---

## Cross-repo dispatch (validating SDK changes against this connector)

Two label-gated paths on `atlanhq/application-sdk` PRs:

| Job on apps-sdk PR | Connector workflow dispatched | Label |
|---|---|---|
| `SDR Integration Tests (testcontainer) — atlan-mysql-app` | `sdr-integration-tests.yaml` | _none — auto-runs on every push_ |
| `E2E Full Tests (system apps) — atlan-mysql-app` | `e2e-full.yaml` | `e2e-full-mysql` |

Mechanism: `codex-/return-dispatch@v3` from the SDK's `e2e-apps` action fires `workflow_dispatch` on this repo with the SDK PR's head SHA as `application_sdk_ref`. The connector workflow's Path B checks out application-sdk at that ref + invokes the SDR action via local path. Worker docker image is built from the dispatched ref, host pytest runtime is re-pinned to it too.

The SDK PR gets a sticky comment summarising the dispatched run (asset counts, lineage coverage, validates bullets). Same body posted on both sides with different sticky markers so updates don't collide.

---

## Onboarding a new connector — checklist

1. Add `app.yaml` at repo root (3 lines).
2. Create `.github/workflows/sdr-integration-tests.yaml` and `.github/workflows/e2e-full.yaml` — copy from this repo, swap `mysql`/`atlan-mysql-app`/`@atlan/mysql`/`atlan-mysql` references for your connector.
3. Create `.github/e2e/` (or `.github/sdr-e2e/` if you want the new convention):
   - `docker-compose.ci.yml` — sibling DB container + seed mount.
   - `e2e-full-docker-compose.yaml` — worker overlay with `ATLAN_AGENT_NAME` + AWS env.
   - `e2e-full-components/` — Dapr S3 OAuth binding.
   - `seed.sql` — testcontainer seed.
   - `make-secrets.py` (SDR) + `make-secrets-e2e-full.py` (full-DAG).
4. Write `tests/sdr/test_<connector>_sdr.py` (Scenario instances) + `tests/full_dag/test_<connector>_full_dag.py` (`SQLAppE2EFullTest` subclass).
5. Set repo-level secrets (see table above).
6. Push a PR — SDR pipeline auto-runs. Apply `e2e-full` label to opt in the full-DAG pipeline.
7. Add `<connector>-app` to the apps-sdk side SDR matrix (`atlanhq/application-sdk/.github/workflows/pull_request.yaml`, `sdr-matrix-builder` job's output). For full-DAG, add a per-connector `e2e-full-<connector>` job + label.

---

## Troubleshooting

### `No app.yaml found at .github/e2e/app.yaml or repo root`
You're missing the configurator input. Add the 3-line `app.yaml` at repo root.

### `No Workers Running` on `atlan-<connector>-e2e-full-ci-<run_id>` (Temporal UI)
Worker container is on a different queue than the harness expects. Verify your `e2e-full-docker-compose.yaml` sets `ATLAN_AGENT_NAME` on the worker, and that the reusable workflow passes the overlay through. Fixed by SDK [#1752](https://github.com/atlanhq/application-sdk/pull/1752) for multi-pipeline apps.

### `create_workflow failed: HTTP 401 — Token is expired`
`ATLAN_API_KEY` rotated. Mint a fresh key on the CI tenant (realm-admin service account), update the GH repo secret on this connector and on apps-sdk if needed, re-toggle the label to retrigger.

### `Cancelled 🚫` sticky on SDK PR but the dispatched run completed fine
The SDK-side poll loop has a 7200s ceiling (matches full-DAG's `timeout-minutes: 120`). Long-tail tenant lag can push past this — bump the override or split into a smaller scenario.

### Workspace-wipe errors on dispatched runs (`Can't find action.yml`)
`setup-deps`' internal `actions/checkout` wipes the local action directory when invoked via `./.application-sdk/...`. The composite action stashes its assets to `/tmp/sdr-e2e/` before setup-deps runs and restores them for post-hooks. If you see this, you're on a pre-[#1710](https://github.com/atlanhq/application-sdk/pull/1710) SDK version.

---

## References

- SDK composite action: [`atlanhq/application-sdk/.github/actions/sdr-e2e/action.yaml`](https://github.com/atlanhq/application-sdk/blob/main/.github/actions/sdr-e2e/action.yaml)
- SDK reusable full-DAG workflow: [`atlanhq/application-sdk/.github/workflows/e2e-full-reusable.yaml`](https://github.com/atlanhq/application-sdk/blob/main/.github/workflows/e2e-full-reusable.yaml)
- SDK cross-repo dispatcher: [`atlanhq/application-sdk/.github/actions/e2e-apps/action.yaml`](https://github.com/atlanhq/application-sdk/blob/main/.github/actions/e2e-apps/action.yaml)
- SDK full-DAG harness: [`atlanhq/application-sdk/application_sdk/testing/full_dag/`](https://github.com/atlanhq/application-sdk/tree/main/application_sdk/testing/full_dag)
- Key SDK PRs:
  - [#1669](https://github.com/atlanhq/application-sdk/pull/1669) — SDR composite action + pytest base
  - [#1710](https://github.com/atlanhq/application-sdk/pull/1710) — Cross-repo dispatch + full-DAG harness
  - [#1746](https://github.com/atlanhq/application-sdk/pull/1746) — `.github/sdr-e2e/` convention + `app.yaml`
  - [#1752](https://github.com/atlanhq/application-sdk/pull/1752) — Restored `components-dir` / `compose-overlay` overrides for multi-pipeline apps
