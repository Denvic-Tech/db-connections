from __future__ import annotations

# pylint: disable=ungrouped-imports
import asyncio
import ssl
from typing import TYPE_CHECKING, Any, Literal

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
    security_protocol: Literal["PLAINTEXT", "SSL", "SASL_PLAINTEXT", "SASL_SSL"] = "PLAINTEXT"
    ssl_ca_pem: str | None = None
    sasl_mechanism: Literal["PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512"] | None = None
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
            try:
                admin.list_topics()
            finally:
                admin.close()
            return ConnectionCheckResult(
                name=connection.name,
                connected=True,
                message="Connection to Kafka successful.",
            )
        except NoBrokersAvailable as exc:
            return ConnectionCheckResult(
                name=connection.name,
                connected=False,
                message="Could not connect to any Kafka brokers.",
                exception=type(exc).__name__,
            )
        except Exception as exc:
            return ConnectionCheckResult(
                name=connection.name,
                connected=False,
                message="Kafka connection check failed.",
                exception=type(exc).__name__,
            )

    def _get_client_blocking(self, connection: ValidatedConnection) -> KafkaProducer:
        if KafkaAdminClient is None:
            raise RuntimeError("Kafka support requires Python's kafka module")

        return KafkaProducer(**self._build_config(connection))

    def _build_config(self, connection: ValidatedConnection) -> dict[str, Any]:
        return build_kafka_config(
            connection.properties.model_dump(),
            {} if connection.secrets is None else connection.secrets.model_dump(),
        )


class AsyncKafkaConnector(Connector):
    async def check(self, connection: ValidatedConnection) -> ConnectionCheckResult:
        if AIOKafkaAdminClient is None:
            raise RuntimeError("AIOKafka support requires Python's aiokafka module")

        try:
            admin = AIOKafkaAdminClient(**self._build_config(connection))
            try:
                await admin.start()
                await admin.list_topics()
            finally:
                await admin.close()
            return ConnectionCheckResult(
                name=connection.name,
                connected=True,
                message="Connection to Kafka successful.",
            )
        except NoBrokersAvailable as exc:
            return ConnectionCheckResult(
                name=connection.name,
                connected=False,
                message="Could not connect to any Kafka brokers.",
                exception=type(exc).__name__,
            )
        except Exception as exc:
            return ConnectionCheckResult(
                name=connection.name,
                connected=False,
                message="Kafka connection check failed.",
                exception=type(exc).__name__,
            )

    async def get_client(self, connection: ValidatedConnection) -> AIOKafkaProducer:
        if AIOKafkaAdminClient is None:
            raise RuntimeError("AIOKafka support requires Python's aiokafka module")

        return AIOKafkaProducer(**self._build_config(connection))

    def _build_config(self, connection: ValidatedConnection) -> dict[str, Any]:
        return build_kafka_config(
            connection.properties.model_dump(),
            {} if connection.secrets is None else connection.secrets.model_dump(),
        )

def build_kafka_config(properties: dict[str, Any], secrets: dict[str, Any]) -> dict[str, Any]:
    """Shared producer/admin/consumer configuration; CA content travels with the record."""
    props = KafkaProperties.model_validate(properties)
    credentials = KafkaSecrets.model_validate(secrets)
    config = props.model_dump(exclude={"ssl_ca_pem"}, exclude_none=True)
    if credentials.sasl_plain_password is not None:
        config["sasl_plain_password"] = credentials.sasl_plain_password
    if props.security_protocol in {"SSL", "SASL_SSL"}:
        context = ssl.create_default_context()
        if props.ssl_ca_pem:
            context.load_verify_locations(cadata=props.ssl_ca_pem)
        config["ssl_context"] = context
    return config
