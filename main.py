# kokomi.py
from __future__ import annotations

import os
import logging
import importlib
import pkgutil

import discord
from discord.ext import commands
from dotenv import load_dotenv

# -------------- Config de logging --------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s %(message)s"
)
log = logging.getLogger(__name__)


def _prefix_callable(bot: commands.Bot, message: discord.Message):
    """
    Permite mencionar al bot como prefijo, además del prefijo por defecto.
    """
    base = getattr(bot, "default_prefix", "!")
    return commands.when_mentioned_or(base)(bot, message)


class KokomiBot(commands.Bot):
    def __init__(self):
        # Para tu bot privado/admin: ALL intents
        intents = discord.Intents.all()

        super().__init__(
            command_prefix=_prefix_callable,
            intents=intents,
            help_command=None,
            case_insensitive=True,
        )

        # Atributos accesibles desde cogs (p.ej. music.py)
        self.default_prefix: str = "!"

    # ---------- Carga de extensiones ----------
    async def _load_all_extensions(self) -> None:
        """
        Carga todas las extensiones del paquete 'comandos' que tengan `setup(...)`.
        Incluye subpaquetes. Ignora módulos que empiecen con '_'.
        Requiere 'comandos/__init__.py'.
        """
        try:
            pkg = importlib.import_module("comandos")
        except ModuleNotFoundError:
            log.warning("No se encontró el paquete 'comandos'. ¿Existe y tiene __init__.py?")
            return

        to_try: list[str] = []
        for m in pkgutil.walk_packages(pkg.__path__, prefix=pkg.__name__ + "."):
            short = m.name.rsplit(".", 1)[-1]
            if short.startswith("_"):
                continue
            to_try.append(m.name)

        if not to_try:
            log.info("No se encontraron módulos en 'comandos'.")
            return

        for name in sorted(set(to_try)):
            try:
                await self.load_extension(name)  # discord.py 2.x: async load
                log.info("Extensión cargada: %s", name)
            except commands.NoEntryPointError:
                # El módulo no define setup(bot) → se ignora en silencio
                log.debug("Saltando %s (sin entrypoint setup)", name)
            except commands.ExtensionNotFound:
                log.debug("Extensión no encontrada: %s", name)
            except commands.ExtensionFailed as e:
                log.exception("Error al cargar %s: %s", name, e)
            except Exception as e:
                log.exception("Excepción cargando %s: %s", name, e)

    # ---------- Setup asíncrono ----------
    async def setup_hook(self) -> None:
        guild_id = os.getenv("GUILD_ID")

        # 1) BORRAR en Discord
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.clear_commands(guild=guild)     # NO await
            try:
                await self.tree.sync(guild=guild)     # push vacío -> borra en ese guild
                log.info("🧹 Comandos slash eliminados en el guild %s.", guild_id)
            except Exception as e:
                log.warning("No se pudieron eliminar los comandos del guild: %s", e)
        else:
            self.tree.clear_commands(guild=None)      # global
            try:
                await self.tree.sync(guild=None)                # push vacío -> borra globales
                log.info("🧹 Todos los comandos slash globales eliminados.")
            except Exception as e:
                log.warning("No se pudieron eliminar los comandos globales: %s", e)

        # 2) CARGAR extensiones (registran hybrid/global en el árbol)
        await self._load_all_extensions()

        # 3) PUBLICAR de nuevo
        try:
            if guild_id:
                guild = discord.Object(id=int(guild_id))
                # Los hybrid quedan como *globales* -> cópialos al ámbito del guild
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                log.info("✅ Slash sync completado en guild %s: %d comandos registrados.",
                        guild_id, len(synced))
            else:
                synced = await self.tree.sync(guild=None)  # global
                log.info("✅ Slash sync global: %d comandos registrados.", len(synced))
        except Exception as e:
            log.warning("No se pudo sincronizar comandos: %s", e)

    # ---------- Eventos ----------
    async def on_ready(self) -> None:
        log.info("Conectado como %s (%s)", self.user, self.user and self.user.id)
        try:
            await self.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.listening,
                    name=f"{self.default_prefix}infomusica"
                ),
                status=discord.Status.online,
            )
        except Exception:
            pass

    async def on_command_error(self, ctx: commands.Context, error: Exception) -> None:
        # Silenciar CommandNotFound para prefijo
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("No tienes permisos para eso.")
            return
        if isinstance(error, commands.NoPrivateMessage):
            await ctx.reply("Este comando no funciona por DM.")
            return

        log.exception("Error en comando %s: %s", getattr(ctx.command, "qualified_name", "?"), error)
        try:
            await ctx.reply(f"⚠️ Ocurrió un error: `{type(error).__name__}`")
        except Exception:
            pass


# ---------- util cogs ----------
async def _unload_all_cogs(bot: commands.Bot) -> None:
    """
    Descarga todas las extensiones actualmente cargadas.
    """
    for ext in list(bot.extensions.keys()):
        try:
            await bot.unload_extension(ext)
            log.info("Descargado: %s", ext)
        except Exception as e:
            log.warning("Error descargando %s: %s", ext, e)


# ---------- Comando de recarga (owner-only) ----------
def _register_owner_commands(bot: KokomiBot) -> None:
    @bot.command(name="reload", help="Recarga todas las extensiones sin reiniciar el bot.")
    @commands.is_owner()
    async def reload_cogs(ctx: commands.Context):
        await ctx.reply("🔄 Recargando extensiones…", delete_after=2)
        await _unload_all_cogs(bot)
        await bot._load_all_extensions()
        try:
            synced = await bot.tree.sync()
            log.info("Slash sync (reload): %d comandos", len(synced))
        except Exception as e:
            log.warning("No se pudo hacer app_commands sync (reload): %s", e)
        await ctx.send("✅ Extensiones recargadas.")


# -------------- Main --------------
def main():
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Falta DISCORD_TOKEN en entorno o .env")

    bot = KokomiBot()
    bot.default_prefix = os.getenv("BOT_PREFIX", "!")

    _register_owner_commands(bot)

    try:
        bot.run(token)
    except KeyboardInterrupt:
        print("\n🛑 Bot detenido manualmente")


if __name__ == "__main__":
    main()
