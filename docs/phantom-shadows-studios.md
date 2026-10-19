# Perfil temporal «Phantom Shadows Studios» (PSS)

Reutiliza el bot Eito para organizar el servidor de **Phantom Shadows Studios** (estudio de
desarrollo centrado en Roblox) sin tocar el comportamiento en ningún otro servidor.
Es una extensión aislada: `profiles/pss.py` + `profiles/pss.toml`, que se carga solo si
`PSS_PROFILE_ENABLED=1`. GitHub de la organización: https://github.com/Phantom-Shadows-Studios

- Servidor: `1420403964746268684` · dueño: `668148837579227137`.
- **PSS es un servidor público para la comunidad:** solo **🔒 » EQUIPO** y **🛡️ » STAFF** son
  privados. **📌 » IMPORTANTE** es visible para todos en solo lectura; COMUNIDAD, DESARROLLO y
  VOZ son abiertos. Formato de nombres: categorías `emoji » NOMBRE`, canales `emoji・nombre`.
- Todo lo del perfil actúa **solo** cuando `guild.id` coincide con el `guild_id` del TOML.
  En cualquier otro servidor `!pss` no responde y los eventos no cambian.

## 1. Cómo activarlo (variables en Railway)

| Variable | Valor | Para qué |
|---|---|---|
| `PSS_PROFILE_ENABLED` | `1` | Activa el perfil. Sin ella (o con otro valor) el bot arranca exactamente igual que antes. |
| `PSS_PROFILE_CONFIG` | ruta a un `.toml` | Opcional. Usa otro archivo en vez de `profiles/pss.toml` (p. ej. para un servidor de pruebas). |

Después de definirlas, reinicia/redespliega. En los logs debe salir
`✅ Perfil PSS cargado (servidor 1420403964746268684, 10 comandos de EITO bloqueados ahí).`
Si el TOML no es válido, el bot arranca igual pero sin perfil y los logs listan **todos** los
errores del archivo, uno por línea con su ruta (por ejemplo
`roles[3] 'colaborador'.permisos: permiso invalido 'manage_server' (¿'manage_guild'?)`).

La tabla `perfil_recursos` se crea sola al cargar el perfil (no existe si el perfil está apagado).

## 2. Orden de despliegue (importante)

0. **Activa Comunidad antes de aplicar** (sección 9, paso 3). El canal de anuncios (`📣・anuncios`)
   y el foro (`❓・ayuda`) la exigen: sin ella el plan los marca **«bloqueado: activa Comunidad»**
   y `!pss aplicar` hace todo lo demás; al activarla y repetir `!pss aplicar` se completan.
1. **(a) Sube el rol del bot** («EITO Setup Bot») por encima de los roles que va a gestionar
   (Developer, y donde quieras que queden los nuevos). Hoy comparte la posición 1 con
   Developer. Los roles nuevos se crean *por debajo* del rol del bot.
2. **(b) `!pss plan`** y revisa el resultado; luego **`!pss aplicar`** con el bot **todavía como
   administrador** (hace falta para crear roles como Administrador con permisos de gestión).
3. **(c) Baja el rol del bot** al entero mínimo de permisos **`1099780189270`**
   (Ajustes del servidor → Roles → *EITO Setup Bot*; no hace falta reinvitar). Equivale a:
   Ver canales, Enviar mensajes, Insertar enlaces, Leer historial, Adjuntar archivos, Añadir
   reacciones, Gestionar mensajes, Gestionar canales, Gestionar roles, Expulsar, Banear y
   Moderar miembros.
4. **(d) `!pss plan` otra vez:** todo debe salir en «⏭️ omitir» (nada pendiente ni bloqueado).
   El reporte de `!pss plan` y de `!pss aplicar` repite estos cuatro pasos.

Con el bot ya sin administrador, el plan marca **«bloqueado: el bot no tiene X»** cualquier
cosa que requiera un permiso que el bot no posee (p. ej. crear un rol con `manage_guild`). Lo
que ya existe y no necesita cambios sigue en «omitir».

Tras aplicar, a mano:
- **Arrastra «Propietario» por encima del rol del bot** (el bot no puede subir un rol por
  encima de sí mismo). Ese rol no tiene permisos: solo color y separación en la lista.
- **Da «Colaborador» (o «Developer») a quien deba ver 🔒 Equipo.** Los canales existentes
  `#info-importante` y `#planificación-de-sesiones` se mueven allí **y se sincronizan** con la
  categoría, igual que el canal de voz `🔊 Reuniones`, así que pasan a ser privados: quien no tenga
  «Developer», «Colaborador» o «Administrador» dejará de verlos.
  `!pss plan` avisa de a quién afecta. (`#frontend` y `#backend` son públicos: no afecta a nadie.)
- **Borra o archiva a mano lo que el plan lista en «🧹 A mano»:** las categorías que quedan
  vacías (`📢 Anuncios`, `🟥 Roblox`, `🛠️ Soporte`) y el `#ayuda` de texto antiguo, que queda
  **reemplazado** por el foro `❓・ayuda` (el bot no lo toca ni lo borra; `🛠️ Soporte` queda vacía
  cuando lo hayas retirado).
- Haz los [pasos manuales en Discord](#9-pasos-manuales-en-discord) de la sección 9.
- El bot da «Miembro» solo a quien entre **después**; a los miembros actuales se lo das tú si
  quieres que lo tengan.

## 3. Cómo editar el TOML y recargarlo

`profiles/pss.toml` describe el servidor. Cada recurso tiene una **`key` estable** (`a-z`, `0-9`,
`_`; única en todo el archivo) que **no debes cambiar**: es la clave del mapeo
`key → ID de Discord` que se guarda en PostgreSQL.

| Sección | Campos |
|---|---|
| `[perfil]` | `nombre`, `guild_id`, `owner_id` (solo verificación), `gestores` (keys de roles que pueden usar `!pss`; vacío = solo el dueño) |
| `[eventos]` | `xp`, `voz`, `anti_multicuentas` (true/false), `rol_al_entrar`, `bienvenida`, `canal_logs` (keys) |
| `[comandos]` | `bloquear = [...]` comandos de EITO que no funcionan en este servidor |
| `[[roles]]` | `key`, `nombre`, `color` (`"#RRGGBB"`), `hoist`, `mentionable`, `permisos` (flags de `discord.Permissions`), `existing_id`, `adoptar`, `permitir_admin`, `autoasignable` |
| `[[categorias]]` | `key`, `nombre`, `orden`, `existing_id`, `adoptar`, `overrides` |
| `[[canales]]` | `key`, `nombre`, `nombre_actual` (solo con `adoptar`: cómo se llama hoy, para renombrarlo), `categoria`, `tipo` (`text`/`voice`/`news`/`forum`), `reemplaza` (solo foros), `tema`, `slowmode`, `limite_usuarios`, `orden`, `existing_id`, `adoptar`, `mover`, `sincronizar_permisos`, `overrides` |
| `[[mensajes]]` | `key`, `canal`, `publicar`, `titulo`, `descripcion`, `color`, `campos`, `pie`, `botones_roles` |

- `overrides = [{ objetivo = "@everyone", permitir = [...], denegar = [...] }, ...]`; `objetivo`
  es `"@everyone"` o la key de un rol. Si denegar `view_channel`/`send_messages` a `@everyone`,
  el bot se añade solo un override propio (así sigue funcionando sin ser administrador).
- Los mensajes admiten `{canal:key}` y `{rol:key}` (menciones sin ping). `botones_roles` solo
  admite roles con `autoasignable = true` (sin permisos elevados).
- **Tipos de canal.** `text` (texto), `voice`, `news` (anuncios) y `forum` (foro). `news` y
  `forum` **exigen la función COMMUNITY**: si el servidor no la tiene el plan los marca
  «bloqueado: activa Comunidad». Un `news` puede *crearse* o *convertir un canal de texto
  existente* (`edit(type=news)`, si lo creó el bot o tiene `adoptar`). Un canal de texto **no se
  convierte en foro**: se crea un foro nuevo y, con `reemplaza = "ayuda"`, el plan lista el canal
  de texto con ese nombre como «reemplazado, archívalo o bórralo a mano» (no se toca).
- **Renombrar lo ya mapeado.** Cambiar el `nombre` de un recurso que creó el bot (o que ya está
  mapeado) **edita el mismo recurso** (mismo ID), nunca crea un duplicado. Un recurso que ya
  existía y no creó el bot necesita `adoptar = true` (y `nombre_actual` para encontrarlo por su
  nombre de hoy).
- **Orden.** Las categorías quedan en el orden de `orden` y, dentro de cada una, los canales en el
  `orden` del TOML (texto/anuncios/foros primero, voz después, como los muestra Discord). Discord
  pone cada categoría o canal nuevo **arriba**, así que el plan incluye una acción «orden» que lo
  corrige con una sola petición cuando hace falta.
- **Un rol con `administrator` exige `permitir_admin = true`.** El rol Propietario no lo tiene.
- El validador comprueba: flags de permisos, claves desconocidas o duplicadas, referencias a
  roles/canales/categorías inexistentes, y los límites de Discord (250 roles, 500 canales,
  50 canales por categoría, longitudes de nombre/tema/slowmode y de embed).

Para recargar: `!pss recargar` relee el archivo y lo valida (si hay errores sigue con el
anterior y los lista). **Ojo:** en Railway el sistema de archivos es efímero y sale del commit,
así que cambiar el TOML implica commit + redeploy; `!pss recargar` solo sirve en local o si el
archivo cambia en disco. `guild_id` no se puede cambiar con `recargar` (reinicia el bot).

## 4. El flujo plan → aplicar

- **`!pss plan`** calcula el diff y **no escribe nada**: 🆕 crear · ✏️ actualizar · 🔗 vincular
  (solo guarda el mapeo de algo que ya existía) · ⏭️ omitir · ⛔ bloqueado (con el motivo:
  permisos que le faltan al bot, jerarquía, nombre ambiguo, límites…), más advertencias.
- **`!pss aplicar`** muestra el resumen —incluido lo que se **moverá, renombrará, convertirá o
  sincronizará**, y los mensajes que se **republicarán borrando el antiguo del bot**— con un botón de confirmación (60 s, solo para quien lo
  invocó). Al confirmar:
  1. toma un `pg_try_advisory_lock` **por servidor** en PostgreSQL; si no lo consigue responde
     «Ya hay una aplicación en curso» (vale también entre dos instancias de Railway);
  2. recalcula el plan y, si cambió desde que lo viste, **no hace nada**;
  3. ejecuta en secuencia (roles → categorías → canales → mensajes → orden), omite lo que no cambia y
     captura `Forbidden`/`NotFound`/`HTTPException` por recurso para seguir con el resto
     (los 429 los gestiona discord.py, sin reintentos propios);
  4. publica un reporte con lo hecho, los fallos, lo bloqueado y lo que queda **a mano**.
- Cooldown de 30 s por servidor. Pueden usarlo el dueño y los roles de `gestores`.
- **Es idempotente:** repetirlo no duplica nada. Un recurso se busca primero por el ID guardado,
  luego por `existing_id` y por último por nombre normalizado (sin acentos, emojis ni
  separadores); si el nombre coincide con varios, queda bloqueado en vez de adivinar.
- Otros comandos: `!pss estado` (mapa key → ID guardado) y `!pss olvidar <key>` (borra solo el
  mapeo, nunca el recurso de Discord; útil si un ID guardado es incorrecto).

## 5. Qué hace y qué no hace

**Hace:** crea los roles, categorías y canales que faltan; mueve/sincroniza **solo** los
canales existentes marcados `mover`/`sincronizar_permisos`; publica y mantiene los mensajes
informativos: `#📜・reglas` solo tiene las reglas de comunidad pública, y `#ℹ️・info-estudio` la
info del estudio, la guía para nuevos y el panel de especialidades con botones `pss::rol::<key>`;
da el rol «Miembro» y manda una bienvenida a quien entra; encamina los logs de moderación al
canal `🛡️・registros` de Staff; deja categorías y canales en el orden del TOML.

**No hace:**
- **No borra ningún rol, canal ni categoría.** Las categorías que queden vacías y los canales
  reemplazados los borras tú: el plan los lista en «🧹 A mano».
- **Única excepción: mensajes.** Si un mensaje que el bot publicó cambia de canal en el TOML, se
  publica en el nuevo y se **borra el antiguo, solo si es un mensaje del bot que el perfil tiene
  mapeado** (nunca el de otro autor).
- No renombra, no mueve ni cambia permisos de lo que ya existía salvo que el TOML lo marque
  (`adoptar`, `mover`, `sincronizar_permisos`) y confirmes la aplicación.
- No toca el rol **Developer** (se reutiliza tal cual; **tiene `administrator`**: quien lo
  reciba ignora todos los overrides. Ponerle `adoptar = true` se lo quitaría).
- Los mensajes: edita solo los suyos y solo si el contenido (embed ya renderizado, con las
  menciones resueltas a IDs) cambió; si lo borraste, lo republica; nunca toca mensajes de otros.
- No asigna roles a miembros existentes.
- No publica proyectos: la organización no tiene repositorios públicos
  (consulta del 2026-10-18). Los canales de proyecto irán en 🔒 Equipo y el mensaje de
  «proyectos activos» están **comentados** en el TOML como ejemplo; no se publica texto de relleno.
- Estructura pequeña a propósito: 15 canales de texto, anuncios y foros (máximo 16) y 2 de voz.
  Lo demás está comentado en el TOML como plantilla: `#staff-chat`, canales de proyecto, **una
  categoría por juego** (`🎮 » [JUEGO]` con noticias = news, códigos, sugerencias y bug-report =
  foro) y **`🗄️ » ARCHIVO`** (solo lectura para todos).

### Eventos de EITO en PSS (`[eventos]`)
- `xp = false`: sin XP por mensajes ni avisos de subida de nivel (`!nivel`, `!top`, `!perfil`
  siguen respondiendo, con ceros). `voz = false`: sin XP ni contadores por voz.
- `anti_multicuentas = true`: como PSS es público, **se aplica el filtro de cuentas nuevas** de EITO
  (expulsa cuentas con menos de `EDAD_MINIMA_DIAS` días, por defecto 7; esa variable es global,
  también vale para EITO; las excepciones se dan con `!permitir <ID>`). El filtro no escucha
  por su cuenta: lo llama `on_member_join` de EITO, y en PSS ese evento lo atiende el perfil
  (`al_entrar`), que solo invoca el filtro si el TOML lo pide. Si expulsa, no hay rol ni
  bienvenida, y el aviso va al canal `registros`.
- `canal_logs = "registros"`: `registrar_log` usa ese canal en PSS; si el perfil no está
  cargado (o no hay canal) usa `🛡️・registros` como siempre.

### Comandos bloqueados en PSS
`!setup`, `!setupsteam`, `!setuprecompensas`, `!crearvcs`, `!panelcochipuerco`, `!panelroles`,
`!reglas`, `!info`/`!guia`, `!presentaciones` y `!paneltickets` (crearían o publicarían
estructura de EITO, y los tickets usan IDs de roles de EITO). Responden «Este comando de EITO no
está disponible en Phantom Shadows Studios». Moderación, `!encuesta`, `!sugerencia`, `!nivel`,
`!top`, `!ayuda`, `!anuncio`, `!exportarserver`… siguen funcionando.

## 6. Probarlo sin staging

1. Crea un servidor de pruebas e invita ahí al bot (o usa uno que ya tengas).
2. Copia `profiles/pss.toml` a `profiles/pss.test.toml`, cambia `guild_id`, `owner_id` y quita
   los `existing_id`; define `PSS_PROFILE_ENABLED=1` y `PSS_PROFILE_CONFIG=profiles/pss.test.toml`.
3. Ejecuta `!pss plan`, `!pss aplicar` y otra vez `!pss plan` (todo en «omitir»).
4. En PSS, `!pss plan` es de solo lectura: úsalo antes de aplicar.

## 7. Riesgos conocidos

- **Developer con `administrator`** y mismo rango que el bot (el empate lo decide el ID del
  rol): el bot puede no poder editarlo; el plan lo avisa.
- Si el perfil falla al cargarse, PSS vuelve a quedar con el comportamiento actual de EITO
  (anti-multicuentas, XP…). Mira los logs tras cada deploy.
- Si la conexión a PostgreSQL se corta durante `aplicar`, el lock se libera solo (la sesión
  termina) pero la aplicación continúa; repetir `!pss aplicar` es seguro.
- Los 5 miembros actuales dejarán de ver `#info-importante`, `#planificación-de-sesiones` y
  `🔊 Reuniones` (pasan a 🔒 Equipo) hasta recibir «Colaborador», «Developer» o «Administrador».
- **Pendiente de confirmar:** los emojis de `#🎨・frontend` y `#⚙️・backend` (renombrar canales
  existentes). Si no los quieres, quita `nombre_actual` y `adoptar` de esas dos entradas.
- `#💡・sugerencias` debe llamarse **exactamente** así: es el nombre que busca `!sugerencia` de EITO.
- Convertir `#anuncios` a canal de anuncios y crear el foro necesitan Comunidad (paso 0).
- El orden usa la misma petición interna que `Channel.move()` de discord.py (una sola llamada
  para todas las categorías y canales).
- El filtro anti-multicuentas expulsa cuentas nuevas: un colaborador legítimo con la cuenta
  recién creada necesita `!permitir <ID>` antes de entrar.

## 8. Estructura resultante

Visibilidad y quién escribe en cada categoría (15 canales de texto, anuncios y foros + 2 de voz). «Existente» =
ya estaba en el servidor; «del bot» = lo creó el perfil antes. Los existentes se renombran con
`adoptar = true` + `nombre_actual` (solo el nombre; nunca se cambia su tema). Las categorías
`📢 Anuncios`, `🟥 Roblox` y `🛠️ Soporte` desaparecen del TOML: sus canales se mueven y quedan
vacías (a borrar a mano); `📌 Estudio` se reutiliza y pasa a llamarse `📌 » IMPORTANTE`.

```
📌 » IMPORTANTE   [👁️ ven: todos · escriben: Developer + Administrador (+ bot)]
  ├─ 📜・reglas             del bot, se renombra · solo las reglas
  ├─ 📣・anuncios           del bot, se convierte en canal de ANUNCIOS y se mueve · requiere Comunidad
  └─ ℹ️・info-estudio       nuevo · info del estudio, guía y botones de especialidad
💬 » COMUNIDAD    [👁️ ven: todos · escriben: todos]
  ├─ 💬・general            existente (general), se renombra
  ├─ 📸・showcase           del bot, se renombra · cualquiera publica
  ├─ 💡・sugerencias        nuevo · nombre exacto que usa !sugerencia
  ├─ 🤖・comandos           nuevo
  └─ 🎲・no-relacionado     existente (no-relacionado), se renombra
💻 » DESARROLLO   [👁️ ven: todos · escriben: todos]
  ├─ 🟥・scripting-luau     del bot, se renombra y se mueve desde 🟥 Roblox
  ├─ 🎨・frontend           existente, se renombra   [PENDIENTE DE CONFIRMAR]
  ├─ ⚙️・backend            existente, se renombra   [PENDIENTE DE CONFIRMAR]
  └─ ❓・ayuda              FORO nuevo · el #ayuda de texto actual no se toca ("reemplazado") · requiere Comunidad
🔊 » VOZ          [👁️ ven y hablan: todos]
  └─ 🔊 General             del bot
🔒 » EQUIPO       [🔒 ven y escriben: Developer + Colaborador + Administrador (+ bot)]
  ├─ 📌・info-importante    existente, se renombra y se sincroniza (privado)
  ├─ 🗓️・planificación-de-sesiones   existente, se renombra y se sincroniza (privado)
  └─ 🔊 Reuniones           voz existente, se sincroniza (privada); sin renombrar
🛡️ » STAFF        [🔒 ven y escriben: Propietario + Administrador (+ bot)]
  └─ 🛡️・registros          del bot, se renombra · logs de moderación
```

Los roles y sus permisos están en `profiles/pss.toml` (Propietario sin permisos; Administrador
con gestión del servidor pero sin `administrator`; Developer existente, sin tocar; Colaborador y
Miembro con permisos básicos; Scripter, Builder y UI autoasignables y sin permisos).
Todo lo demás está comentado en el TOML como ejemplo.

## 9. Pasos manuales en Discord

El bot no puede (ni debe) hacer esto por ti; son ajustes del servidor que hay que revisar a
mano al abrirlo a la comunidad:

1. **Ajustes del servidor → Roles → @everyone:** desactiva **Mencionar @everyone, @here y todos
   los roles** (`mention_everyone`), **Crear eventos** (`create_events`) y **Crear expresiones**
   (`create_expressions`).
2. **Ajustes del servidor → Roles → Developer:** desactiva **Administrador**
   (`administrator`). Mientras lo tenga, quien reciba ese rol ignora todos los overrides, incluido
   el de 🔒 Equipo y 🛡️ Staff. Al quitárselo, dale los permisos que necesite (p. ej. los mismos
   que a «Colaborador»); el bot nunca lo toca (no se adopta).
3. **Activar Comunidad** (Ajustes del servidor → Habilitar la comunidad) **antes de
   `!pss aplicar`**: pide un canal de reglas (`#reglas`) y un canal de actualizaciones (elige
   `#anuncios`; el perfil lo convierte en canal de anuncios si Discord no lo hace antes).
   Sin Comunidad no se pueden crear canales de anuncios ni foros.
4. **Nivel de verificación: Media** (correo verificado y cuenta registrada en Discord desde hace
   más de 5 minutos).
5. **Filtro de contenido multimedia explícito:** analizar el contenido de **todos los miembros**.
6. **Onboarding** (Ajustes del servidor → Onboarding; requiere Comunidad): configura **solo los
   canales por defecto** (`#reglas`, `#info-estudio`, `#general`, `#showcase`…). **No añadas
   preguntas que den roles:** las especialidades (Scripter, Builder, UI) se eligen con los botones
   del bot en `#info-estudio`, y el rol «Miembro» lo da el propio bot al entrar.

## 10. Desactivarlo y retirarlo por completo

1. Quita `PSS_PROFILE_ENABLED` (y `PSS_PROFILE_CONFIG`) en Railway y redespliega: el bot vuelve
   a arrancar exactamente como antes. Los roles/canales/mensajes creados **se quedan** en
   Discord (el bot nunca borra).
2. Borra la carpeta `profiles/`, `tests/test_pss_*.py` y este documento.
3. Deja `eito_setup_bot.py` como estaba: quita el bloque `PSS_PROFILE_ENABLED`, la función
   `evento_permitido` y sus 2 usos (`sumar_xp`, `contar_voz_guild`), la línea `perfil = bot.get_cog(...)`
   en `registrar_log`, la delegación en `on_member_join` y el bloque `load_extension` de
   `setup_hook` (o `git revert` del commit que los añadió).
4. Opcional, borrar la tabla: `DROP TABLE perfil_recursos;`
5. Opcional, limpiar datos de PSS que el bot acumuló *antes* del perfil (XP y contadores):
   ```sql
   DELETE FROM user_xp     WHERE guild_id = '1420403964746268684';
   DELETE FROM xp_mensual  WHERE guild_id = '1420403964746268684';
   DELETE FROM contadores  WHERE guild_id = '1420403964746268684';
   ```
