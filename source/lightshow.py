"""Light show patterns: each step of a show is a color for every one of the 16 pads.

Pads sit in a 4 x 4 grid with Pad 1 at the bottom left and Pad 16 at the top right,
as on the controller. Patterns are pure functions of the step number, so a show is
the same every time and the hardware only needs the pads that change between steps.
"""

import colorsys

# id, name, what it looks like. The interface lists them in this order.
PATTERNS = [
    ('chase', 'Chase', 'A light runs around the edge of the pads'),
    ('snake', 'Snake', 'Weaves row by row through all 16 pads'),
    ('wave', 'Wave', 'A column of light sweeps left and right'),
    ('rain', 'Rain', 'Drops fall down the columns'),
    ('ripple', 'Ripple', 'Rings spread out from the center'),
    ('sparkle', 'Sparkle', 'Pads twinkle at random'),
    ('breathe', 'Breathe', 'Every pad fades in and out together'),
    ('rainbow', 'Rainbow', 'Colors flow diagonally across the pads'),
]
IDS = [p[0] for p in PATTERNS]
PADS = [f'pad{i}' for i in range(1, 17)]
# Brightness of a moving light and the two steps behind it.
TAIL = (1.0, 0.35, 0.12)
RING = [(0, 0), (1, 0), (2, 0), (3, 0), (3, 1), (3, 2), (3, 3), (2, 3), (1, 3), (0, 3), (0, 2), (0, 1)]
SNAKE = [(x if y % 2 == 0 else 3 - x, y) for y in range(4) for x in range(4)]


def position(cid):
    """(column, row) of a pad, counted from the bottom left."""
    n = int(cid[3:]) - 1
    return n % 4, n // 4


def _trail(path, step):
    """A light moving along path, with a fading tail."""
    lit = {}
    for back, level in enumerate(TAIL):
        lit.setdefault(path[(step - back) % len(path)], level)
    return lambda x, y: lit.get((x, y), 0.0)


def _twinkle(step, cid):
    # A small integer hash, so Sparkle repeats exactly without a random generator.
    h = (step * 7919 + int(cid[3:]) * 104729) * 2654435761 & 0xFFFFFFFF
    return (h >> 11) % 7 == 0


def intensity(pattern, step):
    """Brightness from 0 to 1 for each pad at this step."""
    if pattern == 'chase':
        at = _trail(RING, step)
    elif pattern == 'snake':
        at = _trail(SNAKE, step)
    elif pattern == 'wave':
        column = [0, 1, 2, 3, 2, 1][step % 6]
        at = lambda x, y: 1.0 if x == column else 0.25 if abs(x - column) == 1 else 0.0  # noqa: E731
    elif pattern == 'rain':
        # Each column has its own drop: it enters at the top, falls, then pauses for two steps.
        def at(x, y):
            head = 3 - (step + (0, 3, 1, 4)[x]) % 6
            return 1.0 if y == head else 0.3 if y == head + 1 else 0.0
    elif pattern == 'ripple':
        # Rings: the 4 center pads, the 8 edge pads, then the 4 corners; one dark step between waves.
        def at(x, y):
            ring = (x in (0, 3)) + (y in (0, 3))
            phase = step % 4
            return 1.0 if ring == phase else 0.3 if ring == phase - 1 else 0.0
    elif pattern == 'sparkle':
        return {
            cid: max((level for back, level in enumerate(TAIL) if _twinkle(step - back, cid)), default=0.0)
            for cid in PADS
        }
    elif pattern == 'breathe':
        level = 0.08 + 0.92 * (1 - abs(step % 16 - 8) / 8)
        at = lambda x, y: level  # noqa: E731
    else:
        raise ValueError('Unknown light show: ' + str(pattern))
    return {cid: at(*position(cid)) for cid in PADS}


def scale(color, level):
    rgb = bytes.fromhex(color.removeprefix('#'))
    return '#' + bytes(round(c * level) for c in rgb).hex()


def frame(pattern, step, color=None, pads=None):
    """The color of every pad at this step. Lit pads use color, or each pad's own color from
    pads ({pad id: '#rrggbb'}) when color is None; unlit pads are off."""
    if pattern == 'rainbow':
        result = {}
        for cid in PADS:
            x, y = position(cid)
            hue = ((x + y) / 8 + step / 24) % 1
            result[cid] = '#' + bytes(round(c * 255) for c in colorsys.hsv_to_rgb(hue, 1, 1)).hex()
        return result
    pads = pads or {}
    return {cid: scale(color or pads.get(cid, '#ffffff'), level) for cid, level in intensity(pattern, step).items()}
