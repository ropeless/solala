from drawsvg import Drawing, Lines, Rectangle, Path, Group, Circle, Line, Text

from solala.utils.json import JSONDict, json_dict, json_num

GRAPHIC_SIZE: int = 300


class Infographic:
    def __init__(self) -> None:
        width = 300
        height = 320
        icon_margin_x = 40
        icon_margin_y = 50

        self.canvas = Canvas(width=width, height=height)

        # Make the icon group, relative to the canvas
        self.icons = Group()
        self.icons.append(Sun(x=26 + icon_margin_x, y=29 + icon_margin_y))
        self.icons.append(Grid(x=-5 + icon_margin_x, y=height - 64 - icon_margin_y))
        self.icons.append(House(x=width - 62 - icon_margin_x, y=-5 + icon_margin_y))
        self.icons.append(Battery(x=width - 62 - icon_margin_x, y=height - 58 - icon_margin_y))
        self.icons.append(Diamond(size=15, x=width / 2, y=height / 2))

        # Add chevrons and text
        self.make(
            state_of_charge=100,
            solar_power=0,
            grid_power=0,
            house_power=0,
            battery_power=0,
            power_scale=1,
            buy_price=0,
            feed_in_price=0,
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
    ) -> None:
        canvas = self.canvas
        cx = canvas.width / 2
        cy = canvas.height / 2

        power_scale = max(power_scale, abs(solar_power), abs(grid_power), abs(house_power), abs(battery_power))
        solar_scale = max(min(solar_power / power_scale, 1), -1)
        battery_scale = max(min(battery_power / power_scale, 1), -1)
        grid_scale = max(min(grid_power / power_scale, 1), -1)
        house_scale = max(min(house_power / power_scale, 1), -1)

        prices: str = f'{_to_price(buy_price)} / {_to_price(feed_in_price)}'

        canvas.clear()
        canvas.append(self.icons)
        canvas.append(Chevron(x=cx - 34, y=cy - 34, rotate=45, width=20 * solar_scale))
        canvas.append(Chevron(x=cx + 34, y=cy + 34, rotate=45, width=20 * battery_scale))
        canvas.append(Chevron(x=cx - 34, y=cy + 34, rotate=-45, width=20 * grid_scale))
        canvas.append(Chevron(x=cx + 34, y=cy - 34, rotate=-45, width=20 * house_scale))

        font_size = 16
        small_font_size = 12
        font_family = 'Verdana'
        top = cy - 125
        bot = cy + 130
        bot2 = bot + 20
        left = cx - 85
        right = cx + 80
        canvas.append(
            Text(_to_watts(solar_power), text_anchor='middle', font_size=font_size, font_family=font_family, x=left,
                 y=top))
        canvas.append(
            Text(_to_watts(grid_power), text_anchor='middle', font_size=font_size, font_family=font_family, x=left,
                 y=bot))
        canvas.append(
            Text(_to_watts(house_power), text_anchor='middle', font_size=font_size, font_family=font_family, x=right,
                 y=top))
        canvas.append(
            Text(_to_watts(battery_power), text_anchor='middle', font_size=font_size, font_family=font_family, x=right,
                 y=bot))

        canvas.append(
            Text(prices, text_anchor='middle', font_size=small_font_size, font_family=font_family, x=left,
                 y=bot2))
        canvas.append(
            Text(_to_pct(state_of_charge), text_anchor='middle', font_size=small_font_size, font_family=font_family,
                 x=right,
                 y=bot2))

    def as_svg(self) -> str:
        return self.canvas.as_svg()


def _to_price(price: float) -> str:
    price = abs(price)
    return f'{price:0.2f}'


def _to_watts(power: float) -> str:
    power = abs(power)
    if power < 1000:
        return f'{int(round(power))} W'
    else:
        return f"{power / 1000:.2f} kW"


def _to_pct(state_of_charge: float) -> str:
    return f'{int(round(state_of_charge))}%'


class Canvas(Drawing):
    def __init__(self, *, width: float, height: float):
        super().__init__(width, height, origin=(0, 0))

        stroke = 1.2
        radius = 4  # corner radius
        half_stroke = stroke / 2
        self.background = Rectangle(
            half_stroke, half_stroke, self.width - stroke, self.height - stroke,
            fill='#f2f5f8', stroke="#e1e9ef", stroke_width=stroke,
            rx=radius,
        )
        self.clear()

    def clear(self) -> None:
        self.elements.clear()
        self.append(self.background)


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

    def move_to(self, x: float, y: float) -> None:
        self._x = x
        self._y = y
        self._transform = f'translate({x}, {y})'

    def move(self, dx: float, dy: float) -> None:
        self._x += dx
        self._y += dy
        self._transform = f'translate({self._x}, {self._y})'

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


class Diamond(Shape):

    def __init__(
            self,
            *,
            size: int,
            x: float = 0,
            y: float = 0,
            color: str = 'black',
    ) -> None:
        super().__init__(x=x, y=y)

        diamond = Lines(
            0, size,  # Top point
            size, 0,  # Right point
            0, -size,  # Bottom point
            -size, 0,  # Left point
            close=True,  # Connect the last point back to the first point
            fill=color  # Fill the shape with colour
        )
        self.append(diamond)


class Battery(Shape):

    def __init__(
            self,
            *,
            size: int = 64,
            x: float = 0,
            y: float = 0,
            stroke_width=5,
            color: str = 'darkgreen',
    ) -> None:
        super().__init__(x=x, y=y)
        s = size / 64

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
            fill="none",
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
        rays.append(Rectangle(x=204, y=52, width=38, height=92, rx=19))
        rays.append(Rectangle(x=270, y=52, width=38, height=92, rx=19))
        rays.append(Rectangle(x=204, y=368, width=38, height=92, rx=19))
        rays.append(Rectangle(x=270, y=368, width=38, height=92, rx=19))
        rays.append(Rectangle(x=52, y=204, width=92, height=38, rx=19))
        rays.append(Rectangle(x=52, y=270, width=92, height=38, rx=19))
        rays.append(Rectangle(x=368, y=204, width=92, height=38, rx=19))
        rays.append(Rectangle(x=368, y=270, width=92, height=38, rx=19))
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
            size: float = 44,
            width: float = 20,
            x: float = 0,
            y: float = 0,
            rotate: float = 0,
            stroke_width: float = 5,
            color: str = 'gray',
    ):
        super().__init__(x=x, y=y, rotate=rotate)
        s = size / 64
        w = width / 2

        if width > 0:
            start = (w - 32) * s
            mid = w / 2
            end = 32 * s
        else:
            start = -32 * s
            mid = w / 2
            end = (32 + w) * s

        self.append(Line(start, 0, end, 0, stroke_width=stroke_width * s, stroke=color))
        if abs(w) > 0.1:
            self.append(Path(
                d=f"M {start - w * s},{-w * s} "
                  f"L {start},0 "
                  f"L {start - w * s},{w * s}",
                fill="none",
                stroke=color,
                stroke_width=stroke_width * s,
                stroke_linecap="round"
            ))
            self.append(Path(
                d=f"M {mid - w * s},{-w * s} "
                  f"L {mid},0 "
                  f"L {mid - w * s},{w * s}",
                fill="none",
                stroke=color,
                stroke_width=stroke_width * s,
                stroke_linecap="round"
            ))
            self.append(Path(
                d=f"M {end - w * s},{-w * s} "
                  f"L {end},0 "
                  f"L {end - w * s},{w * s}",
                fill="none",
                stroke=color,
                stroke_width=stroke_width * s,
                stroke_linecap="round"
            ))
