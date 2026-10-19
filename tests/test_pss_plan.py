"""Calculo del plan del perfil PSS con una foto del servidor hecha a mano (sin Discord)."""

import copy
from dataclasses import replace

import pytest

from profiles.pss_config import parsear
from profiles.pss_plan import (
    MAX_ROLES, Registro, SCanal, SMiembro, SRol, Snapshot, bits, calcular_plan,
    hash_contenido, lineas_plan, normalizar, renderizar, ORDEN_DESPLIEGUE,
)

G, BOT, DUENO = 100, 900, 777
MINIMO_BOT = 1099780189270   # entero minimo de permisos acordado para el bot


def config(**cambios):
    d = {
        "perfil": {"guild_id": G, "owner_id": DUENO},
        "roles": [
            {"key": "dev", "nombre": "Developer", "existing_id": 50},
            {"key": "colab", "nombre": "Colaborador", "permisos": ["send_messages"]},
        ],
        "categorias": [
            {"key": "cat_priv", "nombre": "Privada", "orden": 1,
             "overrides": [{"objetivo": "@everyone", "denegar": ["view_channel"]},
                           {"objetivo": "colab", "permitir": ["view_channel"]}]},
            {"key": "cat_pub", "nombre": "Publica", "orden": 2},
        ],
        "canales": [
            {"key": "general", "nombre": "general", "categoria": "cat_pub"},
            {"key": "front", "nombre": "frontend", "categoria": "cat_priv"},
        ],
        "mensajes": [{"key": "msg", "canal": "general", "titulo": "Hola {canal:front}"}],
    }
    d.update(cambios)
    return parsear(d)


def snap(roles=(), canales=(), admin=True, permisos=0, miembros=(), top=(10, 1)):
    return Snapshot(
        guild_id=G, owner_id=DUENO, bot_id=BOT, bot_permisos=permisos, bot_admin=admin,
        bot_top=top, roles=[SRol(G, "@everyone", 0), *roles], canales=list(canales),
        miembros=list(miembros),
    )


def accion(plan, key):
    return next(a for a in plan.acciones if a.key == key)


def ops(plan):
    return {a.key: a.op for a in plan.acciones}


# --- resolucion ---------------------------------------------------------------------------
def test_normalizar_quita_emoji_acentos_y_separadores():
    assert normalizar("📂 Proyectos") == "proyectos"
    assert normalizar("planificación-de-sesiones") == normalizar("Planificación de sesiones")
    assert normalizar("🔊 Reuniones") == "reuniones"


def test_resolucion_id_guardado_luego_existing_id_luego_nombre():
    c = config(canales=[
        {"key": "general", "nombre": "general", "categoria": "cat_pub", "existing_id": 21},
        {"key": "front", "nombre": "frontend", "categoria": "cat_priv"}])
    canales = [SCanal(21, "otro", "text"), SCanal(22, "x", "text"), SCanal(23, "general", "text")]
    # 1) ID guardado
    plan = calcular_plan(c, snap(canales=canales), {"general": Registro("canal", 22)}, {})
    assert (accion(plan, "general").destino_id, accion(plan, "general").via) == (22, "guardado")
    # 2) existing_id
    plan = calcular_plan(c, snap(canales=canales), {}, {})
    assert (accion(plan, "general").destino_id, accion(plan, "general").via) == (21, "existing_id")
    # 3) nombre normalizado (si no hay existing_id)
    c2 = config()
    plan = calcular_plan(c2, snap(canales=canales), {}, {})
    assert (accion(plan, "general").destino_id, accion(plan, "general").via) == (23, "nombre")


def test_id_guardado_que_ya_no_existe_cae_al_siguiente_criterio():
    plan = calcular_plan(config(), snap(canales=[SCanal(23, "general", "text")]),
                         {"general": Registro("canal", 999)}, {})
    assert accion(plan, "general").destino_id == 23


def test_nombre_ambiguo_se_bloquea_sin_crear_duplicados():
    plan = calcular_plan(config(), snap(canales=[SCanal(1, "general", "text"), SCanal(2, "General", "text")]), {}, {})
    a = accion(plan, "general")
    assert a.op == "bloqueado" and "varios" in a.razon and "existing_id" in a.razon


def test_dos_keys_no_se_enlazan_al_mismo_objeto():
    c = config(canales=[
        {"key": "a", "nombre": "general", "categoria": "cat_pub"},
        {"key": "b", "nombre": "general", "categoria": "cat_pub"}], mensajes=[])
    plan = calcular_plan(c, snap(canales=[SCanal(1, "general", "text")]), {}, {})
    assert {accion(plan, "a").op, accion(plan, "b").op} == {"vincular", "crear"}


def test_roles_administrados_no_se_enlazan_por_nombre():
    plan = calcular_plan(config(), snap(roles=[SRol(5, "Colaborador", 1, managed=True)]), {}, {})
    assert accion(plan, "colab").op == "crear"


# --- no destructivo ------------------------------------------------------------------------
def test_canal_existente_sin_mover_ni_adoptar_no_se_toca():
    c = config(canales=[{"key": "general", "nombre": "general", "categoria": "cat_pub",
                         "tema": "otro tema", "slowmode": 5}], mensajes=[])
    existente = SCanal(21, "general", "text", 11, topic="tema original", slowmode=0)
    plan = calcular_plan(c, snap(canales=[existente, SCanal(11, "Vieja", "categoria")]), {}, {})
    assert accion(plan, "general").op == "vincular"       # solo se guarda el mapeo
    assert accion(plan, "general").cambios == {}


def test_adoptar_actualiza_tema_y_sin_adoptar_no():
    base = {"key": "general", "nombre": "general", "categoria": "cat_pub", "tema": "nuevo"}
    existente = SCanal(21, "general", "text", None, topic="viejo")
    sin = calcular_plan(config(canales=[base], mensajes=[]), snap(canales=[existente]), {}, {})
    con = calcular_plan(config(canales=[{**base, "adoptar": True}], mensajes=[]), snap(canales=[existente]), {}, {})
    assert accion(sin, "general").op == "vincular"
    assert accion(con, "general").op == "actualizar" and accion(con, "general").cambios == {"tema": "nuevo"}


def test_mover_y_sincronizar_son_explicitos():
    existente = SCanal(21, "frontend", "text", 11)
    canales = [existente, SCanal(11, "Canales de texto", "categoria")]
    c = config(canales=[{"key": "front", "nombre": "frontend", "categoria": "cat_priv", "mover": True,
                         "sincronizar_permisos": True}], mensajes=[])
    plan = calcular_plan(c, snap(canales=canales), {}, {})
    a = accion(plan, "front")
    assert a.op == "actualizar" and a.cambios == {"mover": "cat_priv", "sincronizar": True}
    # sin mover: se queda donde esta
    c = config(canales=[{"key": "front", "nombre": "frontend", "categoria": "cat_priv"}], mensajes=[])
    assert accion(calcular_plan(c, snap(canales=canales), {}, {}), "front").op == "vincular"


# --- adoptar = «ya existe»: lo que no aparece NO se crea --------------------------------------------
def test_adoptar_con_nombre_actual_que_no_existe_sale_bloqueado_y_no_crea_nada():
    c = config(canales=[{"key": "front", "nombre": "🎨・frontend", "nombre_actual": "frontend", "adoptar": True,
                         "categoria": "cat_pub"}],
               mensajes=[{"key": "msg", "canal": "front", "titulo": "Hola"}])
    plan = calcular_plan(c, snap(canales=[SCanal(21, "otro", "text")]), {}, {})
    a = accion(plan, "front")
    assert a.op == "bloqueado" and a.razon.startswith("no encontrado (adoptar)")
    assert "bloqueado: no encontrado (adoptar)" in "\n".join(lineas_plan(plan))
    assert not [x for x in plan.acciones if x.tipo == "canal" and x.op == "crear"]      # nada que crear
    assert accion(plan, "msg").op == "bloqueado"                                          # y su mensaje espera
    # tampoco por existing_id: un ID que no esta en el servidor
    c = config(canales=[{"key": "front", "nombre": "frontend", "adoptar": True, "existing_id": 999,
                         "categoria": "cat_pub"}], mensajes=[])
    assert accion(calcular_plan(c, snap(), {}, {}), "front").op == "bloqueado"


def test_adoptar_que_no_existe_bloquea_tambien_roles_y_categorias_y_arrastra_a_sus_canales():
    c = config(roles=[{"key": "fantasma", "nombre": "Fantasma", "adoptar": True}],
               categorias=[{"key": "cat_vieja", "nombre": "Vieja", "orden": 1, "adoptar": True}],
               canales=[{"key": "dentro", "nombre": "dentro", "categoria": "cat_vieja"}], mensajes=[])
    plan = calcular_plan(c, snap(), {}, {})
    assert ops(plan)["fantasma"] == "bloqueado" and accion(plan, "fantasma").razon.startswith("no encontrado (adoptar)")
    assert ops(plan)["cat_vieja"] == "bloqueado"
    assert ops(plan)["dentro"] == "bloqueado" and "depende de la categoría" in accion(plan, "dentro").razon


def test_lo_que_no_es_adoptar_o_lo_creo_el_bot_si_se_crea_aunque_falte():
    # sin adoptar: se crea (el caso normal)
    c = config(canales=[{"key": "nuevo", "nombre": "nuevo", "categoria": "cat_pub"}], mensajes=[])
    assert ops(calcular_plan(c, snap(), {}, {}))["nuevo"] == "crear"
    # con adoptar pero creado antes por el bot (alguien lo borro a mano): se vuelve a crear
    c = config(canales=[{"key": "nuevo", "nombre": "nuevo", "adoptar": True, "categoria": "cat_pub"}], mensajes=[])
    estado = {"nuevo": Registro("canal", 321, creado=True)}
    assert ops(calcular_plan(c, snap(), estado, {}))["nuevo"] == "crear"
    # con adoptar y presente (por nombre): se vincula como siempre
    plan = calcular_plan(c, snap(canales=[SCanal(21, "nuevo", "text")]), {}, {})
    assert ops(plan)["nuevo"] in ("vincular", "actualizar")


def test_canal_ya_movido_y_sincronizado_da_omitir():
    cat = SCanal(30, "Privada", "categoria", overwrites={G: (0, 1024)})
    canal = SCanal(21, "frontend", "text", 30, overwrites={G: (0, 1024)})
    c = config(canales=[{"key": "front", "nombre": "frontend", "categoria": "cat_priv", "mover": True,
                         "sincronizar_permisos": True}], mensajes=[])
    estado = {"front": Registro("canal", 21), "cat_priv": Registro("categoria", 30, creado=True),
              "dev": Registro("rol", 50), "colab": Registro("rol", 60, creado=True)}
    roles = [SRol(50, "Developer", 1, 8), SRol(60, "Colaborador", 1, bits(["send_messages"]))]
    # la categoria deberia tener tambien el override de colab: se actualizara, pero el canal no
    plan = calcular_plan(c, snap(roles=roles, canales=[cat, canal]), estado, {})
    assert accion(plan, "front").op == "omitir"


def test_developer_se_reutiliza_sin_cambios_aunque_tenga_administrator():
    roles = [SRol(50, "Developer", 1, bits(["administrator"]))]
    plan = calcular_plan(config(), snap(roles=roles), {}, {})
    assert accion(plan, "dev").op == "vincular"
    plan2 = calcular_plan(config(), snap(roles=roles), {"dev": Registro("rol", 50)}, {})
    assert accion(plan2, "dev").op == "omitir" and accion(plan2, "dev").cambios == {}
    assert any("administrator" in a for a in plan2.advertencias)


# --- permisos y jerarquia ----------------------------------------------------------------------
def test_bloqueado_si_el_bot_no_tiene_un_permiso_del_rol():
    c = config(roles=[{"key": "adm", "nombre": "Administrador", "permisos": ["manage_guild", "kick_members"]}],
               categorias=[], canales=[], mensajes=[])
    plan = calcular_plan(c, snap(admin=False, permisos=MINIMO_BOT), {}, {})
    a = accion(plan, "adm")
    assert a.op == "bloqueado" and a.razon == "el bot no tiene manage_guild"
    assert "bloqueado: el bot no tiene manage_guild" in "\n".join(lineas_plan(plan))
    # con administrator se puede
    assert accion(calcular_plan(c, snap(admin=True), {}, {}), "adm").op == "crear"


def test_bloqueado_si_el_bot_no_tiene_manage_roles_o_manage_channels():
    plan = calcular_plan(config(), snap(admin=False, permisos=0), {}, {})
    assert accion(plan, "colab").razon.startswith("el bot no tiene manage_roles")
    assert "manage_channels" in accion(plan, "cat_pub").razon


def test_no_se_actualiza_un_rol_por_encima_del_bot():
    alto = SRol(60, "Colaborador", 99, 0)
    c = config(roles=[{"key": "colab", "nombre": "Colaborador", "adoptar": True, "permisos": ["send_messages"]}],
               categorias=[], canales=[], mensajes=[])
    plan = calcular_plan(c, snap(roles=[alto], top=(10, 1)), {}, {})
    assert accion(plan, "colab").op == "bloqueado" and "jerarquía" in accion(plan, "colab").razon


def test_empate_de_posicion_lo_decide_el_id_como_en_discord():
    bot_top = (1, 5)
    s = snap(roles=[SRol(60, "bajo", 1), SRol(3, "alto", 1)], top=bot_top)
    assert s.rol_bajo_el_bot(SRol(60, "bajo", 1)) is True    # mismo puesto, ID mayor = mas bajo
    assert s.rol_bajo_el_bot(SRol(3, "alto", 1)) is False


def test_rol_propio_se_mantiene_al_dia_y_si_el_bot_ya_no_tiene_permisos_no_hay_bloqueo_sin_cambios():
    c = config(roles=[{"key": "colab", "nombre": "Colaborador", "permisos": ["send_messages"]}],
               categorias=[], canales=[], mensajes=[])
    rol = SRol(60, "Colaborador", 1, bits(["send_messages"]))
    plan = calcular_plan(c, snap(roles=[rol], admin=False, permisos=MINIMO_BOT),
                         {"colab": Registro("rol", 60, creado=True)}, {})
    assert accion(plan, "colab").op == "omitir"          # sin diferencias no hace falta ningun permiso
    deriva = SRol(60, "Colaborador", 1, 0)
    plan = calcular_plan(c, snap(roles=[deriva], admin=False, permisos=MINIMO_BOT),
                         {"colab": Registro("rol", 60, creado=True)}, {})
    assert accion(plan, "colab").op == "actualizar" and "permisos" in accion(plan, "colab").cambios


def test_limites_de_roles_y_de_canales_por_categoria():
    muchos = [SRol(1000 + i, f"r{i}", 1) for i in range(MAX_ROLES - 1)]   # + @everyone = 250
    plan = calcular_plan(config(), snap(roles=muchos), {}, {})
    assert accion(plan, "colab").op == "bloqueado" and "250" in accion(plan, "colab").razon
    llenos = [SCanal(2000 + i, f"c{i}", "text", 30) for i in range(50)]
    cat = SCanal(30, "Publica", "categoria")
    plan = calcular_plan(config(), snap(canales=[cat, *llenos]), {"cat_pub": Registro("categoria", 30)}, {})
    assert accion(plan, "general").op == "bloqueado" and "50" in accion(plan, "general").razon


def test_si_la_categoria_esta_bloqueada_sus_canales_tambien():
    plan = calcular_plan(config(), snap(admin=False, permisos=bits(["manage_roles"])), {}, {})
    assert accion(plan, "cat_pub").op == "bloqueado"
    assert accion(plan, "general").op == "bloqueado" and "depende" in accion(plan, "general").razon


def test_el_bot_recibe_un_override_en_lo_privado():
    plan = calcular_plan(config(), snap(), {}, {})
    from profiles.pss_plan import overwrites_deseados
    from profiles.pss_config import Override
    deseados, _ = overwrites_deseados((Override("@everyone", (), ("view_channel",)),), {}, G, BOT)
    assert BOT in deseados and deseados[BOT][0] & bits(["view_channel", "send_messages"])
    deseados, _ = overwrites_deseados((Override("@everyone", ("view_channel",), ()),), {}, G, BOT)
    assert BOT not in deseados
    assert plan  # el plan completo se calcula


# --- advertencias ---------------------------------------------------------------------------------
def test_aviso_de_miembros_que_pierden_acceso_al_sincronizar():
    canal = SCanal(21, "frontend", "text", 11)
    c = config(canales=[{"key": "front", "nombre": "frontend", "categoria": "cat_priv", "mover": True,
                         "sincronizar_permisos": True}], mensajes=[],
               categorias=[{"key": "cat_priv", "nombre": "Privada", "orden": 1,
                            "overrides": [{"objetivo": "@everyone", "denegar": ["view_channel"]},
                                          {"objetivo": "dev", "permitir": ["view_channel"]}]}])
    miembros = [SMiembro(1, frozenset({50})), SMiembro(2, frozenset()), SMiembro(DUENO, frozenset()),
                SMiembro(3, frozenset(), bot=True)]
    plan = calcular_plan(c, snap(roles=[SRol(50, "Developer", 1)], canales=[canal], miembros=miembros), {}, {})
    aviso = next(a for a in plan.advertencias if "frontend" in a)
    assert "1 miembro(s)" in aviso and "<@2>" in aviso and "<@1>" not in aviso


def test_aviso_de_roles_nuevos_bajo_el_bot_menciona_propietario():
    c = config(roles=[{"key": "propietario", "nombre": "Propietario", "hoist": True}],
               categorias=[], canales=[], mensajes=[])
    plan = calcular_plan(c, snap(), {}, {})
    assert any("arrástralo a mano" in a and "Propietario" in a for a in plan.advertencias)


def test_el_reporte_incluye_el_orden_de_despliegue():
    for paso in ("a)", "b)", "c)", "d)"):
        assert paso in ORDEN_DESPLIEGUE
    assert "1099780189270" in ORDEN_DESPLIEGUE and "omitir" in ORDEN_DESPLIEGUE


# --- mensajes -------------------------------------------------------------------------------------------
def estado_con_todo(extra=None):
    e = {"dev": Registro("rol", 50), "colab": Registro("rol", 60, creado=True),
         "cat_priv": Registro("categoria", 30, creado=True), "cat_pub": Registro("categoria", 31, creado=True),
         "general": Registro("canal", 21, creado=True), "front": Registro("canal", 22, creado=True)}
    e.update(extra or {})
    return e


def foto_completa(**kw):
    ow_priv = {G: (0, bits(["view_channel"])), 60: (bits(["view_channel"]), 0), BOT: (bits(["view_channel", "send_messages", "embed_links", "read_message_history", "attach_files"]), 0)}
    canales = [SCanal(30, "Privada", "categoria", overwrites=ow_priv), SCanal(31, "Publica", "categoria"),
               SCanal(21, "general", "text", 31), SCanal(22, "frontend", "text", 30, overwrites=ow_priv)]
    roles = [SRol(50, "Developer", 1, 8), SRol(60, "Colaborador", 1, bits(["send_messages"]))]
    return snap(roles=roles, canales=canales, **kw)


def hash_msg(c, ids):
    return hash_contenido(renderizar(c.mensaje("msg"), ids))


def test_mensaje_nuevo_se_publica_y_el_hash_es_del_embed_renderizado():
    c = config()
    ids = {"general": 21, "front": 22}
    plan = calcular_plan(c, foto_completa(), estado_con_todo(), {})
    assert accion(plan, "msg").op == "crear"
    rend = renderizar(c.mensaje("msg"), ids)
    assert rend["embed"]["title"] == "Hola <#22>"            # menciones ya resueltas
    assert hash_contenido(rend) != hash_contenido(renderizar(c.mensaje("msg"), {"general": 21, "front": 23}))
    assert hash_contenido(rend) == hash_contenido(renderizar(c.mensaje("msg"), dict(ids)))


def test_mensaje_igual_se_omite_distinto_se_edita_borrado_se_republica():
    c = config()
    h = hash_msg(c, {"general": 21, "front": 22})
    reg = Registro("mensaje", 500, canal_id=21, hash=h, creado=True)
    estado = estado_con_todo({"msg": reg})
    assert accion(calcular_plan(c, foto_completa(), estado, {"msg": "existe"}), "msg").op == "omitir"
    cambiado = estado_con_todo({"msg": Registro("mensaje", 500, canal_id=21, hash="otro")})
    a = accion(calcular_plan(c, foto_completa(), cambiado, {"msg": "existe"}), "msg")
    assert a.op == "actualizar" and a.cambios == {"republicar": False}
    a = accion(calcular_plan(c, foto_completa(), estado, {"msg": "falta"}), "msg")
    assert a.op == "crear" and "vuelve a publicar" in a.razon
    movido = estado_con_todo({"msg": Registro("mensaje", 500, canal_id=99, hash=h)})
    a = accion(calcular_plan(c, foto_completa(), movido, {"msg": "existe"}), "msg")
    assert a.op == "actualizar" and a.cambios == {"republicar": True, "borrar_antiguo": True}
    assert "se borra el antiguo" in a.razon


def test_mensaje_ajeno_o_ilegible_nunca_se_toca():
    c = config()
    estado = estado_con_todo({"msg": Registro("mensaje", 500, canal_id=21, hash="x")})
    assert accion(calcular_plan(c, foto_completa(), estado, {"msg": "ajeno"}), "msg").op == "bloqueado"
    assert accion(calcular_plan(c, foto_completa(), estado, {"msg": "error"}), "msg").op == "bloqueado"


def test_mensaje_con_publicar_false_se_omite():
    c = config(mensajes=[{"key": "msg", "canal": "general", "titulo": "TODO", "publicar": False}])
    assert accion(calcular_plan(c, foto_completa(), estado_con_todo(), {}), "msg").op == "omitir"


def test_mensaje_pendiente_si_menciona_algo_que_aun_no_existe():
    plan = calcular_plan(config(), snap(), {}, {})
    a = accion(plan, "msg")
    assert a.op == "crear" and "pendiente" in a.razon


def test_mensaje_bloqueado_si_el_bot_no_puede_escribir():
    plan = calcular_plan(config(), foto_completa(admin=False, permisos=0), estado_con_todo(), {})
    assert accion(plan, "msg").op == "bloqueado"


# --- huella -------------------------------------------------------------------------------------------------
def test_la_huella_cambia_si_cambia_el_plan():
    a = calcular_plan(config(), snap(), {}, {})
    b = calcular_plan(config(), snap(), {}, {})
    c = calcular_plan(config(), snap(roles=[SRol(70, "Colaborador", 1)]), {}, {})
    assert a.huella() == b.huella() != c.huella()


# --- renombrar un canal existente (adoptar + nombre_actual) ---------------------------------------------
def config_ayuda():
    return config(canales=[{"key": "ayuda", "nombre": "ayuda", "nombre_actual": "deberes-ayuda",
                            "categoria": "cat_pub", "adoptar": True}], mensajes=[])


def test_se_encuentra_por_nombre_actual_y_se_renombra():
    plan = calcular_plan(config_ayuda(), snap(canales=[SCanal(22, "deberes-ayuda", "text", None)]), {}, {})
    a = accion(plan, "ayuda")
    assert (a.op, a.destino_id, a.via, a.cambios) == ("actualizar", 22, "nombre", {"nombre": "ayuda"})
    assert "renombrar a «ayuda»" in "\n".join(lineas_plan(plan))


def test_tras_renombrar_el_id_guardado_lo_mantiene_en_omitir():
    estado = {"ayuda": Registro("canal", 22)}
    plan = calcular_plan(config_ayuda(), snap(canales=[SCanal(22, "ayuda", "text", None)]), estado, {})
    assert accion(plan, "ayuda").op == "omitir"


def test_si_ya_se_llama_ayuda_se_encuentra_por_el_nombre_nuevo_sin_duplicar():
    plan = calcular_plan(config_ayuda(), snap(canales=[SCanal(22, "ayuda", "text", None)]), {}, {})
    assert (accion(plan, "ayuda").op, accion(plan, "ayuda").destino_id) == ("vincular", 22)


def test_si_existen_los_dos_nombres_queda_bloqueado_en_vez_de_adivinar():
    canales = [SCanal(22, "deberes-ayuda", "text", None), SCanal(23, "ayuda", "text", None)]
    a = accion(calcular_plan(config_ayuda(), snap(canales=canales), {}, {}), "ayuda")
    assert a.op == "bloqueado" and "varios" in a.razon


def test_sin_adoptar_nunca_se_renombra_un_canal_existente():
    c = config(canales=[{"key": "ayuda", "nombre": "ayuda", "categoria": "cat_pub"}], mensajes=[])
    plan = calcular_plan(c, snap(canales=[SCanal(22, "deberes-ayuda", "text", None)]), {}, {})
    assert accion(plan, "ayuda").op == "crear"        # sin alias no lo reconoce y crea el nuevo


# --- anuncios (news) y foros: exigen Comunidad ------------------------------------------------------------
def config_tipos():
    return config(canales=[
        {"key": "avisos", "nombre": "avisos", "tipo": "news", "categoria": "cat_pub"},
        {"key": "foro", "nombre": "foro", "tipo": "forum", "categoria": "cat_pub", "reemplaza": "ayuda"},
    ], mensajes=[])


def test_crear_news_y_foro_sin_comunidad_sale_bloqueado():
    plan = calcular_plan(config_tipos(), snap(), {}, {})
    for key in ("avisos", "foro"):
        assert accion(plan, key).op == "bloqueado" and accion(plan, key).razon.startswith("activa Comunidad")
    assert "bloqueado: activa Comunidad" in "\n".join(lineas_plan(plan))
    con = calcular_plan(config_tipos(), snap_comunidad(), {}, {})
    assert accion(con, "avisos").op == "crear" and accion(con, "foro").op == "crear"
    assert "anuncios" in accion(con, "avisos").detalle and "foro" in accion(con, "foro").detalle


def snap_comunidad(**kw):
    s = snap(**kw)
    s.features = frozenset({"COMMUNITY"})
    return s


def test_un_texto_existente_se_convierte_en_news_solo_si_es_del_bot_o_adoptado_y_hay_comunidad():
    c = config(canales=[{"key": "avisos", "nombre": "avisos", "tipo": "news", "categoria": "cat_pub"}], mensajes=[])
    existente = SCanal(40, "avisos", "text", None)
    estado = {"avisos": Registro("canal", 40, creado=True)}
    # creado por el bot + Comunidad: se convierte (mismo ID, sin crear otro)
    a = accion(calcular_plan(c, snap_comunidad(canales=[existente]), estado, {}), "avisos")
    assert (a.op, a.destino_id, a.cambios) == ("actualizar", 40, {"tipo": "news"})
    assert "convertir a canal de anuncios" in a.detalle
    # sin Comunidad: bloqueado
    a = accion(calcular_plan(c, snap(canales=[existente]), estado, {}), "avisos")
    assert a.op == "bloqueado" and "activa Comunidad" in a.razon
    # un existente ajeno al bot y sin adoptar: no se toca
    a = accion(calcular_plan(c, snap_comunidad(canales=[existente]), {}, {}), "avisos")
    assert a.op == "vincular" and a.cambios == {}
    # ya es news: nada que hacer
    ya = SCanal(40, "avisos", "news", None)
    assert accion(calcular_plan(c, snap_comunidad(canales=[ya]), estado, {}), "avisos").op == "omitir"


def test_un_canal_de_texto_no_se_convierte_en_foro_se_crea_uno_nuevo_y_el_viejo_se_lista():
    texto_viejo = SCanal(22, "ayuda", "text", None)
    plan = calcular_plan(config_tipos(), snap_comunidad(canales=[texto_viejo]), {}, {})
    a = accion(plan, "foro")
    assert a.op == "crear" and a.destino_id is None                   # foro nuevo, el de texto no es candidato
    assert any("«ayuda» queda **reemplazado** por el foro «foro»" in m and "a mano" in m for m in plan.manuales)
    assert "🧹 A mano" in "\n".join(lineas_plan(plan))
    # un foro que ya existe se reutiliza (y el de texto sigue listado hasta que lo borres)
    foro = SCanal(23, "foro", "forum", None)
    plan = calcular_plan(config_tipos(), snap_comunidad(canales=[texto_viejo, foro]), {}, {})
    assert accion(plan, "foro").op == "vincular" and accion(plan, "foro").destino_id == 23
    assert plan.manuales
    # si el foro esta bloqueado (sin Comunidad) todavia no se pide archivar nada
    plan = calcular_plan(config_tipos(), snap(canales=[texto_viejo]), {}, {})
    assert plan.manuales == []


def test_las_categorias_que_quedan_vacias_se_listan_pero_no_se_borran():
    vieja = SCanal(50, "Vieja", "categoria")
    canal = SCanal(51, "general", "text", 50)
    c = config(canales=[{"key": "general", "nombre": "general", "categoria": "cat_pub", "mover": True}], mensajes=[])
    # mapeada por el perfil y que se vacia al mover su canal
    plan = calcular_plan(c, snap(canales=[vieja, canal]), {"cat_vieja": Registro("categoria", 50, creado=True)}, {})
    assert any("Categoría «Vieja»: queda **vacía**" in m and "bórrala a mano" in m for m in plan.manuales)
    # una categoria vacia ajena al perfil no hace ruido
    plan = calcular_plan(c, snap(canales=[SCanal(60, "Ajena", "categoria"), canal]), {}, {})
    assert not any("Ajena" in m for m in plan.manuales)
    # ninguna accion del plan borra nada
    assert all(a.op in ("crear", "actualizar", "vincular", "omitir", "bloqueado") for a in plan.acciones)


# --- renombrar lo ya mapeado --------------------------------------------------------------------------------
def test_renombrar_un_canal_ya_mapeado_y_creado_por_el_bot_lo_edita_sin_adoptar_ni_duplicar():
    c = config(canales=[{"key": "general", "nombre": "💬・general", "categoria": "cat_pub"}], mensajes=[])
    existente = SCanal(21, "general", "text", None)
    plan = calcular_plan(c, snap(canales=[existente]), {"general": Registro("canal", 21, creado=True)}, {})
    a = accion(plan, "general")
    assert (a.op, a.destino_id, a.cambios) == ("actualizar", 21, {"nombre": "💬・general"})
    assert not [x for x in plan.acciones if x.op == "crear" and x.tipo == "canal"]     # no hay duplicado
    # si NO lo creo yo ni esta adoptado, no se renombra
    plan = calcular_plan(c, snap(canales=[existente]), {"general": Registro("canal", 21, creado=False)}, {})
    assert accion(plan, "general").op == "omitir" and accion(plan, "general").cambios == {}


# --- ordenes y mensajes que cambian de canal -----------------------------------------------------------------------
def test_la_accion_orden_detecta_categorias_en_orden_inverso_y_se_omite_si_ya_esta_bien():
    c = config(canales=[], mensajes=[])
    cats = [SCanal(30, "Privada", "categoria", position=5), SCanal(31, "Publica", "categoria", position=2)]
    estado = {"cat_priv": Registro("categoria", 30, creado=True), "cat_pub": Registro("categoria", 31, creado=True)}
    # orden TOML: cat_priv (orden 1) antes que cat_pub (orden 2); aqui estan al reves
    plan = calcular_plan(c, snap(canales=cats), estado, {})
    assert accion(plan, "@orden").op == "actualizar" and "no coincide" in accion(plan, "@orden").razon
    ok = [SCanal(30, "Privada", "categoria", position=1), SCanal(31, "Publica", "categoria", position=2)]
    assert accion(calcular_plan(c, snap(canales=ok), estado, {}), "@orden").op == "omitir"


def test_crear_o_mover_recursos_siempre_pide_reordenar():
    plan = calcular_plan(config(), snap(), {}, {})
    assert accion(plan, "@orden").op == "actualizar" and "tras crear o mover" in accion(plan, "@orden").razon


def test_mensaje_con_canal_nuevo_que_aun_no_existe_se_republica_y_borra_el_antiguo():
    c = config(mensajes=[{"key": "msg", "canal": "general", "titulo": "Hola"}])
    estado = estado_con_todo({"msg": Registro("mensaje", 500, canal_id=99, hash="x")})
    foto = foto_completa()
    # el canal 'general' existe (21) pero el mensaje esta en otro canal (99): se mueve
    a = accion(calcular_plan(c, foto, estado, {"msg": "existe"}), "msg")
    assert a.op == "actualizar" and a.cambios == {"republicar": True, "borrar_antiguo": True}
    # el canal destino todavia no existe: igual, republicar (el antiguo se borra tras publicar el nuevo)
    c2 = config(canales=[{"key": "general", "nombre": "general", "categoria": "cat_pub"},
                         {"key": "nuevo", "nombre": "nuevo", "categoria": "cat_pub"}],
                mensajes=[{"key": "msg", "canal": "nuevo", "titulo": "Hola"}])
    a = accion(calcular_plan(c2, foto_completa(), estado, {"msg": "existe"}), "msg")
    assert a.op == "actualizar" and a.cambios == {"republicar": True, "borrar_antiguo": True}


def test_un_mensaje_que_menciona_un_recurso_bloqueado_no_se_publica_a_medias():
    cfg = config(canales=[{"key": "avisos", "nombre": "avisos", "categoria": "cat_pub"},
                          {"key": "foro", "nombre": "foro", "tipo": "forum", "categoria": "cat_pub"}],
                 mensajes=[{"key": "msg", "canal": "avisos", "titulo": "Mira {canal:foro}"}])
    a = accion(calcular_plan(cfg, snap(), {}, {}), "msg")                      # sin Comunidad: el foro esta bloqueado
    assert a.op == "bloqueado" and "foro" in a.razon
    assert accion(calcular_plan(cfg, snap_comunidad(), {}, {}), "msg").op == "crear"
