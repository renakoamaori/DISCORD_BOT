# comandos/Music/monitor.py
from __future__ import annotations
import asyncio
import time
from typing import Any, Callable, Iterable
from .constants import (
    AUTO_DC_IDLE_SECONDS,
    AUTO_DC_POLL_PERIOD,
    AUTO_DC_MESSAGE,
)
from .utils import dprint


# Tipos de callback que se inyectan desde el Cog:
# - get_all_players(): Iterable[Any]          -> retorna todos los players activos de lavalink
# - get_announce_channel(guild_id:int) -> Optional[discord.abc.Messageable]
GetPlayersCB = Callable[[], Iterable[Any]]
GetAnnounceCB = Callable[[int], Any]  # retorna canal o None


async def _auto_disconnect_monitor_loop(
    *,
    get_all_players: GetPlayersCB,
    get_announce_channel: GetAnnounceCB,
    idle_seconds: int = AUTO_DC_IDLE_SECONDS,
    poll_period: int = AUTO_DC_POLL_PERIOD,
    debug_enabled: bool = False ) -> None:
    """
    Bucle principal del monitor:
      - Recorre periódicamente todos los players (guilds).
      - Si un player NO está reproduciendo, NO tiene cola y está conectado,
        espera 'idle_seconds' acumulados y desconecta.
      - Envía AUTO_DC_MESSAGE al canal de anuncios si existe.
    """
    # Mapa para acumular tiempo de inactividad por guild
    idle_since: dict[int, float] = {}

    while True:
        try:
            now = time.monotonic()
            for player in list(get_all_players() or []):
                # Obtención de datos mínimos, con duck-typing
                gid = getattr(player, "guild_id", None)
                if gid is None:
                    continue

                # Estados del player
                is_playing = bool(getattr(player, "is_playing", False))
                current = getattr(player, "current", None)
                queue = getattr(player, "queue", None) or []
                connected = bool(getattr(player, "channel_id", None))

                # Condición de "inactivo": sin reproducción actual y sin cola
                inactive = (not is_playing) and (current is None) and (len(queue) == 0) and connected

                if inactive:
                    # comenzar/incrementar contador de inactividad
                    if gid not in idle_since:
                        idle_since[gid] = now
                    # si excede el umbral -> desconectar
                    if (now - idle_since[gid]) >= idle_seconds:
                        # intentar obtener el canal de anuncios
                        ch = get_announce_channel(int(gid))
                        if ch is not None and AUTO_DC_MESSAGE:
                            try:
                                await ch.send(AUTO_DC_MESSAGE)
                            except Exception:
                                pass
                        # desconectar del canal de voz (vía player)
                        try:
                            await player.disconnect()
                        except Exception as e:
                            dprint(f"[monitor] disconnect fallo (guild={gid}): {e}", _enabled=debug_enabled)
                        # limpiar contador para ese guild
                        idle_since.pop(gid, None)
                else:
                    # si vuelve actividad, resetea el contador
                    if gid in idle_since:
                        idle_since.pop(gid, None)

        except asyncio.CancelledError:
            # Finalización ordenada del task
            raise
        except Exception as e:
            dprint(f"[monitor] excepción en loop: {e}", _enabled=debug_enabled)

        await asyncio.sleep(max(1, int(poll_period)))


def start_monitor(
    *,
    loop: asyncio.AbstractEventLoop,
    get_all_players: GetPlayersCB,
    get_announce_channel: GetAnnounceCB,
    idle_seconds: int = AUTO_DC_IDLE_SECONDS,
    poll_period: int = AUTO_DC_POLL_PERIOD,
    debug_enabled: bool = False ) -> asyncio.Task:
    """
    Arranca el task del monitor y devuelve el handle (asyncio.Task).
    El caller (Cog) debe conservar este handle para cancelarlo en cog_unload().
    """
    return loop.create_task(
        _auto_disconnect_monitor_loop(
            get_all_players=get_all_players,
            get_announce_channel=get_announce_channel,
            idle_seconds=idle_seconds,
            poll_period=poll_period,
            debug_enabled=debug_enabled,
        )
    )