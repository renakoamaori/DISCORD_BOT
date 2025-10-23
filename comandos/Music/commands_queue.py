from __future__ import annotations
from typing import Optional, List, cast
import discord
from discord.ext import commands
from .commands_core import Music as m
from .constants import EMBED_COLOR_PRIMARY
from .covers import build_local_now_embed
from .utils import popleft_many, strip_discord_wrapping, is_subpath
from pathlib import Path
import lavalink

class Music(m):
    @commands.guild_only()
    @commands.hybrid_command(name="play", description="Reproduce una URL, ruta local o busca en YouTube. Acepta playlists.")
    async def play(self, ctx: commands.Context, *, query: str):
        await ctx.defer()
        guild = cast(discord.Guild, ctx.guild)
        voice = await self._connect(ctx)
        if voice is None:
            return

        player = await self._ensure_player(guild)
        node = player.node
        gid = getattr(player, "guild_id", guild.id)
        q = strip_discord_wrapping(query)

        # Ruta local
        p = Path(q)
        if p.exists() and p.is_file():
            if self.base_path and not is_subpath(p, self.base_path):
                return await ctx.reply("La ruta no está dentro de la MUSIC_BASE autorizada.")
            local_identifier = p.resolve().as_posix()
            try:
                load_res = await node.get_tracks(local_identifier)
            except Exception as e:
                return await ctx.reply(f"No se pudo cargar el archivo local: {e}")
            tracks = getattr(load_res, "tracks", None) or []
            if not tracks:
                return await ctx.reply("No se pudo cargar el archivo local (¿'local' habilitado en Lavalink?).")
            t = tracks[0]
            player.add(requester=ctx.author.id, track=t)
            ident = self._track_attr(t, "identifier")
            uri   = self._track_attr(t, "uri")
            for key in (ident, uri, local_identifier, q):
                if isinstance(key, str):
                    self._local_map[key] = p.resolve()
            await self._ensure_playing(player, gid, first_track=t)
            try:
                await ctx.reply("✅")
            except Exception:
                pass
            return

        # URL o búsqueda
        identifier = q if q.startswith(("http://", "https://", "/")) else f"ytsearch:{q}"
        try:
            load_res = await node.get_tracks(identifier)
        except Exception as e:
            return await ctx.reply(f"No se pudo cargar: {e}")

        tracks = getattr(load_res, "tracks", None) or []
        if not tracks:
            return await ctx.reply("Sin resultados.")

        lt = getattr(load_res, "load_type", None)
        def _is(kind: "lavalink.LoadType") -> bool:
            if isinstance(lt, lavalink.LoadType):
                return lt == kind
            s = str(lt).upper() if lt is not None else ""
            if kind == lavalink.LoadType.PLAYLIST:
                return ("PLAYLIST" in s) or ("PLAYLIST_LOADED" in s)
            if kind == lavalink.LoadType.TRACK:
                return ("TRACK" in s) or ("TRACK_LOADED" in s)
            if kind == lavalink.LoadType.SEARCH:
                return ("SEARCH" in s) or ("SEARCH_RESULT" in s)
            return False

        if _is(lavalink.LoadType.PLAYLIST):
            pl_info = getattr(load_res, "playlist_info", None)
            pl_name = getattr(pl_info, "name", None) if pl_info else None
            for tr in tracks:
                player.add(requester=ctx.author.id, track=tr)
            await self._ensure_playing(player, gid, first_track=(tracks[0] if tracks else None))
            msg = f"Añadida playlist con **{len(tracks)}** temas."
            if pl_name:
                msg = f"Añadida playlist **{pl_name}** con **{len(tracks)}** temas."
            return await ctx.reply(msg)

        t = tracks[0]
        id_str = self._track_attr(t, "identifier")
        if isinstance(id_str, str):
            try:
                maybe_path = Path(id_str)
                if maybe_path.is_absolute():
                    self._local_map[id_str] = maybe_path
            except Exception:
                pass
        player.add(requester=ctx.author.id, track=t)
        if not player.is_playing:
            await self._ensure_playing(player, gid, first_track=t)
            await ctx.reply("✅")
        else:
            await ctx.reply(f"➕ En cola: **{self._track_attr(t, 'title', '(sin título)')}**")

    @commands.guild_only()
    @commands.hybrid_command(name="queue", description="Muestra la cola.")
    async def queue(self, ctx: commands.Context):
        guild = cast(discord.Guild, ctx.guild)
        player = self.ll.player_manager.get(guild.id)
        if not player or (not player.queue and not player.current):
            return await ctx.reply("Cola vacía.")
        lines: List[str] = []
        if player.current:
            cur = player.current
            lines.append(f"▶️ **Ahora:** {getattr(cur, 'title', '(sin título)')} — `{getattr(cur, 'author', '')}`")
        for idx, t in enumerate(player.queue, start=1):
            lines.append(f"{idx}. {getattr(t, 'title', '(sin título)')} — `{getattr(t, 'author', '')}`")
        await ctx.reply("\n".join(lines[:20]) or "Cola vacía.")

    @commands.guild_only()
    @commands.hybrid_command(name="skip", description="Salta N temas (por defecto 1).")
    async def skip(self, ctx: commands.Context, n: Optional[int] = None):
        await ctx.defer()
        guild = cast(discord.Guild, ctx.guild)
        player = self.ll.player_manager.get(guild.id)
        if not player:
            return await ctx.reply("No hay reproductor.")
        n = 1 if (n is None or n < 1) else int(n)
        if not player.is_playing and not player.queue:
            return await ctx.reply("No hay reproducción.")
        q_list = list(player.queue)
        to_remove = max(0, n - 1)
        target_pre = q_list[to_remove] if to_remove < len(q_list) else None
        removed_from_queue = popleft_many(player.queue, to_remove)
        gid = getattr(player, "guild_id", guild.id)
        if player.is_playing or player.current:
            await player.skip()
            total_skipped = removed_from_queue + 1
        else:
            if player.queue:
                next_first = player.queue[0]
                await self._ensure_playing(player, gid, first_track=next_first)
                total_skipped = removed_from_queue
            else:
                return await ctx.reply("Cola vacía.")
        if target_pre is not None:
            await ctx.reply(f"⏭️ Saltados {total_skipped} temas.")
        else:
            await ctx.reply(f"⏭️ Saltados {total_skipped} temas. Cola terminada.")

    @commands.guild_only()
    @commands.hybrid_command(name="skipto", description="Salta a la posición N de la cola (1 = siguiente).")
    async def skipto(self, ctx: commands.Context, index: int):
        await ctx.defer()
        guild = cast(discord.Guild, ctx.guild)
        player = self.ll.player_manager.get(guild.id)
        if not player:
            return await ctx.reply("No hay reproductor.")
        if index < 1:
            index = 1
        q_list = list(player.queue)
        if not q_list:
            if player.is_playing or player.current:
                await player.skip()
                return await ctx.reply("⏭️ Cola vacía. Reproducción detenida.")
            return await ctx.reply("No hay temas en la cola.")
        if index > len(q_list):
            to_remove = len(q_list); target_pre = None
        else:
            to_remove = index - 1;   target_pre = q_list[index - 1]
        removed_from_queue = popleft_many(player.queue, to_remove)
        gid = getattr(player, "guild_id", guild.id)
        if (player.is_playing or player.current):
            await player.skip()
            total_skipped = removed_from_queue + 1
        else:
            if player.queue:
                next_first = player.queue[0]
                await self._ensure_playing(player, gid, first_track=next_first)
                total_skipped = removed_from_queue
            else:
                return await ctx.reply("Cola vacía tras saltar.")
        if target_pre is not None:
            await ctx.reply(f"⏭️ Saltados {total_skipped} temas hasta la posición {index}.")
        else:
            await ctx.reply(f"⏭️ Saltados {total_skipped} temas hasta el final. Cola terminada.")

    @commands.guild_only()
    @commands.hybrid_command(name="clearqueue", description="Limpia la cola. Opcional: detener la reproducción.")
    async def clearqueue(self, ctx: commands.Context, stop: Optional[bool] = False):
        """Prefijo: acepta `true/false/1/0/on/off`. (Si escribes `stop`, usa `/clearqueue` o `true`)."""
        guild = cast(discord.Guild, ctx.guild)
        player = self.ll.player_manager.get(guild.id)
        if not player:
            return await ctx.reply("No hay reproductor.")

        # Limpiar cola
        n = len(player.queue)
        player.queue.clear()

        # Detener opcionalmente (pero NO desconectar del VC)
        if stop:
            await player.stop()
            try:
                await player.set_pause(False)  # por si quedó pausado
            except Exception:
                pass
            await ctx.reply(f"🧹 Cola limpiada ({n}). ⏹️ Reproducción detenida.")
        else:
            await ctx.reply(f"🧹 Cola limpiada ({n}). ⏯️ Sonando se mantiene.")

    @commands.guild_only()
    @commands.hybrid_command(name="stop", description="Detiene y limpia la cola.")
    async def stop(self, ctx: commands.Context):
        guild = cast(discord.Guild, ctx.guild)
        player = self.ll.player_manager.get(guild.id)
        if not player:
            return await ctx.reply("Nada que detener.")
        await player.stop()
        player.queue.clear()
        try:
            await player.destroy()
        except Exception:
            pass
        vc = guild.voice_client
        if vc:
            try:
                await vc.disconnect(force=True)
            except Exception:
                pass
        await ctx.reply("⏹️ Detenido y desconectado.")
    
    @commands.guild_only()
    @commands.hybrid_command(name="now", description="Muestra el tema actual. Si es local, incluye portada y metadatos.")
    async def now(self, ctx: commands.Context):
        guild = cast(discord.Guild, ctx.guild)
        player = self.ll.player_manager.get(guild.id)
        if not player or not player.current:
            return await ctx.reply("Nada sonando.")
        cur = player.current
        p = self._resolve_local_path(cur)
        if p is not None and p.exists():
            embed, cover_file = await build_local_now_embed(p)
            if cover_file:
                return await ctx.reply(embed=embed, file=cover_file)
            return await ctx.reply(embed=embed)
        title = self._track_attr(cur, "title", "(sin título)")
        author = self._track_attr(cur, "author", "")
        uri = self._track_attr(cur, "uri", None)
        embed = discord.Embed(title=str(title), colour=EMBED_COLOR_PRIMARY, description=f"`{author}`")
        if isinstance(uri, str):
            embed.add_field(name="Enlace", value=uri, inline=False)
        await ctx.reply(embed=embed)