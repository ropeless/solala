from drawsvg import Drawing, Lines, Rectangle, Path, Group, Circle, Line, Text, TSpan

from solala.server_constants import BUY_PRICE_RED, BUY_PRICE_AMBER
from solala.units import WATTS, KILOWATTS, PERCENT, PRICE_DOLLARS, PRICE_CENTS
from solala.utils.json import JSONDict, json_dict, json_num, json_bool

GRAPHIC_SIZE: int = 300

CLICK_ID_SUN = 'click_sun'
CLICK_ID_GRID = 'click_grid'
CLICK_ID_HOME = 'click_home'
CLICK_ID_BATTERY = 'click_battery'
CLICK_ID_INVERTER = 'click_battery'


def _click_area(name: str, x: float, y: float) -> Rectangle:
    return Rectangle(
        id=name,
        x=x, y=y, width=90, height=110,
        fill='transparent', stroke='transparent',
        # fill='gray',
    )


class Infographic:
    def __init__(self) -> None:
        width = 300
        height = 340
        icon_offset = 50

        self.canvas = Drawing(width=width, height=height, origin=(-width / 2, -height / 2))
        self.icon_offset = icon_offset

        # Make the static parts (background)
        self.static_background = Group()
        # bg_stroke = 1.2
        # self.static_background.append(Rectangle(
        #     bg_stroke / 2 - width / 2, bg_stroke / 2 - height / 2, width - bg_stroke, height - bg_stroke,
        #     fill='#f2f5f8', stroke="#e1e9ef", stroke_width=bg_stroke,
        #     rx=4,
        # ))

        # Clickable areas
        self.static_background.append(_click_area(CLICK_ID_SUN, x=-83 - icon_offset, y=-83 - icon_offset))
        self.static_background.append(_click_area(CLICK_ID_GRID, x=-83 - icon_offset, y=0 + icon_offset))
        self.static_background.append(_click_area(CLICK_ID_HOME, x=-5 + icon_offset, y=-85 - icon_offset))
        self.static_background.append(_click_area(CLICK_ID_BATTERY, x=0 + icon_offset, y=+5 + icon_offset))
        self.static_background.append(_click_area(CLICK_ID_INVERTER, x=-45, y=-45))

        self.static_background.append(Sun(x=-33 - icon_offset, y=-33 - icon_offset))
        self.static_background.append(Grid(x=-63 - icon_offset, y=0 + icon_offset))
        self.static_background.append(House(x=-4 + icon_offset, y=-65 - icon_offset))
        self.static_background.append(Inverter(x=0, y=0))

        # Make the default drawing
        self.make(
            state_of_charge=0,
            solar_power=0,
            grid_power=0,
            house_power=0,
            battery_power=0,
            power_scale=1,
            buy_price=0,
            feed_in_price=0,
            estimate=True,
        )

    def make_from_status(self, status: JSONDict, power_scale=2000) -> None:
        power_dict: JSONDict = json_dict(status['power'])
        price_dict: JSONDict = json_dict(status['price'])
        self.make(
            state_of_charge=json_num(power_dict['state_of_charge']),
            solar_power=json_num(power_dict['solar_power']),
            grid_power=json_num(power_dict['grid_power']),
            house_power=json_num(power_dict['house_power']),
            battery_power=json_num(power_dict['battery_power']),
            power_scale=power_scale,
            buy_price=json_num(price_dict['buy_price']),
            feed_in_price=json_num(price_dict['feed_in_price']),
            estimate=json_bool(price_dict['estimate']),
        )

    def make(
            self,
            *,
            state_of_charge: float,
            solar_power: float,
            grid_power: float,
            house_power: float,
            battery_power: float,
            power_scale: float,
            buy_price: float,
            feed_in_price: float,
            estimate: bool,
    ) -> None:
        canvas = self.canvas
        icon_offset = self.icon_offset

        power_scale = max(power_scale, abs(solar_power), abs(grid_power), abs(house_power), abs(battery_power))
        solar_scale = max(min(solar_power / power_scale, 1), -1)
        battery_scale = max(min(battery_power / power_scale, 1), -1)
        grid_scale = max(min(grid_power / power_scale, 1), -1)
        house_scale = max(min(house_power / power_scale, 1), -1)

        canvas.clear()

        canvas.append(self.static_background)
        canvas.append(Battery(x=-3 + icon_offset, y=+5 + icon_offset, state_of_charge=state_of_charge))

        max_chevron_width = 30
        canvas.append(Chevron(x=- 34, y=- 34, rotate=45, width=max_chevron_width * solar_scale))
        canvas.append(Chevron(x=+ 34, y=+ 34, rotate=45, width=max_chevron_width * battery_scale))
        canvas.append(Chevron(x=- 34, y=+ 34, rotate=-45, width=max_chevron_width * grid_scale))
        canvas.append(Chevron(x=+ 34, y=- 34, rotate=-45, width=max_chevron_width * house_scale))

        font_size = 16
        small_font_size = 12
        top = -125
        bot = 130
        bot2 = bot + 20
        bot3 = bot2 + 20
        left = -83
        right = 80
        class_text = 'solala-svg-text'
        class_text_amber = 'solala-svg-text-amber'
        class_text_danger = 'solala-svg-text-danger'
        kwargs = {'text_anchor': 'middle'}

        canvas.append(Text(_to_watts(solar_power), x=left, y=top, font_size=font_size, class_=class_text, **kwargs))
        canvas.append(Text(_to_watts(grid_power), x=left, y=bot, font_size=font_size, class_=class_text, **kwargs))
        canvas.append(Text(_to_watts(house_power), x=right, y=top, font_size=font_size, class_=class_text, **kwargs))
        canvas.append(Text(_to_watts(battery_power), x=right, y=bot, font_size=font_size, class_=class_text, **kwargs))
        canvas.append(
            Text(_to_pct(state_of_charge), x=right, y=bot2, font_size=small_font_size, class_=class_text, **kwargs))

        # price
        prefix: str = '~ ' if estimate else ''
        if buy_price >= 100:
            buy_str = _to_dollars(buy_price)
            feed_in_str = _to_dollars(feed_in_price)
            units = PRICE_DOLLARS
        else:
            buy_str = _to_cents(buy_price)
            feed_in_str = _to_cents(feed_in_price)
            units = PRICE_CENTS
        if buy_price >= BUY_PRICE_RED:
            buy_colour = class_text_danger
        elif buy_price >= BUY_PRICE_AMBER:
            buy_colour = class_text_amber
        else:
            buy_colour = class_text
        if feed_in_price < 0:
            feed_in_colour = class_text_danger
        else:
            feed_in_colour = class_text

        buy_text = Text(
            prefix + 'buy: ', x=left, y=bot2, font_size=small_font_size, class_=class_text, **kwargs
        )
        buy_text.append(TSpan(buy_str + units, class_=buy_colour))
        canvas.append(buy_text)

        feed_in_text = Text(
            prefix + 'feed in: ', x=left, y=bot3, font_size=small_font_size, class_=class_text, **kwargs
        )
        feed_in_text.append(TSpan(feed_in_str + units, class_=feed_in_colour))
        canvas.append(feed_in_text)

    def as_svg(self) -> str:
        return self.canvas.as_svg()


def _to_dollars(price: float) -> str:
    price /= 100
    price_str = f'{price:0.2f}'
    if price_str == '-0.00':
        price_str = '0.00'
    return price_str


def _to_cents(price: float) -> str:
    price_str = f'{price:0.1f}'
    if price_str == '-0.0':
        price_str = '0.0'
    return price_str


def _to_watts(power: float) -> str:
    power = abs(power)
    if power < 1000:
        return f'{int(round(power))}{WATTS}'
    else:
        return f"{power / 1000:.2f}{KILOWATTS}"


def _to_pct(state_of_charge: float) -> str:
    return f'{int(round(state_of_charge))}{PERCENT}'


class Shape(Group):
    def __init__(
            self,
            *,
            x: float = 0,
            y: float = 0,
            scale: float = 1,
            rotate: float = 0,
    ) -> None:
        super().__init__(transform=f'translate({x},{y}) scale({scale}) rotate({rotate})')
        self._x = x
        self._y = y

    @property
    def _transform(self) -> str:
        return self.args['transform']

    @_transform.setter
    def _transform(self, value: str):
        self.args['transform'] = value


class House(Shape):
    def __init__(
            self,
            *,
            size=64,
            x: float = 0,
            y: float = 0,
            stroke_width=5,
            color='#2196F3',
    ):
        """
        Draw a simple house icon with no windows.

        Parameters
        ----------
        size : float
            Width and height of the icon.
        stroke_width : float
            Stroke width, scaled relative to the icon size.
        """
        super().__init__(x=x, y=y)

        # Scale from the original 64 x 64 design
        s = size / 64

        # Roof
        self.append(Path(
            d=f'M {7 * s},{30 * s} '
              f'L {32 * s},{9 * s} '
              f'L {57 * s},{30 * s}',
            fill='none',
            stroke=color,
            stroke_width=stroke_width * s,
            stroke_linecap='round',
            stroke_linejoin='round'
        ))

        # House body
        self.append(Path(
            d=f'M {12 * s},{27 * s} '
              f'L {12 * s},{56 * s} '
              f'L {52 * s},{56 * s} '
              f'L {52 * s},{27 * s}',
            fill='none',
            stroke=color,
            stroke_width=stroke_width * s,
            stroke_linejoin='round'
        ))

        # Door
        self.append(Path(
            d=f'M {25 * s},{56 * s} '
              f'L {25 * s},{39 * s} '
              f'L {39 * s},{39 * s} '
              f'L {39 * s},{56 * s}',
            fill='none',
            stroke=color,
            stroke_width=stroke_width * s,
            stroke_linejoin='round'
        ))


class Inverter(Shape):

    def __init__(
            self,
            *,
            size: int = 15,
            x: float = 0,
            y: float = 0,
            stroke_width=3,
            color: str = 'gray',
    ) -> None:
        super().__init__(x=x, y=y)

        diamond = Lines(
            0, size,  # Top point
            size, 0,  # Right point
            0, -size,  # Bottom point
            -size, 0,  # Left point
            close=True,  # Connect the last point back to the first point
            fill="none",
            stroke=color,  # Stroke the shape with colour
            stroke_width=stroke_width,
            stroke_linejoin="round",
        )

        # 2. Corrected Sine Wave
        size -= stroke_width * 2
        wave = Path(
            fill="none",
            stroke=color,
            stroke_width=stroke_width,
            stroke_linejoin="round",
            stroke_linecap="round",
        )
        amp = size * 0.35
        wave.M(-size, 0)
        wave.L(-size * 0.75, -amp * 0.7)
        wave.L(-size * 0.5, -amp)
        wave.L(-size * 0.25, -amp * 0.7)
        wave.L(0, 0)
        wave.L(size * 0.25, amp * 0.7)
        wave.L(size * 0.5, amp)
        wave.L(size * 0.75, amp * 0.7)
        wave.L(size, 0)

        self.append(diamond)
        self.append(wave)


class Battery(Shape):

    def __init__(
            self,
            *,
            size: int = 64,
            x: float = 0,
            y: float = 0,
            stroke_width=5,
            state_of_charge: float = 100,
            color: str = 'darkgreen',
            start_of_charge_color: str = '#00A000',
    ) -> None:
        super().__init__(x=x, y=y)
        s = size / 64

        # Battery charge visual
        height = state_of_charge / 100 * 30 + stroke_width + 0.3
        self.append(Rectangle(
            x=18 * s,
            y=(52 - stroke_width / 2 - height) * s,
            width=28 * s,
            height=height * s,
            fill=start_of_charge_color,
            id=CLICK_ID_BATTERY,
        ))

        # Battery body
        self.append(Path(
            d=f"M {18 * s},{12 * s} "
              f"L {46 * s},{12 * s} "
              f"L {46 * s},{52 * s} "
              f"L {18 * s},{52 * s} Z",
            fill="none",
            stroke=color,
            stroke_width=stroke_width * s,
            stroke_linejoin="round"
        ))

        # Positive terminal
        self.append(Path(
            d=f"M {27 * s},{12 * s} "
              f"L {27 * s},{7 * s} "
              f"L {37 * s},{7 * s} "
              f"L {37 * s},{12 * s}",
            fill=color,
            stroke=color,
            stroke_width=stroke_width * s,
            stroke_linejoin="round"
        ))


class Sun(Shape):
    def __init__(
            self,
            *,
            size: float = 80,
            x: float = 0,
            y: float = 0,
            color: str = '#FFB700',
    ):
        super().__init__(x=x, y=y, scale=size / 512)
        rays = Group(transform='rotate(45, 0, 0) translate(-256, -256)', fill=color)
        rays.append(Rectangle(x=204, y=52, width=38, height=92, rx=19, id=CLICK_ID_SUN))
        rays.append(Rectangle(x=270, y=52, width=38, height=92, rx=19, id=CLICK_ID_SUN))
        rays.append(Rectangle(x=204, y=368, width=38, height=92, rx=19, id=CLICK_ID_SUN))
        rays.append(Rectangle(x=270, y=368, width=38, height=92, rx=19, id=CLICK_ID_SUN))
        rays.append(Rectangle(x=52, y=204, width=92, height=38, rx=19, id=CLICK_ID_SUN))
        rays.append(Rectangle(x=52, y=270, width=92, height=38, rx=19, id=CLICK_ID_SUN))
        rays.append(Rectangle(x=368, y=204, width=92, height=38, rx=19, id=CLICK_ID_SUN))
        rays.append(Rectangle(x=368, y=270, width=92, height=38, rx=19, id=CLICK_ID_SUN))
        self.append(rays)
        self.append(Circle(cx=0, cy=0, r=116, fill=color))


class Grid(Shape):
    def __init__(
            self,
            *,
            size: float = 64,
            x: float = 0,
            y: float = 0,
            stroke_width: float = 5,
            color: str = 'black',
    ):
        super().__init__(x=x, y=y)
        s = size / 64

        # Main pole
        self.append(Path(
            d=f"M {30 * s},{12 * s} "
              f"L {30 * s},{56 * s}",
            fill="none",
            stroke=color,
            stroke_width=stroke_width * s,
            stroke_linecap="round"
        ))

        # Cross arm
        self.append(Path(
            d=f"M {14 * s},{18 * s} "
              f"L {46 * s},{18 * s}",
            fill="none",
            stroke=color,
            stroke_width=stroke_width * s,
            stroke_linecap="round"
        ))

        # Left insulator
        self.append(Path(
            d=f"M {18 * s},{18 * s} "
              f"L {18 * s},{13 * s}",
            fill="none",
            stroke=color,
            stroke_width=stroke_width * s,
            stroke_linecap="round"
        ))

        # Centre insulator
        self.append(Path(
            d=f"M {30 * s},{18 * s} "
              f"L {30 * s},{11 * s}",
            fill="none",
            stroke=color,
            stroke_width=stroke_width * s,
            stroke_linecap="round"
        ))

        # Right insulator
        self.append(Path(
            d=f"M {42 * s},{18 * s} "
              f"L {42 * s},{13 * s}",
            fill="none",
            stroke=color,
            stroke_width=stroke_width * s,
            stroke_linecap="round"
        ))

        # Ground
        self.append(Path(
            d=f"M {20 * s},{56 * s} "
              f"L {40 * s},{56 * s}",
            fill="none",
            stroke=color,
            stroke_width=stroke_width * s,
            stroke_linecap="round"
        ))


class Chevron(Shape):
    def __init__(
            self,
            *,
            length: float = 44,
            width: float = 40,
            x: float = 0,
            y: float = 0,
            rotate: float = 0,
            stroke_width: float = 5,
            color: str = 'gray',
    ):
        super().__init__(x=x, y=y, rotate=rotate)

        min_width = 4

        if abs(width) < 0.2:
            width = 0
        elif 0 < width < min_width:
            width = min_width
        elif -min_width < width < 0:
            width = -min_width

        l = length / 64
        w = width / 2

        if width > 0:
            start = (w - 32) * l
            mid = w / 2
            end = 32 * l
        else:
            start = -32 * l
            mid = w / 2
            end = (32 + w) * l

        self.append(Line(start, 0, end, 0, stroke_width=stroke_width * l, stroke=color))
        if abs(w) > 0:
            self.append(Path(
                d=f"M {start - w * l},{-w * l} "
                  f"L {start},0 "
                  f"L {start - w * l},{w * l}",
                fill="none",
                stroke=color,
                stroke_width=stroke_width * l,
                stroke_linecap="round"
            ))
            self.append(Path(
                d=f"M {mid - w * l},{-w * l} "
                  f"L {mid},0 "
                  f"L {mid - w * l},{w * l}",
                fill="none",
                stroke=color,
                stroke_width=stroke_width * l,
                stroke_linecap="round"
            ))
            self.append(Path(
                d=f"M {end - w * l},{-w * l} "
                  f"L {end},0 "
                  f"L {end - w * l},{w * l}",
                fill="none",
                stroke=color,
                stroke_width=stroke_width * l,
                stroke_linecap="round"
            ))
