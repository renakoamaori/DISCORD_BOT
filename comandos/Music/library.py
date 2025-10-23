from __future__ import annotations
import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from .constants import SUPPORTED_EXTS, CACHE_VERSION, MUSIC_CACHE_FILENAME
from .utils import file_stat
from .tags import read_tags_worker
import os

class LocalLibrary:
    f"""
    Artist -> Album -> [(trackno, Path)]
    Cache JSON en BASE/{MUSIC_CACHE_FILENAME}
    """
    def __init__(self, base: Path, cache_path: Optional[Path] = None):
        """
        Inicializa con ruta base y opcionalmente una ruta de caché.
        """
        self.base = base.resolve()
        self.cache_path = (cache_path or (self.base / MUSIC_CACHE_FILENAME)).resolve()
        self.data: Dict[str, Dict[str, List[Tuple[Optional[int], Path]]]] = {}
        self.last_stats: Dict[str, int] = {"total": 0, "cached": 0, "updated": 0, "removed": 0, "added": 0}

    def _load_cache(self) -> Dict[str, Any]:
        """
        Carga la caché desde disco si es válida (version/base coinciden).
        Devuelve {} si no hay caché válida.
        """
        try:
            if not self.cache_path.exists():
                return {}
            with self.cache_path.open("r", encoding="utf-8") as f:
                cache = json.load(f)
            if cache.get("version") != CACHE_VERSION:
                return {}
            if Path(cache.get("base", "")).resolve() != self.base:
                return {}
            files = cache.get("files")
            if not isinstance(files, dict):
                return {}
            return cache
        except Exception:
            return {}

    def _save_cache(self, files: Dict[str, Any]) -> None:
        """
        Persiste la caché atomizada (archivo temporal + rename).
        Guarda version, base, timestamp y el mapa de archivos.
        """
        try:
            blob = {
                "version": CACHE_VERSION, 
                "base": str(self.base), 
                "saved_at": int(time.time()), 
                "files": files
                }
            tmp = self.cache_path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(blob, f, ensure_ascii=False)
            tmp.replace(self.cache_path)
        except Exception:
            pass

    def clear(self):
        self.data.clear()
        self.last_stats = {"total": 0, "cached": 0, "updated": 0, "removed": 0, "added": 0}

    def scan(self, force_full: bool = False) -> None:
        """
        (Re)construye el índice: compara caché vs. disco, lee metadatos
        cuando hay cambios y actualiza la estructura Artist/Album/Tracks.
        """
        self.clear()
        if not self.base.exists():
            return

        current_files: List[str] = []
        for f in self.base.rglob("*"):
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS:
                current_files.append(f.resolve().as_posix())
        current_set = set(current_files)

        cache = {} if force_full else self._load_cache()
        cached_files: Dict[str, Any] = cache.get("files", {}) if cache else {}

        to_add_or_update: List[str] = []
        kept: Dict[str, Any] = {}
        removed_count = 0
        for path_str, meta in list(cached_files.items()):
            if path_str not in current_set:
                removed_count += 1
                continue
            try:
                size_now, mtime_now = file_stat(path_str)
            except FileNotFoundError:
                removed_count += 1
                continue
            if meta.get("size") != size_now or meta.get("mtime") != mtime_now:
                to_add_or_update.append(path_str)
            else:
                kept[path_str] = meta

        added_files = [p for p in current_files if p not in cached_files]
        to_add_or_update.extend(added_files)

        updated_entries: Dict[str, Any] = {}
        if to_add_or_update:
            max_workers = max(1, os.cpu_count() or 1)
            with ProcessPoolExecutor(max_workers=max_workers) as pool:
                futures = [pool.submit(read_tags_worker, p) for p in to_add_or_update]
                for _p, _fut in zip(to_add_or_update, as_completed(futures)):
                    pass
            for p in to_add_or_update:
                tags = read_tags_worker(p)
                size_now, mtime_now = file_stat(p)
                tags["size"] = size_now
                tags["mtime"] = mtime_now
                updated_entries[p] = tags

        merged: Dict[str, Any] = {}
        merged.update(kept)
        merged.update(updated_entries)

        for path_str, meta in merged.items():
            artist = meta.get("artist") or "Unknown Artist"
            album = meta.get("album") or "Unknown Album"
            trackno = meta.get("trackno")
            p = Path(path_str)
            albums = self.data.setdefault(artist, {})
            tracks = albums.setdefault(album, [])
            tracks.append((trackno if isinstance(trackno, int) else None, p))

        for _artist, albums in self.data.items():
            for _album, items in albums.items():
                items.sort(key=lambda it: (999999 if it[0] is None else it[0], it[1].name))

        self._save_cache(merged)
        self.last_stats = {
            "total": len(current_files), "cached": len(kept),
            "updated": len(to_add_or_update), "removed": removed_count,
            "added": len(added_files)
        }

    def artists(self) -> List[str]:
        return sorted(self.data.keys(), key=lambda s: s.lower())

    def albums(self, artist: str) -> List[str]:
        return sorted(self.data.get(artist, {}).keys(), key=lambda s: s.lower())

    def all_tracks(self) -> List[Path]:
        out: List[Path] = []
        for albums in self.data.values():
            for items in albums.values():
                out.extend([p for _tn, p in items])
        return out

    def tracks_by_artist(self, artist: str) -> List[Path]:
        out: List[Path] = []
        for items in self.data.get(artist, {}).values():
            out.extend([p for _tn, p in items])
        return out

    def tracks_by_album(self, artist: str, album: str) -> List[Path]:
        return [p for _tn, p in self.data.get(artist, {}).get(album, [])]