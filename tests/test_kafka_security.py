import ssl
from types import SimpleNamespace
from unittest.mock import MagicMock

from db_connection.connectors import kafka


def test_custom_ca_keeps_hostname_verification(monkeypatch):
    context = MagicMock()
    monkeypatch.setattr(kafka.ssl, "create_default_context", lambda: context)
    config = kafka.build_kafka_config(
        {"bootstrap_servers": "broker:9093", "security_protocol": "SSL",
         "ssl_ca_pem": "test-ca"},
        {},
    )
    context.load_verify_locations.assert_called_once_with(cadata="test-ca")
    assert config["ssl_context"] is context
    assert "ssl_ca_pem" not in config
    assert "ssl_check_hostname" not in config


def test_system_trust_remains_enabled():
    config = kafka.build_kafka_config(
        {"bootstrap_servers": ["broker:9093"], "security_protocol": "SSL"}, {},
    )
    assert config["ssl_context"].check_hostname
    assert config["ssl_context"].verify_mode == ssl.CERT_REQUIRED


def test_sasl_secrets_and_producer_contract(monkeypatch):
    connection = SimpleNamespace(
        properties=kafka.KafkaProperties(
            bootstrap_servers=["broker:9092"], security_protocol="SASL_PLAINTEXT",
            sasl_mechanism="SCRAM-SHA-512", sasl_plain_username="user",
        ),
        secrets=kafka.KafkaSecrets(sasl_plain_password="test-password"),
    )
    producer = MagicMock()
    monkeypatch.setattr(kafka, "KafkaProducer", producer)
    assert kafka.KafkaConnector()._get_client_blocking(connection) is producer.return_value
    assert producer.call_args.kwargs["sasl_plain_password"] == "test-password"
    assert producer.call_args.kwargs["sasl_mechanism"] == "SCRAM-SHA-512"


def test_admin_closed_and_error_redacted(monkeypatch):
    admin = MagicMock()
    admin.list_topics.side_effect = RuntimeError("credential-from-server")
    monkeypatch.setattr(kafka, "KafkaAdminClient", lambda **kwargs: admin)
    connection = SimpleNamespace(
        name="test", properties=kafka.KafkaProperties(bootstrap_servers=["broker:9092"]),
        secrets=None,
    )
    result = kafka.KafkaConnector()._check_blocking(connection)
    admin.close.assert_called_once()
    assert "credential-from-server" not in str(result)
    assert not result.connected
