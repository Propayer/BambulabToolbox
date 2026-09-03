from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()

    import tkinter as tk
    from PIL import Image, ImageTk

    root = tk.Tk()
    root.title("Jarvis · Optimización generacional")
    root.configure(bg="#111820")
    label = tk.Label(root, bg="#111820")
    label.pack(fill="both", expand=True)
    root.geometry("1100x720")
    last_stamp = None
    photo = None

    def refresh() -> None:
        nonlocal last_stamp, photo
        try:
            stamp = args.image.stat().st_mtime_ns
            if stamp != last_stamp:
                with Image.open(args.image) as opened:
                    image = opened.convert("RGB")
                photo = ImageTk.PhotoImage(image)
                label.configure(image=photo)
                last_stamp = stamp
            if args.state.exists():
                state = json.loads(args.state.read_text(encoding="utf-8"))
                if state.get("finished"):
                    root.title("Jarvis · Optimización terminada")
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            pass
        root.after(350, refresh)

    refresh()
    root.mainloop()


if __name__ == "__main__":
    main()
