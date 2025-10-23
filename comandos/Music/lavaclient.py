from __future__ import annotations
import os
from typing import Awaitable, Callable
import lavalink

OnTrackStartCB = Callable[[int, object], Awaitable[None]]
OnQueueEndCB  = Callable[[int], Awaitable[None]]

def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    v = v.strip().lower()
    return v in ("1", "true", "yes", "on", "y")

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip())
    except Exception:
        return default

async def init_lavalink(bot) -> lavalink.Client:
    """
    Crea y configura el cliente de Lavalink y añade el nodo principal.
    Expone el handler de voice update en el bot para el VoiceProtocol.
    """
    user = bot.user
    if user is None:
        await bot.wait_until_ready()
        user = bot.user
    assert user is not None, "Bot user aún no disponible"

    ll = lavalink.Client(user_id=user.id)

    host = os.getenv("LAVALINK_HOST", "127.0.0.1")
    port = _env_int("LAVALINK_PORT", 2333)
    password = os.getenv("LAVALINK_PASSWORD", "contraseña")
    region = os.getenv("LAVALINK_REGION", "us")
    name = os.getenv("LAVALINK_NAME", "main")
    use_ssl = _env_bool("LAVALINK_SSL", False)

    ll.add_node(host=host, port=port, password=password, region=region, name=name, ssl=use_ssl)
    setattr(bot, "_ll_voice_update", ll.voice_update_handler)
    return ll

def add_event_hooks(ll: lavalink.Client, on_track_start: OnTrackStartCB, on_queue_end: OnQueueEndCB) -> None:
    """
    Registra un solo hook que enruta a los callbacks del Cog.
    Mantiene compatibilidad con lavalink.py v3/v4 (tipos de eventos).
    """
    async def _hook(event):
        # Según versión, los eventos pueden venir con nombres/clases distintas.
        # Usamos duck-typing y getattr para evitar romper en cambios menores.
        etype = type(event).__name__

        # guild_id: en v4 suele venir en event.player.guild_id (string) o event.player.guild_id int
        guild_id = None
        player = getattr(event, "player", None)
        if player is not None:
            gid = getattr(player, "guild_id", None)
            try:
                guild_id = int(gid) if gid is not None else None
            except Exception:
                pass

        # TrackStart
        if etype.endswith("TrackStartEvent") or etype == "TrackStartEvent":
            if guild_id is not None:
                track = getattr(event, "track", None)
                await on_track_start(guild_id, track)
            return

        # QueueEnd
        if etype.endswith("QueueEndEvent") or etype == "QueueEndEvent":
            if guild_id is not None:
                await on_queue_end(guild_id)
            return

        # Otros eventos: ignora silenciosamente
        return

    ll.add_event_hook(_hook)

def get_first_node(ll: lavalink.Client):
    """
    Retorna el primer nodo disponible (o None).
    Útil para comandos de diagnóstico.
    """
    nm = getattr(ll, "node_manager", None)
    if nm is None:
        return None
    # v4: node_manager.nodes (list-like)
    nodes = getattr(nm, "nodes", None)
    if isinstance(nodes, list) and nodes:
        return nodes[0]
    # fallback v3: get_node() o estructuras similares
    get_node = getattr(nm, "get_node", None)
    if callable(get_node):
        try:
            return get_node()
        except Exception:
            return None
    return None
