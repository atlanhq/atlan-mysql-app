---
id: RP05
applies-to: [app]
---
# The extract output declares every transform and keeps an empty delivery empty

Principle: The procedure transform runs in `MySQLApp.run()`, after `SqlApp.run()` has verified its
own output, so its reference is folded into the declaration and verified with the rest before the
hand-off. `transformed_data_prefix` comes from what was delivered and is empty when nothing was.
`MySQLExtractionOutput` is not a subclass of the SDK's extraction output, whose validator would
refill an empty prefix.
Why: Publish diffs what it finds under the prefix against the catalog. An entity outside the
verified declaration can go missing unnoticed, and an empty prefix refilled with a real path tells
publish to archive every asset as removed from source.
Ask:
- Does a transform added to or moved into the `run()` override reach the verified declaration, not only the upload list?
- Can the returned prefix be non-empty after an empty delivery: a new base class, a default, or a value taken from the base result?
- Does the hand-off still go by declared reference, not by a local directory whose contents depend on which pod ran each transform?
Don't flag: SDK-owned transfers and cleanup, transfers inside a task (`P008`, `P044`), app state
passed between tasks (`P027`). FP01 and FP03 cover completeness and ownership in general.
Severity: High when publish could archive or miss assets under a green run. Medium when the proof
is missing but the data is still right.
