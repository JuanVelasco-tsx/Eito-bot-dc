"""Planificador + ejecutor del perfil PSS contra un servidor FALSO (sin Discord ni BD).

Pruebas de punta a punta con el profiles/pss.toml real: se aplica sobre una copia del estado
de PSS (con el bot como administrador) y despues, con el bot ya bajado al entero minimo de
permisos, el plan debe dar todo en «omitir». Tambien se prueba la MIGRACION: se aplica la
version anterior del TOML (tests/fixtures/pss_v1.toml, la de verdad desplegada) y encima la
nueva, para comprobar que renombrar recursos ya mapeados los edita y no crea duplicados."""

import types
from dataclasses import replace
from pathlib import Path

import discord
import pytest

from profiles import pss_db
from profiles.pss_config import cargar
from profiles.pss_exec import ejecutar
from profiles.pss_plan import (
    Registro, bits, calcular_orden_payload, calcular_plan, lineas_plan, normalizar, orden_ya_correcto,
)
from tests.pss_fakes import (
    BOT, DEVELOPER, G, MINIMO_BOT, FCanal, FMensaje, FMiembro, FServidor, estado_mensajes, foto, orden_actual,
)

RUTA = Path(__file__).resolve().parent.parent / "profiles" / "pss.toml"
RUTA_V1 = Path(__file__).resolve().parent / "fixtures" / "pss_v1.toml"

CATEGORIAS_FINAL = ["📌 » IMPORTANTE", "💬 » COMUNIDAD", "💻 » DESARROLLO", "🔊 » VOZ", "🔒 » EQUIPO", "🛡️ » STAFF"]
HIJOS_FINAL = {
    "📌 » IMPORTANTE": ["📜・reglas", "👋・bienvenida", "📣・anuncios", "ℹ️・info-estudio"],
    "💬 » COMUNIDAD": ["💬・general", "🙋・presentaciones", "📸・showcase", "💡・sugerencias", "🤖・comandos",
                      "📈・niveles", "🎲・no-relacionado"],
    "💻 » DESARROLLO": ["🟥・scripting-luau", "❓・ayuda"],
    "🔊 » VOZ": ["🔊 General"],
    "🔒 » EQUIPO": ["📌・info-importante", "🗓️・planificación-de-sesiones", "Reuniones"],
    "🛡️ » STAFF": ["🛡️・registros", "🧪・pruebas-bot"],
}


@pytest.fixture
def guardado(monkeypatch):
    """Sustituye pss_db.guardar por un diccionario en memoria: {key: Registro}."""
    estado = {}

    async def guardar(guild_id, key, tipo, discord_id, canal_id=None, hash_contenido=None, creado=False):
        previo = estado.get(key)
        mantiene = previo is not None and previo.discord_id == discord_id and previo.creado
        estado[key] = Registro(tipo, discord_id, canal_id, hash_contenido, creado or mantiene)

    monkeypatch.setattr(pss_db, "guardar", guardar)
    return estado


async def aplicar(srv, config, estado, admin=True, permisos=8):
    plan = calcular_plan(config, foto(srv, admin, permisos), estado, estado_mensajes(srv, config, estado))
    res = await ejecutar(srv, plan, config, estado, lambda keys: object())
    return plan, res


def plan_de(srv, config, estado, admin=True, permisos=8):
    return calcular_plan(config, foto(srv, admin, permisos), estado, estado_mensajes(srv, config, estado))


def por_nombre(srv):
    return {c.name: c for c in srv.canales.values()}


def acciones(plan):
    return {a.key: a for a in plan.acciones}


# --- Servidor nuevo: estructura, nombres, tipos y orden ---------------------------------------------
async def test_aplicar_crea_lo_que_falta_y_el_plan_posterior_da_todo_omitir(guardado):
    config, srv = cargar(RUTA), FServidor()
    plan, res = await aplicar(srv, config, guardado)
    assert res.fallos == [] and res.bloqueadas == []

    nombres_roles = {r.name for r in srv.roles}
    assert {"Propietario", "Administrador", "Colaborador", "Miembro", "Scripter", "Builder", "UI"} <= nombres_roles
    propietario = next(r for r in srv.roles if r.name == "Propietario")
    assert propietario.permissions.value == 0 and propietario.hoist       # sin administrator
    assert srv.get_role(DEVELOPER).permissions.administrator               # Developer intacto

    # --- bug de orden: las categorias y canales quedan en el orden del TOML ---
    cats, hijos = orden_actual(srv)
    assert cats[:6] == CATEGORIAS_FINAL
    assert cats[6:] == ["Información", "Canales de texto", "Canales de voz"]   # las viejas, abajo
    for categoria, esperados in HIJOS_FINAL.items():
        assert hijos[categoria] == esperados

    c = por_nombre(srv)
    # tipos
    assert c["📣・anuncios"].tipo == "news" and c["❓・ayuda"].tipo == "forum"
    assert c["💬・general"].tipo == "text" and c["🔊 General"].tipo == "voice"
    # existentes: renombrados SIN crear duplicados (mismos IDs de siempre)
    for ident, nombre in {21: "💬・general", 24: "🎲・no-relacionado", 20: "📌・info-importante",
                          23: "🗓️・planificación-de-sesiones"}.items():
        assert srv.canales[ident].name == nombre
    # #frontend y #backend ya no estan en el TOML: el bot no los toca (siguen donde estaban)
    assert srv.canales[25].name == "frontend" and srv.canales[26].name == "backend"
    assert srv.canales[25].category_id == 11 and srv.canales[26].category_id == 11
    assert srv.canales[20].topic is None                                     # no se cambia su tema
    assert srv.canales[30].name == "Reuniones"                                # sin renombrar
    # el #deberes-ayuda original no se toca: el foro es uno nuevo
    assert srv.canales[22].name == "deberes-ayuda" and srv.canales[22].tipo == "text"
    # EITO busca este nombre exacto para !sugerencia
    assert "💡・sugerencias" in c
    # categorias
    assert "📂 Proyectos" not in c and not any(n in c for n in ("📢 Anuncios", "🟥 Roblox", "🛠️ Soporte"))

    # Equipo: privada, con Administrador, developer, colaborador y el bot
    equipo = c["🔒 » EQUIPO"]
    por_id = {getattr(e, "id", None): ow for e, ow in equipo.overwrites.items()}
    administrador = next(r for r in srv.roles if r.name == "Administrador")
    colaborador = next(r for r in srv.roles if r.name == "Colaborador")
    assert por_id[G].pair()[1].view_channel is True
    for ident in (administrador.id, DEVELOPER, colaborador.id):
        assert por_id[ident].pair()[0].view_channel is True
    assert por_id[BOT].pair()[0].view_channel and por_id[BOT].pair()[0].send_messages
    for n in ("📌・info-importante", "🗓️・planificación-de-sesiones", "Reuniones"):
        assert c[n].category is equipo and c[n].overwrites == equipo.overwrites
    # Publicas: sin overrides
    for n in ("💬 » COMUNIDAD", "💻 » DESARROLLO", "🔊 » VOZ", "💬・general", "❓・ayuda", "🔊 General"):
        assert c[n].overwrites == {}
    # IMPORTANTE: solo lectura para @everyone; escriben developer y administrador (+ bot)
    importante = c["📌 » IMPORTANTE"]
    ow = {getattr(e, "id", None): o for e, o in importante.overwrites.items()}
    assert ow[G].pair()[1].send_messages is True and ow[G].pair()[1].view_channel is False
    assert ow[DEVELOPER].pair()[0].send_messages is True and BOT in ow
    assert c["📜・reglas"].overwrites == importante.overwrites and c["ℹ️・info-estudio"].overwrites == importante.overwrites
    assert c["🛡️・registros"].overwrites == c["🛡️ » STAFF"].overwrites
    # Fase 1: bienvenida en IMPORTANTE (solo lectura), presentaciones publica, niveles solo lectura, pruebas-bot en Staff
    assert c["👋・bienvenida"].overwrites == importante.overwrites
    assert c["🙋・presentaciones"].overwrites == {}
    niveles = {getattr(e, "id", None): o for e, o in c["📈・niveles"].overwrites.items()}
    assert niveles[G].pair()[1].send_messages is True and BOT in niveles and DEVELOPER not in niveles
    assert c["🧪・pruebas-bot"].overwrites == c["🛡️ » STAFF"].overwrites
    helper = next(r for r in srv.roles if r.name == "Helper")
    novedades = next(r for r in srv.roles if r.name == "🔔 Novedades")
    assert helper.permissions.value == 0 and helper.hoist and not helper.mentionable
    assert novedades.mentionable and novedades.permissions.value == 0
    assert [m.embed.title for m in c["🙋・presentaciones"].mensajes.values()] == ["🙋 Preséntate"]

    # Mensajes: #reglas solo las reglas; info, guia y botones en #info-estudio
    assert [m.embed.title for m in c["📜・reglas"].mensajes.values()] == ["📜 Reglas"]
    assert [m.embed.title for m in c["ℹ️・info-estudio"].mensajes.values()] == [
        "👻 Phantom Shadows Studios", "🧭 Guía para nuevos integrantes", "🎭 Especialidades y avisos"]
    assert list(c["ℹ️・info-estudio"].mensajes.values())[2].view is not None      # panel con botones
    regla = next(iter(c["📜・reglas"].mensajes.values()))
    assert f"<#{c['❓・ayuda'].id}>" in regla.embed.description               # menciones resueltas al foro

    # --- (c) el bot baja al entero minimo y (d) el plan da todo en omitir ---
    plan2, res2 = await aplicar(srv, config, guardado, admin=False, permisos=MINIMO_BOT)
    assert [a for a in plan2.acciones if a.op != "omitir"] == [], "\n".join(lineas_plan(plan2))
    assert res2.hechos == []


async def test_reaplicar_no_repite_llamadas_ni_duplica(guardado):
    config, srv = cargar(RUTA), FServidor()
    await aplicar(srv, config, guardado)
    antes = list(srv.llamadas)
    mensajes_antes = sum(len(c.mensajes) for c in srv.canales.values())
    await aplicar(srv, config, guardado)
    assert srv.llamadas == antes
    assert sum(len(c.mensajes) for c in srv.canales.values()) == mensajes_antes


async def test_el_orden_sale_bien_tanto_si_discord_pone_lo_nuevo_arriba_como_abajo(guardado):
    for arriba in (True, False):
        guardado.clear()
        config, srv = cargar(RUTA), FServidor()
        srv.canales_arriba = arriba
        await aplicar(srv, config, guardado)
        cats, hijos = orden_actual(srv)
        assert cats[:6] == CATEGORIAS_FINAL, arriba
        assert hijos == {**hijos, **HIJOS_FINAL}


async def test_se_crean_en_orden_los_roles_nuevos(guardado):
    config, srv = cargar(RUTA), FServidor()
    await aplicar(srv, config, guardado)
    orden = [r.name for r in sorted((r for r in srv.roles if r.name in {"Propietario", "Administrador", "Colaborador", "Miembro"}),
                                     key=lambda r: -r.position)]
    assert orden == ["Propietario", "Administrador", "Colaborador", "Miembro"]


async def test_si_discord_deja_los_roles_nuevos_al_reves_se_reordenan_entre_ellos(guardado):
    config, srv = cargar(RUTA), FServidor()
    srv.nuevos_arriba = True
    antes = {r.id: r.position for r in srv.roles}
    await aplicar(srv, config, guardado)
    nuevos = ["Propietario", "Administrador", "Colaborador", "Miembro"]
    orden = [r.name for r in sorted((r for r in srv.roles if r.name in nuevos), key=lambda r: -r.position)]
    assert orden == nuevos
    assert any(llamada[0] == "edit_role_positions" for llamada in srv.llamadas)
    # nunca se mueven los roles que ya existian (Developer, bot, booster)
    assert all(r.position == antes[r.id] for r in srv.roles if r.id in antes)


async def test_con_el_bot_minimo_el_rol_con_permisos_ajenos_sale_bloqueado(guardado):
    config, srv = cargar(RUTA), FServidor()
    plan, res = await aplicar(srv, config, guardado, admin=False, permisos=MINIMO_BOT)
    a = next(a for a in plan.acciones if a.key == "administrador")
    assert a.op == "bloqueado" and "manage_guild" in a.razon
    assert "Administrador" not in {r.name for r in srv.roles}
    # Lo que depende del rol bloqueado no se crea a medias: una categoria con overrides para
    # un rol que no existe falla entera en vez de quedar mal protegida.
    assert any("cat_staff" in f and "faltan roles" in f for f in res.fallos)
    assert not any(c.name == "🛡️ » STAFF" for c in srv.canales.values())
    assert any(c.name == "💬 » COMUNIDAD" for c in srv.canales.values())       # lo que cabe, si


async def test_un_mensaje_borrado_se_vuelve_a_publicar_y_uno_cambiado_se_edita(guardado):
    config, srv = cargar(RUTA), FServidor()
    await aplicar(srv, config, guardado)
    reglas = por_nombre(srv)["📜・reglas"]
    del reglas.mensajes[guardado["msg_reglas"].discord_id]      # alguien borra el mensaje de las reglas
    plan, _ = await aplicar(srv, config, guardado)
    assert acciones(plan)["msg_reglas"].op == "crear"
    assert len(reglas.mensajes) == 1
    ids_antes = set(reglas.mensajes)
    nuevo = replace(config.mensaje("msg_reglas"), titulo="📜 Reglas (v2)")
    config2 = replace(config, mensajes=tuple(nuevo if m.key == "msg_reglas" else m for m in config.mensajes),
                      _indice={**config._indice, ("mensaje", "msg_reglas"): nuevo})
    plan, _ = await aplicar(srv, config2, guardado)
    assert acciones(plan)["msg_reglas"].op == "actualizar"
    assert set(reglas.mensajes) == ids_antes                     # el mismo mensaje, editado
    assert reglas.mensajes[guardado["msg_reglas"].discord_id].embed.title == "📜 Reglas (v2)"


async def test_un_fallo_por_recurso_no_detiene_el_resto(guardado, monkeypatch):
    config, srv = cargar(RUTA), FServidor()
    original = srv.create_text_channel

    async def falla_en_reglas(nombre, **o):
        if nombre == "📜・reglas":
            raise discord.Forbidden(types.SimpleNamespace(status=403, reason="x"), "sin permiso")
        return await original(nombre, **o)

    monkeypatch.setattr(srv, "create_text_channel", falla_en_reglas)
    plan, res = await aplicar(srv, config, guardado)
    assert any("canal reglas" in f and "sin permisos" in f for f in res.fallos)
    assert any("scripting-luau" in h for h in res.hechos)
    assert any("msg_reglas" in f for f in res.fallos)            # su mensaje no se intenta
    assert "reglas" not in guardado


# --- Comunidad: anuncios y foros la exigen --------------------------------------------------------------
async def test_sin_comunidad_anuncios_y_foro_salen_bloqueados_y_el_resto_se_aplica(guardado):
    config, srv = cargar(RUTA), FServidor(features=())
    plan, res = await aplicar(srv, config, guardado)
    a = acciones(plan)
    for key in ("anuncios", "ayuda"):
        assert a[key].op == "bloqueado" and "activa Comunidad" in a[key].razon
    assert "bloqueado: activa Comunidad" in "\n".join(lineas_plan(plan))
    assert res.fallos == []
    c = por_nombre(srv)
    assert "📣・anuncios" not in c and "❓・ayuda" not in c
    assert "📜・reglas" in c and "💬・general" in c
    # Se activa Comunidad y se repite: ahora si se crean
    srv.features.add("COMMUNITY")
    plan2, res2 = await aplicar(srv, config, guardado)
    assert res2.fallos == []
    c = por_nombre(srv)
    assert c["📣・anuncios"].tipo == "news" and c["❓・ayuda"].tipo == "forum"
    plan3 = plan_de(srv, config, guardado, admin=False, permisos=MINIMO_BOT)
    assert [x for x in plan3.acciones if x.op != "omitir"] == []
    assert orden_actual(srv)[0][:6] == CATEGORIAS_FINAL


# --- Migracion: la version anterior del TOML (v1) -> la nueva ---------------------------------------------------
async def aplicar_v1(guardado):
    """Aplica la version ANTERIOR del TOML tal y como la aplico el codigo de entonces: sin
    reordenar (la accion «orden» es nueva), por eso las categorias quedan al reves."""
    srv = FServidor()
    config = cargar(RUTA_V1)
    plan = plan_de(srv, config, guardado)
    plan.acciones = [a for a in plan.acciones if a.tipo != "orden"]
    res = await ejecutar(srv, plan, config, guardado, lambda keys: object())
    assert res.fallos == []
    return srv


async def test_el_bug_de_orden_se_reproduce_con_v1_y_la_nueva_version_lo_arregla(guardado):
    srv = await aplicar_v1(guardado)
    cats, _ = orden_actual(srv)
    # lo que se vio en PSS: las categorias quedaron al reves (la ultima creada, arriba)
    assert cats[:3] == ["🛡️ Staff", "🔒 Equipo", "🔊 Voz"]
    assert "📌 Estudio" in cats
    config = cargar(RUTA)
    plan = plan_de(srv, config, guardado)
    assert acciones(plan)["@orden"].op == "actualizar"
    await aplicar(srv, config, guardado)
    assert orden_actual(srv)[0][:6] == CATEGORIAS_FINAL


async def test_renombrar_un_recurso_ya_mapeado_lo_edita_y_no_crea_un_duplicado(guardado):
    srv = await aplicar_v1(guardado)
    config = cargar(RUTA)
    ids_antes = {k: guardado[k].discord_id for k in
                 ("cat_estudio", "cat_comunidad", "cat_desarrollo", "cat_voz", "cat_equipo", "cat_staff",
                  "reglas", "anuncios", "showcase", "scripting_luau", "voz_general", "registros",
                  "general", "no_relacionado", "info_importante", "planificacion_sesiones")}
    plan = plan_de(srv, config, guardado)
    a = acciones(plan)
    # el plan EDITA lo ya mapeado (mismo destino_id) y solo crea lo realmente nuevo
    for key, ident in ids_antes.items():
        assert a[key].destino_id == ident, key
        assert a[key].op == ("omitir" if key == "voz_general" else "actualizar"), key   # "🔊 General" no cambia
    assert a["cat_estudio"].cambios["nombre"] == "📌 » IMPORTANTE"
    assert a["reglas"].cambios["nombre"] == "📜・reglas"
    assert {k for k, x in a.items() if x.op == "crear"} == {
        "info_estudio", "sugerencias", "comandos", "ayuda",                        # de la reorganizacion
        "bienvenida", "presentaciones", "niveles", "pruebas_bot", "helper", "novedades",   # de la Fase 1
        "msg_presentaciones"}

    await aplicar(srv, config, guardado)
    # los mismos IDs, con los nombres nuevos
    for key, ident in ids_antes.items():
        assert guardado[key].discord_id == ident, key
    nombres = [c.name for c in srv.canales.values()]
    assert srv.canales[ids_antes["cat_estudio"]].name == "📌 » IMPORTANTE"
    assert srv.canales[ids_antes["reglas"]].name == "📜・reglas"
    assert srv.canales[ids_antes["anuncios"]].tipo == "news" and srv.canales[ids_antes["anuncios"]].name == "📣・anuncios"
    # nada duplicado: ningun nombre normalizado repetido dentro de un mismo tipo
    vistos = [(c.tipo, normalizar(c.name)) for c in srv.canales.values()
              if c.tipo != "voice" and "ayuda" not in c.name]
    assert len(vistos) == len(set(vistos)), nombres
    assert "📌 Estudio" not in nombres and "📜・reglas" in nombres
    plan3 = plan_de(srv, config, guardado, admin=False, permisos=MINIMO_BOT)
    assert [x for x in plan3.acciones if x.op != "omitir"] == []


async def test_los_canales_de_las_categorias_fusionadas_se_mueven_y_las_vacias_se_listan(guardado):
    srv = await aplicar_v1(guardado)
    config = cargar(RUTA)
    plan = plan_de(srv, config, guardado)
    texto = "\n".join(lineas_plan(plan))
    for vieja in ("📢 Anuncios", "🟥 Roblox"):
        assert f"Categoría «{vieja}»: queda **vacía**; bórrala a mano" in texto, vieja
    # las categorias de Discord que ya estaban vacias y no son del perfil no hacen ruido
    assert "Información" not in texto and "Canales de texto" not in texto
    # Soporte conserva solo el #ayuda antiguo, que queda reemplazado por el foro
    assert "Categoría «🛠️ Soporte»: queda **vacía** (solo queda el canal reemplazado" in texto
    assert "«ayuda» queda **reemplazado** por el foro «❓・ayuda»" in texto
    assert "archívalo o bórralo a mano" in texto
    await aplicar(srv, config, guardado)
    c = por_nombre(srv)
    assert c["🛠️ Soporte"].id and [x.name for x in srv.canales.values() if x.category_id == c["🛠️ Soporte"].id] == ["ayuda"]
    assert [x for x in srv.canales.values() if x.category_id == c["📢 Anuncios"].id] == []   # vacia, NO borrada
    assert [x for x in srv.canales.values() if x.category_id == c["🟥 Roblox"].id] == []
    assert c["ayuda"].tipo == "text" and c["ayuda"].id == 22                                  # el viejo, sin tocar
    assert c["❓・ayuda"].tipo == "forum" and c["❓・ayuda"].id != 22
    # tras aplicar, el plan sigue listando lo manual (el bot no lo hace)
    texto2 = "\n".join(lineas_plan(plan_de(srv, config, guardado)))
    assert "reemplazado" in texto2 and "📢 Anuncios" in texto2


async def test_los_mensajes_que_cambian_de_canal_se_republican_y_se_borra_el_antiguo_del_bot(guardado):
    srv = await aplicar_v1(guardado)
    config = cargar(RUTA)
    reglas = srv.canales[guardado["reglas"].discord_id]
    antiguos = {k: guardado[k].discord_id for k in ("msg_info_estudio", "msg_guia", "msg_especialidades", "msg_reglas")}
    assert set(reglas.mensajes) == set(antiguos.values())            # en v1 estaban los 4 en #reglas
    # un mensaje AJENO en #reglas (de un usuario) nunca se toca
    ajeno = FMensaje(reglas, 777, 12345, None, None)
    reglas.mensajes[ajeno.id] = ajeno
    plan = plan_de(srv, config, guardado)
    a = acciones(plan)
    for key in ("msg_info_estudio", "msg_guia", "msg_especialidades"):
        assert a[key].op == "actualizar" and a[key].cambios == {"republicar": True, "borrar_antiguo": True}, key
    assert a["msg_reglas"].op == "actualizar" and not a["msg_reglas"].cambios.get("republicar")   # solo se edita
    _, res = await aplicar(srv, config, guardado)
    assert res.fallos == []
    info = srv.canales[guardado["info_estudio"].discord_id]
    assert [m.embed.title for m in info.mensajes.values()] == [
        "👻 Phantom Shadows Studios", "🧭 Guía para nuevos integrantes", "🎭 Especialidades y avisos"]
    for key in ("msg_info_estudio", "msg_guia", "msg_especialidades"):
        assert antiguos[key] not in reglas.mensajes                     # el antiguo del bot, borrado
        assert guardado[key].canal_id == info.id                        # y mapeado al canal nuevo
    assert antiguos["msg_reglas"] in reglas.mensajes                    # el de reglas se editó, no se borró
    assert reglas.mensajes[antiguos["msg_reglas"]].embed.title == "📜 Reglas"
    assert 777 in reglas.mensajes                                       # el ajeno sigue ahi
    assert any("mensaje antiguo del bot borrado" in h for h in res.hechos)


async def test_no_se_borra_un_mensaje_antiguo_que_no_es_del_bot(guardado):
    srv = await aplicar_v1(guardado)
    config = cargar(RUTA)
    reglas = srv.canales[guardado["reglas"].discord_id]
    id_guia = guardado["msg_guia"].discord_id
    reglas.mensajes[id_guia].author.id = 4242        # el mensaje guardado ya no es del bot
    plan = plan_de(srv, config, guardado)
    assert acciones(plan)["msg_guia"].op == "bloqueado"
    await aplicar(srv, config, guardado)
    assert id_guia in reglas.mensajes                 # intacto


async def test_con_comunidad_apagada_la_migracion_bloquea_solo_lo_que_la_exige(guardado):
    srv = await aplicar_v1(guardado)
    srv.features.clear()
    config = cargar(RUTA)
    plan = plan_de(srv, config, guardado)
    a = acciones(plan)
    assert a["anuncios"].op == "bloqueado" and "activa Comunidad" in a["anuncios"].razon     # no se convierte a news
    assert a["ayuda"].op == "bloqueado"
    texto = "\n".join(lineas_plan(plan))
    assert "reemplazado" not in texto                       # no se pide archivar hasta que exista el foro
    assert "Categoría «📢 Anuncios»" not in texto           # anuncios sigue ahi: no esta vacia
    ident = guardado["anuncios"].discord_id
    await aplicar(srv, config, guardado)
    assert srv.canales[ident].tipo == "text" and srv.canales[ident].name != "📣・anuncios"   # intacto
    srv.features.add("COMMUNITY")
    await aplicar(srv, config, guardado)
    assert srv.canales[ident].tipo == "news" and srv.canales[ident].name == "📣・anuncios"   # convertido, mismo ID
    assert guardado["ayuda"].discord_id != 22 and srv.canales[guardado["ayuda"].discord_id].tipo == "forum"
    plan3 = plan_de(srv, config, guardado, admin=False, permisos=MINIMO_BOT)
    assert [x for x in plan3.acciones if x.op != "omitir"] == []


# --- Orden: pruebas puras -------------------------------------------------------------------------------------
def test_calcular_orden_payload_deja_lo_del_toml_arriba_y_conserva_el_resto():
    canales = [  # (id, tipo, categoria, posicion): categorias invertidas y un canal ajeno
        (1, "categoria", None, 0), (2, "categoria", None, 1), (3, "categoria", None, 2), (9, "categoria", None, 3),
        (10, "text", 3, 0), (11, "text", 3, 1), (12, "text", 2, 2), (13, "text", 9, 3), (14, "voice", 3, 0),
    ]
    payload = calcular_orden_payload(canales, [3, 2, 1], {3: [11, 10], 2: [12]})
    pos = {p["id"]: p["position"] for p in payload}
    assert [i for i in sorted((1, 2, 3, 9), key=pos.get)] == [3, 2, 1, 9]       # las del TOML primero; la ajena, al final
    assert pos[11] < pos[10] < pos[12] < pos[13]                              # el orden del TOML, luego lo demas
    assert {p["id"] for p in payload} == {1, 2, 3, 9, 10, 11, 12, 13, 14}      # cada canal una vez


def test_orden_ya_correcto_solo_mira_lo_que_menciona_el_toml():
    canales = [(1, "categoria", None, 0), (2, "categoria", None, 5), (10, "text", 1, 0), (11, "text", 1, 3), (99, "text", 1, 1)]
    assert orden_ya_correcto(canales, [1, 2], {1: [10, 11]}) is True           # el 99 no es del TOML: no importa
    assert orden_ya_correcto(canales, [2, 1], {1: [10, 11]}) is False
    assert orden_ya_correcto(canales, [1, 2], {1: [11, 10]}) is False


# --- Clases reales de discord.py ------------------------------------------------------------------------------------
def test_construir_snapshot_lee_roles_canales_y_overwrites_reales():
    from discord.abc import _Overwrites
    from discord.channel import CategoryChannel, ForumChannel, TextChannel, VoiceChannel

    from profiles.pss_exec import construir_snapshot

    class Rol:
        def __init__(self, id, name, pos, perm=0, managed=False):
            self.id, self.name, self.position, self.managed = id, name, pos, managed
            self.permissions, self.colour = discord.Permissions(perm), discord.Colour(0x112233)
            self.hoist = self.mentionable = False

    class Guild:
        id, owner_id = 1, 2

        def __init__(self):
            self.bot_rol = Rol(5, "bot", 3, 8)
            self.roles = [Rol(1, "@everyone", 0), self.bot_rol, Rol(6, "dev", 1, 8)]
            self.me = types.SimpleNamespace(id=9, guild_permissions=discord.Permissions(administrator=True),
                                            top_role=self.bot_rol)
            self.channels, self.members = [], []
            self.features = ["COMMUNITY", "NEWS"]

        def get_role(self, i):
            return next((r for r in self.roles if r.id == i), None)

        def get_member(self, i):
            return None

    g = Guild()

    def canal(cls, id, name, ows=(), tipo=None, **kw):
        c = object.__new__(cls)
        c.id, c.name, c.guild = id, name, g
        c._overwrites = [_Overwrites({"id": i, "type": t, "allow": a, "deny": d}) for i, t, a, d in ows]
        if tipo is not None:
            c._type = tipo
        for k, v in kw.items():
            setattr(c, k, v)
        return c

    cat = canal(CategoryChannel, 10, "Cat", [(1, 0, 0, 1024), (9, 1, 1024, 0)], position=4)
    cat.category_id = None
    g.channels = [cat,
                  canal(TextChannel, 11, "general", tipo=0, category_id=10, topic="x", slowmode_delay=3, position=1),
                  canal(TextChannel, 12, "anuncios", tipo=5, category_id=10, topic=None, slowmode_delay=0, position=2),
                  canal(ForumChannel, 13, "ayuda", tipo=15, category_id=10, topic="foro", slowmode_delay=0, position=3),
                  canal(VoiceChannel, 14, "Voz", category_id=10, user_limit=4, position=0)]
    s = construir_snapshot(g)
    por_id = {c.id: c for c in s.canales}
    assert por_id[10].tipo == "categoria" and por_id[10].overwrites == {1: (0, 1024), 9: (1024, 0)}
    assert por_id[10].position == 4 and por_id[10].category_id is None
    assert (por_id[11].tipo, por_id[11].category_id, por_id[11].topic, por_id[11].slowmode) == ("text", 10, "x", 3)
    assert por_id[12].tipo == "news" and por_id[13].tipo == "forum" and por_id[13].topic == "foro"
    assert (por_id[14].tipo, por_id[14].user_limit) == ("voice", 4)
    assert s.bot_admin and s.bot_top == (3, 5) and s.bot_id == 9 and s.owner_id == 2
    assert s.features == frozenset({"COMMUNITY", "NEWS"})
    assert {r.id: r.colour for r in s.roles}[6] == 0x112233


async def test_reunir_estado_de_mensajes():
    from profiles.pss_exec import reunir_estado_mensajes

    config = cargar(RUTA)
    srv = FServidor()
    canal = srv.canales[20]
    propio = await canal.send(embed=None)
    ajeno = FMensaje(canal, 77, 12345, None, None)
    canal.mensajes[ajeno.id] = ajeno
    estado = {"msg_info_estudio": Registro("mensaje", propio.id, 20),
              "msg_reglas": Registro("mensaje", ajeno.id, 20),
              "msg_guia": Registro("mensaje", 999, 20),                  # borrado
              "msg_especialidades": Registro("mensaje", 1, 404)}        # el canal ya no existe
    assert await reunir_estado_mensajes(srv, config, estado) == {
        "msg_info_estudio": "existe", "msg_reglas": "ajeno", "msg_guia": "falta", "msg_especialidades": "falta"}


async def test_borrar_mensaje_antiguo_solo_si_es_del_bot_y_esta_mapeado():
    from profiles.pss_exec import _borrar_mensaje_antiguo

    srv = FServidor()
    canal = srv.canales[21]
    propio = await canal.send(embed=None)
    ajeno = FMensaje(canal, 777, 12345, None, None)
    canal.mensajes[ajeno.id] = ajeno
    # el del bot, mapeado: se borra
    assert "borrado" in await _borrar_mensaje_antiguo(srv, Registro("mensaje", propio.id, canal.id))
    assert propio.id not in canal.mensajes
    # uno que no es del bot: NO se borra aunque este mapeado
    assert "no es del bot" in await _borrar_mensaje_antiguo(srv, Registro("mensaje", ajeno.id, canal.id))
    assert ajeno.id in canal.mensajes
    # ya no existe / el canal ya no existe: no falla
    assert "ya no existía" in await _borrar_mensaje_antiguo(srv, Registro("mensaje", 123456, canal.id))
    assert "ya no existe" in await _borrar_mensaje_antiguo(srv, Registro("mensaje", 1, 99999))
