"""
Read Solala theme colours from browser CSS and format RGB colours.
"""

from dataclasses import dataclass

from nicegui import ui


@dataclass
class Colours:
    """
    Hold the computed colours used by the Solala interface.

    Each field corresponds to a `--solala-*-color` CSS custom property.
    Values are strings returned by the browser's computed style.
    """
    sun: str
    house: str
    tab: str
    grid: str
    inverter: str
    battery: str
    battery_charge: str
    grid_import: str
    grid_export: str
    demand_window: str


async def css_colours() -> Colours:
    """
    Retrieve theme colours from the current NiceGUI client's browser.

    The values are read from CSS custom properties on the document root.
    This function requires an active NiceGUI client context.

    Returns:
        Computed CSS colour values for the Solala interface.
    """
    colour_dict = await ui.run_javascript("""
        (() => {
            const style = getComputedStyle(document.documentElement);
            return {
                sun: style.getPropertyValue('--solala-sun-color').trim(),
                house: style.getPropertyValue('--solala-house-color').trim(),
                tab: style.getPropertyValue('--solala-tab-color').trim(),
                grid: style.getPropertyValue('--solala-grid-color').trim(),
                inverter: style.getPropertyValue('--solala-inverter-color').trim(),
                battery: style.getPropertyValue('--solala-battery-color').trim(),
                battery_charge: style.getPropertyValue('--solala-battery-charge-color').trim(),
                grid_import: style.getPropertyValue('--solala-grid-import-color').trim(),
                grid_export: style.getPropertyValue('--solala-grid-export-color').trim(),
                demand_window: style.getPropertyValue('--solala-demand-window-color').trim(),
            };
        })()
    """)
    return Colours(**colour_dict)


def rgba(colour: str, alpha: float = 0.1) -> str:
    """
    Convert a six-digit hexadecimal RGB colour to CSS rgba() notation.

    Args:
        colour: RGB hexadecimal string, optionally prefixed with '#'.
        alpha: Alpha component to include in the result; defaults to 0.1.

    Returns:
        CSS rgba() colour string.

    Raises:
        RuntimeError: If the input cannot be parsed as hexadecimal RGB.
    """
    try:
        colour = colour.lstrip('#')
        r, g, b = (int(colour[i:i + 2], 16) for i in (0, 2, 4))
        return f'rgba({r}, {g}, {b}, {alpha})'
    except Exception as err:
        raise RuntimeError(f'problem with colour {colour!r}', err)