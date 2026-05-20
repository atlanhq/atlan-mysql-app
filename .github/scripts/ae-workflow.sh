#!/usr/bin/env bash
# ae-workflow.sh — Publish the 5-node MYSQL DAG
# (extract → qi + publish → lineage-app → lineage-publish).
#
# Replaces the prior 2-node ``extract → publish`` script. Production
# tenants now run the same DAG that ``ae-publish-test.yaml`` exercises
# locally, so QI + lineage trigger automatically after extract.
#
# Notes:
#   • ``lake_provider`` is forwarded from extract via
#     ``$.extract.outputs.lake_provider``. The extractor reads GCP_BUCKET /
#     S3_BUCKET to decide ``gcs`` / ``aws``, falling back to ``local`` for CI
#     where neither is set.
#   • ``parsing_mode: lorien-only`` skips the 124 MB Gudusoft LFS jar.
#   • ``--token`` adds ``Authorization: Bearer`` to every AE call;
#     omit for unauthenticated local AE.
#   • If a published workflow with the same name already exists we DON'T
#     short-circuit — we push a new version of the DAG and publish it,
#     so re-deploys actually propagate DAG drift (queue names, args).
#
# Usage (production tenant):
#   bash scripts/ae-workflow.sh \
#     --ae-url           https://my-<tenant-domain>/automation \
#     --token            "$ATLAN_API_KEY" \
#     --name             "MYSQL Extract + Publish" \
#     --cred-guid        <guid> \
#     --connection-qn    default/mysql/test \
#     --connection-name  test_mysql \
#     --mysql-queue      atlan-mysql-production \
#     --publish-queue    atlan-publish-production \
#     --qi-queue         atlan-query-intelligence-production \
#     --lineage-queue    atlan-lineage-production
#
# Usage (local CI):
#   bash scripts/ae-workflow.sh \
#     --ae-url   http://localhost:8000 \
#     --name     "MYSQL 5-node CI" \
#     --cred-guid       ci-mysql-cred \
#     --connection-qn   default/mysql/ci \
#     --connection-name ci_mysql \
#     --mysql-queue     atlan-mysql-ci \
#     --publish-queue   atlan-publish-ci \
#     --qi-queue        atlan-query-intelligence-ci \
#     --lineage-queue   atlan-lineage-ci

set -euo pipefail

AE_URL="http://localhost:8000"
WF_NAME=""
CRED_GUID="local-mysql-cred-001"
CONN_QN="default/mysql/test"
CONN_NAME="test_mysql"
MYSQL_QUEUE="atlan-mysql-local"
PUBLISH_QUEUE="atlan-publish-local"
QI_QUEUE="atlan-query-intelligence-local"
LINEAGE_QUEUE="atlan-lineage-local"
TOKEN=""
CONNECTION_CREATION_ENABLED="false"
# Publish-side flags. Defaults match production tenants (real Atlas write +
# cache population). CI overrides to "false" so publish stays in dry-run
# (no OAuth, no real Atlas calls).
EXECUTOR_ENABLED="true"
CONNECTION_CACHE_ENABLED="true"
CONNECTION_CACHE_VIA_APP_ENABLED="true"

while [[ $# -gt 0 ]]; do
  case $1 in
    --ae-url)                    AE_URL="$2";                    shift 2 ;;
    --token)                     TOKEN="$2";                     shift 2 ;;
    --name)                      WF_NAME="$2";                   shift 2 ;;
    --cred-guid)                 CRED_GUID="$2";                 shift 2 ;;
    --connection-creation-enabled) CONNECTION_CREATION_ENABLED="$2"; shift 2 ;;
    --executor-enabled)          EXECUTOR_ENABLED="$2";          shift 2 ;;
    --connection-cache-enabled)  CONNECTION_CACHE_ENABLED="$2";  shift 2 ;;
    --connection-cache-via-app-enabled) CONNECTION_CACHE_VIA_APP_ENABLED="$2"; shift 2 ;;
    --connection-qn)   CONN_QN="$2";        shift 2 ;;
    --connection-name) CONN_NAME="$2";      shift 2 ;;
    --mysql-queue)     MYSQL_QUEUE="$2";    shift 2 ;;
    --publish-queue)   PUBLISH_QUEUE="$2";  shift 2 ;;
    --qi-queue)        QI_QUEUE="$2";       shift 2 ;;
    --lineage-queue)   LINEAGE_QUEUE="$2";  shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

# Auth header injected into every AE call when --token is set or ATLAN_API_KEY is in env.
[ -z "$TOKEN" ] && TOKEN="${ATLAN_API_KEY:-}"
CURL_AUTH=()
[ -n "$TOKEN" ] && CURL_AUTH=(-H "Authorization: Bearer $TOKEN")

[ -z "$WF_NAME" ] && WF_NAME="MYSQL Extract"

err() { echo "ERROR: $*" >&2; exit 1; }
log() { echo "$*" >&2; }

# --- Reuse-or-create: same-name PUBLISHED workflow → push a new
#     version onto its slug; otherwise create a new workflow.
EXISTING_SLUG=$(curl -s "${CURL_AUTH[@]}" "$AE_URL/api/v1/workflows" | python3 -c "
import json, sys
wfs = json.load(sys.stdin).get('data', [])
for w in wfs:
    if w.get('name') == '''$WF_NAME''' and w.get('status') == 'PUBLISHED':
        print(w['slug'])
        break
" 2>/dev/null || true)

if [ -n "$EXISTING_SLUG" ]; then
  log "Found existing published workflow: $EXISTING_SLUG — pushing a new version"
  SLUG="$EXISTING_SLUG"
else
  log "Creating workflow: $WF_NAME"
  CREATE_RESP=$(curl -s -X POST "$AE_URL/api/v1/workflows" \
    "${CURL_AUTH[@]}" \
    -H "Content-Type: application/json" \
    -d "{\"name\": \"$WF_NAME\", \"description\": \"MYSQL 5-node DAG: extract -> qi + publish -> lineage-app -> lineage-publish\"}")

  SLUG=$(echo "$CREATE_RESP" | python3 -c "
import json, sys
d = json.load(sys.stdin)
s = d.get('data', {}).get('slug') or d.get('slug')
if not s:
    raise ValueError('No slug in response: ' + json.dumps(d))
print(s)
") || err "Failed to create workflow: $CREATE_RESP"

  log "Workflow slug: $SLUG"

  # Wait for AE to index the new workflow before creating a version.
  # The creation API returns the slug immediately but the workflow may
  # not be visible to subsequent calls for a short time on production AE.
  sleep 3
fi

# --- Create version with full 5-node DAG ---
# Retry up to 3 times — on production AE the workflow may not be
# immediately findable after creation (propagation delay).
VERSION=$(date +%s)
for _attempt in 1 2 3; do
  VERSION_RESP=$(curl -s -X POST "$AE_URL/api/v1/workflows/$SLUG/versions" \
  "${CURL_AUTH[@]}" \
  -H "Content-Type: application/json" \
  -d "{
    \"version\": $VERSION,
    \"dag\": {
      \"extract\": {
        \"node_type\": \"workflow\",
        \"activity_name\": \"execute_workflow\",
        \"activity_display_name\": \"Extract MYSQL Metadata\",
        \"app_name\": \"mysql\",
        \"app_task_queue\": \"$MYSQL_QUEUE\",
        \"inputs\": {
          \"workflow_type\": \"mysql-metadata-extractor\",
          \"app_id\": \"\",
          \"task_queue\": \"$MYSQL_QUEUE\",
          \"args\": {
            \"credential_guid\": \"$CRED_GUID\",
            \"connection\": {
              \"connection_name\": \"$CONN_NAME\",
              \"connection_qualified_name\": \"$CONN_QN\"
            },
            \"extraction_method\": \"direct\",
            \"include_filter\": \"\",
            \"exclude_filter\": \"\",
            \"temp_table_regex\": \"\"
          }
        }
      },
      \"qi\": {
        \"node_type\": \"workflow\",
        \"activity_name\": \"execute_workflow\",
        \"activity_display_name\": \"Parse View Lineage\",
        \"app_name\": \"query-intelligence\",
        \"app_task_queue\": \"$QI_QUEUE\",
        \"inputs\": {
          \"workflow_type\": \"QueryIntelligenceWorkflow\",
          \"task_queue\": \"$QI_QUEUE\",
          \"args\": {
            \"connection_qualified_name\": \"\$.extract.outputs.connection_qualified_name\",
            \"vendor_name\": \"mysql\",
            \"sql_key\": \"attributes.definition\",
            \"catalog_key\": \"attributes.databaseName\",
            \"schema_key\": \"attributes.schemaName\",
            \"timestamp_key\": \"\",
            \"mine_output_type\": \"json\",
            \"parsing_mode\": \"lorien-only\",
            \"lake_provider\": \"\$.extract.outputs.lake_provider\",
            \"storage_bucket\": \"\$.extract.outputs.storage_bucket\",
            \"input_prefix\": \"\$.extract.outputs.view_data_prefix\",
            \"output_prefix\": \"\$.extract.outputs.view_lineage_output_prefix\"
          }
        },
        \"depends_on\": {\"node_id\": \"extract\"}
      },
      \"publish\": {
        \"node_type\": \"workflow\",
        \"activity_name\": \"execute_workflow\",
        \"activity_display_name\": \"Publish to Atlas\",
        \"app_name\": \"publish\",
        \"app_task_queue\": \"$PUBLISH_QUEUE\",
        \"inputs\": {
          \"workflow_type\": \"PublishWorkflow\",
          \"task_queue\": \"$PUBLISH_QUEUE\",
          \"args\": {
            \"connection_qualified_name\": \"$CONN_QN\",
            \"transformed_data_prefix\": \"\$.extract.outputs.transformed_data_prefix\",
            \"publish_state_prefix\": \"\$.extract.outputs.publish_state_prefix\",
            \"current_state_prefix\": \"\$.extract.outputs.current_state_prefix\",
            \"connection_creation_enabled\": $CONNECTION_CREATION_ENABLED,
            \"executor_enabled\": $EXECUTOR_ENABLED,
            \"connection_cache_enabled\": $CONNECTION_CACHE_ENABLED,
            \"connection_cache_via_app_enabled\": $CONNECTION_CACHE_VIA_APP_ENABLED
          }
        },
        \"depends_on\": {\"node_id\": \"extract\"}
      },
      \"lineage-app\": {
        \"node_type\": \"workflow\",
        \"activity_name\": \"execute_workflow\",
        \"activity_display_name\": \"Build Lineage Entities\",
        \"app_name\": \"lineage\",
        \"app_task_queue\": \"$LINEAGE_QUEUE\",
        \"inputs\": {
          \"workflow_type\": \"LineageWorkflow\",
          \"task_queue\": \"$LINEAGE_QUEUE\",
          \"args\": {
            \"connection_qualified_name\": \"\$.extract.outputs.connection_qualified_name\",
            \"connector_name\": \"mysql\",
            \"session_key\": \"view-lineage\",
            \"sql_unquoted_case\": \"lower\",
            \"ignore_all_case\": false,
            \"input_path\": \"\",
            \"parsed_views_path\": \"\$.extract.outputs.view_lineage_output_prefix\",
            \"lineage_output_path\": \"\$.extract.outputs.lineage_stage_prefix\",
            \"cache_path\": \"connection-cache\",
            \"file_type\": \"json\",
            \"lake_provider\": \"\$.extract.outputs.lake_provider\",
            \"cloud_storage_bucket\": \"\$.extract.outputs.storage_bucket\"
          }
        },
        \"depends_on\": {\"and_conditions\": [{\"node_id\": \"qi\"}, {\"node_id\": \"publish\"}]}
      },
      \"lineage-publish\": {
        \"node_type\": \"workflow\",
        \"activity_name\": \"execute_workflow\",
        \"activity_display_name\": \"Publish Lineage to Atlas\",
        \"app_name\": \"publish\",
        \"app_task_queue\": \"$PUBLISH_QUEUE\",
        \"inputs\": {
          \"workflow_type\": \"PublishWorkflow\",
          \"task_queue\": \"$PUBLISH_QUEUE\",
          \"args\": {
            \"connection_qualified_name\": \"\$.extract.outputs.connection_qualified_name\",
            \"transformed_data_prefix\": \"\$.extract.outputs.lineage_stage_prefix\",
            \"publish_state_prefix\": \"\$.extract.outputs.lineage_publish_state_prefix\",
            \"current_state_prefix\": \"\$.extract.outputs.lineage_current_state_prefix\",
            \"connection_creation_enabled\": false,
            \"executor_enabled\": $EXECUTOR_ENABLED,
            \"cache_namespace\": \"lineage\",
            \"connection_cache_enabled\": $CONNECTION_CACHE_ENABLED,
            \"connection_cache_via_app_enabled\": $CONNECTION_CACHE_VIA_APP_ENABLED
          }
        },
        \"depends_on\": {\"node_id\": \"lineage-app\"}
      }
    }
  }")
  REAL_VERSION=$(echo "$VERSION_RESP" | python3 -c "
import json, sys
d = json.load(sys.stdin)
v = d.get('data', {}).get('version') or d.get('version')
if v:
    print(v)
" 2>/dev/null || true)
  [ -n "$REAL_VERSION" ] && break
  log "Version create attempt $_attempt failed (workflow not ready yet), retrying in 5s..."
  sleep 5
done
[ -n "$REAL_VERSION" ] || err "Failed to create version after 3 attempts: $VERSION_RESP"

log "Version created: $REAL_VERSION"

# --- Delete auto-created empty version, if any ---
ALL_VERSIONS=$(curl -s "${CURL_AUTH[@]}" "$AE_URL/api/v1/workflows/$SLUG/versions")
EMPTY_VERSION=$(echo "$ALL_VERSIONS" | python3 -c "
import json, sys
vs = json.load(sys.stdin).get('data', [])
for v in vs:
    dag = v.get('dag') or {}
    if not dag or dag == {}:
        print(v['version'])
        break
" 2>/dev/null || true)

if [ -n "$EMPTY_VERSION" ] && [ "$EMPTY_VERSION" != "$REAL_VERSION" ]; then
  log "Deleting auto-created empty version: $EMPTY_VERSION"
  curl -s -X DELETE "${CURL_AUTH[@]}" "$AE_URL/api/v1/workflows/$SLUG/versions/$EMPTY_VERSION" >/dev/null
fi

# --- Publish the version ---
log "Publishing version $REAL_VERSION..."
PUB_RESP=$(curl -s -X POST "${CURL_AUTH[@]}" "$AE_URL/api/v1/workflows/$SLUG/versions/$REAL_VERSION/publish")
PUB_STATUS=$(echo "$PUB_RESP" | python3 -c "
import json, sys
print(json.load(sys.stdin).get('status', 'unknown'))
" 2>/dev/null || echo "unknown")

[ "$PUB_STATUS" = "success" ] || err "Publish failed: $PUB_RESP"
log "Published. Workflow ready."

echo "$SLUG"
