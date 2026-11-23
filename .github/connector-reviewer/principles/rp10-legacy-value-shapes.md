---
id: RP10
applies-to: [app, tests]
---
# Published values keep the legacy wire shape unless value-level evidence says otherwise

Principle: The mappers reproduce what the legacy MySQL crawler published. Table custom attributes
go through `_safe_str` (whole floats without `.0`, NaN and infinity as empty); column custom
attributes keep their raw types; numeric NULLs that pandas reads as NaN become zero. This repo's
parity tests check which keys exist, not their values, so a change to a value's type or format
needs evidence from legacy output, not from the asset model's declared type.
Why: Atlas has accepted these shapes for years. Normalising them rewrites the metadata of every
asset on the next run, can break whoever reads them, and no test here would notice. A past attempt
to stringify column custom attributes was dropped for this reason.
Ask:
- Does the diff change the type or format of a published value (string or number, `None` or empty, how a float renders)?
- If so, does the PR cite legacy output or a value-level golden file, not only the pyatlan type?
- Does a new numeric field read from a pandas row guard against NaN, given that `NaN or 0` is NaN?
Don't flag: new attributes, key presence (pinned by `tests/unit/test_parity.py`), raw-dict
entities (`P058`). Do not ask to stringify column custom attributes.
Severity: High when values change for every asset of a type on existing connections. Medium for
one rarely set field.
