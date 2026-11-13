# Audio Switch

> Your output device and volume, always in view. Switch speakers,
> headphones and mics with one click, mix per-app volume, and cycle outputs
> with **Ctrl+Alt+A**.

![Platform](https://img.shields.io/badge/platform-Windows-0078D6)
![Python](https://img.shields.io/badge/python-3.8%2B-3776AB)
![Version](https://img.shields.io/badge/version-2.0.0-7C5CFF)
![Plugin for](https://img.shields.io/badge/plugin%20for-Nook%20%2F%20Fenn-111)

A plugin for **Nook**, the floating notch for Windows (and its successor
**Fenn**). It talks to Windows Core Audio directly through `ctypes`, so there
is nothing to install.

| | |
|---|---|
| **Hotkey** | `Ctrl+Alt+A` cycles outputs |
| **Tile** | wide (small and large also supported) |
| **Page** | 620 × 440 |
| **Dependencies** | none |

## Highlights

- **Volume dial tile** showing the current output by its real product name
  ("realme Buds T200 Lite", not "Headphones").
- **One-click switching** for outputs and inputs, with **live level meters**.
- **Per-app volume mixer** for apps that are playing or recording.
- **Separate calls device** for Teams, Zoom and Discord.
- **Hotkey cycling** through just the outputs you pick, optionally taking
  the matching mic along.

## Install

Clone the repo into your plugins folder. The folder name must be `audio-switch`:

```powershell
# Nook
git clone https://github.com/Geguchh024/nook-audio-switch "$env:APPDATA\Nook\plugins\audio-switch"
# Fenn
git clone https://github.com/Geguchh024/nook-audio-switch "$env:APPDATA\Fenn\plugins\audio-switch"
```

You can also download the ZIP and extract it to the same place.

## The tile

The tile shows the default output device (headphones, speakers, a monitor's
HDMI audio…) inside a dial that fills with its volume. It turns orange with
a crossed speaker when muted. Small, wide and large tiles are drawn to the
tile's exact size. The large one also shows the microphone with its level,
and the calls device if it differs.

After each hotkey switch, the collapsed pill shows the new device's icon for a
few seconds.

## The page

Click the tile to open it:

| View | What's there |
|---|---|
| **Devices** | Every active output and input. Click one to make it the default. Each side shows the current device, a volume slider with a mute button, and a **live level meter**. The input meter only moves while an app records. |
| **Apps** | A volume mixer for the apps playing on the current output and the apps recording from the current mic, each with a volume slider, mute and a level meter. An app with several sessions (a browser, say) is one row. |
| **Settings** | See below. |

The header buttons open the Windows Volume Mixer and Sound settings.

### Settings

- **Hotkey outputs:** choose which outputs **Ctrl+Alt+A** steps through, so it
  can skip a monitor you never listen on, for example.
- **Switch the microphone along with the output:** switching to a headset
  also makes its mic the default.
- **Calls device:** a separate speaker and microphone for calls. Calling apps
  (Teams, Zoom, Discord) use Windows' *communications* device. If you set one
  here, switching the default leaves it alone. "Same as default" makes calls
  follow the default again. A calls device set elsewhere (the Sound panel, a
  headset driver) is picked up.

## How it works

Devices, levels and app sessions are read with Core Audio through `ctypes`
(`coreaudio.py`), using `IAudioEndpointVolume`, `IAudioMeterInformation`,
`IAudioSessionManager2` and `ISimpleAudioVolume`. The default device is set
through `IPolicyConfig`, the same interface the Sound control panel uses. App
names come from each exe's file description.

The device list is re-read every two seconds. The meters and the mixer update
five times a second, and only while the page is open. Each view is re-sent
only when it changes, so the plugin stays light when idle.

## Files

| File | What it is |
|---|---|
| `main.py` | Tile, pages, hotkey and settings |
| `coreaudio.py` | Core Audio bindings through `ctypes` (shared with Call Mute) |
| `nook.py` | The Nook plugin helper |
| `plugin.toml` | Plugin manifest |

## Requirements

- Windows 10 or 11
- Python 3.8+ on `PATH` as `python`
