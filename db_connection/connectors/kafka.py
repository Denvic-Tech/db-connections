from __future__ import annotations

# pylint: disable=ungrouped-imports
import asyncio
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, field_validator

from ..connectors.base import Connector
from ..domain.entities import ConnectionCheckResult, ValidatedConnection


class NoBrokersAvailableFallback(Exception):
    pass

if TYPE_CHECKING:
    from aiokafka import AIOKafkaProducer
    from aiokafka.admin import AIOKafkaAdminClient
    from kafka import KafkaProducer
    from kafka.admin import KafkaAdminClient
    from kafka.errors import NoBrokersAvailable
else:
    AIOKafkaProducer = Any
    AIOKafkaAdminClient = Any
    KafkaProducer = Any
    KafkaAdminClient = Any
    KafkaAdminServer = Any
    NoBrokersAvailable = NoBrokersAvailableFallback

try:
    from aiokafka import AIOKafkaProducer
    from aiokafka.admin import AIOKafkaAdminClient
    from kafka import KafkaProducer
    from kafka.admin import KafkaAdminClient
    from kafka.errors import NoBrokersAvailable
except ImportError:
    AIOKafkaProducer = None
    AIOKafkaAdminClient = None
    KafkaProducer = None
    KafkaAdminClient = None
    NoBrokersAvailable = NoBrokersAvailableFallback


class KafkaProperties(BaseModel):
    bootstrap_servers: list[str]
    security_protocol: str = "PLAINTEXT"
    sasl_mechanism: str | None = None
    sasl_plain_username: str | None = None
    client_id: str = "kafka_client"
    request_timeout_ms: int = 30000

    @field_validator("bootstrap_servers", mode="before")
    @classmethod
    def normalize_bootstrap_servers(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


class KafkaSecrets(BaseModel):
    sasl_plain_password: str | None = None


class KafkaConnector(Connector):
    async def check(self, connection: ValidatedConnection) -> ConnectionCheckResult:
        return await asyncio.to_thread(self._check_blocking, connection)

    async def get_client(self, connection: ValidatedConnection) -> KafkaProducer:
        return await asyncio.to_thread(self._get_client_blocking, connection)

    def _check_blocking(self, connection: ValidatedConnection) -> ConnectionCheckResult:
        if KafkaAdminClient is None:
            raise RuntimeError("Kafka support requires Python's kafka module")

        try:
            admin = KafkaAdminClient(**self._build_config(connection))
            admin.list_topics()
            admin.close()
            return ConnectionCheckResult(
                name=connection.name,
                connected=True,
                message="Connection to Kafka successful.",
            )
        except NoBrokersAvailable as exc:
            return self._check_failure_result(
                connection,
                exc,
                message="Could not connect to any Kafka brokers.",
                exception=str(exc),
            )
        except Exception as exc:
            return self._check_failure_result(
                connection,
                exc,
                message=str(exc),
                exception=str(exc),
            )

    def _get_client_blocking(self, connection: ValidatedConnection) -> KafkaProducer:
        if KafkaAdminClient is None:
            raise RuntimeError("Kafka support requires Python's kafka module")

        return KafkaProducer(**self._build_config(connection))

    def _build_config(self, connection: ValidatedConnection) -> dict[str, Any]:
        props = connection.properties.model_dump()
        secrets = {} if connection.secrets is None else connection.secrets.model_dump()
        config = {
            "bootstrap_servers": props["bootstrap_servers"],
            "security_protocol": props.get("security_protocol", "PLAINTEXT"),
            "sasl_mechanism": props.get("sasl_mechanism"),
            "sasl_plain_username": props.get("sasl_plain_username"),
            "sasl_plain_password": secrets.get("sasl_plain_password"),
            "client_id": props.get("client_id", "kafka_client"),
            "request_timeout_ms": props.get("request_timeout_ms", 30000),
        }
        return {key: value for key, value in config.items() if value is not None}


class AsyncKafkaConnector(Connector):
    async def check(self, connection: ValidatedConnection) -> ConnectionCheckResult:
        if AIOKafkaAdminClient is None:
            raise RuntimeError("AIOKafka support requires Python's aiokafka module")

        try:
            admin = AIOKafkaAdminClient(**self._build_config(connection))
            await admin.start()
            await admin.list_topics()
            await admin.close()
            return ConnectionCheckResult(
                name=connection.name,
                connected=True,
                message="Connection to Kafka successful.",
            )
        except NoBrokersAvailable as exc:
            return self._check_failure_result(
                connection,
                exc,
                message="Could not connect to any Kafka brokers.",
                exception=str(exc),
            )
        except Exception as exc:
            return self._check_failure_result(
                connection,
                exc,
                message=str(exc),
                exception=str(exc),
            )

    async def get_client(self, connection: ValidatedConnection) -> AIOKafkaProducer:
        if AIOKafkaAdminClient is None:
            raise RuntimeError("AIOKafka support requires Python's aiokafka module")

        return AIOKafkaProducer(**self._build_config(connection))

    def _build_config(self, connection: ValidatedConnection) -> dict[str, Any]:
        props = connection.properties.model_dump()
        secrets = {} if connection.secrets is None else connection.secrets.model_dump()
        config = {
            "bootstrap_servers": props["bootstrap_servers"],
            "security_protocol": props.get("security_protocol", "PLAINTEXT"),
            "sasl_mechanism": props.get("sasl_mechanism"),
            "sasl_plain_username": props.get("sasl_plain_username"),
            "sasl_plain_password": secrets.get("sasl_plain_password"),
            "client_id": props.get("client_id", "kafka_client"),
            "request_timeout_ms": props.get("request_timeout_ms", 30000),
        }
        return {key: value for key, value in config.items() if value is not None}
