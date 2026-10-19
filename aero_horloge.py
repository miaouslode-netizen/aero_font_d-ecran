"""
Aero Horloge  (Windows)
-----------------------
Widget de bureau "heure + date" en verre style Frutiger Aero.

- 3 styles : numérique, analogique (cadran brillant), combiné
- 24 h / 12 h, secondes, date longue / courte / numérique, n° de semaine
- 5 thèmes, taille, opacité, position (dessus / bureau / normal)
- Arrière-plan (icône près de l'horloge), lancement avec Windows
- Ultra léger : une mise à jour par seconde (ou par minute sans secondes)
- Réglages sauvegardés, bouton de désinstallation
"""

import os
import sys
import json
import math
import time
import shutil
import ctypes
import subprocess
from datetime import datetime
from ctypes import wintypes

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except ImportError:                       # (tests hors Windows)
    tk = ttk = messagebox = None

from PIL import Image, ImageDraw, ImageFilter, ImageChops, ImageFont

try:
    import pystray
except ImportError:
    pystray = None

# ------------------------------------------------------------ constantes ---

NOM = "AeroHorloge"
DATA = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), NOM)
CONFIG = os.path.join(DATA, "config.json")
EXE_INSTALLE = os.path.join(DATA, NOM + ".exe")
FROZEN = getattr(sys, "frozen", False)
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

DEFAUT = dict(
    style="numerique", theme="Ciel Aero", h24=True, secondes=True,
    date_fmt="long", semaine=False, echelle=100, opacite=100,
    zordre="bureau", verrouille=False, widget_visible=True,
    pos_x=None, pos_y=None, demarrage=True)

STYLES = {"Numérique": "numerique", "Analogique": "analogique",
          "Combiné": "combine"}
STYLES_INV = {v: k for k, v in STYLES.items()}
FORMATS = {"Longue (lundi 19 octobre 2026)": "long",
           "Courte (lun. 19 oct. 2026)": "court",
           "Numérique (19/10/2026)": "num"}
FORMATS_INV = {v: k for k, v in FORMATS.items()}
ZORDRES = {"Toujours au-dessus": "dessus",
           "Sur le bureau (sous les fenêtres)": "bureau",
           "Normal": "normal"}
ZORDRES_INV = {v: k for k, v in ZORDRES.items()}

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi",
         "dimanche"]
JOURS_C = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]
MOIS_C = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août",
          "sept.", "oct.", "nov.", "déc."]

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

# taille du panneau (sans marge) et position du cadran (cx, cy, rayon)
MARGE = 14
PANNEAU = {"numerique": (300, 138), "analogique": (204, 244),
           "combine": (396, 172)}
CADRAN = {"analogique": (102, 108, 76), "combine": (94, 86, 66)}

POLICES = {
    "leger": ["segoeuil.ttf", "segoeuisl.ttf", "segoeui.ttf", "arial.ttf",
              "DejaVuSans.ttf"],
    "normal": ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"],
    "semi": ["seguisb.ttf", "segoeuib.ttf", "arialbd.ttf",
             "DejaVuSans-Bold.ttf"],
}
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


# ------------------------------------------------------------- Windows ---

_u = None
_g = None


def api():
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


# ----------------------------------------------------------- dessin (PIL) ---

def charger_police(genre, taille):
    dossiers = [os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts"),
                ""]
    taille = int(max(6, round(taille)))
    for n in POLICES[genre]:
        for d in dossiers:
            try:
                return ImageFont.truetype(os.path.join(d, n) if d else n,
                                          taille)
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


def formater_date(dt, fmt):
    j, m = dt.weekday(), dt.month - 1
    if fmt == "court":
        s = f"{JOURS_C[j]} {dt.day} {MOIS_C[m]} {dt.year}"
    elif fmt == "num":
        s = f"{dt.day:02d}/{dt.month:02d}/{dt.year}"
    else:
        s = f"{JOURS[j]} {dt.day} {MOIS[m]} {dt.year}"
    return s[:1].upper() + s[1:]


class Rendu:
    """Dessine le widget. Le fond (verre + cadran) est préparé une fois ;
    chaque seconde, seuls le texte et les aiguilles sont redessinés."""

    def __init__(self, style, theme, echelle):
        self.style = style if style in PANNEAU else "numerique"
        self.th = THEMES.get(theme, THEMES["Ciel Aero"])
        self.E = max(0.5, echelle)
        self.L, self.Hh = PANNEAU[self.style]
        self.W = int(round((self.L + 2 * MARGE) * self.E))
        self.H = int(round((self.Hh + 2 * MARGE) * self.E))
        self.K = 2.0 * self.W / (self.L + 2 * MARGE)
        self.cache = {}
        self.skin = self.creer_skin()

    def k(self, v):
        return int(round(v * self.K))

    def p(self, v):
        return int(round(v * self.E))

    # ------------------------------------------------------------ fond ---
    def creer_skin(self):
        k, th = self.k, self.th
        W2, H2 = self.W * 2, self.H * 2
        box = (k(MARGE), k(MARGE), k(MARGE + self.L), k(MARGE + self.Hh))
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
                    fill=mix(th["haut"], th["bas"], t) + (int(224 - 36 * t),))
        deg.putalpha(ImageChops.multiply(deg.getchannel("A"), masque))
        img.alpha_composite(deg)

        # bulles décoratives
        bul = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        bd = ImageDraw.Draw(bul)
        L, Hh = self.L, self.Hh
        for fx, fy, r in ((0.90, 0.22, 26), (0.78, 0.86, 15), (0.97, 0.66, 10),
                          (0.58, 0.07, 8), (0.06, 0.88, 14), (0.40, 0.95, 7)):
            cx, cy = MARGE + L * fx, MARGE + Hh * fy
            bd.ellipse((k(cx - r), k(cy - r), k(cx + r), k(cy + r)),
                       fill=(255, 255, 255, 32), outline=(255, 255, 255, 120),
                       width=max(1, k(1.4)))
            bd.ellipse((k(cx - r * .62), k(cy - r * .78), k(cx + r * .1),
                        k(cy - r * .2)), fill=(255, 255, 255, 105))
            bd.arc((k(cx - r * .8), k(cy - r * .8), k(cx + r * .8),
                    k(cy + r * .8)), 20, 100, fill=(255, 255, 255, 150),
                   width=max(1, k(1.2)))
        bul.putalpha(ImageChops.multiply(bul.getchannel("A"), masque))
        img.alpha_composite(bul)

        # cadran (styles analogique et combiné)
        if self.style in CADRAN:
            self.dessiner_cadran(img)

        # reflet de verre
        gl = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        ImageDraw.Draw(gl).ellipse(
            (box[0] - k(80), box[1] - k(210), box[2] + k(80),
             box[1] + k(Hh * 0.50)), fill=(255, 255, 255, 58))
        gl.putalpha(ImageChops.multiply(gl.getchannel("A"), masque))
        img.alpha_composite(gl)

        bord = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        bdd = ImageDraw.Draw(bord)
        bdd.rounded_rectangle(box, rayon, outline=(255, 255, 255, 205),
                              width=k(2))
        ins = k(3)
        bdd.rounded_rectangle((box[0] + ins, box[1] + ins, box[2] - ins,
                               box[3] - ins), rayon - ins,
                              outline=(255, 255, 255, 60), width=max(1, k(1)))
        img.alpha_composite(bord)
        res = img.resize((self.W, self.H), Image.LANCZOS)
        if self.style in CADRAN:
            self.chiffres(res)
        return res

    def dessiner_cadran(self, img):
        k, th = self.k, self.th
        cx, cy, R = CADRAN[self.style]
        cx, cy = MARGE + cx, MARGE + cy
        S = (img.width, img.height)
        d = ImageDraw.Draw(img)
        # lunette (anneau coloré brillant)
        n = 30
        for i in range(n):
            t = i / (n - 1)
            rr = R * (1 - 0.10 * t)
            d.ellipse((k(cx - rr), k(cy - rr - 0.8 * t), k(cx + rr),
                       k(cy + rr - 0.8 * t)),
                      fill=mix(th["orb_bas"], th["orb_haut"], t ** 0.9) + (255,))
        d.ellipse((k(cx - R), k(cy - R), k(cx + R), k(cy + R)),
                  outline=(255, 255, 255, 215), width=k(2))
        # fond du cadran (verre clair)
        rf = R * 0.86
        for i in range(24):
            t = i / 23
            rr = rf * (1 - 0.0 * t)
            d.line((0, 0, 0, 0))
        face = Image.new("RGBA", S, (0, 0, 0, 0))
        fd = ImageDraw.Draw(face)
        y0, y1 = int(k(cy - rf)), int(k(cy + rf))
        grad = Image.new("RGBA", S, (0, 0, 0, 0))
        gd = ImageDraw.Draw(grad)
        for y in range(y0, y1):
            t = (y - y0) / max(1, y1 - y0)
            gd.line((0, y, S[0], y), fill=mix((255, 255, 255), (206, 232, 255),
                                             t) + (int(244 - 22 * t),))
        m = Image.new("L", S, 0)
        ImageDraw.Draw(m).ellipse((k(cx - rf), k(cy - rf), k(cx + rf),
                                   k(cy + rf)), fill=255)
        grad.putalpha(ImageChops.multiply(grad.getchannel("A"), m))
        img.alpha_composite(grad)
        d = ImageDraw.Draw(img)
        d.ellipse((k(cx - rf), k(cy - rf), k(cx + rf), k(cy + rf)),
                  outline=(0, 70, 140, 70), width=max(1, k(1.2)))
        # graduations
        for i in range(60):
            a = i * math.pi / 30
            sx, sy = math.sin(a), -math.cos(a)
            if i % 5 == 0:
                r0, r1, w = rf * 0.80, rf * 0.94, k(2.4 if i % 15 == 0 else 1.8)
                d.line((k(cx + sx * r0), k(cy + sy * r0), k(cx + sx * r1),
                        k(cy + sy * r1)), fill=mix(th["orb_bas"], (0, 20, 60),
                                                   .35) + (255,), width=w)
            else:
                rr, pr = rf * 0.91, k(0.7)
                px, py = k(cx + sx * rr), k(cy + sy * rr)
                d.ellipse((px - pr, py - pr, px + pr, py + pr),
                          fill=(60, 100, 150, 170))
        # reflet sur le haut du cadran
        img.alpha_composite(gloss(S, (k(cx - rf * .86), k(cy - rf * .98),
                                      k(cx + rf * .86), k(cy - rf * .05)),
                                  118, 4))

    def chiffres(self, res):
        """12 / 3 / 6 / 9 dessinés au final (texte plus net)."""
        cx, cy, R = CADRAN[self.style]
        d = ImageDraw.Draw(res)
        police = charger_police("semi", self.p(11.5))
        rr = R * 0.60
        for txt, ax, ay in (("12", 0, -1), ("3", 1, 0), ("6", 0, 1),
                            ("9", -1, 0)):
            x = (MARGE + cx + ax * rr) * self.E
            y = (MARGE + cy + ay * rr) * self.E
            w = d.textlength(txt, font=police)
            d.text((x - w / 2, y - self.p(7.5)), txt, font=police,
                   fill=mix(self.th["orb_bas"], (0, 20, 60), .45) + (255,))

    # ---------------------------------------------------------- texte ---
    def texte(self, s, genre, taille, couleur=(255, 255, 255),
              ombre=(0, 35, 85, 150)):
        cle = (s, genre, taille, couleur)
        if cle in self.cache:
            return self.cache[cle]
        police = charger_police(genre, self.p(taille))
        w = int(police.getlength(s)) + 8
        h = int(self.p(taille) * 1.45) + 6
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        dec = max(1, self.p(1.6))
        d.text((4 + dec // 2, 3 + dec), s, font=police, fill=ombre)
        d.text((4, 3), s, font=police, fill=couleur + (255,))
        if len(self.cache) > 300:
            self.cache.clear()
        self.cache[cle] = img
        return img

    def aiguilles(self, dt, avec_secondes):
        cx, cy, R = CADRAN[self.style]
        th = self.th
        D = self.p(2 * R + 6)
        ss = 3
        S = D * ss
        c = S / 2
        Rr = R * self.E * ss
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        h, m, s = dt.hour % 12, dt.minute, dt.second
        a_h = ((h + m / 60) / 12) * 2 * math.pi
        a_m = ((m + (s / 60 if avec_secondes else 0)) / 60) * 2 * math.pi
        a_s = (s / 60) * 2 * math.pi

        def main(angle, long_, larg, coul, queue):
            sx, sy = math.sin(angle), -math.cos(angle)
            px, py = -sy, sx
            L1, L0 = Rr * long_, Rr * queue
            w0, w1 = larg * ss * self.E / 2, larg * ss * self.E / 4
            pts = [(c - sx * L0 + px * w0, c - sy * L0 + py * w0),
                   (c + sx * L1 + px * w1, c + sy * L1 + py * w1),
                   (c + sx * L1 - px * w1, c + sy * L1 - py * w1),
                   (c - sx * L0 - px * w0, c - sy * L0 - py * w0)]
            off = 2.2 * ss * self.E
            d.polygon([(x + off * .6, y + off) for x, y in pts],
                      fill=(0, 30, 70, 80))
            d.polygon(pts, fill=coul + (255,))
            d.line([(c, c), (c + sx * L1 * .94, c + sy * L1 * .94)],
                   fill=mix(coul, (255, 255, 255), .55) + (170,),
                   width=max(1, int(ss * self.E * 0.8)))

        coul_hm = mix(th["orb_bas"], (0, 20, 70), .35)
        main(a_h, 0.50, 6.2, coul_hm, 0.14)
        main(a_m, 0.74, 4.4, coul_hm, 0.16)
        if avec_secondes:
            main(a_s, 0.80, 1.8, th["acc_bas"], 0.22)
        rc = 5.4 * ss * self.E
        d.ellipse((c - rc, c - rc, c + rc, c + rc),
                  fill=mix(th["orb_haut"], th["orb_bas"], .35) + (255,),
                  outline=(255, 255, 255, 230), width=max(1, int(ss * .9)))
        d.ellipse((c - rc * .55, c - rc * .8, c + rc * .35, c - rc * .05),
                  fill=(255, 255, 255, 200))
        return img.resize((D, D), Image.LANCZOS)

    # ------------------------------------------------------- assemblage ---
    def composer(self, dt, o):
        E, M = self.E, MARGE
        img = self.skin.copy()
        th = self.th
        blanc = (255, 255, 255)

        def coin(s, x, y):
            img.alpha_composite(s, (max(0, int(round(x))), max(0, int(round(y)))))

        def centre_x(s, cx_base, y_base):
            coin(s, (M + cx_base) * E - s.width / 2, (M + y_base) * E)

        date = formater_date(dt, o["date_fmt"])
        sem = f"Semaine {dt.isocalendar()[1]}" if o["semaine"] else None

        if o["h24"]:
            hhmm, ampm = f"{dt.hour:02d}:{dt.minute:02d}", None
        else:
            h12 = dt.hour % 12 or 12
            hhmm = f"{h12}:{dt.minute:02d}"
            ampm = "AM" if dt.hour < 12 else "PM"

        def bloc_heure(cx_base, y_base, taille, t_sec, t_ap):
            """Heure + secondes + AM/PM, centrés autour de cx_base."""
            t_main = self.texte(hhmm, "leger", taille)
            extra = []
            if o["secondes"]:
                extra.append(self.texte(f"{dt.second:02d}", "semi", taille * .36,
                                        th["acc_haut"]))
            if ampm:
                extra.append(self.texte(ampm, "semi", taille * .24, blanc))
            largeur_extra = max([e.width for e in extra], default=0)
            gap = 2 * E if extra else 0
            total = t_main.width + gap + largeur_extra
            x0 = (M + cx_base) * E - total / 2
            coin(t_main, x0, (M + y_base) * E)
            if extra:
                xe = x0 + t_main.width + gap
                ye = (M + y_base) * E + t_main.height * 0.20
                coin(extra[0], xe, ye)
                if len(extra) > 1:
                    coin(extra[1], xe, ye + extra[0].height * 0.78)

        if self.style == "numerique":
            bloc_heure(self.L / 2, 4, 62, None, None)
            centre_x(self.texte(date, "semi", 16), self.L / 2, 92)
            if sem:
                centre_x(self.texte(sem, "normal", 11.5, (232, 247, 255)),
                         self.L / 2, 114)
        else:
            cx, cy, R = CADRAN[self.style]
            av = o["secondes"]
            ai = self.aiguilles(dt, av)
            coin(ai, (M + cx) * E - ai.width / 2, (M + cy) * E - ai.height / 2)
            if self.style == "analogique":
                centre_x(self.texte(date, "semi", 15), self.L / 2, 192)
                if sem:
                    centre_x(self.texte(sem, "normal", 11.5, (232, 247, 255)),
                             self.L / 2, 216)
            else:
                xt = 94 + 66 + (self.L - 94 - 66) / 2 + 2
                bloc_heure(xt, 22, 50, None, None)
                centre_x(self.texte(date, "semi", 14.5), xt, 100)
                if sem:
                    centre_x(self.texte(sem, "normal", 11.5, (232, 247, 255)),
                             xt, 124)
        return img


# ------------------------------------------------ fenêtre transparente ---

class Fenetre:
    def __init__(self, app):
        self.app = app
        self.root = app.root
        self.dib = None
        self.x = self.y = 0
        self.depart = (0, 0, 0, 0)
        self.bouge = False
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
        t.bind("<Enter>", lambda e: self.appliquer_zordre())

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

    def appui(self, e):
        self.depart = (e.x_root, e.y_root, self.x, self.y)
        self.bouge = False

    def glisse(self, e):
        dx, dy = e.x_root - self.depart[0], e.y_root - self.depart[1]
        if not self.bouge and abs(dx) + abs(dy) < 4:
            return
        self.bouge = True
        if self.app.cfg["verrouille"]:
            return
        self.x, self.y = self.depart[2] + dx, self.depart[3] + dy
        self.deplacer()

    def relache(self, e):
        if self.bouge and not self.app.cfg["verrouille"]:
            self.app.cfg["pos_x"], self.app.cfg["pos_y"] = self.x, self.y
            self.app.sauver_plus_tard()
        self.root.after(60, self.appliquer_zordre)

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
    r = Rendu("analogique", "Ciel Aero", 1.0)
    dt = datetime(2026, 1, 1, 10, 10, 0)
    cx, cy, R = CADRAN["analogique"]
    skin = r.skin
    box = (int((MARGE + cx - R - 3) * r.E), int((MARGE + cy - R - 3) * r.E),
           int((MARGE + cx + R + 3) * r.E), int((MARGE + cy + R + 3) * r.E))
    base = skin.crop(box)
    ai = r.aiguilles(dt, False)
    base.alpha_composite(ai, ((base.width - ai.width) // 2,
                              (base.height - ai.height) // 2))
    return base.resize((64, 64), Image.LANCZOS)


class App:
    def __init__(self, root, arriere):
        self.root = root
        self.cfg = charger_config()
        self.fenetre = None
        self.rendu = None
        self.tache = None
        self.tache_sauv = None
        self.tache_rebuild = None
        self.signature = None
        self.tray = None
        self.prevenu = False
        self.maj_vars = False

        os.makedirs(DATA, exist_ok=True)
        regler_demarrage(self.cfg["demarrage"])
        root.title("Aero Horloge – Réglages")
        root.geometry("520x520")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.cacher_reglages)
        self.construire_reglages()
        self.creer_tray()
        if self.cfg["widget_visible"]:
            self.montrer_widget()
        if arriere and self.cfg["widget_visible"]:
            root.withdraw()

    # --------------------------------------------------------- widget ----
    def construire_rendu(self):
        self.rendu = Rendu(self.cfg["style"], self.cfg["theme"],
                           self.cfg["echelle"] / 100.0)
        if self.fenetre:
            self.fenetre.configurer(self.rendu.W, self.rendu.H)
        self.signature = None
        self.tick()

    def montrer_widget(self):
        if self.fenetre is None:
            self.fenetre = Fenetre(self)
        self.cfg["widget_visible"] = True
        self.sync_var("v_widget", True)
        self.sauver_plus_tard()
        self.construire_rendu()

    def masquer_widget(self):
        if self.tache:
            self.root.after_cancel(self.tache)
            self.tache = None
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
        if self.fenetre:
            self.construire_rendu()

    def options(self):
        c = self.cfg
        return dict(h24=c["h24"], secondes=c["secondes"],
                    date_fmt=c["date_fmt"], semaine=c["semaine"])

    def dessiner(self, force=False):
        if not (self.fenetre and self.rendu):
            return
        dt = datetime.now()
        o = self.options()
        sig = (dt.hour, dt.minute, dt.second if o["secondes"] else 0, dt.day,
               tuple(o.values()), self.cfg["opacite"])
        if sig == self.signature and not force:
            return
        self.signature = sig
        self.fenetre.ecrire(self.rendu.composer(dt, o))

    def tick(self):
        """Se réveille pile à la prochaine seconde (ou minute)."""
        if self.tache:
            self.root.after_cancel(self.tache)
            self.tache = None
        if not self.fenetre:
            return
        self.dessiner()
        pas = 1.0 if self.cfg["secondes"] else 60.0
        ms = int((pas - (time.time() % pas)) * 1000) + 25
        self.tache = self.root.after(ms, self.tick)

    # ---------------------------------------------------------- menu ------
    def basculer(self, cle):
        self.cfg[cle] = not self.cfg[cle]
        self.sync_var("v_" + cle, self.cfg[cle])
        self.sauver_plus_tard()
        self.apres_option()

    def apres_option(self):
        self.signature = None
        self.tick()

    def fixer(self, cle, val):
        self.cfg[cle] = val
        self.sauver_plus_tard()
        if cle == "style":
            self.cfg["pos_x"] = self.cfg["pos_y"] = None
            self.sync_var("v_style", STYLES_INV[val])
            self.reconstruire()
        elif cle == "date_fmt":
            self.sync_var("v_date", FORMATS_INV[val])
            self.apres_option()
        elif cle == "theme":
            self.sync_var("v_theme", val)
            self.reconstruire()

    def menu_contextuel(self, x, y):
        if not self.fenetre:
            return
        m = tk.Menu(self.fenetre.top, tearoff=0)
        sm = tk.Menu(m, tearoff=0)
        for lab, val in STYLES.items():
            sm.add_command(label=("● " if self.cfg["style"] == val else "    ") + lab,
                           command=lambda v=val: self.fixer("style", v))
        m.add_cascade(label="Style", menu=sm)
        st = tk.Menu(m, tearoff=0)
        for nom in THEMES:
            st.add_command(label=("● " if self.cfg["theme"] == nom else "    ") + nom,
                           command=lambda v=nom: self.fixer("theme", v))
        m.add_cascade(label="Thème", menu=st)
        sd = tk.Menu(m, tearoff=0)
        for lab, val in FORMATS.items():
            sd.add_command(label=("● " if self.cfg["date_fmt"] == val else "    ") + lab,
                           command=lambda v=val: self.fixer("date_fmt", v))
        m.add_cascade(label="Format de la date", menu=sd)
        m.add_separator()
        m.add_command(label=("✔ " if self.cfg["secondes"] else "    ") + "Afficher les secondes",
                      command=lambda: self.basculer("secondes"))
        m.add_command(label=("✔ " if self.cfg["h24"] else "    ") + "Format 24 heures",
                      command=lambda: self.basculer("h24"))
        m.add_command(label=("✔ " if self.cfg["semaine"] else "    ") + "Numéro de semaine",
                      command=lambda: self.basculer("semaine"))
        m.add_separator()
        m.add_command(label="⚙  Réglages…", command=self.montrer_reglages)
        m.add_command(label="🙈  Masquer", command=self.masquer_widget)
        m.add_command(label="✖  Quitter", command=self.quitter)
        try:
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    # ------------------------------------------------------- réglages ----
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
        for cle, txt in (("aff", " Affichage "), ("widget", " Widget "),
                         ("demarrage", " Démarrage "),
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

        # ---- Affichage
        p = pages["aff"]
        p.columnconfigure(1, weight=1)
        self.v_widget = tk.BooleanVar(value=c["widget_visible"])
        self.v_style = tk.StringVar(value=STYLES_INV.get(c["style"]))
        self.v_theme = tk.StringVar(value=c["theme"])
        self.v_h24 = tk.BooleanVar(value=c["h24"])
        self.v_secondes = tk.BooleanVar(value=c["secondes"])
        self.v_date = tk.StringVar(value=FORMATS_INV.get(c["date_fmt"]))
        self.v_semaine = tk.BooleanVar(value=c["semaine"])
        ttk.Checkbutton(p, text="Afficher le widget sur le bureau",
                        variable=self.v_widget,
                        command=self.toggle_widget_ui).grid(
            row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(p, text="Style").grid(row=1, column=0, sticky="w", pady=8)
        ttk.Combobox(p, textvariable=self.v_style, state="readonly",
                     values=list(STYLES)).grid(row=1, column=1, columnspan=2,
                                               sticky="ew", padx=8)
        ttk.Label(p, text="Thème").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Combobox(p, textvariable=self.v_theme, state="readonly",
                     values=list(THEMES)).grid(row=2, column=1, columnspan=2,
                                               sticky="ew", padx=8)
        ttk.Label(p, text="Date").grid(row=3, column=0, sticky="w", pady=6)
        ttk.Combobox(p, textvariable=self.v_date, state="readonly",
                     values=list(FORMATS)).grid(row=3, column=1, columnspan=2,
                                                sticky="ew", padx=8)
        ttk.Checkbutton(p, text="Format 24 heures (sinon AM / PM)",
                        variable=self.v_h24).grid(
            row=4, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Checkbutton(p, text="Afficher les secondes",
                        variable=self.v_secondes).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Checkbutton(p, text="Afficher le numéro de semaine",
                        variable=self.v_semaine).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Label(p, foreground="#666", wraplength=470, text=(
            "Astuce : clic droit sur le widget pour changer de style, de "
            "thème ou de format sans ouvrir cette fenêtre.")).grid(
            row=7, column=0, columnspan=3, sticky="w", pady=14)
        self.lier(self.v_style, "style", lambda x: STYLES[x],
                  lambda: (self.cfg.update(pos_x=None, pos_y=None),
                           self.reconstruire_tard()))
        self.lier(self.v_theme, "theme", apres=self.reconstruire_tard)
        self.lier(self.v_date, "date_fmt", lambda x: FORMATS[x],
                  self.apres_option)
        self.lier(self.v_h24, "h24", apres=self.apres_option)
        self.lier(self.v_secondes, "secondes", apres=self.apres_option)
        self.lier(self.v_semaine, "semaine", apres=self.apres_option)

        # ---- Widget
        p = pages["widget"]
        p.columnconfigure(1, weight=1)
        self.v_echelle = tk.IntVar(value=c["echelle"])
        self.v_opacite = tk.IntVar(value=c["opacite"])
        self.v_zordre = tk.StringVar(value=ZORDRES_INV.get(c["zordre"]))
        self.v_verrou = tk.BooleanVar(value=c["verrouille"])
        curseur(p, 0, "Taille (%)", self.v_echelle, 60, 250)
        curseur(p, 1, "Opacité (%)", self.v_opacite, 30, 100)
        ttk.Label(p, text="Position").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Combobox(p, textvariable=self.v_zordre, state="readonly",
                     values=list(ZORDRES)).grid(row=2, column=1, columnspan=2,
                                                sticky="ew", padx=8)
        ttk.Checkbutton(p, text="Verrouiller la position",
                        variable=self.v_verrou).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=6)
        ttk.Button(p, text="↖  Replacer en haut à droite",
                   command=self.replacer).grid(row=4, column=0, columnspan=3,
                                               sticky="w", pady=12)
        self.lier(self.v_echelle, "echelle", int, self.reconstruire_tard)
        self.lier(self.v_opacite, "opacite", int,
                  lambda: self.dessiner(force=True))
        self.lier(self.v_zordre, "zordre", lambda x: ZORDRES[x],
                  lambda: self.fenetre and self.fenetre.appliquer_zordre())
        self.lier(self.v_verrou, "verrouille")

        # ---- Démarrage
        p = pages["demarrage"]
        self.v_demarrage = tk.BooleanVar(value=c["demarrage"])
        ttk.Checkbutton(p, text="Lancer Aero Horloge avec Windows "
                        "(en arrière-plan)", variable=self.v_demarrage,
                        command=self.maj_demarrage).pack(anchor="w", pady=4)
        ttk.Label(p, foreground="#666", wraplength=470, text=(
            "Au démarrage, l'application se place près de l'horloge "
            "(flèche ^) et affiche directement le widget. Tous les réglages "
            "sont enregistrés automatiquement.")).pack(anchor="w", pady=10)

        # ---- Désinstaller
        p = pages["desinstaller"]
        ttk.Label(p, wraplength=470, text=(
            "La désinstallation retire le démarrage automatique et supprime "
            "l'application et ses réglages de cet ordinateur.")).pack(
            anchor="w", pady=10)
        ttk.Button(p, text="🗑  Désinstaller Aero Horloge…",
                   command=self.desinstaller).pack(anchor="w", pady=10)

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
                lambda i: "Masquer le widget" if self.fenetre
                else "Afficher le widget",
                lambda i, m: self.root.after(0, self.toggle_widget_tray),
                default=True),
            pystray.MenuItem("Afficher les secondes",
                             lambda i, m: self.root.after(
                                 0, lambda: self.basculer("secondes")),
                             checked=lambda i: self.cfg["secondes"]),
            pystray.MenuItem("Format 24 heures",
                             lambda i, m: self.root.after(
                                 0, lambda: self.basculer("h24")),
                             checked=lambda i: self.cfg["h24"]),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Réglages…", lambda i, m: self.root.after(
                0, self.montrer_reglages)),
            pystray.MenuItem("Quitter", lambda i, m: self.root.after(
                0, self.quitter)))
        self.tray = pystray.Icon(NOM, icone_tray(), "Aero Horloge", menu)
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
                                     "sur l'icône pour quitter.", "Aero Horloge")
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
                "Désinstaller", "Supprimer Aero Horloge, ses réglages et le "
                "démarrage automatique ?", icon="warning"):
            return
        regler_demarrage(False)
        if FROZEN:
            cmd = (f'ping 127.0.0.1 -n 4 >nul & del /f /q "{sys.executable}"'
                   f' & rmdir /s /q "{DATA}"')
            subprocess.Popen(f'cmd /s /c "{cmd}"', close_fds=True,
                             creationflags=0x08000000 | 0x00000008)
        else:
            shutil.rmtree(DATA, ignore_errors=True)
        messagebox.showinfo("Désinstallé", "Aero Horloge a été désinstallé.")
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
    if not instance_unique():
        if not arriere:
            r = tk.Tk()
            r.withdraw()
            messagebox.showinfo(NOM, "Aero Horloge tourne déjà.\nCherche son "
                                "icône près de l'horloge (flèche ^).")
        return
    basse_priorite()
    root = tk.Tk()
    App(root, arriere)
    root.mainloop()


if __name__ == "__main__":
    main()
