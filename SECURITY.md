# Security Policy

## Risk model

TabTS-SkillBench executes model-generated shell and Python code. Treat the
evaluated agent as untrusted code with possible access to credentials and files
visible to its process.

## Safe evaluation requirements

- Run Gold-sensitive evaluation on Linux with the configured Bubblewrap sandbox.
- Mount only staged task inputs and allowed Skills into the agent workspace.
- Keep evaluator tasks, Gold, Oracle SQL, credentials, and the repository checkout
  outside the sandbox.
- Use read-only mounts for external source data; the workspace copy is disposable.
- Use dedicated, least-privilege provider credentials and never store them in a
  repository or run artifact.
- Do not weaken a failed sandbox preflight to obtain a score.

The Docker image is a packaging convenience and is not, by itself, proof that
the nested agent process cannot read Gold. Container runtime mounts and
privileges must still satisfy the boundary above.

## Reporting a vulnerability

Do not open a public issue containing credentials, exploitable Gold-leak paths,
or private data. Contact the repository maintainers privately through the
security-reporting channel configured on the GitHub repository. A permanent
contact address is still a release blocker for `v1.0.0`.
