#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dimensionnement préliminaire d'un échangeur routier R+n
(R = niveau du sol, n = nombre de niveaux d'ouvrages au-dessus).

Application Streamlit. Lancement :
    pip install streamlit pandas
    streamlit run app_echangeur.py
"""
import json
import math

import pandas as pd
import streamlit as st

# ----------------------------------------------------------------- Constantes
FROTTEMENT = [(30, .28), (40, .23), (50, .19), (60, .15), (70, .14), (80, .14),
              (90, .13), (100, .12), (110, .11), (120, .09), (130, .08)]
ET = {"plat": 1.5, "vallonne": 2.5, "montagneux": 4.5}   # équivalent uvp / PL

DEFAUT = {
    "n_niveaux": 2,
    "vitesse": {"A": 90, "B": 70},
    "terrain": "plat",
    "pct_pl": 8.0,
    "phf": 0.92,
    "capacite_voie_principale": 2000,
    "taux_charge_max": 0.80,
    "devers_max": 0.07,
    "v_bretelle_droite": 50,
    "v_boucle": 40,
    "v_semi_directe": 60,
    "debit_max_boucle": 1000,
    "decel_sortie": 2.5,
    "accel_insertion": 1.2,
    "temps_reaction": 2.5,
    "pente_max_rampe": 0.06,
    "gabarit": 4.50,
    "epaisseur_tablier": 1.20,
    "longueur_biseau_sortie": 70,
    "longueur_biseau_insertion": 100,
    "flux": {
        "A+": {"tout_droit": 2400, "droite": 350, "gauche": 250},
        "A-": {"tout_droit": 2200, "droite": 300, "gauche": 400},
        "B+": {"tout_droit": 900, "droite": 200, "gauche": 150},
        "B-": {"tout_droit": 850, "droite": 180, "gauche": 120},
    },
}


# ----------------------------------------------------------------- Fonctions
def interp(table, x):
    if x <= table[0][0]:
        return table[0][1]
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return table[-1][1]


def f_hv(cfg):
    return 1.0 / (1.0 + cfg["pct_pl"] / 100.0 * (ET[cfg["terrain"]] - 1.0))


def en_uvp(debit, cfg):
    """Débit horaire (véh/h) -> débit de pointe en uvp/h."""
    return debit / (cfg["phf"] * f_hv(cfg))


def capacite_bretelle(v):
    """Capacité d'une bretelle à une voie (uvp/h) selon sa vitesse."""
    if v >= 65:
        return 2000
    if v >= 50:
        return 1900
    if v >= 40:
        return 1800
    return 1700


def rayon_min(v, cfg):
    f = interp(FROTTEMENT, v)
    return v ** 2 / (127.0 * (cfg["devers_max"] + f))


def dva(v, cfg, pente=0.0):
    """Distance de visibilité d'arrêt (m). pente > 0 = descente."""
    freinage = 3.4 / 9.81 - pente
    return v * cfg["temps_reaction"] / 3.6 + v ** 2 / (254.0 * freinage)


def l_decel(v_route, v_bretelle, cfg):
    return max(0.0, (v_route ** 2 - v_bretelle ** 2) / (25.92 * cfg["decel_sortie"]))


def l_accel(v_route, v_bretelle, cfg):
    v_ins = 0.85 * v_route          # vitesse d'insertion ≈ 85 % de la vitesse de la route
    return max(0.0, (v_ins ** 2 - v_bretelle ** 2) / (25.92 * cfg["accel_insertion"]))


def nb_voies(pc, capacite, cfg):
    return max(1, math.ceil(pc / (capacite * cfg["taux_charge_max"])))


# ----------------------------------------------------------------- Analyse
def analyser(cfg):
    res = {"mouvements": [], "niveaux": [], "alertes": [], "synthese": {}}
    n_semi = 0

    for appr in ("A+", "A-", "B+", "B-"):
        route = appr[0]
        autre = "B" if route == "A" else "A"
        v = cfg["vitesse"][route]
        v_dest = cfg["vitesse"][autre]
        fl = cfg["flux"][appr]

        # --- Tout droit
        pc = en_uvp(fl["tout_droit"], cfg)
        n = nb_voies(pc, cfg["capacite_voie_principale"], cfg)
        res["mouvements"].append({
            "approche": appr, "mouvement": "tout droit", "type": "chaussée principale",
            "debit_veh_h": fl["tout_droit"], "debit_uvp_h": round(pc), "voies": n,
            "vitesse": v, "rayon_min_m": round(rayon_min(v, cfg)), "dva_m": round(dva(v, cfg)),
        })

        # --- Tourne-à-droite : bretelle de sortie simple
        if fl["droite"] > 0:
            vr = cfg["v_bretelle_droite"]
            pc = en_uvp(fl["droite"], cfg)
            n = nb_voies(pc, capacite_bretelle(vr), cfg)
            res["mouvements"].append({
                "approche": appr, "mouvement": "droite", "type": "bretelle directe (sortie/insertion)",
                "debit_veh_h": fl["droite"], "debit_uvp_h": round(pc), "voies": n,
                "vitesse": vr, "rayon_min_m": round(rayon_min(vr, cfg)),
                "dva_m": round(dva(vr, cfg, cfg["pente_max_rampe"])),
                "l_decel_m": round(l_decel(v, vr, cfg)),
                "l_biseau_sortie_m": cfg["longueur_biseau_sortie"],
                "l_accel_m": round(l_accel(v_dest, vr, cfg)),
                "l_biseau_insertion_m": cfg["longueur_biseau_insertion"],
            })
            if n > 2:
                res["alertes"].append(f"{appr} droite : {n} voies requises (>2) – revoir le schéma.")

        # --- Tourne-à-gauche : boucle ou semi-directe
        if fl["gauche"] > 0:
            pc = en_uvp(fl["gauche"], cfg)
            if pc <= cfg["debit_max_boucle"]:
                vr, typ = cfg["v_boucle"], "boucle (270°)"
            else:
                vr, typ, n_semi = cfg["v_semi_directe"], "bretelle semi-directe", n_semi + 1
            n = nb_voies(pc, capacite_bretelle(vr), cfg)
            r = rayon_min(vr, cfg)
            mv = {
                "approche": appr, "mouvement": "gauche", "type": typ,
                "debit_veh_h": fl["gauche"], "debit_uvp_h": round(pc), "voies": n,
                "vitesse": vr, "rayon_min_m": round(r),
                "dva_m": round(dva(vr, cfg, cfg["pente_max_rampe"])),
                "l_decel_m": round(l_decel(v, vr, cfg)),
                "l_biseau_sortie_m": cfg["longueur_biseau_sortie"],
                "l_accel_m": round(l_accel(v_dest, vr, cfg)),
                "l_biseau_insertion_m": cfg["longueur_biseau_insertion"],
            }
            if typ.startswith("boucle"):
                mv["emprise_boucle_m"] = round(2 * r)
                mv["developpee_boucle_m"] = round(1.5 * math.pi * r)
            res["mouvements"].append(mv)
            if n > 2:
                res["alertes"].append(f"{appr} gauche : {n} voies requises (>2) – revoir le schéma.")

    # --- Niveaux R+n
    n = cfg["n_niveaux"]
    h = cfg["gabarit"] + cfg["epaisseur_tablier"]
    for k in range(0, n + 1):
        cote = k * h
        res["niveaux"].append({
            "niveau": "R" if k == 0 else f"R+{k}",
            "cote_m": round(cote, 2),
            "longueur_rampe_m": round(cote / cfg["pente_max_rampe"]) if k else 0,
        })
    n_min = 1 + (1 if n_semi >= 1 else 0) + (1 if n_semi >= 3 else 0)
    if n < n_min:
        res["alertes"].append(
            f"Avec {n_semi} bretelle(s) semi-directe(s), R+{n_min} au minimum est conseillé (R+{n} retenu).")

    # --- Espacements et synthèse
    v_max = max(cfg["vitesse"].values())
    res["synthese"] = {
        "niveaux_retenus": f"R+{n}",
        "niveaux_minimum_conseille": f"R+{n_min}",
        "hauteur_totale_m": round(n * h, 2),
        "nb_boucles": sum(1 for m in res["mouvements"] if m["type"].startswith("boucle")),
        "nb_semi_directes": n_semi,
        "espacement_mini_bretelles_m": round(max(250, 3.0 * v_max)),
        "type_conseille": ("Losange / giratoire (R+1)" if n_semi == 0 and not any(
            m["type"].startswith("boucle") for m in res["mouvements"] if m["debit_uvp_h"] > 600)
            else "Trèfle partiel / trompette (R+1 à R+2)" if n_semi == 0
            else "Échangeur directionnel / turbine (R+2 et plus)"),
    }
    return res


# ----------------------------------------------------------------- Interface Streamlit (version colorée)
COLONNES = {
    "approche": "Approche", "mouvement": "Mouvement", "type": "Type", "debit_veh_h": "véh/h",
    "debit_uvp_h": "uvp/h", "voies": "Voies", "vitesse": "V (km/h)", "rayon_min_m": "R min (m)",
    "dva_m": "DVA (m)", "l_decel_m": "Décélération (m)", "l_biseau_sortie_m": "Biseau sortie (m)",
    "l_accel_m": "Accélération (m)", "l_biseau_insertion_m": "Biseau insertion (m)",
    "emprise_boucle_m": "Emprise boucle (m)", "developpee_boucle_m": "Développée boucle (m)",
}

CSS = """
<style>
@keyframes glisse { from {opacity:0; transform:translateY(14px);} to {opacity:1; transform:none;} }
@keyframes flux { 0% {background-position:0% 50%;} 100% {background-position:200% 50%;} }
.hero {
  background: linear-gradient(110deg, #5b21b6, #2563eb, #06b6d4, #10b981, #2563eb, #5b21b6);
  background-size: 300% 100%; animation: flux 14s linear infinite, glisse .6s ease-out;
  border-radius: 18px; padding: 26px 30px; margin-bottom: 18px; color: #fff;
  box-shadow: 0 10px 30px rgba(37,99,235,.35);
}
.hero h1 { color:#fff; margin:0; font-size:2.1rem; padding:0; }
.hero p { margin:6px 0 0; opacity:.92; font-size:1.02rem; }
.carte {
  border-radius: 16px; padding: 16px 18px; color:#fff; min-height: 104px;
  animation: glisse .6s ease-out; transition: transform .2s, box-shadow .2s;
  box-shadow: 0 6px 16px rgba(0,0,0,.18);
}
.carte:hover { transform: translateY(-5px) scale(1.02); box-shadow: 0 14px 26px rgba(0,0,0,.28); }
.carte .k { font-size:.78rem; text-transform:uppercase; letter-spacing:.08em; opacity:.9; }
.carte .v { font-size:1.8rem; font-weight:800; line-height:1.25; margin-top:4px; }
.bandeau-type {
  margin: 16px 0 6px; padding: 12px 18px; border-radius: 12px; color:#fff; font-weight:600;
  background: linear-gradient(90deg, #f59e0b, #ef4444, #ec4899); animation: glisse .7s ease-out;
}
h2, h3 { background: linear-gradient(90deg, #2563eb, #7c3aed); -webkit-background-clip: text;
         -webkit-text-fill-color: transparent; font-weight: 800 !important; }
div.stButton > button, div.stDownloadButton > button {
  border: 0; color: #fff; font-weight: 700; border-radius: 12px; padding: .5rem 1.2rem;
  background: linear-gradient(90deg, #2563eb, #7c3aed); transition: transform .15s, filter .15s;
}
div.stDownloadButton > button:hover { transform: translateY(-2px); filter: brightness(1.15); color:#fff; }
button[data-baseweb="tab"] { font-weight: 700; font-size: 1rem; }
</style>
"""

GRADIENTS = [
    "linear-gradient(135deg,#7c3aed,#4f46e5)",
    "linear-gradient(135deg,#2563eb,#06b6d4)",
    "linear-gradient(135deg,#0d9488,#22c55e)",
    "linear-gradient(135deg,#f59e0b,#f97316)",
    "linear-gradient(135deg,#ec4899,#ef4444)",
]
COULEURS_TYPE = {"chaussée": "#cfe0ff", "bretelle directe": "#c4f5e0", "boucle": "#ffe0b8", "bretelle semi": "#ffcfe0"}
PALETTE_NIVEAUX = ["#64748b", "#2563eb", "#7c3aed", "#ec4899", "#f59e0b", "#10b981"]


def carte(label, valeur, i):
    return (f'<div class="carte" style="background:{GRADIENTS[i % len(GRADIENTS)]}">'
            f'<div class="k">{label}</div><div class="v">{valeur}</div></div>')


def coupe_niveaux_svg(niveaux, cfg):
    """Coupe schématique : sol (R) puis un tablier coloré par niveau, à l'échelle."""
    n = len(niveaux) - 1
    h_tot = max(niveaux[-1]["cote_m"], 1.0)
    ech = min(36.0, 250.0 / h_tot)            # pixels par mètre
    h_tab = cfg["epaisseur_tablier"] * ech
    base, larg = 40 + h_tot * ech + 30, 640
    haut = base + 56
    s = [f'<svg viewBox="0 0 {larg} {haut:.0f}" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:760px">']
    s.append(f'<rect width="{larg}" height="{haut:.0f}" rx="16" fill="#0f172a"/>')
    s.append(f'<rect x="0" y="{base:.0f}" width="{larg}" height="56" fill="#16a34a"/>'
             f'<text x="24" y="{base + 34:.0f}" fill="#fff" font-size="15" font-weight="700">R  (sol, cote 0 m)</text>')
    for k in range(1, n + 1):
        cote = niveaux[k]["cote_m"]
        y = base - cote * ech
        col = PALETTE_NIVEAUX[k % len(PALETTE_NIVEAUX)]
        s.append(f'<line x1="150" y1="{y + h_tab:.0f}" x2="150" y2="{base:.0f}" stroke="#94a3b8" stroke-width="5"/>'
                 f'<line x1="{larg - 150}" y1="{y + h_tab:.0f}" x2="{larg - 150}" y2="{base:.0f}" stroke="#94a3b8" stroke-width="5"/>')
        s.append(f'<rect x="90" y="{y:.0f}" width="{larg - 180}" height="{max(h_tab, 8):.0f}" rx="4" fill="{col}">'
                 f'<animate attributeName="opacity" from="0" to="1" dur="{0.4 + 0.3 * k:.1f}s" fill="freeze"/></rect>')
        s.append(f'<text x="{larg - 80}" y="{y + 6:.0f}" fill="#fff" font-size="14" font-weight="700">'
                 f'R+{k} : +{cote:.1f} m</text>')
    s.append("</svg>")
    return "".join(s)


def colorier_type(valeur):
    for cle, couleur in COULEURS_TYPE.items():
        if str(valeur).startswith(cle):
            return f"background-color:{couleur}; color:#1e293b; font-weight:600"
    return ""


def interface():
    st.set_page_config(page_title="Échangeur R+n", page_icon="🛣️", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown('<div class="hero"><h1>🛣️ Échangeur R+n</h1>'
                '<p>Voies, bretelles, longueurs d\'insertion et niveaux d\'ouvrages. '
                'Modifiez une valeur : tout se recalcule aussitôt.</p></div>', unsafe_allow_html=True)

    cfg = json.loads(json.dumps(DEFAUT))

    with st.sidebar:
        st.header("⚙️ Données générales")
        cfg["n_niveaux"] = st.number_input("Niveaux n (R+n)", 1, 5, DEFAUT["n_niveaux"], 1)
        cfg["terrain"] = st.selectbox("Terrain", list(ET.keys()), 0)
        cfg["vitesse"]["A"] = st.number_input("Vitesse route A (km/h)", 30, 130, 90, 10)
        cfg["vitesse"]["B"] = st.number_input("Vitesse route B (km/h)", 30, 130, 70, 10)
        cfg["pct_pl"] = st.number_input("Poids lourds (%)", 0.0, 50.0, 8.0, 0.5)
        cfg["phf"] = st.number_input("Facteur de pointe horaire", 0.5, 1.0, 0.92, 0.01)

        with st.expander("Paramètres avancés"):
            cfg["capacite_voie_principale"] = st.number_input("Capacité par voie (uvp/h)", 1000, 2400, 2000, 50)
            cfg["taux_charge_max"] = st.number_input("Taux de charge max (v/c)", 0.3, 1.0, 0.80, 0.05)
            cfg["devers_max"] = st.number_input("Dévers max", 0.02, 0.10, 0.07, 0.01)
            cfg["pente_max_rampe"] = st.number_input("Pente max des rampes", 0.02, 0.10, 0.06, 0.005, format="%.3f")
            cfg["v_bretelle_droite"] = st.number_input("V bretelle droite (km/h)", 30, 90, 50, 5)
            cfg["v_boucle"] = st.number_input("V boucle (km/h)", 30, 70, 40, 5)
            cfg["v_semi_directe"] = st.number_input("V semi-directe (km/h)", 40, 90, 60, 5)
            cfg["debit_max_boucle"] = st.number_input("Débit max d'une boucle (uvp/h)", 200, 1500, 1000, 50)
            cfg["decel_sortie"] = st.number_input("Décélération (m/s²)", 1.0, 4.0, 2.5, 0.1)
            cfg["accel_insertion"] = st.number_input("Accélération (m/s²)", 0.5, 3.0, 1.2, 0.1)
            cfg["temps_reaction"] = st.number_input("Temps de réaction (s)", 1.0, 4.0, 2.5, 0.1)
            cfg["gabarit"] = st.number_input("Gabarit sous ouvrage (m)", 4.0, 6.0, 4.5, 0.1)
            cfg["epaisseur_tablier"] = st.number_input("Épaisseur du tablier (m)", 0.5, 3.0, 1.2, 0.1)
            cfg["longueur_biseau_sortie"] = st.number_input("Biseau de sortie (m)", 30, 150, 70, 5)
            cfg["longueur_biseau_insertion"] = st.number_input("Biseau d'insertion (m)", 30, 200, 100, 5)

    st.subheader("🚗 Débits de pointe (véh/h)")
    base = pd.DataFrame(DEFAUT["flux"]).T.rename(
        columns={"tout_droit": "Tout droit", "droite": "Droite", "gauche": "Gauche"})
    base.index.name = "Approche"
    colonne_saisie, colonne_graphe = st.columns([1, 1])
    with colonne_saisie:
        saisie = st.data_editor(base, use_container_width=True, num_rows="fixed")
    with colonne_graphe:
        st.bar_chart(saisie, color=["#2563eb", "#10b981", "#f97316"], height=210)
    cfg["flux"] = {a: {"tout_droit": int(r["Tout droit"]), "droite": int(r["Droite"]),
                       "gauche": int(r["Gauche"])} for a, r in saisie.iterrows()}

    res = analyser(cfg)
    s = res["synthese"]

    cartes = st.columns(5)
    infos = [("Niveaux retenus", s["niveaux_retenus"]),
             ("Minimum conseillé", s["niveaux_minimum_conseille"]),
             ("Hauteur totale", f"{s['hauteur_totale_m']} m"),
             ("Boucles / semi-directes", f"{s['nb_boucles']} / {s['nb_semi_directes']}"),
             ("Espacement mini bretelles", f"{s['espacement_mini_bretelles_m']} m")]
    for i, (col, (k, v)) in enumerate(zip(cartes, infos)):
        col.markdown(carte(k, v, i), unsafe_allow_html=True)
    st.markdown(f'<div class="bandeau-type">🏗️ Type d\'échangeur conseillé : {s["type_conseille"]}</div>',
                unsafe_allow_html=True)
    for a in res["alertes"]:
        st.warning(a, icon="⚠️")

    onglet1, onglet2, onglet3 = st.tabs(["🏗️ Niveaux R+n", "🛣️ Mouvements", "📥 Export"])

    with onglet1:
        g1, g2 = st.columns([3, 2])
        with g1:
            st.markdown(coupe_niveaux_svg(res["niveaux"], cfg), unsafe_allow_html=True)
        with g2:
            niv = pd.DataFrame(res["niveaux"]).rename(columns={
                "niveau": "Niveau", "cote_m": "Cote (m)", "longueur_rampe_m": "Rampe mini (m)"})
            st.dataframe(niv, hide_index=True, use_container_width=True)

    mv = pd.DataFrame(res["mouvements"]).rename(columns=COLONNES)
    with onglet2:
        style = mv.style
        appliquer = style.map if hasattr(style, "map") else style.applymap
        style = appliquer(colorier_type, subset=["Type"])
        st.dataframe(
            style, hide_index=True, use_container_width=True,
            column_config={
                "uvp/h": st.column_config.ProgressColumn(
                    "uvp/h", min_value=0, max_value=int(max(mv["uvp/h"].max(), 1)), format="%d"),
                "Voies": st.column_config.NumberColumn("Voies", format="%d 🛣️"),
            })
        st.caption("Couleurs : bleu = chaussée principale, vert = bretelle directe, "
                   "orange = boucle, rose = semi-directe.")

    with onglet3:
        d1, d2 = st.columns(2)
        d1.download_button("📄 Télécharger (CSV)", mv.to_csv(index=False).encode("utf-8-sig"),
                           "echangeur_resultats.csv", "text/csv")
        d2.download_button("🧾 Télécharger (JSON)", json.dumps(res, indent=2, ensure_ascii=False),
                           "echangeur_resultats.json", "application/json")
        st.caption("Méthodes simplifiées (type AASHTO / ICTAAL), à valider par un bureau d'études.")


interface()
