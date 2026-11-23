---
id: RP09
applies-to: [app]
---
# Only MySQL errors that mean "try again" are classified as transient

Principle: `transient_failure` treats a full connection table (errno 1040, 1203, 1226), a lost or
restarting server (1053, 2006, 2013) and a probe that ran out of time as retryable, and everything
else as definitive. It finds the errno by walking the SQLAlchemy `orig` and `__cause__` chain down
to the driver error.
Why: When an auth or permission errno is classed as transient, the hard preflight gate retries a
bad credential instead of blocking it; a server restart classed as definitive blocks a healthy run.
Ask:
- Does each errno added to or removed from a set match the MySQL and MariaDB error references, not a guess from its message?
- Is the errno still found when the driver error arrives wrapped in a new way, or can the walk stop early or pick up an integer that is not an errno?
- Do the test-auth, auth and table-listing probes still classify only through `transient_failure`?
Don't flag: raising a transient instead of returning a verdict, and the required preflight
scenarios (`F008`, `F016`); typed failures and actions (`F003`, `F007`). FP09 and FP12 cover
honest verdicts in general.
Severity: High when a bad credential would pass the gate or every server restart would block a
run. Medium for one rare errno misclassified.
