# 🤖 EITO Setup Bot

Bot de Discord para la comunidad **EITO** (gaming / Left 4 Dead). Monta la
estructura del servidor y añade funciones de comunidad, moderación y niveles.

## ✨ Funciones

- **Setup automático**: crea categorías, canales y roles con un solo comando.
- **Bienvenida** automática + rol al entrar.
- **Panel de roles** con botones (plataforma, región y avisos) y rol +18 por reacción.
- **Niveles/XP** con ranking, recompensas por nivel y **Activo del mes**.
- **Moderación**: borrar, kick, ban, mute, warns.
- **Utilidades**: encuestas, sugerencias, perfiles de Steam y búsqueda de partida (`!jugar`).
- **Avisos de releases** del L4D2 Versus Addon Manager vía webhook HTTP.

### 🔥 Activo del mes

Cada mensaje (que no sea un comando) suma XP al total y al acumulado del mes
actual (UTC). Cada hora el bot revisa el mes anterior y, si aún no se premió,
da el rol **🔥 Activo del mes** al top 3 de XP mensual (desempata por XP total),
se lo quita a los ganadores anteriores y lo anuncia en el canal de niveles.
Quedan excluidos los bots, el dueño del servidor y el rol DEVELOPER; admins y
moderadores sí participan. `!importarniveles` reconstruye un mes pasado a partir
de los avisos de subida de nivel.

### 🌱 Fundador

Los 100 miembros más antiguos del servidor (por fecha de entrada, sin bots) reciben
el rol **🌱 Fundador**. Lo asigna una sola vez el dueño o un DEVELOPER con
`!fundadores` (primero una vista previa, luego `!fundadores confirmar`). La lista se
guarda en la base de datos: si un fundador sale y vuelve a entrar, recupera el rol.

### 🎖️ Rangos por antigüedad

Solo cuenta el tiempo en el servidor (no el nivel). Cada 6 horas el bot da
**🥉 Veterano** a quien lleva 90 días o más y **🥈 Leyenda** a quien lleva 180 o más
(Leyenda reemplaza a Veterano). Nunca los quita por otra razón. Si hubo ascensos,
publica un resumen con los nombres (máximo 20 por rango y luego «+X más», sin pings)
en el canal de logros. **🥇 OG** es un rol manual: el bot nunca lo da ni lo quita, solo
lo muestra. `!antiguedad` muestra tus días, rango y distinciones.

### 🏅 Logros

Los logros se anuncian en el canal **🏅・logros** (lo creas tú a mano; si no existe se
usa el canal de niveles): un embed con el color del rol, quién lo consiguió, el motivo
y su avatar, mencionando solo a esa persona. Además, cuando el staff **agrega a mano**
un rol de honor (hoy 🥇 OG, lista `ROLES_HONOR_IDS`), el bot lo anuncia con el motivo
«Reconocido por el staff». Quitar el rol, o dar cualquier otro rol, no anuncia nada.
El Activo del mes sigue anunciándose en el canal de niveles.

## 🚀 Instalación

1. Instala Python 3.12 y las dependencias:

   ```bash
   pip install -r requirements.txt
   ```

2. Ten una base de datos **PostgreSQL**. Las tablas se crean solas al arrancar
   (no hay migraciones: los cambios en tablas existentes requieren hacerlos a mano).

3. Copia `.env.example` como `.env` y completa las variables de entorno
   (en producción, por ejemplo Railway, se definen en el panel):

   | Variable | Obligatoria | Para qué sirve |
   |---|---|---|
   | `DISCORD_TOKEN` | Sí | Token del bot de Discord. |
   | `DATABASE_URL` | Sí | Conexión a PostgreSQL (`postgresql://usuario:clave@host/base`). |
   | `EITO_GUILD_ID` | No | ID del servidor principal. Ahí `!darnivel` queda bloqueado. Déjala vacía en servers de pruebas. |
   | `RELEASE_CHANNEL_ID` | No | Canal donde el webhook publica nuevas versiones. Si falta, busca el canal `🔧・l4d2-mod-loader`. |
   | `RELEASE_WEBHOOK_SECRET` | Para el webhook | Secreto `Bearer` de `POST /release-webhook`. Sin él, el endpoint responde 503. |
   | `PORT` | No | Puerto del servidor web interno (por defecto `8080`; si está vacía también se usa `8080`). |

4. En el [Developer Portal](https://discord.com/developers/applications),
   dentro de tu app → **Bot**, activa los *Privileged Gateway Intents*:
   - ☑️ MESSAGE CONTENT INTENT
   - ☑️ SERVER MEMBERS INTENT

5. Ejecuta el bot:

   ```bash
   python eito_setup_bot.py
   ```

6. En el servidor, el rol del bot debe estar **por encima** de los roles que
   gestiona (roles de plataforma/región, Nivel 10, Activo del mes...). Luego un
   admin corre `!setup`.

## 📖 Comandos

Todos usan el prefijo `!`. Escribe `!ayuda` en el servidor para ver la lista
según tus permisos.

### Administración (solo admins)
- `!setup` — crea canales, categorías y roles
- `!setupsteam` — reconfigura el canal de perfiles de Steam (solo-bot)
- `!setuprecompensas` — reconfigura los canales de recompensa por nivel
- `!reglas` — publica las reglas; si ya existe el mensaje, lo **edita** en vez de duplicarlo
- `!info` (alias `!guia`) — publica o edita la guía de inicio
- `!panelroles` — publica o edita el panel de roles con botones (los botones siguen funcionando)
- `!presentaciones` — publica o edita la plantilla de presentación
- `!anuncio <texto>` — publica un anuncio (permiso *Gestionar servidor*: también lo pueden usar los admins y el staff con ese permiso)
- `!panelcochipuerco` — publica el panel del rol +18 y configura el acceso NSFW
- `!importarniveles <YYYY-MM> [confirmar]` — reconstruye la XP mensual de un mes
  desde los avisos de subida de nivel. Sin `confirmar` solo muestra una vista previa.
- `!exportarserver` — exporta roles y canales (permisos, overrides) a JSON por DM.
  Requiere ser admin **y** el dueño del servidor o tener el rol DEVELOPER.
- `!setxp @usuario <xp>` / `!resetxp @usuario` — corrigen la XP **total** de alguien
  (0 a 10 000 000). Solo el dueño del servidor o el rol DEVELOPER, también en EITO.
  Solo tocan `user_xp`: no modifican el Activo del mes ni dan o quitan roles de
  recompensa. Responden con el antes y el después y quedan en el canal de registros.
- `!fundadores [confirmar]` — asigna el rol Fundador a los 100 miembros más antiguos.
  Solo el dueño o un DEVELOPER. Sin `confirmar` muestra una vista previa; con
  `confirmar` guarda la lista y da el rol. Si ya se asignó, rechaza el comando.
- `!darnivel <nivel> [@usuario]` — asigna un nivel exacto. **Solo para pruebas**:
  se bloquea en el servidor definido en `EITO_GUILD_ID` (EITO).

### Moderación
- `!borrar <n>` — borra los últimos N mensajes (1–100) · *Gestionar mensajes*
- `!kick @usuario [razón]` · *Expulsar miembros*
- `!ban @usuario [razón]` · *Banear miembros*
- `!mute @usuario <duración> [razón]` (ej. `10m`, `2h`, `1d`) · *Moderar miembros*
- `!unmute @usuario` · *Moderar miembros*
- `!warn @usuario [razón]` · *Expulsar miembros*
- `!warns [@usuario]` — ver avisos. Cualquiera ve los suyos; ver los de otro requiere *Expulsar* o *Moderar miembros*

### Utilidad
- `!encuesta <pregunta>` — encuesta con 👍👎
- `!sugerencia <texto>` — sugerencia con votación
- `!steam <enlace o SteamID>` — publica tu perfil de Steam en el canal de perfiles
- `!jugar [mensaje]` — avisa a los **Leftsito** que buscas partida (cooldown de 10 min)

### Comunidad
- `!ping`, `!miembros`, `!avatar [@usuario]`, `!serverinfo`
- `!nivel [@usuario]` — nivel y XP
- `!antiguedad [@usuario]` — fecha de entrada, días en el server, rango (Veterano/Leyenda), cuánto falta para el siguiente y distinciones (🌱 Fundador, 🥇 OG)
- `!top` — ranking de niveles
- `!ayuda` — lista de comandos

## 🌐 Webhook de releases

`POST /release-webhook` con la cabecera `Authorization: Bearer <RELEASE_WEBHOOK_SECRET>`
y un JSON `{"version": "1.2.0", "changelog": "..."}` publica un aviso y menciona
al rol **🔔 Mod Loader**. `GET /` responde un health check.

## 🗂️ Datos

El bot guarda todo en **PostgreSQL** (`DATABASE_URL`), separado por servidor
(`guild_id`):
- `user_xp` — XP total de cada usuario
- `xp_mensual` — XP por usuario y mes (Activo del mes)
- `ganadores_mes` — historial de ganadores (evita premiar dos veces)
- `fundadores` — los 100 primeros miembros y su puesto (para devolverles el rol)
- `user_warns` — avisos de moderación
- `config_servidor` — configuración por servidor (panel +18)
- `mensajes_fijos` — canal y mensaje de reglas, guía, panel de roles y presentaciones (para editarlos)

## 🔒 Seguridad

- El token y las credenciales van en `.env` o en las variables del hosting,
  **nunca** en el código ni en el repo.
- `.gitignore` protege el `.env`.
