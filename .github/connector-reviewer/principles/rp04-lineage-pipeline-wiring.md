---
id: RP04
applies-to: [contract, app]
---
# The lineage pipeline reads what the extract step really writes

Principle: The parse, lineage and lineage-publish nodes in `contract/app.pkl` take their inputs
from `MySQLExtractionOutput` by JSONPath and from keys inside the transformed entities. The
prefixes and bucket the extract step returns, the entity keys the parse step reads
(`attributes.definition`, `attributes.databaseName`, `attributes.schemaName`), and the condition
that runs lineage only after both parsing and publish succeed stay in step with the code.
Why: A wrong prefix, key or dependency does not fail the DAG; lineage simply finds nothing. Past
changes to cache settings, storage arguments and node wiring each left runs green with no lineage.
Ask:
- Does the diff change a lineage prefix or suffix, `storage_bucket`, or a field the parse step reads, without the matching change on the other side?
- Does it change the `pipeline` block (keys, case handling, `dependsOnCondition`), or does regeneration drop a node?
- Do procedures still carry their SQL in `definition`, so the parse step reads them beside views?
Don't flag: renamed or removed output fields (`B005`), manifest keys that miss the contract
(`K006`), stale or hand-edited generated files (`K003`, `K004`, `K005`). Do not review the
generated manifest line by line.
Severity: High when lineage would be empty or wrong for every connection. Medium when only an
optional argument drifts.
