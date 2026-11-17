# SPDX-License-Identifier: GPL-3.0-only
"""Blink design tokens and native Tk widgets, shared with the mobile palette."""
import math
import os
import struct
import subprocess
import tkinter as tk
from tkinter import ttk
import zlib

BG = "#080d18"
PANEL = "#131d2c"
INK = "#0b1320"
FIELD = "#1c293b"
STROKE = "#29394e"
FG = "#f2f6ff"
MUTED = "#a6b3ca"
ACCENT = "#93e8d1"
ICE = "#a8c7ff"
VK = "#b8bfff"


def mix(a, b, fraction):
    ac = [int(a[i:i+2], 16) for i in (1, 3, 5)]
    bc = [int(b[i:i+2], 16) for i in (1, 3, 5)]
    return "#" + "".join("{:02x}".format(round(x+(y-x)*fraction)) for x, y in zip(ac, bc))


def reduced_motion():
    if os.environ.get("BLINK_REDUCE_MOTION") == "1":
        return True
    try:
        p = subprocess.run(["/usr/bin/gsettings", "get", "org.gnome.desktop.interface", "enable-animations"], capture_output=True, text=True, timeout=1)
        return p.returncode == 0 and p.stdout.strip() == "false"
    except (OSError, subprocess.TimeoutExpired):
        return False


def rounded_png(fill, stroke, size=52, radius=18):
    def rgb(color):
        return tuple(int(color[i:i+2], 16) for i in (1, 3, 5))
    data = bytearray()
    fill, stroke = rgb(fill), rgb(stroke)
    for y in range(size):
        data.append(0)
        for x in range(size):
            dx = max(radius-x-0.5, 0, x+0.5-(size-radius))
            dy = max(radius-y-0.5, 0, y+0.5-(size-radius))
            distance = math.hypot(dx, dy)
            alpha = max(0, min(1, radius+0.5-distance))
            edge = distance > radius-1.2 or x < 1 or x >= size-1 or y < 1 or y >= size-1
            data.extend((stroke if edge else fill) + (round(alpha*255),))
    def chunk(kind, payload):
        return struct.pack("!I", len(payload)) + kind + payload + struct.pack("!I", zlib.crc32(kind+payload) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!2I5B", size, size, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(bytes(data))) + chunk(b"IEND", b"")


def configure(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=FG, font=("DejaVu Sans", 11))
    for name, background in (("Card", PANEL), ("Hero", INK)):
        style.configure(name+".TFrame", background=background)
        style.configure(name+".TLabel", background=background, foreground=FG)
        style.configure(name+"Muted.TLabel", background=background, foreground=MUTED, font=("DejaVu Sans", 10))
    style.configure("Muted.TLabel", foreground=MUTED, font=("DejaVu Sans", 10))
    style.configure("Status.TLabel", background=INK, font=("DejaVu Sans", 21, "bold"))
    style.configure("TEntry", lightcolor=STROKE, darkcolor=STROKE, relief="flat", borderwidth=1, fieldbackground=FIELD, foreground=FG, insertcolor=FG, bordercolor=STROKE, padding=12)
    style.configure("TCombobox", lightcolor=STROKE, darkcolor=STROKE, arrowcolor=MUTED, borderwidth=1, relief="flat", fieldbackground=FIELD, background=FIELD, foreground=FG, bordercolor=STROKE, padding=12, arrowsize=15)
    style.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", FG)])
    style.configure("TCheckbutton", background=PANEL, foreground=MUTED, font=("DejaVu Sans", 10))
    style.map("TCheckbutton", background=[("active", PANEL)])
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", "#30495b")
    style.configure("Vertical.TScrollbar", background=PANEL, troughcolor=BG, arrowcolor=MUTED, bordercolor=BG, lightcolor=BG, darkcolor=BG)
    root._blink_images = []
    for name, color, foreground in (("Blink", FIELD, FG), ("Connect", ACCENT, BG), ("Turn", VK, BG)):
        images = []
        for fill, border in ((color, STROKE if name == "Blink" else color), (mix(color, FG, .12), ACCENT), (mix(color, FG, .2), ACCENT), (PANEL, STROKE), (color, ACCENT)):
            images.append(tk.PhotoImage(master=root, data=rounded_png(fill, border)))
        root._blink_images.extend(images)
        element = name+".rounded"
        style.element_create(element, "image", images[0], ("disabled", images[3]), ("pressed", images[2]), ("active", images[1]), ("focus", images[4]), border=18, sticky="nsew")
        style.layout(name+".TButton", [(element, {"sticky": "nsew", "children": [("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})])
        style.configure(name+".TButton", background=PANEL if name == "Blink" else INK, borderwidth=0, foreground=foreground, padding=(0, 2), anchor="center", font=("DejaVu Sans", 11, "bold" if name != "Blink" else "normal"))
        style.map(name+".TButton", foreground=[("disabled", MUTED)], background=[("disabled", PANEL if name == "Blink" else INK), ("active", PANEL if name == "Blink" else INK), ("pressed", PANEL if name == "Blink" else INK)])
    return style


class Card(tk.Canvas):
    def __init__(self, master, hero=False, padding=24):
        self.color = INK if hero else PANEL
        super().__init__(master, bg=BG, highlightthickness=0, bd=0, height=1)
        self.padding = padding
        self.body = ttk.Frame(self, style="Hero.TFrame" if hero else "Card.TFrame")
        self.window = self.create_window(padding, padding, window=self.body, anchor="nw")
        self.bind("<Configure>", self.layout)
        self.body.bind("<Configure>", self.layout)

    def layout(self, event=None):
        width = max(1, self.winfo_width())
        self.itemconfigure(self.window, width=max(1, width-self.padding*2))
        height = self.body.winfo_reqheight()+self.padding*2
        if self.winfo_reqheight() != height:
            self.configure(height=height)
        self.delete("surface")
        r = 28
        self.create_polygon(r, 1, width-r, 1, width-1, 1, width-1, r, width-1, height-r, width-1, height-1, width-r, height-1, r, height-1, 1, height-1, 1, height-r, 1, r, 1, 1, fill=self.color, outline=STROKE, smooth=True, splinesteps=24, tags="surface")
        self.tag_lower("surface")


class Orbit(tk.Canvas):
    def __init__(self, master, root, color=ACCENT):
        super().__init__(master, width=232, height=232, bg=INK, bd=0, highlightthickness=0)
        self.root = root
        self.color = color
        self.active = False
        self.busy = False
        self.angle = 0
        self.timer = None
        self.reduce_motion = reduced_motion()
        self.bind("<Destroy>", self.destroyed, add="+")
        root.bind("<Map>", lambda _: self.schedule(), add="+")
        root.bind("<Unmap>", lambda _: self.pause(), add="+")
        self.draw()

    def state(self, active=False, busy=False, color=None):
        changed = (self.active, self.busy, self.color) != (active, busy, color or self.color)
        self.active, self.busy = active, busy
        self.color = color or self.color
        if changed:
            self.draw()
        self.schedule()

    def draw(self):
        self.delete("all")
        for radius in range(111, 59, -3):
            strength = (1-radius/118)*(.3 if self.active else .16)
            c = mix(INK, self.color, strength)
            self.create_oval(116-radius, 116-radius, 116+radius, 116+radius, fill=c, outline=c)
        for inset, strength in ((9, .14), (25, .22), (47, .14)):
            self.create_oval(inset, inset, 232-inset, 232-inset, outline=mix(INK, self.color, strength), width=1)
        extent = 235 if self.busy else 326
        for step in range(55):
            self.create_arc(25, 25, 207, 207, start=self.angle+step*extent/55, extent=extent/55+1, style="arc", outline=mix(INK, self.color, .15+.85*step/55), width=3)
        self.create_arc(9, 9, 223, 223, start=30-self.angle*.6, extent=106, style="arc", outline=mix(INK, self.color, .35), width=1)
        self.create_arc(91, 92, 141, 144, start=128, extent=284, style="arc", outline=self.color, width=3)
        self.create_line(116, 80, 116, 113, fill=self.color, width=3, capstyle="round")

    def schedule(self):
        if self.busy and not self.reduce_motion and self.root.winfo_ismapped() and self.timer is None:
            self.timer = self.after(50, self.animate)
        elif not self.busy or self.reduce_motion:
            self.pause()

    def animate(self):
        self.timer = None
        if self.busy and not self.reduce_motion and self.root.winfo_ismapped():
            self.angle = (self.angle-5) % 360
            self.draw()
            self.schedule()

    def pause(self):
        if self.timer:
            self.after_cancel(self.timer)
            self.timer = None

    def destroyed(self, event):
        if event.widget is self:
            self.pause()
