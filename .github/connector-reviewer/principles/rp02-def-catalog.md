---
id: RP02
applies-to: [app]
---
# The catalog is always `def`, and the connection never selects a default database

Principle: MySQL has one level of namespace, so this app puts every schema under the single
catalog `def` (`DATABASE_PLACEHOLDER`). The connection opens with no default database, so
`COALESCE(DATABASE(), 'def')` stays `def`. That one value is the catalog that saved filters name,
the left side of every include and exclude `REGEXP`, and the database segment of every qualified
name.
Why: Saved filters are anchored patterns such as `^def\.sales$`. If the connection gains a default
database or the placeholder changes, they stop matching: the run extracts nothing or ignores
exclusions, and publish archives or renames assets while the run stays green.
Ask:
- Does the diff add a database to the connection URL, `connect_args` or credentials, or run `USE`, so that `DATABASE()` is no longer NULL?
- Does it change `DATABASE_PLACEHOLDER`, the catalog a query or mapper reads, or the catalog the metadata endpoint returns?
- Would a filter saved before this change still select the same schemas after it?
Don't flag: how a qualified name is built when the string is unchanged (`P028`), or new asset
types. FP02 covers identity changes in general; this is only about the `def` catalog.
Severity: High when saved filters or existing qualified names change for existing connections.
Medium for a new code path that takes the catalog from somewhere other than the placeholder.
