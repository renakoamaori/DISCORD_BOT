# comandos/Music/enqueue.py
from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Optional, Tuple, List
from .constants import MAX_CONC_ENQUEUE
from .utils import dprint

# ensure_playing(player, guild_id, first_track) -> Awaitable[None]
EnsurePlayingCB = Callable[[Any, int, Optional[Any]], Awaitable[None]]
# progress_cb(done: int, total: int) -> None  (no-async)
ProgressCB = Callable[[int, int], None]


async def enqueue_tracks_from_paths(
    *,
    node: Any,
    player: Any,
    guild_id: int,
    requester_id: int,
    paths: Iterable[Path],
    local_map: dict[str, Path],
    ensure_playing: EnsurePlayingCB,
    shuffle: bool = False,
    max_concurrency: int = MAX_CONC_ENQUEUE,
    progress_cb: Optional[ProgressCB] = None,
    debug_enabled: bool = False ) -> Tuple[int, int]:
    """
    Carga en paralelo y AÑADE AL PLAYER EN EL MISMO ORDEN DE ENTRADA.

    Estrategia:
      - Se lanza carga concurrente (node.get_tracks) con límite de semáforo.
      - Se acumulan resultados como (idx, track, path) a medida que llegan.
      - Se ordenan por idx (posición original) y recién ahí se hace player.add(...).
      - Se actualiza local_map con claves identifier/uri/identifier_local -> Path.
      - Al final, si se añadió al menos uno, ensure_playing(...) con la primera pista añadida.

    progress_cb(done, total) se invoca en cada resultado de carga exitosa (antes del add),
    usando 'done' relativo al conjunto pasado en 'paths'.
    """
    items: List[Path] = [p.resolve() for p in paths]
    if shuffle:
        import random
        random.shuffle(items)

    total = len(items)
    if total == 0:
        return (0, 0)

    sem = asyncio.Semaphore(max(1, int(max_concurrency)))

    async def _fetch_one(idx: int, path: Path) -> Optional[Tuple[int, Any, Path]]:
        identifier = path.as_posix()
        async with sem:
            try:
                lr = await node.get_tracks(identifier)
            except Exception as e:
                dprint(f"[enqueue] fallo get_tracks({identifier}): {e}", _enabled=debug_enabled)
                return None
        tracks = getattr(lr, "tracks", None) or []
        if not tracks:
            return None
        return (idx, tracks[0], path)

    tasks = [asyncio.create_task(_fetch_one(i, p)) for i, p in enumerate(items)]
    results: List[Tuple[int, Any, Path]] = []
    done_loads = 0
    failed = 0

    # Recogemos a medida que terminan las cargas
    for coro in asyncio.as_completed(tasks):
        res = await coro
        if res is None:
            failed += 1
            continue
        results.append(res)
        done_loads += 1
        if progress_cb:
            try:
                progress_cb(done_loads, total)
            except Exception:
                pass

    # Orden estable por índice original
    results.sort(key=lambda t: t[0])

    # Ahora, recién añadimos al player en orden
    added = 0
    first_added_track: Optional[Any] = None
    for _, track, path in results:
        try:
            player.add(requester=requester_id, track=track)
        except Exception as e:
            dprint(f"[enqueue] fallo player.add: {e}", _enabled=debug_enabled)
            failed += 1
            continue

        # mapear posibles claves -> Path
        try:
            ident = getattr(track, "identifier", None)
            uri = getattr(track, "uri", None)
            identifier_local = path.as_posix()
            for key in (ident, uri, identifier_local):
                if isinstance(key, str):
                    local_map[key] = path
        except Exception:
            local_map[path.as_posix()] = path

        if first_added_track is None:
            first_added_track = track

        added += 1

    # Garantizar reproducción si añadimos al menos uno
    if first_added_track is not None:
        try:
            await ensure_playing(player, guild_id, first_added_track)
        except Exception as e:
            dprint(f"[enqueue] ensure_playing fallo: {e}", _enabled=debug_enabled)

    return (added, failed)
