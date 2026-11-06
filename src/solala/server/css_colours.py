from dataclasses import dataclass

from nicegui import ui


@dataclass
class Colours:
    sun: str
    house: str
    grid: str
    inverter: str
    battery: str
    battery_charge: str
    grid_import: str
    grid_export: str
    demand_window: str


async def css_colours() -> Colours:
    colour_dict = await ui.run_javascript("""
        (() => {
            const style = getComputedStyle(document.documentElement);
            return {
                sun: style.getPropertyValue('--solala-sun-color').trim(),
                house: style.getPropertyValue('--solala-house-color').trim(),
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
