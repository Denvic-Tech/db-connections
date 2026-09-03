class RepresentationMixin:

    @staticmethod
    def convert_long_value(value: any) -> str:
        value_str = str(value)

        if len(value_str) > 50:
            value_str = f"{value_str[:20]}...{value_str[-20:]}"

        return value_str

    def __repr__(self) -> str:
        items = " ".join([
            f'{key}={self.convert_long_value(value)}'
            for key, value in self.__dict__.items()
            if not key.startswith('_')
        ])
        return f'<{self.__class__.__name__} {items}>'

    def __str__(self) -> str:
        return self.__repr__()