from __future__ import annotations

# pylint: disable=invalid-name
import asyncio
import contextlib
import io
import socket
import ssl
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, field_validator, model_validator

from ..connectors.base import Connector
from ..domain.entities import ConnectionCheckResult, ValidatedConnection

if TYPE_CHECKING:  # pragma: no cover
    from ftplib import FTP, FTP_TLS

    from paramiko import SFTPClient, SSHClient
else:
    FTP = Any
    FTP_TLS = Any
    SSHClient = Any
    SFTPClient = Any

try:
    from ftplib import FTP, FTP_TLS, error_perm, error_proto, error_reply, error_temp

    FTP_ERRORS = (error_perm, error_temp, error_reply, error_proto)
except ImportError:  # pragma: no cover
    FTP = None
    FTP_TLS = None

    class FTPError(Exception):
        pass

    FTP_ERRORS = (FTPError,)
    error_perm = FTPError

try:
    from paramiko import AutoAddPolicy, ECDSAKey, Ed25519Key, RSAKey, SSHClient, SSHException
    from paramiko.ssh_exception import AuthenticationException, NoValidConnectionsError

    SFTP_AVAILABLE = True
except ImportError:  # pragma: no cover
    SSHClient = None
    SFTPClient = None
    RSAKey = None
    ECDSAKey = None
    Ed25519Key = None

    class SSHException(Exception):
        pass

    class NoValidConnectionsError(ConnectionError):
        pass

    class AuthenticationException(Exception):
        pass

    SFTP_AVAILABLE = False

PRIVATE_KEY_CLASSES = (RSAKey, ECDSAKey, Ed25519Key)
SFTP_CLIENT_ATTR = "db_connection_ssh_client"


class FTPMode(str, Enum):
    FTP = "ftp"
    FTPS_IMPLICIT = "ftps_implicit"
    FTPS_EXPLICIT = "ftps_explicit"


class FTPProperties(BaseModel):
    host: str = Field(..., description="FTP server hostname or IP address")
    port: int = Field(21, description="FTP server port")
    mode: FTPMode = Field(FTPMode.FTP, description="Connection mode")
    username: str | None = Field(default=None, description="Username for authentication")
    anonymous: bool = Field(default=False, description="Use anonymous login")
    encoding: str = Field(default="utf-8", description="Connection encoding")
    initial_directory: str | None = Field(default=None, description="Initial directory after login")
    ssl_context: dict[str, Any] | None = Field(default=None, description="Custom SSL context config")
    verify_ssl: bool = Field(default=True, description="Verify SSL certificates")
    certfile: str | None = Field(default=None, description="Client certificate file")
    keyfile: str | None = Field(default=None, description="Client private key file")

    @field_validator("anonymous")
    @classmethod
    def validate_anonymous(cls, value: bool, info) -> bool:
        if value and info.data.get("username"):
            raise ValueError("Cannot specify both anonymous=True and username")
        return value

    @field_validator("port")
    @classmethod
    def validate_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return value

    @model_validator(mode="after")
    def normalize_port_for_mode(self) -> FTPProperties:
        if self.mode == FTPMode.FTPS_IMPLICIT and self.port == 21:
            self.port = 990
        elif self.mode == FTPMode.FTP and self.port == 990:
            self.port = 21
        return self


class FTPSecrets(BaseModel):
    password: str | None = None


class SFTPProperties(BaseModel):
    host: str = Field(..., description="SFTP server hostname or IP address")
    port: int = Field(22, description="SFTP server port")
    username: str = Field(..., description="Username for authentication")
    private_key_path: str | None = Field(default=None, description="Path to private key file")
    initial_directory: str | None = Field(default=None, description="Initial directory after login")
    allow_agent: bool = Field(default=False, description="Allow SSH agent authentication")

    @field_validator("port")
    @classmethod
    def validate_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return value

    @field_validator("private_key_path")
    @classmethod
    def validate_private_key_path(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        if not normalized:
            return None

        key_path = Path(normalized)
        if not key_path.exists():
            raise ValueError(f"Private key file not found: {normalized}")
        if not key_path.is_file():
            raise ValueError(f"Private key path is not a file: {normalized}")
        return normalized


class SFTPSecrets(BaseModel):
    password: str | None = None
    private_key_passphrase: str | None = None
    private_key_string: str | None = None


class FTPConnector(Connector):
    SUPPORTED_MODES = frozenset({FTPMode.FTP, FTPMode.FTPS_IMPLICIT, FTPMode.FTPS_EXPLICIT})

    async def check(self, connection: ValidatedConnection) -> ConnectionCheckResult:
        return await asyncio.to_thread(self._check_blocking, connection)

    async def get_client(self, connection: ValidatedConnection) -> FTP:
        return await asyncio.to_thread(self._get_client_blocking, connection)

    def _check_blocking(self, connection: ValidatedConnection) -> ConnectionCheckResult:
        client = None
        props = self._ensure_properties(connection)
        try:
            if props.mode not in self.SUPPORTED_MODES:
                return ConnectionCheckResult(
                    name=connection.name,
                    connected=False,
                    message=f"FTPConnector does not support mode: {props.mode}",
                )

            if not self._check_host_port(props.host, props.port):
                return ConnectionCheckResult(
                    name=connection.name,
                    connected=False,
                    message=f"Host {props.host}:{props.port} is unreachable",
                )

            client = self._get_client_blocking(connection)
            return ConnectionCheckResult(
                name=connection.name,
                connected=True,
                message=f"Connected successfully. Current directory: {client.pwd()}",
            )
        except TimeoutError as exc:
            return self._check_failure_result(
                connection,
                exc,
                message="Connection timed out",
            )
        except FTP_ERRORS as exc:
            return self._check_failure_result(
                connection,
                exc,
                message=self._parse_ftp_error(str(exc)),
                exception=str(exc),
            )
        except Exception as exc:
            return self._check_failure_result(
                connection,
                exc,
                message=f"Unexpected error: {exc!s}",
                exception=str(exc),
            )
        finally:
            if client is not None:
                self._close_client(client)

    def _get_client_blocking(self, connection: ValidatedConnection) -> FTP:
        props = self._ensure_properties(connection)
        secrets = self._get_ftp_secrets(connection)
        return self._create_client(props, secrets)

    def _ensure_properties(self, connection: ValidatedConnection) -> FTPProperties:
        props = connection.properties
        if not isinstance(props, FTPProperties):
            raise TypeError(f"Expected FTPProperties, got {type(props).__name__}")
        return props

    def _get_ftp_secrets(self, connection: ValidatedConnection) -> FTPSecrets:
        secrets = connection.secrets
        if secrets is None:
            return FTPSecrets()
        if not isinstance(secrets, FTPSecrets):
            raise TypeError(f"Expected FTPSecrets, got {type(secrets).__name__}")
        return secrets

    def _create_client(self, props: FTPProperties, secrets: FTPSecrets) -> FTP:
        if FTP is None:
            raise RuntimeError("FTP support requires Python's ftplib module")

        timeout = 30
        if props.mode in (FTPMode.FTPS_IMPLICIT, FTPMode.FTPS_EXPLICIT):
            client = FTP_TLS(
                timeout=timeout,
                encoding=props.encoding,
                context=self._build_ssl_context(props),
            )
        else:
            client = FTP(timeout=timeout, encoding=props.encoding)

        client.connect(props.host, props.port)

        if hasattr(client, "prot_p"):
            client.auth()
            client.prot_p()

        client.login(
            user="anonymous" if props.anonymous else (props.username or ""),
            passwd="" if props.anonymous else (secrets.password or ""),
        )
        client.set_pasv(True)

        if props.initial_directory:
            try:
                client.cwd(props.initial_directory)
            except error_perm as exc:
                if "550" in str(exc):
                    with contextlib.suppress(Exception):
                        self._create_ftp_directory(client, props.initial_directory)

        return client

    def _build_ssl_context(self, props: FTPProperties) -> ssl.SSLContext | None:
        context = ssl.create_default_context()
        if not props.verify_ssl:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        if props.certfile:
            context.load_cert_chain(props.certfile, keyfile=props.keyfile)
        return context

    def _create_ftp_directory(self, client: FTP, directory: str) -> None:
        if not directory or directory == "/":
            return

        current_path = ""
        for part in directory.strip("/").split("/"):
            if not part:
                continue
            current_path = f"{current_path}/{part}" if current_path else part
            try:
                client.cwd(current_path)
            except error_perm:
                client.mkd(current_path)
                client.cwd(current_path)

    def _check_host_port(self, host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=5):
                return True
        except OSError:
            return False

    def _parse_ftp_error(self, error_str: str) -> str:
        if "530" in error_str:
            return "Authentication failed (incorrect username or password)"
        if "550" in error_str:
            return "Permission denied or directory not found"
        return f"FTP Error: {error_str[:100]}"

    def _close_client(self, client: FTP) -> None:
        try:
            client.quit()
        except Exception:
            with contextlib.suppress(Exception):
                client.close()


class SFTPConnector(Connector):
    async def check(self, connection: ValidatedConnection) -> ConnectionCheckResult:
        return await asyncio.to_thread(self._check_blocking, connection)

    async def get_client(self, connection: ValidatedConnection) -> SFTPClient:
        return await asyncio.to_thread(self._get_client_blocking, connection)

    def _check_blocking(self, connection: ValidatedConnection) -> ConnectionCheckResult:
        client = None
        props = self._ensure_properties(connection)
        try:
            if not self._check_host_port(props.host, props.port):
                return ConnectionCheckResult(
                    name=connection.name,
                    connected=False,
                    message=f"Host {props.host}:{props.port} is unreachable",
                )

            client = self._get_client_blocking(connection)
            return ConnectionCheckResult(
                name=connection.name,
                connected=True,
                message=f"SFTP connected. Current directory: {client.getcwd()}",
            )
        except TimeoutError as exc:
            return self._check_failure_result(
                connection,
                exc,
                message="Connection timed out",
            )
        except AuthenticationException as exc:
            return self._check_failure_result(
                connection,
                exc,
                message="Authentication failed. Check credentials or keys.",
            )
        except (SSHException, NoValidConnectionsError) as exc:
            return self._check_failure_result(
                connection,
                exc,
                message=f"SSH error: {exc!s}",
                exception=str(exc),
            )
        except Exception as exc:
            return self._check_failure_result(
                connection,
                exc,
                message=f"Error: {exc!s}",
                exception=str(exc),
            )
        finally:
            if client is not None:
                self._close_client(client)

    def _get_client_blocking(self, connection: ValidatedConnection) -> SFTPClient:
        props = self._ensure_properties(connection)
        secrets = self._get_sftp_secrets(connection)
        return self._create_client(props, secrets)

    def _ensure_properties(self, connection: ValidatedConnection) -> SFTPProperties:
        props = connection.properties
        if not isinstance(props, SFTPProperties):
            raise TypeError(f"Expected SFTPProperties, got {type(props).__name__}")
        return props

    def _get_sftp_secrets(self, connection: ValidatedConnection) -> SFTPSecrets:
        secrets = connection.secrets
        if secrets is None:
            return SFTPSecrets()
        if not isinstance(secrets, SFTPSecrets):
            raise TypeError(f"Expected SFTPSecrets, got {type(secrets).__name__}")
        return secrets

    def _load_private_key(self, props: SFTPProperties, secrets: SFTPSecrets) -> Any | None:
        if not SFTP_AVAILABLE:
            return None

        if secrets.private_key_string:
            for key_class in PRIVATE_KEY_CLASSES:
                try:
                    return key_class.from_private_key(
                        io.StringIO(secrets.private_key_string),
                        password=secrets.private_key_passphrase,
                    )
                except Exception:
                    continue

        if props.private_key_path:
            for key_class in PRIVATE_KEY_CLASSES:
                try:
                    return key_class.from_private_key_file(
                        props.private_key_path,
                        password=secrets.private_key_passphrase,
                    )
                except Exception:
                    continue

        return None

    def _create_ssh_client(self, props: SFTPProperties, secrets: SFTPSecrets) -> SSHClient:
        if not SFTP_AVAILABLE:
            raise RuntimeError("SFTP support requires 'paramiko' module.")

        client = SSHClient()
        client.set_missing_host_key_policy(AutoAddPolicy())

        connect_kwargs: dict[str, Any] = {
            "hostname": props.host,
            "port": props.port,
            "username": props.username,
            "allow_agent": props.allow_agent,
            "look_for_keys": True,
            "timeout": 30,
        }

        try:
            pkey = self._load_private_key(props, secrets)
            if pkey is not None:
                connect_kwargs["pkey"] = pkey
        except Exception as exc:
            if not secrets.password:
                raise RuntimeError(f"Failed to load private key: {exc}") from exc

        if secrets.password:
            connect_kwargs["password"] = secrets.password

        client.connect(**connect_kwargs)
        return client

    def _create_client(self, props: SFTPProperties, secrets: SFTPSecrets) -> SFTPClient:
        ssh_client = self._create_ssh_client(props, secrets)
        sftp_client = ssh_client.open_sftp()
        if props.initial_directory:
            with contextlib.suppress(Exception):
                sftp_client.chdir(props.initial_directory)
        setattr(sftp_client, SFTP_CLIENT_ATTR, ssh_client)
        return sftp_client

    def _check_host_port(self, host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=5):
                return True
        except OSError:
            return False

    def _close_client(self, client: SFTPClient) -> None:
        try:
            client.close()
            ssh_client = getattr(client, SFTP_CLIENT_ATTR, None)
            if ssh_client is not None:
                ssh_client.close()
        except Exception:
            pass
