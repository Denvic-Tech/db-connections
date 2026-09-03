from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ConnectionPropertiesBase(BaseModel):
    pass


class KafkaConnectionProperties(ConnectionPropertiesBase):
    """Additional connection properties for Kafka."""
    bootstrap_servers: list[str] = Field(
        ...,
        description="List of Kafka brokers, e.g., ['kafka1:9092', 'kafka2:9092']"
    )
    security_protocol: str = Field(
        default="PLAINTEXT",
        description="Security protocol used to communicate with brokers."
    )
    sasl_mechanism: str | None = Field(
        default=None,
        description="SASL mechanism for authentication, e.g., 'PLAIN', 'SCRAM-SHA-256'."
    )
    sasl_plain_username: str | None = Field(
        default=None,
        description="Username for SASL PLAIN authentication."
    )
    sasl_plain_password: str | None = Field(
        default=None,
        description="Password for SASL PLAIN authentication."
    )
    client_id: str | None = Field(
        default="kafka_client",
        description="A name for this client."
    )
    request_timeout_ms: int = Field(
        default=30000,
        description="Client request timeout in milliseconds."
    )

    @field_validator("bootstrap_servers", mode="before")
    @classmethod
    def ensure_list(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [s.strip() for s in v.split(',')]

        if isinstance(v, list):
            return v

        raise ValueError("bootstrap_servers must be a string or a list of strings.")


class S3ConnectionProperties(ConnectionPropertiesBase):
    """Дополнительные настройки для S3-совместимых подключений."""

    bucket: str = Field(..., max_length=255, description="Target bucket name.")
    region_name: str | None = Field(default=None, description="Region (AWS style) or analog.")
    endpoint_url: str | None = Field(
        default=None,
        description="Custom endpoint for S3-compatible storage (e.g., MinIO).",
    )
    access_token_id: str = Field(..., max_length=2048, description="Access key / token id.")
    access_token_key: str = Field(..., max_length=2048, description="Secret access key.")
    session_token: str | None = Field(
        default=None,
        description="Temporary session token (STS).",
    )
    use_ssl: bool = Field(default=True, description="Use HTTPS when talking to the endpoint.")
    path_style: bool = Field(
        default=False,
        description="Force path-style addressing (useful for non-AWS providers).",
    )
    signature_version: str | None = Field(
        default=None,
        description="Custom botocore signature version, e.g. 's3v4'.",
    )
    prefix: str = Field(
        ...,
        max_length=512,
        description="Base prefix for storing files, later combined as /{prefix}/{filename}.",
    )

    @field_validator("bucket", mode="before")
    @classmethod
    def normalize_bucket(cls, value: Any) -> str:
        bucket = str(value).strip() if value is not None else ""
        if not bucket:
            raise ValueError("bucket must be a non-empty string.")
        return bucket

    @field_validator("prefix", mode="before")
    @classmethod
    def normalize_prefix(cls, value: Any) -> str:
        prefix = str(value).strip("/") if value is not None else ""
        prefix = prefix.strip()
        if not prefix:
            raise ValueError("prefix must be a non-empty string without leading/trailing slashes.")
        return prefix

    @field_validator("endpoint_url", mode="before")
    @classmethod
    def normalize_endpoint(cls, value: Any) -> str | None:
        if value is None:
            return None
        endpoint = str(value).strip()
        return endpoint or None


class SqlConnectionProperties(ConnectionPropertiesBase):
    host: str = Field(..., max_length=255, description="Database host")
    port: int = Field(..., description="Database port")
    username: str = Field(..., max_length=100, description="Username")
    password: str | None = Field(default=None, max_length=2048, description="Password")
    database: str = Field(..., max_length=255, description="Database")

    secure: bool | None = Field(default=False, description="Use secure connection")
    connect_timeout: int | None = Field(default=30, description="Connection timeout")
    send_receive_timeout: int | None = Field(default=60, description="Send receive timeout")
    sync_request_timeout: int | None = Field(default=60, description="Sync request timeout")
    ca_cert_string: str | None = Field(default=None, description="CA certificate string")
    verify: bool | None = Field(default=False, description="Verify connection")
    driver_name: str | None = Field(default=None,
                                       description="Database driver, e.g. 'psycopg2', 'clickhouse-native'")


class FTPMode(str, Enum):
    """Режим подключения FTP."""
    SFTP = 'sftp'
    FTP = "ftp"
    FTPS_IMPLICIT = "ftps_implicit"
    FTPS_EXPLICIT = "ftps_explicit"


class FTPConnectionProperties(ConnectionPropertiesBase):
    """Параметры подключения к FTP/FTPS серверу."""

    # Основные параметры подключения
    host: str = Field(..., description="FTP server hostname or IP address")
    port: int = Field(21, description="FTP server port (21 for FTP, 990 for FTPS implicit)")
    mode: FTPMode = Field(FTPMode.FTP, description="Connection mode (ftp/ftps_implicit/ftps_explicit)")

    # Аутентификация
    username: str | None = Field(
        default=None,
        description="Username for authentication. If not provided and anonymous=False, will be required."
    )
    password: str | None = Field(
        default=None,
        description="Password for authentication"
    )
    anonymous: bool = Field(
        default=False,
        description="Use anonymous login. If True, username and password are ignored."
    )

    encoding: str = Field(
        default="utf-8",
        description="Connection encoding"
    )

    # Директории
    initial_directory: str | None = Field(
        default=None,
        description="Initial directory to change to after login"
    )

    # SSL/TLS настройки для FTPS
    ssl_context: dict[str, Any] | None = Field(
        default=None,
        description="SSL context configuration for custom SSL settings"
    )
    verify_ssl: bool = Field(
        default=True,
        description="Verify SSL certificates (should be True in production)"
    )
    certfile: str | None = Field(
        default=None,
        description="Client certificate file (PEM format) for mutual TLS"
    )
    keyfile: str | None = Field(
        default=None,
        description="Client private key file for mutual TLS"
    )

    @field_validator('anonymous')
    @classmethod
    def validate_anonymous(cls, v: bool, info):
        """Проверяет корректность настройки анонимного доступа."""
        values = info.data
        if v and values.get('username'):
            raise ValueError("Cannot specify both anonymous=True and username")
        return v

    @field_validator('port')
    @classmethod
    def validate_port(cls, v: int) -> int:
        """Проверяет корректность порта."""
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v

    @field_validator('mode')
    @classmethod
    def validate_mode_port(cls, v: FTPMode, info):
        """Проверяет и корректирует порт в зависимости от режима."""
        values = info.data

        # Для неявного FTPS обычно используется порт 990
        if v == FTPMode.FTPS_IMPLICIT and values.get('port') == 21:
            # Автоматически устанавливаем стандартный порт для implicit FTPS
            values['port'] = 990

        # Для обычного FTP порт обычно 21
        elif v == FTPMode.FTP and values.get('port') == 990:
            values['port'] = 21

        return v

    def get_effective_username(self) -> str:
        """Возвращает имя пользователя для аутентификации."""
        if self.anonymous:
            return "anonymous"
        return self.username or ""

    def get_effective_password(self) -> str:
        """Возвращает пароль для аутентификации."""
        if self.anonymous:
            return ""  # Для anonymous обычно пустой пароль или email
        return self.password or ""


class SFTPConnectionProperties(ConnectionPropertiesBase):
    """Параметры подключения к SFTP серверу (SSH File Transfer Protocol)."""

    # Основные параметры подключения
    host: str = Field(..., description="SFTP server hostname or IP address")
    port: int = Field(22, description="SFTP server port (usually 22 for SSH)")

    # Методы аутентификации
    username: str = Field(..., description="Username for authentication")

    # Вариант 1: Аутентификация по паролю
    password: str | None = Field(
        default=None,
        description="Password for authentication (if using password auth)"
    )

    # Вариант 2: Аутентификация по ключу
    private_key_path: str | None = Field(
        default=None,
        description="Path to private key file (PEM or OpenSSH format) for key-based auth"
    )
    private_key_passphrase: str | None = Field(
        default=None,
        description="Passphrase for encrypted private key"
    )
    private_key_string: str | None = Field(
        default=None,
        description="Private key as string (alternative to private_key_path)"
    )

    # Директории
    initial_directory: str | None = Field(
        default=None,
        description="Initial directory to change to after login"
    )

    # Настройки безопасности SSH
    allow_agent: bool = Field(
        default=False,
        description="Allow SSH agent authentication"
    )

    @field_validator('port')
    @classmethod
    def validate_port(cls, v: int) -> int:
        """Проверяет корректность порта."""
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v

    @field_validator('private_key_path')
    @classmethod
    def validate_private_key_path(cls, v: str | None):
        """Проверяет существование файла ключа, если указан путь."""
        if v and not v.strip():
            return None

        if v:
            import os
            if not os.path.exists(v):
                raise ValueError(f"Private key file not found: {v}")
            if not os.path.isfile(v):
                raise ValueError(f"Private key path is not a file: {v}")

        return v

    @field_validator('password')
    @classmethod
    def validate_auth_method(cls, v: str | None, info):
        """Проверяет, что указан хотя бы один метод аутентификации."""
        values = info.data

        has_password = bool(v)
        has_private_key = bool(values.get('private_key_path')) or bool(values.get('private_key_string'))
        allow_agent = values.get('allow_agent', False)
        look_for_keys = values.get('look_for_keys', True)

        # Если ни один метод не указан явно
        if not has_password and not has_private_key and not allow_agent and not look_for_keys:
            raise ValueError(
                "At least one authentication method must be specified: "
                "password, private_key_path, private_key_string, allow_agent=True, or look_for_keys=True"
            )

        return v


class CustomConnectionProperties(ConnectionPropertiesBase):

    type: str = Field(
        ...,
        description="Custom connection type, e.g., 'custom_type'."
    )

    class Config:
        extra = "allow"
