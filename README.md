# 🤖 EITO Setup Bot

Bot de Discord para la comunidad **EITO** (gaming / Left 4 Dead). Monta la
estructura del servidor y añade funciones de comunidad, moderación y niveles.

## ✨ Funciones

- **Setup automático**: crea categorías, canales y roles con un solo comando.
- **Bienvenida** automática + rol al entrar.
- **Panel de roles** con botones (plataforma, región y avisos) y rol +18 por reacción.
- **Niveles/XP** con ranking, recompensas por nivel y **Activo del mes**.
- **Moderación**: borrar, kick, ban, mute, warns.
- **Tickets de soporte** privados con el staff, con transcripción al cerrar.
- **Utilidades**: encuestas, sugerencias, perfiles de Steam y búsqueda de partida (`!jugar` con botón «Me apunto»).
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

### 🎮 Convocatorias (`!jugar`) y rangos por partidas

`!jugar [mensaje]` publica en `🎮・buscar-partida` una convocatoria que menciona a los
**Leftsito** con dos botones: **✋ Me apunto** (alterna apuntarse y salirse; quien
convoca ya cuenta) y **🔒 Cerrar** (solo quien convocó o un moderador). El embed lista
los apuntados (hasta 15 nombres y «+X más») y se actualiza en cada clic. La convocatoria
dura 2 horas: al cerrarse (por tiempo, por el botón o por un clic tardío) se deshabilitan
los botones y, si se apuntó al menos una persona más, se cuenta **una sola vez**:
+1 «partida» al autor y a cada apuntado, y +1 «convocatoria exitosa» al autor.
Sin apuntados no se cuenta nada. Los botones sobreviven a los reinicios.

Para evitar el farmeo, una convocatoria solo cuenta si estuvo abierta **al menos
15 minutos** (si se cierra antes, se cierra igual, pero el embed dice «no cuenta:
cerrada antes de 15 min» y no suma nada), y cada persona suma como máximo **3 partidas
por día** (y el autor 3 convocatorias exitosas por día; el día se mide en UTC-5). Si
alguien ya llegó al límite, no suma más, pero los demás apuntados sí.

Al llegar a **10 partidas** se gana **🧟 Superviviente** y a **10 convocatorias exitosas**
**🎯 Convocador**: el bot da el rol, lo anuncia en el canal de logros y nunca lo quita.
Cada 6 horas revisa estos umbrales como respaldo (sin anunciar). Los IDs de estos roles
(`ROL_SUPERVIVIENTE_ID`, `ROL_CONVOCADOR_ID`) se configuran en `eito_setup_bot.py`;
mientras estén en 0 los contadores se registran pero el rol no se asigna.

### 🎧 Voz activa (XP por voz)

Cada 5 minutos el bot recorre los canales de voz y, a quien está **acompañado**, le suma
**5 minutos y 5 XP** (1 XP por minuto, total y del mes: cuenta para el Activo del mes).
Condiciones: el canal debe tener **al menos 2 personas** que cuenten; los bots y quienes
están **ensordecidos** no cuentan (estar muteado sí); el **canal AFK** no cuenta. Hay un
tope de **6 horas por día** por persona (día en UTC-5): al llegar, ese día ya no suma.
A las **50 horas** acumuladas se gana **🎧 Voz activa** (con anuncio en logros; permanente).
`!perfil` muestra tu tiempo en voz, el progreso hacia el rango y lo contado hoy.

### 🎫 Tickets de soporte

`!paneltickets` publica un panel con el botón **🎫 Abrir ticket**. Cada usuario puede
tener **un ticket abierto**: el bot crea `ticket-<nombre>` en la categoría **🎫 TICKETS**
(la crea si falta), visible solo para esa persona y el staff (`ROLES_STAFF_TICKETS`: EITO LA GOAT,
DEVELOPER, Admins y Moderador, por ID). El mensaje de bienvenida, con el botón **🔒 Cerrar ticket**,
menciona al usuario y **solo a Admins y Moderador** (`ROLES_PING_TICKETS`); EITO LA GOAT y DEVELOPER
ven el ticket pero no reciben ping. El dueño se guarda en el topic del canal (`ticket:<id>`), sin tablas nuevas. Cerrarlo
(solo el dueño o el staff) guarda una transcripción `.txt` (fecha, autor, contenido y
URLs de adjuntos) en **📁・tickets-log** (categoría 🛡️ STAFF, visible solo para el staff de
tickets), avisa, espera 5 segundos y borra el canal. Si no puede guardar la transcripción,
el ticket no se cierra. Tampoco se cierra (ni se envía nada) si @everyone puede ver el canal de
transcripciones: avisa en el ticket y lo registra en el canal de registros. `!paneltickets` y
`!setup confirmar` reconfiguran los permisos de `🎫・soporte` (solo lectura) y de `📁・tickets-log`. Los botones sobreviven a los reinicios. El bot necesita
**Gestionar canales**.

### 🏅 Logros

Los logros se anuncian en el canal **🏅・logros** (lo creas tú a mano; si no existe se
usa el canal de niveles): «🎉 ¡Felicidades @usuario!» (se menciona solo a esa persona) y un
embed con el color del rol, su avatar, un título y una frase propios de cada rango y la
posición entre quienes lo tienen («Eres el OG #3»). Los textos están en `LOGROS_INFO`. Además, cuando el staff **agrega a mano**
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
   admin corre `!setup` (vista previa) y, si todo está bien, `!setup confirmar`.

## 📖 Comandos

Todos usan el prefijo `!` y **solo funcionan en un servidor**: por mensaje privado el
bot responde que no están disponibles. Escribe `!ayuda` en el servidor para ver la lista
según tus permisos.

### Administración (solo admins)
- `!setup [confirmar]` — sin argumento solo muestra una **vista previa**: lista completa de lo que se **creará**, las categorías omitidas (sus canales ya existen), un resumen por categoría de lo que **ya existe** y los permisos que reconfiguraría. Las categorías se buscan por ID y luego por nombre; un canal que ya existe en cualquier categoría no se crea ni se mueve. Con `!setup confirmar` crea lo que falta
- `!setupsteam` — reconfigura el canal de perfiles de Steam (solo-bot)
- `!setuprecompensas` — reconfigura los canales de recompensa por nivel
- `!reglas` — publica las reglas; si ya existe el mensaje, lo **edita** en vez de duplicarlo
- `!info` (alias `!guia`) — publica o edita la guía de inicio
- `!panelroles` — publica o edita el panel de roles con botones (los botones siguen funcionando)
- `!paneltickets` — publica o edita el panel de soporte con el botón **Abrir ticket** en `🎫・soporte` (o en el canal actual si no existe)
- `!presentaciones` — publica o edita la plantilla de presentación
- `!anuncio [everyone|here] <texto>` — publica un anuncio (permiso *Gestionar servidor*: también lo pueden usar los admins y el staff con ese permiso). Con `everyone` o `here` como **primera palabra** añade ese ping fuera del embed; además hace falta el permiso *Mencionar @everyone* en el canal de anuncios
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
- `!darnivel <nivel> [@usuario]` — asigna un nivel exacto (máximo 200). **Solo para pruebas**:
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
- `!jugar [mensaje]` — busca gente para jugar: avisa a los **Leftsito** y los demás se apuntan con un botón (cooldown de 10 min)

### Comunidad
- `!ping`, `!miembros`, `!avatar [@usuario]`, `!serverinfo`
- `!nivel [@usuario]` — nivel y XP
- `!perfil [@usuario]` — tu tarjeta: nivel y XP, días y rango de antigüedad, distinciones (🌱 Fundador, 🥇 OG, 🔥 Activo del mes ×N) y progreso hacia 🧟 Superviviente y 🎯 Convocador
- `!antiguedad [@usuario]` — fecha de entrada, días en el server, rango (Veterano/Leyenda), cuánto falta para el siguiente y distinciones (🌱 Fundador, 🥇 OG)
- `!top` — ranking de niveles
- `!ayuda` — lista de comandos

## 🌐 Webhook de releases

`POST /release-webhook` con la cabecera `Authorization: Bearer <RELEASE_WEBHOOK_SECRET>`
y un JSON `{"version": "1.2.0", "changelog": "..."}` publica un aviso y menciona
al rol **🔔 Mod Loader**. El body debe ser un objeto JSON y `version` y `changelog` deben
ser texto (si no, responde 400); el título se recorta a 256 caracteres y la descripción
a 4096. El secreto se compara en tiempo constante. `GET /` responde un health check.

## 🗂️ Datos

El bot guarda todo en **PostgreSQL** (`DATABASE_URL`), separado por servidor
(`guild_id`):
- `user_xp` — XP total de cada usuario
- `xp_mensual` — XP por usuario y mes (Activo del mes)
- `ganadores_mes` — historial de ganadores (evita premiar dos veces)
- `fundadores` — los 100 primeros miembros y su puesto (para devolverles el rol)
- `contadores` — contadores por usuario (partidas, convocatorias exitosas)
- `lfg_posts` y `lfg_participantes` — convocatorias de `!jugar` y sus apuntados
- `user_warns` — avisos de moderación
- `config_servidor` — configuración por servidor (panel +18)
- `mensajes_fijos` — canal y mensaje de reglas, guía, panel de roles, panel de tickets y presentaciones (para editarlos)

## 🔒 Seguridad

- El token y las credenciales van en `.env` o en las variables del hosting,
  **nunca** en el código ni en el repo.
- `.gitignore` protege el `.env`.
- **Protección global de menciones:** el bot se crea con `allowed_mentions` sin `@everyone`/`@here`
  ni roles (solo usuarios), así que ningún mensaje —por ejemplo una razón de `!warn` con
  `@everyone`— puede pinguear de forma masiva. Los envíos que sí deben mencionar algo lo piden
  explícitamente: `!jugar` (rol Leftsito), el webhook de releases (rol Mod Loader),
  `!anuncio everyone|here` (solo con el permiso *Mencionar @everyone*) y la bienvenida de
  los tickets (Admins y Moderador).
- La conexión a la base de datos usa `pool_pre_ping` y `pool_recycle=1800` para no fallar con
  conexiones cortadas por inactividad.
