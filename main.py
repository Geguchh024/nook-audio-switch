"""Audio Switch: the tile shows the default output device and its volume;
the page switches outputs and inputs with a click, mixes per-app volume, and
keeps a separate device for calls if you want one. Ctrl+Alt+A cycles
through the outputs switched on in Settings, optionally taking the matching
microphone along.

Devices, levels and app sessions are read through Core Audio with ctypes
(coreaudio.py), so nothing has to be installed. The device list is re-read
every couple of seconds; while the page is open the level meters and the
mixer update five times a second. Each view is only re-sent when it
changed."""

import json
import math
import sys
import time

import nook

if sys.platform == "win32":
    import coreaudio as ca
else:  # lets the checker run elsewhere
    ca = None

VIEWS = ["Devices", "Apps", "Settings"]
TRACK = "#8080802E"
SWEEP = 270          # degrees of the tile's volume dial, open at the bottom
GENERIC = {"speakers", "speaker", "headphones", "headset", "earphones", "microphone",
           "microphone array", "headset microphone", "line", "line in", "line out",
           "digital audio (s/pdif)", "digital output", "stereo mix", "hands-free",
           "hands-free ag audio", "external microphone"}

app = nook.Plugin()
prefs = {"skip": [], "link_mic": False, "keep_calls": {"out": False, "in": False},
         **(app.load("prefs", {}) or {})}
prefs["skip"] = list(prefs.get("skip") or app.load("skip", []) or [])   # 1.0 kept it alone
ui = {"view": 0, "error": "", "flash_until": 0.0}
state = {"out": [], "in": [], "out_vol": None, "in_vol": None, "out_peak": None,
         "in_peak": None, "apps_out": [], "apps_in": []}
last_sent = {"tile": None, "page": None}


def save_prefs():
    app.save("prefs", prefs)


# Naming ---------------------------------------------------------------------------

def titles(dev):
    """(title, subtitle): the product name first when the endpoint's own
    name is a generic word like "Speakers" or "Headset"."""
    desc, adapter = dev["desc"] or "", dev["adapter"] or ""
    if adapter and (not desc or desc.lower() in GENERIC):
        return adapter, desc or None
    return desc or dev["name"], adapter or None


def short(text, limit):
    return text if len(text) <= limit else text[:max(1, limit - 1)].rstrip() + "…"


def kind_icon(dev):
    name = (dev["name"] + " " + dev["desc"]).lower()
    if any(w in name for w in ("headphone", "headset", "earbud", "buds", "airpods", "hands-free")):
        return "headphones"
    if any(w in name for w in ("nvidia", "hdmi", "displayport", "display audio", "monitor", "tv")):
        return "monitor"
    if "bluetooth" in name:
        return "bluetooth"
    if "microphone" in name or "mic" in name:
        return "microphone"
    return "speaker-high"


def default(flow_list):
    return next((d for d in flow_list if d["default"]), None)


def calls_dev(flow_list):
    return next((d for d in flow_list if d["calls"]), None)


def pct(level):
    return f"{round(level * 100)}%"


def meter_value(peak):
    """The peak amplitude 0..1, read linearly like the Sound panel's meters."""
    return max(0.0, min(1.0, peak or 0.0))


def meter_color(v):
    return "red" if v >= 0.99 else "green"   # red only when it clips


# Reading --------------------------------------------------------------------------

def refresh():
    if ca is None:
        return
    try:
        state["out"] = ca.devices(ca.RENDER)
        state["in"] = ca.devices(ca.CAPTURE)
        o, i = default(state["out"]), default(state["in"])
        state["out_vol"] = ca.get_volume(o["id"]) if o else None
        state["in_vol"] = ca.get_volume(i["id"]) if i else None
        # A calls device set elsewhere (the Sound panel, a headset's driver) counts too.
        for flow in ("out", "in"):
            d, c = default(state[flow]), calls_dev(state[flow])
            if d and c and d is not c and not prefs["keep_calls"][flow]:
                prefs["keep_calls"][flow] = True
                save_prefs()
        ui["error"] = ""
    except OSError as e:
        ui["error"] = f"Core Audio error: {e}"
    refresh_live()


def group_apps(sessions):
    """One row per app: sessions of the same exe (a browser has several)
    share a row, the loudest volume and the louder peak."""
    rows = {}
    for s in sessions:
        key = (s["path"] or s["name"]).lower()
        r = rows.get(key)
        if not r:
            rows[key] = {"key": key, "name": s["name"], "system": s["system"], "sids": [s["sid"]],
                         "level": s["level"], "muted": s["muted"], "peak": s["peak"] or 0.0,
                         "active": s["active"]}
        else:
            r["sids"].append(s["sid"])
            r["level"] = max(r["level"], s["level"])
            r["muted"] = r["muted"] and s["muted"]
            r["peak"] = max(r["peak"], s["peak"] or 0.0)
            r["active"] = r["active"] or s["active"]
    # Playing apps first, system sounds last, then by name.
    return sorted(rows.values(), key=lambda r: (r["system"], not r["active"], r["name"].lower()))


def refresh_live():
    """Peak levels, and the per-app sessions while the Apps view is showing."""
    if ca is None:
        return
    o, i = default(state["out"]), default(state["in"])
    try:
        state["out_peak"] = ca.peak(o["id"]) if o else None
        state["in_peak"] = ca.peak(i["id"]) if i else None
        if app.page_open and ui["view"] == 1:
            state["apps_out"] = group_apps(ca.sessions(o["id"])) if o else []
            state["apps_in"] = [a for a in group_apps(ca.sessions(i["id"])) if not a["system"]] if i else []
    except OSError as e:
        ui["error"] = f"Core Audio error: {e}"


# Tile -----------------------------------------------------------------------------

def dial(cx, cy, r, level, muted, glyph):
    """The volume as a 270° arc with round caps, the device's glyph inside."""
    stroke = max(3.0, r * 0.16)
    shapes = [nook.arc(cx, cy, r, -SWEEP / 2, SWEEP / 2, color=TRACK, width=stroke)]
    color = "orange" if muted else "accent"
    if level is not None and level > 0.005:
        end = -SWEEP / 2 + SWEEP * level
        shapes.append(nook.arc(cx, cy, r, -SWEEP / 2, end, color="faint" if muted else color,
                               width=stroke))
        for deg in (-SWEEP / 2, end):
            a = math.radians(deg - 90)
            shapes.append(nook.circle(cx + r * math.cos(a), cy + r * math.sin(a), stroke / 2,
                                      fill="faint" if muted else color))
    shapes.append(nook.glyph(cx, cy, "speaker-slash" if muted else glyph, size=max(12, r * 0.95),
                             color=color, fill=not muted))
    return shapes


def bar(x, y, w, value, color, h=4):
    shapes = [nook.rect(x, y, w, h, fill=TRACK, radius=h / 2)]
    if value:
        shapes.append(nook.rect(x, y, max(h, w * value), h, fill=color, radius=h / 2))
    return shapes


def tile_tip(dev, vol):
    title, sub = titles(dev)
    tip = title + (f" ({sub})" if sub else "")
    if vol:
        tip += " · " + ("muted" if vol[1] else pct(vol[0]))
    mic = default(state["in"])
    if mic:
        tip += f"\nMic: {titles(mic)[0]}"
    calls = calls_dev(state["out"])
    if calls and calls is not dev:
        tip += f"\nCalls: {titles(calls)[0]}"
    return tip + "\nCtrl+Alt+A: next output"


def tile_view():
    w, h = app.tile_width or 104, app.tile_height or 36
    size = app.tile_size or "wide"
    dev = default(state["out"])
    if not dev:
        return nook.canvas(h, [nook.glyph(w / 2, h / 2, "speaker-slash", size=22, color="faint")],
                           width=w, tooltip=ui["error"] or "No output device")
    vol = state["out_vol"]
    level, muted = (vol[0], vol[1]) if vol else (None, False)
    glyph = kind_icon(dev)
    title, sub = titles(dev)
    detail = "Muted" if muted else (pct(level) if level is not None else (sub or "Output"))
    tip = tile_tip(dev, vol)

    if size == "small":
        side = min(w, h)
        roomy = side > 100
        r = side * (0.3 if roomy else 0.36)
        cy = h * (0.42 if roomy else 0.5)
        shapes = dial(w / 2, cy, r, level, muted, glyph)
        if roomy:
            shapes += [nook.label(w / 2, cy + r + 12, short(title, int(w / 6.5)), size=11, bold=True,
                                  anchor="center"),
                       nook.label(w / 2, cy + r + 26, detail, size=10, color="dim", anchor="center")]
        return nook.canvas(h, shapes, width=w, tooltip=tip)

    if size == "large":
        pad = 14
        r = min(h * 0.17, w * 0.16)
        cy = pad + r + 4
        shapes = dial(pad + r + 2, cy, r, level, muted, glyph)
        tx = pad + 2 * r + 16
        chars = max(6, int((w - tx - pad) / 7))
        shapes += [nook.label(tx, cy - 14, "Output", size=10, color="dim"),
                   nook.label(tx, cy + 2, short(title, chars), size=14, bold=True),
                   nook.label(tx, cy + 18, detail if sub is None or muted else f"{sub} · {detail}",
                              size=10, color="orange" if muted else "dim")]
        y = cy + r + 18
        mic = default(state["in"])
        if mic and y + 30 < h:
            mvol = state["in_vol"]
            mmuted = bool(mvol and mvol[1])
            shapes += [nook.glyph(pad + 7, y + 6, "microphone-slash" if mmuted else "microphone",
                                  size=14, color="orange" if mmuted else "dim"),
                       nook.label(pad + 20, y + 6, short(titles(mic)[0], int((w - 80) / 6.5)), size=11),
                       nook.label(w - pad, y + 6, "Muted" if mmuted else (pct(mvol[0]) if mvol else ""),
                                  size=10, color="dim", anchor="end")]
            shapes += bar(pad, y + 17, w - 2 * pad, 0 if mmuted or not mvol else mvol[0],
                          "faint" if mmuted else "accent", h=3)
            y += 32
        calls = calls_dev(state["out"])
        if calls and calls is not dev and y + 14 < h:
            shapes += [nook.glyph(pad + 7, y + 6, "phone", size=13, color="dim"),
                       nook.label(pad + 20, y + 6, "Calls: " + short(titles(calls)[0], int((w - 70) / 6.5)),
                                  size=10, color="dim")]
        return nook.canvas(h, shapes, width=w, tooltip=tip)

    # Wide: the dial, then the device and its level.
    r = h * 0.34
    cy = h / 2
    shapes = dial(h * 0.5, cy, r, level, muted, glyph)
    tx = h * 0.5 + r + 9
    chars = max(5, int((w - tx - 4) / 6.6))
    if sub and not muted and level is not None and len(sub) + 7 <= chars:
        detail = f"{sub} · {detail}"
    # A tall wide tile has room to break a long name onto two lines.
    cut = title.rfind(" ", 0, chars + 1) if h > 60 and len(title) > chars else -1
    lines = [title[:cut], short(title[cut + 1:], chars)] if cut > 0 else [short(title, chars)]
    top = cy - 7 * len(lines)
    for n, line in enumerate(lines):
        shapes.append(nook.label(tx, top + 15 * n, line, size=12, bold=True))
    shapes.append(nook.label(tx, top + 15 * len(lines), short(detail, chars), size=10,
                             color="orange" if muted else "dim"))
    return nook.canvas(h, shapes, width=w, tooltip=tip)


# Page -----------------------------------------------------------------------------

def role_note(d, flow):
    """"Calls" is only worth saying while calls have their own device."""
    calls = d["calls"] and prefs["keep_calls"][flow]
    if d["default"]:
        return "Default · Calls" if calls else "Default"
    return "Calls" if calls else None


def device_items(devs, flow):
    items = []
    for d in devs:
        title, sub = titles(d)
        note = role_note(d, flow)
        items.append(nook.item(f"{flow}:{d['id']}", title, subtitle=sub,
                               icon="check-circle" if d["default"] else
                               ("phone" if d["calls"] else kind_icon(d)),
                               trailing=note, selected=d["default"]))
    return items


def volume_block(flow, vol, peak):
    if not vol:
        return [nook.text("No volume control", size="small", color="faint")]
    level, muted = vol
    mute_icon = ("speaker-slash" if flow == "out" else "microphone-slash") if muted else \
        ("speaker-high" if flow == "out" else "microphone")
    m = 0.0 if muted else meter_value(peak)
    return [
        # [button, spacer, slider, text]: the text is packed against the right
        # edge first, then the slider takes all the room between.
        nook.row([nook.button(f"mute:{flow}", icon=mute_icon, tooltip="Unmute" if muted else "Mute"),
                  nook.spacer(),
                  nook.slider(f"vol:{flow}", round(level, 2), 0, 1, step=0.01),
                  nook.text("Muted" if muted else pct(level), size="small",
                            color="orange" if muted else "dim")], gap=8, align="center"),
        nook.progress(m, color=meter_color(m),
                      tooltip="Level" + ("" if flow == "out" else " (reads while an app records)")),
    ]


def device_card(title, icon, flow):
    devs, vol, peak = state[flow], state[f"{flow}_vol"], state[f"{flow}_peak"]
    cur = default(devs)
    body = [nook.row([nook.icon(icon, size=16, color="accent", fill=True),
                      nook.text(title, bold=True), nook.spacer(),
                      nook.text(titles(cur)[0] if cur else "None", size="small", color="dim",
                                tooltip=cur["name"] if cur else None)], gap=6, align="center")]
    body += volume_block(flow, vol, peak)
    body.append(nook.divider())
    body.append(nook.list_view(device_items(devs, flow)) if devs
                else nook.text(f"No active {title.lower()} devices", size="small", color="faint"))
    return nook.card(body, padding=12, gap=8)


def devices_page():
    hint = ("Click a device to make it the default." +
            (" The calls device stays as set in Settings." if any(prefs["keep_calls"].values()) else
             " Calls follow it too."))
    # Stacked, not a grid: the installed Nook centres grid cells of unequal
    # height on each other, which steps the shorter card down.
    return [device_card("Output", "speaker-high", "out"), device_card("Input", "microphone", "in"),
            nook.text(hint, size="small", color="faint", wrap=True)]


def app_card(a, flow):
    m = 0.0 if a["muted"] else meter_value(a["peak"])
    icon = "speaker-slash" if a["muted"] else ("bell" if a["system"] else "speaker-high")
    return nook.card([
        nook.row([nook.button(f"amute:{flow}:{a['key']}", icon=icon,
                              tooltip="Unmute" if a["muted"] else "Mute"),
                  nook.text(short(a["name"], 22), bold=True, color="dim" if a["muted"] else None,
                            tooltip=a["name"]),
                  nook.spacer(),
                  nook.slider(f"avol:{flow}:{a['key']}", round(a["level"], 2), 0, 1, step=0.01),
                  nook.text("Muted" if a["muted"] else pct(a["level"]), size="small",
                            color="orange" if a["muted"] else "dim")], gap=8, align="center"),
        nook.progress(m, color=meter_color(m)),
    ], padding=10, gap=6)


def apps_page():
    o, i = default(state["out"]), default(state["in"])
    if not o:
        return [nook.text("No output device", color="faint")]
    parts = [nook.row([nook.icon("speaker-high", size=14, color="dim"),
                       nook.text(f"Playing on {titles(o)[0]}", size="small", color="dim", bold=True)],
                      gap=6, align="center")]
    apps = state["apps_out"]
    if apps:
        parts += [app_card(a, "out") for a in apps]
    else:
        parts.append(nook.text("No app has opened this device yet", size="small", color="faint"))
    if i and state["apps_in"]:
        parts += [nook.spacer(4),
                  nook.row([nook.icon("microphone", size=14, color="dim"),
                            nook.text(f"Recording from {titles(i)[0]}", size="small", color="dim",
                                      bold=True)], gap=6, align="center")]
        parts += [app_card(a, "in") for a in state["apps_in"]]
    parts.append(nook.text("Each app's volume is relative to the device volume, like the Windows "
                           "Volume Mixer.", size="small", color="faint", wrap=True))
    return parts


def section(title, children):
    return nook.card([nook.text(title, size="small", color="dim", bold=True)] + children,
                     padding=12, gap=8)


def calls_list(flow):
    devs = state[flow]
    keep = prefs["keep_calls"][flow]
    items = [nook.item(f"calls:{flow}:same", "Same as default", icon="link",
                       subtitle="Calls use whatever is the default", selected=not keep)]
    for d in devs:
        title, sub = titles(d)
        items.append(nook.item(f"calls:{flow}:{d['id']}", title, subtitle=sub, icon="phone",
                               trailing="Calls" if keep and d["calls"] else None,
                               selected=keep and d["calls"]))
    return nook.list_view(items)


def settings_page():
    skip = set(prefs["skip"])
    cycle = [nook.toggle(f"cyc:{d['id']}", d["id"] not in skip, label=titles(d)[0]) for d in state["out"]]
    return [
        section("Ctrl+Alt+A steps through", cycle or [nook.text("No outputs", color="faint")]),
        section("Switching", [
            nook.toggle("link_mic", prefs["link_mic"],
                        label="Switch the microphone along with the output"),
            nook.text("Picks the input on the same device, e.g. a headset's mic when you switch to "
                      "the headset.", size="small", color="faint", wrap=True),
        ]),
        section("Calls: speaker", [calls_list("out")]),
        section("Calls: microphone", [calls_list("in")]),
        nook.text("Calling apps (Teams, Zoom, Discord…) use the calls device; everything else "
                  "uses the default.", size="small", color="faint", wrap=True),
    ]


def page_view():
    body = [nook.chips("view", VIEWS, selected=ui["view"])]
    if ui["error"]:
        body.append(nook.row([nook.icon("warning-circle", size=16, color="red"),
                              nook.text(ui["error"], color="red", wrap=True)], gap=6))
    body += [devices_page, apps_page, settings_page][ui["view"]]()
    return nook.column(body, gap=10, scroll=True, id=VIEWS[ui["view"]])


ACTIONS = [{"id": "mixer", "icon": "sliders-horizontal", "tooltip": "Windows Volume Mixer"},
           {"id": "settings", "icon": "gear", "tooltip": "Windows sound settings"},
           {"id": "refresh", "icon": "arrow-clockwise", "tooltip": "Refresh"}]


def draw(force=False):
    tile = tile_view()
    key_t = json.dumps(tile, sort_keys=True)
    if force or key_t != last_sent["tile"]:
        app.tile(tile)
        last_sent["tile"] = key_t
    page = page_view()
    key_p = json.dumps(page, sort_keys=True)
    if force or key_p != last_sent["page"]:
        app.page(page, ACTIONS)
        last_sent["page"] = key_p


# Actions --------------------------------------------------------------------------

def roles_for(flow):
    return (ca.CONSOLE, ca.MULTIMEDIA) if prefs["keep_calls"][flow] else ca.ROLES


def matching_mic(out_dev):
    """The input on the same hardware as an output (same interface name)."""
    adapter = (out_dev.get("adapter") or "").lower()
    if not adapter:
        return None
    return next((d for d in state["in"] if (d.get("adapter") or "").lower() == adapter), None)


def make_default(flow, device_id):
    try:
        ca.set_default(device_id, roles_for(flow))
        if flow == "out" and prefs["link_mic"]:
            dev = next((d for d in state["out"] if d["id"] == device_id), None)
            mic = dev and matching_mic(dev)
            if mic and not mic["default"]:
                ca.set_default(mic["id"], roles_for("in"))
    except OSError as e:
        ui["error"] = f"Couldn't switch: {e}"
    refresh()
    draw()


def set_calls(flow, target):
    try:
        if target == "same":
            prefs["keep_calls"][flow] = False
            cur = default(state[flow])
            if cur:
                ca.set_default(cur["id"], (ca.COMMUNICATIONS,))
        else:
            prefs["keep_calls"][flow] = True
            ca.set_default(target, (ca.COMMUNICATIONS,))
    except OSError as e:
        ui["error"] = f"Couldn't set the calls device: {e}"
    save_prefs()
    refresh()


def cycle():
    skip = set(prefs["skip"])
    outs = [d for d in state["out"] if d["id"] not in skip] or state["out"]
    if len(outs) < 2:
        return
    ids = [d["id"] for d in outs]
    cur = default(state["out"])
    i = ids.index(cur["id"]) if cur and cur["id"] in ids else -1
    nxt = outs[(i + 1) % len(outs)]
    make_default("out", nxt["id"])
    app.badge_glyph(kind_icon(nxt))   # a moment of feedback on the collapsed pill
    ui["flash_until"] = time.monotonic() + 3


def app_row(flow, key):
    return next((a for a in state[f"apps_{flow}"] if a["key"] == key), None)


@app.on_message("event")
def on_event(e):
    eid, value = e.get("id", ""), e.get("value")
    if eid == "view" and isinstance(value, dict):
        ui["view"] = max(0, min(value.get("index", 0), len(VIEWS) - 1))
        refresh_live()
    elif eid == "refresh":
        refresh()
    elif eid == "settings":
        app.open("ms-settings:sound")
    elif eid == "mixer":
        app.open("ms-settings:apps-volume")
    elif eid.startswith(("out:", "in:")) and ca:
        flow, dev_id = eid.split(":", 1)
        make_default(flow, dev_id)
        return
    elif eid.startswith("calls:") and ca:
        _, flow, target = eid.split(":", 2)
        set_calls(flow, target)
    elif eid.startswith("cyc:"):
        skip = set(prefs["skip"])
        (skip.discard if value else skip.add)(eid[4:])
        prefs["skip"] = sorted(skip)
        save_prefs()
    elif eid == "link_mic":
        prefs["link_mic"] = bool(value)
        save_prefs()
    elif eid.startswith("vol:") and ca and isinstance(value, (int, float)):
        dev = default(state[eid[4:]])
        if dev:
            ca.set_volume(dev["id"], float(value))
            refresh()
    elif eid.startswith("mute:") and ca:
        flow = eid[5:]
        dev, vol = default(state[flow]), state[f"{flow}_vol"]
        if dev and vol:
            ca.set_mute(dev["id"], not vol[1])
            refresh()
    elif eid.startswith(("avol:", "amute:")) and ca:
        kind, flow, key = eid.split(":", 2)
        row, dev = app_row(flow, key), default(state[flow])
        if row and dev:
            try:
                if kind == "avol" and isinstance(value, (int, float)):
                    ca.set_session(dev["id"], row["sids"], level=float(value), muted=False if value else None)
                elif kind == "amute":
                    ca.set_session(dev["id"], row["sids"], muted=not row["muted"])
            except OSError as err:
                ui["error"] = f"Couldn't change {row['name']}: {err}"
            refresh_live()
    draw()


@app.on_message("hotkey")
def on_hotkey(_):
    refresh()
    cycle()


@app.on_message("layout")
def on_layout(_):
    draw(force=True)


@app.on_message("page_open")
def on_page_open(_):
    refresh()
    draw()


def tick():
    if ui["flash_until"] and time.monotonic() > ui["flash_until"]:
        ui["flash_until"] = 0.0
        app.clear_badge()
    refresh()
    draw()


def tick_live():
    if app.page_open:
        refresh_live()
        draw()


if ca:
    ca.init()
refresh()
draw(force=True)
app.every(2, tick)
app.every(0.2, tick_live)
app.run()
