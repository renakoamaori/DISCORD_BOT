from __future__ import annotations
from typing import Optional, Union
import discord
from discord.types.voice import GuildVoiceState, VoiceServerUpdate

ChanT = Union[discord.VoiceChannel, discord.StageChannel]

class LavalinkVoiceClient(discord.VoiceProtocol):
        """VoiceProtocol que integra discord.py con lavalink (no usar VoiceClient base)."""

        def __init__(self, client: discord.Client, channel: discord.abc.Connectable):
            super().__init__(client, channel)
            self.client: discord.Client = client
            self._chan_opt: Optional[ChanT] = channel if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)) else None
            self.guild: Optional[discord.Guild] = getattr(channel, "guild", None)

        async def connect(self, *, timeout: float, reconnect: bool,
                        self_deaf: bool = False, self_mute: bool = False) -> None:
            if self.guild is None:
                return
            ws = self.client._get_websocket(self.guild.id)  # type: ignore[attr-defined]
            await ws.voice_state(
                guild_id=self.guild.id,
                channel_id=self._chan_id(self.channel),
                self_mute=self_mute,
                self_deaf=self_deaf,
            )

        async def move_to(self, channel: ChanT, *, self_deaf: bool = False, self_mute: bool = False) -> None:
            g = getattr(channel, "guild", None)
            if g is None:
                return
            ws = self.client._get_websocket(g.id)  # type: ignore[attr-defined]
            await ws.voice_state(
                guild_id=g.id,
                channel_id=self._chan_id(channel),
                self_mute=self_mute,
                self_deaf=self_deaf,
            )
            self._chan_opt = channel
            self.guild = g

        async def on_voice_server_update(self, data: VoiceServerUpdate) -> None:
            payload = {"t": "VOICE_SERVER_UPDATE", "d": data}
            handler = getattr(self.client, "_ll_voice_update", None)
            if handler:
                await handler(payload)

        async def on_voice_state_update(self, data: GuildVoiceState) -> None:
            user = self.client.user
            if not user or int(data.get("user_id", 0)) != user.id:
                return
            payload = {"t": "VOICE_STATE_UPDATE", "d": data}
            handler = getattr(self.client, "_ll_voice_update", None)
            if handler:
                await handler(payload)

        async def disconnect(self, *, force: bool = False) -> None:
            if self.guild is None:
                return
            ws = self.client._get_websocket(self.guild.id)  # type: ignore[attr-defined]
            await ws.voice_state(
                guild_id=self.guild.id,
                channel_id=None,
                self_mute=False,
                self_deaf=False,
            )
            state = getattr(self.client, "_connection", None)
            try:
                remover = getattr(state, "remove_voice_client", None) or getattr(state, "_remove_voice_client", None)
                if callable(remover):
                    remover(self.guild.id)
            except Exception:
                pass
            self._chan_opt = None
            self.guild = None

        @staticmethod
        def _chan_id(ch: Optional[discord.abc.Connectable]) -> Optional[int]:
            if isinstance(ch, (discord.VoiceChannel, discord.StageChannel)):
                return ch.id
            return None