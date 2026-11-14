class Sentinel:

    def __init__(self, name: str = 'Sentinel') -> None:
        self._name = name

    def __repr__(self) -> str:
        return f'Sentinel({self._name!r})'

    def __str__(self) -> str:
        return self._name
