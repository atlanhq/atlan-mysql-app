---
schema: 2
id: MYSQL-REPO-001
level: L3
category: correctness
globs: []
severity: HIGH
suppressible: true
---
# Review MySQL-specific behavior

- Report a finding only when changed code breaks a concrete repository contract
  shown by code, tests, generated contracts, or maintained documentation.
- Check source-specific discovery, identity, extraction, lineage, or workflow
  behavior only when the diff affects it.
- Do not restate conformance, shared connector, or platform policy covered by
  L1, L2, or L4.
