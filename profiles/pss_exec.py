"""Parte con Discord del perfil PSS: foto del servidor y ejecucion del plan.

`construir_snapshot` y `reunir_estado_mensajes` solo LEEN. `ejecutar` es lo unico que
escribe: recorre las acciones del plan en secuencia (sin reintentos propios: los 429 los
gestiona discord.py), captura Forbidden/NotFound/HTTPException por recurso y sigue con el
resto. Nunca borra nada.
"""

import traceback
from dataclasses import dataclass, field

import discord

from profiles import pss_db
from profiles.pss_plan import (
    SCanal, SMiembro, SRol, Snapshot, calcular_orden_payload, hash_contenido,
    overrides_efectivos, overwrites_deseados, renderizar, PendienteDeId, _deseado_orden,
)

RAZON = "Perfil PSS (!pss aplicar)"
CADA_CUANTAS_ACCIONES = 5     # cada cuantas acciones se avisa del progreso


# --- Lectura -------------------------------------------------------------------------------
_TIPO_POR_TYPE = {
    discord.ChannelType.category: "categoria", discord.ChannelType.text: "text",
    discord.ChannelType.news: "news", discord.ChannelType.forum: "forum",
    discord.ChannelType.voice: "voice", discord.ChannelType.stage_voice: "stage",
}


def _tipo_canal(c):
    """Tipo que distingue el perfil, a partir de `c.type` (vale para canales reales y falsos)."""
    return _TIPO_POR_TYPE.get(c.type, "otro")


def _foto_canal(c):
    """SCanal de un canal de discord.py (los tipos que distingue el perfil)."""
    tipo = _tipo_canal(c)
    overwrites = {t.id: tuple(p.value for p in ow.pair()) for t, ow in c.overwrites.items()}
    con_tema = tipo in ("text", "news", "forum")
    return SCanal(
        c.id, c.name, tipo, None if tipo == "categoria" else c.category_id,
        c.topic if con_tema else None,
        (c.slowmode_delay or 0) if con_tema else 0,
        c.user_limit if tipo == "voice" else 0,
        c.position, overwrites,
    )


def construir_snapshot(guild):
    """Foto del servidor para el calculo del plan (no modifica nada)."""
    yo = guild.me
    roles = [
        SRol(r.id, r.name, r.position, r.permissions.value, r.colour.value, r.hoist,
             r.mentionable, r.managed)
        for r in guild.roles
    ]
    canales = [_foto_canal(c) for c in guild.channels]
    miembros = [SMiembro(m.id, frozenset(r.id for r in m.roles), m.bot) for m in guild.members]
    permisos = yo.guild_permissions
    return Snapshot(
        guild_id=guild.id, owner_id=guild.owner_id, bot_id=yo.id,
        bot_permisos=permisos.value, bot_admin=permisos.administrator,
        bot_top=(yo.top_role.position, yo.top_role.id),
        roles=roles, canales=canales, miembros=miembros,
        features=frozenset(getattr(guild, "features", ()) or ()),
    )


async def reunir_estado_mensajes(guild, config, estado):
    """{key: existe | falta | ajeno | error} para los mensajes de la config ya guardados."""
    resultado = {}
    for m in config.mensajes:
        reg = estado.get(m.key)
        if reg is None or reg.tipo != "mensaje":
            continue
        canal = guild.get_channel(reg.canal_id) if reg.canal_id else None
        if canal is None:
            resultado[m.key] = "falta"
            continue
        try:
            mensaje = await canal.fetch_message(reg.discord_id)
        except discord.NotFound:
            resultado[m.key] = "falta"
        except discord.HTTPException:
            resultado[m.key] = "error"
        else:
            resultado[m.key] = "existe" if mensaje.author.id == guild.me.id else "ajeno"
    return resultado


# --- Escritura -----------------------------------------------------------------------------
@dataclass
class Resultado:
    hechos: list = field(default_factory=list)
    fallos: list = field(default_factory=list)
    bloqueadas: list = field(default_factory=list)
    ids: dict = field(default_factory=dict)


class _Falla(Exception):
    """Un recurso no se pudo aplicar por una causa propia (no de Discord)."""


def _ids_roles(config, ids):
    return {r.key: ids[r.key] for r in config.roles if r.key in ids}


def _mapa_overwrites(guild, deseados):
    """{entidad: PermissionOverwrite} para crear/editar canales (roles, @everyone o el bot)."""
    mapa = {}
    for objetivo, (allow, deny) in deseados.items():
        if objetivo == guild.id:
            entidad = guild.default_role
        elif objetivo == guild.me.id:
            entidad = guild.me
        else:
            entidad = guild.get_role(objetivo)
        if entidad is None:
            raise _Falla(f"el objetivo {objetivo} de un override ya no existe")
        mapa[entidad] = discord.PermissionOverwrite.from_pair(
            discord.Permissions(allow), discord.Permissions(deny)
        )
    return mapa


def _deseados(config, guild, ids, categoria, canal=None):
    overrides = overrides_efectivos(categoria, canal)
    deseados, pendiente = overwrites_deseados(overrides, _ids_roles(config, ids), guild.id, guild.me.id)
    if pendiente:
        raise _Falla("faltan roles para los overrides (¿falló su creación?)")
    return deseados


async def ejecutar(guild, plan, config, estado, fabrica_vista, progreso=None):
    """Aplica las acciones pendientes del plan. Devuelve un Resultado.

    `estado` es lo guardado en la BD (para editar mensajes); `fabrica_vista(keys)` crea la
    vista de botones de roles; `progreso(texto)` (opcional) recibe avisos de avance."""
    ids = dict(plan.ids)
    res = Resultado()
    fallidas = {a.key for a in plan.bloqueadas()}
    res.bloqueadas = [f"{a.tipo} {a.key}: {a.razon}" for a in plan.bloqueadas()]
    roles_nuevos = []
    no_menciones = discord.AllowedMentions.none()

    async def hacer_rol(a):
        r = config.rol(a.key)
        if a.op == "crear":
            rol = await guild.create_role(
                name=r.nombre, permissions=discord.Permissions(_bits_rol(r)),
                colour=discord.Colour(r.color), hoist=r.hoist, mentionable=r.mentionable, reason=RAZON,
            )
            ids[r.key] = rol.id
            roles_nuevos.append(rol)
            await pss_db.guardar(guild.id, r.key, "rol", rol.id, creado=True)
            return f"rol creado: {r.nombre}"
        if a.op == "actualizar":
            rol = guild.get_role(a.destino_id)
            if rol is None:
                raise _Falla("el rol ya no existe")
            opciones = {}
            c = a.cambios
            if "nombre" in c:
                opciones["name"] = r.nombre
            if "color" in c:
                opciones["colour"] = discord.Colour(r.color)
            if "hoist" in c:
                opciones["hoist"] = r.hoist
            if "mentionable" in c:
                opciones["mentionable"] = r.mentionable
            if "permisos" in c:
                opciones["permissions"] = discord.Permissions(_bits_rol(r))
            await rol.edit(reason=RAZON, **opciones)
        await pss_db.guardar(guild.id, r.key, "rol", a.destino_id)
        return f"rol {'actualizado' if a.op == 'actualizar' else 'vinculado'}: {r.nombre}"

    async def hacer_categoria(a):
        c = config.categoria(a.key)
        deseados = _deseados(config, guild, ids, c)
        if a.op == "crear":
            cat = await guild.create_category(c.nombre, overwrites=_mapa_overwrites(guild, deseados), reason=RAZON)
            ids[c.key] = cat.id
            await pss_db.guardar(guild.id, c.key, "categoria", cat.id, creado=True)
            return f"categoría creada: {c.nombre}"
        if a.op == "actualizar":
            cat = guild.get_channel(a.destino_id)
            if cat is None:
                raise _Falla("la categoría ya no existe")
            if "nombre" in a.cambios:
                await cat.edit(name=c.nombre, reason=RAZON)
            if "overwrites" in a.cambios:
                # set_permissions por objetivo: añade o corrige, nunca quita overrides ajenos.
                for entidad, ow in _mapa_overwrites(guild, deseados).items():
                    await cat.set_permissions(entidad, overwrite=ow, reason=RAZON)
        await pss_db.guardar(guild.id, c.key, "categoria", a.destino_id)
        return f"categoría {'actualizada' if a.op == 'actualizar' else 'vinculada'}: {c.nombre}"

    async def hacer_canal(a):
        c = config.canal(a.key)
        cat_cfg = config.categoria(c.categoria)
        if c.categoria in fallidas:
            raise _Falla(f"depende de la categoría '{c.categoria}', que falló")
        if a.op == "crear":
            cat = guild.get_channel(ids[c.categoria])
            # Overwrites explicitos (los de la categoria + los propios): no se depende de
            # que Discord sincronice solo, porque discord.py envia una lista vacia.
            ow = _mapa_overwrites(guild, _deseados(config, guild, ids, cat_cfg, c))
            opciones = {"category": cat, "overwrites": ow, "reason": RAZON}
            if c.tipo in ("text", "news", "forum"):
                if c.tema is not None:
                    opciones["topic"] = c.tema
                if c.slowmode is not None:
                    opciones["slowmode_delay"] = c.slowmode
                if c.tipo == "forum":
                    canal = await guild.create_forum(c.nombre, **opciones)
                else:
                    if c.tipo == "news":
                        opciones["news"] = True
                    canal = await guild.create_text_channel(c.nombre, **opciones)
            else:
                if c.limite_usuarios is not None:
                    opciones["user_limit"] = c.limite_usuarios
                canal = await guild.create_voice_channel(c.nombre, **opciones)
            ids[c.key] = canal.id
            await pss_db.guardar(guild.id, c.key, "canal", canal.id, creado=True)
            return f"canal creado: {c.nombre}"
        if a.op == "actualizar":
            canal = guild.get_channel(a.destino_id)
            if canal is None:
                raise _Falla("el canal ya no existe")
            cambios = a.cambios
            opciones = {}
            if "nombre" in cambios:
                opciones["name"] = c.nombre
            if "tema" in cambios:
                opciones["topic"] = c.tema
            if "slowmode" in cambios:
                opciones["slowmode_delay"] = c.slowmode
            if "limite_usuarios" in cambios:
                opciones["user_limit"] = c.limite_usuarios
            if "tipo" in cambios:
                opciones["type"] = discord.ChannelType.news
            if "mover" in cambios:
                destino = guild.get_channel(ids[c.categoria])
                if destino is None:
                    raise _Falla(f"la categoría '{c.categoria}' no existe")
                opciones["category"] = destino
            if "sincronizar" in cambios:
                opciones["sync_permissions"] = True
            if opciones:
                await canal.edit(reason=RAZON, **opciones)
            if "overwrites" in cambios:
                for entidad, ow in _mapa_overwrites(guild, _deseados(config, guild, ids, cat_cfg, c)).items():
                    await canal.set_permissions(entidad, overwrite=ow, reason=RAZON)
        await pss_db.guardar(guild.id, c.key, "canal", a.destino_id)
        return f"canal {'actualizado' if a.op == 'actualizar' else 'vinculado'}: {c.nombre}"

    async def hacer_mensaje(a):
        m = config.mensaje(a.key)
        if m.canal in fallidas:
            raise _Falla(f"depende del canal '{m.canal}', que falló")
        canal = guild.get_channel(ids[m.canal])
        if canal is None:
            raise _Falla(f"el canal '{m.canal}' no existe")
        try:
            renderizado = renderizar(m, ids)
        except PendienteDeId as e:
            raise _Falla(f"menciona «{e.args[0]}», que no existe") from None
        embed = discord.Embed.from_dict(renderizado["embed"])
        vista = fabrica_vista(m.botones_roles) if m.botones_roles else None
        extra = {"view": vista} if vista is not None else {}
        h = hash_contenido(renderizado)
        reg = estado.get(m.key)
        # Si el mensaje guardado esta en otro canal, no se edita: se publica el nuevo y se
        # borra el antiguo (solo si es del bot y el perfil lo tiene mapeado).
        cambia_canal = reg is not None and reg.canal_id != canal.id
        editar = a.op == "actualizar" and reg is not None and not cambia_canal and not a.cambios.get("republicar")
        if editar:
            try:
                original = await canal.fetch_message(reg.discord_id)
                if original.author.id != guild.me.id:
                    raise _Falla("el mensaje guardado no es del bot")
                await original.edit(embed=embed, **extra)
                await pss_db.guardar(guild.id, m.key, "mensaje", original.id, canal.id, h)
                return f"mensaje editado: {m.key}"
            except discord.NotFound:
                pass   # se borro entre el plan y ahora: se publica de nuevo
        enviado = await canal.send(embed=embed, allowed_mentions=no_menciones, **extra)
        await pss_db.guardar(guild.id, m.key, "mensaje", enviado.id, canal.id, h, creado=True)
        borrado = ""
        if cambia_canal and a.cambios.get("borrar_antiguo"):
            borrado = await _borrar_mensaje_antiguo(guild, reg)
        return f"mensaje publicado: {m.key}{borrado}"

    async def hacer_orden(a):
        frescos = await guild.fetch_channels()
        datos = [(c.id, _tipo_canal(c), None if c.type == discord.ChannelType.category else c.category_id, c.position)
                 for c in frescos]
        cats, canales = _deseado_orden(config, ids, ids)
        payload = calcular_orden_payload(datos, cats, canales)
        actual = {i: pos for i, _t, _c, pos in datos}
        if all(actual.get(p["id"]) == p["position"] for p in payload):
            return "orden de categorías y canales: ya estaba bien"
        # discord.py no expone el reordenado en bloque; es la misma peticion que usa Channel.move().
        await guild._state.http.bulk_channel_update(guild.id, payload, reason=RAZON)
        return "categorías y canales reordenados según el TOML"

    manejadores = {"rol": hacer_rol, "categoria": hacer_categoria, "canal": hacer_canal,
                   "mensaje": hacer_mensaje, "orden": hacer_orden}
    pendientes = plan.pendientes()
    for i, a in enumerate(pendientes, 1):
        etiqueta = f"{a.tipo} {a.key}"
        try:
            res.hechos.append(await manejadores[a.tipo](a))
        except discord.Forbidden:
            fallidas.add(a.key)
            res.fallos.append(f"{etiqueta}: Discord respondió «sin permisos» (revisa permisos y jerarquía del bot)")
        except discord.NotFound:
            fallidas.add(a.key)
            res.fallos.append(f"{etiqueta}: Discord respondió «no existe» (¿se borró durante la aplicación?)")
        except discord.HTTPException as e:
            fallidas.add(a.key)
            res.fallos.append(f"{etiqueta}: error de Discord ({e.status}) {e.text[:120]}")
        except _Falla as e:
            fallidas.add(a.key)
            res.fallos.append(f"{etiqueta}: {e}")
        except Exception as e:
            fallidas.add(a.key)
            print(f"⚠️ Perfil PSS: error inesperado en {etiqueta}:")
            traceback.print_exc()
            res.fallos.append(f"{etiqueta}: error inesperado ({type(e).__name__}); mira los logs")
        if progreso is not None and (i % CADA_CUANTAS_ACCIONES == 0):
            await progreso(f"⏳ Aplicando… {i}/{len(pendientes)}")

    # Los roles nuevos se crean uno encima del otro; se reordenan entre ellos para que
    # queden en el orden del TOML (solo permuta posiciones que ya ocupan: nunca sube
    # ninguno por encima del bot).
    if len(roles_nuevos) > 1:
        try:
            # Las posiciones de la cache pueden ir por detras de Discord: se piden frescas.
            frescos = {r.id: r for r in await guild.fetch_roles()}
            actuales = [frescos[r.id] for r in roles_nuevos if r.id in frescos]
            posiciones = sorted((r.position for r in actuales), reverse=True)
            if len(set(posiciones)) == len(posiciones) and [r.position for r in actuales] != posiciones:
                await guild.edit_role_positions(dict(zip(actuales, posiciones)), reason=RAZON)
                res.hechos.append("roles nuevos ordenados como en el TOML")
        except discord.HTTPException as e:
            res.fallos.append(f"orden de roles: no pude reordenarlos ({e.status}); arrástralos a mano")
    res.ids = ids
    return res


async def _borrar_mensaje_antiguo(guild, reg):
    """Borra el mensaje viejo SOLO si el perfil lo tiene mapeado y es del propio bot.

    Devuelve un texto para el reporte (vacio si no habia nada que borrar)."""
    canal = guild.get_channel(reg.canal_id) if reg.canal_id else None
    if canal is None:
        return " (el canal antiguo ya no existe)"
    try:
        viejo = await canal.fetch_message(reg.discord_id)
    except discord.NotFound:
        return " (el mensaje antiguo ya no existía)"
    if viejo.author.id != guild.me.id:
        return " (el mensaje antiguo no es del bot: no se borra)"
    try:
        await viejo.delete()
    except discord.HTTPException as e:
        return f" (no pude borrar el mensaje antiguo: {e.status})"
    return " (mensaje antiguo del bot borrado)"


def _bits_rol(r):
    return discord.Permissions(**{p: True for p in r.permisos}).value
