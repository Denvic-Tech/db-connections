from db_connection.domain.entities import ConnectionDraft


def create_sql_connection_draft() -> ConnectionDraft:
   ...


def create_kafka_connection_draft() -> ConnectionDraft:
    ...


def create_s3_connection_draft() -> ConnectionDraft:
    ...


def create_ftp_connection_draft() -> ConnectionDraft:
    ...
