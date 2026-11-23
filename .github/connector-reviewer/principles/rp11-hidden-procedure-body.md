---
id: RP11
applies-to: [app]
---
# A routine whose body the user cannot see is still published

Principle: MySQL returns `ROUTINE_DEFINITION` as NULL when the connection's user holds only
`EXECUTE`, `CREATE ROUTINE` or `ALTER ROUTINE` on a routine and is not its definer. `map_procedure`
still publishes such a routine, with an empty definition; the placeholder it passes to the creator
only satisfies validation and never reaches the output.
Why: Dropping a routine because its body is hidden removes a real asset from the catalog, and a
leftover placeholder is fake SQL that the lineage parser then reads.
Ask:
- Can a NULL or empty definition now drop the routine (in SQL or in the mapper), raise, or publish the placeholder?
- If the change needs routine bodies, does the PR name the privilege that needs (`SHOW_ROUTINE` or global `SELECT`) and how preflight reports it?
Don't flag: qualified-name construction when the string is unchanged (`P028`). FP02 covers
identity and FP12 covers preflight checks for new source access in general.
Severity: High when routines would be dropped for existing connections. Medium when only lineage
for routines with hidden bodies changes.
