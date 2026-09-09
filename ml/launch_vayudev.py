"""
VayuDev - launch_vayudev.py
============================
One-click launcher: starts the inference server (which now also serves the
dashboard AND handles "Connect UAV" flight selection via the browser - see
inference.py's /api/datasets and /api/connect_uav). This launcher's only
job is: start the server, open the browser once it's ready, and keep the
process alive. Everything else (picking a flight, starting the stream) now
happens by clicking in the browser - no terminal interaction needed.

Build a standalone VayuDev.exe (run once, on Windows, in this folder):

    pip install pyinstaller
    pyinstaller --onefile --name VayuDev ^
      --add-data "vayudev_dashboard.html;." ^
      --add-data "cert.pem;." --add-data "key.pem;." ^
      --add-data "vayu_xgboost_model.pkl;." ^
      launch_vayudev.py

The resulting dist\\VayuDev.exe is fully self-contained. To hand it to a
teammate, they need only: VayuDev.exe + one dataset_2_*.csv file sitting
in the same folder. Nothing else - no Python required on their machine.
Closing the console window (or Ctrl+C) stops the whole app.
"""

import os
import sys
import threading
import time
import webbrowser
import ssl
import urllib.request

import uvicorn

# When frozen by PyInstaller, data files land next to the exe; when run as
# a plain script, they're next to this file. Handle both.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
    RESOURCE_DIR = getattr(sys, "_MEIPASS", BASE_DIR)  # bundled --add-data files
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    RESOURCE_DIR = BASE_DIR

os.chdir(BASE_DIR)  # so relative paths (dataset CSVs) resolve correctly

# Bundled resource files (model/cert/html) may live in RESOURCE_DIR (frozen)
# rather than BASE_DIR - copy them alongside if the plain files aren't
# already sitting next to the exe.
for fname in ("vayudev_dashboard.html", "cert.pem", "key.pem", "vayu_xgboost_model.pkl"):
    src = os.path.join(RESOURCE_DIR, fname)
    dst = os.path.join(BASE_DIR, fname)
    if os.path.exists(src) and not os.path.exists(dst):
        import shutil
        shutil.copy(src, dst)

import inference  # noqa: E402  (loads the model, defines `app`)


def wait_for_server_then_open_browser(timeout=25):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen("https://localhost:8000/health", context=ctx, timeout=2)
            print("Server is up - opening dashboard...")
            webbrowser.open("https://localhost:8000/")
            return
        except Exception:
            time.sleep(0.5)
    print("Server did not start in time - open https://localhost:8000/ manually once it does.")


def main():
    print("=" * 60)
    print(" VAYUDEV - Digital Twin Engine Health Monitor")
    print("=" * 60)
    print("\nStarting server... dashboard will open automatically in your browser.")
    print("(First time only: your browser may warn the certificate isn't trusted")
    print(" - expected for a local self-signed cert. Click through to continue.)")
    print("\nClose this window to stop VayuDev.\n")

    threading.Thread(target=wait_for_server_then_open_browser, daemon=True).start()

    has_cert = os.path.exists("cert.pem") and os.path.exists("key.pem")
    config = uvicorn.Config(
        inference.app, host="0.0.0.0", port=8000, log_level="info",
        ssl_certfile="cert.pem" if has_cert else None,
        ssl_keyfile="key.pem" if has_cert else None,
    )
    uvicorn.Server(config).run()  # blocks - this IS the running app now


if __name__ == "__main__":
    main()


