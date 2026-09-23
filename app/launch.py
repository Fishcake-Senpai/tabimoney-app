from __future__ import annotations

import threading
import webbrowser

import uvicorn


def open_browser() -> None:
    webbrowser.open("http://127.0.0.1:8765", new=2)


def main() -> None:
    browser_timer = threading.Timer(1.25, open_browser)
    browser_timer.daemon = True
    browser_timer.start()
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8765,
        workers=1,
        reload=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()
