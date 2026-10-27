"""MineLauncher 入口"""
import sys

from launcher.ui import App

if __name__ == "__main__":
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    App().mainloop()
