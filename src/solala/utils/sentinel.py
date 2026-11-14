"""
Provide named sentinel objects for distinguishing special values.
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
        """
        Return a representation that includes the sentinel's name.
        """
        return f'Sentinel({self._name!r})'

    def __str__(self) -> str:
        """
        Return the sentinel's name.
        """
        return self._name
