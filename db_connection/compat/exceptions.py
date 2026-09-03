from fastapi import HTTPException, status

from db_connection.compat.types import ConnectionType


class DBConnectionNotFound(HTTPException):
    def __init__(
            self,
            connection_name: str | None = None,
            **kwargs,
    ):
        detail_list = []

        if connection_name is not None:
            detail_list.append(f"Name={connection_name}")

        for field_name, field_value in kwargs.items():
            if field_value is not None:
                detail_list.append(f"{field_name}={field_value}")

        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DB connection {' '.join(detail_list)} not found"
        )


class WrongDBTypeError(HTTPException):
    def __init__(
            self,
            type_received: ConnectionType,
            type_expected: ConnectionType | None = None
    ):
        detail = f"Wrong DB type, received: {type_received}"
        if type_expected is not None:
            detail += f", expected: {type_expected}"
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail
        )


class DBTypeNotSupported(HTTPException):
    def __init__(
            self,
            type_received: ConnectionType,
            message: str = ""
    ):
        detail = f"Unsupported DB type, received: {type_received}"
        if message:
            detail += f", message: {message}"

        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail
        )


class DriverNotSpecifiedError(HTTPException):
    def __init__(self, db_type: ConnectionType):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Driver not specified for {db_type} connection"
        )
