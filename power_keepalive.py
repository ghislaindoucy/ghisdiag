"""
Ghisdiag - Blocage de la mise en veille.

Repose sur SetThreadExecutionState (kernel32). Deux contraintes de cette API
dictent toute la conception :

1. L'etat pose avec ES_CONTINUOUS appartient au THREAD qui l'a pose et
   disparait quand ce thread se termine. On garde donc un thread dedie vivant
   tant que l'application tourne, au lieu d'appeler l'API depuis le thread
   tkinter (qui, lui, va et vient dans les callbacks).
2. L'etat disparait aussi avec le processus. Le blocage ne survit donc PAS a
   la fermeture de Ghisdiag : c'est une propriete du systeme, pas un reglage
   qu'on pourrait persister, et l'interface doit le dire.

Plusieurs demandeurs peuvent coexister (l'interrupteur de l'onglet Setup et le
bench thermique, qui bloque la veille le temps du test). Chacun pose et retire
sa propre raison ; la veille n'est rendue que lorsque la derniere est levee.

acquire() et release() rendent l'etat REEL confirme par Windows, pas l'intention
- l'interface doit pouvoir dire << refuse >> plutot que d'afficher un blocage
imaginaire.
"""
import ctypes
import logging
import threading
import time

logger = logging.getLogger(__name__)

# Constantes Windows (winbase.h)
ES_CONTINUOUS       = 0x80000000
ES_SYSTEM_REQUIRED  = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

# Re-affirmation periodique. ES_CONTINUOUS suffit en theorie ; ce rappel couvre
# le cas ou un autre composant remet l'etat a zero pendant un bench de 17 min.
_REASSERT_SEC = 30.0

_cond = threading.Condition(threading.RLock())

_reasons: dict[str, bool] = {}      # raison -> garder aussi l'ecran allume
_thread: threading.Thread | None = None
_stop        = False
_active      = False                # veille bloquee, d'apres la reponse de l'API
_gen         = 0                    # incremente a chaque changement de raisons
_applied_gen = -1                   # derniere generation reellement appliquee


def _set_execution_state(flags: int) -> bool:
    """Appelle SetThreadExecutionState. Rend False si Windows refuse.

    Isole dans une fonction pour que les tests puissent la remplacer sans
    toucher a l'etat energetique de la machine qui les execute.
    """
    try:
        fn = ctypes.windll.kernel32.SetThreadExecutionState
        fn.argtypes = [ctypes.c_uint32]
        fn.restype  = ctypes.c_uint32
        return fn(ctypes.c_uint32(flags)) != 0
    except Exception as exc:          # non-Windows, ou API indisponible
        logger.debug("SetThreadExecutionState indisponible : %s", exc)
        return False


def _wanted_flags() -> tuple[int, bool]:
    """(drapeaux a poser, la veille est-elle censee etre bloquee)."""
    with _cond:
        if not _reasons:
            return ES_CONTINUOUS, False        # rend la main au systeme
        flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        if any(_reasons.values()):
            flags |= ES_DISPLAY_REQUIRED
        return flags, True


def _worker():
    """Porte l'etat d'execution. Vit jusqu'a shutdown() : voir contrainte 1."""
    global _active, _applied_gen
    while True:
        with _cond:
            gen = _gen
        flags, blocking = _wanted_flags()
        ok = _set_execution_state(flags)

        with _cond:
            _active = bool(blocking and ok)
            _applied_gen = gen
            if blocking and not ok:
                logger.warning("Blocage de la mise en veille refuse par Windows")
            _cond.notify_all()
            if _stop:
                break
            if gen == _gen:
                _cond.wait(_REASSERT_SEC)

    # Liberation depuis le thread proprietaire de l'etat.
    _set_execution_state(ES_CONTINUOUS)
    with _cond:
        _active = False
        _cond.notify_all()


def _ensure_thread():
    global _thread
    with _cond:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_worker, name="ghisdiag-keepalive",
                                   daemon=True)
        _thread.start()


def _apply(timeout: float) -> bool:
    """Signale le changement au porteur d'etat et attend l'appel systeme.

    On attend la generation courante et pas un simple drapeau : sinon un
    acquire() pourrait lire le resultat de l'appel precedent et affirmer un
    blocage que Windows vient tout juste de refuser.
    """
    global _gen
    with _cond:
        _gen += 1
        my_gen = _gen
        _cond.notify_all()

    _ensure_thread()

    deadline = time.monotonic() + timeout
    with _cond:
        while _applied_gen < my_gen:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            _cond.wait(left)
        return _active


def acquire(reason: str, keep_display: bool = False, timeout: float = 3.0) -> bool:
    """Bloque la mise en veille au nom de `reason`. Rend l'etat REEL obtenu.

    `keep_display` maintient aussi l'ecran allume (inutile pour un bench, utile
    quand le technicien veut garder la machine visible).
    """
    with _cond:
        _reasons[reason] = bool(keep_display)
    return _apply(timeout)


def release(reason: str, timeout: float = 3.0) -> bool:
    """Leve la raison `reason`. La veille n'est rendue qu'a la derniere."""
    with _cond:
        _reasons.pop(reason, None)
    return _apply(timeout)


def is_active() -> bool:
    """Vrai si la veille est bloquee et que Windows l'a confirme."""
    with _cond:
        return _active


def reasons() -> set[str]:
    with _cond:
        return set(_reasons)


def shutdown(timeout: float = 3.0):
    """Rend la main au systeme et arrete le thread (fermeture de l'app, tests)."""
    global _stop, _thread, _gen
    with _cond:
        _reasons.clear()
        _stop = True
        _gen += 1
        _cond.notify_all()
        th = _thread
    if th is not None and th.is_alive():
        th.join(timeout)
    with _cond:
        _stop = False       # reutilisable (les tests enchainent les scenarios)
        _thread = None
