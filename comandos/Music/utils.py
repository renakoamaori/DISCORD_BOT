from __future__ import annotations
from pathlib import Path
from typing import Tuple, Iterable

# ---------------------- Helper de depuración ----------------------
def dprint(*a, **k):
    """
    Imprime con prefijo [music] si _enabled=True.
    """
    if k.pop("_enabled", False):
        print("[music]", *a, **k)

def strip_discord_wrapping(s: str) -> str:
    """
    Remueve <...>, "..." o '...' y \u200b de los extremos.
    """
    s = s.strip().strip("\u200b")
    if len(s) >= 2 and (
        (s[0] == s[-1] and s[0] in ("'", '"')) or
        (s[0] == "<" and s[-1] == ">")
    ):
        s = s[1:-1]
    return s

def norm(s: str) -> str:
    """
    Normaliza de forma simple para comparaciones: trim + lower.
    """
    return s.strip().lower()

def is_subpath(child: Path, base: Path) -> bool:
    """
    True si 'child' está dentro de 'base' (ambas absolutas o relativas).
    """
    try:
        child.resolve().relative_to(base.resolve())
        return True
    except Exception:
        return False

def file_stat(path_str: str) -> Tuple[int, int]:
    """
    Devuelve (size_bytes, mtime_epoch_int) de un archivo.
    """
    p = Path(path_str)
    st = p.stat()
    return (st.st_size, int(st.st_mtime))

def popleft_many(q: Iterable, k: int) -> int:
    """
    Elimina hasta k elementos desde el inicio de una cola 'q' (deque, lista, etc.).
    Devuelve cuántos fueron removidos.
    """
    if k <= 0:
        return 0
    try:
        if hasattr(q, "popleft"):
            removed = 0
            for _ in range(k):
                try:
                    q.popleft()  # type: ignore[attr-defined]
                    removed += 1
                except Exception:
                    break
            return removed
        if hasattr(q, "__delitem__"):
            try:
                n = len(q)  # type: ignore[arg-type]
                r = min(k, n)
                if r > 0:
                    del q[:r]  # type: ignore[index]
                return r
            except Exception:
                removed = 0
                for _ in range(k):
                    try:
                        q.pop(0)  # type: ignore[attr-defined]
                        removed += 1
                    except Exception:
                        break
                return removed
    except Exception:
        pass
    return 0