"""
Provide named and typed sentinel objects for distinguishing special values.
"""


class Sentinel:
    """
    Represent a unique marker value with a readable name.

    Sentinel instances compare by identity, so two separately created
    instances remain distinct even when they have the same name.
    """

    def __init__(self, name: str = 'Sentinel') -> None:
        """
        Create a named sentinel.

        Args:
            name: Label used in the string and representation forms.
        """
        self._name = name

    def __repr__(self) -> str:
        return f'Sentinel({self._name!r})'

    def __str__(self) -> str:
        return self._name
