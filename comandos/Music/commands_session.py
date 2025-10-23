from __future__ import annotations
from typing import cast, List
import discord
from discord.ext import commands
from .commands_core import Music as m
from .constants import VOL_MIN, VOL_MAX

class Music(m):
    @commands.guild_only()
    @commands.hybrid_command(name="vol", description=f"Ajusta el volumen ({VOL_MIN}-{VOL_MAX}%).")
    async def vol(self, ctx: commands.Context, volume: int):
        # Validación estricta del rango antes de aplicar
        if volume < VOL_MIN or volume > VOL_MAX:
            return await ctx.reply(
                f"⚠️ El volumen debe ser un valor **entre {VOL_MIN} y {VOL_MAX}**. "
                "Por favor, ingresa un número dentro de ese rango."
            )

        guild = cast(discord.Guild, ctx.guild)
        player = self.ll.player_manager.get(guild.id)
        if not player:
            return await ctx.reply("❌ No hay reproductor activo en este servidor.")

        await player.set_volume(volume)
        await ctx.reply(f"🔊 Volumen ajustado a **{volume}%** correctamente.")

    # ---------------- Diagnóstico ----------------
    @commands.guild_only()
    @commands.hybrid_command(name="vcinfo", description="Estado de voz/lavalink.")
    async def vcinfo(self, ctx: commands.Context):
        guild = cast(discord.Guild, ctx.guild)
        node = None
        nm = getattr(self._ll, "node_manager", None)
        if nm is not None:
            get_node = getattr(nm, "get_node", None)
            if callable(get_node):
                try:
                    node = get_node()
                except Exception:
                    node = None
            if node is None:
                nodes = getattr(nm, "nodes", None)
                if isinstance(nodes, list) and nodes:
                    node = nodes[0]
        player = self.ll.player_manager.get(guild.id)
        lines: List[str] = []
        node_available = bool(node and getattr(node, "available", True))
        lines.append(f"Node available: {node_available}")
        if player:
            lines.append(f"Player: playing={player.is_playing} queue={len(player.queue)}")
            lines.append(f"channel_id={getattr(player, 'channel_id', None)}")
            if player.current:
                lines.append(f"Now: {getattr(player.current, 'title', '(sin título)')}")
        else:
            lines.append("Player: None")
        author_in = "NO"
        if isinstance(ctx.author, discord.Member):
            vs = ctx.author.voice
            if vs and vs.channel:
                author_in = vs.channel.name
        lines.append(f"Author in: {author_in}")
        await ctx.reply("```\n" + "\n".join(lines) + "\n```")

    @commands.guild_only()
    @commands.hybrid_command(name="join", description="Fuerza conexión al canal de voz actual.")
    async def join(self, ctx: commands.Context):
        voice = await self._connect(ctx)
        await ctx.reply("OK" if voice else "NO")