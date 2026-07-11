import ctypes
import tkinter as tk

from PIL import Image, ImageTk

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except (AttributeError, OSError):
    ctypes.windll.user32.SetProcessDPIAware()

root = tk.Tk()
root.overrideredirect(True)
root.geometry("+0+0")
root.attributes("-topmost", True)

img = Image.open("tests/fixture_hire_screen.png")
photo = ImageTk.PhotoImage(img)
root.geometry(f"{img.width}x{img.height}+0+0")

label = tk.Label(root, image=photo, borderwidth=0)
label.pack()

root.mainloop()
