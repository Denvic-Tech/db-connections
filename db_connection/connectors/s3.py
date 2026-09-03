from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, field_validator

from ..connectors.base import Connector
from ..domain.entities import ConnectionCheckResult, ValidatedConnection

try:
    from botocore.config import Config
    from botocore.exceptions import ClientError, EndpointConnectionError
except ImportError:  # pragma: no cover
    Config = None  # type: ignore[assignment]

    class ClientError(Exception):
        pass

    class EndpointConnectionError(Exception):
        pass


class S3Properties(BaseModel):
    bucket: str
    region_name: str | None = None
    endpoint_url: str | None = None
    use_ssl: bool = True
    verify: bool = True
    path_style: bool = False
    signature_version: str | None = None
    prefix: str | None = None

    @field_validator("bucket", mode="before")
    @classmethod
    def normalize_bucket(cls, value: str) -> str:
        bucket = str(value).strip()
        if not bucket:
            raise ValueError("bucket must be a non-empty string")
        return bucket

    @field_validator("prefix", mode="before")
    @classmethod
    def normalize_prefix(cls, value: str | None) -> str | None:
        if not value:
            return None

        if not isinstance(value, str):
            raise ValueError("prefix must be a string or None")  # noqa: TRY004

        return value.strip().strip("/")


class S3Secrets(BaseModel):
    access_token_id: str
    access_token_key: str
    session_token: str | None = None


class S3Connector(Connector):
    async def check(self, connection: ValidatedConnection) -> ConnectionCheckResult:
        return await asyncio.to_thread(self._check_blocking, connection)

    async def get_client(self, connection: ValidatedConnection) -> Any:
        return await asyncio.to_thread(self._get_client_blocking, connection)

    def _check_blocking(self, connection: ValidatedConnection) -> ConnectionCheckResult:
        try:
            client = self._get_client_blocking(connection)
            props = connection.properties.model_dump()
            client.list_objects_v2(
                Bucket=props["bucket"],
                Prefix=props["prefix"] or "",
                MaxKeys=1,
            )
            close_fn = getattr(client, "close", None)
            if callable(close_fn):
                close_fn()
            return ConnectionCheckResult(
                name=connection.name,
                connected=True,
                message="Connection to S3 successful.",
            )
        except (ClientError, EndpointConnectionError) as exc:
            return self._check_failure_result(
                connection,
                exc,
                message="S3 connectivity check failed.",
                exception=str(exc),
            )
        except Exception as exc:
            return self._check_failure_result(
                connection,
                exc,
                message=str(exc),
                exception=str(exc),
            )

    def _get_client_blocking(self, connection: ValidatedConnection) -> Any:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("boto3 is required for S3 connections.") from exc

        props = connection.properties.model_dump()
        secrets = {} if connection.secrets is None else connection.secrets.model_dump()
        kwargs: dict[str, Any] = {
            "region_name": props.get("region_name"),
            "endpoint_url": props.get("endpoint_url"),
            "aws_access_key_id": secrets.get("access_token_id"),
            "aws_secret_access_key": secrets.get("access_token_key"),
            "aws_session_token": secrets.get("session_token"),
            "use_ssl": props.get("use_ssl", True),
            "verify": props.get("verify", True),
        }

        config_kwargs: dict[str, Any] = {}
        if props.get("signature_version"):
            config_kwargs["signature_version"] = props["signature_version"]
        if props.get("path_style"):
            config_kwargs.setdefault("s3", {})["addressing_style"] = "path"
        if config_kwargs and Config is not None:
            kwargs["config"] = Config(**config_kwargs)

        return boto3.client("s3", **{key: value for key, value in kwargs.items() if value is not None})
