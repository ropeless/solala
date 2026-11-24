# Python style decisions

## IDE inspections

Follow the [PyCharm inspection workflow](../AGENTS.md#pycharm-inspections)
when checking Python changes.

## Public function and method annotations

Annotate the parameters and return values of public functions and methods.
Leave implicit receiver parameters such as `self` and `cls` unannotated.
Use `-> None` for callables with no return value. Annotate private helpers
where the types clarify a contract that would otherwise be hard to infer.

## Class method return types

Use `typing.Self` as the return annotation for a class method that returns an
instance of `cls`. This preserves the concrete type when a subclass calls the
method. Annotate class methods that return other values with their actual
return types.

## String literals

Prefer single quotes for ordinary string literals. Use double quotes when
they avoid escaping an embedded single quote.

## Docstrings

Use Google-style docstrings. Put the summary on its own line between opening
and closing triple double quotes, even when the summary is the entire
docstring. Add sections such as `Args:`, `Returns:`, and `Raises:` when they
provide information the reader needs.

```python
class AppConfig:
    @classmethod
    def load(cls, path: Path) -> Self:
        """
        Load the application configuration from a TOML file.

        Args:
            path: Path to the application configuration file.

        Returns:
            The validated application configuration.

        Raises:
            ValueError: A configuration setting is invalid.
        """
```
