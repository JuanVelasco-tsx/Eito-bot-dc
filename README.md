# 🤖 EITO Setup Bot

Bot de Discord para la comunidad **EITO** (gaming / Left 4 Dead). Monta la
estructura del servidor y añade funciones de comunidad, moderación y niveles.

## ✨ Funciones

- **Setup automático**: crea categorías, canales y roles con un solo comando.
- **Bienvenida** automática + rol al entrar.
- **Panel de roles** con botones (plataforma y región).
- **Sistema de niveles/XP** con ranking.
- **Moderación**: borrar, kick, ban, mute, warns.
- **Utilidades**: encuestas, sugerencias, perfiles de Steam.

## 🚀 Instalación

1. Instala las dependencias:

   ```bash
   pip install -r requirements.txt
   ```

2. Copia `.env.example` como `.env` y pon tu token de Discord:

   ```
   DISCORD_TOKEN=tu_token_aqui
   ```

3. En el [Developer Portal](https://discord.com/developers/applications),
   dentro de tu app → **Bot**, activa los *Privileged Gateway Intents*:
   - ☑️ MESSAGE CONTENT INTENT
   - ☑️ SERVER MEMBERS INTENT

4. Ejecuta el bot:

   ```bash
   python eito_setup_bot.py
   ```

## 📖 Comandos

Todos usan el prefijo `!`. Escribe `!ayuda` en el servidor para ver la lista.

### Administración (solo admins)
- `!setup` — crea canales, categorías y roles
- `!reglas` — publica las reglas
- `!panelroles` — panel de roles con botones
- `!presentaciones` — plantilla de presentación
- `!anuncio <texto>` — publica un anuncio

### Moderación
- `!borrar <n>` — borra los últimos N mensajes (1–100)
- `!kick @usuario [razón]`
- `!ban @usuario [razón]`
- `!mute @usuario <duración> [razón]` (ej. `10m`, `2h`, `1d`)
- `!unmute @usuario`
- `!warn @usuario [razón]` / `!warns [@usuario]`

### Utilidad
- `!encuesta <pregunta>` — encuesta con 👍👎
- `!sugerencia <texto>` — sugerencia con votación
- `!steam <enlace o SteamID>` — publica tu perfil de Steam

### Comunidad
- `!ping`, `!miembros`, `!avatar [@usuario]`, `!serverinfo`
- `!nivel [@usuario]` — tu nivel y XP
- `!top` — ranking de niveles
- `!ayuda` — lista de comandos

## 🗂️ Datos

El bot guarda datos en archivos JSON locales (excluidos del repo):
- `niveles.json` — XP de cada usuario
- `avisos.json` — avisos de moderación

## 🔒 Seguridad

- El token va en `.env`, **nunca** en el código ni en el repo.
- `.gitignore` protege el `.env` y los archivos de datos.
