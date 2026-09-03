from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from db_connection.connectors.s3 import S3Connector, S3Properties, S3Secrets
from db_connection.domain.entities import ValidatedConnection


def _build_s3_connection(*, verify: bool) -> ValidatedConnection:
    return ValidatedConnection(
        name="objects",
        kind="file",
        type="s3",
        driver=None,
        driver_options=None,
        properties=S3Properties(
            bucket="bucket",
            endpoint_url="https://s3.example.test",
            use_ssl=True,
            verify=verify,
        ),
        secrets=S3Secrets(
            access_token_id="key-id",
            access_token_key="key-secret",
        ),
        labels={},
        metadata={},
        extra={},
    )


@pytest.mark.parametrize("verify", [True, False])
def test_s3_connector_passes_verify_to_boto3_client(monkeypatch, verify: bool) -> None:
    captured: dict[str, Any] = {}

    def fake_client(service_name: str, **kwargs: Any) -> object:
        captured["service_name"] = service_name
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=fake_client))

    client = S3Connector()._get_client_blocking(_build_s3_connection(verify=verify))

    assert client is not None
    assert captured["service_name"] == "s3"
    assert captured["kwargs"]["verify"] is verify
