---
id: RP01
applies-to: [app]
---
# Every extract query crawls the same set of tables and views

Principle: The table, column and schema-count SQL templates use one list of table types, one list
of system schemas and the same include and exclude filters, and the table and column queries apply
the same table-name filter. The preflight count uses the same table types and system schemas.
`map_table` and `map_column` agree on whether a row is a table or a view.
Why: When one query admits an object another drops, columns are published for a table that was
never extracted: publish rejects them and the run fails, or the table quietly goes missing. A past
regression did this with MariaDB system-versioned tables.
Ask:
- Does a change to the table types, system schemas or filter clause in one template reach every sibling template, the schema counts and the preflight count?
- Does each injected temp-table fragment use the alias of the query it lands in (`C.` in the column query, `T.` elsewhere), and does new SQL also run on MariaDB?
- If a new table type is admitted, do `map_table` and `map_column` classify it the same way?
Don't flag: equality of the table-type lists in the table, column and preflight queries, which
`tests/unit/test_sql_table_types.py` already pins. No conformance rule checks SQL template scope.
Do not flag the procedure query or the schema counts for lacking the table-name filter, or the
preflight count for matching every schema.
Severity: High when tables or columns can be dropped or orphaned for any connection. Medium when
only counts or the preflight message drift.
