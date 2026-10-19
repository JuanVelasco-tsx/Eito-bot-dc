"""Loader y validador de profiles/pss.toml (sin Discord ni BD)."""

import copy
from pathlib import Path

import pytest

from profiles.pss_config import Boton, ConfigInvalida, DestinoRelease, cargar, parsear

RUTA_REAL = Path(__file__).resolve().parent.parent / "profiles" / "pss.toml"

BASE = {
    "perfil": {"guild_id": 10, "gestores": []},
    "eventos": {"rol_al_entrar": "miembro", "bienvenida": "general", "canal_logs": "logs"},
    "roles": [{"key": "miembro", "nombre": "Miembro", "color": "#2ECC71",
               "permisos": ["send_messages"]}],
    "categorias": [{"key": "cat_a", "nombre": "A", "orden": 1,
                    "overrides": [{"objetivo": "@everyone", "denegar": ["view_channel"]},
                                  {"objetivo": "miembro", "permitir": ["view_channel"]}]}],
    "canales": [{"key": "general", "nombre": "general", "categoria": "cat_a"},
                {"key": "logs", "nombre": "logs", "categoria": "cat_a"}],
    "mensajes": [{"key": "msg", "canal": "general", "titulo": "Hola {canal:logs}"}],
}


def datos(**cambios):
    d = copy.deepcopy(BASE)
    d.update(cambios)
    return d


def errores_de(d):
    with pytest.raises(ConfigInvalida) as e:
        parsear(d)
    return e.value.errores


def alguno(errores, *trozos):
    return any(all(t in e for t in trozos) for e in errores)


def test_la_base_es_valida():
    c = parsear(BASE)
    assert c.guild_id == 10 and c.rol("miembro").color == 0x2ECC71
    assert c.canal("general").categoria == "cat_a"


def test_el_toml_real_es_valido_y_refleja_lo_acordado():
    c = cargar(RUTA_REAL)
    assert c.guild_id == 1420403964746268684 and c.owner_id == 668148837579227137
    assert c.gestores == ()
    # PSS es publico: XP encendida (Fase 1), voz apagada y el filtro de cuentas nuevas SI se aplica
    assert (c.eventos.xp, c.eventos.voz, c.eventos.anti_multicuentas) == (True, True, True)
    assert c.eventos.fundador_automatico is True
    assert c.eventos.rol_al_entrar == "miembro" and c.eventos.canal_logs == "registros"
    assert c.eventos.bienvenida == "bienvenida" and c.canal("bienvenida").categoria == "cat_estudio"
    assert c.canal("registros").categoria == "cat_staff"
    # Propietario: solo color y hoist, sin permisos (ni administrator)
    assert c.rol("propietario").permisos == () and c.rol("propietario").hoist
    # Developer existente: se reutiliza sin adoptar
    assert c.rol("developer").existing_id == 1561497283315638312 and not c.rol("developer").adoptar
    assert not any("administrator" in r.permisos for r in c.roles)


def test_estructura_publica_solo_equipo_y_staff_son_privadas():
    c = cargar(RUTA_REAL)
    # Orden de las categorias y nombres con el formato "emoji » NOMBRE"
    cats = sorted(c.categorias, key=lambda x: x.orden)
    assert [x.nombre for x in cats] == [
        "📌 » IMPORTANTE", "🎮 » EL JUEGO", "💬 » COMUNIDAD", "🔊 » VOZ", "🔒 » EQUIPO", "🛡️ » STAFF", "🎫 » TICKETS"]
    assert [x.key for x in cats] == ["cat_estudio", "cat_juego", "cat_comunidad", "cat_voz", "cat_equipo", "cat_staff",
                                     "cat_tickets"]
    for vieja in ("cat_anuncios", "cat_roblox", "cat_soporte", "cat_proyectos", "cat_desarrollo"):
        assert c.categoria(vieja) is None                  # fusionadas: sus canales se mueven
    privadas = {cat.key for cat in c.categorias
                if any(o.objetivo == "@everyone" and "view_channel" in o.denegar for o in cat.overrides)}
    assert privadas == {"cat_equipo", "cat_staff", "cat_tickets"}
    equipo = c.categoria("cat_equipo")
    assert {o.objetivo for o in equipo.overrides if "view_channel" in o.permitir} == {"developer", "colaborador", "administrador"}
    staff = c.categoria("cat_staff")
    assert {o.objetivo for o in staff.overrides if "view_channel" in o.permitir} == {"propietario", "administrador"}
    # IMPORTANTE: visible para todos, solo lectura para @everyone; escriben developer y administrador
    importante = c.categoria("cat_estudio")
    todos = next(o for o in importante.overrides if o.objetivo == "@everyone")
    assert "send_messages" in todos.denegar and "view_channel" not in todos.denegar
    assert {o.objetivo for o in importante.overrides if "send_messages" in o.permitir} == {"developer", "administrador"}
    for key in ("cat_juego", "cat_comunidad", "cat_voz"):
        assert c.categoria(key).overrides == ()                 # el juego es PUBLICO


def test_el_formato_de_nombres_es_emoji_y_punto_medio():
    c = cargar(RUTA_REAL)
    for canal in c.canales:
        if canal.tipo == "voice":
            continue
        emoji, sep, resto = canal.nombre.partition("・")
        assert sep == "・" and emoji and resto == resto.lower() and " " not in resto, canal.nombre
    for cat in c.categorias:
        assert " » " in cat.nombre and cat.nombre.split(" » ")[1].isupper(), cat.nombre


def test_canales_existentes_renombrados_con_adoptar_y_nombre_actual():
    c = cargar(RUTA_REAL)
    esperado = {"general": "general", "no_relacionado": "no-relacionado", "info_importante": "info-importante",
                "planificacion_sesiones": "planificación-de-sesiones"}
    for key, actual in esperado.items():
        canal = c.canal(key)
        assert canal.adoptar and canal.nombre_actual == actual and canal.mover, key
        assert canal.tema is None, key                          # solo se renombra: no se cambia el tema
    # los creados por el bot no necesitan adoptar: se renombran por estar mapeados
    for key in ("reglas", "anuncios", "showcase", "scripting_luau", "registros"):
        assert not c.canal(key).adoptar and c.canal(key).nombre_actual is None, key


def test_canales_segun_la_estructura_objetivo():
    c = cargar(RUTA_REAL)
    en = lambda cat: [x.nombre for x in sorted((x for x in c.canales if x.categoria == cat), key=lambda x: x.orden)]
    assert en("cat_estudio") == ["📜・reglas", "👋・bienvenida", "📣・anuncios", "ℹ️・info-estudio"]
    assert en("cat_juego") == ["🎁・códigos", "🐛・reportar-bugs", "💡・sugerencias", "❓・ayuda", "🎫・soporte"]
    assert en("cat_comunidad") == ["💬・general", "📸・capturas", "🤖・comandos", "📈・niveles", "🎲・no-relacionado"]
    assert c.canal("presentaciones") is None and c.mensaje("msg_presentaciones") is None   # ya no estan en el TOML
    assert en("cat_voz") == ["🔊 General"]
    assert en("cat_equipo") == ["📌・info-importante", "🗓️・planificación-de-sesiones", "🟥・scripting-luau", "Reuniones"]
    assert en("cat_staff") == ["🛡️・registros", "🧪・pruebas-bot", "📁・tickets-log"]
    assert en("cat_tickets") == []                      # aqui el bot crea un canal por ticket
    # tipos: anuncios = news (se convierte el existente), ayuda = foro nuevo que reemplaza al canal de texto
    assert c.canal("anuncios").tipo == "news" and c.canal("anuncios").mover
    ayuda = c.canal("ayuda")
    assert ayuda.tipo == "forum" and ayuda.reemplaza == "ayuda" and not ayuda.adoptar and ayuda.nombre_actual is None
    assert c.canal("info_estudio").categoria == "cat_estudio" and not c.canal("info_estudio").mover
    # Equipo: existentes movidos y sincronizados, sin cambiar su tema
    for key in ("info_importante", "planificacion_sesiones", "reuniones", "scripting_luau"):
        assert c.canal(key).categoria == "cat_equipo" and c.canal(key).sincronizar_permisos, key
    assert c.canal("reuniones").nombre == "Reuniones" and not c.canal("reuniones").adoptar
    # Desarrollo y Comunidad son publicos: nada de sincronizar
    for key in ("general", "no_relacionado"):
        assert not c.canal(key).sincronizar_permisos, key
    # #frontend y #backend los borro el dueño a proposito: el TOML ya no los menciona
    assert c.canal("frontend") is None and c.canal("backend") is None
    assert not any("frontend" in x.nombre or "backend" in x.nombre for x in c.canales)
    assert c.canal("voz_general").tipo == "voice" and c.canal("voz_general").overrides == ()
    # hasta 24 canales de texto (texto + anuncios + foros), mas la voz
    no_voz = [x for x in c.canales if x.tipo != "voice"]
    assert len(no_voz) == 20 <= 24 and len([x for x in c.canales if x.tipo == "voice"]) == 2


def test_sugerencias_usa_el_nombre_exacto_que_busca_el_comando_de_eito(mod):
    c = cargar(RUTA_REAL)
    assert c.canal("sugerencias").nombre == mod.CANAL_SUGERENCIAS == "💡・sugerencias"
    assert c.canal("sugerencias").tipo == "text" and c.canal("sugerencias").categoria == "cat_juego"
    assert c.canal("sugerencias").mover                       # se mueve desde COMUNIDAD (mismo canal, mismo nombre)
    assert c.canal("comandos").nombre == "🤖・comandos"


def test_las_reglas_son_de_comunidad_publica():
    c = cargar(RUTA_REAL)
    reglas = c.mensaje("msg_reglas").descripcion.lower()
    for tema in ("respeto", "spam", "publicidad", "creaciones ajenas", "cada canal", "staff"):
        assert tema in reglas
    # #reglas solo tiene las reglas; info, guia y botones van en #info-estudio
    assert [m.key for m in c.mensajes if m.canal == "reglas"] == ["msg_reglas"]
    assert {m.key for m in c.mensajes if m.canal == "info_estudio"} == {"msg_info_estudio", "msg_guia", "msg_especialidades"}
    assert c.mensaje("msg_especialidades").botones_roles == ("novedades", "eventos", "movil", "pc", "consola")
    assert "{canal:ayuda}" in reglas
    assert "msg_proyectos_activos" not in {m.key for m in c.mensajes}
    assert "setup" in c.comandos_bloqueados and "pss" not in c.comandos_bloqueados


def test_plantillas_comentadas_de_juego_y_archivo():
    """Las plantillas estan en el TOML pero comentadas; descomentandolas el archivo sigue siendo valido."""
    texto = RUTA_REAL.read_text(encoding="utf-8")
    assert "# nombre = \"🎮 » [JUEGO]\"" in texto and "# nombre = \"🗄️ » ARCHIVO\"" in texto
    for trozo in ('tipo = "news"', 'tipo = "forum"', "noticias", "códigos", "sugerencias-juego", "bug-report"):
        assert trozo in texto
    # descomentar solo los bloques de plantilla (los que llevan cat_juego1 / cat_archivo / juego1_*)
    lineas, salida, activo = texto.split("\n"), [], False
    for i, linea in enumerate(lineas):
        if linea.startswith("# [[") and any(k in " ".join(lineas[i:i + 4]) for k in ("cat_juego1", "cat_archivo", "juego1_")):
            activo = True
        elif not linea.startswith("#") or linea.strip() == "#":
            activo = False
        salida.append(linea[2:] if activo and linea.startswith("# ") else linea)
    import tomllib
    c = parsear(tomllib.loads("\n".join(salida)))
    assert c.categoria("cat_juego1").nombre == "🎮 » [JUEGO]"
    assert c.categoria("cat_archivo").nombre == "🗄️ » ARCHIVO"
    archivo = c.categoria("cat_archivo")
    assert "send_messages" in archivo.overrides[0].denegar and archivo.overrides[0].permitir == ()
    assert {x.tipo for x in c.canales if x.categoria == "cat_juego1"} == {"news", "text", "forum"}


def con_canal_extra(**campos):
    """datos() mas un canal 'otro' (los demas estan referenciados por eventos y mensajes)."""
    d = datos()
    d["canales"].append({"key": "otro", "nombre": "otro", "categoria": "cat_a", **campos})
    return d


def test_tipos_de_canal_news_y_forum():
    assert parsear(con_canal_extra(tipo="news")).canal("otro").tipo == "news"
    assert parsear(con_canal_extra(tipo="forum")).canal("otro").tipo == "forum"
    assert alguno(errores_de(con_canal_extra(tipo="stage")), "tipo", "news", "forum")
    # un anuncio no tiene slowmode; un foro no tiene limite de voz
    assert alguno(errores_de(con_canal_extra(tipo="news", slowmode=5)), "slowmode")
    assert alguno(errores_de(con_canal_extra(tipo="forum", limite_usuarios=5)), "limite_usuarios")
    assert parsear(con_canal_extra(tipo="forum", slowmode=5)).canal("otro").slowmode == 5


def test_los_mensajes_solo_pueden_ir_a_canales_de_texto_o_anuncios_no_a_foros():
    d = con_canal_extra(tipo="forum")
    d["mensajes"][0]["canal"] = "otro"
    assert alguno(errores_de(d), "mensaje 'msg'.canal", "otro")            # los foros no reciben mensajes del bot
    d = con_canal_extra(tipo="news")
    d["mensajes"][0]["canal"] = "otro"
    assert parsear(d).mensaje("msg").canal == "otro"                          # un canal de anuncios si


def test_reemplaza_solo_en_foros_y_nombre_actual_no_vale_para_foros():
    assert alguno(errores_de(con_canal_extra(reemplaza="viejo")), "reemplaza", "foros")
    assert parsear(con_canal_extra(tipo="forum", reemplaza="viejo")).canal("otro").reemplaza == "viejo"
    assert alguno(errores_de(con_canal_extra(tipo="forum", adoptar=True, nombre_actual="viejo")), "nombre_actual", "foro")


def test_permiso_invalido_con_sugerencia():
    d = datos()
    d["roles"][0]["permisos"] = ["manage_server"]
    errores = errores_de(d)
    assert alguno(errores, "roles[0] 'miembro'", "manage_server", "manage_guild")


def test_administrator_exige_permitir_admin():
    d = datos()
    d["roles"][0]["permisos"] = ["administrator"]
    assert alguno(errores_de(d), "administrator", "permitir_admin")
    d["roles"][0]["permitir_admin"] = True
    assert parsear(d).rol("miembro").permitir_admin


def test_por_encima_del_bot_es_opcional_booleano_y_solo_lo_usa_propietario():
    d = datos()
    assert parsear(d).rol("miembro").por_encima_del_bot is False
    d["roles"][0]["por_encima_del_bot"] = True
    assert parsear(d).rol("miembro").por_encima_del_bot is True
    d["roles"][0]["por_encima_del_bot"] = "si"
    assert errores_de(d)
    c = cargar(RUTA_REAL)
    assert [r.key for r in c.roles if r.por_encima_del_bot] == ["propietario"]


# --- [recursos]: claves de los sistemas de EITO -> keys del TOML ---------------------------------------------
def datos_recursos(**recursos):
    d = datos()
    d["canales"].append({"key": "voz", "nombre": "voz", "categoria": "cat_a", "tipo": "voice"})
    d["recursos"] = recursos
    return d


def test_recursos_validos_y_opcionales():
    assert parsear(datos()).recursos.roles == {} and parsear(datos()).recursos.canales == {}
    r = parsear(datos_recursos(
        roles={"veterano": "miembro", "staff_tickets": ["miembro"], "ping_tickets": ["miembro"]},
        canales={"niveles": "general", "anuncios": "logs"}, categorias={"tickets": "cat_a"})).recursos
    assert r.roles == {"veterano": ("miembro",), "staff_tickets": ("miembro",), "ping_tickets": ("miembro",)}
    assert r.canales == {"niveles": "general", "anuncios": "logs"} and r.categorias == {"tickets": "cat_a"}


def test_recursos_clave_desconocida_con_sugerencia():
    texto = " | ".join(errores_de(datos_recursos(roles={"veteranos": "miembro"}, canales={"nivels": "general"},
                                                 categorias={"ticket": "cat_a"}, otra={})))
    assert "recursos.roles.veteranos" in texto and "veterano" in texto
    assert "recursos.canales.nivels" in texto and "niveles" in texto
    assert "recursos.categorias.ticket" in texto and "tickets" in texto
    assert "recursos.otra" in texto and "clave desconocida" in texto


def test_recursos_deben_apuntar_a_una_key_existente_y_del_tipo_correcto():
    texto = " | ".join(errores_de(datos_recursos(
        roles={"veterano": "fantasma", "og": "general", "fundador": ["miembro", "miembro"]},
        canales={"niveles": "fantasma", "anuncios": "voz", "soporte": "miembro", "logros": 3},
        categorias={"tickets": "general"})))
    assert "'fantasma' no es una key de [[roles]]" in texto           # rol inexistente
    assert "'general' no es una key de [[roles]]" in texto            # un canal donde va un rol
    assert "admite un solo rol" in texto                              # lista en una clave de un solo rol
    assert "'fantasma' no es una key de [[canales]]" in texto
    assert "es de tipo 'voice'" in texto                              # canal de voz donde va uno de texto
    assert "'miembro' no es una key de [[canales]]" in texto          # un rol donde va un canal
    assert "recursos.canales.logros" in texto and "debe ser la key de un canal" in texto
    assert "'general' no es una key de [[categorias]]" in texto       # un canal donde va una categoria


def test_recursos_acepta_un_canal_de_anuncios_y_listas_en_las_claves_que_las_admiten():
    d = datos_recursos(canales={"anuncios": "anu"}, roles={"honor": ["miembro"], "excluidos_activo_mes": "miembro"})
    d["canales"].append({"key": "anu", "nombre": "anuncios", "categoria": "cat_a", "tipo": "news"})
    r = parsear(d).recursos
    assert r.canales == {"anuncios": "anu"} and r.roles["honor"] == ("miembro",)


# --- Fase 1: roles nuevos, bienvenida, comandos y XP ---------------------------------------------------------
def test_fase_1_roles_nuevos_helper_y_novedades():
    c = cargar(RUTA_REAL)
    helper, novedades = c.rol("helper"), c.rol("novedades")
    assert helper.nombre == "Helper" and helper.permisos == () and not helper.autoasignable and not helper.mentionable
    assert novedades.nombre == "🔔 Novedades" and novedades.mentionable and novedades.autoasignable
    assert novedades.permisos == () and not novedades.hoist
    assert not any("administrator" in r.permisos for r in c.roles)


def test_fase_1_xp_bienvenida_y_comandos():
    c = cargar(RUTA_REAL)
    assert c.eventos.xp is True and c.eventos.voz is True      # voz: Fase 3
    assert c.recursos.canales["niveles"] == "niveles"
    niveles = c.canal("niveles")
    assert niveles.nombre == "📈・niveles" and niveles.categoria == "cat_comunidad"
    # solo lectura para @everyone (el bot escribe gracias a su override automatico)
    todos = next(o for o in niveles.overrides if o.objetivo == "@everyone")
    assert "send_messages" in todos.denegar and "view_channel" not in todos.denegar
    assert c.canal("pruebas_bot").categoria == "cat_staff"
    assert c.canal("bienvenida").categoria == "cat_estudio" and c.canal("bienvenida").overrides == ()
    # bloqueados: sin nivel/top, con fundadores/importarniveles/darnivel
    assert c.comandos_bloqueados == {
        "setup", "setupsteam", "setuprecompensas", "crearvcs", "panelcochipuerco", "panelroles", "reglas", "info",
        "presentaciones", "steam", "jugar", "perfil", "importarniveles", "darnivel"}
    for habilitado in ("nivel", "top", "fundadores", "paneltickets"):
        assert habilitado not in c.comandos_bloqueados, habilitado


def test_la_bienvenida_enlaza_a_las_reglas_y_a_info_estudio():
    b = cargar(RUTA_REAL).bienvenida
    assert "{canal:reglas}" in b.descripcion and "{canal:info_estudio}" in b.descripcion
    assert "{usuario}" in b.descripcion and "{numero}" in b.descripcion and "{servidor}" in b.titulo


def test_bienvenida_validacion():
    d = datos()
    d["bienvenida"] = {"titulo": "Hola {servidor}", "descripcion": "{usuario} eres el #{numero}. Ve a {canal:general}"}
    b = parsear(d).bienvenida
    assert b.titulo == "Hola {servidor}" and b.color == 0x2ECC71
    assert parsear(datos()).bienvenida is None                                 # opcional
    d["bienvenida"] = {"titulo": "x", "descripcion": "{nombre} {canal:fantasma} {rol:nadie}", "color": "verde"}
    texto = " | ".join(errores_de(d))
    assert "{nombre} no es una variable valida" in texto
    assert "{canal:fantasma} no existe en [[canales]]" in texto and "{rol:nadie} no existe en [[roles]]" in texto
    assert "bienvenida.color" in texto
    d["bienvenida"] = {"titulo": "x"}
    assert "bienvenida.descripcion: es obligatorio" in " | ".join(errores_de(d))
    d["bienvenida"] = {"titulo": "x", "descripcion": "y", "otra": 1}
    assert "clave desconocida" in " | ".join(errores_de(d))


# --- Fase 2: rangos, tickets y recursos ---------------------------------------------------------------------
def test_fase_2_roles_de_rango_y_distincion_sin_permisos():
    c = cargar(RUTA_REAL)
    nombres = {"activo_mes": "🔥 Activo del mes", "og": "🥇 OG", "fundador": "🌱 Fundador",
               "leyenda": "🥈 Leyenda", "veterano": "🥉 Veterano"}
    for key, nombre in nombres.items():
        rol = c.rol(key)
        assert rol.nombre == nombre and rol.permisos == () and not rol.autoasignable and not rol.mentionable, key
    assert c.rol("og").hoist and c.rol("activo_mes").hoist and not c.rol("fundador").hoist
    assert not any("administrator" in r.permisos for r in c.roles)


def test_fase_2_recursos_apuntan_a_roles_canales_y_categoria_de_tickets():
    r = cargar(RUTA_REAL).recursos
    assert r.roles["staff_tickets"] == ("propietario", "administrador")
    assert r.roles["ping_tickets"] == ("propietario", "administrador")
    assert r.roles["excluidos_activo_mes"] == ("developer",) and r.roles["honor"] == ("og",)
    assert "developer" not in r.roles                         # sin mapear: setxp/resetxp/exportarserver/fundadores, solo el dueño
    for clave in ("activo_mes", "fundador", "veterano", "leyenda", "og"):
        assert r.roles[clave] == (clave,)
    assert r.canales == {"anuncios": "anuncios", "niveles": "niveles", "soporte": "soporte",
                         "transcripciones": "tickets_log"}
    assert "logros" not in r.canales                          # los logros caen a 📈・niveles
    assert r.categorias == {"tickets": "cat_tickets"}


def test_fase_2_tickets_soporte_y_log():
    c = cargar(RUTA_REAL)
    soporte, log = c.canal("soporte"), c.canal("tickets_log")
    assert soporte.nombre == "🎫・soporte" and soporte.categoria == "cat_juego" and soporte.mover
    assert soporte.orden > c.canal("ayuda").orden                    # debajo del foro
    todos = next(o for o in soporte.overrides if o.objetivo == "@everyone")
    assert "send_messages" in todos.denegar and "view_channel" not in todos.denegar
    assert log.nombre == "📁・tickets-log" and log.categoria == "cat_staff" and log.overrides == ()
    assert "#🎫・soporte" in c.canal("ayuda").tema                    # el tema del foro lo enlaza
    assert c.categoria("cat_tickets").nombre == "🎫 » TICKETS"
    assert "{canal:soporte}" in " ".join(v for _n, v, _i in c.mensaje("msg_guia").campos)


def test_fase_2_rangos_y_ayuda():
    c = cargar(RUTA_REAL)
    import datetime as dt
    assert c.rangos.contar_desde == dt.datetime(2026, 10, 19, tzinfo=dt.timezone.utc)
    administracion = next(s for s in c.ayuda.secciones if s.titulo == "⚙️ Administración")
    assert [e.comando for e in administracion.entradas] == ["anuncio", "exportarserver", "setxp", "resetxp", "fundadores"]


def test_rangos_validacion():
    import datetime as dt
    d = datos()
    assert parsear(d).rangos.contar_desde is None                       # sin la clave: cuenta la entrada
    d["rangos"] = {"contar_desde": "2026-10-19"}
    assert parsear(d).rangos.contar_desde == dt.datetime(2026, 10, 19, tzinfo=dt.timezone.utc)
    d["rangos"] = {"contar_desde": dt.date(2026, 10, 19)}                # fecha nativa de TOML
    assert parsear(d).rangos.contar_desde == dt.datetime(2026, 10, 19, tzinfo=dt.timezone.utc)
    for malo in ("19/10/2026", "mañana", 5):
        d["rangos"] = {"contar_desde": malo}
        assert "rangos.contar_desde" in " | ".join(errores_de(d)), malo
    d["rangos"] = {"otra": 1}
    assert "clave desconocida" in " | ".join(errores_de(d))


# --- Fase 3: voz activa, webhook con destino, fundador automatico -------------------------------------------
def test_fase_3_voz_activa_y_webhook_de_pss():
    c = cargar(RUTA_REAL)
    voz = c.rol("voz_activa")
    assert voz.nombre == "🎧 Voz activa" and voz.permisos == () and not voz.autoasignable
    assert c.recursos.roles["voz_activa"] == ("voz_activa",)
    assert c.webhook == {"pss": DestinoRelease(canal="anuncios", rol="novedades")}
    assert c.canal(c.webhook["pss"].canal).tipo == "news" and c.rol(c.webhook["pss"].rol).mentionable
    # la recompensa por nivel NO se implementa: ni el rol ni el canal de EITO
    assert c.rol("nivel_10") is None and c.canal("nivel_10") is None
    assert not any("nivel-10" in x.nombre or "Nivel 10" in x.nombre for x in (*c.canales, *c.roles))


def test_webhook_validacion():
    d = datos()
    d["canales"].append({"key": "voz", "nombre": "voz", "categoria": "cat_a", "tipo": "voice"})
    assert parsear(datos()).webhook == {}
    d["webhook"] = {"pss": {"canal": "general", "rol": "miembro"}}
    assert parsear(d).webhook["pss"] == DestinoRelease("general", "miembro")
    d["webhook"] = {"PSS": {"canal": "fantasma", "rol": "nadie"}, "otro": {"canal": "voz", "rol": "miembro", "x": 1},
                    "vacio": {}}
    texto = " | ".join(errores_de(d))
    assert "webhook.PSS" in texto and "minusculas" in texto
    assert "'fantasma' no es una key de [[canales]]" in texto and "'nadie' no es una key de [[roles]]" in texto
    assert "es de tipo 'voice'" in texto and "clave desconocida" in texto
    assert "webhook.vacio.canal: es obligatorio" in texto and "webhook.vacio.rol: es obligatorio" in texto


def test_fundador_automatico_es_un_evento_booleano_y_por_defecto_apagado():
    assert parsear(datos()).eventos.fundador_automatico is False
    d = datos()
    d["eventos"]["fundador_automatico"] = True
    assert parsear(d).eventos.fundador_automatico is True
    d["eventos"]["fundador_automatico"] = "si"
    assert errores_de(d)


# --- El juego: [juego], categoria, mensajes, panel de roles --------------------------------------------------
def juego_real(**juego):
    import tomllib
    with RUTA_REAL.open("rb") as f:
        d = tomllib.load(f)
    d["juego"] = juego
    return d


def test_juego_vacio_la_categoria_se_llama_el_juego_y_la_info_omite_el_campo():
    c = cargar(RUTA_REAL)
    assert (c.juego.nombre, c.juego.enlace_juego, c.juego.enlace_grupo) == ("", "", "")
    assert c.categoria("cat_juego").nombre == "🎮 » EL JUEGO"
    assert [n for n, _v, _i in c.mensaje("msg_info_estudio").campos] == ["🤝 ¿Quieres unirte al equipo?"]
    assert "GitHub" not in c.mensaje("msg_info_estudio").descripcion


def test_juego_con_nombre_renombra_la_categoria_y_aparecen_sus_campos():
    c = parsear(juego_real(nombre="Mi Juego", enlace_juego="https://www.roblox.com/games/1/x",
                           enlace_grupo="https://www.roblox.com/communities/2/y"))
    assert c.categoria("cat_juego").nombre == "🎮 » MI JUEGO"
    campos = {n: v for n, v, _i in c.mensaje("msg_info_estudio").campos}
    assert campos["🎮 El juego"] == "[Mi Juego](https://www.roblox.com/games/1/x)"
    assert campos["👥 Grupo de Roblox"] == "https://www.roblox.com/communities/2/y"
    assert list(campos)[-1] == "🤝 ¿Quieres unirte al equipo?"


def test_juego_con_nombre_sin_enlaces_y_con_solo_el_grupo():
    c = parsear(juego_real(nombre="Mi Juego"))
    campos = {n: v for n, v, _i in c.mensaje("msg_info_estudio").campos}
    assert campos["🎮 El juego"] == "**Mi Juego**" and "👥 Grupo de Roblox" not in campos
    c = parsear(juego_real(enlace_grupo="https://roblox.com/communities/2/y"))      # sin nombre: no hay campo del juego
    campos = {n for n, _v, _i in c.mensaje("msg_info_estudio").campos}
    assert "🎮 El juego" not in campos and "👥 Grupo de Roblox" in campos
    assert c.categoria("cat_juego").nombre == "🎮 » EL JUEGO"


@pytest.mark.parametrize("malo", [
    "http://www.roblox.com/games/1", "https://roblox.com.evil.com/games/1", "https://evil.com/roblox.com",
    "https://notroblox.com/games/1", "ftp://roblox.com/x", "www.roblox.com/games/1", "https://user:pw@www.roblox.com/x",
    "https://www.roblox.com/ juego"])
def test_los_enlaces_del_juego_deben_ser_https_de_roblox_com(malo):
    for clave in ("enlace_juego", "enlace_grupo"):
        assert f"juego.{clave}" in " | ".join(errores_de(juego_real(**{clave: malo})))


@pytest.mark.parametrize("bueno", ["https://www.roblox.com/games/1", "https://roblox.com/x", "https://web.roblox.com/x?a=1"])
def test_enlaces_validos_de_roblox(bueno):
    assert parsear(juego_real(enlace_juego=bueno, enlace_grupo=bueno)).juego.enlace_juego == bueno


def test_juego_claves_desconocidas_y_nombre_con_llaves():
    assert "clave desconocida" in " | ".join(errores_de(juego_real(otro="x")))
    assert "juego.nombre" in " | ".join(errores_de(juego_real(nombre="Mi {juego}")))


def test_el_nombre_de_la_categoria_cumple_el_formato_aunque_el_juego_este_vacio_o_lleno():
    for nombre in ("", "Mi Juego"):
        cat = parsear(juego_real(nombre=nombre)).categoria("cat_juego").nombre
        assert " » " in cat and cat.split(" » ")[1].isupper()


def test_la_guia_para_jugadores_y_la_info():
    c = cargar(RUTA_REAL)
    info = c.mensaje("msg_info_estudio")
    assert info.titulo == "👻 Phantom Shadows Studios"
    assert info.descripcion == "Somos un estudio independiente que crea experiencias en **Roblox**."
    assert "{canal:soporte}" in dict((n, v) for n, v, _i in info.campos)["🤝 ¿Quieres unirte al equipo?"]
    guia = c.mensaje("msg_guia")
    assert guia.titulo == "🧭 Guía para jugadores" and guia.descripcion == ""
    assert [n for n, _v, _i in guia.campos] == ["1️⃣ Empieza aquí", "🎮 El juego", "🐛 ¿Algo falla?", "🆘 Ayuda", "💬 Comunidad"]
    assert not any(i for _n, _v, i in guia.campos)                      # ninguno en linea
    texto = " ".join(v for _n, v, _i in guia.campos)
    for ref in ("reglas", "anuncios", "codigos", "sugerencias", "reportar_bugs", "ayuda", "soporte", "general",
                "showcase", "comandos"):
        assert "{canal:" + ref + "}" in texto, ref
    assert "`!nivel`, `!top` y `!ayuda`" in texto


def test_la_regla_del_juego_y_la_bienvenida_sin_presentaciones():
    c = cargar(RUTA_REAL)
    assert "No uses ni compartas exploits o hacks. Si encuentras un bug, repórtalo en {canal:reportar_bugs}; no lo abuses." in \
        c.mensaje("msg_reglas").descripcion.replace("**", "")
    assert "{canal:reglas}" in c.bienvenida.descripcion and "{canal:info_estudio}" in c.bienvenida.descripcion
    assert "presentaciones" not in c.bienvenida.descripcion


def test_roles_del_equipo_sin_boton_y_roles_nuevos_de_avisos_y_plataforma():
    c = cargar(RUTA_REAL)
    for key in ("scripter", "builder", "ui"):
        assert not c.rol(key).autoasignable and c.rol(key).permisos == ()
    assert [r.key for r in c.roles_autoasignables()] == ["novedades", "eventos", "movil", "pc", "consola"]
    eventos = c.rol("eventos")
    assert eventos.nombre == "🎉 Eventos" and eventos.mentionable and eventos.permisos == ()
    for key, nombre in (("movil", "📱 Móvil"), ("pc", "💻 PC"), ("consola", "🎮 Consola")):
        assert c.rol(key).nombre == nombre and c.rol(key).permisos == () and not c.rol(key).mentionable, key


def test_el_panel_de_roles_filas_estilos_y_emojis():
    c = cargar(RUTA_REAL)
    panel = c.mensaje("msg_especialidades")
    assert panel.titulo == "🎭 Elige tus roles"
    assert panel.descripcion == "Pulsa un botón para darte el rol; púlsalo otra vez para quitártelo."
    assert [(b.rol, b.estilo, b.fila, b.emoji) for b in panel.botones] == [
        ("novedades", "success", 0, "🔔"), ("eventos", "success", 0, "🎉"),
        ("movil", "secondary", 1, "📱"), ("pc", "secondary", 1, "💻"), ("consola", "secondary", 1, "🎮")]


def test_botones_con_emoji_estilo_y_fila_son_opcionales_y_se_validan():
    d = datos()
    d["roles"][0]["autoasignable"] = True
    d["mensajes"][0]["botones_roles"] = ["miembro"]                     # forma antigua: lista de keys
    b = parsear(d).mensaje("msg").botones
    assert b[0].rol == "miembro" and (b[0].estilo, b[0].fila, b[0].emoji) == ("secondary", None, "")
    d["mensajes"][0]["botones_roles"] = [{"rol": "miembro", "estilo": "danger", "fila": 2, "emoji": "🔥"}]
    assert parsear(d).mensaje("msg").botones[0] == Boton("miembro", "danger", 2, "🔥")
    for malo, trozo in (({"rol": "miembro", "estilo": "rojo"}, "estilo"), ({"rol": "miembro", "fila": 5}, "fila"),
                        ({"rol": "miembro", "emoji": "abc"}, "emoji"), ({"rol": "miembro", "x": 1}, "clave desconocida"),
                        ({"estilo": "success"}, "obligatorio"), (7, "debe ser")):
        d["mensajes"][0]["botones_roles"] = [malo]
        assert trozo in " | ".join(errores_de(d)), malo
    d["mensajes"][0]["botones_roles"] = [{"rol": "miembro", "fila": 0}] * 6
    assert "maximo 5" in " | ".join(errores_de(d))


def test_campo_con_solo_si_desconocido_es_un_error():
    d = datos()
    d["mensajes"][0]["campos"] = [{"nombre": "a", "valor": "b", "solo_si": "juego.otra"}]
    assert "solo_si" in " | ".join(errores_de(d))


def test_claves_duplicadas_entre_tipos():
    d = datos()
    d["canales"].append({"key": "miembro", "nombre": "x", "categoria": "cat_a"})
    assert alguno(errores_de(d), "key duplicada", "miembro")


def test_referencias_inexistentes():
    d = datos()
    d["categorias"][0]["overrides"][1]["objetivo"] = "fantasma"
    d["canales"][0]["categoria"] = "no_existe"
    d["mensajes"][0]["canal"] = "nada"
    d["eventos"]["rol_al_entrar"] = "otro"
    d["perfil"]["gestores"] = ["jefe"]
    errores = errores_de(d)
    assert alguno(errores, "fantasma")
    assert alguno(errores, "no_existe")
    assert alguno(errores, "mensaje 'msg'.canal", "nada")
    assert alguno(errores, "eventos.rol_al_entrar", "otro")
    assert alguno(errores, "perfil.gestores", "jefe")


def test_placeholder_a_recurso_inexistente():
    d = datos()
    d["mensajes"][0]["descripcion"] = "mira {rol:nadie} y {canal:tampoco}"
    errores = errores_de(d)
    assert alguno(errores, "{rol:nadie}") and alguno(errores, "{canal:tampoco}")


def test_se_reportan_todos_los_errores_juntos():
    d = datos()
    d["roles"][0]["permisos"] = ["nope"]
    d["roles"][0]["color"] = "rojo"
    d["canales"][0]["slowmode"] = 99999
    assert len(errores_de(d)) >= 3


def test_limites_de_discord():
    d = datos()
    d["roles"][0]["nombre"] = "x" * 101
    d["canales"][0]["tema"] = "t" * 1025
    d["canales"][0]["slowmode"] = 21601
    d["mensajes"][0]["titulo"] = "t" * 257
    d["mensajes"][0]["descripcion"] = "d" * 4097
    errores = errores_de(d)
    assert alguno(errores, "roles[0]", "nombre", "101")
    assert alguno(errores, "tema", "1025")
    assert alguno(errores, "slowmode", "21601")
    assert alguno(errores, "titulo", "257")
    assert alguno(errores, "descripcion", "4097")


def test_limite_de_50_canales_por_categoria():
    d = datos()
    d["canales"] = [{"key": f"c{i}", "nombre": f"c{i}", "categoria": "cat_a"} for i in range(51)]
    d["eventos"] = {}
    d["mensajes"] = []
    assert alguno(errores_de(d), "cat_a", "51", "50")


def test_limite_de_250_roles_y_500_canales():
    d = datos()
    d["roles"] = [{"key": f"r{i}", "nombre": f"r{i}"} for i in range(251)]
    d["categorias"][0]["overrides"] = []
    d["eventos"] = {}
    assert alguno(errores_de(d), "251", "250")
    d = datos()
    d["categorias"] = [{"key": f"cat{i}", "nombre": f"c{i}"} for i in range(11)]
    d["canales"] = [{"key": f"ch{i}", "nombre": f"c{i}", "categoria": f"cat{i % 11}"} for i in range(490)]
    d["eventos"] = {}
    d["mensajes"] = []
    assert alguno(errores_de(d), "501", "500")


def test_embed_demasiado_grande():
    d = datos()
    d["mensajes"][0] = {"key": "msg", "canal": "general", "descripcion": "a" * 4000,
                        "campos": [{"nombre": "n", "valor": "v" * 1000} for _ in range(3)]}
    assert alguno(errores_de(d), "embed", "6000")


def test_clave_desconocida_y_key_mal_formada():
    d = datos()
    d["roles"][0]["colorr"] = "#fff"
    d["canales"][0]["key"] = "Mala Key"
    errores = errores_de(d)
    assert alguno(errores, "colorr", "desconocida")
    assert alguno(errores, "key", "[a-z0-9_]")


def test_rol_autoasignable_no_puede_ser_elevado_ni_existente():
    d = datos()
    d["roles"].append({"key": "esp", "nombre": "Esp", "autoasignable": True, "permisos": ["manage_roles"]})
    assert alguno(errores_de(d), "autoasignable", "elevados", "manage_roles")
    d["roles"][1] = {"key": "esp", "nombre": "Esp", "autoasignable": True, "existing_id": 5}
    assert alguno(errores_de(d), "autoasignable", "existing_id")


def test_botones_solo_de_roles_autoasignables():
    d = datos()
    d["mensajes"][0]["botones_roles"] = ["miembro"]
    assert alguno(errores_de(d), "botones_roles", "no es autoasignable")


def test_no_se_puede_bloquear_pss_y_existing_id_no_se_repite():
    d = datos()
    d["comandos"] = {"bloquear": ["pss"]}
    assert alguno(errores_de(d), "pss")
    d = datos()
    d["roles"].append({"key": "otro", "nombre": "Otro", "existing_id": 7})
    d["roles"][0]["existing_id"] = 7
    assert alguno(errores_de(d), "existing_id 7")


def test_overrides_contradictorios():
    d = datos()
    d["categorias"][0]["overrides"] = [{"objetivo": "@everyone", "permitir": ["view_channel"], "denegar": ["view_channel"]}]
    assert alguno(errores_de(d), "a la vez")
    d = datos()
    d["canales"][0]["sincronizar_permisos"] = True
    d["canales"][0]["overrides"] = [{"objetivo": "@everyone", "denegar": ["send_messages"]}]
    assert alguno(errores_de(d), "sincronizar_permisos", "overrides")


def test_nombre_actual_solo_con_adoptar():
    d = datos()
    d["canales"][0]["nombre_actual"] = "viejo"
    assert alguno(errores_de(d), "nombre_actual", "adoptar")
    d["canales"][0]["adoptar"] = True
    assert parsear(d).canal("general").nombre_actual == "viejo"


def test_toml_roto_o_inexistente(tmp_path):
    malo = tmp_path / "malo.toml"
    malo.write_text("[perfil\nguild_id = 1", encoding="utf-8")
    with pytest.raises(ConfigInvalida) as e:
        cargar(malo)
    assert "no es un TOML valido" in str(e.value)
    with pytest.raises(ConfigInvalida) as e:
        cargar(tmp_path / "no_existe.toml")
    assert "no existe" in str(e.value)
