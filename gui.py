#!/usr/bin/env python3
"""Sing-Box GUI Control Panel"""

import customtkinter as ctk
import subprocess, threading, json, os, gzip, queue, time, copy
import urllib.request, urllib.error, urllib.parse
from tkinter import filedialog, messagebox
from pathlib import Path
import ctypes, sys

# ─────────────────────────────────────────────
# Works both as script and as PyInstaller bundle
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

SINGBOX_EXE  = BASE_DIR / "sing-box.exe"
DEFAULT_CFG  = BASE_DIR / "config.json"
RUNTIME_CFG  = BASE_DIR / "_runtime_config.json"
# ─────────────────────────────────────────────

def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def decode_bpf(path: Path) -> dict:
    data = path.read_bytes()
    decompressed = gzip.decompress(data[2:])
    # Find JSON start in raw bytes (skip non-UTF-8 header)
    json_start = decompressed.index(b"{")
    return json.loads(decompressed[json_start:].decode("utf-8"))

def load_config_file(path: str) -> dict:
    p = Path(path)
    if p.suffix.lower() == ".bpf":
        return decode_bpf(p)
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def get_selectors(cfg: dict) -> dict:
    return {
        o["tag"]: o.get("outbounds", [])
        for o in cfg.get("outbounds", [])
        if o.get("type") == "selector"
    }

def clash_switch(tag: str, choice: str, port: int) -> bool:
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/proxies/{tag}",
            data=json.dumps({"name": choice}).encode(),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        urllib.request.urlopen(req, timeout=2)
        return True
    except Exception:
        return False

def color_for(line: str) -> str:
    u = line.upper()
    if "FATAL" in u or "ERROR" in u:  return "err"
    if "WARN"  in u:                  return "warn"
    if "INFO"  in u:                  return "info"
    if "[GUI]" in line:               return "gui"
    return "plain"


# ══════════════════════════════════════════════════════════
class App(ctk.CTk):

    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Sing-Box Control Panel  •  v1.13.13")
        self.geometry("1060x720")
        self.minsize(840, 560)

        self._proc:     subprocess.Popen | None = None
        self._running   = False
        self._cfg:      dict = {}
        self._cfg_path  = ""
        self._q:        queue.Queue = queue.Queue()
        self._sel_vars: dict[str, ctk.StringVar] = {}

        self._build()
        self._tick()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if DEFAULT_CFG.exists():
            self._do_load(str(DEFAULT_CFG))

    # ──────────────────────────────────────────────────────
    # UI Build
    # ──────────────────────────────────────────────────────
    def _build(self):
        # ── Header ────────────────────────────────────────
        hdr = ctk.CTkFrame(self, height=56, corner_radius=0,
                           fg_color=("#1a1a2e","#0d1117"))
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(hdr, text="⚡  Sing-Box Control Panel",
                     font=ctk.CTkFont("Segoe UI", 17, "bold")
                     ).pack(side="left", padx=20)

        # Admin badge
        adm_color = "#44aa44" if is_admin() else "#cc4444"
        adm_text  = "🔓 Admin" if is_admin() else "🔒 No Admin"
        self._adm_lbl = ctk.CTkLabel(hdr, text=adm_text,
                                     text_color=adm_color,
                                     font=ctk.CTkFont("Segoe UI", 11))
        self._adm_lbl.pack(side="right", padx=8)

        # Status badge
        badge = ctk.CTkFrame(hdr, corner_radius=14,
                             fg_color=("#2b2b3b","#161b22"))
        badge.pack(side="right", padx=(0, 6), pady=10)

        self._dot = ctk.CTkLabel(badge, text="●", text_color="#ff4444",
                                 font=ctk.CTkFont(size=15))
        self._dot.pack(side="left", padx=(10, 4), pady=6)
        self._status_lbl = ctk.CTkLabel(badge, text="Stopped",
                                        font=ctk.CTkFont("Segoe UI", 12))
        self._status_lbl.pack(side="left", padx=(0, 14), pady=6)

        # ── Body ──────────────────────────────────────────
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=10, pady=6)

        # Sidebar (scrollable)
        self._sb = ctk.CTkScrollableFrame(body, width=275,
                                          fg_color=("#ebebf0","#1c1c2e"),
                                          label_text="")
        self._sb.pack(side="left", fill="y", padx=(0, 6))

        # Log area
        rp = ctk.CTkFrame(body)
        rp.pack(side="right", fill="both", expand=True)

        ctk.CTkLabel(rp, text="Live Logs",
                     font=ctk.CTkFont("Segoe UI", 13, "bold")
                     ).pack(anchor="w", padx=12, pady=(10, 3))

        self._logbox = ctk.CTkTextbox(rp,
                                      font=ctk.CTkFont("Consolas", 11),
                                      wrap="word", state="disabled")
        self._logbox.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        # ── Footer ────────────────────────────────────────
        ftr = ctk.CTkFrame(self, height=65, corner_radius=0)
        ftr.pack(fill="x", side="bottom")
        ftr.pack_propagate(False)

        self._btn_start = ctk.CTkButton(
            ftr, text="▶  Start", width=145, height=42,
            fg_color="#1a7a1a", hover_color="#228b22",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.start)
        self._btn_start.pack(side="left", padx=(18, 6), pady=11)

        self._btn_stop = ctk.CTkButton(
            ftr, text="■  Stop", width=145, height=42,
            fg_color="#7a1a1a", hover_color="#8b0000",
            font=ctk.CTkFont(size=13, weight="bold"),
            state="disabled", command=self.stop)
        self._btn_stop.pack(side="left", padx=6, pady=11)

        self._btn_restart = ctk.CTkButton(
            ftr, text="↺  Restart", width=145, height=42,
            fg_color="#444", hover_color="#555",
            font=ctk.CTkFont(size=13, weight="bold"),
            state="disabled", command=self.restart)
        self._btn_restart.pack(side="left", padx=6, pady=11)

        ctk.CTkButton(
            ftr, text="🗑 Clear Logs", width=120, height=42,
            fg_color="transparent", border_width=1,
            font=ctk.CTkFont(size=12),
            command=self._clear).pack(side="right", padx=(6, 14), pady=11)

        ctk.CTkButton(
            ftr, text="💾 Save Config", width=120, height=42,
            fg_color="transparent", border_width=1,
            font=ctk.CTkFont(size=12),
            command=self._save_cfg).pack(side="right", padx=4, pady=11)

        ctk.CTkButton(
            ftr, text="📝 Edit Config", width=130, height=42,
            fg_color="#1a4a7a", hover_color="#1e5c99",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._open_editor).pack(side="right", padx=4, pady=11)

        self._build_sidebar()

    # ──────────────────────────────────────────────────────
    def _section(self, text: str):
        ctk.CTkLabel(self._sb, text=text,
                     font=ctk.CTkFont("Segoe UI", 12, "bold"),
                     anchor="w").pack(fill="x", padx=8, pady=(16, 3))
        ctk.CTkFrame(self._sb, height=1,
                     fg_color="gray40").pack(fill="x", padx=8, pady=(0, 6))

    def _build_sidebar(self):
        sb = self._sb

        # ── Config File ───────────────────────────────────
        self._section("📁  Config File")

        row = ctk.CTkFrame(sb, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=(0, 4))

        self._cfg_lbl = ctk.CTkLabel(
            row, text="No file loaded", anchor="w",
            font=ctk.CTkFont(size=11), text_color="gray60",
            wraplength=170)
        self._cfg_lbl.pack(side="left", fill="x", expand=True)

        ctk.CTkButton(row, text="Browse…", width=76, height=28,
                      command=self._browse).pack(side="right")

        self._cfg_ok = ctk.CTkLabel(
            sb, text="", font=ctk.CTkFont(size=11), text_color="#44cc44")
        self._cfg_ok.pack(anchor="w", padx=8)

        # ── Server Selection ──────────────────────────────
        self._section("🔌  Server Selection")
        self._sel_box = ctk.CTkFrame(sb, fg_color="transparent")
        self._sel_box.pack(fill="x", padx=8)

        self._no_sel = ctk.CTkLabel(
            self._sel_box, text="Load a config to see servers",
            text_color="gray55", font=ctk.CTkFont(size=11))
        self._no_sel.pack(pady=4)

        # ── DNS Strategy ──────────────────────────────────
        self._section("🌐  DNS Strategy")
        self._dns_var = ctk.StringVar(value="prefer_ipv4")
        ctk.CTkOptionMenu(
            sb,
            values=["prefer_ipv4","prefer_ipv6","ipv4_only","ipv6_only"],
            variable=self._dns_var,
            command=lambda v: self._cfg.get("dns",{}).update({"strategy": v})
        ).pack(fill="x", padx=8)

        # ── Mixed Proxy Port ──────────────────────────────
        self._section("🔗  Mixed Proxy Port")
        prow = ctk.CTkFrame(sb, fg_color="transparent")
        prow.pack(fill="x", padx=8)
        ctk.CTkLabel(prow, text="127.0.0.1 :",
                     font=ctk.CTkFont(size=12)).pack(side="left")
        self._port_var = ctk.StringVar(value="2080")
        ctk.CTkEntry(prow, textvariable=self._port_var,
                     width=75).pack(side="right")

        # ── Log Level ─────────────────────────────────────
        self._section("📊  Log Level")
        self._lvl_var = ctk.StringVar(value="info")
        ctk.CTkOptionMenu(
            sb, values=["trace","debug","info","warn","error"],
            variable=self._lvl_var,
            command=lambda v: self._cfg.setdefault("log",{}).update({"level": v})
        ).pack(fill="x", padx=8)

        # ── TUN Mode ──────────────────────────────────────
        self._section("🔒  TUN Mode")
        self._tun_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(
            sb, text="Enable TUN  (requires Admin)",
            variable=self._tun_var,
            font=ctk.CTkFont(size=11),
            command=self._toggle_tun
        ).pack(anchor="w", padx=8)
        ctk.CTkLabel(
            sb, text="Routes ALL traffic through sing-box",
            text_color="gray55", font=ctk.CTkFont(size=10)
        ).pack(anchor="w", padx=8, pady=(2, 0))

        # ── Bandwidth ─────────────────────────────────────
        self._section("⚡  Bandwidth Limits (Mbps)")
        brow = ctk.CTkFrame(sb, fg_color="transparent")
        brow.pack(fill="x", padx=8)

        ctk.CTkLabel(brow, text="↑ Up:",
                     font=ctk.CTkFont(size=12), width=48).pack(side="left")
        self._up_var = ctk.StringVar(value="200")
        ctk.CTkEntry(brow, textvariable=self._up_var,
                     width=62).pack(side="left", padx=(0,10))

        ctk.CTkLabel(brow, text="↓ Down:",
                     font=ctk.CTkFont(size=12), width=56).pack(side="left")
        self._dn_var = ctk.StringVar(value="200")
        ctk.CTkEntry(brow, textvariable=self._dn_var,
                     width=62).pack(side="left")

        ctk.CTkButton(
            sb, text="Apply Bandwidth", height=30,
            command=self._apply_bw
        ).pack(fill="x", padx=8, pady=(8, 0))

        # ── Clash API Port ────────────────────────────────
        self._section("⚙️  Clash API Port")
        self._api_var = ctk.StringVar(value="9090")
        ctk.CTkEntry(sb, textvariable=self._api_var,
                     width=80).pack(anchor="w", padx=8)
        ctk.CTkLabel(
            sb, text="Enables live server switching",
            text_color="gray55", font=ctk.CTkFont(size=10)
        ).pack(anchor="w", padx=8, pady=(2, 0))

        # ── Appearance ────────────────────────────────────
        self._section("🎨  Appearance")
        self._theme_var = ctk.StringVar(value="Dark")
        ctk.CTkSegmentedButton(
            sb, values=["Light","Dark","System"],
            variable=self._theme_var,
            command=ctk.set_appearance_mode
        ).pack(fill="x", padx=8, pady=(0, 12))

    # ──────────────────────────────────────────────────────
    # Config
    # ──────────────────────────────────────────────────────
    def _browse(self):
        p = filedialog.askopenfilename(
            title="Select Config File",
            filetypes=[
                ("Sing-Box Config","*.json *.bpf"),
                ("JSON","*.json"),
                ("BPF Profile","*.bpf"),
                ("All","*.*"),
            ]
        )
        if p:
            self._do_load(p)

    def _do_load(self, path: str):
        try:
            self._cfg      = load_config_file(path)
            self._cfg_path = path
            self._cfg_lbl.configure(
                text=os.path.basename(path), text_color="white")
            self._cfg_ok.configure(
                text="✓  Config loaded successfully", text_color="#44cc44")
            self._sync_from_cfg()
            self._rebuild_selectors()
            self._log(f"[GUI] Config loaded: {os.path.basename(path)}")
        except Exception as e:
            self._cfg_ok.configure(
                text=f"✗  {str(e)[:50]}", text_color="#ff5555")
            messagebox.showerror("Load Error", str(e))

    def _sync_from_cfg(self):
        dns = self._cfg.get("dns", {})
        self._dns_var.set(dns.get("strategy", "prefer_ipv4"))
        self._lvl_var.set(self._cfg.get("log", {}).get("level", "info"))

        for ib in self._cfg.get("inbounds", []):
            if ib.get("type") == "mixed":
                self._port_var.set(str(ib.get("listen_port", 2080)))
                break

        has_tun = any(
            i.get("type") == "tun"
            for i in self._cfg.get("inbounds", [])
        )
        if has_tun and not is_admin():
            # Remove TUN from config data AND from UI
            self._cfg["inbounds"] = [
                i for i in self._cfg.get("inbounds", [])
                if i.get("type") != "tun"
            ]
            self._tun_var.set(False)
            self._log("[GUI] ⚠ TUN disabled (not Admin) — running as Mixed proxy only")
        else:
            self._tun_var.set(has_tun)

        for ob in self._cfg.get("outbounds", []):
            if ob.get("type") == "hysteria2":
                self._up_var.set(str(ob.get("up_mbps", 200)))
                self._dn_var.set(str(ob.get("down_mbps", 200)))
                break

    def _rebuild_selectors(self):
        for w in self._sel_box.winfo_children():
            w.destroy()
        self._sel_vars.clear()

        sels = get_selectors(self._cfg)
        if not sels:
            ctk.CTkLabel(
                self._sel_box,
                text="No selector outbounds in config",
                text_color="gray55", font=ctk.CTkFont(size=11)
            ).pack(pady=6)
            return

        for tag, choices in sels.items():
            row = ctk.CTkFrame(self._sel_box, fg_color="transparent")
            row.pack(fill="x", pady=3)

            ctk.CTkLabel(
                row, text=f"{tag}:", width=65, anchor="w",
                font=ctk.CTkFont(size=11)
            ).pack(side="left")

            var = ctk.StringVar(value=choices[0] if choices else "")
            self._sel_vars[tag] = var

            ctk.CTkOptionMenu(
                row, values=choices, variable=var,
                command=lambda c, t=tag: self._on_server_change(t, c)
            ).pack(side="right", fill="x", expand=True, padx=(4, 0))

    # ──────────────────────────────────────────────────────
    # Event handlers
    # ──────────────────────────────────────────────────────
    def _on_server_change(self, tag: str, choice: str):
        if not self._running:
            self._log(f"[GUI] '{tag}' will be '{choice}' on next start")
            return
        try:
            port = int(self._api_var.get())
        except ValueError:
            port = 9090
        ok = clash_switch(tag, choice, port)
        if ok:
            self._log(f"[GUI] ✓ Switched '{tag}' → '{choice}'")
        else:
            self._log(f"[GUI] ✗ Clash API unavailable — restart to apply")

    def _toggle_tun(self):
        ibs  = self._cfg.get("inbounds", [])
        has  = any(i.get("type") == "tun" for i in ibs)
        want = self._tun_var.get()

        if want and not has:
            if not is_admin():
                messagebox.showwarning(
                    "Admin Required",
                    "TUN mode requires running as Administrator.\n"
                    "Right-click the app and choose 'Run as administrator'."
                )
                self._tun_var.set(False)
                return
            ibs.append({
                "type": "tun", "tag": "tun-in",
                "address": "172.19.0.1/30",
                "auto_route": True, "strict_route": True,
                "stack": "gvisor"
            })
            self._cfg["inbounds"] = ibs
            self._log("[GUI] TUN mode enabled")

        elif not want and has:
            self._cfg["inbounds"] = [
                i for i in ibs if i.get("type") != "tun"
            ]
            self._log("[GUI] TUN mode disabled")

    def _apply_bw(self):
        try:
            up = int(self._up_var.get())
            dn = int(self._dn_var.get())
        except ValueError:
            messagebox.showerror("Error", "Bandwidth must be a number")
            return
        count = 0
        for ob in self._cfg.get("outbounds", []):
            if ob.get("type") == "hysteria2":
                ob["up_mbps"]   = up
                ob["down_mbps"] = dn
                count += 1
        self._log(f"[GUI] Bandwidth applied to {count} outbound(s): ↑{up} ↓{dn} Mbps")
        if self._running:
            self._log("[GUI] Restart to apply bandwidth changes")

    def _save_cfg(self):
        self._apply_ui_to_cfg()
        path = filedialog.asksaveasfilename(
            title="Save Config",
            defaultextension=".json",
            filetypes=[("JSON","*.json"),("All","*.*")],
            initialfile="config.json",
            initialdir=str(BASE_DIR)
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._cfg, f, indent=2, ensure_ascii=False)
        self._log(f"[GUI] Config saved to: {os.path.basename(path)}")

    def _apply_ui_to_cfg(self):
        try:
            port = int(self._port_var.get())
            for ib in self._cfg.get("inbounds", []):
                if ib.get("type") == "mixed":
                    ib["listen_port"] = port
        except ValueError:
            pass
        self._cfg.setdefault("log", {})["level"]     = self._lvl_var.get()
        self._cfg.setdefault("dns", {})["strategy"]  = self._dns_var.get()

    # ──────────────────────────────────────────────────────
    # Process management
    # ──────────────────────────────────────────────────────
    def _make_runtime_cfg(self) -> dict:
        cfg = copy.deepcopy(self._cfg)

        # Port
        try:
            port = int(self._port_var.get())
        except ValueError:
            port = 2080
        for ib in cfg.get("inbounds", []):
            if ib.get("type") == "mixed":
                ib["listen_port"] = port

        # Log level
        cfg.setdefault("log", {})["level"] = self._lvl_var.get()

        # Inject Clash API
        try:
            api_port = int(self._api_var.get())
        except ValueError:
            api_port = 9090
        cfg.setdefault("experimental", {})["clash_api"] = {
            "external_controller": f"127.0.0.1:{api_port}",
            "secret": ""
        }

        # Apply selector choices
        for tag, var in self._sel_vars.items():
            for ob in cfg.get("outbounds", []):
                if ob.get("type") == "selector" and ob.get("tag") == tag:
                    ob["default"] = var.get()

        return cfg

    def start(self):
        self._log("[GUI] ── Start button pressed ──")
        try:
            if self._running:
                self._log("[GUI] Already running, ignoring.")
                return

            if not self._cfg:
                self._log("[GUI] ✗ No config loaded!")
                messagebox.showwarning("No Config", "Please load a config file first.")
                return

            # Always strip TUN if not admin before starting
            if not is_admin():
                has_tun = any(
                    i.get("type") == "tun"
                    for i in self._cfg.get("inbounds", [])
                )
                if has_tun:
                    self._cfg["inbounds"] = [
                        i for i in self._cfg["inbounds"]
                        if i.get("type") != "tun"
                    ]
                    self._tun_var.set(False)
                    self._log("[GUI] TUN removed (no Admin) — using Mixed proxy mode")

            cfg = self._make_runtime_cfg()
            self._log(f"[GUI] Writing runtime config → {RUNTIME_CFG.name}")

            with open(RUNTIME_CFG, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)

            self._log(f"[GUI] Launching: {SINGBOX_EXE.name} run -c {RUNTIME_CFG.name}")

            self._proc = subprocess.Popen(
                [str(SINGBOX_EXE), "run", "-c", str(RUNTIME_CFG)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            self._log(f"[GUI] Process started (PID {self._proc.pid})")

            self._running = True
            self._set_ui_state(True)
            threading.Thread(target=self._reader, daemon=True).start()
            self._log("[GUI] ▶ Sing-Box is running")

        except Exception as e:
            self._log(f"[GUI] ✗ START ERROR: {e}")
            messagebox.showerror("Start Error", str(e))

    def stop(self):
        if not self._running:
            return
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
        self._running = False
        self._set_ui_state(False)
        self._log("[GUI] ■ Sing-Box stopped")

    def restart(self):
        self.stop()
        time.sleep(0.4)
        self.start()

    def _set_ui_state(self, running: bool):
        if running:
            self._dot.configure(text_color="#44ff44")
            self._status_lbl.configure(text="Running")
            self._btn_start.configure(state="disabled")
            self._btn_stop.configure(state="normal")
            self._btn_restart.configure(state="normal")
        else:
            self._dot.configure(text_color="#ff4444")
            self._status_lbl.configure(text="Stopped")
            self._btn_start.configure(state="normal")
            self._btn_stop.configure(state="disabled")
            self._btn_restart.configure(state="disabled")

    # ──────────────────────────────────────────────────────
    # Logging
    # ──────────────────────────────────────────────────────
    def _reader(self):
        try:
            for line in self._proc.stdout:
                self._q.put(line.rstrip())
        except Exception:
            pass
        if self._running:
            self.after(0, self._proc_died)

    def _proc_died(self):
        self._running = False
        self._proc    = None
        self._set_ui_state(False)
        self._log("[GUI] ⚠ Process exited unexpectedly")

    def _log(self, msg: str):
        self._q.put(msg)

    def _tick(self):
        """Drain log queue every 80 ms — thread-safe."""
        try:
            lines = []
            while not self._q.empty():
                lines.append(self._q.get_nowait())
            if lines:
                self._logbox.configure(state="normal")
                for line in lines:
                    self._logbox.insert("end", line + "\n")
                self._logbox.see("end")
                self._logbox.configure(state="disabled")
        except Exception as e:
            print(f"[TICK ERROR] {e}", flush=True)
        self.after(80, self._tick)

    def _clear(self):
        self._logbox.configure(state="normal")
        self._logbox.delete("1.0", "end")
        self._logbox.configure(state="disabled")

    # ──────────────────────────────────────────────────────
    # Config Editor
    # ──────────────────────────────────────────────────────
    def _open_editor(self):
        """Open floating config editor window."""
        # If already open, just focus it
        if hasattr(self, "_ew") and self._ew.winfo_exists():
            self._ew.focus()
            return

        self._ew = ctk.CTkToplevel(self)
        self._ew.title("Config Editor")
        self._ew.geometry("860x680")
        self._ew.minsize(640, 460)

        # ── Header ────────────────────────────────────────
        hdr = ctk.CTkFrame(self._ew, height=50, corner_radius=0,
                           fg_color=("#1a1a2e", "#0d1117"))
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(hdr, text="📝  Config Editor",
                     font=ctk.CTkFont("Segoe UI", 15, "bold")
                     ).pack(side="left", padx=15)

        self._ew_status = ctk.CTkLabel(hdr, text="",
                                        font=ctk.CTkFont("Segoe UI", 11))
        self._ew_status.pack(side="right", padx=15)

        # ── Line-number + editor frame ─────────────────────
        editor_frame = ctk.CTkFrame(self._ew, fg_color="transparent")
        editor_frame.pack(fill="both", expand=True, padx=10, pady=(8, 0))

        # JSON editor
        self._ew_text = ctk.CTkTextbox(
            editor_frame,
            font=ctk.CTkFont("Consolas", 12),
            wrap="none",
            activate_scrollbars=True,
        )
        self._ew_text.pack(fill="both", expand=True)

        # ── Toolbar ───────────────────────────────────────
        tb_frame = ctk.CTkFrame(self._ew, fg_color="transparent")
        tb_frame.pack(fill="x", padx=10, pady=4)

        ctk.CTkButton(tb_frame, text="🔍 Format JSON", width=130, height=32,
                      fg_color="transparent", border_width=1,
                      command=self._editor_format).pack(side="left", padx=(0, 6))

        ctk.CTkButton(tb_frame, text="✓ Validate", width=110, height=32,
                      fg_color="transparent", border_width=1,
                      command=self._editor_validate).pack(side="left", padx=6)

        ctk.CTkButton(tb_frame, text="↺ Reset to current", width=140, height=32,
                      fg_color="transparent", border_width=1,
                      command=self._editor_reload).pack(side="left", padx=6)

        # search box
        self._ew_search = ctk.CTkEntry(tb_frame, placeholder_text="🔎 Search…",
                                        width=160, height=32)
        self._ew_search.pack(side="right", padx=(6, 0))
        self._ew_search.bind("<Return>", lambda e: self._editor_search())

        ctk.CTkButton(tb_frame, text="Find", width=60, height=32,
                      command=self._editor_search).pack(side="right", padx=4)

        # ── Footer buttons ────────────────────────────────
        ftr = ctk.CTkFrame(self._ew, height=58, corner_radius=0)
        ftr.pack(fill="x", side="bottom")
        ftr.pack_propagate(False)

        ctk.CTkButton(
            ftr, text="💾 Save to file…", width=150, height=40,
            fg_color="transparent", border_width=1,
            font=ctk.CTkFont(size=12),
            command=self._editor_save_file
        ).pack(side="left", padx=(14, 6), pady=9)

        ctk.CTkButton(
            ftr, text="✔ Apply to session", width=160, height=40,
            fg_color="#1a5c1a", hover_color="#228b22",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._editor_apply
        ).pack(side="left", padx=6, pady=9)

        ctk.CTkButton(
            ftr, text="✔ Apply & Restart", width=160, height=40,
            fg_color="#1a4a7a", hover_color="#1e5c99",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._editor_apply_restart
        ).pack(side="left", padx=6, pady=9)

        ctk.CTkButton(
            ftr, text="✕ Close", width=100, height=40,
            fg_color="transparent", border_width=1,
            font=ctk.CTkFont(size=12),
            command=self._ew.destroy
        ).pack(side="right", padx=(6, 14), pady=9)

        # Load current config into editor
        self._editor_reload()

    def _editor_reload(self):
        """Reload current in-memory config into editor."""
        if not self._cfg:
            self._ew_status.configure(text="⚠ No config loaded", text_color="#ffcc44")
            return
        content = json.dumps(self._cfg, indent=2, ensure_ascii=False)
        self._ew_text.configure(state="normal")
        self._ew_text.delete("1.0", "end")
        self._ew_text.insert("1.0", content)
        lines = content.count("\n") + 1
        self._ew_status.configure(
            text=f"Loaded  •  {lines} lines", text_color="gray60")

    def _editor_format(self):
        """Re-format JSON with 2-space indent."""
        raw = self._ew_text.get("1.0", "end").strip()
        try:
            parsed  = json.loads(raw)
            pretty  = json.dumps(parsed, indent=2, ensure_ascii=False)
            self._ew_text.delete("1.0", "end")
            self._ew_text.insert("1.0", pretty)
            lines = pretty.count("\n") + 1
            self._ew_status.configure(
                text=f"✓ Formatted  •  {lines} lines", text_color="#44cc44")
        except json.JSONDecodeError as e:
            self._ew_status.configure(
                text=f"✗ JSON error: {e}", text_color="#ff5555")

    def _editor_validate(self):
        """Validate JSON without applying."""
        raw = self._ew_text.get("1.0", "end").strip()
        try:
            parsed = json.loads(raw)
            keys   = list(parsed.keys())
            self._ew_status.configure(
                text=f"✓ Valid JSON  •  keys: {keys}", text_color="#44cc44")
        except json.JSONDecodeError as e:
            line = getattr(e, "lineno", "?")
            col  = getattr(e, "colno",  "?")
            self._ew_status.configure(
                text=f"✗ Line {line} col {col}: {e.msg}", text_color="#ff5555")

    def _editor_search(self):
        """Highlight all occurrences of the search term."""
        term = self._ew_search.get().strip()
        if not term:
            return
        tb = self._ew_text._textbox
        tb.tag_remove("search", "1.0", "end")
        tb.tag_config("search", background="#ffdd44", foreground="#000000")
        idx = "1.0"
        count = 0
        while True:
            idx = tb.search(term, idx, stopindex="end", nocase=True)
            if not idx:
                break
            end = f"{idx}+{len(term)}c"
            tb.tag_add("search", idx, end)
            idx = end
            count += 1
        if count:
            # Jump to first match
            first = tb.tag_ranges("search")
            if first:
                tb.see(first[0])
            self._ew_status.configure(
                text=f"Found {count} match(es)", text_color="#44cc44")
        else:
            self._ew_status.configure(
                text=f"'{term}' not found", text_color="#ffcc44")

    def _editor_apply(self):
        """Parse editor content and apply to in-memory config."""
        raw = self._ew_text.get("1.0", "end").strip()
        try:
            new_cfg = json.loads(raw)
        except json.JSONDecodeError as e:
            self._ew_status.configure(
                text=f"✗ JSON error: {e}", text_color="#ff5555")
            messagebox.showerror("JSON Error",
                                 f"Cannot parse JSON:\n{e}", parent=self._ew)
            return
        self._cfg = new_cfg
        self._sync_from_cfg()
        self._rebuild_selectors()
        self._ew_status.configure(
            text="✔ Applied to session", text_color="#44cc44")
        self._log("[GUI] Config updated from editor")

    def _editor_apply_restart(self):
        """Apply config and restart sing-box."""
        self._editor_apply()
        if self._cfg:
            if self._running:
                self.restart()
            else:
                self.start()

    def _editor_save_file(self):
        """Save editor content to a JSON file on disk."""
        raw = self._ew_text.get("1.0", "end").strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            self._ew_status.configure(
                text=f"✗ JSON error — fix before saving", text_color="#ff5555")
            messagebox.showerror("JSON Error", str(e), parent=self._ew)
            return

        path = filedialog.asksaveasfilename(
            title="Save Config",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All", "*.*")],
            initialfile="config.json",
            initialdir=str(BASE_DIR),
            parent=self._ew,
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(parsed, f, indent=2, ensure_ascii=False)
        self._ew_status.configure(
            text=f"✔ Saved → {os.path.basename(path)}", text_color="#44cc44")
        self._log(f"[GUI] Config saved to: {os.path.basename(path)}")

    # ──────────────────────────────────────────────────────
    def _on_close(self):
        if self._running:
            if messagebox.askyesno("Quit", "Sing-Box is running.\nStop and exit?"):
                self.stop()
                self.destroy()
        else:
            self.destroy()


# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    App().mainloop()
