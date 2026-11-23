---
id: RP07
applies-to: [app]
---
# Every IAM connection gets a fresh token over TLS, and IAM failures stay auth failures

Principle: An RDS IAM token lives for minutes, so the client makes one for each new connection
through the `do_connect` listener, sends it with the clear-password plugin over TLS, takes the
region from the RDS host name, and passes any AWS key pair to STS directly. STS refusals and a
token MySQL rejects leave `load()` as the app's IAM auth error.
Why: A token reused past its lifetime fails every connection opened later in a long run. Keys
staged in the process environment leak between workflows on one worker. A raw boto or driver error
is reported as a platform fault instead of a credential the customer must fix.
Ask:
- Can a pooled or retried connection reuse an old token, or does a new code path open a connection without the listener?
- Does the diff stage AWS keys in `os.environ`, drop TLS or the clear-password plugin, or change how the region is found?
- Can a new failure on the IAM path (STS, token generation, the connection test) leave `load()` untranslated?
Don't flag: blocking calls and offloading (`P023`; FP05), secrets in logs (`L010`; FP11), error
mechanics (`E012`, `E016`). FP09 covers failure typing in general.
Severity: High when every IAM user or IAM role connection would fail, or keys could cross between
workflows. Medium when a failure stays visible but is routed to the wrong owner.
