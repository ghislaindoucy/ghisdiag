r"""
GhisdiagDisk - fiche par disque : identite, type de support, exclusions.

Toutes les regles de ce module ont ete CALIBREES sur les campagnes du 08/08 au
03/09/2026 (27 disques, dont 12 mecaniques). Les fonctions sont pures et
testables sans materiel ; `inventaire_machine()` est la seule qui touche au
systeme.

Regles (ROADMAP, sections << Campagne >>, qui font foi) :
  - un champ rempli n'est PAS un identifiant : la cle USB rend << 1 >>, le
    NVMe rend un EUI-64 presque tout en zeros, l'Optane rend `Optane_0000` ;
  - cle composite avec NIVEAU DE CONFIANCE : forte (smartctl), moyenne
    (IOCTL), faible (repli explicite MODELE-TAILLE-SANS-SERIE) ;
  - mecanique / SSD : bus NVMe -> SSD ; rotation_rate 0 -> SSD, >0 -> mecanique ;
    sinon profil ZBR (ratio fin/debut 0,30-0,65 ET decroissance monotone) ;
  - exclusions : porteur de l'exe et support de boot (jamais), virtuel (jamais),
    composite Optane (pas un disque physique), cle USB amovible (pas la
    population visee). Un disque en dock USB reste testable, avec avertissement.
"""

from typing import Optional

# --- Numero de serie ---------------------------------------------------------

def nettoyer_serie(brut) -> tuple:
    """Serie utilisable comme NOM DE FICHIER + drapeau << a ete assaini >>.

    L'IOCTL rend pour une cle USB un serie contenant des octets de controle.
    """
    if not brut:
        return None, False
    propre = "".join(c if (c.isalnum() or c in "-_") else "_"
                     for c in str(brut)).strip("_")
    return (propre or None), (propre != str(brut))


def serie_solide(serie) -> tuple:
    """(ok, raison) - un serie assaini n'est pas pour autant DISCRIMINANT."""
    if not serie:
        return False, "absent"
    s = str(serie).strip("_. ")
    nu = s.replace("_", "").replace("-", "")
    if len(nu) < 6:
        return False, "trop court pour discriminer"
    if len(set(nu)) <= 1:
        return False, "un seul caractere repete"
    if len(nu.strip("0")) < 4:
        return False, "essentiellement des zeros"
    if nu.endswith("0000"):
        return False, "terminaison en zeros - serie generique de fabricant"
    return True, "ok"


def _norm(x) -> Optional[str]:
    return "".join(str(x).split()).upper().strip("_. ") if x else None


def cle_identite(idt: dict, smart: dict, taille_go) -> dict:
    """Cle composite retenue pour indexer les rapports, avec sa confiance."""
    idt, smart = idt or {}, smart or {}
    ser_smart = smart.get("numero_serie")
    ser_ioctl = nettoyer_serie(idt.get("numero_serie"))[0]
    ok_smart, _   = serie_solide(ser_smart)
    ok_ioctl, why = serie_solide(ser_ioctl)
    if ok_smart:
        cle, source, conf = nettoyer_serie(ser_smart)[0], "smartctl", "forte"
    elif ok_ioctl:
        cle, source, conf = ser_ioctl, "IOCTL", "moyenne"
    else:
        cle = f"{idt.get('modele') or smart.get('modele') or 'DISQUE'}-{taille_go}Go-SANS-SERIE"
        cle = nettoyer_serie(cle)[0]
        source, conf = "repli modele+taille", "faible"
    return {"cle_identite": cle, "source_cle": source, "confiance_cle": conf,
            "serie_smartctl": ser_smart, "serie_ioctl": ser_ioctl,
            "raison_rejet_ioctl": None if ok_ioctl else why}


# --- Type de support ---------------------------------------------------------

def profil_zbr(debits: list) -> dict:
    """Signature d'enregistrement par zones d'un disque mecanique.

    `debits` = [debut, milieu, fin] en Mo/s. Calibre sur 11 disques
    mecaniques : ratio fin/debut 0,40-0,52 et decroissance monotone (11/11),
    contre 0,98-1,84 et jamais monotone sur SSD. Bande elargie a 0,30-0,65 :
    exclut toujours l'Optane (0,08) et la cle USB (0,77).
    """
    d = [x for x in (debits or []) if x]
    if len(d) != 3:
        return {"ratio_fin_debut": None, "monotone_decroissant": None,
                "signature_mecanique": None}
    ratio = d[2] / d[0]
    monotone = d[0] > d[1] > d[2]
    return {"ratio_fin_debut": round(ratio, 2),
            "monotone_decroissant": monotone,
            "signature_mecanique": bool(monotone and 0.30 <= ratio <= 0.65)}


def type_support(idt: dict, smart: dict, debits: Optional[list] = None) -> str:
    """Regle en cascade (voir en-tete). `debits` optionnel = [debut, milieu, fin]."""
    smart = smart or {}
    bus = (idt or {}).get("bus")
    if bus == "NVMe" or smart.get("usure_nvme_pct") is not None \
            or (smart.get("protocole") or "").upper() == "NVME":
        return "SSD NVMe"
    rr = smart.get("rotation_rate")
    if rr == 0:
        return "SSD"
    if isinstance(rr, int) and rr > 0:
        return f"Disque mecanique ({rr} tr/min)"
    if profil_zbr(debits).get("signature_mecanique"):
        return "Disque mecanique (profil ZBR, vitesse inconnue)"
    if bus == "RAID":
        return "volume RAID - support reel inconnu"
    if bus == "USB":
        return "USB - support indetermine"
    return "indetermine"


def classe_support(type_sup: str, bus: Optional[str]) -> str:
    """Classe pour la comparaison de debit : nvme | ssd | hdd | inconnue."""
    t = (type_sup or "").lower()
    if "nvme" in t:
        return "nvme"
    if t.startswith("ssd"):
        return "ssd"
    if "mecanique" in t:
        return "hdd"
    return "inconnue"


# --- Appariement smartctl / IOCTL --------------------------------------------

def apparier_smart(idt: dict, smarts: list) -> dict:
    """Par numero de serie d'abord, par modele ensuite - jamais par position
    (smartctl voit aussi les lecteurs optiques et duplique derriere RST)."""
    serie  = _norm((idt or {}).get("numero_serie"))
    modele = _norm((idt or {}).get("modele"))
    for s in smarts:
        if serie and _norm(s.get("numero_serie")) == serie:
            return s
    for s in smarts:
        if modele and _norm(s.get("modele")) == modele:
            return s
    return {}


# --- Exclusions --------------------------------------------------------------

def _composite_optane(idt: dict) -> bool:
    """`Optane+932GBHDD` (bus RAID) : cache Optane devant un HDD. Pas un
    disque : la lecture brute voit le cache puis les plateaux, et smartctl
    decrit le disque membre. Verdict impossible sur un objet qui n'existe pas."""
    m = str((idt or {}).get("modele") or "")
    return "optane" in m.lower() and "+" in m


def regles_exclusion(fiche: dict, exclus: dict) -> tuple:
    """-> (testable, raisons_exclusion, avertissements)."""
    raisons, avert = [], []
    idx = fiche.get("index")
    idt = fiche.get("identite") or {}
    bus = idt.get("bus")
    if idx in (exclus.get("porteur_exe") or []):
        raisons.append("porte l'executable GhisdiagDisk (garde-fou 3)")
    if idx in (exclus.get("boot_pe") or []):
        raisons.append("support de demarrage du WinPE - un support qui alimente "
                       "le systeme donne des chiffres qui ne le decrivent pas")
    if bus in ("virtuel", "virtuel-fichier", "StorageSpaces"):
        raisons.append(f"peripherique {bus} - pas un disque physique")
    if _composite_optane(idt):
        raisons.append("volume composite Optane + HDD - le verdict porterait sur un "
                       "objet qui n'existe pas physiquement")
    if bus == "USB" and idt.get("amovible"):
        raisons.append("cle USB amovible - hors population visee")
    elif bus == "USB":
        avert.append("disque derriere un pont USB : debit plafonne par le lien, "
                     "comparaison a la classe desactivee")
    if bus == "RAID" and not _composite_optane(idt):
        avert.append("controleur RAID/RST : SMART possiblement muet, le test de "
                     "surface est alors la seule source")
    if not (fiche.get("geometrie") or {}).get("taille_octets"):
        raisons.append("taille inconnue")
    return (not raisons), raisons, avert


# --- Fiche -------------------------------------------------------------------

def construire_fiche(geo: dict, idt: dict, smart_entree: dict, exclus: dict,
                     partitions: Optional[dict] = None) -> dict:
    """Fiche consolidee d'un disque a partir des trois sources (pure)."""
    from . import smart as _smart
    fiche = {"index": geo.get("index"), "peripherique": geo.get("peripherique"),
             "geometrie": geo, "identite": idt or {}, "taille_go": geo.get("taille_go")}
    cle = cle_identite(idt, smart_entree, geo.get("taille_go"))
    fiche.update(cle)
    fiche["modele"] = (idt or {}).get("modele") or (smart_entree or {}).get("modele")
    fiche["bus"] = (idt or {}).get("bus")
    fiche["type_support"] = type_support(idt, smart_entree)
    fiche["classe"] = classe_support(fiche["type_support"], fiche["bus"])
    fiche["smart"] = smart_entree or None
    fiche["smart_disponible"] = bool(smart_entree)
    fiche["usure"] = _smart.projection_usure(smart_entree) if smart_entree else None
    fiche["partitions"] = partitions
    testable, raisons, avert = regles_exclusion(fiche, exclus or {})
    fiche["testable"] = testable
    fiche["raisons_exclusion"] = raisons
    fiche["avertissements"] = avert
    return fiche


def inventaire_machine(avec_smart: bool = True, avec_partitions: bool = True) -> dict:
    """Inventaire reel : rawdisk + smartctl. Ne leve jamais."""
    from . import rawdisk, smart as _smart
    ctx = rawdisk.contexte()
    try:
        exclus = rawdisk.disques_a_exclure()
    except Exception:
        exclus = {"porteur_exe": [], "boot_pe": [], "indices": []}
    smarts, smart_info = [], {"disponible": False, "entrees": []}
    if avec_smart:
        try:
            smart_info = _smart.inventaire()
            smarts = [e for e in smart_info["entrees"] if e.get("exploitable")]
        except Exception:
            pass
    fiches = []
    for geo in rawdisk.enumerer():
        i = geo["index"]
        try:
            idt = rawdisk.identite_ioctl(i)
        except Exception as exc:
            idt = {"erreur": f"{type(exc).__name__}: {exc}"}
        parts = None
        if avec_partitions:
            try:
                parts = rawdisk.partitions(i, geo["secteur_logique"])
            except Exception as exc:
                parts = {"schema": "illisible", "erreur": str(exc), "partitions": []}
        fiches.append(construire_fiche(geo, idt, apparier_smart(idt, smarts), exclus, parts))
    return {"contexte": ctx, "exclusions": exclus, "smartctl": {
                "disponible": smart_info.get("disponible"),
                "nb_entrees": len(smart_info.get("entrees") or [])},
            "disques": fiches,
            "avertissement_elevation": (not ctx["admin"] and not fiches and
                                        ctx["environnement"] == "windows")}
