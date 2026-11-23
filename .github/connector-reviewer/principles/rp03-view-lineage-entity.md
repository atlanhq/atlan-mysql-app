---
id: RP03
applies-to: [app]
---
# A view entity carries what the query parser needs to build its lineage

Principle: MySQL keeps only the SELECT body in `VIEW_DEFINITION`, so `map_table` publishes a view's
definition as a full `CREATE OR REPLACE VIEW <name> AS <body>` statement and adds the top-level
`defaultCatalogName` and `defaultSchemaName` keys. Views come out of the table query and are
written by the table transform; there is no separate view stream.
Why: The parser cannot name the target of a bare SELECT, and lineage cannot resolve unqualified
table names without a default catalog and schema. Past runs went green with no view lineage for
each of these reasons.
Ask:
- Does the diff change the definition prefix, drop either default key, or turn the view back into a plain asset that cannot carry them?
- Does it add a view stream or a `fetch_view_sql`, so views are written twice or to a path the lineage steps do not read?
- Does a view with no body still get an empty definition rather than a bare prefix?
Don't flag: the view being the one mapper result returned as a serialised dict; that is deliberate
and pinned by tests. Raw-dict entities (`P058`) and serialisation outside `entity_bytes` (`P052`)
are conformance findings.
Severity: High when view lineage would silently disappear for every connection. Medium for a
change limited to an edge case such as views with no body.
