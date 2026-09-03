from __future__ import annotations

from datetime import UTC, datetime

from cryptography.fernet import Fernet

from db_connection import FernetEncryptionProvider, NoOpEncryptionProvider, StoredConnectionRecordMapper


def test_record_mapper_marks_fernet_decryption_failure_as_unreadable_secrets() -> None:
    mapper = StoredConnectionRecordMapper(encryption_provider=FernetEncryptionProvider(Fernet.generate_key()))
    wrong_key_provider = FernetEncryptionProvider(Fernet.generate_key())

    record = mapper.to_record(
        id="connection-1",
        name="Broken",
        kind="sql",
        type="postgres",
        properties_json={"host": "localhost"},
        secrets_ciphertext=wrong_key_provider.encrypt({"password": "wrong-key-secret"}),
        labels_json={},
        metadata_json={},
        extra_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    assert record.secrets == {}
    assert record.raw_secrets is None
    assert [issue.code for issue in record.read_issues] == ["unreadable_secrets"]


def test_record_mapper_preserves_invalid_decrypted_secrets_as_raw_payload() -> None:
    mapper = StoredConnectionRecordMapper(encryption_provider=NoOpEncryptionProvider())

    record = mapper.to_record(
        id="connection-1",
        name="Broken",
        kind="file",
        type="s3",
        properties_json={"bucket": "test-bucket"},
        secrets_ciphertext='["broken", "json"]',
        labels_json={},
        metadata_json={},
        extra_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    assert record.secrets == {}
    assert record.raw_secrets == ["broken", "json"]
    assert [issue.code for issue in record.read_issues] == ["invalid_secrets"]
