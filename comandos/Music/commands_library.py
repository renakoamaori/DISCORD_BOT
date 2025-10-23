from __future__ import annotations
import asyncio
import time
import os
import random
from pathlib import Path
from typing import List, Optional
import discord
from discord.ext import commands
from .library import LocalLibrary
from .enqueue import enqueue_tracks_from_paths
from .constants import MAX_CONC_ENQUEUE, WARMUP_FIRST, PROGRESS_EVERY, PROGRESS_MIN_SECS, MUSIC_DEBUG, MUSIC_BASE_ENV
from .utils import is_subpath, norm, dprint
from .commands_core import Music as m
 
class Music(m):
    # ----------------------- Helpers internos de UX -----------------------
    async def _progress_msg_updater(
        self,
        ctx: commands.Context,
        *,
        step: int,
        min_secs: float,
        total: int,
    ):
        """
        Genera un closure async para actualizar un mensaje de progreso:
        progress(done) -> None (async)
        """
        prog_msg: Optional[discord.Message] = None
        last_edit = 0.0

        async def _progress(done: int):
            nonlocal prog_msg, last_edit
            if step <= 0:
                return
            now = time.monotonic()
            if (done % step == 0) and (now - last_edit >= min_secs):
                pct = (done * 100) // (total if total else 1)
                text = f"Encolando… {done}/{total} ({pct}%)"
                if prog_msg is None:
                    try:
                        prog_msg = await ctx.reply(text)
                    except Exception:
                        prog_msg = None
                else:
                    try:
                        await prog_msg.edit(content=text)
                    except Exception:
                        pass
                last_edit = now
        # devolver callable y el objeto de mensaje para usar al final
        return _progress, lambda: prog_msg

    async def _warmup_then_enqueue(
        self,
        ctx: commands.Context,
        paths: List[Path],
        *,
        shuffle: bool,
    ) -> int:
        """
        Warm-up secuencial para sonar rápido + encolado masivo preservando orden.
        Devuelve cantidad total añadida.
        """
        if not paths:
            await ctx.reply("No hay temas para encolar.")
            return 0

        guild = ctx.guild
        if guild is None:
            await ctx.reply("Este comando solo funciona en servidores.")
            return 0

        # Conectar al canal del autor (o al que pases en otros comandos)
        await self._connect(ctx)

        player = await self._ensure_player(guild)
        node = player.node

        safe_paths = [p for p in paths if self.music_base_path and is_subpath(p, self.music_base_path)]
        if not safe_paths:
            await ctx.reply("No hay temas válidos dentro de la carpeta de música configurada.")
            return 0

        if shuffle:
            random.shuffle(safe_paths)

        total = len(safe_paths)
        step = int(getattr(self, "PROGRESS_EVERY", PROGRESS_EVERY))
        min_secs = float(getattr(self, "PROGRESS_MIN_SECS", PROGRESS_MIN_SECS))
        warmup_first = int(getattr(self, "WARMUP_FIRST", WARMUP_FIRST))

        # Progreso (warm-up + paralelo comparten el mismo contador)
        progress_cb_async, get_prog_msg = await self._progress_msg_updater(
            ctx, step=step, min_secs=min_secs, total=total
        )
        added_so_far = 0
        first_track = None

        # --------- 1) Warm-up secuencial ---------
        warm_slice = safe_paths[:warmup_first]
        for p in warm_slice:
            identifier = p.resolve().as_posix()
            try:
                lr = await node.get_tracks(identifier)
            except Exception as e:
                dprint(f"[commands_library] aviso: {e}", _enabled=MUSIC_DEBUG)
                continue
            trks = getattr(lr, "tracks", None) or []
            if not trks:
                continue
            t = trks[0]
            player.add(requester=ctx.author.id, track=t)

            # mapear claves locales
            ident = getattr(t, "identifier", None)
            uri = getattr(t, "uri", None)
            for key in (ident, uri, identifier):
                if isinstance(key, str):
                    self._local_map[key] = p

            if first_track is None:
                first_track = t

            added_so_far += 1
            await progress_cb_async(added_so_far)

        # arrancar reproducción temprano
        gid = getattr(player, "guild_id", guild.id)
        await self._ensure_playing(player, gid, first_track=first_track)

        # --------- 2) Paralelo preservando orden ---------
        rest_paths = safe_paths[warmup_first:]
        if rest_paths:
            # el helper de enqueue reporta done relativo al subset;
            # lo convertimos a global sumando added_so_far actual
            def _progress_cb_subset(done_subset: int, total_subset: int):
                self.bot.loop.create_task(progress_cb_async(added_so_far + done_subset))

            added2, _failed2 = await enqueue_tracks_from_paths(
                node=node,
                player=player,
                guild_id=guild.id,
                requester_id=ctx.author.id,
                paths=rest_paths,
                local_map=self._local_map,
                ensure_playing=self._ensure_playing,
                shuffle=False,
                max_concurrency=MAX_CONC_ENQUEUE,
                progress_cb=_progress_cb_subset,
                debug_enabled=False,
            )
            added_so_far += added2

        # Mensaje final
        prog_msg = get_prog_msg()
        final_text = f"Encolados {added_so_far} temas. 🎶"
        if prog_msg:
            try:
                await prog_msg.edit(content=final_text)
            except Exception as e:
                dprint(f"[commands_library] aviso: {e}", _enabled=MUSIC_DEBUG)
                await ctx.reply(final_text)
        else:
            await ctx.reply(final_text)

        return added_so_far

    @commands.guild_only()
    @commands.hybrid_command(name="setlocal", description="Configura la carpeta base de música local.")
    async def setlocal(self, ctx: commands.Context, *, folder: str):
        p = Path(folder).expanduser().resolve()
        if not p.exists() or not p.is_dir():
            return await ctx.reply("La ruta indicada no existe o no es una carpeta.")
        # Actualiza base y librería
        self.music_base_path = p
        self.base_path = p.parent
        self.lib = LocalLibrary(p)

        try:
            os.environ[MUSIC_BASE_ENV] = str(p)
        except Exception:
            pass

        await ctx.reply(f"Carpeta de música configurada en:\n`{p}`\n"
                        f"(Para persistir entre reinicios, define {MUSIC_BASE_ENV} en tu sistema o .env)")


    @commands.guild_only()
    @commands.hybrid_command(name="scanlocal", description="Escanea la biblioteca local por tags (con caché).")
    async def scanlocal(self, ctx: commands.Context):
        await ctx.defer()
        if not self.music_base_path or not self.lib:
            return await ctx.reply("Primero usa `!setmusic <ruta>`.")
        try:
            async with asyncio.Lock():
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self.lib.scan)
            arts = len(self.lib.artists())
            albs = sum(len(v) for v in self.lib.data.values())
            tracks = len(self.lib.all_tracks())
            s = self.lib.last_stats
            await ctx.reply(
                f"Escaneo: {arts} artistas, {albs} álbumes, {tracks} temas.\n"
                f"Cache → total:{s['total']} reusados:{s['cached']} actualizados:{s['updated']} añadidos:{s['added']} eliminados:{s['removed']}."
            )
        except Exception as e:
            dprint(f"[commands_library] aviso: {e}", _enabled=MUSIC_DEBUG)
            return await ctx.reply(f"No se pudo escanear.")
    
    @commands.guild_only()
    @commands.hybrid_command(name="reindex", description="Reconstruye índice ignorando caché.")
    async def reindex(self, ctx: commands.Context):
        await ctx.defer()
        if not self.base_path or not self.lib:
            return await ctx.reply("MUSIC_BASE no está configurado.")
        async with asyncio.Lock():
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self.lib.scan, True)
        await ctx.reply("Reindex completo listo ✅")
    
    @commands.guild_only()
    @commands.hybrid_command(name="play_artist", description="Reproduce todos los temas de un artista.")
    async def play_artist(self, ctx: commands.Context, artista: str, shuffle: Optional[bool] = False):
        await ctx.defer()
        if not self.base_path or not self.lib:
            return await ctx.reply("MUSIC_BASE no está configurado.")
        if await self._connect(ctx) is None:
            return
        arts = self.lib.artists()
        if artista not in arts:
            m = next((a for a in arts if norm(a) == norm(artista)), None)
            if not m:
                return await ctx.reply("Artista no encontrado. Ejecuta /scanlocal y revisa los nombres.")
            artista = m
        paths = self.lib.tracks_by_artist(artista)
        await self._warmup_then_enqueue(ctx, paths, shuffle=bool(shuffle))
    
    @commands.guild_only()
    @commands.hybrid_command(name="play_album", description="Reproduce un álbum específico.")
    async def play_album(self, ctx: commands.Context, artista: str, album: str, shuffle: Optional[bool] = False):
        await ctx.defer()
        if not self.base_path or not self.lib:
            return await ctx.reply("MUSIC_BASE no está configurado.")
        if await self._connect(ctx) is None:
            return
        arts = self.lib.artists()
        if artista not in arts:
            m = next((a for a in arts if norm(a) == norm(artista)), None)
            if not m:
                return await ctx.reply("Artista no encontrado.")
            artista = m
        albs = self.lib.albums(artista)
        if album not in albs:
            m = next((a for a in albs if norm(a) == norm(album)), None)
            if not m:
                return await ctx.reply("Álbum no encontrado.")
            album = m
        paths = self.lib.tracks_by_album(artista, album)
        await self._warmup_then_enqueue(ctx, paths, shuffle=bool(shuffle))
    
    @commands.guild_only()
    @commands.hybrid_command(name="play_local", description="Reproduce toda la biblioteca local.")
    async def play_local(self, ctx: commands.Context, shuffle: Optional[bool] = False):
        await ctx.defer()
        if not self.base_path or not self.lib:
            return await ctx.reply("MUSIC_BASE no está configurado.")
        if await self._connect(ctx) is None:
            return
        paths = self.lib.all_tracks()
        await self._warmup_then_enqueue(ctx, paths, shuffle=bool(shuffle))