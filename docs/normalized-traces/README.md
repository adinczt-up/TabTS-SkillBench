# Normalized trace schemas and synthetic examples

This directory publishes the versioned normalized-trace contract and safe,
machine-readable examples for integration and scorer testing.

The examples are **synthetic contract and scoring fixtures**. They are not
paper experiment runs, do not reproduce model sessions, and cannot be used to
validate or reconstruct any reported paper result. Their table names, answer
values, identifiers, tool results, and scoring contract are invented.

Available versions:

- [`v1/`](v1/) — JSON Schema Draft 2020-12, exactly three synthetic normalized
  traces, expected metrics, and executable validation.

Consumers should select an explicit version rather than assuming that the
latest directory is backward compatible. See the version README for its files,
privacy boundary, harness-label disclaimer, and validation command.
