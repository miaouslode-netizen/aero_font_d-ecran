"""
Aero Contrôle  (Windows)
------------------------
Tableau de bord de bureau en verre style "Frutiger Aero".

  SYSTÈME  : jauges processeur, mémoire, disque, batterie, températures,
             débit réseau, durée d'allumage
  TÂCHES   : mini gestionnaire des tâches -> programmes détectés, mémoire,
             processeur, bouton pour les fermer vite, "Fermer toutes les applis"
  ACTIONS  : changer le fond d'écran, volume / muet, musique (précédent,
             lecture, suivant), verrouiller, gestionnaire des tâches, corbeille

Arrière-plan (icône près de l'horloge), lancement avec Windows, réglages
sauvegardés, bouton de désinstallation. Rien ne tourne quand le widget est
masqué ou quand un jeu est en plein écran.
"""

import os
import sys
import gc
import json
import math
import time
import random
import shutil
import ctypes
import threading
import subprocess
from ctypes import wintypes

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
except ImportError:                       # (tests hors Windows)
    tk = ttk = messagebox = filedialog = None

from PIL import Image, ImageDraw, ImageFilter, ImageChops, ImageFont

try:
    import psutil
except ImportError:
    psutil = None
try:
    import pystray
except ImportError:
    pystray = None

# ------------------------------------------------------------ constantes ---

NOM = "AeroControle"
DATA = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), NOM)
CONFIG = os.path.join(DATA, "config.json")
EXE_INSTALLE = os.path.join(DATA, NOM + ".exe")
FROZEN = getattr(sys, "frozen", False)
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
IMAGES = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
CREATE_NO_WINDOW = 0x08000000

DEFAUT = dict(
    theme="Ciel Aero", echelle=100, opacite=100, zordre="bureau",
    verrouille=False, widget_visible=True, pos_x=None, pos_y=None,
    onglet="sys", mode_apps=True, tri="mem", confirmer=True,
    rafraichir=2, temp_s=20, dossier_fonds="", dernier_fond="",
    demarrage=True, pause_plein_ecran=True)

ZORDRES = {"Toujours au-dessus": "dessus",
           "Sur le bureau (sous les fenêtres)": "bureau",
           "Normal": "normal"}
ZORDRES_INV = {v: k for k, v in ZORDRES.items()}
ONGLETS = {"Système": "sys", "Tâches": "taches", "Actions": "actions"}
ONGLETS_INV = {v: k for k, v in ONGLETS.items()}

THEMES = {
    "Ciel Aero": dict(haut=(165, 224, 255), bas=(38, 138, 235),
                      orb_haut=(150, 236, 255), orb_bas=(14, 100, 214),
                      acc_haut=(196, 255, 160), acc_bas=(40, 176, 60)),
    "Nature": dict(haut=(196, 246, 172), bas=(44, 164, 84),
                   orb_haut=(218, 255, 172), orb_bas=(24, 138, 50),
                   acc_haut=(255, 250, 170), acc_bas=(235, 176, 30)),
    "Aqua": dict(haut=(152, 249, 240), bas=(8, 154, 176),
                 orb_haut=(172, 255, 248), orb_bas=(0, 134, 160),
                 acc_haut=(255, 255, 255), acc_bas=(104, 224, 255)),
    "Coucher de soleil": dict(haut=(255, 218, 142), bas=(224, 84, 116),
                              orb_haut=(255, 228, 152), orb_bas=(214, 74, 70),
                              acc_haut=(255, 246, 162), acc_bas=(255, 148, 40)),
    "Verre sombre": dict(haut=(108, 120, 142), bas=(18, 24, 40),
                         orb_haut=(142, 206, 255), orb_bas=(24, 84, 190),
                         acc_haut=(142, 212, 255), acc_bas=(40, 120, 230)),
}

# programmes qu'on ne propose jamais de fermer (système, sécurité, bureau)
PROTEGES = {
    "system", "system idle process", "registry", "smss.exe", "csrss.exe",
    "wininit.exe", "services.exe", "lsass.exe", "winlogon.exe", "svchost.exe",
    "explorer.exe", "dwm.exe", "fontdrvhost.exe", "ctfmon.exe", "sihost.exe",
    "taskhostw.exe", "runtimebroker.exe", "searchhost.exe", "searchindexer.exe",
    "startmenuexperiencehost.exe", "shellexperiencehost.exe",
    "textinputhost.exe", "securityhealthservice.exe",
    "securityhealthsystray.exe", "msmpeng.exe", "nissrv.exe", "audiodg.exe",
    "spoolsv.exe", "wudfhost.exe", "lsaiso.exe", "memcompression",
    "memory compression", "conhost.exe", "dllhost.exe", "wmiprvse.exe",
    "applicationframehost.exe", "lockapp.exe", "logonui.exe", "taskmgr.exe",
    "python.exe", "pythonw.exe", "py.exe"}

# géométrie (unités de base, avant le zoom)
L_PAN, H_PAN, MARGE = 380, 470, 14
HAUT_LISTE, NB_LIGNES, H_LIGNE = 114, 8, 30
_mutex = None


# --------------------------------------------------------------- config ---

def charger_config():
    cfg = json.loads(json.dumps(DEFAUT))
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def sauver_config(cfg):
    try:
        os.makedirs(DATA, exist_ok=True)
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def fmt_mem(mo):
    if mo >= 1024:
        return f"{mo / 1024:.1f}".replace(".", ",") + " Go"
    return f"{int(mo)} Mo"


def fmt_debit(o):
    if o >= 1048576:
        return f"{o / 1048576:.1f}".replace(".", ",") + " Mo/s"
    return f"{int(o / 1024)} Ko/s"


def fmt_duree(s):
    s = int(s)
    j, r = divmod(s, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    if j:
        return f"{j} j {h} h"
    return f"{h} h {m:02d} min" if h else f"{m} min"


# ------------------------------------------------------------- Windows ---

_u = None
_g = None
_dwm = None


def api():
    global _u, _g, _dwm
    if _u:
        return _u, _g
    u = ctypes.WinDLL("user32", use_last_error=True)
    g = ctypes.WinDLL("gdi32", use_last_error=True)
    H = wintypes.HWND
    V = ctypes.c_void_p
    u.FindWindowExW.argtypes = [H, H, wintypes.LPCWSTR, wintypes.LPCWSTR]
    u.FindWindowExW.restype = H
    u.EnumWindows.argtypes = [V, wintypes.LPARAM]
    u.EnumWindows.restype = wintypes.BOOL
    u.IsWindowVisible.argtypes = [H]
    u.GetWindowTextLengthW.argtypes = [H]
    u.GetWindowTextW.argtypes = [H, wintypes.LPWSTR, ctypes.c_int]
    u.GetWindowThreadProcessId.argtypes = [H, ctypes.POINTER(wintypes.DWORD)]
    u.GetForegroundWindow.restype = H
    u.GetWindowRect.argtypes = [H, V]
    u.GetClassNameW.argtypes = [H, wintypes.LPWSTR, ctypes.c_int]
    u.GetParent.argtypes = [H]
    u.GetParent.restype = H
    u.GetWindowLongW.argtypes = [H, ctypes.c_int]
    u.GetWindowLongW.restype = ctypes.c_long
    u.SetWindowLongW.argtypes = [H, ctypes.c_int, ctypes.c_long]
    u.SetWindowLongW.restype = ctypes.c_long
    u.SetWindowPos.argtypes = [H, H, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, wintypes.UINT]
    u.SetWindowPos.restype = wintypes.BOOL
    u.SetForegroundWindow.argtypes = [H]
    u.GetDC.argtypes = [H]
    u.GetDC.restype = V
    u.ReleaseDC.argtypes = [H, V]
    u.UpdateLayeredWindow.argtypes = [H, V, V, V, V, V, wintypes.DWORD, V,
                                      wintypes.DWORD]
    u.UpdateLayeredWindow.restype = wintypes.BOOL
    g.CreateCompatibleDC.argtypes = [V]
    g.CreateCompatibleDC.restype = V
    g.CreateDIBSection.argtypes = [V, V, wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), V,
                                   wintypes.DWORD]
    g.CreateDIBSection.restype = V
    g.SelectObject.argtypes = [V, V]
    g.SelectObject.restype = V
    g.DeleteObject.argtypes = [V]
    g.DeleteDC.argtypes = [V]
    try:
        _dwm = ctypes.WinDLL("dwmapi")
        _dwm.DwmGetWindowAttribute.argtypes = [H, wintypes.DWORD, V,
                                               wintypes.DWORD]
    except Exception:
        _dwm = None
    _u, _g = u, g
    return u, g


def instance_unique():
    global _mutex
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.restype = ctypes.c_void_p
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k.CreateMutexW(None, False, NOM + "_mutex")
    if ctypes.get_last_error() == 183:      # ERROR_ALREADY_EXISTS
        k.CloseHandle(h)
        return False
    _mutex = h
    return True


def basse_priorite():
    try:
        k = ctypes.WinDLL("kernel32")
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000)
    except Exception:
        pass


def taille_ecran():
    u = ctypes.windll.user32
    return u.GetSystemMetrics(0), u.GetSystemMetrics(1)


def hote_icones():
    try:
        u, _ = api()
        trouve = []
        proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                   wintypes.LPARAM)

        def cb(h, lp):
            if u.FindWindowExW(h, None, "SHELLDLL_DefView", None):
                trouve.append(h)
                return False
            return True

        u.EnumWindows(proto(cb), 0)
        return trouve[0] if trouve else None
    except Exception:
        return None


def plein_ecran_actif():
    try:
        u, _ = api()
        h = u.GetForegroundWindow()
        if not h:
            return False

        class RECT(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                        ("r", ctypes.c_long), ("b", ctypes.c_long)]

        r = RECT()
        u.GetWindowRect(h, ctypes.byref(r))
        sw, sh = taille_ecran()
        if r.l > 0 or r.t > 0 or r.r < sw or r.b < sh:
            return False
        if u.GetWindowLongW(h, -16) & 0xC00000:
            return False
        buf = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(h, buf, 64)
        return buf.value not in ("Progman", "WorkerW", "Shell_TrayWnd")
    except Exception:
        return False


def fenetres_visibles():
    """{pid: titre} des programmes qui ont une vraie fenêtre ouverte."""
    res = {}
    try:
        u, _ = api()
        proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                   wintypes.LPARAM)

        def cb(h, lp):
            try:
                if not u.IsWindowVisible(h):
                    return True
                ex = u.GetWindowLongW(h, -20) & 0xFFFFFFFF
                if ex & 0x80 and not ex & 0x40000:       # fenêtre outil
                    return True
                n = u.GetWindowTextLengthW(h)
                if n == 0:
                    return True
                if _dwm:
                    cache = wintypes.DWORD(0)
                    _dwm.DwmGetWindowAttribute(h, 14, ctypes.byref(cache), 4)
                    if cache.value:                      # appli UWP en veille
                        return True
                buf = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(h, buf, n + 1)
                if buf.value in ("Program Manager", "Settings"):
                    return True
                pid = wintypes.DWORD()
                u.GetWindowThreadProcessId(h, ctypes.byref(pid))
                res.setdefault(pid.value, buf.value)
            except Exception:
                pass
            return True

        u.EnumWindows(proto(cb), 0)
    except Exception:
        pass
    return res


def definir_fond(chemin):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop",
                            0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "WallpaperStyle", 0, winreg.REG_SZ, "10")
            winreg.SetValueEx(k, "TileWallpaper", 0, winreg.REG_SZ, "0")
    except Exception:
        pass
    ctypes.windll.user32.SystemParametersInfoW(20, 0, os.path.abspath(chemin), 3)


def touche(vk):
    u = ctypes.windll.user32
    u.keybd_event(vk, 0, 0, 0)
    u.keybd_event(vk, 0, 2, 0)


def installer_exe():
    try:
        src = os.path.abspath(sys.executable)
        if src.lower() == EXE_INSTALLE.lower():
            return
        if (not os.path.exists(EXE_INSTALLE)
                or os.path.getsize(EXE_INSTALLE) != os.path.getsize(src)):
            os.makedirs(DATA, exist_ok=True)
            shutil.copy2(src, EXE_INSTALLE)
    except OSError:
        pass


def commande_demarrage():
    if FROZEN:
        exe = EXE_INSTALLE if os.path.exists(EXE_INSTALLE) else sys.executable
        return f'"{exe}" --background'
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    return f'"{pyw}" "{os.path.abspath(__file__)}" --background'


def regler_demarrage(actif):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            if actif:
                if FROZEN:
                    installer_exe()
                winreg.SetValueEx(k, NOM, 0, winreg.REG_SZ,
                                  commande_demarrage())
            else:
                try:
                    winreg.DeleteValue(k, NOM)
                except FileNotFoundError:
                    pass
    except Exception:
        pass


# --------------------------------------------------- données du système ---

def mon_exe():
    return os.path.basename(sys.executable).lower()


class Temperatures:
    """Lecture de la température. Windows ne la donne pas toujours :
    on essaie LibreHardwareMonitor / OpenHardwareMonitor, la sonde ACPI
    (souvent réservée à l'administrateur) et nvidia-smi pour la carte NVIDIA."""
    SCRIPT = (
        "$t=$null;"
        "foreach($ns in 'root/LibreHardwareMonitor','root/OpenHardwareMonitor')"
        "{try{$s=Get-CimInstance -Namespace $ns -ClassName Sensor -ErrorAction Stop"
        "|Where-Object{$_.SensorType -eq 'Temperature' -and $_.Name -match 'CPU'}"
        "|Sort-Object Value -Descending|Select-Object -First 1;"
        "if($s){$t=[math]::Round($s.Value,0);break}}catch{}};"
        "if($t -eq $null){try{$z=Get-CimInstance -Namespace root/wmi "
        "-ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop"
        "|Select-Object -First 1;"
        "if($z){$t=[math]::Round($z.CurrentTemperature/10-273.15,0)}}catch{}};"
        "if($t -ne $null){Write-Output $t}")

    def __init__(self):
        self.cpu = None
        self.gpu = None
        self.occupe = False
        self.derniere = 0.0

    def lire(self):
        cpu = gpu = None
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                                "-Command", self.SCRIPT], capture_output=True,
                               text=True, timeout=25,
                               creationflags=CREATE_NO_WINDOW)
            v = int(float(r.stdout.strip().splitlines()[-1]))
            if 0 < v < 125:
                cpu = v
        except Exception:
            pass
        try:
            r = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu",
                                "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=8,
                               creationflags=CREATE_NO_WINDOW)
            v = int(r.stdout.strip().splitlines()[0])
            if 0 < v < 125:
                gpu = v
        except Exception:
            pass
        self.cpu, self.gpu = cpu, gpu
        self.derniere = time.time()
        return cpu, gpu


class Systeme:
    def __init__(self):
        self.users = {}
        self.moi = ""
        self.net = None
        if psutil:
            try:
                self.moi = psutil.Process().username().lower()
            except Exception:
                pass
            psutil.cpu_percent(None)

    def collecter(self, onglet, mode_apps, tri):
        d = {}
        if not psutil:
            return d
        d["cpu"] = psutil.cpu_percent(None)
        vm = psutil.virtual_memory()
        d["ram"] = vm.percent
        d["ram_txt"] = f"{vm.used / 2**30:.1f}".replace(".", ",") + " / " + \
            f"{vm.total / 2**30:.0f} Go"
        try:
            d["disque"] = psutil.disk_usage(
                os.environ.get("SystemDrive", "C:") + "\\").percent
        except Exception:
            d["disque"] = None
        try:
            b = psutil.sensors_battery()
            d["bat"] = (b.percent, b.power_plugged) if b else None
        except Exception:
            d["bat"] = None
        try:
            io = psutil.net_io_counters()
            t = time.time()
            if self.net:
                dt = max(0.1, t - self.net[0])
                d["down"] = (io.bytes_recv - self.net[1]) / dt
                d["up"] = (io.bytes_sent - self.net[2]) / dt
            self.net = (t, io.bytes_recv, io.bytes_sent)
        except Exception:
            pass
        try:
            d["allume"] = time.time() - psutil.boot_time()
        except Exception:
            pass
        if onglet == "taches":
            d["taches"] = self.lister(mode_apps, tri)
        return d

    def lister(self, mode_apps, tri):
        wins = fenetres_visibles()
        ncpu = psutil.cpu_count() or 1
        groupes = {}
        me, exe = os.getpid(), mon_exe()
        for p in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                info = p.info
                pid = info["pid"]
                nom = info["name"] or "?"
                mem = (info["memory_info"].rss / 1048576) if info["memory_info"] else 0
                cpu = p.cpu_percent(None) / ncpu
                if pid not in self.users:
                    try:
                        self.users[pid] = (p.username() or "").lower()
                    except Exception:
                        self.users[pid] = ""
            except (psutil.NoSuchProcess, psutil.AccessDenied,
                    psutil.ZombieProcess):
                continue
            cle = nom.lower()
            g = groupes.get(cle)
            if g is None:
                g = dict(nom=nom, cle=cle, pids=[], ram=0.0, cpu=0.0, n=0,
                         titre="", fenetre=False, protege=False)
                groupes[cle] = g
            g["pids"].append(pid)
            g["ram"] += mem
            g["cpu"] += cpu
            g["n"] += 1
            if pid in wins:
                g["fenetre"] = True
                if not g["titre"]:
                    g["titre"] = wins[pid]
            if (cle in PROTEGES or cle == exe or pid == me
                    or self.users[pid] != self.moi):
                g["protege"] = True
        liste = list(groupes.values())
        if mode_apps:
            liste = [g for g in liste if g["fenetre"]]
        liste.sort(key=lambda g: g["cpu"] if tri == "cpu" else g["ram"],
                   reverse=True)
        if len(self.users) > 3000:
            self.users.clear()
        return liste


def fermer_groupe(g):
    """Ferme poliment (si fenêtre), puis de force. Renvoie True si fermé."""
    pids = list(g["pids"])
    flags = CREATE_NO_WINDOW
    try:
        if g.get("fenetre"):
            for pid in pids:
                subprocess.run(["taskkill", "/PID", str(pid), "/T"],
                               capture_output=True, creationflags=flags)
            for _ in range(8):
                time.sleep(0.4)
                if not any(psutil.pid_exists(p) for p in pids):
                    return True
        for pid in pids:
            if psutil.pid_exists(pid):
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                               capture_output=True, creationflags=flags)
        time.sleep(0.5)
        return not any(psutil.pid_exists(p) for p in pids)
    except Exception:
        return False


# ------------------------------------------------------------- dessin ---

def charger_police(genre, taille):
    noms = {"semi": ["seguisb.ttf", "segoeuib.ttf", "arialbd.ttf",
                     "DejaVuSans-Bold.ttf"],
            "leger": ["segoeuil.ttf", "segoeuisl.ttf", "segoeui.ttf",
                      "DejaVuSans.ttf"],
            "normal": ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"]}[genre]
    dossiers = [os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts"),
                ""]
    taille = int(max(6, round(taille)))
    for n in noms:
        for d in dossiers:
            try:
                return ImageFont.truetype(os.path.join(d, n) if d else n, taille)
            except OSError:
                continue
    return ImageFont.load_default()


def gloss(S, bbox, a0, a1):
    grad = Image.new("L", S, 0)
    gd = ImageDraw.Draw(grad)
    y0, y1 = int(bbox[1]), int(bbox[3])
    for y in range(max(0, y0), min(S[1], y1)):
        t = (y - y0) / max(1, y1 - y0)
        gd.line((0, y, S[0], y), fill=int(a0 + (a1 - a0) * t))
    m = Image.new("L", S, 0)
    ImageDraw.Draw(m).ellipse(bbox, fill=255)
    layer = Image.new("RGBA", S, (255, 255, 255, 0))
    layer.putalpha(ImageChops.multiply(grad, m))
    return layer


def poser(dest, sp, x, y):
    w, h = sp.size
    W, H = dest.size
    x, y = int(x), int(y)
    if x >= W or y >= H or x + w <= 0 or y + h <= 0:
        return
    sx, sy = max(0, -x), max(0, -y)
    ex, ey = min(w, W - x), min(h, H - y)
    if (sx, sy, ex, ey) != (0, 0, w, h):
        sp = sp.crop((sx, sy, ex, ey))
    dest.alpha_composite(sp, (max(0, x), max(0, y)))


def icone(d, nom, cx, cy, u, c):
    """Pictogrammes dessinés (pas de police d'icônes nécessaire)."""
    w = max(1, int(0.2 * u))
    if nom == "play":
        d.polygon([(cx - .45 * u, cy - .9 * u), (cx + .85 * u, cy),
                   (cx - .45 * u, cy + .9 * u)], fill=c)
    elif nom == "next":
        d.polygon([(cx - .8 * u, cy - .8 * u), (cx + .35 * u, cy),
                   (cx - .8 * u, cy + .8 * u)], fill=c)
        d.rectangle((cx + .45 * u, cy - .8 * u, cx + .85 * u, cy + .8 * u), fill=c)
    elif nom == "prev":
        d.polygon([(cx + .8 * u, cy - .8 * u), (cx - .35 * u, cy),
                   (cx + .8 * u, cy + .8 * u)], fill=c)
        d.rectangle((cx - .85 * u, cy - .8 * u, cx - .45 * u, cy + .8 * u), fill=c)
    elif nom in ("son", "muet", "vol+", "vol-"):
        d.polygon([(cx - 1.0 * u, cy - .35 * u), (cx - .5 * u, cy - .35 * u),
                   (cx + .05 * u, cy - .85 * u), (cx + .05 * u, cy + .85 * u),
                   (cx - .5 * u, cy + .35 * u), (cx - 1.0 * u, cy + .35 * u)], fill=c)
        if nom == "muet":
            d.line((cx + .35 * u, cy - .45 * u, cx + 1.0 * u, cy + .45 * u), fill=c, width=w)
            d.line((cx + .35 * u, cy + .45 * u, cx + 1.0 * u, cy - .45 * u), fill=c, width=w)
        elif nom == "vol+":
            d.line((cx + .4 * u, cy, cx + 1.1 * u, cy), fill=c, width=w)
            d.line((cx + .75 * u, cy - .35 * u, cx + .75 * u, cy + .35 * u), fill=c, width=w)
        elif nom == "vol-":
            d.line((cx + .4 * u, cy, cx + 1.1 * u, cy), fill=c, width=w)
        else:
            d.arc((cx - .3 * u, cy - .5 * u, cx + .6 * u, cy + .5 * u), -55, 55, fill=c, width=w)
    elif nom == "shuffle":
        d.line((cx - .95 * u, cy - .5 * u, cx + .6 * u, cy + .5 * u), fill=c, width=w)
        d.line((cx - .95 * u, cy + .5 * u, cx + .6 * u, cy - .5 * u), fill=c, width=w)
        d.polygon([(cx + 1.05 * u, cy + .5 * u), (cx + .5 * u, cy + .1 * u),
                   (cx + .5 * u, cy + .9 * u)], fill=c)
        d.polygon([(cx + 1.05 * u, cy - .5 * u), (cx + .5 * u, cy - .9 * u),
                   (cx + .5 * u, cy - .1 * u)], fill=c)
    elif nom == "image":
        d.rounded_rectangle((cx - 1.0 * u, cy - .8 * u, cx + 1.0 * u, cy + .8 * u),
                            int(.2 * u), outline=c, width=w)
        d.ellipse((cx + .2 * u, cy - .55 * u, cx + .65 * u, cy - .1 * u), fill=c)
        d.polygon([(cx - .8 * u, cy + .62 * u), (cx - .2 * u, cy - .05 * u),
                   (cx + .25 * u, cy + .42 * u), (cx + .5 * u, cy + .15 * u),
                   (cx + .85 * u, cy + .62 * u)], fill=c)
    elif nom == "dossier":
        d.polygon([(cx - 1.0 * u, cy - .6 * u), (cx - .25 * u, cy - .6 * u),
                   (cx + .0 * u, cy - .3 * u), (cx + 1.0 * u, cy - .3 * u),
                   (cx + 1.0 * u, cy + .7 * u), (cx - 1.0 * u, cy + .7 * u)], fill=c)
    elif nom == "verrou":
        d.rounded_rectangle((cx - .75 * u, cy - .1 * u, cx + .75 * u, cy + .85 * u),
                            int(.15 * u), fill=c)
        d.arc((cx - .5 * u, cy - .9 * u, cx + .5 * u, cy + .25 * u), 180, 360,
              fill=c, width=max(2, int(.24 * u)))
    elif nom == "taskmgr":
        d.rounded_rectangle((cx - 1.0 * u, cy - .8 * u, cx + 1.0 * u, cy + .65 * u),
                            int(.15 * u), outline=c, width=w)
        d.line([(cx - .7 * u, cy + .3 * u), (cx - .3 * u, cy - .2 * u),
                (cx + .1 * u, cy + .15 * u), (cx + .7 * u, cy - .4 * u)], fill=c, width=w)
        d.line((cx - .5 * u, cy + .9 * u, cx + .5 * u, cy + .9 * u), fill=c, width=w)
    elif nom == "corbeille":
        d.line((cx - .85 * u, cy - .55 * u, cx + .85 * u, cy - .55 * u), fill=c, width=w)
        d.rectangle((cx - .25 * u, cy - .85 * u, cx + .25 * u, cy - .55 * u), outline=c, width=w)
        d.polygon([(cx - .65 * u, cy - .4 * u), (cx + .65 * u, cy - .4 * u),
                   (cx + .5 * u, cy + .9 * u), (cx - .5 * u, cy + .9 * u)], outline=c, width=w)
        d.line((cx - .15 * u, cy - .1 * u, cx - .12 * u, cy + .65 * u), fill=c, width=w)
        d.line((cx + .15 * u, cy - .1 * u, cx + .12 * u, cy + .65 * u), fill=c, width=w)
    elif nom == "croix":
        d.line((cx - .6 * u, cy - .6 * u, cx + .6 * u, cy + .6 * u), fill=c, width=max(2, int(.3 * u)))
        d.line((cx - .6 * u, cy + .6 * u, cx + .6 * u, cy - .6 * u), fill=c, width=max(2, int(.3 * u)))
    elif nom == "engrenage":
        for k in range(8):
            a = k * math.pi / 4
            d.line((cx, cy, cx + math.cos(a) * u, cy + math.sin(a) * u), fill=c,
                   width=max(2, int(.5 * u)))
        d.ellipse((cx - .72 * u, cy - .72 * u, cx + .72 * u, cy + .72 * u), fill=c)
        d.ellipse((cx - .3 * u, cy - .3 * u, cx + .3 * u, cy + .3 * u), fill=(0, 0, 0, 0))
    elif nom == "balai":
        d.line((cx - .8 * u, cy + .8 * u, cx + .5 * u, cy - .7 * u), fill=c, width=max(2, int(.22 * u)))
        d.polygon([(cx - 1.0 * u, cy + .3 * u), (cx - .3 * u, cy + .0 * u),
                   (cx + .0 * u, cy + .9 * u), (cx - .9 * u, cy + 1.0 * u)], fill=c)


class Rendu:
    """Dessine le tableau de bord. Fond et sprites en cache : à chaque mise
    à jour on ne redessine que les textes et les valeurs."""

    def __init__(self, theme, echelle):
        self.th = THEMES.get(theme, THEMES["Ciel Aero"])
        self.E = max(0.5, echelle)
        self.W = int(round((L_PAN + 2 * MARGE) * self.E))
        self.H = int(round((H_PAN + 2 * MARGE) * self.E))
        self.K = 2.0 * self.W / (L_PAN + 2 * MARGE)
        self.cache = {}
        self.skin = self.creer_skin()

    def k(self, v):
        return int(round(v * self.K))

    def p(self, v):
        return int(round(v * self.E))

    def garder(self, cle, img):
        if len(self.cache) > 700:
            self.cache.clear()
        self.cache[cle] = img
        return img

    # ----------------------------------------------------------- fond ---
    def creer_skin(self):
        k, th = self.k, self.th
        W2, H2 = self.W * 2, self.H * 2
        box = (k(MARGE), k(MARGE), k(MARGE + L_PAN), k(MARGE + H_PAN))
        rayon = k(26)
        masque = Image.new("L", (W2, H2), 0)
        ImageDraw.Draw(masque).rounded_rectangle(box, rayon, fill=255)

        def clip(layer):
            layer.putalpha(ImageChops.multiply(layer.getchannel("A"), masque))
            return layer

        img = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        ombre = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        ImageDraw.Draw(ombre).rounded_rectangle(
            (box[0], box[1] + k(5), box[2], box[3] + k(5)), rayon,
            fill=(0, 20, 50, 135))
        img.alpha_composite(ombre.filter(ImageFilter.GaussianBlur(k(7))))

        deg = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        dd = ImageDraw.Draw(deg)
        for y in range(box[1], box[3]):
            t = (y - box[1]) / (box[3] - box[1])
            dd.line((box[0], y, box[2], y),
                    fill=mix(th["haut"], th["bas"], t) + (int(228 - 30 * t),))
        img.alpha_composite(clip(deg))

        # barre de titre en verre (style fenêtre Aero)
        tb = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        td = ImageDraw.Draw(tb)
        for y in range(box[1], box[1] + k(46)):
            t = (y - box[1]) / k(46)
            td.line((box[0], y, box[2], y), fill=(255, 255, 255, int(78 - 52 * t)))
        td.line((box[0], box[1] + k(46), box[2], box[1] + k(46)),
                fill=(255, 255, 255, 110), width=max(1, k(1)))
        img.alpha_composite(clip(tb))

        # bande de reflet en diagonale + halo en haut à droite
        sh = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sh)
        sd.polygon([(k(MARGE), k(MARGE + 120)), (k(MARGE + 230), k(MARGE)),
                    (k(MARGE + 330), k(MARGE)), (k(MARGE), k(MARGE + 310))],
                   fill=(255, 255, 255, 34))
        sd.polygon([(k(MARGE + 250), k(MARGE + H_PAN)),
                    (k(MARGE + L_PAN), k(MARGE + 300)),
                    (k(MARGE + L_PAN), k(MARGE + 380)),
                    (k(MARGE + 340), k(MARGE + H_PAN))], fill=(255, 255, 255, 26))
        sd.ellipse((k(MARGE + L_PAN - 150), k(MARGE - 90),
                    k(MARGE + L_PAN + 70), k(MARGE + 110)),
                   fill=(255, 255, 255, 60))
        img.alpha_composite(clip(sh.filter(ImageFilter.GaussianBlur(k(4)))))

        # bulles (autre disposition : bas-gauche et haut-droite)
        bul = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        bd = ImageDraw.Draw(bul)
        for x, y, r in ((24, 392, 24), (58, 434, 13), (18, 446, 8),
                        (352, 74, 17), (336, 112, 9), (365, 124, 6),
                        (300, 452, 11), (210, 20, 7)):
            cx, cy = MARGE + x, MARGE + y
            bd.ellipse((k(cx - r), k(cy - r), k(cx + r), k(cy + r)),
                       fill=(255, 255, 255, 22), outline=(255, 255, 255, 105),
                       width=max(1, k(1.3)))
            bd.ellipse((k(cx - r * .62), k(cy - r * .78), k(cx + r * .1),
                        k(cy - r * .2)), fill=(255, 255, 255, 95))
            bd.arc((k(cx - r * .8), k(cy - r * .8), k(cx + r * .8),
                    k(cy + r * .8)), 20, 100, fill=(255, 255, 255, 140),
                   width=max(1, k(1.1)))
        img.alpha_composite(clip(bul))

        # zone des mesures (pied de page)
        pied = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        ImageDraw.Draw(pied).rounded_rectangle(
            (k(MARGE + 8), k(MARGE + 414), k(MARGE + L_PAN - 8),
             k(MARGE + H_PAN - 8)), k(16), fill=(0, 30, 70, 46),
            outline=(255, 255, 255, 70), width=max(1, k(1)))
        img.alpha_composite(pied)

        bord = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        bdd = ImageDraw.Draw(bord)
        bdd.rounded_rectangle(box, rayon, outline=(255, 255, 255, 210),
                              width=k(2))
        ins = k(3)
        bdd.rounded_rectangle((box[0] + ins, box[1] + ins, box[2] - ins,
                               box[3] - ins), rayon - ins,
                              outline=(255, 255, 255, 60), width=max(1, k(1)))
        img.alpha_composite(bord)
        return img.resize((self.W, self.H), Image.LANCZOS)

    # --------------------------------------------------------- sprites ---
    def verre(self, w, h, r, haut, bas, a0, a1, rim=150, gl=60, hover=0):
        cle = ("v", w, h, r, haut, bas, a0, a1, rim, gl, hover)
        if cle in self.cache:
            return self.cache[cle]
        ss = 3
        Wp, Hp = max(4, self.p(w)) * ss, max(4, self.p(h)) * ss
        rad = self.p(r) * ss
        img = Image.new("RGBA", (Wp, Hp), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for y in range(Hp):
            t = y / max(1, Hp - 1)
            d.line((0, y, Wp, y), fill=mix(haut, bas, t) + (int(a0 + (a1 - a0) * t),))
        m = Image.new("L", (Wp, Hp), 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, Wp - 1, Hp - 1), rad, fill=255)
        img.putalpha(ImageChops.multiply(img.getchannel("A"), m))
        if gl:
            g = Image.new("RGBA", (Wp, Hp), (0, 0, 0, 0))
            gd = ImageDraw.Draw(g)
            for y in range(int(Hp * 0.52)):
                t = y / (Hp * 0.52)
                gd.line((0, y, Wp, y), fill=(255, 255, 255, int(gl * (1 - t))))
            g.putalpha(ImageChops.multiply(g.getchannel("A"), m))
            img.alpha_composite(g)
        if hover:
            hv = Image.new("RGBA", (Wp, Hp), (255, 255, 255, hover))
            hv.putalpha(ImageChops.multiply(hv.getchannel("A"), m))
            img.alpha_composite(hv)
        ImageDraw.Draw(img).rounded_rectangle((0, 0, Wp - 1, Hp - 1), rad,
                                              outline=(255, 255, 255, rim), width=ss)
        res = img.resize((Wp // ss, Hp // ss), Image.LANCZOS)
        return self.garder(cle, res)

    def pilule(self, w, h, actif, survol):
        th = self.th
        if actif:
            return self.verre(w, h, h / 2, th["orb_haut"], th["orb_bas"], 255, 255,
                              rim=210, gl=90, hover=30 if survol else 0)
        return self.verre(w, h, h / 2, (255, 255, 255), (190, 225, 255), 80, 34,
                          rim=125, gl=55, hover=45 if survol else 0)

    def icone(self, nom, u, coul=(255, 255, 255)):
        cle = ("i", nom, u, coul)
        if cle in self.cache:
            return self.cache[cle]
        ss = 3
        D = self.p(u * 2.8) * ss
        c = D / 2
        uu = u * self.E * ss
        img = Image.new("RGBA", (D, D), (0, 0, 0, 0))
        omb = Image.new("RGBA", (D, D), (0, 0, 0, 0))
        icone(ImageDraw.Draw(omb), nom, c, c + 1.4 * self.E * ss, uu, (0, 40, 90, 120))
        img.alpha_composite(omb.filter(ImageFilter.GaussianBlur(1.1 * self.E * ss)))
        icone(ImageDraw.Draw(img), nom, c, c, uu, coul + (255,))
        res = img.resize((D // ss, D // ss), Image.LANCZOS)
        return self.garder(cle, res)

    def bouton_rond(self, nom, survol, coul=None):
        cle = ("br", nom, survol, coul)
        if cle in self.cache:
            return self.cache[cle]
        th = self.th
        c1, c2 = coul or (th["orb_haut"], th["orb_bas"])
        s = self.verre(24, 24, 12, c1, c2, 255, 255, rim=210, gl=90,
                       hover=40 if survol else 0).copy()
        ic = self.icone(nom, 7.2)
        s.alpha_composite(ic, ((s.width - ic.width) // 2, (s.height - ic.height) // 2))
        return self.garder(cle, s)

    def texte(self, s, genre, taille, couleur=(255, 255, 255), larg=None,
              ombre=(0, 35, 85, 140)):
        cle = ("t", s, genre, taille, couleur, larg, ombre)
        if cle in self.cache:
            return self.cache[cle]
        police = charger_police(genre, self.p(taille))
        if larg is not None:
            maxpx = self.p(larg)
            if police.getlength(s) > maxpx:
                while s and police.getlength(s + "…") > maxpx:
                    s = s[:-1]
                s += "…"
        w = int(police.getlength(s or " ")) + 8
        h = int(self.p(taille) * 1.45) + 6
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        dec = max(1, self.p(1.3))
        if ombre:
            d.text((4, 3 + dec), s, font=police, fill=ombre)
        d.text((4, 3), s, font=police, fill=couleur + (255,))
        return self.garder(cle, img)

    def couleur_niveau(self, v):
        if v is None:
            return self.th["acc_bas"]
        if v < 60:
            return self.th["acc_bas"]
        if v < 85:
            return (255, 188, 40)
        return (236, 62, 52)

    def jauge(self, v):
        cle = ("j", None if v is None else int(v))
        if cle in self.cache:
            return self.cache[cle]
        ss = 3
        D = self.p(96)
        S = D * ss
        c = S / 2
        R = S / 2 - 2 * ss
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((c - R, c - R, c + R, c + R), fill=(255, 255, 255, 34),
                  outline=(255, 255, 255, 135), width=ss * 2)
        img.alpha_composite(gloss((S, S), (c - R * .84, c - R * .97, c + R * .84,
                                           c - R * .06), 80, 4))
        d = ImageDraw.Draw(img)
        w = max(3, int(9 * self.E * ss))
        Rr = R * 0.80
        box = (c - Rr, c - Rr, c + Rr, c + Rr)
        d.arc(box, 135, 405, fill=(0, 35, 85, 105), width=w)
        if v is not None and v > 0:
            fin = 135 + 270 * min(100, v) / 100
            col = self.couleur_niveau(v)
            d.arc(box, 135, fin, fill=col + (255,), width=w)
            for ang in (135, fin):
                x = c + Rr * math.cos(math.radians(ang))
                y = c + Rr * math.sin(math.radians(ang))
                d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=col + (255,))
            Rh = Rr + w * 0.22
            d.arc((c - Rh, c - Rh, c + Rh, c + Rh), 138, fin - 3,
                  fill=mix(col, (255, 255, 255), .6) + (150,), width=max(1, w // 4))
        res = img.resize((D, D), Image.LANCZOS)
        return self.garder(cle, res)

    def barre(self, w, frac, col):
        cle = ("b", w, int(max(0, min(1, frac)) * self.p(w)), col)
        if cle in self.cache:
            return self.cache[cle]
        ss = 3
        Wp, Hp = self.p(w) * ss, max(6, self.p(9)) * ss
        img = Image.new("RGBA", (Wp, Hp), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        r = Hp // 2
        d.rounded_rectangle((0, 0, Wp - 1, Hp - 1), r, fill=(0, 30, 70, 100),
                            outline=(255, 255, 255, 115), width=ss)
        fx = int(max(0.0, min(1.0, frac)) * (Wp - 1))
        if fx > r:
            fill = Image.new("RGBA", (Wp, Hp), (0, 0, 0, 0))
            fd = ImageDraw.Draw(fill)
            for y in range(Hp):
                t = y / max(1, Hp - 1)
                fd.line((0, y, Wp, y), fill=mix(mix(col, (255, 255, 255), .55), col, t) + (255,))
            m = Image.new("L", (Wp, Hp), 0)
            ImageDraw.Draw(m).rounded_rectangle((0, 0, fx, Hp - 1), r, fill=255)
            fill.putalpha(ImageChops.multiply(fill.getchannel("A"), m))
            img.alpha_composite(fill)
        res = img.resize((Wp // ss, Hp // ss), Image.LANCZOS)
        return self.garder(cle, res)

    def pastille(self, nom):
        cle = ("pa", nom)
        if cle in self.cache:
            return self.cache[cle]
        pal = [(255, 140, 60), (60, 190, 120), (80, 150, 255), (230, 90, 150),
               (160, 120, 240), (240, 200, 60), (70, 200, 220)]
        col = pal[sum(ord(ch) for ch in nom) % len(pal)]
        ss, D = 4, max(8, self.p(12))
        S = D * ss
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((ss, ss, S - ss, S - ss), fill=col + (255,),
                  outline=(255, 255, 255, 220), width=ss)
        d.ellipse((S * .24, S * .16, S * .66, S * .46), fill=(255, 255, 255, 140))
        return self.garder(cle, img.resize((D, D), Image.LANCZOS))

    # -------------------------------------------------------- assemblage ---
    def composer(self, d):
        """d = dictionnaire d'état. Renvoie (image, zones cliquables)."""
        E, M = self.E, MARGE
        th = self.th
        img = self.skin.copy()
        zones = []
        sv = d.get("survol")
        blanc = (255, 255, 255)
        clair = (232, 247, 255)

        def X(v):
            return int(round((M + v) * E))

        def coin(s, x, y):
            poser(img, s, X(x), X(y))

        def txt(s, x, y):                     # texte aligné à gauche
            poser(img, s, X(x) - 4, X(y) - 3)

        def txt_d(s, xr, y):                  # aligné à droite
            poser(img, s, X(xr) - s.width + 4, X(y) - 3)

        def txt_c(s, cx, y):                  # centré
            poser(img, s, int(X(cx) - s.width / 2), X(y) - 3)

        def centre(s, cx, cy):
            poser(img, s, int(round((M + cx) * E - s.width / 2)),
                  int(round((M + cy) * E - s.height / 2)))

        def zone(i, x0, y0, x1, y1):
            zones.append((i, x0, y0, x1, y1))

        T = self.texte
        onglet = d["onglet"]

        # ---- en-tête
        txt(T("Centre de contrôle", "semi", 15, blanc), 18, 12)
        centre(self.bouton_rond("engrenage", sv == "gear"), 330, 23)
        zone("gear", 318, 11, 342, 35)
        centre(self.bouton_rond("croix", sv == "fermer",
                                ((255, 170, 150), (210, 50, 40))), 358, 23)
        zone("fermer", 346, 11, 370, 35)

        # ---- onglets
        for i, (cle, nom) in enumerate((("sys", "Système"), ("taches", "Tâches"),
                                        ("actions", "Actions"))):
            x0 = 15 + i * 118
            coin(self.pilule(114, 28, onglet == cle, sv == "tab:" + cle), x0, 52)
            txt_c(T(nom, "semi", 12.5, blanc), x0 + 57, 57)
            zone("tab:" + cle, x0, 52, x0 + 114, 80)

        # ---- contenu
        if onglet == "sys":
            self.onglet_systeme(d, centre, txt, txt_c, txt_d, coin, T)
        elif onglet == "taches":
            self.onglet_taches(d, centre, txt, txt_c, txt_d, coin, T, zone, sv, img)
        else:
            self.onglet_actions(d, centre, txt_c, coin, T, zone, sv)

        # ---- message
        if d.get("message"):
            txt(T(d["message"], "normal", 11, th["acc_haut"], 340), 20, 398)

        # ---- pied de page : CPU / RAM / température
        t_cpu = d.get("temp_cpu")
        t_gpu = d.get("temp_gpu")
        temp = t_cpu if t_cpu is not None else t_gpu
        puces = [("Processeur", d.get("cpu"), f"{int(d['cpu'])} %" if d.get("cpu") is not None else "—"),
                 ("Mémoire", d.get("ram"), f"{int(d['ram'])} %" if d.get("ram") is not None else "—"),
                 ("Température", temp if temp is None else min(100, temp),
                  f"{temp} °C" if temp is not None else "—")]
        for i, (nom, v, s) in enumerate(puces):
            x0 = 22 + i * 117
            txt(T(nom, "normal", 10.5, clair), x0, 424)
            txt_d(T(s, "semi", 11.5, blanc), x0 + 105, 424)
            coin(self.barre(105, (v or 0) / 100.0,
                            self.couleur_niveau(v)), x0, 443)
        return img, zones

    # ------------------------------------------------- onglet « Système »
    def onglet_systeme(self, d, centre, txt, txt_c, txt_d, coin, T):
        th = self.th
        blanc, clair = (255, 255, 255), (232, 247, 255)
        bat = d.get("bat")
        jauges = [("Processeur", d.get("cpu"), 100, 142, ""),
                  ("Mémoire", d.get("ram"), 280, 142, d.get("ram_txt", "")),
                  ("Disque", d.get("disque"), 100, 246, ""),
                  ("Batterie" if not (bat and bat[1]) else "En charge",
                   bat[0] if bat else None, 280, 246, "" if bat else "Secteur")]
        for nom, v, cx, cy, sous in jauges:
            centre(self.jauge(v), cx, cy)
            s = f"{int(v)}" if v is not None else "—"
            t = T(s, "semi", 24, blanc)
            centre(t, cx, cy - 6)
            txt_c(T(nom, "normal", 10.5, clair), cx, cy + 13)
            if sous:
                txt_c(T(sous, "normal", 9.5, clair), cx, cy + 53)
        y = 304
        txt(T("Températures", "semi", 11.5, blanc), 20, y)
        lignes = [("Processeur", d.get("temp_cpu")), ("Carte graphique", d.get("temp_gpu"))]
        if d.get("temp_cpu") is None and d.get("temp_gpu") is None:
            txt(T("Non disponible : voir Réglages > Température", "normal", 10.5, clair,
                  340), 20, y + 22)
        else:
            for i, (nom, v) in enumerate(lignes):
                yy = y + 22 + i * 22
                txt(T(nom, "normal", 10.5, clair), 20, yy)
                if v is None:
                    txt_d(T("—", "normal", 10.5, clair), 360, yy)
                else:
                    coin(self.barre(150, min(1, v / 100), self.couleur_niveau(v * 100 / 95)),
                         142, yy + 3)
                    txt_d(T(f"{v} °C", "semi", 11, blanc), 360, yy)
        yy = 372
        if "down" in d:
            txt(T(f"↓ {fmt_debit(d['down'])}    ↑ {fmt_debit(d['up'])}", "normal", 10.5, clair), 20, yy)
        if "allume" in d:
            txt_d(T("Allumé depuis " + fmt_duree(d["allume"]), "normal", 10.5, clair), 360, yy)

    # ------------------------------------------------- onglet « Tâches »
    def onglet_taches(self, d, centre, txt, txt_c, txt_d, coin, T, zone, sv, img):
        th = self.th
        blanc, clair = (255, 255, 255), (232, 247, 255)
        apps = d["mode_apps"]
        for i, (cle, nom, w) in enumerate((("apps", "Applications", 100),
                                            ("tous", "Processus", 86))):
            x0 = 15 + (0 if i == 0 else 104)
            actif = (apps and cle == "apps") or (not apps and cle == "tous")
            coin(self.pilule(w, 22, actif, sv == "mode:" + cle), x0, 88)
            txt_c(T(nom, "semi", 11, blanc), x0 + w / 2, 91)
            zone("mode:" + cle, x0, 88, x0 + w, 110)
        for i, (cle, nom, w) in enumerate((("mem", "Mémoire", 66), ("cpu", "CPU", 48))):
            x0 = 245 + (0 if i == 0 else 70)
            coin(self.pilule(w, 22, d["tri"] == cle, sv == "tri:" + cle), x0, 88)
            txt_c(T(nom, "semi", 11, blanc), x0 + w / 2, 91)
            zone("tri:" + cle, x0, 88, x0 + w, 110)

        liste = d.get("taches")
        if liste is None:
            txt(T("Lecture en cours…", "normal", 11.5, clair), 20, 130)
            return
        if not liste:
            txt(T("Aucun programme à afficher.", "normal", 11.5, clair), 20, 130)
        maxi = max(0, len(liste) - NB_LIGNES)
        off = max(0, min(d["scroll"], maxi))
        d["scroll"] = off
        for i in range(NB_LIGNES):
            idx = off + i
            if idx >= len(liste):
                break
            g = liste[idx]
            y = HAUT_LISTE + i * H_LIGNE
            surv = sv == f"ligne:{i}" or sv == f"kill:{idx}"
            if i % 2 == 0 or surv:
                coin(self.verre(342, H_LIGNE - 2, 8, (255, 255, 255), (255, 255, 255),
                                60 if surv else 26, 60 if surv else 26, rim=0, gl=0), 15, y)
            zone(f"ligne:{i}", 15, y, 300, y + H_LIGNE)
            centre(self.pastille(g["cle"]), 28, y + H_LIGNE / 2 - 1)
            nom = g["nom"][:-4] if g["nom"].lower().endswith(".exe") else g["nom"]
            if g["n"] > 1:
                nom += f"  ×{g['n']}"
            col = clair if g["protege"] else blanc
            if apps and g["titre"]:
                txt(T(nom, "semi", 11.5, col, 160), 42, y + 2)
                txt(T(g["titre"], "normal", 9, clair, 160, ombre=None), 42, y + 16)
            else:
                txt(T(nom, "semi", 11.5, col, 160), 42, y + 6)
            txt_d(T(fmt_mem(g["ram"]), "normal", 10.5, blanc), 262, y + 7)
            txt_d(T(f"{g['cpu']:.0f} %", "normal", 10.5, blanc), 306, y + 7)
            if g["protege"]:
                centre(self.icone("verrou", 5.2, (210, 232, 250)), 336, y + H_LIGNE / 2)
            else:
                if d.get("confirme") == g["cle"]:
                    coin(self.verre(40, 22, 11, (255, 190, 170), (214, 50, 40), 255, 255,
                                    rim=230, gl=90, hover=30 if surv else 0), 316, y + 3)
                    txt_c(T("Sûr ?", "semi", 10.5, blanc), 336, y + 6)
                    zone(f"kill:{idx}", 316, y + 3, 356, y + 25)
                else:
                    centre(self.bouton_rond("croix", surv,
                                            ((255, 170, 150), (210, 50, 40))),
                           336, y + H_LIGNE / 2)
                    zone(f"kill:{idx}", 322, y + 2, 350, y + 28)
        if maxi > 0:
            haut = NB_LIGNES * H_LIGNE
            tb = max(20, haut * NB_LIGNES / len(liste))
            ty = HAUT_LISTE + (haut - tb) * off / maxi
            coin(self.verre(4, tb / 1.0, 2, (255, 255, 255), (255, 255, 255), 150, 150,
                            rim=0, gl=0), 366, ty)
        # fermer toutes les applications
        bw = 350
        coin(self.verre(bw, 28, 14, (255, 190, 160), (214, 56, 40), 255, 255, rim=220,
                        gl=95, hover=36 if sv == "fermer_tout" else 0), 15, 362)
        centre(self.icone("balai", 6.4), 120, 376)
        txt_c(T("Fermer toutes les applications", "semi", 12, blanc), 205, 368)
        zone("fermer_tout", 15, 362, 365, 390)
        d["_liste"] = liste

    # ------------------------------------------------- onglet « Actions »
    def onglet_actions(self, d, centre, txt_c, coin, T, zone, sv):
        blanc = (255, 255, 255)
        boutons = [
            ("fond", "image", "Fond d'écran"), ("fond_alea", "shuffle", "Fond aléatoire"),
            ("fond_dossier", "dossier", "Dossier de fonds"),
            ("vol-", "vol-", "Volume −"), ("muet", "muet", "Muet"), ("vol+", "vol+", "Volume +"),
            ("prev", "prev", "Précédent"), ("play", "play", "Lecture / pause"),
            ("next", "next", "Suivant"),
            ("verrou", "verrou", "Verrouiller"), ("taskmgr", "taskmgr", "Gestionnaire"),
            ("corbeille", "corbeille", "Vider corbeille")]
        for i, (ident, ico, nom) in enumerate(boutons):
            col, lig = i % 3, i // 3
            x0, y0 = 15 + col * 119, 90 + lig * 76
            surv = sv == "btn:" + ident
            coin(self.verre(112, 68, 16, (255, 255, 255), (190, 225, 255), 96, 40,
                            rim=150, gl=70, hover=50 if surv else 0), x0, y0)
            centre(self.bouton_rond(ico, surv), x0 + 56, y0 + 25)
            txt_c(T(nom, "semi", 10.5, blanc, 106), x0 + 56, y0 + 45)
            zone("btn:" + ident, x0, y0, x0 + 112, y0 + 68)


# ------------------------------------------------ fenêtre transparente ---

class Fenetre:
    def __init__(self, app):
        self.app = app
        self.root = app.root
        self.dib = None
        self.x = self.y = 0
        self.depart = (0, 0, 0, 0)
        self.bouge = False
        self.z = None
        self.survol = None
        self.top = tk.Toplevel(self.root)
        self.top.overrideredirect(True)
        self.top.geometry("+-6000+-6000")
        self.top.update()
        u, g = api()
        inner = self.top.winfo_id()
        self.hwnd = u.GetParent(inner) or inner
        ex = u.GetWindowLongW(self.hwnd, -20)
        u.SetWindowLongW(self.hwnd, -20, ex | 0x80000 | 0x80)
        t = self.top
        t.bind("<ButtonPress-1>", self.appui)
        t.bind("<B1-Motion>", self.glisse)
        t.bind("<ButtonRelease-1>", self.relache)
        t.bind("<ButtonPress-3>", self.clic_droit)
        t.bind("<Motion>", self.survole)
        t.bind("<Leave>", lambda e: self.maj_survol(None))
        t.bind("<Enter>", lambda e: self.appliquer_zordre())
        t.bind("<MouseWheel>", self.molette)

    def configurer(self, w, h):
        self.liberer_dib()
        self.creer_dib(w, h)
        cfg = self.app.cfg
        sw, sh = taille_ecran()
        if cfg["pos_x"] is None:
            cfg["pos_x"] = sw - w - 30
            cfg["pos_y"] = 40
        self.x = min(max(cfg["pos_x"], -w + 80), sw - 80)
        self.y = min(max(cfg["pos_y"], -h + 80), sh - 80)
        self.appliquer_zordre()

    def creer_dib(self, w, h):
        u, g = api()

        class BMI(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                        ("biBitCount", wintypes.WORD),
                        ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD),
                        ("biXPels", ctypes.c_long), ("biYPels", ctypes.c_long),
                        ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]

        bmi = BMI(40, w, -h, 1, 32, 0, w * h * 4, 0, 0, 0, 0)
        self.hdc_ecran = u.GetDC(None)
        self.hdc = g.CreateCompatibleDC(self.hdc_ecran)
        bits = ctypes.c_void_p()
        self.bitmap = g.CreateDIBSection(self.hdc_ecran, ctypes.byref(bmi), 0,
                                         ctypes.byref(bits), None, 0)
        self.ancien = g.SelectObject(self.hdc, self.bitmap)
        self.bits = bits.value
        self.dib = (w, h)

    def liberer_dib(self):
        if not self.dib:
            return
        u, g = api()
        g.SelectObject(self.hdc, self.ancien)
        g.DeleteObject(self.bitmap)
        g.DeleteDC(self.hdc)
        u.ReleaseDC(None, self.hdc_ecran)
        self.dib = None

    def ecrire(self, img):
        if not self.dib or img.size != self.dib:
            return
        u, _ = api()
        pre = img.convert("RGBa")
        try:
            data = pre.tobytes("raw", "BGRa")
        except Exception:
            r, gr, b, a = pre.split()
            data = Image.merge("RGBA", (b, gr, r, a)).tobytes()
        ctypes.memmove(self.bits, data, len(data))

        class PT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class BL(ctypes.Structure):
            _fields_ = [("Op", ctypes.c_ubyte), ("Fl", ctypes.c_ubyte),
                        ("Alpha", ctypes.c_ubyte), ("Fmt", ctypes.c_ubyte)]

        pt, sz, src = PT(self.x, self.y), PT(*self.dib), PT(0, 0)
        op = int(max(30, min(100, self.app.cfg["opacite"])) * 2.55)
        bl = BL(0, 0, op, 1)
        u.UpdateLayeredWindow(self.hwnd, None, ctypes.byref(pt), ctypes.byref(sz),
                              self.hdc, ctypes.byref(src), 0, ctypes.byref(bl), 2)

    def deplacer(self):
        u, _ = api()
        u.SetWindowPos(self.hwnd, None, self.x, self.y, 0, 0, 0x1 | 0x4 | 0x10)

    def appliquer_zordre(self):
        try:
            u, _ = api()
            flags = 0x1 | 0x2 | 0x10
            mode = self.app.cfg["zordre"]
            if mode == "dessus":
                u.SetWindowPos(self.hwnd, wintypes.HWND(-1), 0, 0, 0, 0, flags)
            else:
                u.SetWindowPos(self.hwnd, wintypes.HWND(-2), 0, 0, 0, 0, flags)
                if mode == "bureau":
                    hote = hote_icones()
                    if hote:
                        u.SetWindowPos(self.hwnd, hote, 0, 0, 0, 0, flags)
        except Exception:
            pass

    # souris
    def hit(self, ex, ey):
        E = self.app.rendu.E
        bx, by = ex / E - MARGE, ey / E - MARGE
        for ident, x0, y0, x1, y1 in reversed(self.app.zones):
            if x0 <= bx <= x1 and y0 <= by <= y1:
                return ident
        return None

    def maj_survol(self, z):
        if z != self.survol:
            self.survol = z
            self.app.dessiner(force=True)

    def survole(self, e):
        self.maj_survol(self.hit(e.x, e.y))

    def appui(self, e):
        self.z = self.hit(e.x, e.y)
        self.depart = (e.x_root, e.y_root, self.x, self.y)
        self.bouge = False

    def glisse(self, e):
        dx, dy = e.x_root - self.depart[0], e.y_root - self.depart[1]
        if not self.bouge and abs(dx) + abs(dy) < 5:
            return
        self.bouge = True
        if self.app.cfg["verrouille"]:
            return
        self.x, self.y = self.depart[2] + dx, self.depart[3] + dy
        self.deplacer()

    def relache(self, e):
        if self.bouge:
            if not self.app.cfg["verrouille"]:
                self.app.cfg["pos_x"], self.app.cfg["pos_y"] = self.x, self.y
                self.app.sauver_plus_tard()
        elif self.z and not self.z.startswith("ligne:"):
            self.app.action(self.z)
        self.z = None
        self.root.after(60, self.appliquer_zordre)

    def molette(self, e):
        self.app.defiler(-1 if e.delta > 0 else 1)

    def clic_droit(self, e):
        try:
            u, _ = api()
            u.SetForegroundWindow(self.hwnd)
        except Exception:
            pass
        self.app.menu_contextuel(e.x_root, e.y_root)

    def replacer(self):
        sw, sh = taille_ecran()
        w, h = self.dib
        self.x, self.y = sw - w - 30, 40
        self.app.cfg["pos_x"], self.app.cfg["pos_y"] = self.x, self.y
        self.deplacer()

    def detruire(self):
        try:
            self.liberer_dib()
            self.top.destroy()
        except Exception:
            pass


# ------------------------------------------------------------ application ---

def icone_tray():
    r = Rendu("Ciel Aero", 1.0)
    base = r.verre(64, 64, 16, r.th["haut"], r.th["bas"], 255, 255, rim=230, gl=90)
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    img.alpha_composite(base)
    j = r.jauge(68).resize((54, 54), Image.LANCZOS)
    img.alpha_composite(j, (5, 5))
    return img


class App:
    def __init__(self, root, arriere):
        self.root = root
        self.cfg = charger_config()
        self.fenetre = None
        self.rendu = None
        self.zones = []
        self.data = dict(taches=None)
        self.sys = Systeme()
        self.temp = Temperatures()
        self.tache = None
        self.tache_sauv = None
        self.tache_rebuild = None
        self.tache_msg = None
        self.tache_conf = None
        self.occupe = False
        self.plein = False
        self.scroll = 0
        self.confirme = None
        self.message = ""
        self.tray = None
        self.prevenu = False
        self.maj_vars = False

        os.makedirs(DATA, exist_ok=True)
        regler_demarrage(self.cfg["demarrage"])
        root.title("Aero Contrôle – Réglages")
        root.geometry("540x600")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.cacher_reglages)
        self.construire_reglages()
        self.creer_tray()
        if self.cfg["widget_visible"]:
            self.montrer_widget()
        if arriere and self.cfg["widget_visible"]:
            root.withdraw()

    # ------------------------------------------------------ widget ------
    def montrer_widget(self):
        if self.fenetre is None:
            self.fenetre = Fenetre(self)
        self.cfg["widget_visible"] = True
        self.sync_var("v_widget", True)
        self.sauver_plus_tard()
        self.reconstruire()

    def masquer_widget(self):
        for t in (self.tache, self.tache_conf):
            if t:
                self.root.after_cancel(t)
        self.tache = self.tache_conf = None
        if self.fenetre:
            self.fenetre.detruire()
            self.fenetre = None
        self.rendu = None
        self.cfg["widget_visible"] = False
        self.sync_var("v_widget", False)
        self.sauver_plus_tard()

    def reconstruire_tard(self):
        if self.tache_rebuild:
            self.root.after_cancel(self.tache_rebuild)
        self.tache_rebuild = self.root.after(300, self.reconstruire)

    def reconstruire(self):
        self.tache_rebuild = None
        if not self.fenetre:
            return
        self.rendu = Rendu(self.cfg["theme"], self.cfg["echelle"] / 100.0)
        self.fenetre.configurer(self.rendu.W, self.rendu.H)
        self.dessiner(force=True)
        self.relancer()

    def etat(self):
        d = dict(self.data)
        d.update(onglet=self.cfg["onglet"], mode_apps=self.cfg["mode_apps"],
                 tri=self.cfg["tri"], scroll=self.scroll,
                 confirme=self.confirme, message=self.message,
                 survol=self.fenetre.survol if self.fenetre else None,
                 temp_cpu=self.temp.cpu, temp_gpu=self.temp.gpu)
        return d

    def dessiner(self, force=False):
        if not (self.fenetre and self.rendu):
            return
        d = self.etat()
        img, self.zones = self.rendu.composer(d)
        self.scroll = d["scroll"]
        self.liste = d.get("_liste", self.data.get("taches"))
        self.fenetre.ecrire(img)

    # ------------------------------------------------ collecte & boucle ---
    def relancer(self):
        if self.tache:
            self.root.after_cancel(self.tache)
        self.tache = self.root.after(50, self.tick)
        self.lancer_temp()

    def tick(self):
        self.tache = None
        if not self.fenetre:
            return
        if self.cfg["pause_plein_ecran"] and plein_ecran_actif():
            self.tache = self.root.after(5000, self.tick)
            return
        if not self.occupe:
            self.occupe = True
            args = (self.cfg["onglet"], self.cfg["mode_apps"], self.cfg["tri"])
            threading.Thread(target=self._collecter, args=args, daemon=True).start()
        ms = int(max(1, int(self.cfg["rafraichir"])) * 1000)
        self.tache = self.root.after(ms, self.tick)

    def _collecter(self, onglet, mode_apps, tri):
        try:
            d = self.sys.collecter(onglet, mode_apps, tri)
        except Exception:
            d = None
        try:
            self.root.after(0, lambda: self.apres_collecte(d))
        except Exception:
            self.occupe = False

    def apres_collecte(self, d):
        self.occupe = False
        if d is None or not self.fenetre:
            return
        if "taches" not in d:
            d["taches"] = self.data.get("taches")
        self.data = d
        self.dessiner()

    def lancer_temp(self):
        if self.fenetre and not self.temp.occupe and \
                time.time() - self.temp.derniere > max(10, int(self.cfg["temp_s"])) - 1:
            self.temp.occupe = True

            def travail():
                try:
                    self.temp.lire()
                finally:
                    self.temp.occupe = False
                try:
                    self.root.after(0, lambda: self.dessiner(force=True))
                except Exception:
                    pass

            threading.Thread(target=travail, daemon=True).start()
        if self.fenetre:
            self.root.after(max(10, int(self.cfg["temp_s"])) * 1000, self.lancer_temp_boucle)

    def lancer_temp_boucle(self):
        if self.fenetre and not self.temp.occupe:
            self.temp.derniere = 0
            self.lancer_temp()

    # --------------------------------------------------------- actions ---
    def dire(self, texte, duree=5000):
        self.message = texte
        if self.tache_msg:
            self.root.after_cancel(self.tache_msg)
        self.tache_msg = self.root.after(duree, self.effacer_message)
        self.dessiner(force=True)

    def effacer_message(self):
        self.message = ""
        self.tache_msg = None
        self.dessiner(force=True)

    def defiler(self, sens):
        if self.cfg["onglet"] == "taches":
            self.scroll = max(0, self.scroll + sens * 2)
            self.dessiner(force=True)

    def changer_onglet(self, o):
        self.cfg["onglet"] = o
        self.scroll = 0
        self.confirme = None
        self.sauver_plus_tard()
        self.dessiner(force=True)
        self.relancer()

    def action(self, z):
        if z.startswith("tab:"):
            self.changer_onglet(z[4:])
        elif z == "gear":
            self.montrer_reglages()
        elif z == "fermer":
            self.masquer_widget()
        elif z.startswith("mode:"):
            self.cfg["mode_apps"] = z[5:] == "apps"
            self.scroll = 0
            self.data["taches"] = None
            self.sauver_plus_tard()
            self.dessiner(force=True)
            self.relancer()
        elif z.startswith("tri:"):
            self.cfg["tri"] = z[4:]
            self.scroll = 0
            self.sauver_plus_tard()
            self.dessiner(force=True)
            self.relancer()
        elif z.startswith("kill:"):
            self.cliquer_fermer(int(z[5:]))
        elif z == "fermer_tout":
            self.fermer_toutes()
        elif z.startswith("btn:"):
            self.bouton_action(z[4:])

    # --- fermeture de programmes
    def cliquer_fermer(self, idx):
        liste = getattr(self, "liste", None) or []
        if idx >= len(liste):
            return
        g = liste[idx]
        if g["protege"]:
            return
        if self.cfg["confirmer"] and self.confirme != g["cle"]:
            self.confirme = g["cle"]
            if self.tache_conf:
                self.root.after_cancel(self.tache_conf)
            self.tache_conf = self.root.after(3000, self.fin_confirmation)
            self.dessiner(force=True)
            return
        self.fin_confirmation()
        self.fermer_en_fond([g])

    def fin_confirmation(self):
        self.confirme = None
        self.tache_conf = None
        self.dessiner(force=True)

    def fermer_en_fond(self, groupes):
        noms = ", ".join(g["nom"].replace(".exe", "") for g in groupes[:3])
        self.dire(f"Fermeture de {noms}…" if len(groupes) <= 3
                  else f"Fermeture de {len(groupes)} applications…", 15000)

        def travail():
            ok = sum(1 for g in groupes if fermer_groupe(g))
            if len(groupes) == 1:
                txt = (f"✔ {groupes[0]['nom'].replace('.exe', '')} fermé"
                       if ok else f"⚠ Impossible de fermer {groupes[0]['nom']}")
            else:
                txt = f"✔ {ok} application(s) fermée(s) sur {len(groupes)}"
            self.root.after(0, lambda: (self.dire(txt), self.relancer()))

        threading.Thread(target=travail, daemon=True).start()

    def fermer_toutes(self):
        def lancer(apps):
            cibles = [g for g in apps if g["fenetre"] and not g["protege"]]
            if not cibles:
                self.dire("Aucune application à fermer.")
                return
            noms = "\n".join("• " + g["nom"].replace(".exe", "") for g in cibles[:12])
            plus = f"\n… et {len(cibles) - 12} autre(s)" if len(cibles) > 12 else ""
            if messagebox.askyesno(
                    "Fermer toutes les applications",
                    f"Fermer ces {len(cibles)} application(s) ?\n\n{noms}{plus}\n\n"
                    "Ce qui n'est pas enregistré sera perdu si le programme ne le "
                    "propose pas.", icon="warning"):
                self.fermer_en_fond(cibles)

        def lire():
            try:
                apps = self.sys.lister(True, "mem")
            except Exception:
                apps = []
            self.root.after(0, lambda: lancer(apps))

        self.dire("Recherche des applications ouvertes…", 4000)
        threading.Thread(target=lire, daemon=True).start()

    # --- actions rapides
    def images_du_dossier(self):
        d = self.cfg["dossier_fonds"]
        try:
            return [os.path.join(d, f) for f in sorted(os.listdir(d))
                    if f.lower().endswith(IMAGES)]
        except OSError:
            return []

    def choisir_dossier_fonds(self):
        d = filedialog.askdirectory(title="Dossier d'images pour les fonds d'écran")
        if d:
            self.cfg["dossier_fonds"] = d
            self.sync_var("v_dossier", d)
            self.sauver_plus_tard()
            self.dire(f"Dossier choisi ({len(self.images_du_dossier())} images)")
            return True
        return False

    def fond_aleatoire(self):
        imgs = self.images_du_dossier()
        if not imgs:
            if not self.choisir_dossier_fonds():
                return
            imgs = self.images_du_dossier()
            if not imgs:
                self.dire("Aucune image dans ce dossier.")
                return
        choix = [i for i in imgs if i != self.cfg["dernier_fond"]] or imgs
        f = random.choice(choix)
        self.appliquer_fond(f)

    def appliquer_fond(self, f):
        try:
            definir_fond(f)
            self.cfg["dernier_fond"] = f
            self.sauver_plus_tard()
            self.dire("✔ Fond : " + os.path.basename(f))
        except Exception as e:
            self.dire(f"⚠ Fond impossible : {e}")

    def bouton_action(self, i):
        if i == "fond":
            f = filedialog.askopenfilename(
                title="Choisir une image pour le fond d'écran",
                filetypes=[("Images", " ".join("*" + e for e in IMAGES)),
                           ("Tous les fichiers", "*.*")])
            if f:
                self.appliquer_fond(f)
        elif i == "fond_alea":
            self.fond_aleatoire()
        elif i == "fond_dossier":
            self.choisir_dossier_fonds()
        elif i in ("vol+", "vol-"):
            for _ in range(5):
                touche(0xAF if i == "vol+" else 0xAE)
        elif i == "muet":
            touche(0xAD)
        elif i == "prev":
            touche(0xB1)
        elif i == "play":
            touche(0xB3)
        elif i == "next":
            touche(0xB0)
        elif i == "verrou":
            ctypes.windll.user32.LockWorkStation()
        elif i == "taskmgr":
            try:
                subprocess.Popen("taskmgr")
            except OSError:
                self.dire("⚠ Impossible d'ouvrir le gestionnaire.")
        elif i == "corbeille":
            if messagebox.askyesno("Corbeille", "Vider définitivement la corbeille ?",
                                   icon="warning"):
                r = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x7)
                self.dire("✔ Corbeille vidée" if r in (0, -2147418113)
                          else "Corbeille déjà vide")

    # ------------------------------------------------------------ menu ---
    def menu_contextuel(self, x, y):
        if not self.fenetre:
            return
        m = tk.Menu(self.fenetre.top, tearoff=0)
        for nom, cle in ONGLETS.items():
            m.add_command(label=("● " if self.cfg["onglet"] == cle else "    ") + nom,
                          command=lambda c=cle: self.changer_onglet(c))
        m.add_separator()
        m.add_command(label="🎲  Fond d'écran aléatoire", command=self.fond_aleatoire)
        m.add_command(label="⚙  Réglages…", command=self.montrer_reglages)
        m.add_command(label="🙈  Masquer", command=self.masquer_widget)
        m.add_command(label="✖  Quitter", command=self.quitter)
        try:
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    # ---------------------------------------------------------- réglages ---
    def sync_var(self, nom, valeur):
        v = getattr(self, nom, None)
        if v is not None:
            self.maj_vars = True
            try:
                v.set(valeur)
            finally:
                self.maj_vars = False

    def lier(self, var, cle, conv=lambda x: x, apres=None):
        def cb(*_):
            if self.maj_vars:
                return
            try:
                val = conv(var.get())
            except (tk.TclError, ValueError, KeyError):
                return
            self.cfg[cle] = val
            self.sauver_plus_tard()
            if apres:
                apres()
        var.trace_add("write", cb)

    def sauver_plus_tard(self):
        if self.tache_sauv:
            self.root.after_cancel(self.tache_sauv)
        self.tache_sauv = self.root.after(800, self.sauver_maintenant)

    def sauver_maintenant(self):
        self.tache_sauv = None
        sauver_config(self.cfg)

    def construire_reglages(self):
        c = self.cfg
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        pages = {}
        for cle, txt in (("widget", " Widget "), ("fonctions", " Fonctions "),
                         ("temp", " Température "), ("demarrage", " Démarrage "),
                         ("desinstaller", " Désinstaller ")):
            f = ttk.Frame(nb, padding=14)
            nb.add(f, text=txt)
            pages[cle] = f

        def curseur(p, lig, txt, var, a, b):
            ttk.Label(p, text=txt).grid(row=lig, column=0, sticky="w", pady=6)
            ttk.Scale(p, from_=a, to=b, variable=var,
                      command=lambda v: var.set(int(float(v)))
                      ).grid(row=lig, column=1, sticky="ew", padx=8)
            ttk.Label(p, textvariable=var, width=4).grid(row=lig, column=2)

        # ---- Widget
        p = pages["widget"]
        p.columnconfigure(1, weight=1)
        self.v_widget = tk.BooleanVar(value=c["widget_visible"])
        self.v_theme = tk.StringVar(value=c["theme"])
        self.v_echelle = tk.IntVar(value=c["echelle"])
        self.v_opacite = tk.IntVar(value=c["opacite"])
        self.v_zordre = tk.StringVar(value=ZORDRES_INV.get(c["zordre"]))
        self.v_verrou = tk.BooleanVar(value=c["verrouille"])
        self.v_plein = tk.BooleanVar(value=c["pause_plein_ecran"])
        ttk.Checkbutton(p, text="Afficher le widget sur le bureau",
                        variable=self.v_widget, command=self.toggle_widget_ui).grid(
            row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(p, text="Thème").grid(row=1, column=0, sticky="w", pady=8)
        ttk.Combobox(p, textvariable=self.v_theme, state="readonly",
                     values=list(THEMES)).grid(row=1, column=1, columnspan=2,
                                               sticky="ew", padx=8)
        curseur(p, 2, "Taille (%)", self.v_echelle, 60, 200)
        curseur(p, 3, "Opacité (%)", self.v_opacite, 30, 100)
        ttk.Label(p, text="Position").grid(row=4, column=0, sticky="w", pady=6)
        ttk.Combobox(p, textvariable=self.v_zordre, state="readonly",
                     values=list(ZORDRES)).grid(row=4, column=1, columnspan=2,
                                                sticky="ew", padx=8)
        ttk.Checkbutton(p, text="Verrouiller la position",
                        variable=self.v_verrou).grid(row=5, column=0, columnspan=3,
                                                     sticky="w", pady=4)
        ttk.Checkbutton(p, text="Mettre en pause quand une appli ou un jeu est en "
                        "plein écran", variable=self.v_plein).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Button(p, text="↖  Replacer en haut à droite",
                   command=self.replacer).grid(row=7, column=0, columnspan=3,
                                               sticky="w", pady=12)
        self.lier(self.v_theme, "theme", apres=self.reconstruire_tard)
        self.lier(self.v_echelle, "echelle", int, self.reconstruire_tard)
        self.lier(self.v_opacite, "opacite", int, lambda: self.dessiner(force=True))
        self.lier(self.v_zordre, "zordre", lambda x: ZORDRES[x],
                  lambda: self.fenetre and self.fenetre.appliquer_zordre())
        self.lier(self.v_verrou, "verrouille")
        self.lier(self.v_plein, "pause_plein_ecran")

        # ---- Fonctions
        p = pages["fonctions"]
        p.columnconfigure(1, weight=1)
        self.v_conf = tk.BooleanVar(value=c["confirmer"])
        self.v_onglet = tk.StringVar(value=ONGLETS_INV.get(c["onglet"]))
        self.v_raf = tk.IntVar(value=c["rafraichir"])
        self.v_dossier = tk.StringVar(value=c["dossier_fonds"] or "Aucun dossier choisi")
        ttk.Checkbutton(p, text="Demander « Sûr ? » avant de fermer un programme "
                        "(2e clic)", variable=self.v_conf).grid(
            row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(p, text="Onglet affiché").grid(row=1, column=0, sticky="w", pady=10)
        ttk.Combobox(p, textvariable=self.v_onglet, state="readonly",
                     values=list(ONGLETS)).grid(row=1, column=1, columnspan=2,
                                                sticky="ew", padx=8)
        curseur(p, 2, "Actualiser (s)", self.v_raf, 1, 10)
        ttk.Label(p, text="Dossier des fonds d'écran").grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(14, 2))
        ttk.Label(p, textvariable=self.v_dossier, foreground="#666",
                  wraplength=480).grid(row=4, column=0, columnspan=3, sticky="w")
        b = ttk.Frame(p)
        b.grid(row=5, column=0, columnspan=3, sticky="w", pady=8)
        ttk.Button(b, text="📁 Choisir…", command=self.choisir_dossier_fonds).pack(
            side="left", padx=(0, 8))
        ttk.Button(b, text="🎲 Changer le fond maintenant",
                   command=self.fond_aleatoire).pack(side="left")
        ttk.Label(p, foreground="#666", wraplength=480, text=(
            "Programmes protégés : Windows, la sécurité et le bureau ne peuvent "
            "pas être fermés depuis le widget (cadenas).")).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=16)
        self.lier(self.v_conf, "confirmer")
        self.lier(self.v_onglet, "onglet", lambda x: ONGLETS[x],
                  lambda: self.changer_onglet(self.cfg["onglet"]))
        self.lier(self.v_raf, "rafraichir", int)

        # ---- Température
        p = pages["temp"]
        self.v_temp_s = tk.IntVar(value=c["temp_s"])
        self.v_temp_res = tk.StringVar(value="")
        ttk.Label(p, wraplength=490, text=(
            "Windows ne donne pas toujours la température. L'application essaie "
            "(1) LibreHardwareMonitor ou OpenHardwareMonitor s'ils sont lancés, "
            "(2) la sonde ACPI de la carte mère (souvent réservée à "
            "l'administrateur) et (3) nvidia-smi pour une carte NVIDIA. "
            "Si rien n'est trouvé, le widget affiche « — ».")).pack(anchor="w")
        l = ttk.Frame(p)
        l.pack(fill="x", pady=12)
        ttk.Label(l, text="Lire toutes les").pack(side="left")
        ttk.Spinbox(l, from_=10, to=300, width=5, textvariable=self.v_temp_s
                    ).pack(side="left", padx=6)
        ttk.Label(l, text="secondes").pack(side="left")
        ttk.Button(p, text="🌡  Tester maintenant", command=self.tester_temp).pack(
            anchor="w", pady=4)
        ttk.Label(p, textvariable=self.v_temp_res, foreground="#2a6").pack(anchor="w")
        ttk.Button(p, text="🛡  Relancer en administrateur (pour la sonde ACPI)",
                   command=self.relancer_admin).pack(anchor="w", pady=14)
        ttk.Label(p, foreground="#666", wraplength=490, text=(
            "En administrateur, Windows te demande une confirmation. Au "
            "démarrage automatique, l'application se lance en mode normal.")
                  ).pack(anchor="w")
        self.lier(self.v_temp_s, "temp_s", lambda x: max(10, int(float(x))))

        # ---- Démarrage
        p = pages["demarrage"]
        self.v_demarrage = tk.BooleanVar(value=c["demarrage"])
        ttk.Checkbutton(p, text="Lancer Aero Contrôle avec Windows "
                        "(en arrière-plan)", variable=self.v_demarrage,
                        command=self.maj_demarrage).pack(anchor="w", pady=4)
        ttk.Label(p, foreground="#666", wraplength=490, text=(
            "Au démarrage, l'application se place près de l'horloge "
            "(flèche ^) et affiche directement le widget. Tous les réglages "
            "sont enregistrés automatiquement.")).pack(anchor="w", pady=10)

        # ---- Désinstaller
        p = pages["desinstaller"]
        ttk.Label(p, wraplength=490, text=(
            "La désinstallation retire le démarrage automatique et supprime "
            "l'application et ses réglages de cet ordinateur. Ton fond d'écran "
            "et tes programmes ne sont pas touchés.")).pack(anchor="w", pady=10)
        ttk.Button(p, text="🗑  Désinstaller Aero Contrôle…",
                   command=self.desinstaller).pack(anchor="w", pady=10)

    def tester_temp(self):
        self.v_temp_res.set("Lecture en cours…")

        def travail():
            cpu, gpu = self.temp.lire()
            txt = []
            txt.append(f"Processeur : {cpu} °C" if cpu is not None else "Processeur : introuvable")
            txt.append(f"Carte graphique : {gpu} °C" if gpu is not None else "Carte graphique : introuvable")
            self.root.after(0, lambda: (self.v_temp_res.set("   ".join(txt)),
                                        self.dessiner(force=True)))

        threading.Thread(target=travail, daemon=True).start()

    def relancer_admin(self):
        try:
            sh = ctypes.windll.shell32
            sh.ShellExecuteW.restype = ctypes.c_void_p
            sh.ShellExecuteW.argtypes = [wintypes.HWND, wintypes.LPCWSTR,
                                         wintypes.LPCWSTR, wintypes.LPCWSTR,
                                         wintypes.LPCWSTR, ctypes.c_int]
            if FROZEN:
                exe, params = sys.executable, "--attendre"
            else:
                exe = sys.executable
                params = f'"{os.path.abspath(__file__)}" --attendre'
            r = sh.ShellExecuteW(None, "runas", exe, params, None, 1)
            if (r or 0) > 32:
                self.quitter()
            else:
                messagebox.showinfo("Administrateur", "Relance annulée.")
        except Exception as e:
            messagebox.showerror("Administrateur", str(e))

    def toggle_widget_ui(self):
        if self.v_widget.get():
            self.montrer_widget()
        else:
            self.masquer_widget()

    def replacer(self):
        if self.fenetre:
            self.fenetre.replacer()

    def maj_demarrage(self):
        self.cfg["demarrage"] = self.v_demarrage.get()
        self.sauver_plus_tard()
        regler_demarrage(self.cfg["demarrage"])

    # ------------------------------------------- arrière-plan / quitter ---
    def creer_tray(self):
        if pystray is None:
            return
        menu = pystray.Menu(
            pystray.MenuItem(
                lambda i: "Masquer le widget" if self.fenetre else "Afficher le widget",
                lambda i, m: self.root.after(0, self.toggle_widget_tray), default=True),
            pystray.MenuItem("🎲 Fond d'écran aléatoire",
                             lambda i, m: self.root.after(0, self.fond_aleatoire)),
            pystray.MenuItem("Réglages…", lambda i, m: self.root.after(
                0, self.montrer_reglages)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quitter", lambda i, m: self.root.after(0, self.quitter)))
        self.tray = pystray.Icon(NOM, icone_tray(), "Aero Contrôle", menu)
        self.tray.run_detached()

    def toggle_widget_tray(self):
        if self.fenetre:
            self.masquer_widget()
        else:
            self.montrer_widget()

    def montrer_reglages(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def cacher_reglages(self):
        if self.tray:
            self.root.withdraw()
            if not self.prevenu:
                self.prevenu = True
                try:
                    self.tray.notify("Je continue en arrière-plan. Clic droit "
                                     "sur l'icône pour quitter.", "Aero Contrôle")
                except Exception:
                    pass
        else:
            self.root.iconify()

    def quitter(self):
        try:
            sauver_config(self.cfg)
            if self.fenetre:
                self.fenetre.detruire()
            if self.tray:
                self.tray.stop()
        except Exception:
            pass
        self.root.destroy()

    def desinstaller(self):
        if not messagebox.askyesno(
                "Désinstaller", "Supprimer Aero Contrôle, ses réglages et le "
                "démarrage automatique ?", icon="warning"):
            return
        regler_demarrage(False)
        if FROZEN:
            cmd = (f'ping 127.0.0.1 -n 4 >nul & del /f /q "{sys.executable}"'
                   f' & rmdir /s /q "{DATA}"')
            subprocess.Popen(f'cmd /s /c "{cmd}"', close_fds=True,
                             creationflags=CREATE_NO_WINDOW | 0x00000008)
        else:
            shutil.rmtree(DATA, ignore_errors=True)
        messagebox.showinfo("Désinstallé", "Aero Contrôle a été désinstallé.")
        try:
            if self.tache_sauv:
                self.root.after_cancel(self.tache_sauv)
            if self.fenetre:
                self.fenetre.detruire()
            if self.tray:
                self.tray.stop()
        except Exception:
            pass
        self.root.destroy()


# ------------------------------------------------------------------ main ---

def main():
    if not sys.platform.startswith("win"):
        print("Cette application fonctionne sous Windows uniquement.")
        return
    arriere = "--background" in sys.argv
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass
    if "--attendre" in sys.argv:             # relance en administrateur
        for _ in range(60):
            if instance_unique():
                break
            time.sleep(0.25)
        else:
            return
    elif not instance_unique():
        if not arriere:
            r = tk.Tk()
            r.withdraw()
            messagebox.showinfo(NOM, "Aero Contrôle tourne déjà.\nCherche son "
                                "icône près de l'horloge (flèche ^).")
        return
    if psutil is None:
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror(NOM, "Le module « psutil » est manquant.\n"
                             "Lance : pip install psutil")
        return
    basse_priorite()
    root = tk.Tk()
    App(root, arriere)
    root.mainloop()


if __name__ == "__main__":
    main()
