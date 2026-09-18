# atlan-mysql-server

The MySQL **serving** surface — auth, preflight and metadata — as an importable
package built on `atlan-server-sdk`, independent of the worker in `app/`.

Two consumers:

- the consolidated `common-api-server`, which installs this package and mounts
  `get_asgi_app()` under the `mysql` Host label;
- standalone, for local work: `uvicorn --factory mysql_server:get_asgi_app`.

## Why this is not a copy of `app/handler.py`

The worker generates RDS IAM tokens by writing `AWS_ACCESS_KEY_ID` /
`AWS_SECRET_ACCESS_KEY` into `os.environ` and restoring them in a `finally`.
In a process serving one app that is untidy; in the consolidated host, which
serves several apps in one process with one environment, it is a live fault —
a co-tenant app reading AWS credentials inside that window gets this tenant's
customer keys, overlapping requests clobber each other's restore, and boto3
prefers env credentials over the pod's IRSA identity.

`test_auth` and `preflight_check` both reach that path, so every IAM-role MySQL
call triggers it. This package passes credentials explicitly through
server-sdk's AWS helpers instead. `tests/test_no_env_mutation.py` enforces it,
statically and by driving the IAM path.

## Tests

```bash
cd server && uv venv .venv && uv pip install --python .venv -e . pytest pytest-asyncio
uv run --no-sync --python .venv python -m pytest tests -q
```
