"""Render a GitHub contribution calendar as a playable-looking Breakout board.

The contribution squares are the bricks. A one-ball game with a paddle that
never misses runs headless, and only the direction changes are emitted as CSS
keyframes -- the ball travels in straight lines between them, so linear
interpolation in the browser reproduces the simulated path exactly at a
fraction of the file size.
"""

import json
import math
import sys

PITCH = 14          # cell-to-cell distance
BRICK = 11          # drawn brick size
PAD_X = 24
TOP = 26
ROWS = 7
BALL_R = 3.6
PADDLE_W = 58
PADDLE_H = 5
SPEED = 1050.0      # px/s
PADDLE_SPEED = 2000.0
MAX_BOUNCE = 60     # widest launch angle off the paddle, degrees from vertical
DT = 1.0 / 600
T_MAX = 90.0
TAIL = 1.2          # keep playing briefly after the last brick, so the loop has
                    # keyframes all the way to 100% instead of snapping to the origin

THEMES = {
    "dark": {
        "bg": "none",
        "empty": "#161b22",
        "levels": ["#243449", "#3f5f96", "#6d8fd0", "#9fc4c9"],
        "ball": "#a6cacf",
        "paddle": "#a6cacf",
        "text": "#8b929e",
    },
    "light": {
        "bg": "none",
        "empty": "#eef1f7",
        "levels": ["#c7d4ea", "#9ab0da", "#6d8fd0", "#3f5f96"],
        "ball": "#3f5f96",
        "paddle": "#3f5f96",
        "text": "#6b7280",
    },
}


def load_cells(path):
    with open(path, encoding="utf-8") as fh:
        cal = json.load(fh)["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    weeks = cal["weeks"]
    cells = []
    for wi, week in enumerate(weeks):
        for day in week["contributionDays"]:
            cells.append((wi, day["weekday"], day["contributionCount"]))
    return cells, len(weeks), cal["totalContributions"]


def level_of(count, thresholds):
    for i, t in enumerate(thresholds):
        if count <= t:
            return i
    return len(thresholds)


def simulate(bricks, width, height, floor_y):
    """Play one ball against the bricks with a paddle that never misses.

    Returns (balls, paddle events, end time, brick -> hit time, alive map), where
    each ball carries "ev", its (t, x, y) at every direction change.
    """
    alive = {k: True for k in bricks}
    remaining = len(alive)
    paddle_y = floor_y - 16
    catch_y = paddle_y - BALL_R

    def rect(key):
        return PAD_X + key[0] * PITCH, TOP + key[1] * PITCH

    def landing_x(x, y, vx, vy):
        # where the ball meets the paddle, folding in any side-wall bounces
        t = (catch_y - y) / vy
        lo, hi = BALL_R, width - BALL_R
        span = hi - lo
        u = (x + vx * t - lo) % (2 * span)
        return lo + (u if u <= span else 2 * span - u)

    def aim(lx):
        """Paddle centre that sends the ball from lx toward the nearest brick."""
        live = [k for k, v in alive.items() if v]
        if not live:
            return lx
        # prefer low, near bricks: they are reachable without a wall bank
        def cost(k):
            bx, by = rect(k)
            return abs(bx + BRICK / 2 - lx) + (ROWS - k[1]) * 6
        bx, by = rect(min(live, key=cost))
        ang = math.degrees(math.atan2(bx + BRICK / 2 - lx, catch_y - (by + BRICK / 2)))
        off = max(-1.0, min(1.0, ang / MAX_BOUNCE))
        return lx - off * PADDLE_W / 2

    ball = {"x": width / 2, "y": catch_y, "vx": 0.0, "vy": 0.0, "ev": []}
    ang = math.radians(-18)
    ball["vx"], ball["vy"] = SPEED * math.sin(ang), -SPEED * math.cos(ang)
    ball["ev"].append((0.0, ball["x"], ball["y"]))
    paddle_x = width / 2
    paddle_target = paddle_x
    paddle_ev = [(0.0, paddle_x)]
    paddle_moving = False
    hits = []

    t = 0.0
    clear_t = None
    while t < T_MAX:
        t += DT
        b = ball
        px, py = b["x"], b["y"]
        b["x"] += b["vx"] * DT
        b["y"] += b["vy"] * DT
        bounced = False

        if b["x"] < BALL_R:
            b["x"] = BALL_R; b["vx"] = abs(b["vx"]); bounced = True
        elif b["x"] > width - BALL_R:
            b["x"] = width - BALL_R; b["vx"] = -abs(b["vx"]); bounced = True
        if b["y"] < BALL_R:
            b["y"] = BALL_R; b["vy"] = abs(b["vy"]); bounced = True

        # circle against brick rectangles, only the cells the ball can touch
        col0 = int((b["x"] - BALL_R - PAD_X) // PITCH)
        row0 = int((b["y"] - BALL_R - TOP) // PITCH)
        for col in (col0, col0 + 1):
            for row in (row0, row0 + 1):
                key = (col, row)
                if not alive.get(key):
                    continue
                bx, by = rect(key)
                nx = b["x"] - max(bx, min(b["x"], bx + BRICK))
                ny = b["y"] - max(by, min(b["y"], by + BRICK))
                if nx * nx + ny * ny > BALL_R * BALL_R:
                    continue
                alive[key] = False
                remaining -= 1
                hits.append((t, key))
                # reflect on the axis the ball came in from
                came_x = px + BALL_R <= bx or px - BALL_R >= bx + BRICK
                came_y = py + BALL_R <= by or py - BALL_R >= by + BRICK
                if came_x and not came_y:
                    b["vx"] = -b["vx"]
                elif came_y and not came_x:
                    b["vy"] = -b["vy"]
                else:
                    b["vx"], b["vy"] = -b["vx"], -b["vy"]
                b["x"], b["y"] = px, py
                bounced = True
                break
            if bounced and (b["x"], b["y"]) == (px, py):
                break

        # the paddle commits to a spot the moment the ball starts coming down
        if b["vy"] > 0 and (bounced or len(b["ev"]) == 1):
            lx = landing_x(b["x"], b["y"], b["vx"], b["vy"])
            paddle_target = max(PADDLE_W / 2, min(width - PADDLE_W / 2, aim(lx)))

        if b["vy"] > 0 and b["y"] >= catch_y:
            off = (b["x"] - paddle_x) / (PADDLE_W / 2)
            assert abs(off) <= 1.0 + BALL_R / (PADDLE_W / 2), "paddle missed at t=%.2f" % t
            a = math.radians(MAX_BOUNCE * max(-1.0, min(1.0, off)))
            b["vx"], b["vy"] = SPEED * math.sin(a), -SPEED * math.cos(a)
            b["y"] = catch_y
            bounced = True

        if bounced:
            b["ev"].append((t, b["x"], b["y"]))

        step = PADDLE_SPEED * DT
        gap = paddle_target - paddle_x
        moving = abs(gap) > 1e-6
        if moving != paddle_moving:
            paddle_ev.append((t, paddle_x))
            paddle_moving = moving
        paddle_x += max(-step, min(step, gap))

        if remaining == 0 and clear_t is None:
            clear_t = t
        if clear_t is not None and t >= clear_t + TAIL:
            break

    ball["ev"].append((t, ball["x"], ball["y"]))
    paddle_ev.append((t, paddle_x))
    destroyed = {key: ht for ht, key in hits}
    return [ball], paddle_ev, t, destroyed, alive


def build(theme_name, cells, n_weeks, total, out_path):
    th = THEMES[theme_name]
    width = PAD_X * 2 + n_weeks * PITCH
    floor_y = TOP + ROWS * PITCH + 96
    height = floor_y + 16
    paddle_y = floor_y - 16

    counts = sorted(c[2] for c in cells if c[2] > 0)
    q = lambda p: counts[min(len(counts) - 1, int(len(counts) * p))]
    thresholds = [q(0.25), q(0.5), q(0.75)]

    bricks = {}
    for wi, wd, count in cells:
        if count > 0:
            bricks[(wi, wd)] = level_of(count, thresholds)

    balls, paddle_ev, total_t, destroyed, alive = simulate(bricks, width, height, floor_y)
    dur = round(total_t, 2)
    pct = lambda t: max(0.0, min(100.0, t / dur * 100.0))

    parts = []
    css = [
        ".c{transform-box:fill-box;transform-origin:center}",
        "@media (prefers-reduced-motion:reduce){.c,.ball,.pad{animation:none!important}}",
    ]

    # bricks
    for i, ((wi, wd), lvl) in enumerate(sorted(bricks.items())):
        x = PAD_X + wi * PITCH
        y = TOP + wd * PITCH
        name = "k%d" % i
        dt_ = destroyed.get((wi, wd))
        if dt_ is None:
            parts.append('<use href="#s" x="%d" y="%d" fill="%s"/>' % (x, y, th["levels"][lvl]))
            continue
        p = pct(dt_)
        # the alive stop must pin transform too, or it eases toward scale(.25)
        # for the whole run and the bricks visibly shrink before they are hit
        css.append("@keyframes %s{0%%,%.3f%%{opacity:1;transform:none}%.3f%%,100%%{opacity:0;transform:scale(.25)}}"
                   % (name, p, min(100.0, p + 0.25)))
        # a real rect rather than <use x y>: fill-box ignores a <use>'s x/y, so
        # scaling one pulls it toward the origin instead of shrinking in place
        parts.append('<rect x="%d" y="%d" width="%d" height="%d" rx="2.5" fill="%s" class="c" '
                     'style="animation:%s %ss linear infinite"/>'
                     % (x, y, BRICK, BRICK, th["levels"][lvl], name, dur))

    # every cell gets the faint board square, so a destroyed brick reveals the
    # grid underneath instead of punching a hole in it
    board = []
    for wi, wd, count in cells:
        board.append('<use href="#s" x="%d" y="%d" fill="%s"/>'
                     % (PAD_X + wi * PITCH, TOP + wd * PITCH, th["empty"]))

    # balls
    for bi, b in enumerate(balls):
        stops = []
        last = None
        # every bounce is kept: dropping one bends the whole path after it
        for t, x, y in b["ev"]:
            stop = "%.3f%%" % pct(t)
            if stop == last:
                continue
            last = stop
            stops.append("%s{transform:translate(%.1fpx,%.1fpx)}" % (stop, x, y))
        css.append("@keyframes ball%d{%s}" % (bi, "".join(stops)))
        parts.append('<circle class="ball" r="%.1f" fill="%s" style="animation:ball%d %ss linear infinite"/>'
                     % (BALL_R, th["ball"], bi, dur))

    # paddle
    stops = []
    last = None
    for t, x in paddle_ev:
        stop = "%.3f%%" % pct(t)
        if stop == last:
            continue
        last = stop
        stops.append("%s{transform:translate(%.1fpx,0)}" % (stop, x - PADDLE_W / 2))
    css.append("@keyframes pad{%s}" % "".join(stops))
    parts.append('<rect class="pad" y="%d" width="%d" height="%d" rx="2.5" fill="%s" style="animation:pad %ss linear infinite"/>'
                 % (paddle_y, PADDLE_W, PADDLE_H, th["paddle"], dur))

    label = "%s contributions in the last year" % format(total, ",")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
        'role="img" aria-label="Breakout played against %s">\n'
        '<title>%s</title>\n<style>%s</style>\n'
        '<defs><rect id="s" width="%d" height="%d" rx="2.5"/></defs>\n'
        '<g>%s</g>\n<g>%s</g>\n'
        '<text x="%d" y="%d" fill="%s" font-family="ui-monospace, SFMono-Regular, Consolas, monospace" '
        'font-size="10" letter-spacing="1.4">%s</text>\n</svg>\n'
    ) % (width, height, width, height, label, label, "".join(css), BRICK, BRICK,
         "".join(board), "".join(parts), PAD_X, height - 3, th["text"], label.upper())

    assert all(ord(ch) < 128 for ch in svg), "non-ascii leaked into the svg"
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(svg)
    return dur, len(bricks), len(destroyed), len(svg)


def main():
    cal_path, out_dir = sys.argv[1], sys.argv[2]
    cells, n_weeks, total = load_cells(cal_path)
    for theme in ("dark", "light"):
        name = "breakout.svg" if theme == "dark" else "breakout-light.svg"
        dur, nb, nd, size = build(theme, cells, n_weeks, total, out_dir + "/" + name)
        print("%-18s dur=%ss bricks=%d cleared=%d size=%dKB" % (name, dur, nb, nd, size // 1024))


if __name__ == "__main__":
    main()
