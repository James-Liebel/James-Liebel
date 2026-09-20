"""Render a GitHub contribution calendar as a playable-looking Breakout board.

The contribution squares are the bricks. A short physics simulation runs
headless, and only the direction changes are emitted as CSS keyframes -- the
ball travels in straight lines between them, so linear interpolation in the
browser reproduces the simulated path exactly at a fraction of the file size.
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
SPEED = 620.0       # px/s
N_BALLS = 6
DT = 1.0 / 240
T_MAX = 40.0
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
    """Return (events per ball, paddle events, clear time).

    events are (t, x, y) at every direction change.
    """
    alive = {k: True for k in bricks}
    remaining = len(alive)

    balls = []
    n = N_BALLS
    for i in range(n):
        ang = -50.0 - (80.0 * i / max(1, n - 1))
        r = math.radians(ang)
        balls.append({
            "x": width * (i + 1) / (n + 1),
            "y": floor_y - 26.0,
            "vx": SPEED * math.cos(r),
            "vy": SPEED * math.sin(r),
            "ev": [],
        })
    for b in balls:
        b["ev"].append((0.0, b["x"], b["y"]))

    paddle_x = width / 2
    paddle_ev = [(0.0, paddle_x)]
    paddle_y = floor_y - 16

    def brick_at(px, py):
        if py < TOP or py > TOP + ROWS * PITCH:
            return None
        col = int((px - PAD_X) // PITCH)
        row = int((py - TOP) // PITCH)
        if (col, row) in alive and alive[(col, row)]:
            bx = PAD_X + col * PITCH
            by = TOP + row * PITCH
            if bx <= px <= bx + BRICK and by <= py <= by + BRICK:
                return (col, row)
        return None

    t = 0.0
    clear_t = None
    while t < T_MAX:
        t += DT
        # paddle chases the mean of the balls still heading down
        targets = [b["x"] for b in balls if b["vy"] > 0]
        target = sum(targets) / len(targets) if targets else width / 2
        paddle_x += max(-420 * DT, min(420 * DT, target - paddle_x))
        paddle_x = max(PADDLE_W / 2, min(width - PADDLE_W / 2, paddle_x))
        if not paddle_ev or abs(paddle_ev[-1][1] - paddle_x) > 6:
            paddle_ev.append((t, paddle_x))

        for b in balls:
            b["x"] += b["vx"] * DT
            b["y"] += b["vy"] * DT
            bounced = False

            if b["x"] < BALL_R:
                b["x"] = BALL_R; b["vx"] = abs(b["vx"]); bounced = True
            elif b["x"] > width - BALL_R:
                b["x"] = width - BALL_R; b["vx"] = -abs(b["vx"]); bounced = True
            if b["y"] < BALL_R:
                b["y"] = BALL_R; b["vy"] = abs(b["vy"]); bounced = True
            elif b["y"] > floor_y - BALL_R:
                b["y"] = floor_y - BALL_R; b["vy"] = -abs(b["vy"]); bounced = True

            # paddle deflection: angle depends on where it lands on the paddle
            if (b["vy"] > 0 and paddle_y - 6 < b["y"] < paddle_y + PADDLE_H + 6
                    and abs(b["x"] - paddle_x) < PADDLE_W / 2 + BALL_R):
                off = (b["x"] - paddle_x) / (PADDLE_W / 2)
                ang = math.radians(-90 + 52 * max(-1.0, min(1.0, off)))
                b["vx"] = SPEED * math.cos(ang)
                b["vy"] = SPEED * math.sin(ang)
                b["y"] = paddle_y - 6
                bounced = True

            hit = brick_at(b["x"], b["y"])
            if hit is not None:
                alive[hit] = False
                remaining -= 1
                bx = PAD_X + hit[0] * PITCH
                by = TOP + hit[1] * PITCH
                # reflect on the axis with the shallower overlap
                dx = min(abs(b["x"] - bx), abs(b["x"] - (bx + BRICK)))
                dy = min(abs(b["y"] - by), abs(b["y"] - (by + BRICK)))
                if dx < dy:
                    b["vx"] = -b["vx"]
                else:
                    b["vy"] = -b["vy"]
                b["hits"] = b.get("hits", [])
                b["hits"].append((t, hit))
                bounced = True

            if bounced:
                b["ev"].append((t, b["x"], b["y"]))

        if remaining == 0 and clear_t is None:
            clear_t = t
        if clear_t is not None and t >= clear_t + TAIL:
            break

    for b in balls:
        b["ev"].append((t, b["x"], b["y"]))
    paddle_ev.append((t, paddle_x))
    destroyed = {}
    for b in balls:
        for ht, key in b.get("hits", []):
            destroyed[key] = ht
    return balls, paddle_ev, t, destroyed, alive


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
            anim = ""
        else:
            p = pct(dt_)
            css.append("@keyframes %s{0%%,%.2f%%{opacity:1}%.2f%%,100%%{opacity:0;transform:scale(.25)}}"
                       % (name, p, min(100.0, p + 0.6)))
            anim = ' class="c" style="animation:%s %ss linear infinite"' % (name, dur)
        parts.append('<use href="#s" x="%d" y="%d" fill="%s"%s/>'
                     % (x, y, th["levels"][lvl], anim))

    # every cell gets the faint board square, so a destroyed brick reveals the
    # grid underneath instead of punching a hole in it
    board = []
    for wi, wd, count in cells:
        board.append('<use href="#s" x="%d" y="%d" fill="%s"/>'
                     % (PAD_X + wi * PITCH, TOP + wd * PITCH, th["empty"]))

    # balls
    for bi, b in enumerate(balls):
        stops = []
        last = -1.0
        ev = b["ev"]
        for i, (t, x, y) in enumerate(ev):
            p = pct(t)
            if p - last < 0.05 and i != len(ev) - 1:
                continue
            last = p
            stops.append("%.2f%%{transform:translate(%dpx,%dpx)}" % (p, round(x), round(y)))
        css.append("@keyframes ball%d{%s}" % (bi, "".join(stops)))
        parts.append('<circle class="ball" r="%.1f" fill="%s" style="animation:ball%d %ss linear infinite"/>'
                     % (BALL_R, th["ball"], bi, dur))

    # paddle
    stops = []
    last = -1.0
    for i, (t, x) in enumerate(paddle_ev):
        p = pct(t)
        if p - last < 0.05 and i != len(paddle_ev) - 1:
            continue
        last = p
        stops.append("%.2f%%{transform:translate(%dpx,0)}" % (p, round(x - PADDLE_W / 2)))
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
