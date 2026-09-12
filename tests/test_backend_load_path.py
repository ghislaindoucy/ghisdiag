"""
Tests du chemin de chargement du backend capteurs (collectors/lhm_backend.py)
— audit du 13/09/2026.

L'exe chargeait les DLL LibreHardwareMonitor depuis %LOCALAPPDATA%\\Ghisdiag\\tools
et depuis $GHISDIAG_TOOLS_DIR, tous deux inscriptibles par l'utilisateur courant
même quand Ghisdiag tourne en administrateur. Un malware sans privilèges y
déposait une DLL, chargée ensuite EN ADMIN par Assembly.LoadFrom (sensors.ps1) :
élévation de privilèges. Désormais l'exe ne consulte plus que des dossiers de
confiance (à côté de l'exe, ou l'embarqué).

Lancement :  py -m unittest discover -s tests -v
"""

import os
import tempfile

os.environ.setdefault("GHISDIAG_LOG_DIR",
                      os.path.join(tempfile.gettempdir(), "ghisdiag_tests"))

import sys
import unittest
from pathlib import Path

from collectors import lhm_backend as L

_BS = os.sep


class _FrozenBase(unittest.TestCase):
    def setUp(self):
        self._saved = {k: getattr(sys, k, None) for k in ("frozen", "_MEIPASS", "executable")}
        self._env = os.environ.get("GHISDIAG_TOOLS_DIR")

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                if hasattr(sys, k):
                    delattr(sys, k)
            else:
                setattr(sys, k, v)
        if self._env is None:
            os.environ.pop("GHISDIAG_TOOLS_DIR", None)
        else:
            os.environ["GHISDIAG_TOOLS_DIR"] = self._env

    def _make_frozen(self, root):
        sys.frozen = True
        sys.executable = str(Path(root) / "Ghisdiag.exe")
        sys._MEIPASS = str(Path(root) / "_internal")


class LoadPathTests(_FrozenBase):

    def test_production_exclut_localappdata_et_env(self):
        self._make_frozen(r"C:\App")
        os.environ["GHISDIAG_TOOLS_DIR"] = r"X:\attaquant"
        dirs = [str(d) for d in L._candidate_dirs()]
        joined = " | ".join(dirs).lower()
        self.assertNotIn("attaquant", joined)                       # env ignorée
        self.assertNotIn(("local" + _BS + "ghisdiag").lower(), joined)  # %LOCALAPPDATA% ignoré
        # Seuls exe-adjacent + embarqué.
        self.assertTrue(any(d.lower().endswith("app" + _BS + "tools") for d in dirs))

    def test_production_embarque_toujours_en_repli(self):
        self._make_frozen(r"C:\App")
        dirs = [str(d) for d in L._candidate_dirs()]
        self.assertEqual(dirs[-1], str(L.embedded_tools_dir()))

    def test_dev_autorise_env_pas_localappdata(self):
        # Hors frozen : l'override par variable reste pratique pour les tests,
        # sans frontière de privilèges (on exécute depuis les sources).
        for k in ("frozen", "_MEIPASS"):
            if hasattr(sys, k):
                delattr(sys, k)
        os.environ["GHISDIAG_TOOLS_DIR"] = r"X:\dev"
        dirs = [str(d) for d in L._candidate_dirs()]
        self.assertTrue(any("dev" in d.lower() for d in dirs))
        self.assertNotIn(("local" + _BS + "ghisdiag").lower(),
                         " | ".join(dirs).lower())

    def test_dest_installation_est_de_confiance(self):
        # La mise à jour dépose là où l'exe ira lire : à côté de l'exe.
        self._make_frozen(r"C:\App")
        self.assertEqual(L._default_install_dest(), L.exe_tools_dir())
        self.assertTrue(str(L._default_install_dest()).lower().endswith("app" + _BS + "tools"))


if __name__ == "__main__":
    unittest.main()
