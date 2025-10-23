from __future__ import annotations
from typing import Optional, Dict, cast, Callable, Any
from pathlib import Path

try:
    import mutagen
except ImportError:
    mutagen = None

def read_tags_worker(path_str: str) -> Dict[str, Any]:
    p = Path(path_str)
    artist = "Unknown Artist"
    album = "Unknown Album"
    title = p.stem
    trackno: Optional[int] = None
    try:
        m_file = cast(Callable[..., Any], getattr(mutagen, "File", None))
        m = m_file(p.as_posix(), easy=True) if m_file else None
        if m:
            a = m.get("artist")
            if a and a[0].strip():
                artist = a[0].strip()
            al = m.get("album")
            if al and al[0].strip():
                album = al[0].strip()
            t = m.get("title")
            if t and t[0].strip():
                title = t[0].strip()
            tn = m.get("tracknumber")
            if tn and tn[0].strip():
                raw = tn[0].strip()
                try:
                    trackno = int(raw.split("/")[0])
                except Exception:
                    trackno = None
    except Exception:
        pass
    return {"artist": artist, "album": album, "title": title, "trackno": trackno}