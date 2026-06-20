# ⚡ SingBox GUI Control Panel

A modern Windows desktop GUI for managing the [sing-box](https://github.com/SagerNet/sing-box) proxy engine — no command line required.

![Platform](https://img.shields.io/badge/platform-Windows-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![sing-box](https://img.shields.io/badge/sing--box-v1.13.13-green)
![License](https://img.shields.io/badge/license-MIT-green)

---

## ✨ Features

- **Load configs** — supports both `.json` and `.bpf` profile formats
- **Live server switching** — switch between outbounds instantly via Clash API (no restart needed)
- **Built-in config editor** — view, edit, format, search, and validate JSON directly in the app
- **Real-time logs** — live log viewer with color-coded output
- **TUN mode toggle** — enable/disable TUN with admin detection
- **DNS strategy** — prefer IPv4/IPv6 or force single stack
- **Bandwidth limits** — set upload/download Mbps for Hysteria2 outbounds
- **Mixed proxy port** — configure the local HTTP/SOCKS proxy port
- **Dark / Light / System** theme support
- **Standalone `.exe`** — packaged with PyInstaller, no Python needed on target machine

---

## 📁 Project Structure

```
SingBox-GUI/
├── gui.py            # Main GUI application
├── config.json       # Default sing-box config
├── start.bat         # Launch sing-box via CMD
├── open_gui.bat      # Launch the GUI
└── .gitignore
```

> **Note:** `sing-box.exe` and `libcronet.dll` must be placed in the same folder.  
> Download them from the [sing-box releases page](https://github.com/SagerNet/sing-box/releases).

---

## 🚀 Getting Started

### Option 1 — Run from source

**Requirements:** Python 3.10+

```bash
pip install customtkinter
python gui.py
```

### Option 2 — Standalone executable

1. Download the latest release from [Releases](https://github.com/bareqmaher-arch/SingBox-GUI/releases)
2. Extract the ZIP
3. Place `sing-box.exe` + `libcronet.dll` in the same folder
4. Double-click `SingBox-GUI.exe`

---

## ⚙️ Configuration

The app loads `config.json` from its directory on startup.  
You can also browse for any `.json` or `.bpf` config file at runtime.

### Supported protocols (via sing-box)
`Hysteria2` · `VLESS` · `VMess` · `Shadowsocks` · `WireGuard` · `TUIC` · and more

---

## 🔒 TUN Mode

TUN mode routes **all system traffic** through sing-box.  
It requires running the app as **Administrator**.

Right-click `SingBox-GUI.exe` → **Run as administrator**

---

## 🛠️ Build from Source

```bash
pip install pyinstaller customtkinter
pyinstaller singbox.spec --noconfirm --clean
```

Then copy `sing-box.exe` and `libcronet.dll` into `dist/SingBox-GUI/`.

---

## 📋 Requirements

| Dependency | Version |
|------------|---------|
| Python | 3.10+ |
| customtkinter | 5.x |
| sing-box | 1.12+ |

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.
