"""Utilities for MySQL connector.

Currently contains:

* `resolve_information_schema()` — replaces the ``{information_schema}``
  placeholder in SQL templates with either the canonical
  ``information_schema`` identifier or a customer-provided mirror schema
  name (e.g. ``atlan_meta``).

* `resolve_excluded_schemas()` — replaces the ``{excluded_schemas}``
  placeholder with the system-schema exclusion list. When a mirror schema
  is configured, the mirror name is appended so its pass-through views
  aren't crawled as user assets.

* `extract_control_config()` — pull control-config from a connection-config
  dict (handler side) or workflow input (extraction side), normalizing
  shape (JSON string → dict, ``control-config-strategy`` gating).

The mirror-schema flow is for customers whose security policy forbids
granting ``SELECT`` on the native ``INFORMATION_SCHEMA`` (because in MySQL,
``INFORMATION_SCHEMA`` reads require the underlying ``SELECT`` privilege on
each user table). The DBA creates views in a dedicated schema (e.g.
``atlan_meta``) that mirror ``INFORMATION_SCHEMA`` rows, grants ``SELECT``
on the mirror schema only, and configures the connector with
``{"clonedInformationSchema": "atlan_meta"}``. The connector then queries
``atlan_meta.SCHEMATA`` etc. instead of ``information_schema.SCHEMATA``.

Mirrors the Redshift ``clonedPgCatalogSchema`` precedent in
``atlan-redshift-app/app/activities/metadata_extraction/utils.py``.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Canonical MySQL system schema. Used when no customer override is provided.
DEFAULT_INFORMATION_SCHEMA = "information_schema"

# System schemas the connector never wants to crawl as user metadata.
# Substituted into SQL templates via the ``{excluded_schemas}`` placeholder.
# When a customer configures ``clonedInformationSchema``, the mirror schema
# name is appended so the mirror's own pass-through views (e.g. atlan_meta.TABLES)
# are not surfaced as user assets in Atlan.
DEFAULT_EXCLUDED_SCHEMAS: tuple[str, ...] = (
    "mysql",
    "performance_schema",
    "information_schema",
    "sys",
)

# Conservative MySQL identifier pattern. Schema names entered by customers
# arrive via JSON config and are concatenated directly into SQL templates,
# so we hard-validate the shape before substitution. Accepts the standard
# unquoted-identifier form (letter or underscore, then alphanumeric or
# underscore). Backtick-quoted identifiers are intentionally rejected — they
# add an injection surface and the mirror-schema setup script does not use
# them.
#
# Matches MySQL identifier rules at
# https://dev.mysql.com/doc/refman/8.0/en/identifiers.html for the simple case.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

# Placeholder strings SQL templates use. Kept as constants so callers
# don't sprinkle the literals across the codebase.
_PLACEHOLDER = "{information_schema}"
_EXCLUDED_PLACEHOLDER = "{excluded_schemas}"


def _validated_cloned_information_schema(
    control_config: dict[str, Any] | None,
) -> str | None:
    """Return the validated ``clonedInformationSchema`` value or ``None``.

    Used by both :func:`resolve_information_schema` and
    :func:`resolve_excluded_schemas` so the identifier validation lives in
    exactly one place. Returns ``None`` when no override is configured.
    Raises ``ValueError`` for malformed values — better an early, explicit
    failure than a confusing SQL syntax error deeper in the pipeline.
    """
    if not control_config:
        return None
    candidate = control_config.get("clonedInformationSchema")
    if candidate is None:
        return None
    if not isinstance(candidate, str) or not candidate.strip():
        raise ValueError(
            f"clonedInformationSchema must be a non-empty string; got {candidate!r}"
        )
    stripped = candidate.strip()
    if not _IDENTIFIER_RE.match(stripped):
        raise ValueError(
            "clonedInformationSchema must match the MySQL identifier "
            f"pattern [A-Za-z_][A-Za-z0-9_]{{0,63}}; got {stripped!r}"
        )
    return stripped


def _coerce_to_dict(value: Any) -> dict[str, Any]:
    """Normalize a control-config-shaped value to a dict.

    Accepts a dict (returned as-is), a JSON string (parsed and returned if
    it decodes to a dict), or anything else (returns empty dict). Invalid
    JSON yields an empty dict rather than raising — control-config is
    customer-supplied and must fail soft on malformed input. Soft failure
    here means: behave as if no override was provided, which leaves the
    connector pointed at the native ``information_schema`` (current
    behavior, fully backward compatible).
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(decoded, dict):
            return decoded
    return {}


def extract_control_config(
    source: Any,
    *,
    strategy_key: str = "control-config-strategy",
    config_key: str = "control-config",
) -> dict[str, Any]:
    """Pull control-config from a source dict or pydantic object.

    The marketplace UI surfaces a "Custom Control Config" mode via two fields:

    - ``control-config-strategy``: ``"custom"`` to enable, anything else
      (including absent) disables.
    - ``control-config``: a dict (or JSON-encoded string) of key/value
      overrides.

    Only when the strategy is ``"custom"`` AND the config is non-empty do we
    return the parsed dict. In every other case we return ``{}``, which
    preserves today's behavior.

    *source* may be a plain dict, a pydantic ``BaseModel``, or anything that
    exposes attribute or item access. Hyphenated and underscored key forms
    are both checked, since AE/Argo payloads use hyphens and pydantic-coerced
    forms use underscores.
    """
    if source is None:
        return {}

    def _get(name: str) -> Any:
        underscored = name.replace("-", "_")
        hyphenated = name if "-" in name else name.replace("_", "-")

        # 1. Plain dict access (workflow_args, AE payloads).
        if isinstance(source, dict):
            for key in (name, underscored, hyphenated):
                if key in source:
                    return source[key]
            return None

        # 2. Pydantic v2 `extra='allow'` stores extras in __pydantic_extra__,
        #    keyed by the original (often hyphenated) name — getattr() on
        #    the model does NOT see them.
        extra = getattr(source, "__pydantic_extra__", None)
        if isinstance(extra, dict):
            for key in (name, underscored, hyphenated):
                if key in extra:
                    return extra[key]

        # 3. Regular attribute access (real fields, or non-pydantic objects).
        return getattr(source, underscored, None)

    strategy = _get(strategy_key)
    if not isinstance(strategy, str) or strategy.lower() != "custom":
        return {}

    raw_config = _get(config_key)
    return _coerce_to_dict(raw_config)


def resolve_information_schema(
    sql_template: str,
    control_config: dict[str, Any] | None = None,
) -> str:
    """Replace ``{information_schema}`` in *sql_template* with the target schema.

    When *control_config* contains a non-empty ``clonedInformationSchema``
    value, that value (after validation) is used. Otherwise the canonical
    ``information_schema`` identifier is used, which preserves the current
    behavior bit-for-bit when no override is configured.

    Args:
        sql_template: The SQL string, expected to contain zero or more
            occurrences of the literal ``{information_schema}``.
        control_config: Optional parsed control-config dict (from
            :func:`extract_control_config`).

    Returns:
        The SQL string with all ``{information_schema}`` occurrences
        replaced. If the template contains no placeholder, the input is
        returned unchanged.

    Raises:
        ValueError: When ``clonedInformationSchema`` is present but its
            value does not match the MySQL identifier pattern. We raise
            rather than silently fall back so the operator gets a clear
            error early (during preflight or first extract) instead of a
            confusing SQL syntax failure deeper in the pipeline.
    """
    if not sql_template:
        return sql_template

    mirror = _validated_cloned_information_schema(control_config)
    target = mirror or DEFAULT_INFORMATION_SCHEMA
    return sql_template.replace(_PLACEHOLDER, target)


def resolve_excluded_schemas(
    sql_template: str,
    control_config: dict[str, Any] | None = None,
) -> str:
    """Replace ``{excluded_schemas}`` in *sql_template* with the system-schema list.

    The default list is :data:`DEFAULT_EXCLUDED_SCHEMAS`. When *control_config*
    contains a non-empty ``clonedInformationSchema``, that value (after
    identifier validation) is appended to the list so the customer's mirror
    schema and its pass-through views are never crawled as user assets in
    Atlan. The list is rendered as a comma-separated tuple of single-quoted
    identifiers, ready for direct substitution into a SQL ``NOT IN (...)``
    clause.

    Args:
        sql_template: The SQL string, expected to contain zero or more
            occurrences of the literal ``{excluded_schemas}``.
        control_config: Optional parsed control-config dict (from
            :func:`extract_control_config`).

    Returns:
        The SQL string with all ``{excluded_schemas}`` occurrences replaced.
        If the template contains no placeholder, the input is returned
        unchanged. When no override is configured, the rendered list is
        byte-identical to the literal that used to live in each SQL file.

    Raises:
        ValueError: When ``clonedInformationSchema`` is present but malformed.
            Mirrors the contract of :func:`resolve_information_schema`.
    """
    if not sql_template:
        return sql_template

    schemas = list(DEFAULT_EXCLUDED_SCHEMAS)
    mirror = _validated_cloned_information_schema(control_config)
    if mirror and mirror not in schemas:
        schemas.append(mirror)

    rendered = ", ".join(f"'{s}'" for s in schemas)
    return sql_template.replace(_EXCLUDED_PLACEHOLDER, rendered)
