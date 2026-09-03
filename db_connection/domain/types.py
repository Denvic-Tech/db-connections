from typing import Literal

DefaultConnectionKinds = Literal["sql", "file", "queue"]
DefaultConnectionTypes = Literal["postgres", "mysql", "clickhouse", "mssql", "oracle", "mongodb", "kafka", "s3", "ftp", "sftp"]
