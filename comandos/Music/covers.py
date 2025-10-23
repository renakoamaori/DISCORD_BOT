from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Optional, List, Tuple, cast, Callable, Any
from .constants import COVER_CAND_NAMES, COVER_EXTS, EMBED_COLOR_PRIMARY
from io import BytesIO
import discord

# mutagen es opcional: protege los imports para no romper en entornos sin mutagen
try:
    from mutagen.flac import FLAC
except Exception:  # pragma: no cover
    FLAC = None  # type: ignore

try:
    from mutagen.mp4 import MP4, MP4Cover
except Exception:  # pragma: no cover
    MP4 = None  # type: ignore
    MP4Cover = None  # type: ignore

try:
    from mutagen.id3 import ID3
except Exception:  # pragma: no cover
    ID3 = None  # type: ignore

try:
    import mutagen
except Exception:  # pragma: no cover
    mutagen = None  # type: ignore

def _find_cover_in_dir(track_path: Path) -> Optional[Path]:
    """
    Busca portada en el directorio del track, priorizando:
    1) Imagen cuyo *stem* sea igual al del track.
    2) Imagen cuyo nombre sea exactamente uno de COVER_CAND_NAMES.
    3) Imagen cuyo nombre contenga alguna keyword de COVER_CAND_NAMES.
    Devuelve la primera ruta (ordenada) que cumpla.
    """
    d = track_path.parent
    base = track_path.stem.lower()
    exact_hits: List[Path] = []
    keyword_hits: List[Path] = []
    try:
        for f in d.iterdir():
            if not f.is_file():
                continue
            name, ext = f.stem.lower(), f.suffix.lower()
            if ext not in COVER_EXTS:
                continue
            if name == base or name in COVER_CAND_NAMES:
                exact_hits.append(f.resolve())
                continue
            for kw in COVER_CAND_NAMES:
                if kw in name:
                    keyword_hits.append(f.resolve())
                    break
        if exact_hits:
            return sorted(exact_hits)[0]
        if keyword_hits:
            return sorted(keyword_hits)[0]
    except Exception:
        pass
    return None

def _extract_embedded_cover_bytes(track_path: Path) -> Optional[Tuple[bytes, str]]:
    """
    Extrae las portadas incrustadas de los archivos de música
    """
    try:
        suffix = track_path.suffix.lower()
        if suffix == ".flac" and FLAC is not None:
            f = FLAC(track_path.as_posix())
            if f.pictures:
                pic = f.pictures[0]
                mime = (pic.mime or "").lower()
                ext = "png" if "png" in mime else "jpg"
                return pic.data, ext
        elif suffix in {".m4a", ".mp4", ".aac"} and MP4 is not None:
            m = MP4(track_path.as_posix())
            covr = m.tags.get("covr") if m.tags else None
            if covr:
                c = covr[0]
                data = bytes(c)
                ext = "jpg"
                if MP4Cover is not None and isinstance(c, MP4Cover) and getattr(c, "imageformat", None) == MP4Cover.FORMAT_PNG:
                    ext = "png"
                return data, ext
        elif suffix == ".mp3" and ID3 is not None:
            id3 = ID3(track_path.as_posix())
            apics = id3.getall("APIC")
            if apics:
                ap = apics[0]
                mime = (getattr(ap, "mime", "") or "").lower()
                ext = "png" if "png" in mime else "jpg"
                return bytes(ap.data), ext
    except Exception:
        pass
    return None

async def build_local_now_embed(track_path: Path) -> Tuple[discord.Embed, Optional[discord.File]]:
    """
    Construye un embed que muestra la info del track actual
    """
    def _read():
        m_file = cast(Callable[..., Any], getattr(mutagen, "File", None))
        m = m_file(track_path.as_posix(), easy=True) if m_file else None
        artist = album = None
        title = track_path.stem
        if m:
            a = m.get("artist");  artist = a[0].strip() if a and a[0].strip() else None
            al = m.get("album");  album  = al[0].strip() if al and al[0].strip() else None
            t = m.get("title");   title  = t[0].strip() if t and t[0].strip() else title
        return title, artist, album

    title, artist, album = await asyncio.to_thread(_read)

    embed = discord.Embed(
        title=title, colour=EMBED_COLOR_PRIMARY,
        description=f"**Artista**: {artist or 'Desconocido'}\n**Álbum**: {album or 'Desconocido'}"
    )
    cover_file: Optional[discord.File] = None
    cover_path = _find_cover_in_dir(track_path)
    if cover_path and cover_path.exists():
        filename = f"cover{cover_path.suffix.lower()}"
        cover_file = discord.File(cover_path.as_posix(), filename=filename)
        embed.set_thumbnail(url=f"attachment://{filename}")
    else:
        emb = await asyncio.to_thread(_extract_embedded_cover_bytes, track_path)
        if emb is not None:
            data, ext = emb
            filename = f"cover.{ext}"
            cover_file = discord.File(BytesIO(data), filename=filename)
            embed.set_thumbnail(url=f"attachment://{filename}")
    return embed, cover_file