# CLAUDE.md — Security Guidelines

> **Repo:** atlan-mysql-app | **Full policy:** see `AGENTS.md` | **Contact:** `bu-security-and-it`

**All AI agents must follow these guidelines when working on this codebase.**

---

## Security

### Owners & Contact

- **Security contact:** `bu-security-and-it` on Slack
- **Request manual review** for: auth flows, secrets management, new API endpoints, multi-tenant data access, Docker configuration

---

### atlan-mysql-app: Key Security Rules

- `[MUST]` Never hardcode DB credentials. All connection params (host, port, user, password) must come from env vars
- `[MUST]` Parameterize all SQL queries — use ORM/prepared statements, never string concatenation with user input
- `[MUST]` Validate database metadata before export — no injection patterns in schema/table/column names
- `[MUST]` Docker image must run as non-root user (default: `appuser` in base image)
- `[MUST]` Never log database credentials, connection strings, or detailed error messages with PII
- `[MUST]` FastAPI endpoints must validate inputs for SQL injection before passing to queries
- `[REDLINE]` Never pass raw user input to database placeholder replacement functions
- `[SHOULD]` Use OIDC for CI/CD secrets instead of long-lived tokens; rotate test credentials regularly

---

### Universal Minimums

- `[MUST]` No secrets in code, configs, or logs
- `[MUST]` Parameterize all queries — no string concatenation with user input
- `[MUST]` `tenant_id` from auth context only — never from request input
- `[MUST]` New API endpoints: auth + authz + input validation + rate limiting before merge
- `[REDLINE]` No `eval`/exec of user input; no unsafe deserialization
- `[MUST]` Pin actions/images to SHA or version — no `latest` tags
- `[MUST]` Generic error responses only — no stack traces, SQL, or internal paths to clients
