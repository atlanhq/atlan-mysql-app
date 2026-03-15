# AGENTS.md — Security Guidelines

> **Repo:** atlan-mysql-app | **Companion:** see `CLAUDE.md` | **Contact:** `bu-security-and-it`

**All AI agents must follow these guidelines when working on this codebase.**

---

## Security

### Owners & Contact

- **Security contact:** `bu-security-and-it` on Slack / GitHub
- **Request manual review** for: auth flows, secrets management, new API endpoints, external integrations, multi-tenant data access
- **Escalation:** When in doubt, ask — better to review than ship a vulnerability

---

### atlan-mysql-app: Security Guidelines

- `[MUST]` Never hardcode database credentials (host, port, username, password). All must come from environment variables.

```
❌ connection = "mysql+aiomysql://root:password123@localhost/db"
✅ connection = f"mysql+aiomysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}/{os.getenv('DB_NAME')}"
```

- `[MUST]` Parameterize all SQL queries — use ORM or prepared statements, never string concatenation

```
❌ query = f"SELECT * FROM {table_name} WHERE id = {user_id}"
✅ query = select(User).where(User.id == user_id)
```

- `[MUST]` Validate database metadata (schema names, table names, column names) before export — no special chars or injection patterns
- `[MUST]` Docker container must run as non-root (use `appuser` from base image; confirm `--chown=appuser:appuser` on COPY)
- `[MUST]` Activity code in `app/activities/` must never log credentials, connection strings, or detailed errors with PII
- `[MUST]` FastAPI endpoints must allowlist database/table/column filter parameters (regex: valid identifiers only)
- `[REDLINE]` Never pass user input directly to `_replace_database_placeholder()` or SQL construction — use only hardcoded constants
- `[SHOULD]` CI/CD workflows: use OIDC for AWS/GCP auth; rotate test DB credentials quarterly

---

### Core Invariants

- `[MUST]` No secrets in code, configs, logs, or CI output
- `[MUST]` `tenant_id` from authenticated session only — never from request params/headers
- `[MUST]` Parameterize all queries — never concatenate user input into SQL/filters
- `[MUST]` New endpoints: auth + authz + input validation + rate limiting before merge
- `[REDLINE]` No `eval`/exec/shell commands from user input; no unsafe deserialization
- `[MUST]` Pin actions/images to SHA/version — no `latest`
- `[MUST]` Client errors: generic messages only — no stack traces, SQL, file paths
- `[MUST]` Validate/allowlist outbound URLs built from user input (SSRF prevention)
- `[MUST]` All code in approved GitHub orgs (AtlanHQ) — flag personal repo references

### Secret Discovery

If you find a secret in code/config/CI: do not commit it further, flag as CRITICAL, recommend immediate rotation, notify `bu-security-and-it`.

### Severity

| CRITICAL | Block — fix before proceeding |
| HIGH | Block — fix before merging |
| MEDIUM | Flag — can be follow-up |
| LOW | Note briefly |
