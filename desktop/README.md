# Desktop pet

The desktop client replaces the browser-injected panel with an Electron pet,
chat window and full dashboard. The Python agent remains responsible for all
automation.

## Run

```powershell
python -m pip install -e .
cd desktop
npm install
npm start
```

After installation, the project CLI can also launch it:

```powershell
browser-agent desktop
```

The Electron main process starts the Python API on a random `127.0.0.1` port
with a one-time bearer token. API keys entered in the dashboard are encrypted
with Electron `safeStorage`; they are not stored in renderer local storage.
