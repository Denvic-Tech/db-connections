# AGENTS.md

## Project overview

`db-connection` is a Python library for storing, validating, exposing, and
checking service connection definitions through a unified API. The current
library is instance-based: consumer projects build a `DBConnectionExtension`
with their own repository, registry, policies, schemas, and runtime settings.

## Current architecture

The current codebase uses a DDD-lite split with explicit runtime and adapter
layers.

- `db_connection/domain/`: core models and contracts.
  - `connection.py`: `ConnectionDraft`, `ConnectionPatch`,
    `ConnectionRecord`, `ConnectionListQuery`, `ValidatedConnection`,
    `ConnectionCheckResult`.
  - `specs.py`: `KindSpec`, `TypeSpec`.
  - `repositories.py`: `ConnectionRepository` protocol.
- `db_connection/application/`: use-case and policy layer.
  - `service.py`: `ConnectionService` CRUD/check flows.
  - `validation.py`: registry-backed payload validation and public
    serialization.
  - `policies.py`: `AccessPolicy`, `AccessContext`,
    `AllowAllAccessPolicy`.
- `db_connection/runtime/`: instance-scoped runtime state and cross-cutting
  helpers.
  - `settings.py`: immutable `DBConnectionSettings`,
    `DBConnectionRuntime`, atomic settings updates.
  - `encryption.py`: encryption provider abstractions and defaults.
- `db_connection/registry/`: runtime kind/type registry.
  - `base.py`: `ConnectionRegistry`.
  - `defaults.py`: built-in kinds/types and default connector bindings.
- `db_connection/connectors/`: infrastructure adapters for actual services
  (`sql`, `kafka`, `s3`, `ftp`).
- `db_connection/infra/`: persistence implementation for the current runtime.
  - `models.py`: `DefaultStoredConnection`.
  - `repositories.py`: `DefaultSQLModelConnectionRepository`.
- `db_connection/fastapi/`: presentation and public HTTP integration.
  - `extension.py`: `DBConnectionExtension`, route installation.
  - `builder.py`: `DBConnectionExtensionBuilder`.
  - `schemas.py`, `schema_builders.py`, `mapper.py`: request/response models
    and API mapping.
- `db_connection/dsl/` and `db_connection/plugins.py`: declarative registry
  extension and plugin loading.
- `db_connection/__init__.py`: primary public export surface.

Layer intent:

- `domain` should stay independent of FastAPI, SQLModel, and legacy compat
  code.
- `application` may depend on `domain`, `registry`, `runtime` contracts, and
  library errors, but not on `fastapi` or storage details.
- `infra` implements repository/storage concerns and may depend on SQLAlchemy,
  SQLModel, encryption providers, and domain protocols.
- `fastapi` adapts runtime/application behavior to HTTP and owns OpenAPI-facing
  schemas and exception mapping.

## Legacy compatibility layer

`db_connection/compat/` contains the legacy implementation and backward
compatibility bridge. It is not the source of truth for the new architecture.

Rules for agents:

- Do not use `db_connection/compat` as the primary reference when adding or
  changing current-version behavior.
- Do not move new architecture code into `db_connection/compat`.
- Modify `db_connection/compat` only when the task explicitly concerns legacy
  APIs or backward compatibility.
- `db_connection/compat/runtime_bridge.py` may delegate legacy connectors to the
  new runtime. Treat that as compatibility plumbing, not as the main design.
- If new-runtime behavior and `compat` behavior differ, call that out explicitly
  in the final response.

## Repository structure

Current implementation:

- `db_connection/__init__.py`: public exports for the new library API.
- `db_connection/domain/`, `application/`, `runtime/`, `registry/`,
  `connectors/`, `infra/`, `fastapi/`, `dsl/`, `plugins.py`, `errors.py`.

DDD-lite modules/layers:

- `domain/`: entities, value-like payload models, specs, repository protocols.
- `application/`: service/use-case orchestration, validation, access policies.
- `runtime/`: instance runtime container and settings/encryption concerns.
- `infra/`: default SQLModel persistence.
- `fastapi/`: builder, HTTP routes, schema generation, API mapping.

Compatibility code:

- `db_connection/compat/`: old API surface, legacy connectors, router, manager,
  schemas, runtime bridge.

Tests:

- `tests/test_service_dispatch.py`: service and connector dispatch behavior.
- `tests/test_http_api.py`: default HTTP CRUD/OpenAPI behavior.
- `tests/test_custom_extension.py`: custom repository, custom schemas, access
  policy integration.
- `tests/test_core_extension_features.py`: builder, DSL, plugin, runtime
  settings behavior.
- `tests/test_compat_runtime_bridge.py`: legacy compat bridge expectations.
- `tests/conftest.py`: shared FastAPI/repository fixtures.

Docs and examples:

- `README.md`: current usage and extension guidance.
- `app/main.py`: demo FastAPI app with custom repository, policy, error mapper,
  and custom type registration.
- `docker-compose.tests.yaml`: docker-backed test services.

Build and config:

- `pyproject.toml`: packaging, dependencies, pytest, Ruff, mypy config.
- `requirements.txt`: pinned local/dev toolchain, includes `build`, `twine`,
  `ruff`, `uvicorn`, pytest tooling.
- `scripts/upload_builds.py`: artifact upload helper.
- `scripts/analysis/ruff_check_changed.py`: scoped Ruff helper.
- `scripts/analysis/pylint_check_changed.py`: scoped Pylint helper.

## Development commands

Use the repository virtual environment, not system Python.

Install dependencies:

- `.\.venv\Scripts\python.exe -m pip install -e .[drivers,async,test,s3]`
  from `README.md` and `pyproject.toml`.
- `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` for the
  pinned full dev toolchain in `requirements.txt`.

Run tests:

- `.\.venv\Scripts\python.exe -m pytest`
- `.\.venv\Scripts\python.exe -m pytest -m "not docker_required"`
- `.\.venv\Scripts\python.exe -m pytest tests\test_http_api.py`
- `.\.venv\Scripts\python.exe -m pytest tests\test_service_dispatch.py::test_sync_connector_dispatch`

Lint:

- `.\.venv\Scripts\python.exe scripts/analysis/ruff_check_changed.py`
- `.\.venv\Scripts\python.exe scripts/analysis/pylint_check_changed.py`

Format:

- `.\.venv\Scripts\ruff.exe format .`

Type checking:

- Needs confirmation: `pyproject.toml` contains `[tool.mypy]`, but `mypy` is
  not declared in `requirements.txt` and `.\.venv\Scripts\python.exe -m mypy`
  is not currently available in this workspace.

Build:

- `.\.venv\Scripts\python.exe -m build`

Run demo API:

- `.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 3000`

## Coding conventions

- Formatting follows Ruff config in `pyproject.toml`: 4 spaces, line length 100,
  double quotes, import sorting via Ruff/isort.
- Keep DDD-lite boundaries explicit:
  - `domain` must not import from `infra`, `fastapi`, or `compat`.
  - `application` should work with domain models, protocols, registry, and
    library errors; do not couple it to HTTP or SQLModel.
  - `infra` should implement repository/encryption/storage details and return
    domain models.
  - `fastapi` should translate HTTP payloads to domain/application calls and map
    exceptions with `ErrorMapper`.
- Domain models, repository protocols, specs, and domain-level errors belong in
  `db_connection/domain/` and `db_connection/errors.py`.
- Infrastructure adapters and persistence mappers belong in
  `db_connection/infra/` or `db_connection/connectors/`, not in `domain`.
- Public exports should be defined deliberately in `db_connection/__init__.py`.
  Avoid adding new public imports implicitly through internal modules only.
- Preserve old compatibility APIs inside `db_connection/compat`; do not let new
  code depend on compat models when current domain models are sufficient.
- Sync/async split is connector-oriented. The main repository protocol is sync;
  async behavior currently exists through `AsyncConnector` and service methods
  such as `check_payload_async`.
- Prefer strict typing consistent with existing Pydantic v2 models, protocols,
  and dataclasses. Avoid introducing untyped `dict` payload plumbing when a
  model or protocol already exists.
- Raise library exceptions from `db_connection/errors.py` instead of leaking raw
  framework exceptions across layers. Use `InfrastructureError` for adapter or
  integration failures and `ValidationFailedError` for normalized validation
  failures.
- Naming follows the existing codebase: modules in `snake_case`, classes in
  `CapWords`, specs named `KindSpec`/`TypeSpec`, repository implementations with
  explicit backend names such as `DefaultSQLModelConnectionRepository`.

## Testing guidance

- Add or update tests in `tests/` alongside the affected layer.
- Domain/application changes should usually be covered in
  `tests/test_service_dispatch.py` or a similarly focused new test file.
- HTTP, schema, builder, and public API behavior should be covered in
  `tests/test_http_api.py`, `tests/test_custom_extension.py`, or
  `tests/test_core_extension_features.py`.
- Changes touching `db_connection/compat` should include or update compat tests,
  especially `tests/test_compat_runtime_bridge.py`.
- Add regression tests whenever changing validation rules, connector defaults,
  public serialization, registry behavior, builder behavior, or compat bridging.
- After changes, run the smallest relevant command first. For example:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_service_dispatch.py`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_http_api.py`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_compat_runtime_bridge.py`
- If docker-backed behavior is involved, run the appropriate docker-marked tests
  or state clearly that they were not run.

## Public API and backward compatibility

- Do not break public imports or exported symbols without explicit instruction.
- Treat `db_connection/__init__.py` as the main public API contract.
- Be careful with FastAPI-facing classes and builder hooks that consumer
  projects may import directly, including `DBConnectionExtension`,
  `DBConnectionExtensionBuilder`, `APISchemaSet`, repository/encryption
  providers, specs, and error types.
- Keep compatibility behavior isolated in `db_connection/compat`.
- If you change public behavior, also update tests and any affected examples in
  `README.md` or `app/main.py`.

## Files and directories agents should avoid modifying casually

- `db_connection/compat/`: change only for explicit compatibility work.
- `db_connection.egg-info/`: generated packaging metadata.
- `.venv/`, `.pytest_cache/`, `.ruff_cache/`, `__pycache__/`: local environment
  and cache artifacts.
- `app/db_connection_demo.db`: demo database artifact.
- `build/`, `dist/`: generated build artifacts, if present.
- `tmp/`: scratch area used by tests and local experiments.

## Agent workflow rules

- Read the relevant current-version files before editing; do not assume the old
  structure still applies.
- Do not use `db_connection/compat` as the source of truth for new
  implementation work.
- Prefer small, focused changes that preserve current DDD-lite boundaries.
- Avoid introducing new dependencies without strong justification.
- Update or add tests when behavior changes.
- Run the smallest relevant validation command for the files or layer you
  touched.
- After repository edits, run `scripts/analysis/ruff_check_changed.py` and
  `scripts/analysis/pylint_check_changed.py` via the repository virtual
  environment and address the reported issues pragmatically: fix relevant
  problems introduced or exposed by your change, but do not turn every task
  into a broad cleanup.
- Report exactly what changed and which checks were run.
- If repository behavior or intent is ambiguous, say so and cite the files that
  made it ambiguous instead of guessing.
