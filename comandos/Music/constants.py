from __future__ import annotations
from typing import Final

# Ruta de musica local
MUSIC_BASE_ENV: Final[str] = "MUSIC_BASE"

# Extensiones que tengo en la biblioteca músical
SUPPORTED_EXTS: Final[tuple[str, ...]] = (
    ".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac", ".opus",
)

# Nombres de archivo de las portadas que pueden tener los tracks
COVER_CAND_NAMES: Final[tuple[str, ...]] = (
    "cover", "folder", "front", "album", "art",
)

# Extensiones de archivo que pueden tener las portadas de los tracks
COVER_EXTS: Final[tuple[str, ...]] = (".png", ".jpg", ".jpeg", ".webp")

# Índice local
CACHE_VERSION: Final[int] = 1
MUSIC_CACHE_FILENAME: Final[str] = ".kokomi_music_cache.json"

# Rendimiento / escaneo
MAX_CONC_ENQUEUE: Final[int] = 6
SCAN_BATCH_SIZE: Final[int] = 512
SCAN_FOLLOW_SYMLINKS: Final[bool] = False
EXCLUDED_DIR_NAMES: Final[tuple[str, ...]] = (".git", "__pycache__", ".cache")

# Comportamiento del bot
MUSIC_DEBUG: Final[bool] = True
WARMUP_FIRST: Final[int] = 8
PROGRESS_EVERY: Final[int] = 200
PROGRESS_MIN_SECS: Final[float] = 12.0
ANNOUNCE_DEDUP_SECONDS: Final[int] = 5  # evita spam de “now playing”
AUTO_DC_IDLE_SECONDS: Final[int] = 180  # desconexión si no hay reproducción/cola
AUTO_DC_POLL_PERIOD: Final[int] = 30    # cada cuánto chequea el monitor
AUTO_DC_MESSAGE = "⏹️ Desconectado automáticamente por inactividad (3 min)."

# Audio / Player
VOL_MIN: Final[int] = 0
VOL_MAX: Final[int] = 100
PLAYER_INITIAL_VOLUME: Final[int] = 50  # volumen por defecto al crear player

QUEUE_MAX_LEN: Final[int] = 0           # 0 = sin límite

# Estilo / símbolos
EMBED_COLOR_PRIMARY: Final[int] = 0xF6D4CB
EMOJI_NOW: Final[str] = "🎵"
EMOJI_QUEUE: Final[str] = "📜"
EMOJI_OK: Final[str] = "✅"
EMOJI_WARN: Final[str] = "⚠️"