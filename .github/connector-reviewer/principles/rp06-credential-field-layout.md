---
id: RP06
applies-to: [app, contract]
---
# Each auth type reads its credential fields where the stored form puts them

Principle: The three auth types reuse field names with different meanings, kept from the legacy
credential form. Basic uses `username` and `password`. IAM user puts the AWS key pair in `username`
and `password` and the database user in `extra.username`. IAM role puts the database user in
`username` and the role ARN and external id under `extra`. Agent mode sends basic fields as
`basic.username` and `basic.password`. Fields beyond host, port, username and password live under
`extra`, because the credential UI drops unknown top-level fields.
Why: Stored credentials and agent configurations already use this layout. A client or form that
moves a field reads the wrong value, such as an AWS key as the database user, or nothing, and every
existing connection of that auth type fails to sign in.
Ask:
- Does the diff change which field the client reads for an auth type, or where the form or agent config writes it?
- Do `contract/app.pkl`, `app/client.py` and `_creds_to_dict` in the handler still agree for all three types and for agent mode?
- Is a new auth field declared under `extraFields`, not as a new top-level field?
Don't flag: credential routing (`P053`), hard-coded or env credentials (`S001`, `S002`), form keys
that miss the manifest (`K019`). FP11 covers where secret values may travel.
Severity: High when existing connections of an auth type would stop signing in. Medium for a new
optional field placed inconsistently.
