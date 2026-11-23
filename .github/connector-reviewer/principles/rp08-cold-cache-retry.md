---
id: RP08
applies-to: [app]
---
# The basic-auth retry stays narrow: auth failures only, few attempts, a fresh engine each time

Principle: Basic auth tries `load()` at most five times in total, with small jitter and only
retrying an auth failure, to get past the `caching_sha2_password` cold cache on MySQL 8, and
disposes the engine before each attempt. It is not widened to other errors or more attempts, and
no second retry layer is added around it.
Why: Every retry is another failed login, so a server that locks an account after repeated failed
logins (`FAILED_LOGIN_ATTEMPTS`) locks out a customer whose password is simply wrong. Retrying
handshake or connection errors as well can get the worker's host blocked (`max_connect_errors`),
and an engine kept between attempts leaks connections.
Ask:
- Does the diff widen the retried exception types, raise the attempt count or delay, or wrap `load()` in another retry?
- Is the engine still disposed before each new attempt?
- Does a wrong password still end, within the bounded attempts, as the auth error and not a timeout?
Don't flag: the retry being written with tenacity; do not ask to move it to another helper unless
the behaviour changes. No conformance rule that runs on app repos checks this retry.
Severity: High when a wrong credential could lock the customer's account or host, or the retry
could hang a run. Medium for a change in delay or jitter only.
