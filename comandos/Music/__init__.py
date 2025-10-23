from __future__ import annotations
from .commands_core import Music as _CoreMusic
from .commands_library import Music as _LibMusic
from .commands_queue import Music as _QueueMusic
from .commands_session import Music as _SessionMusic


# Cog final que combina todo
class Music(_SessionMusic, _QueueMusic, _LibMusic, _CoreMusic):
    """Cog final de música: núcleo + comandos de biblioteca, cola y sesión."""
    pass

# Punto de entrada para discord.py
async def setup(bot):
    """Registrado por load_extension('comandos.Music')."""
    await bot.add_cog(Music(bot))
