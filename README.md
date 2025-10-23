# Bot de Música para Discord

Un bot simple para reproducir música en Discord, construido con `discord.py` y `Lavalink`.

## Motivación

Este es un proyecto puramente personal, desarrollado por simple capricho.

## Configuración

1.  Clona este repositorio:
    ```bash
    git clone https://github.com/renakoamaori/DISCORD_BOT.git
    cd DISCORD_BOT
    ```

2.  Crea un entorno virtual e instala las dependencias:
    ```bash
    python -m venv .venv
    # En Windows: .venv\Scripts\activate
    # En macOS/Linux: source .venv/bin/activate
    pip install -r requirements.txt
    ```

3.  Crea un archivo `.env` y añade lo siguiente:
    ```env
    DISCORD_TOKEN=tutoken
    GUILD_ID=123
    BOT_PREFIX=tuprefijo
    MUSIC_BASE="directorio de música local"
    LAVALINK_HOST=127.0.0.1
    LAVALINK_PORT=2333
    LAVALINK_PASSWORD=tucontraseña
    LAVALINK_REGION=laregiondelavalink
    LAVALINK_SSL=true/false
    LAVALINK_NAME=loquesea
    ```
    Remplaza los valores con tus respectivos datos.

4.  Configura `application.yml`:
    Copia el archivo `application.yml.template` y renuévalo a `application.yml`. Luego, edita el archivo para establecer tu contraseña:
    ```yml
    lavalink:
      server:
        password: "tucontraseña" # ¡Importante: Debe coincidir con LAVALINK_PASSWORD del .env!
    ```

5.  Ejecuta el bot:
    ```bash
    python main.py
    ```
