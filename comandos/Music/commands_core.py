from __future__ import annotations
import time
import os
from pathlib import Path
from typing import Any, Dict, Optional, cast, Union
import discord
from discord.ext import commands
import lavalink
from .constants import (
    ANNOUNCE_DEDUP_SECONDS,
    MUSIC_DEBUG,
    EMBED_COLOR_PRIMARY,
    VOL_MIN,
    VOL_MAX,
    MUSIC_BASE_ENV
)
from .utils import dprint
from .covers import build_local_now_embed
from .library import LocalLibrary
from .lavaclient import init_lavalink, add_event_hooks
from .monitor import start_monitor
from .voice import LavalinkVoiceClient
import asyncio

class Music(commands.Cog):
    """Cog base"""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # base_path: raíz del proyecto; music_base_path: carpeta de música local.
        self.base_path: Optional[Path] = None
        self.music_base_path: Optional[Path] = None

        # Librería local (se setea cuando esté music_base_path)
        self.lib: Optional[LocalLibrary] = None

        # Lavalink client
        self._ll: Optional[lavalink.Client] = None

        # Estado de anuncios por guild
        self._announce_ch: Dict[int, int] = {}  # guild_id -> channel_id

        # Dedupe de “now playing”
        self._last_announced: Dict[int, str] = {}
        self._last_announced_ts: Dict[int, float] = {}

        # Mapa de tracks locales: identifier/uri/pathposix -> Path
        self._local_map: Dict[str, Path] = {}

        # Handle del monitor
        self._monitor_task = None

    # --------------- Ciclo de vida del Cog ---------------
    async def cog_load(self) -> None:
        """
        Se ejecuta cuando el Cog es cargado. Inicializa Lavalink, eventos y monitor.
        """
        # Inicializa cliente de Lavalink y expone voice_update handler
        self._ll = await init_lavalink(self.bot)

        # Callbacks de eventos
        async def _on_track_start(gid: int, track: Any) -> None:
            ident = str(
                self._track_attr(track, "identifier", "")
                or self._track_attr(track, "uri", "")
                or ""
            )
            now = time.monotonic()
            last_id = self._last_announced.get(gid)
            last_ts = self._last_announced_ts.get(gid, 0.0)
            if ident and (ident == last_id) and (now - last_ts < ANNOUNCE_DEDUP_SECONDS):
                dprint("dedup TrackStartEvent", _enabled=MUSIC_DEBUG)
                return
            if ident:
                self._last_announced[gid] = ident
                self._last_announced_ts[gid] = now

            ch = self._get_announce_channel(gid)
            if not ch:
                return

            # Resolver si el track es local (mapeado)
            p = self._resolve_local_path(track)
            if p is not None and p.exists():
                try:
                    embed, cover_file = await build_local_now_embed(p)
                    if cover_file:
                        await ch.send(embed=embed, file=cover_file)
                    else:
                        await ch.send(embed=embed)
                except Exception:
                    # Si algo falla con portada/embeds, al menos anuncia el título
                    title = self._track_attr(track, "title", "(sin título)") or "(sin título)"
                    await ch.send(f"▶ **{title}**")
                return

            # No es local: anuncia con texto mínimo
            title = self._track_attr(track, "title", "(sin título)") or "(sin título)"
            await ch.send(f"▶ **{title}**")

        async def _on_queue_end(gid: int) -> None:
            ch = self._get_announce_channel(gid)
            if ch:
                try:
                    await ch.send("✅ **Cola terminada.**")
                except Exception:
                    pass

        add_event_hooks(self.ll, _on_track_start, _on_queue_end)

        # Iniciar monitor de auto-desconexión
        def _get_players():
            pm = getattr(self.ll, "player_manager", None)
            return list(getattr(pm, "players", []) or []) if pm else []

        def _get_ann(gid: int):
            return self._get_announce_channel(gid)

        self._monitor_task = start_monitor(
            loop=self.bot.loop,
            get_all_players=_get_players,
            get_announce_channel=_get_ann,
            debug_enabled=MUSIC_DEBUG,
        )

        env_base = os.getenv(MUSIC_BASE_ENV, "")
        if env_base:
            try:
                p = Path(env_base).expanduser().resolve()
                if p.exists() and p.is_dir():
                    self.music_base_path = p
                    self.base_path = p.parent
                    self.lib = LocalLibrary(p)
                    dprint(f"[music] MUSIC_BASE autoload: {p}", _enabled=MUSIC_DEBUG)
                else:
                    dprint(f"[music] MUSIC_BASE inválida: {p}", _enabled=MUSIC_DEBUG)
            except Exception as e:
                dprint(f"[music] fallo leyendo MUSIC_BASE: {e}", _enabled=MUSIC_DEBUG)

    async def cog_unload(self) -> None:
        # 1) Cancelar monitor
        try:
            if self._monitor_task:
                self._monitor_task.cancel()
                await self._monitor_task
        except Exception:
            pass

        # 2) Limpiar el hook de voice_update si es el nuestro
        try:
            h_bot = getattr(self.bot, "_ll_voice_update", None)
            h_ours = getattr(self.ll, "voice_update_handler", None) if self._ll else None
            if h_bot is h_ours:
                delattr(self.bot, "_ll_voice_update")
        except Exception:
            pass

    # --------------- Propiedad/Accesores básicos ---------------
    @property
    def ll(self) -> lavalink.Client:
        if self._ll is None:
            raise RuntimeError("Lavalink no inicializado aún.")
        return self._ll

    # --------------- Utilidades internas usadas por los comandos ---------------
    def _track_attr(self, track: Any, attr: str, default: Optional[str] = None) -> Optional[str]:
        """
        Helper interno: obtiene un atributo conocido de un 'track' de Lavalink
        tolerando diferencias de versión (v3/v4) y posibles dicts.
        """
        if track is None:
            return default
        # objeto con atributos
        val = getattr(track, attr, None)
        if isinstance(val, str) and val.strip():
            return val
        # dict-like
        if isinstance(track, dict):
            v = track.get(attr)
            if isinstance(v, str) and v.strip():
                return v
        return default

    def _get_announce_channel(self, guild_id: int) -> Optional[discord.abc.Messageable]:
        """
        Devuelve el canal de anuncios registrado para el guild, si existe.
        """
        ch_id = self._announce_ch.get(guild_id)
        if not ch_id:
            return None
        ch = self.bot.get_channel(ch_id)
        if isinstance(ch, (discord.TextChannel, discord.Thread)):
            return ch
        return None

    def _resolve_local_path(self, track: Any) -> Optional[Path]:
        """
        Resuelve el Path local asociado a un 'track' (por identifier/uri/pathposix).
        """
        ident = self._track_attr(track, "identifier")
        if isinstance(ident, str) and ident in self._local_map:
            return self._local_map[ident]
        uri = self._track_attr(track, "uri")
        if isinstance(uri, str) and uri in self._local_map:
            return self._local_map[uri]
        # Algunas fuentes locales usan el path absoluto como identifier/uri
        if isinstance(ident, str):
            p = self._local_map.get(ident)
            if p:
                return p
        return None
    
    async def _ensure_player(self, guild: discord.Guild) -> Any:
        """
        Garantiza un player para el guild (crea si no existe).
        """
        pm = self.ll.player_manager
        player = pm.create(guild.id)
        return player

    async def _ensure_playing(self, player: Any, guild_id: int, first_track: Optional[Any] = None) -> None:
        """
        Inicia la reproducción si el player está detenido y hay cola.
        """
        try:
            is_playing = bool(getattr(player, "is_playing", False))
            current = getattr(player, "current", None)
            queue = getattr(player, "queue", None) or []
            if not is_playing and current is None and queue:
                await player.play()
        except Exception:
            # fallback best-effort
            try:
                await player.play()
            except Exception:
                pass

    async def _connect(
    self,
    ctx: commands.Context,
    channel: Optional[Union[discord.VoiceChannel, discord.StageChannel]] = None,
) -> Optional[discord.VoiceState]:
        """
        Conecta (o mueve) al bot al canal de voz.
        - Si 'channel' es None, usa el canal de voz del autor del comando.
        - Maneja clientes de voz previos (mover si es LavalinkVoiceClient, 
        desconectar si es otro).
        - Espera a que el player de Lavalink quede conectado (hasta ~6s).
        - Quita suppress en Stage si aplica.
        - Registra el canal de texto actual como canal de anuncios.
        """
        # 1) Resolver guild y canal destino
        guild = cast(discord.Guild, ctx.guild)
        if channel is None:
            member = cast(discord.Member, ctx.author)
            if not member.voice or not member.voice.channel:
                await ctx.reply("Debes estar en un canal de voz.")
                return None
            channel = member.voice.channel

        if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            await ctx.reply("Tipo de canal no soportado.")
            return None
        dest = channel

        # 2) Conectar / mover / reemplazar cliente de voz
        vc_proto = guild.voice_client
        try:
            if vc_proto is None:
                await dest.connect(cls=LavalinkVoiceClient, self_deaf=True)
            else:
                if isinstance(vc_proto, LavalinkVoiceClient):
                    cur = getattr(vc_proto, "channel", None)
                    if getattr(cur, "id", None) != dest.id:
                        await vc_proto.move_to(dest, self_deaf=True)
                else:
                    try:
                        await vc_proto.disconnect(force=True)
                    except Exception as e:
                        dprint(f"[voice] fallo al desconectar cliente no Lavalink: {e}", _enabled=MUSIC_DEBUG)
                    await dest.connect(cls=LavalinkVoiceClient, self_deaf=True)
        except discord.ClientException as e:
            dprint(f"[voice] aviso: {e}", _enabled=MUSIC_DEBUG)
            # No interrumpimos: intentaremos igual preparar player
        except Exception as e:
            await ctx.reply(f"No pude conectar al canal de voz: {e!s}")
            return None

        # 3) Esperar que el player esté listo
        player = await self._ensure_player(guild)
        for _ in range(12):  # ~6s
            if getattr(player, "channel_id", None) or getattr(player, "is_connected", False):
                break
            await asyncio.sleep(0.5)

        # 4) Stage: quitar suppress o avisar
        if isinstance(dest, discord.StageChannel):
            try:
                me = guild.me
                if me and me.voice and me.voice.suppress:
                    await me.edit(suppress=False)
            except Exception:
                try:
                    await ctx.send("Estoy en un Stage: promuéveme a speaker o muéveme a un canal de voz normal.")
                except Exception:
                    pass  # ignora si no puede mandar mensaje

        # 5) Registrar canal de anuncios
        if ctx.guild and isinstance(ctx.channel, discord.TextChannel):
            self._announce_ch[ctx.guild.id] = ctx.channel.id

        # 6) Devolver estado del miembro (opcionalmente útil para el caller)
        return cast(discord.Member, ctx.author).voice

    @commands.guild_only()
    @commands.hybrid_command(name="infomusica", description="Lista de comandos de música disponibles.")
    async def infomusica(self, ctx: commands.Context):
        # Detectar prefijo para ejemplos
        pref = getattr(self.bot, "default_prefix", None) or getattr(ctx, "clean_prefix", None) or "!"
        def both(cmd: str, args: str = "") -> str:
            args = args.strip()
            s_form = f"/{cmd} {args}".rstrip()
            p_form = f"{pref}{cmd} {args}".rstrip()
            return f"• {s_form}  |  `{p_form}`"

        embed = discord.Embed(
            title="Comandos de Música",
            description=(
                "Usa **slash** o **prefijo** indistintamente. "
                "Entre `< >` son obligatorios y `[ ]` opcionales.\n"
                "_Tip:_ rutas locales entre comillas o `<...>`."
            ),
            colour=EMBED_COLOR_PRIMARY,
        )
        embed.add_field(
            name="▶ Reproducción",
            value="\n".join([
                both("play", "<consulta|url|ruta>") + " — Link, **playlist YouTube** o **archivo local**.",
                both("play_artist", "<artista> [shuffle]") + " — Todos los temas del artista.",
                both("play_album", "<artista> <álbum> [shuffle]") + " — Un álbum completo.",
                both("play_local", "[shuffle]") + " — Toda tu biblioteca local.",
            ]),
            inline=False,
        )
        embed.add_field(
            name="📜 Cola y navegación",
            value="\n".join([
                both("queue") + " — Muestra la cola.",
                both("skip", "[n]") + " — Salta *n* temas (por defecto 1).",
                both("skipto", "<n>") + " — Va a la posición *n* (1 = siguiente).",
                both("clearqueue", "[true|false]") + " — Limpia la cola (opcional: detener).",
                both("now") + " — Track actual (con **portada** si es local).",
            ]),
            inline=False,
        )
        embed.add_field(
            name="🎛️ Sesión y utilidades",
            value="\n".join([
                both("join") + " — Conecta al canal de voz.",
                both("stop") + " — Detiene, limpia y desconecta.",
                both("vol", f"<{VOL_MIN}-{VOL_MAX}>") + " — Volumen.",
                both("setlocal") + " — Configura la carpeta base de música local.",
                both("scanlocal") + " — Escanea (usa caché).",
                both("reindex") + " — Reconstruye índice sin caché.",
                both("vcinfo") + " — Info técnica del nodo/player.",
            ]),
            inline=False,
        )
        embed.set_footer(text="Sangonomiya Kokomi ♪  |  shuffle: en prefijo usa true/false; en slash marca el toggle.")
        await ctx.reply(embed=embed)
