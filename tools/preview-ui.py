#!/usr/bin/env python3
"""Capture the actual desktop window under Xvfb with synthetic profile labels."""
from pathlib import Path
import subprocess
import sys
import time
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gui"))
import blink_gui
root = blink_gui.tk.Tk()
with mock.patch.object(blink_gui.Blink, "load_profiles"):
    app = blink_gui.Blink(root)
app.profiles = [{"id": "demo", "name": "Нидерланды · Amsterdam", "kind": "xray"}, {"id": "turn", "name": "VK TURN · Основной", "kind": "vk"}]
app.filter_profiles()
app.notice.set("Ваши серверы всегда под рукой. Добавляйте профили, обновляйте подписки и выбирайте свой маршрут.")
mode = sys.argv[1] if len(sys.argv)>1 else "wide"
if mode == "narrow":
    root.geometry("600x850+0+0")
else:
    root.geometry("1120x940+0+0")
for _ in range(20):
    root.update()
    time.sleep(.025)
filename = Path(__file__).resolve().parents[1] / "work" / ("blink-ui-" + mode + ".png")
subprocess.run(["scrot", "-o", "-a", "{},{},{},{}".format(root.winfo_rootx(),root.winfo_rooty(),root.winfo_width(),root.winfo_height()), str(filename)], check=True)
root.destroy()
print(filename)
