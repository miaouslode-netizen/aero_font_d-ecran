"""
Aero Musique  (Windows)
-----------------------
Lecteur de musique en arrière-plan avec un widget de bureau en verre
style "Frutiger Aero" (Windows Vista / 7).

- Joue MP3, MP4, M4A, WAV, WMA, AAC, FLAC, OGG... (le son des vidéos aussi)
- Se lance avec Windows, en arrière-plan (icône près de l'horloge)
- Options de démarrage : lecture auto, délai, volume, fondu d'entrée,
  reprise du titre et de la position
- Widget : thèmes, taille, opacité, position (dessus / bureau / normal),
  visualiseur, verrouillage, menu clic droit
- Réglages sauvegardés, bouton de désinstallation
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
import subprocess
from ctypes import wintypes

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except ImportError:                       # (pour les tests hors Windows)
    tk = ttk = filedialog = messagebox = None

from PIL import Image, ImageDraw, ImageFilter, ImageChops, ImageFont

try:
    import pystray
except ImportError:
    pystray = None

# ------------------------------------------------------------ constantes ---

NOM = "AeroMusique"
DATA = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), NOM)
CONFIG = os.path.join(DATA, "config.json")
EXE_INSTALLE = os.path.join(DATA, NOM + ".exe")
FROZEN = getattr(sys, "frozen", False)
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

EXTENSIONS = (".mp3", ".mp4", ".m4a", ".wav", ".wma", ".aac", ".flac", ".ogg",
              ".opus", ".mkv", ".webm", ".avi", ".mov", ".wmv", ".mpg",
              ".mpeg", ".3gp")

DEFAUT = dict(
    playlist=[], index=0, position_ms=0, volume=70, muet=False,
    aleatoire=False, repeter="tout",
    widget_visible=True, theme="Ciel Aero", echelle=100, opacite=100,
    zordre="bureau", verrouille=False, visualiseur=True, pos_x=None,
    pos_y=None,
    demarrage=True, lire_demarrage=True, delai=3, vol_demarrage_actif=False,
    vol_demarrage=60, fondu_entree=3, reprendre=True)

ZORDRES = {"Toujours au-dessus": "dessus",
           "Sur le bureau (sous les fenêtres)": "bureau",
           "Normal": "normal"}
ZORDRES_INV = {v: k for k, v in ZORDRES.items()}
REPETER = {"Non": "non", "Tout": "tout", "Un titre": "un"}
REPETER_INV = {v: k for k, v in REPETER.items()}

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

# géométrie du widget (unités de base, avant le zoom)
LARG, HAUT, MARGE = 340, 150, 14
IMG_L, IMG_H = LARG + 2 * MARGE, HAUT + 2 * MARGE
NB_BARRES = 18

# zones cliquables : (id, forme, x, y, w/rayon, h)   (repère = panneau)
ZONES = [
    ("orbe", "c", 62, 66, 40, 0),
    ("prec", "c", 34, 128, 13, 0),
    ("suiv", "c", 90, 128, 13, 0),
    ("muet", "c", 128, 130, 13, 0),
    ("shuffle", "c", 274, 130, 13, 0),
    ("repeat", "c", 306, 130, 13, 0),
    ("barre", "r", 112, 86, 214, 18),
    ("volume", "r", 146, 122, 102, 16),
]

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


def fmt(ms):
    s = max(0, int(ms // 1000))
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ------------------------------------------------------------- Windows ---

_u = None
_g = None


def api():
    """user32 / gdi32 avec les bons types (indispensable en 64 bits)."""
    global _u, _g
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
    _u, _g = u, g
    return u, g


def instance_unique():
    global _mutex
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.restype = ctypes.c_void_p
    _mutex = k.CreateMutexW(None, False, NOM + "_mutex")
    return ctypes.get_last_error() != 183


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
    """Fenêtre de plus haut niveau qui contient les icônes du bureau."""
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
        if actif:
            if FROZEN:
                installer_exe()
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, NOM, 0, winreg.REG_SZ,
                                  commande_demarrage())
        else:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as k:
                try:
                    winreg.DeleteValue(k, NOM)
                except FileNotFoundError:
                    pass
    except Exception:
        pass


# ------------------------------------------------- lecteur (Windows MCI) ---

class Lecteur:
    """Lecture via MCI (winmm) : aucune dépendance, très léger.
    Joue tout ce que Windows sait décoder (MP3, MP4, M4A, WAV, WMA...)."""
    A = "aeromus"

    def __init__(self):
        self.mm = ctypes.WinDLL("winmm")
        self.mm.mciSendStringW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR,
                                           wintypes.UINT, wintypes.HANDLE]
        self.mm.mciSendStringW.restype = wintypes.DWORD
        self.duree = 0
        self.ouvert = False

    def cmd(self, s):
        buf = ctypes.create_unicode_buffer(256)
        err = self.mm.mciSendStringW(s, buf, 255, None)
        return err, buf.value

    def ouvrir(self, chemin):
        self.fermer()
        chemin = os.path.abspath(chemin).replace('"', "")
        for t in ("type mpegvideo ", ""):
            err, _ = self.cmd(f'open "{chemin}" {t}alias {self.A}')
            if err == 0:
                break
        else:
            return False
        self.cmd(f"set {self.A} time format milliseconds")
        self.cmd(f"set {self.A} video off")      # son seulement
        err, d = self.cmd(f"status {self.A} length")
        self.duree = int(d) if err == 0 and d.strip().isdigit() else 0
        self.ouvert = True
        return True

    def jouer(self, depuis=0):
        if depuis > 0:
            self.cmd(f"play {self.A} from {int(depuis)}")
        else:
            self.cmd(f"play {self.A}")
        self.cmd(f"window {self.A} state hide")

    def pause(self):
        self.cmd(f"pause {self.A}")

    def reprendre(self):
        err, _ = self.cmd(f"resume {self.A}")
        if err:
            self.cmd(f"play {self.A}")

    def seek(self, ms, relancer):
        self.cmd(f"seek {self.A} to {int(ms)}")
        if relancer:
            self.cmd(f"play {self.A}")

    def position(self):
        err, v = self.cmd(f"status {self.A} position")
        return int(v) if err == 0 and v.strip().isdigit() else 0

    def mode(self):
        err, v = self.cmd(f"status {self.A} mode")
        return v if err == 0 else "error"

    def set_volume(self, v):
        v = max(0, min(100, int(v)))
        self.cmd(f"setaudio {self.A} volume to {v * 10}")

    def fermer(self):
        if self.ouvert:
            self.cmd(f"stop {self.A}")
            self.cmd(f"close {self.A}")
            self.ouvert = False


# ------------------------------------------------- rendu du widget (PIL) ---

def charger_police(taille, gras):
    noms = (["segoeuib.ttf", "seguisb.ttf", "arialbd.ttf",
             "DejaVuSans-Bold.ttf"] if gras else
            ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"])
    dossiers = [os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts"),
                ""]
    taille = int(max(6, round(taille)))
    for n in noms:
        for d in dossiers:
            try:
                return ImageFont.truetype(os.path.join(d, n) if d else n,
                                          taille)
            except OSError:
                continue
    return ImageFont.load_default()


def icone(d, nom, cx, cy, u, c):
    """Dessine un pictogramme blanc centré en (cx, cy), taille u."""
    w = max(1, int(0.2 * u))
    if nom == "play":
        d.polygon([(cx - .45 * u, cy - .9 * u), (cx + .85 * u, cy),
                   (cx - .45 * u, cy + .9 * u)], fill=c)
    elif nom == "pause":
        d.rounded_rectangle((cx - .8 * u, cy - .85 * u, cx - .25 * u,
                             cy + .85 * u), int(.12 * u), fill=c)
        d.rounded_rectangle((cx + .25 * u, cy - .85 * u, cx + .8 * u,
                             cy + .85 * u), int(.12 * u), fill=c)
    elif nom == "next":
        d.polygon([(cx - .8 * u, cy - .8 * u), (cx + .35 * u, cy),
                   (cx - .8 * u, cy + .8 * u)], fill=c)
        d.rectangle((cx + .45 * u, cy - .8 * u, cx + .85 * u, cy + .8 * u),
                    fill=c)
    elif nom == "prev":
        d.polygon([(cx + .8 * u, cy - .8 * u), (cx - .35 * u, cy),
                   (cx + .8 * u, cy + .8 * u)], fill=c)
        d.rectangle((cx - .85 * u, cy - .8 * u, cx - .45 * u, cy + .8 * u),
                    fill=c)
    elif nom in ("son", "muet"):
        d.polygon([(cx - .95 * u, cy - .35 * u), (cx - .45 * u, cy - .35 * u),
                   (cx + .1 * u, cy - .85 * u), (cx + .1 * u, cy + .85 * u),
                   (cx - .45 * u, cy + .35 * u), (cx - .95 * u, cy + .35 * u)],
                  fill=c)
        if nom == "son":
            d.arc((cx - .3 * u, cy - .5 * u, cx + .6 * u, cy + .5 * u),
                  -55, 55, fill=c, width=w)
            d.arc((cx - .45 * u, cy - .85 * u, cx + 1.0 * u, cy + .85 * u),
                  -55, 55, fill=c, width=w)
        else:
            d.line((cx + .4 * u, cy - .45 * u, cx + 1.05 * u, cy + .45 * u),
                   fill=c, width=w)
            d.line((cx + .4 * u, cy + .45 * u, cx + 1.05 * u, cy - .45 * u),
                   fill=c, width=w)
    elif nom == "shuffle":
        d.line((cx - .95 * u, cy - .5 * u, cx + .6 * u, cy + .5 * u),
               fill=c, width=w)
        d.line((cx - .95 * u, cy + .5 * u, cx + .6 * u, cy - .5 * u),
               fill=c, width=w)
        d.polygon([(cx + 1.05 * u, cy + .5 * u), (cx + .5 * u, cy + .1 * u),
                   (cx + .5 * u, cy + .9 * u)], fill=c)
        d.polygon([(cx + 1.05 * u, cy - .5 * u), (cx + .5 * u, cy - .9 * u),
                   (cx + .5 * u, cy - .1 * u)], fill=c)
    elif nom in ("repeat", "repeat1"):
        d.rounded_rectangle((cx - .95 * u, cy - .55 * u, cx + .95 * u,
                             cy + .6 * u), int(.4 * u), outline=c, width=w)
        d.polygon([(cx + .8 * u, cy - .55 * u), (cx + .2 * u, cy - .98 * u),
                   (cx + .2 * u, cy - .12 * u)], fill=c)
        if nom == "repeat1":
            d.line((cx, cy - .28 * u, cx, cy + .32 * u), fill=c, width=w)


class Rendu:
    """Dessine le widget (verre Aero) avec PIL. Tout est mis en cache :
    seuls les éléments qui changent sont redessinés."""

    def __init__(self, theme, echelle):
        self.th = THEMES.get(theme, THEMES["Ciel Aero"])
        self.E = max(0.5, echelle)
        self.W = int(round(IMG_L * self.E))
        self.H = int(round(IMG_H * self.E))
        self.K = 2.0 * self.W / IMG_L          # coefficient "supersample"
        self.cache = {}
        self.skin = self.creer_skin()

    def k(self, v):
        return int(round(v * self.K))

    def p(self, v):
        return int(round(v * self.E))

    # --- outils de dessin
    def gloss(self, S, bbox, a0, a1):
        grad = Image.new("L", (S, S), 0)
        gd = ImageDraw.Draw(grad)
        y0, y1 = int(bbox[1]), int(bbox[3])
        for y in range(max(0, y0), min(S, y1)):
            t = (y - y0) / max(1, y1 - y0)
            gd.line((0, y, S, y), fill=int(a0 + (a1 - a0) * t))
        m = Image.new("L", (S, S), 0)
        ImageDraw.Draw(m).ellipse(bbox, fill=255)
        layer = Image.new("RGBA", (S, S), (255, 255, 255, 0))
        layer.putalpha(ImageChops.multiply(grad, m))
        return layer

    def corps_rond(self, S, c_haut, c_bas, a_haut=255, a_bas=255):
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        R = S / 2 - self.k(1.5)
        c = S / 2
        n = 40
        for i in range(n):
            t = i / (n - 1)
            rr = R * (1 - 0.88 * t)
            dy = -R * 0.30 * t
            col = mix(c_bas, c_haut, t ** 0.9) + (int(a_bas + (a_haut - a_bas) * t),)
            d.ellipse((c - rr, c + dy - rr, c + rr, c + dy + rr), fill=col)
        return img

    # --- fond en verre
    def creer_skin(self):
        k, th = self.k, self.th
        W2, H2 = self.W * 2, self.H * 2
        box = (k(MARGE), k(MARGE), k(MARGE + LARG), k(MARGE + HAUT))
        rayon = k(26)
        masque = Image.new("L", (W2, H2), 0)
        ImageDraw.Draw(masque).rounded_rectangle(box, rayon, fill=255)
        img = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))

        ombre = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        ImageDraw.Draw(ombre).rounded_rectangle(
            (box[0], box[1] + k(5), box[2], box[3] + k(5)), rayon,
            fill=(0, 20, 50, 130))
        img.alpha_composite(ombre.filter(ImageFilter.GaussianBlur(k(6))))

        deg = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        dd = ImageDraw.Draw(deg)
        for y in range(box[1], box[3]):
            t = (y - box[1]) / (box[3] - box[1])
            dd.line((box[0], y, box[2], y),
                    fill=mix(th["haut"], th["bas"], t) + (int(222 - 34 * t),))
        deg.putalpha(ImageChops.multiply(deg.getchannel("A"), masque))
        img.alpha_composite(deg)

        # bulles
        bul = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        bd = ImageDraw.Draw(bul)
        for cx, cy, r in ((300, 34, 30), (262, 122, 17), (332, 98, 11),
                          (214, 16, 9), (14, 130, 15), (150, 140, 7)):
            cx, cy, r = MARGE + cx, MARGE + cy, r
            bd.ellipse((k(cx - r), k(cy - r), k(cx + r), k(cy + r)),
                       fill=(255, 255, 255, 34),
                       outline=(255, 255, 255, 120), width=max(1, k(1.4)))
            bd.ellipse((k(cx - r * .62), k(cy - r * .78), k(cx + r * .1),
                        k(cy - r * .2)), fill=(255, 255, 255, 110))
            bd.arc((k(cx - r * .8), k(cy - r * .8), k(cx + r * .8),
                    k(cy + r * .8)), 20, 100, fill=(255, 255, 255, 150),
                   width=max(1, k(1.2)))
        bul.putalpha(ImageChops.multiply(bul.getchannel("A"), masque))
        img.alpha_composite(bul)

        # reflet de verre sur la moitié haute
        gl = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        gd = ImageDraw.Draw(gl)
        gd.ellipse((box[0] - k(70), box[1] - k(190), box[2] + k(70),
                    box[1] + k(HAUT * 0.50)), fill=(255, 255, 255, 62))
        gl.putalpha(ImageChops.multiply(gl.getchannel("A"), masque))
        img.alpha_composite(gl)

        # contour
        bord = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        bdd = ImageDraw.Draw(bord)
        bdd.rounded_rectangle(box, rayon, outline=(255, 255, 255, 205),
                              width=k(2))
        ins = k(3)
        bdd.rounded_rectangle((box[0] + ins, box[1] + ins, box[2] - ins,
                               box[3] - ins), rayon - ins,
                              outline=(255, 255, 255, 60), width=max(1, k(1)))
        img.alpha_composite(bord)
        return img.resize((self.W, self.H), Image.LANCZOS)

    # --- sprites (mis en cache)
    def orbe(self, ico, survol):
        cle = ("orbe", ico, survol)
        if cle in self.cache:
            return self.cache[cle]
        k, th = self.k, self.th
        S = k(80)
        img = self.corps_rond(S, th["orb_haut"], th["orb_bas"])
        R = S / 2 - k(1.5)
        c = S / 2
        img.alpha_composite(self.gloss(
            S, (c - R * .74, c - R * .97, c + R * .74, c - R * .02), 175, 22))
        img.alpha_composite(self.gloss(
            S, (c - R * .55, c + R * .38, c + R * .55, c + R * .93), 0, 75))
        d = ImageDraw.Draw(img)
        d.ellipse((c - R, c - R, c + R, c + R), outline=(255, 255, 255, 220),
                  width=k(2))
        u = R * 0.5
        ombre = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        icone(ImageDraw.Draw(ombre), ico, c, c + k(1.6), u, (0, 40, 90, 120))
        img.alpha_composite(ombre.filter(ImageFilter.GaussianBlur(k(1.2))))
        icone(ImageDraw.Draw(img), ico, c, c, u, (255, 255, 255, 255))
        if survol:
            hv = Image.new("RGBA", (S, S), (0, 0, 0, 0))
            ImageDraw.Draw(hv).ellipse((c - R, c - R, c + R, c + R),
                                       fill=(255, 255, 255, 52))
            img.alpha_composite(hv)
        r = img.resize((self.p(80), self.p(80)), Image.LANCZOS)
        self.cache[cle] = r
        return r

    def bouton(self, ico, actif, survol):
        cle = ("btn", ico, actif, survol)
        if cle in self.cache:
            return self.cache[cle]
        k, th = self.k, self.th
        S = k(26)
        if actif:
            img = self.corps_rond(S, th["orb_haut"], th["orb_bas"])
        else:
            img = self.corps_rond(S, (255, 255, 255), (190, 225, 255), 120, 45)
        R = S / 2 - k(1.5)
        c = S / 2
        img.alpha_composite(self.gloss(
            S, (c - R * .72, c - R * .96, c + R * .72, c - R * .05), 150, 15))
        d = ImageDraw.Draw(img)
        d.ellipse((c - R, c - R, c + R, c + R), outline=(255, 255, 255, 200),
                  width=max(1, k(1.3)))
        u = R * 0.42
        ombre = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        icone(ImageDraw.Draw(ombre), ico, c, c + k(.8), u, (0, 40, 90, 110))
        img.alpha_composite(ombre.filter(ImageFilter.GaussianBlur(k(.7))))
        icone(ImageDraw.Draw(img), ico, c, c, u, (255, 255, 255, 255))
        if survol:
            hv = Image.new("RGBA", (S, S), (0, 0, 0, 0))
            ImageDraw.Draw(hv).ellipse((c - R, c - R, c + R, c + R),
                                       fill=(255, 255, 255, 60))
            img.alpha_composite(hv)
        r = img.resize((self.p(26), self.p(26)), Image.LANCZOS)
        self.cache[cle] = r
        return r

    def barre(self, largeur, frac, gros):
        frac = max(0.0, min(1.0, frac))
        cle = ("barre", largeur, gros, int(frac * self.p(largeur)))
        if cle in self.cache:
            return self.cache[cle]
        k, th = self.k, self.th
        w2, h2 = k(largeur), k(12)
        img = Image.new("RGBA", (w2, h2), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        y0, y1 = (k(2.5), k(9.5)) if gros else (k(4.3), k(7.7))
        r = (y1 - y0) // 2
        d.rounded_rectangle((0, y0, w2 - 1, y1), r, fill=(0, 30, 70, 95),
                            outline=(255, 255, 255, 120), width=max(1, k(1)))
        rk = k(5.5) if gros else k(4.5)
        fx = rk + frac * (w2 - 2 * rk)
        if fx > r:
            fill = Image.new("RGBA", (w2, h2), (0, 0, 0, 0))
            fd = ImageDraw.Draw(fill)
            for y in range(y0, y1 + 1):
                t = (y - y0) / max(1, y1 - y0)
                fd.line((0, y, w2, y), fill=mix(th["acc_haut"], th["acc_bas"],
                                                t) + (255,))
            m = Image.new("L", (w2, h2), 0)
            ImageDraw.Draw(m).rounded_rectangle((0, y0, int(fx), y1), r,
                                                fill=255)
            fill.putalpha(ImageChops.multiply(fill.getchannel("A"), m))
            img.alpha_composite(fill)
            d = ImageDraw.Draw(img)
        cy = h2 / 2
        d.ellipse((fx - rk, cy - rk, fx + rk, cy + rk),
                  fill=(255, 255, 255, 240), outline=mix(
                      th["acc_bas"], (0, 0, 0), .15) + (200,),
                  width=max(1, k(1)))
        d.ellipse((fx - rk * .6, cy - rk * .75, fx + rk * .6, cy - rk * .05),
                  fill=(255, 255, 255, 255))
        res = img.resize((self.p(largeur), self.p(12)), Image.LANCZOS)
        if len(self.cache) > 400:
            self.cache.clear()
        self.cache[cle] = res
        return res

    def visu(self, niveaux):
        k, th = self.k, self.th
        w2, h2 = k(214), k(28)
        img = Image.new("RGBA", (w2, h2), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        bw = k(8)
        gap = (w2 - NB_BARRES * bw) / (NB_BARRES - 1)
        for i, lv in enumerate(niveaux):
            x = int(i * (bw + gap))
            hh = max(k(3), int(lv * h2))
            d.rounded_rectangle((x, h2 - hh, x + bw, h2), k(3),
                                fill=th["acc_bas"] + (215,))
            d.rounded_rectangle((x, h2 - hh, x + bw, h2 - int(hh * .45)),
                                k(3), fill=th["acc_haut"] + (235,))
        return img.resize((self.p(214), self.p(28)), Image.LANCZOS)

    def texte(self, s, taille, gras, larg, couleur=(255, 255, 255)):
        cle = ("txt", s, taille, gras, larg, couleur)
        if cle in self.cache:
            return self.cache[cle]
        police = charger_police(self.p(taille), gras)
        maxpx = self.p(larg)
        if police.getlength(s) > maxpx:
            while s and police.getlength(s + "…") > maxpx:
                s = s[:-1]
            s += "…"
        w = int(police.getlength(s or " ")) + 6
        h = int(self.p(taille) * 1.5) + 4
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((3, 3), s, font=police, fill=(0, 35, 85, 150))
        d.text((2, 2), s, font=police, fill=couleur + (255,))
        if len(self.cache) > 400:
            self.cache.clear()
        self.cache[cle] = img
        return img

    # --- assemblage d'une image
    def composer(self, e):
        E, M = self.E, MARGE
        img = self.skin.copy()
        sv = e["survol"]

        def centre(s, cx, cy):
            img.alpha_composite(s, (int(round((M + cx) * E - s.width / 2)),
                                    int(round((M + cy) * E - s.height / 2))))

        def coin(s, x, y):
            img.alpha_composite(s, (int(round((M + x) * E)),
                                    int(round((M + y) * E))))

        centre(self.orbe("pause" if e["etat"] == "lecture" else "play",
                         sv == "orbe"), 62, 66)
        centre(self.bouton("prev", False, sv == "prec"), 34, 128)
        centre(self.bouton("next", False, sv == "suiv"), 90, 128)
        son = "muet" if (e["muet"] or e["volume"] == 0) else "son"
        centre(self.bouton(son, False, sv == "muet"), 128, 130)
        centre(self.bouton("shuffle", e["shuffle"], sv == "shuffle"), 274, 130)
        centre(self.bouton("repeat1" if e["repeter"] == "un" else "repeat",
                           e["repeter"] != "non", sv == "repeat"), 306, 130)

        coin(self.texte(e["titre"] or "Aero Musique", 15, True, 214), 109, 8)
        coin(self.texte(e["sous"], 10.5, False, 214, (232, 247, 255)), 109, 34)
        if e["visu"] is not None:
            coin(self.visu(e["visu"]), 112, 55)
        coin(self.barre(214, e["frac"], True), 112, 88)
        coin(self.texte(fmt(e["pos"]), 9.5, False, 60), 109, 101)
        t = self.texte(fmt(e["dur"]), 9.5, False, 60)
        coin(t, 329 - t.width / E, 101)
        vol = 0 if e["muet"] else e["volume"] / 100
        coin(self.barre(102, vol, False), 146, 124)
        return img


# --------------------------------------------- fenêtre à transparence réelle ---

class FenetreAero:
    """Fenêtre sans bordure dont chaque pixel a sa propre transparence
    (UpdateLayeredWindow) : c'est ce qui donne le vrai effet verre."""

    def __init__(self, app):
        self.app = app
        self.root = app.root
        self.survol = None
        self.apercu = None
        self.z = None
        self.bouge = False
        self.depart = (0, 0, 0, 0)
        self.signature = None
        self.dib = None
        self.rendu = None
        self.x = self.y = 0

        self.top = tk.Toplevel(self.root)
        self.top.overrideredirect(True)
        self.top.geometry("+-6000+-6000")       # caché pendant la création
        self.top.update()
        u, g = api()
        inner = self.top.winfo_id()
        self.hwnd = u.GetParent(inner) or inner
        ex = u.GetWindowLongW(self.hwnd, -20)
        u.SetWindowLongW(self.hwnd, -20, ex | 0x80000 | 0x80)  # LAYERED|TOOL

        t = self.top
        t.bind("<ButtonPress-1>", self.appui)
        t.bind("<B1-Motion>", self.glisse)
        t.bind("<ButtonRelease-1>", self.relache)
        t.bind("<ButtonPress-3>", self.clic_droit)
        t.bind("<Motion>", self.survole)
        t.bind("<Leave>", lambda e: self.maj_survol(None))
        t.bind("<Enter>", lambda e: self.appliquer_zordre())
        t.bind("<MouseWheel>", self.molette)
        self.reconstruire()

    # --- création / reconstruction
    def reconstruire(self):
        cfg = self.app.cfg
        self.rendu = Rendu(cfg["theme"], cfg["echelle"] / 100.0)
        self.liberer_dib()
        self.creer_dib(self.rendu.W, self.rendu.H)
        sw, sh = taille_ecran()
        if cfg["pos_x"] is None:
            cfg["pos_x"] = sw - self.rendu.W - 30
            cfg["pos_y"] = 50
        self.x = min(max(cfg["pos_x"], -self.rendu.W + 80), sw - 80)
        self.y = min(max(cfg["pos_y"], 0), sh - 80)
        self.signature = None
        self.rendre(force=True)
        self.appliquer_zordre()

    def creer_dib(self, w, h):
        u, g = api()

        class BMI(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                        ("biHeight", ctypes.c_long),
                        ("biPlanes", wintypes.WORD),
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

    # --- dessin
    def rendre(self, force=False):
        e = self.app.etat_widget()
        e["survol"] = self.survol
        if self.apercu is not None:
            e["frac"] = self.apercu
        sig = (e["etat"], e["titre"], e["sous"], int(e["pos"] // 1000),
               int(e["frac"] * 400), e["volume"], e["muet"], e["shuffle"],
               e["repeter"], e["survol"],
               tuple(int(v * 20) for v in e["visu"]) if e["visu"] else None)
        if sig == self.signature and not force:
            return
        self.signature = sig
        self.ecrire(self.rendu.composer(e))

    def ecrire(self, img):
        u, g = api()
        r, gr, b, a = img.convert("RGBa").split()
        data = Image.merge("RGBA", (b, gr, r, a)).tobytes()
        ctypes.memmove(self.bits, data, len(data))

        class PT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class BL(ctypes.Structure):
            _fields_ = [("Op", ctypes.c_ubyte), ("Fl", ctypes.c_ubyte),
                        ("Alpha", ctypes.c_ubyte), ("Fmt", ctypes.c_ubyte)]

        pt = PT(self.x, self.y)
        sz = PT(self.dib[0], self.dib[1])
        src = PT(0, 0)
        op = int(max(30, min(100, self.app.cfg["opacite"])) * 2.55)
        bl = BL(0, 0, op, 1)                    # AC_SRC_ALPHA
        u.UpdateLayeredWindow(self.hwnd, None, ctypes.byref(pt),
                              ctypes.byref(sz), self.hdc, ctypes.byref(src),
                              0, ctypes.byref(bl), 2)

    def deplacer(self):
        u, _ = api()
        u.SetWindowPos(self.hwnd, None, self.x, self.y, 0, 0,
                       0x1 | 0x4 | 0x10)        # NOSIZE|NOZORDER|NOACTIVATE

    def appliquer_zordre(self):
        try:
            u, _ = api()
            flags = 0x1 | 0x2 | 0x10            # NOSIZE|NOMOVE|NOACTIVATE
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

    # --- souris
    def hit(self, ex, ey):
        bx = ex / self.rendu.E - MARGE
        by = ey / self.rendu.E - MARGE
        for ident, forme, x, y, a, b in ZONES:
            if forme == "c":
                if (bx - x) ** 2 + (by - y) ** 2 <= a * a:
                    return ident
            elif x <= bx <= x + a and y <= by <= y + b:
                return ident
        return None

    def maj_survol(self, z):
        if z != self.survol:
            self.survol = z
            self.rendre()

    def survole(self, e):
        self.maj_survol(self.hit(e.x, e.y))

    def curseur(self, z, ex, final):
        bx = ex / self.rendu.E - MARGE
        if z == "barre":
            f = (bx - 112 - 5.5) / (214 - 11)
            self.apercu = max(0.0, min(1.0, f))
            self.rendre(force=True)
        else:
            f = (bx - 146 - 4.5) / (102 - 9)
            self.app.set_volume(round(max(0.0, min(1.0, f)) * 100))

    def appui(self, e):
        self.z = self.hit(e.x, e.y)
        self.depart = (e.x_root, e.y_root, self.x, self.y)
        self.bouge = False
        if self.z in ("barre", "volume"):
            self.curseur(self.z, e.x, False)

    def glisse(self, e):
        if self.z in ("barre", "volume"):
            self.curseur(self.z, e.x, False)
            return
        dx, dy = e.x_root - self.depart[0], e.y_root - self.depart[1]
        if not self.bouge and abs(dx) + abs(dy) < 4:
            return
        self.bouge = True
        if self.app.cfg["verrouille"]:
            return
        self.x, self.y = self.depart[2] + dx, self.depart[3] + dy
        self.deplacer()

    def relache(self, e):
        z = self.z
        if z == "barre":
            f, self.apercu = self.apercu, None
            if f is not None:
                self.app.seek_frac(f)
        elif z == "volume":
            pass
        elif not self.bouge and z:
            self.app.action_widget(z)
        elif self.bouge and not self.app.cfg["verrouille"]:
            self.app.cfg["pos_x"], self.app.cfg["pos_y"] = self.x, self.y
            self.app.sauver_plus_tard()
        self.z = None
        self.root.after(60, self.appliquer_zordre)

    def molette(self, e):
        self.app.set_volume(self.app.cfg["volume"] + (5 if e.delta > 0 else -5))

    def clic_droit(self, e):
        try:
            u, _ = api()
            u.SetForegroundWindow(self.hwnd)
        except Exception:
            pass
        self.app.menu_contextuel(e.x_root, e.y_root)

    def replacer(self):
        sw, sh = taille_ecran()
        self.x, self.y = sw - self.rendu.W - 30, 50
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
    return Rendu("Ciel Aero", 1.0).orbe("play", False).resize((64, 64))


class App:
    def __init__(self, root, arriere):
        self.root = root
        self.cfg = charger_config()
        self.lecteur = Lecteur()
        self.etat = "arret"                     # arret | lecture | pause
        self.titre = ""
        self.pos_ms = 0
        self.dur_ms = 0
        self.historique = []
        self.sac = []
        self.fondu = None
        self.debut_lecture = 0.0
        self.derniere_sauv = 0.0
        self.tache_tick = None
        self.tache_sauv = None
        self.tache_echelle = None
        self.niv = [0.0] * NB_BARRES
        self.widget = None
        self.tray = None
        self.maj_vars = False
        self.prevenu = False

        n = len(self.cfg["playlist"])
        self.index = min(max(int(self.cfg["index"]), 0), max(0, n - 1))
        if n:
            self.titre = self.nom_piste(self.cfg["playlist"][self.index])
        self.pos_ms = int(self.cfg["position_ms"]) if self.cfg["reprendre"] else 0

        os.makedirs(DATA, exist_ok=True)
        regler_demarrage(self.cfg["demarrage"])

        root.title("Aero Musique – Réglages")
        root.geometry("540x600")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.cacher_reglages)
        self.construire_reglages()
        self.creer_tray()
        if self.cfg["widget_visible"]:
            self.montrer_widget()

        if self.cfg["lire_demarrage"] and n:
            ms = max(500, int(float(self.cfg["delai"]) * 1000))
            root.after(ms, self.demarrage_auto)
        if arriere and n:
            root.withdraw()

    # ======================================================== lecture ======
    @staticmethod
    def nom_piste(chemin):
        return os.path.splitext(os.path.basename(chemin))[0]

    def jouer_index(self, idx, depuis=0, fondu=0):
        pl = self.cfg["playlist"]
        n = len(pl)
        if not n:
            return False
        essais = 0
        while essais < n:
            chemin = pl[idx % n]
            if os.path.isfile(chemin) and self.lecteur.ouvrir(chemin):
                break
            essais += 1
            idx += 1
        else:
            self.etat = "arret"
            self.rafraichir()
            return False
        self.index = idx % n
        self.titre = self.nom_piste(pl[self.index])
        self.dur_ms = self.lecteur.duree
        self.pos_ms = depuis
        self.fondu = (time.monotonic(), fondu) if fondu > 0 else None
        self.appliquer_volume()
        self.lecteur.jouer(depuis if depuis > 1000 else 0)
        self.etat = "lecture"
        self.debut_lecture = time.monotonic()
        self.cfg["index"] = self.index
        self.sauver_plus_tard()
        self.maj_ui()
        self.planifier_tick()
        return True

    def demarrage_auto(self):
        if self.etat != "arret" or not self.cfg["playlist"]:
            return
        if self.cfg["vol_demarrage_actif"]:
            self.cfg["volume"] = int(self.cfg["vol_demarrage"])
            self.sync_var("v_volume", self.cfg["volume"])
        depuis = self.pos_ms if self.cfg["reprendre"] else 0
        idx = self.index if self.cfg["reprendre"] else 0
        if not self.cfg["reprendre"] and self.cfg["aleatoire"]:
            idx = random.randrange(len(self.cfg["playlist"]))
        self.jouer_index(idx, depuis=depuis,
                         fondu=float(self.cfg["fondu_entree"]))

    def basculer(self):
        if not self.cfg["playlist"]:
            self.ajouter_fichiers()
            return
        if self.etat == "lecture":
            self.pause()
        elif self.etat == "pause":
            self.reprendre()
        else:
            self.jouer_index(self.index)

    def pause(self):
        self.pos_ms = self.lecteur.position()
        self.lecteur.pause()
        self.etat = "pause"
        self.sauver_etat()
        self.maj_ui()

    def reprendre(self):
        self.lecteur.reprendre()
        self.etat = "lecture"
        self.debut_lecture = time.monotonic()
        self.maj_ui()
        self.planifier_tick()

    def arreter_fin(self):
        self.lecteur.fermer()
        self.etat = "arret"
        self.pos_ms = 0
        self.sauver_etat()
        self.maj_ui()

    def prochain_aleatoire(self):
        n = len(self.cfg["playlist"])
        self.sac = [i for i in self.sac if i < n and i != self.index]
        if not self.sac:
            self.sac = [i for i in range(n) if i != self.index]
            random.shuffle(self.sac)
        return self.sac.pop()

    def suivant(self, auto=False):
        n = len(self.cfg["playlist"])
        if not n:
            return
        if auto and self.cfg["repeter"] == "un":
            self.jouer_index(self.index)
            return
        self.historique = (self.historique + [self.index])[-100:]
        if self.cfg["aleatoire"] and n > 1:
            idx = self.prochain_aleatoire()
        else:
            idx = self.index + 1
            if idx >= n:
                if auto and self.cfg["repeter"] != "tout":
                    self.arreter_fin()
                    return
                idx = 0
        self.jouer_index(idx)

    def precedent(self):
        n = len(self.cfg["playlist"])
        if not n:
            return
        if self.etat in ("lecture", "pause") and self.lecteur.position() > 3000:
            self.seek_ms(0)
            return
        idx = self.historique.pop() if self.historique else (self.index - 1) % n
        self.jouer_index(idx)

    def seek_ms(self, ms):
        if self.etat == "arret":
            return
        self.lecteur.seek(ms, self.etat == "lecture")
        self.pos_ms = ms
        self.debut_lecture = time.monotonic()
        self.rafraichir()

    def seek_frac(self, f):
        if self.dur_ms > 0:
            self.seek_ms(int(f * self.dur_ms))

    # ----------------------------------------------------------- volume ---
    def facteur_fondu(self):
        if not self.fondu:
            return 1.0
        t0, d = self.fondu
        f = (time.monotonic() - t0) / max(0.1, d)
        if f >= 1:
            self.fondu = None
            return 1.0
        return max(0.0, f)

    def appliquer_volume(self):
        v = 0 if self.cfg["muet"] else self.cfg["volume"] * self.facteur_fondu()
        self.lecteur.set_volume(v)

    def set_volume(self, v):
        v = max(0, min(100, int(v)))
        if v == self.cfg["volume"] and not self.cfg["muet"]:
            return
        self.cfg["volume"] = v
        if v > 0:
            self.cfg["muet"] = False
        self.fondu = None
        self.appliquer_volume()
        self.sync_var("v_volume", v)
        self.sync_var("v_muet", self.cfg["muet"])
        self.sauver_plus_tard()
        self.rafraichir()

    def toggle_muet(self):
        self.cfg["muet"] = not self.cfg["muet"]
        self.appliquer_volume()
        self.sync_var("v_muet", self.cfg["muet"])
        self.sauver_plus_tard()
        self.rafraichir()

    def toggle_aleatoire(self):
        self.cfg["aleatoire"] = not self.cfg["aleatoire"]
        self.sync_var("v_aleatoire", self.cfg["aleatoire"])
        self.sauver_plus_tard()
        self.rafraichir()

    def cycle_repeter(self):
        ordre = ["non", "tout", "un"]
        self.cfg["repeter"] = ordre[(ordre.index(self.cfg["repeter"]) + 1) % 3]
        self.sync_var("v_repeter", REPETER_INV[self.cfg["repeter"]])
        self.sauver_plus_tard()
        self.rafraichir()

    def action_widget(self, z):
        {"orbe": self.basculer, "prec": self.precedent,
         "suiv": lambda: self.suivant(False), "muet": self.toggle_muet,
         "shuffle": self.toggle_aleatoire,
         "repeat": self.cycle_repeter}.get(z, lambda: None)()

    # ------------------------------------------------------ boucle douce ---
    def planifier_tick(self):
        if self.tache_tick:
            self.root.after_cancel(self.tache_tick)
            self.tache_tick = None
        if self.etat != "lecture":
            return
        visible = self.widget is not None
        if self.fondu:
            ms = 100
        elif visible and self.cfg["visualiseur"]:
            ms = 140
        elif visible:
            ms = 500
        else:
            ms = 1000
        self.tache_tick = self.root.after(ms, self.tick)

    def tick(self):
        self.tache_tick = None
        if self.etat != "lecture":
            return
        self.pos_ms = self.lecteur.position()
        if self.fondu:
            self.appliquer_volume()
        mode = self.lecteur.mode()
        if mode == "stopped" and time.monotonic() - self.debut_lecture > 1.5:
            self.suivant(auto=True)
            return
        if self.cfg["visualiseur"]:
            self.maj_visu()
        self.rafraichir()
        if time.monotonic() - self.derniere_sauv > 20:
            self.sauver_etat()
        self.planifier_tick()

    def maj_visu(self):
        t = time.monotonic()
        v = max(0.0, 1.0 - 0.0)
        for i in range(NB_BARRES):
            cible = (0.5 + 0.5 * math.sin(t * 3.1 + i * 0.7)
                     * math.sin(t * 1.3 + i * 0.31)) * random.uniform(.55, 1)
            self.niv[i] += (cible * v - self.niv[i]) * 0.55

    # -------------------------------------------------------- widget -----
    def etat_widget(self):
        pl = self.cfg["playlist"]
        n = len(pl)
        if not n:
            sous = "Clic droit › Choisir des fichiers"
        elif self.etat == "lecture":
            sous = f"Lecture · {self.index + 1}/{n}"
        elif self.etat == "pause":
            sous = f"En pause · {self.index + 1}/{n}"
        else:
            sous = f"Prêt · {self.index + 1}/{n}"
        dur = self.dur_ms
        frac = (self.pos_ms / dur) if dur > 0 else 0.0
        if self.cfg["visualiseur"]:
            visu = list(self.niv) if self.etat == "lecture" else [0.0] * NB_BARRES
        else:
            visu = None
        return dict(etat=self.etat, titre=self.titre, sous=sous,
                    pos=self.pos_ms, dur=dur, frac=frac,
                    volume=self.cfg["volume"], muet=self.cfg["muet"],
                    shuffle=self.cfg["aleatoire"], repeter=self.cfg["repeter"],
                    visu=visu)

    def rafraichir(self):
        if self.widget:
            try:
                self.widget.rendre()
            except Exception:
                pass

    def montrer_widget(self):
        if self.widget is None:
            self.widget = FenetreAero(self)
        self.cfg["widget_visible"] = True
        self.sync_var("v_widget", True)
        self.sauver_plus_tard()
        self.planifier_tick()

    def masquer_widget(self):
        if self.widget:
            self.widget.detruire()
            self.widget = None
        self.cfg["widget_visible"] = False
        self.sync_var("v_widget", False)
        self.sauver_plus_tard()
        self.planifier_tick()

    def reconstruire_widget(self):
        if self.widget:
            self.widget.reconstruire()

    def maj_ui(self):
        self.rafraichir()
        if self.tray:
            try:
                self.tray.update_menu()
            except Exception:
                pass
        if hasattr(self, "lbl_titre"):
            self.lbl_titre.config(text=self.titre or "—")
            self.btn_play.config(
                text="⏸  Pause" if self.etat == "lecture" else "▶  Lecture")
            self.maj_liste()
        self.planifier_tick()

    # ---------------------------------------------------- menu contextuel ---
    def menu_contextuel(self, x, y):
        parent = self.widget.top if self.widget else self.root
        m = tk.Menu(parent, tearoff=0)
        m.add_command(label="⏸  Pause" if self.etat == "lecture"
                      else "▶  Lecture", command=self.basculer)
        m.add_command(label="⏮  Précédent", command=self.precedent)
        m.add_command(label="⏭  Suivant", command=lambda: self.suivant(False))
        m.add_separator()
        m.add_command(label="🔊  Réactiver le son" if self.cfg["muet"]
                      else "🔇  Couper le son", command=self.toggle_muet)
        m.add_command(label="➕  Volume +",
                      command=lambda: self.set_volume(self.cfg["volume"] + 10))
        m.add_command(label="➖  Volume −",
                      command=lambda: self.set_volume(self.cfg["volume"] - 10))
        m.add_separator()
        m.add_checkbutton(label="Lecture aléatoire",
                          command=self.toggle_aleatoire,
                          variable=tk.BooleanVar(value=self.cfg["aleatoire"]))
        sub = tk.Menu(m, tearoff=0)
        for lab, val in REPETER.items():
            sub.add_command(
                label=("● " if self.cfg["repeter"] == val else "    ") + lab,
                command=lambda v=val: self.fixer_repeter(v))
        m.add_cascade(label="Répéter", menu=sub)
        m.add_separator()
        m.add_command(label="📂  Choisir des fichiers…",
                      command=self.ajouter_fichiers)
        m.add_command(label="⚙  Réglages…", command=self.montrer_reglages)
        m.add_command(label="🙈  Masquer le widget",
                      command=self.masquer_widget)
        m.add_command(label="✖  Quitter", command=self.quitter)
        try:
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    def fixer_repeter(self, v):
        self.cfg["repeter"] = v
        self.sync_var("v_repeter", REPETER_INV[v])
        self.sauver_plus_tard()
        self.rafraichir()

    # ========================================================= réglages ====
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

    def sauver_etat(self):
        self.derniere_sauv = time.monotonic()
        if self.etat in ("lecture", "pause"):
            if self.etat == "lecture":
                self.pos_ms = self.lecteur.position()
            self.cfg["position_ms"] = self.pos_ms
        self.cfg["index"] = self.index
        sauver_config(self.cfg)

    def construire_reglages(self):
        c = self.cfg
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        pages = {}
        for cle, txt in (("lecture", " Lecture "), ("widget", " Widget "),
                         ("demarrage", " Démarrage "),
                         ("desinstaller", " Désinstaller ")):
            f = ttk.Frame(nb, padding=14)
            nb.add(f, text=txt)
            pages[cle] = f

        # ---------------- Lecture
        p = pages["lecture"]
        cadre = ttk.Frame(p)
        cadre.pack(fill="both", expand=True)
        self.liste = tk.Listbox(cadre, height=10, activestyle="none")
        sb = ttk.Scrollbar(cadre, command=self.liste.yview)
        self.liste.config(yscrollcommand=sb.set)
        self.liste.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.liste.bind("<Double-Button-1>", self.double_clic_liste)

        b = ttk.Frame(p)
        b.pack(fill="x", pady=6)
        for txt, cmd in (("➕ Fichiers…", self.ajouter_fichiers),
                         ("📁 Dossier…", self.ajouter_dossier),
                         ("➖ Retirer", self.retirer_selection),
                         ("🗑 Vider", self.vider_liste)):
            ttk.Button(b, text=txt, command=cmd).pack(side="left", expand=True,
                                                      fill="x", padx=2)

        self.lbl_titre = ttk.Label(p, text=self.titre or "—",
                                   font=("Segoe UI", 10, "bold"),
                                   wraplength=480)
        self.lbl_titre.pack(anchor="w", pady=(6, 2))
        t = ttk.Frame(p)
        t.pack(fill="x")
        ttk.Button(t, text="⏮", width=5,
                   command=self.precedent).pack(side="left", padx=2)
        self.btn_play = ttk.Button(t, text="▶  Lecture", command=self.basculer)
        self.btn_play.pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(t, text="⏭", width=5,
                   command=lambda: self.suivant(False)).pack(side="left", padx=2)

        self.v_aleatoire = tk.BooleanVar(value=c["aleatoire"])
        self.v_repeter = tk.StringVar(value=REPETER_INV.get(c["repeter"], "Tout"))
        self.v_volume = tk.IntVar(value=c["volume"])
        self.v_muet = tk.BooleanVar(value=c["muet"])
        l = ttk.Frame(p)
        l.pack(fill="x", pady=(10, 2))
        ttk.Checkbutton(l, text="Lecture aléatoire",
                        variable=self.v_aleatoire).pack(side="left")
        ttk.Label(l, text="    Répéter :").pack(side="left")
        ttk.Combobox(l, textvariable=self.v_repeter, state="readonly", width=9,
                     values=list(REPETER)).pack(side="left", padx=4)
        l = ttk.Frame(p)
        l.pack(fill="x", pady=4)
        ttk.Label(l, text="Volume").pack(side="left")
        ttk.Scale(l, from_=0, to=100, variable=self.v_volume,
                  command=lambda v: self.set_volume(float(v))).pack(
            side="left", fill="x", expand=True, padx=8)
        ttk.Checkbutton(l, text="Muet", variable=self.v_muet,
                        command=self.toggle_muet_depuis_ui).pack(side="left")
        self.lier(self.v_aleatoire, "aleatoire", apres=self.rafraichir)
        self.lier(self.v_repeter, "repeter", lambda x: REPETER[x],
                  self.rafraichir)

        # ---------------- Widget
        p = pages["widget"]
        self.v_widget = tk.BooleanVar(value=c["widget_visible"])
        self.v_theme = tk.StringVar(value=c["theme"])
        self.v_echelle = tk.IntVar(value=c["echelle"])
        self.v_opacite = tk.IntVar(value=c["opacite"])
        self.v_zordre = tk.StringVar(value=ZORDRES_INV.get(c["zordre"]))
        self.v_verrou = tk.BooleanVar(value=c["verrouille"])
        self.v_visu = tk.BooleanVar(value=c["visualiseur"])

        ttk.Checkbutton(p, text="Afficher le widget sur le bureau",
                        variable=self.v_widget,
                        command=self.toggle_widget_ui).pack(anchor="w")
        g = ttk.Frame(p)
        g.pack(fill="x", pady=10)
        g.columnconfigure(1, weight=1)
        ttk.Label(g, text="Thème").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Combobox(g, textvariable=self.v_theme, state="readonly",
                     values=list(THEMES)).grid(row=0, column=1, sticky="ew",
                                               padx=8)
        ttk.Label(g, text="Taille (%)").grid(row=1, column=0, sticky="w",
                                             pady=4)
        ttk.Scale(g, from_=60, to=200, variable=self.v_echelle,
                  command=lambda v: self.v_echelle.set(int(float(v)))
                  ).grid(row=1, column=1, sticky="ew", padx=8)
        ttk.Label(g, textvariable=self.v_echelle, width=4).grid(row=1,
                                                                column=2)
        ttk.Label(g, text="Opacité (%)").grid(row=2, column=0, sticky="w",
                                              pady=4)
        ttk.Scale(g, from_=30, to=100, variable=self.v_opacite,
                  command=lambda v: self.v_opacite.set(int(float(v)))
                  ).grid(row=2, column=1, sticky="ew", padx=8)
        ttk.Label(g, textvariable=self.v_opacite, width=4).grid(row=2,
                                                                column=2)
        ttk.Label(g, text="Position").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Combobox(g, textvariable=self.v_zordre, state="readonly",
                     values=list(ZORDRES)).grid(row=3, column=1, sticky="ew",
                                                padx=8)
        ttk.Checkbutton(p, text="Verrouiller la position (ne plus pouvoir "
                        "le déplacer)", variable=self.v_verrou).pack(
            anchor="w", pady=2)
        ttk.Checkbutton(p, text="Visualiseur animé (décoratif)",
                        variable=self.v_visu).pack(anchor="w", pady=2)
        ttk.Button(p, text="↖  Replacer le widget en haut à droite",
                   command=self.replacer_widget).pack(anchor="w", pady=12)
        ttk.Label(p, foreground="#666", wraplength=480, text=(
            "Astuce : clic droit sur le widget pour le menu (pause, suivant, "
            "volume…), molette de la souris pour le volume, clic sur la "
            "barre pour avancer dans le morceau.")).pack(anchor="w")
        self.lier(self.v_theme, "theme", apres=self.reconstruire_widget)
        self.lier(self.v_echelle, "echelle", int, self.reconstruire_tard)
        self.lier(self.v_opacite, "opacite", int,
                  lambda: self.widget and self.widget.rendre(force=True))
        self.lier(self.v_zordre, "zordre", lambda x: ZORDRES[x],
                  lambda: self.widget and self.widget.appliquer_zordre())
        self.lier(self.v_verrou, "verrouille")
        self.lier(self.v_visu, "visualiseur", apres=self.planifier_tick)

        # ---------------- Démarrage
        p = pages["demarrage"]
        self.v_demarrage = tk.BooleanVar(value=c["demarrage"])
        self.v_lire = tk.BooleanVar(value=c["lire_demarrage"])
        self.v_delai = tk.StringVar(value=str(c["delai"]))
        self.v_vda = tk.BooleanVar(value=c["vol_demarrage_actif"])
        self.v_vd = tk.IntVar(value=c["vol_demarrage"])
        self.v_fondu = tk.StringVar(value=str(c["fondu_entree"]))
        self.v_reprendre = tk.BooleanVar(value=c["reprendre"])
        ttk.Checkbutton(p, text="Lancer Aero Musique avec Windows "
                        "(en arrière-plan)", variable=self.v_demarrage,
                        command=self.maj_demarrage).pack(anchor="w", pady=2)
        ttk.Checkbutton(p, text="Lancer la musique automatiquement au "
                        "démarrage", variable=self.v_lire).pack(anchor="w",
                                                                pady=2)
        g = ttk.Frame(p)
        g.pack(fill="x", padx=20, pady=6)
        ttk.Label(g, text="Attendre").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(g, from_=0, to=300, width=5,
                    textvariable=self.v_delai).grid(row=0, column=1, padx=6)
        ttk.Label(g, text="secondes avant de lancer le son").grid(
            row=0, column=2, sticky="w")
        ttk.Label(g, text="Fondu d'entrée").grid(row=1, column=0, sticky="w",
                                                 pady=8)
        ttk.Spinbox(g, from_=0, to=60, width=5,
                    textvariable=self.v_fondu).grid(row=1, column=1, padx=6)
        ttk.Label(g, text="secondes (le son monte doucement)").grid(
            row=1, column=2, sticky="w")
        ttk.Checkbutton(p, text="Imposer un volume au démarrage",
                        variable=self.v_vda).pack(anchor="w", pady=(10, 0))
        l = ttk.Frame(p)
        l.pack(fill="x", padx=20, pady=4)
        ttk.Scale(l, from_=0, to=100, variable=self.v_vd,
                  command=lambda v: self.v_vd.set(int(float(v)))).pack(
            side="left", fill="x", expand=True)
        ttk.Label(l, textvariable=self.v_vd, width=4).pack(side="left")
        ttk.Checkbutton(p, text="Reprendre le titre et l'endroit où je "
                        "m'étais arrêté", variable=self.v_reprendre).pack(
            anchor="w", pady=10)
        ttk.Label(p, foreground="#666", wraplength=480, text=(
            "Tous les réglages sont enregistrés automatiquement.")).pack(
            anchor="w", pady=(10, 0))
        self.lier(self.v_lire, "lire_demarrage")
        self.lier(self.v_delai, "delai", lambda x: max(0, float(x)))
        self.lier(self.v_vda, "vol_demarrage_actif")
        self.lier(self.v_vd, "vol_demarrage", int)
        self.lier(self.v_fondu, "fondu_entree", lambda x: max(0, float(x)))
        self.lier(self.v_reprendre, "reprendre")

        # ---------------- Désinstaller
        p = pages["desinstaller"]
        ttk.Label(p, wraplength=480, text=(
            "La désinstallation arrête la musique, retire le démarrage "
            "automatique et supprime l'application et ses réglages de cet "
            "ordinateur. Tes fichiers de musique ne sont pas touchés.")
                  ).pack(anchor="w", pady=10)
        ttk.Button(p, text="🗑  Désinstaller Aero Musique…",
                   command=self.desinstaller).pack(anchor="w", pady=10)

        self.maj_liste()

    # --- actions de l'interface
    def reconstruire_tard(self):
        if self.tache_echelle:
            self.root.after_cancel(self.tache_echelle)
        self.tache_echelle = self.root.after(300, self.reconstruire_widget)

    def toggle_widget_ui(self):
        if self.v_widget.get():
            self.montrer_widget()
        else:
            self.masquer_widget()

    def toggle_muet_depuis_ui(self):
        self.cfg["muet"] = self.v_muet.get()
        self.appliquer_volume()
        self.sauver_plus_tard()
        self.rafraichir()

    def replacer_widget(self):
        if not self.widget:
            self.montrer_widget()
        self.widget.replacer()

    def maj_demarrage(self):
        self.cfg["demarrage"] = self.v_demarrage.get()
        self.sauver_plus_tard()
        regler_demarrage(self.cfg["demarrage"])

    def maj_liste(self):
        if not hasattr(self, "liste"):
            return
        self.liste.delete(0, "end")
        for i, ch in enumerate(self.cfg["playlist"]):
            marque = "▶ " if (i == self.index and self.etat == "lecture") else "    "
            self.liste.insert("end", f"{marque}{os.path.basename(ch)}")
        if self.cfg["playlist"]:
            self.liste.itemconfig(min(self.index, self.liste.size() - 1),
                                  background="#d6ecff")

    def ajouter(self, chemins):
        pl = self.cfg["playlist"]
        deja = set(pl)
        nouveaux = [c for c in chemins if c not in deja]
        if not nouveaux:
            return
        vide = not pl
        pl.extend(nouveaux)
        if vide:
            self.index = 0
            self.titre = self.nom_piste(pl[0])
        self.sauver_plus_tard()
        self.maj_liste()
        self.rafraichir()
        if vide and self.etat == "arret":
            self.jouer_index(0)

    def ajouter_fichiers(self):
        self.montrer_reglages()
        ch = filedialog.askopenfilenames(
            title="Choisir des fichiers audio ou vidéo",
            filetypes=[("Audio / vidéo",
                        " ".join("*" + e for e in EXTENSIONS)),
                       ("Tous les fichiers", "*.*")])
        if ch:
            self.ajouter(list(ch))

    def ajouter_dossier(self):
        d = filedialog.askdirectory(title="Dossier de musique")
        if not d:
            return
        trouves = []
        for racine, _, fichiers in os.walk(d):
            for f in sorted(fichiers, key=str.lower):
                if f.lower().endswith(EXTENSIONS):
                    trouves.append(os.path.join(racine, f))
            if len(trouves) > 5000:
                break
        if not trouves:
            messagebox.showinfo("Aucun fichier",
                                "Aucun fichier audio trouvé dans ce dossier.")
            return
        self.ajouter(trouves)

    def retirer_selection(self):
        sel = list(self.liste.curselection())
        pl = self.cfg["playlist"]
        for i in reversed(sel):
            if i < len(pl):
                del pl[i]
                if i < self.index:
                    self.index -= 1
        self.index = min(self.index, max(0, len(pl) - 1))
        self.sauver_plus_tard()
        self.maj_liste()

    def vider_liste(self):
        if not self.cfg["playlist"]:
            return
        if not messagebox.askyesno("Vider", "Vider toute la liste de lecture ?"):
            return
        self.lecteur.fermer()
        self.etat = "arret"
        self.cfg["playlist"] = []
        self.index = 0
        self.titre = ""
        self.dur_ms = self.pos_ms = 0
        self.sauver_plus_tard()
        self.maj_ui()

    def double_clic_liste(self, e):
        sel = self.liste.curselection()
        if sel:
            self.historique = (self.historique + [self.index])[-100:]
            self.jouer_index(sel[0])

    # ================================================ arrière-plan / fin ====
    def creer_tray(self):
        if pystray is None:
            return
        menu = pystray.Menu(
            pystray.MenuItem(
                lambda i: "⏸ Pause" if self.etat == "lecture" else "▶ Lecture",
                lambda i, m: self.root.after(0, self.basculer), default=True),
            pystray.MenuItem("⏮ Précédent",
                             lambda i, m: self.root.after(0, self.precedent)),
            pystray.MenuItem("⏭ Suivant", lambda i, m: self.root.after(
                0, lambda: self.suivant(False))),
            pystray.MenuItem(lambda i: "🔊 Réactiver le son" if self.cfg["muet"]
                             else "🔇 Couper le son",
                             lambda i, m: self.root.after(0, self.toggle_muet)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda i: "Masquer le widget" if self.widget
                else "Afficher le widget",
                lambda i, m: self.root.after(0, self.toggle_widget_tray)),
            pystray.MenuItem("Réglages…", lambda i, m: self.root.after(
                0, self.montrer_reglages)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quitter", lambda i, m: self.root.after(
                0, self.quitter)))
        self.tray = pystray.Icon(NOM, icone_tray(), "Aero Musique", menu)
        self.tray.run_detached()

    def toggle_widget_tray(self):
        if self.widget:
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
                    self.tray.notify("La musique continue en arrière-plan. "
                                     "Clic droit sur l'icône pour quitter.",
                                     "Aero Musique")
                except Exception:
                    pass
        else:
            self.root.iconify()

    def quitter(self):
        try:
            self.sauver_etat()
            self.lecteur.fermer()
            if self.widget:
                self.widget.detruire()
            if self.tray:
                self.tray.stop()
        except Exception:
            pass
        self.root.destroy()

    def desinstaller(self):
        if not messagebox.askyesno(
                "Désinstaller",
                "Supprimer Aero Musique, ses réglages et le démarrage "
                "automatique ?", icon="warning"):
            return
        regler_demarrage(False)
        self.lecteur.fermer()
        if FROZEN:
            cmd = (f'ping 127.0.0.1 -n 4 >nul & del /f /q "{sys.executable}"'
                   f' & rmdir /s /q "{DATA}"')
            subprocess.Popen(f'cmd /s /c "{cmd}"', close_fds=True,
                             creationflags=0x08000000 | 0x00000008)
        else:
            shutil.rmtree(DATA, ignore_errors=True)
        messagebox.showinfo("Désinstallé", "Aero Musique a été désinstallé.")
        if self.tache_sauv:
            self.root.after_cancel(self.tache_sauv)
        try:
            if self.widget:
                self.widget.detruire()
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
    if not instance_unique():
        if not arriere:
            r = tk.Tk()
            r.withdraw()
            messagebox.showinfo(NOM, "Aero Musique tourne déjà.\nCherche son "
                                "icône près de l'horloge (flèche ^).")
        return
    basse_priorite()
    root = tk.Tk()
    App(root, arriere)
    root.mainloop()


if __name__ == "__main__":
    main()
