"""
Tests des pièces jointes au diagnostic IA (ai_attachments.py) — v2.2.0.

Vérifie :
  - fenêtre de fraîcheur : seules les sessions DU JOUR sont retenues ; une
    session d'hier est ignorée, même plus « intéressante » ;
  - une pièce par cible : CPU et GPU joints ensemble, la plus récente par cible ;
    avant + après le même jour → le DELTA (thermal_compare), pas les deux ;
  - le tri-état survit au digest : throttling « oui » / « non » / « non mesure »
    avec sa raison (charge écourtée ≠ fréquence illisible), y compris sur une
    session archivée v1 dont le False était une valeur par défaut ;
  - déroulement : complet / écourté / avorté / urgence, plateau et ΔT invalidés ;
  - la courbe est ré-échantillonnée (~20 points) et les séries brutes restent
    hors digest ;
  - budget propre : au-delà de MAX_ATTACHMENTS_LEN, les courbes sautent d'abord,
    le diagnostic n'est jamais touché ;
  - invariant prompt : sans pièce jointe, `_build_user_prompt` est STRICTEMENT
    identique ; avec, le bloc est placé AVANT le JSON et après l'intro ;
  - le prompt système contient les seuils thermiques et le garde-fou tri-état ;
  - rejeu des sessions RÉELLES archivées sur ce poste (si présentes) : aucun
    digest ne plante, v1 comme v2, y compris une session avortée à 3 échantillons.

Lancement :  py -m unittest discover -s tests -v
"""

import glob
import json
import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

import ai_attachments as aa
from ai_analyzer import SYSTEM_PROMPT, _build_user_prompt
from thermal_bench import load_session


def _samples(idle=60, load=300, cool=120, step=10, cpu_load_idle=3.0,
             clock=3600, target="cpu"):
    out = []
    t = 0
    for phase, dur in (("idle", idle), ("load", load), ("cooldown", cool)):
        for _ in range(0, dur, step):
            temp = {"idle": 45.0, "load": 85.0, "cooldown": 55.0}[phase]
            s = {"t": t, "phase": phase, "cpu": temp, "gpu": temp - 10,
                 "cpu_load": cpu_load_idle if phase != "load" else 99.0,
                 "gpu_load": 2.0 if phase != "load" else 98.0,
                 "clock": clock, "gpu_clock": 1500, "fans": [1200]}
            out.append(s)
            t += step
    return out


def _session(label="libre", target="cpu", started="2026-09-03T14:32:00",
             metrics=None, samples=None, version=2, **extra):
    m = {"idle_c": 45.0, "load_max_c": 88.0, "load_plateau_c": 85.0,
         "delta_c": 40.0, "cooldown_sec": 90.0, "fan_idle_rpm": 1200,
         "fan_load_rpm": 3400, "clock_max_mhz": 3600, "clock_drop_pct": 1.0,
         "clock_samples": 30, "throttling": False, "power_limited": False,
         "load_truncated": False, "idle_load_pct": 3.0, "idle_polluted": False,
         "cpu_load_avg": 99.0}
    if target == "gpu":
        m.update({"gpu_idle_c": 35.0, "gpu_max_c": 78.0, "gpu_plateau_c": 75.0,
                  "gpu_delta_c": 40.0, "gpu_hotspot_max_c": 88.0, "gpu_power_max_w": 110.0,
                  "gpu_clock_max_mhz": 1800, "gpu_clock_drop_pct": 2.0,
                  "gpu_clock_samples": 30, "gpu_throttling": False,
                  "gpu_power_limited": False, "gpu_cooldown_sec": 80.0})
    if metrics:
        m.update(metrics)
    s = {"version": version, "label": label, "started_at": started,
         "duration_sec": 480.0,
         "machine": {"hostname": "PC-TEST", "cpu": "TestCPU", "cores": 8},
         "config": {"label": label, "idle_sec": 60, "load_sec": 300,
                    "cooldown_sec": 120, "intensity": 100, "target": target,
                    "kernel": "avx", "emergency_temp_c": 95.0,
                    "gpu_emergency_temp_c": 90.0},
         "aborted": False, "emergency": False, "cooldown_truncated": False,
         "abort_reason": None, "metrics": m,
         "samples": _samples(target=target) if samples is None else samples}
    if target == "gpu":
        s["gpu_adapter"] = {"index": 0, "name": "NVIDIA RTX 3060", "vendor": "NVIDIA",
                            "vram_mb": 12288}
    s.update(extra)
    return s


def _ecrire(dossier: Path, session: dict) -> Path:
    ts = datetime.fromisoformat(session["started_at"]).strftime("%Y%m%d_%H%M%S")
    p = dossier / "thermal" / f"{session['label']}_{ts}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(session), encoding="utf-8")
    return p


AUJOURDHUI = date(2026, 9, 3)


class TestSelection(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dossier = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_aucune_session_aucune_piece(self):
        self.assertEqual(aa.build_attachments(self.dossier, AUJOURDHUI), [])
        self.assertEqual(aa.render_attachments([]), "")
        self.assertEqual(aa.resume_attachments([]), "")

    def test_session_d_hier_ignoree(self):
        _ecrire(self.dossier, _session(started="2026-09-02T18:00:00",
                                       metrics={"throttling": True}))
        self.assertEqual(aa.build_attachments(self.dossier, AUJOURDHUI), [])

    def test_une_par_cible_la_plus_recente(self):
        _ecrire(self.dossier, _session(started="2026-09-03T09:00:00", metrics={"load_max_c": 70.0}))
        _ecrire(self.dossier, _session(started="2026-09-03T14:32:00", metrics={"load_max_c": 88.0}))
        _ecrire(self.dossier, _session(target="gpu", started="2026-09-03T15:10:00"))
        pieces = aa.build_attachments(self.dossier, AUJOURDHUI)
        self.assertEqual([p["cible"] for p in pieces], ["cpu", "gpu"])
        self.assertEqual(pieces[0]["heure"], "14:32")
        self.assertEqual(pieces[0]["mesures"]["load_max_c"], 88.0)
        self.assertEqual(pieces[1]["adaptateur_gpu"], "NVIDIA RTX 3060")
        self.assertEqual(aa.resume_attachments(pieces), "CPU 14:32 (libre), GPU 15:10 (libre)")

    def test_avant_apres_le_meme_jour_donne_le_delta(self):
        _ecrire(self.dossier, _session("avant", started="2026-09-03T10:00:00",
                                       metrics={"load_plateau_c": 92.0, "load_max_c": 95.0,
                                                "throttling": True}))
        _ecrire(self.dossier, _session("apres", started="2026-09-03T15:00:00",
                                       metrics={"load_plateau_c": 80.0, "load_max_c": 83.0}))
        pieces = aa.build_attachments(self.dossier, AUJOURDHUI)
        self.assertEqual(len(pieces), 1)
        p = pieces[0]
        self.assertEqual(p["type"], aa.TYPE_COMPARAISON)
        self.assertEqual(p["gains"]["load_plateau_c"]["gain"], 12.0)
        self.assertEqual(p["throttling_thermique"], {"avant": "oui", "apres": "non",
                                                     "elimine": True, "apparu": False})
        self.assertFalse(p["comparaison_bloquante"])
        self.assertIn("efficace", p["verdict"])
        self.assertIn("avant/après", aa.resume_attachments(pieces))

    def test_apres_avant_l_avant_ne_compare_pas(self):
        # Un « après » fait le matin et un « avant » l'après-midi : ordre absurde,
        # on joint la plus récente au lieu d'inventer un delta.
        _ecrire(self.dossier, _session("apres", started="2026-09-03T09:00:00"))
        _ecrire(self.dossier, _session("avant", started="2026-09-03T16:00:00"))
        pieces = aa.build_attachments(self.dossier, AUJOURDHUI)
        self.assertEqual(pieces[0]["type"], aa.TYPE_BENCH)
        self.assertEqual(pieces[0]["libelle"], "avant")

    def test_dossier_inexistant(self):
        self.assertEqual(aa.build_attachments(self.dossier / "nulle_part", AUJOURDHUI), [])


class TestDigestTriEtat(unittest.TestCase):

    def test_complet_sans_throttling(self):
        d = aa.digest_bench(_session())
        self.assertEqual(d["deroulement"]["etat"], "complet")
        self.assertTrue(d["deroulement"]["plateau_et_deltaT_valides"])
        self.assertEqual(d["throttling_thermique"], "non")
        self.assertIsNone(d["throttling_raison"])
        self.assertEqual(d["limite_puissance"], "non")
        self.assertNotIn("samples", d)
        self.assertNotIn("clock_samples", json.dumps(d["mesures"]))

    def test_throttling_mesure_oui(self):
        d = aa.digest_bench(_session(metrics={"throttling": True}))
        self.assertEqual(d["throttling_thermique"], "oui")

    def test_charge_ecourtee_ne_conclut_pas(self):
        s = _session(metrics={"throttling": False, "load_truncated": True,
                              "load_plateau_c": None, "delta_c": None},
                     samples=_samples(load=25))
        d = aa.digest_bench(s)
        self.assertEqual(d["deroulement"]["etat"], "ecourte")
        self.assertFalse(d["deroulement"]["plateau_et_deltaT_valides"])
        self.assertIn("s sur 300 s prevues", d["deroulement"]["detail"])
        self.assertLess(d["deroulement"]["charge_reelle_s"], 300 * 0.9)
        self.assertEqual(d["throttling_thermique"], "non mesure")
        self.assertEqual(d["throttling_raison"], "charge ecourtee avant le regime etabli")
        self.assertEqual(d["limite_puissance"], "non mesure")

    def test_frequence_illisible(self):
        d = aa.digest_bench(_session(metrics={"throttling": None, "power_limited": None,
                                              "clock_samples": 0, "clock_max_mhz": None}))
        self.assertEqual(d["throttling_thermique"], "non mesure")
        self.assertEqual(d["throttling_raison"], "aucune frequence CPU exploitable")

    def test_session_v1_false_par_defaut(self):
        m = {"throttling": False}
        s = _session(version=1, metrics=m)
        s["metrics"].pop("clock_samples", None)
        s["metrics"]["clock_max_mhz"] = None
        d = aa.digest_bench(s)
        self.assertEqual(d["throttling_thermique"], "non mesure")

    def test_urgence_et_avorte(self):
        d = aa.digest_bench(_session(emergency=True, samples=_samples(load=23),
                                     metrics={"load_truncated": True}))
        self.assertEqual(d["deroulement"]["etat"], "urgence")
        self.assertIn("seuil de securite", d["deroulement"]["detail"])
        d = aa.digest_bench(_session(aborted=True, abort_reason="Annule pendant la charge",
                                     samples=_samples(load=40), metrics={"load_truncated": True}))
        self.assertEqual(d["deroulement"]["etat"], "avorte")
        self.assertIn("Annule pendant la charge", d["deroulement"]["detail"])

    def test_repos_pollue(self):
        d = aa.digest_bench(_session(metrics={"idle_load_pct": 35.0, "idle_polluted": True}))
        self.assertTrue(d["deroulement"]["repos_pollue"])
        self.assertEqual(d["deroulement"]["charge_cpu_au_repos_pct"], 35.0)

    def test_gpu(self):
        d = aa.digest_bench(_session(target="gpu", metrics={"gpu_throttling": None,
                                                            "gpu_clock_samples": 0,
                                                            "gpu_clock_max_mhz": None,
                                                            "gpu_power_limited": None}))
        self.assertEqual(d["cible"], "gpu")
        self.assertIn("gpu_hotspot_max_c", d["mesures"])
        self.assertNotIn("load_plateau_c", d["mesures"])
        self.assertEqual(d["throttling_raison"], "aucune frequence GPU exploitable")
        self.assertEqual(d["protocole"]["seuil_urgence_c"], 90.0)
        self.assertIn("GPU", d["courbe"]["legende"])

    def test_courbe_reechantillonnee(self):
        d = aa.digest_bench(_session())
        pts = d["courbe"]["points"]
        self.assertEqual(len(pts), aa.CURVE_POINTS)
        self.assertEqual(pts[0][1], "R")
        self.assertEqual(pts[-1][1], "F")
        self.assertTrue(any(p[1] == "C" for p in pts))
        self.assertEqual(pts[0][0], 0)
        self.assertEqual(len(pts[0]), 5)
        d = aa.digest_bench(_session(samples=[]))
        self.assertEqual(d["courbe"]["points"], [])


class TestRendu(unittest.TestCase):

    def test_bloc_et_budget(self):
        pieces = [aa.digest_bench(_session()), aa.digest_bench(_session(target="gpu"))]
        txt = aa.render_attachments(pieces)
        self.assertTrue(txt.startswith("PIÈCES JOINTES"))
        self.assertIn("2026-09-03", txt)
        self.assertIn("TRI-ÉTAT", txt)
        self.assertIn("```json", txt)
        self.assertTrue(txt.endswith("---\n\n"))
        self.assertLessEqual(len(txt), aa.MAX_ATTACHMENTS_LEN)
        self.assertIn('"courbe"', txt)
        # Budget serre : les courbes sautent, les mesures restent.
        court = aa.render_attachments(pieces, max_len=len(txt) - 100)
        self.assertNotIn('"courbe"', court)
        self.assertIn('"load_plateau_c"', court)
        self.assertLessEqual(len(court), len(txt) - 100)
        # Budget minuscule : on tronque avec un marqueur, jamais une exception.
        mini = aa.render_attachments(pieces, max_len=400)
        self.assertIn("tronquée", mini)

    def test_prompt_inchange_sans_piece(self):
        data = {"meta": {"machine": "PC-TEST"}, "performance": {"ram": {"usage_percent": 42}}}
        self.assertEqual(_build_user_prompt(data), _build_user_prompt(data, "", ""))
        self.assertEqual(_build_user_prompt(data, "q ?"), _build_user_prompt(data, "q ?", ""))
        self.assertNotIn("PIÈCES JOINTES", _build_user_prompt(data))

    def test_bloc_avant_le_json_apres_l_intro(self):
        data = {"meta": {"machine": "PC-TEST"}}
        bloc = aa.render_attachments([aa.digest_bench(_session())])
        prompt = _build_user_prompt(data, "", bloc)
        i_intro = prompt.index("Voici le rapport")
        i_bloc = prompt.index("PIÈCES JOINTES")
        i_json = prompt.index('```json\n{"meta"')
        self.assertLess(i_intro, i_bloc)
        self.assertLess(i_bloc, i_json)
        # Avec une question, la question reste en tete.
        prompt = _build_user_prompt(data, "pourquoi ?", bloc)
        self.assertLess(prompt.index("QUESTION DU TECHNICIEN"), prompt.index("PIÈCES JOINTES"))

    def test_budget_du_diagnostic_intact(self):
        # Un diagnostic enorme est tronque a 120 000 quelle que soit la piece
        # jointe : elle ne prend jamais sur lui, et lui jamais sur elle.
        data = {"events": ["x" * 1000] * 200}
        bloc = aa.render_attachments([aa.digest_bench(_session())])
        p_sans = _build_user_prompt(data)
        p_avec = _build_user_prompt(data, "", bloc)
        self.assertIn("données tronquées", p_sans)
        self.assertIn("données tronquées", p_avec)
        self.assertIn("PIÈCES JOINTES", p_avec)
        self.assertIn('"load_plateau_c"', p_avec)
        self.assertAlmostEqual(len(p_avec) - len(p_sans), len(bloc), delta=0)

    def test_prompt_systeme_seuils_thermiques(self):
        self.assertIn("Thermique", SYSTEM_PROMPT)
        self.assertIn("limite_puissance", SYSTEM_PROMPT)
        self.assertIn("non mesure", SYSTEM_PROMPT)
        self.assertIn("95 °C", SYSTEM_PROMPT)
        self.assertIn("Thermique (bench du jour)", _build_user_prompt({"a": 1}))
        self.assertIn("Refroidissement", _build_user_prompt({"a": 1}))


class TestSessionsReelles(unittest.TestCase):
    """Rejeu des sessions archivées sur ce poste — sautées si absentes."""

    DOSSIER = Path.home() / "Documents" / "Ghisdiag_Reports" / "thermal"

    def test_rejeu(self):
        fichiers = sorted(glob.glob(str(self.DOSSIER / "*.json")))
        if not fichiers:
            self.skipTest("aucune session archivée sur ce poste")
        for f in fichiers:
            s = load_session(f)
            if not s:
                continue
            with self.subTest(fichier=os.path.basename(f)):
                d = aa.digest_bench(s)
                self.assertIn(d["throttling_thermique"], ("oui", "non", "non mesure"))
                self.assertIn(d["deroulement"]["etat"], ("complet", "ecourte", "avorte", "urgence"))
                if d["deroulement"]["etat"] != "complet":
                    self.assertNotEqual(d["throttling_thermique"], "non",
                                        "un test incomplet ne peut pas certifier l'absence")
                json.dumps(d)
                txt = aa.render_attachments([d])
                self.assertLessEqual(len(txt), aa.MAX_ATTACHMENTS_LEN)


if __name__ == "__main__":
    unittest.main()
