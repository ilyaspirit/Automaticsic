<p align="center">
  <img src="icon.png" width="120" alt="Automaticsic">
</p>

<h1 align="center">Automaticsic</h1>

<p align="center">
  Step-based scripts for Windows: start programs, arrange windows, press hotkeys.<br>
  Double-click a file and your workspace assembles itself.
</p>

<p align="center"><a href="README.md">Русский</a> · <b>English</b></p>

---

## What it is

A tool for the repetitive things you got tired of doing by hand. You describe a sequence of steps in the editor and save it as an `.asic` file — from then on a double-click runs the whole chain and quits. Right-click → «Edit» opens the editor.

A typical script: in the morning open the browser on the right page, bring up mail, hide the messenger to the tray, maximise the editor. Or the other way round — close it all in the evening.

The program is made for personal use, with no ambition of wide distribution. The sources are open — take it and bend it to your needs.

The interface is in Russian.

## Features

**Ten kinds of step**

| Step | What it does |
|---|---|
| Start a program | Runs an exe, a shortcut or an address such as `steam://`, with arguments; can switch to an already open window |
| Close a program | Gently through `WM_CLOSE`, by quitting as if Windows were shutting down, or by force; can close child processes |
| Command line | Runs a cmd or PowerShell command — in a shell window or without one, checking the exit code |
| Window action | Maximise, restore, bring to front, move to another monitor, minimise to the taskbar or to the tray, show |
| Hotkey | Sends a key combination globally or to a specific window |
| Primary monitor | Makes the chosen screen the primary one |
| Desktop wallpaper | Sets an image with a fit mode or fills the desktop with a solid colour; can remember the previous one and put it back |
| Pause | A delay in milliseconds |
| Copy a file | From one place to another, creating the destination folder |
| Stream Deck brightness | Changes the Stream Deck backlight, from 0 to 100% |

**What it can do beyond that**

- **Command line.** The step works in two modes. *In a shell window* — a window opens and stays on screen while the script moves on: that is how you look at `ipconfig` or hold an ssh tunnel that outlives the finished script. *Without a shell* — no window; with «wait for completion» ticked the script waits for the command to end, and then a non-zero exit code fails the step and puts the output in the log: that is how you map a network drive or sync a folder and actually know whether it worked. Multi-line commands work as written, nothing needs escaping.

- **Quit as if Windows were shutting down.** A separate way to close the programs that ignore the close button. A program is free to intercept that button and hide in the tray — but it cannot hide from a system shutdown: it has to quit and clean up after itself. That is how you close, for example, a VPN client whose tunnel must be brought down properly. It never kills anything: if the program does not quit, the step fails. Child processes get the same request rather than a kill.

- **Minimise to tray, two ways.** You cannot create a tray icon on another program's behalf, so the choice is yours. *Press the close button* — a request to the program itself: Telegram, INCY and everything else that knows how to hide in the tray will hide, and a click on their icon brings the window back. *Hide the window through Windows* — the window goes away behind the program's back, and only the «Show a hidden window» step can bring it out.

- **Wallpaper there and back.** The «remember the previous wallpaper» tick records what was on the desktop before the change — the file, the fit mode and the background colour. The «restore the remembered one» mode puts it back. What is remembered lives in the program's settings rather than in the script, so one script can remember and a different one restore — even after a reboot.

- **Aliases.** A start step gives the program a nickname; later steps refer to it and land on exactly the window that was started — even with five Chrome windows open.

- **Arguments and shortcuts.** A chosen shortcut is split in two: the path to the program and its arguments, both visible and editable.

- **Steam shortcuts and other addresses.** An internet shortcut `.url` — with an address like `steam://rungameid/227300` inside — is launched exactly as a double-click would; the address can also be typed by hand. Steam, not the step, starts the game, so the step has no process of its own, and everything that depends on a window does not apply to such shortcuts.

- **Running as administrator.** The built program asks for elevation right at startup: Windows will not let you control windows and processes running above you. From sources the editor starts unelevated; you can raise it through **Settings → Restart as administrator**.

- **Start minimised or maximised.** The wish passed at launch is ignored by most programs, so the window is pushed into the requested state after it appears.

- **Choosing a monitor.** The «Monitor» field exists on the start step and on window actions: the standalone «move to monitor» action only moves the window, while for «maximise», «restore» and «bring to front» the monitor works as an addition — «maximise» + «monitor 2» maximises on the second screen in a single step. The window travels the same way it does with `Win+Shift+arrow`: the size is kept, the position is carried over proportionally. Screens are numbered left to right, with «Primary» as a separate entry. The «Identify» button next to the list flashes the number on each monitor for a couple of seconds.

- **Step icons.** Each step is prefixed with the icon of the program it works with — the same one Explorer shows. The path that was found is remembered, so the icon is there even when the program is closed. Steps without a program get a system icon. The progress window shows the same icon.

- **The form promises nothing it will not do.** Some settings do not apply in some modes — there is no point waiting for a window when there is nothing to wait for. Such tick boxes and lists do not merely grey out: they show what is actually going to happen. Your own choice is kept and comes back together with the mode.

- **Recording key combinations.** A field where you press the combination you want and it gets recorded rather than triggered. System ones are caught too — `Alt+F4`, `Win+D`.

- **Steps through the clipboard.** `Ctrl+C` / `Ctrl+V` move a step between editor windows and even to another machine: readable JSON goes into the clipboard. `Ctrl+D` duplicates a step, `Del` deletes it.

- **Stream Deck without Elgato's software.** The device is an ordinary HID; brightness is set with a single feature report. We talk to it through the system's own `hid.dll` and `cfgmgr32.dll`, with no third-party libraries and no official software. Original, Mini, XL, MK.2, Plus and Neo are supported.

- **Progress window.** Double-clicking an `.asic` puts an icon in the tray and a small window above it with the current step and a progress bar. It never takes focus, so it does not get in the script's way. The «Stop» button is there as well as in the editor.

- **Tolerance for other people's files.** A step of an unknown type does not break loading: it is switched off but saved back to the file unchanged.

## Installation

You need Python 3.12 (64-bit) and [uv](https://github.com/astral-sh/uv).

```
uv sync
```

Running from sources:

```
uv run main.py                       empty editor
uv run main.py --edit script.asic    open in the editor
uv run main.py script.asic           run and quit
```

## Building

```
uv run pyinstaller --noconfirm Automaticsic.spec
```

The resulting `dist\Automaticsic.exe` is self-contained. The version and the icons come from the project: the number from `model.VERSION`, the pictures from `icon.ico` for the program itself and `icon_asic.ico` for script files. Both icons go inside the exe, no separate files are needed next to it.

For debugging, build with a console, otherwise tracebacks go nowhere:

```
uv run pyinstaller --noconfirm --console Automaticsic.spec
```

Close the running exe before rebuilding.

## Associating .asic files

From the built program: **Settings → Reinstall the association**. Or by hand:

```
uv run install.py              install
uv run install.py --uninstall  remove
```

Everything is written to `HKEY_CURRENT_USER\Software\Classes`, no administrator rights required. The association holds on to a specific path to the exe: reinstall it after moving. **Settings → Check the .asic association** shows what is currently registered.

## The .asic format

Plain JSON, editable by hand if you like.

```json
{
  "name": "Workspace",
  "autopause_ms": 200,
  "alias_exe": { "np": "C:\\Windows\\System32\\notepad.exe" },
  "steps": [
    {
      "id": "a1b2c3d4",
      "type": "launch",
      "enabled": true,
      "ignore_error": true,
      "comment": "open notepad",
      "params": {
        "path": "C:\\Windows\\System32\\notepad.exe",
        "args": "",
        "show": "normal",
        "if_running": "skip",
        "wait_window": true,
        "wait_timeout_ms": 3000,
        "alias": "np"
      }
    }
  ]
}
```

| Step field | Meaning |
|---|---|
| `id` | Eight characters, generated automatically |
| `type` | `launch`, `close`, `command`, `window`, `pause`, `copy`, `hotkey`, `wallpaper`, `streamdeck`, `primary_monitor` |
| `enabled` | A disabled step is skipped but stays in the file |
| `ignore_error` | The error is written to the log and execution continues |
| `comment` | A note, appended to the step's title in the list |
| `params` | Parameters, different for every type |

Missing parameters are filled in with defaults, so old files do not break when new fields appear. Outdated values are migrated on load.

## How it is built

The core — `model`, `actions`, `runner`, `winapi`, `streamdeck` — knows nothing about Qt: it holds the step model, the action handlers and the work with the Windows API. The interface lives separately: `editor`, `ui_props`, `ui_progress`, `ui_widgets`, `ui_style`.

A new step is a function plus a line in `actions.HANDLERS` plus a method in `ui_props`. Step types live in groups in `model.STEP_GROUPS`, which is where both the menu and the list of types come from. The version number lives in `model.VERSION` and the build reads it from there.

## Stack

Python 3.12, PySide6, psutil, pywin32. Built with PyInstaller, packages with uv.

---

<p align="center"><a href="https://github.com/ilyaspirit">@ilyaspirit</a></p>
