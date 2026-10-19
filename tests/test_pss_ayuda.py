"""Ayuda separada por servidor (PSS), comandos bloqueados y !pss ayuda.

Se prueba contra el bot REAL de EITO (el modulo importado, sin conectarse a Discord): la ayuda de PSS
usa can_run de los comandos de verdad, y los comandos bloqueados pasan por sus manejadores .error."""

import logging
import types
from pathlib import Path

import discord
import pytest
from discord.ext import commands

from profiles import pss_db
from profiles.pss import (
    AYUDA_PSS, MSG_NO_DISPONIBLE, PerfilPSS, PssComandoBloqueado, PssNoAplica, PssSinPermiso,
)
from profiles.pss_config import ConfigInvalida, cargar, comandos_de_ayuda_inexistentes, parsear

RUTA = Path(__file__).resolve().parent.parent / "profiles" / "pss.toml"
G_PSS, OTRO = 1420403964746268684, 5
NUEVOS_BLOQUEADOS = ("steam", "jugar", "perfil", "fundadores", "importarniveles", "darnivel")


@pytest.fixture
def sin_bd(monkeypatch):
    async def nada(*a, **k):
        return None

    async def mapa(guild_id):
        return {}

    monkeypatch.setattr(pss_db, "asegurar_tabla", nada)
    monkeypatch.setattr(pss_db, "cargar_mapa", mapa)


@pytest.fixture(autouse=True)
async def con_anti_multicuentas(mod):
    """!permitir y !despermitir son del cog AntiMulticuentas, que el bot registra en setup_hook: aqui se
    registra tambien para no depender de que otro test haya corrido setup_hook antes."""
    from anti_multicuentas import AntiMulticuentas
    puesto = mod.bot.get_cog("AntiMulticuentas") is None
    if puesto:
        await mod.bot.add_cog(AntiMulticuentas(mod.bot, mod.registrar_log))
    yield
    if puesto:
        await mod.bot.remove_cog("AntiMulticuentas")


@pytest.fixture
async def perfil(mod, sin_bd):
    """El cog de PSS cargado en el bot real (y descargado al terminar)."""
    cog = PerfilPSS(mod.bot, cargar(RUTA), RUTA)
    await mod.bot.add_cog(cog)
    cog.ids = {"sugerencias": 777}
    yield cog
    await mod.bot.remove_cog("PerfilPSS")


async def _comando_vacio(ctx):
    return None


def ctx_de(mod, fakes, guild_id, permisos=0, comando="ayuda"):
    cmd = mod.bot.get_command(comando)
    ctx = fakes.Ctx(guild=fakes.Guild(id=guild_id), comando=cmd)
    ctx.bot = mod.bot
    ctx.permissions = discord.Permissions(permisos)           # lo que leen has_permissions & co.
    ctx.author.guild_permissions = discord.Permissions(permisos)
    return ctx


MODERADOR = discord.Permissions(kick_members=True, ban_members=True, moderate_members=True,
                                manage_messages=True).value


# --- 1. Gancho en !ayuda de EITO --------------------------------------------------------------------------------
async def test_sin_perfil_la_ayuda_de_eito_es_la_de_siempre(mod, fakes):
    assert mod.bot.get_cog("PerfilPSS") is None
    ctx = ctx_de(mod, fakes, OTRO)
    await mod.ayuda.callback(ctx)
    embed = ctx.respuestas[0][1]["embed"]
    assert embed.title == "📖 Comandos de EITO" and embed.description == "Todos los comandos usan el prefijo `!`"
    assert "Ganas XP" in embed.footer.text
    assert any("nivel" in f.value for f in embed.fields)          # lo de EITO sigue ahi


async def test_con_perfil_pero_en_otro_servidor_la_ayuda_sigue_siendo_la_de_eito(mod, fakes, perfil):
    ctx = ctx_de(mod, fakes, OTRO)
    await mod.ayuda.callback(ctx)
    embed = ctx.respuestas[0][1]["embed"]
    assert embed.title == "📖 Comandos de EITO" and "Ganas XP" in embed.footer.text


async def test_en_el_servidor_del_perfil_la_ayuda_delega_en_el_perfil(mod, fakes, perfil, monkeypatch):
    recibidos = []

    async def enviar_ayuda(ctx):
        recibidos.append(ctx)

    monkeypatch.setattr(perfil, "enviar_ayuda", enviar_ayuda)
    ctx = ctx_de(mod, fakes, G_PSS)
    await mod.ayuda.callback(ctx)
    assert recibidos == [ctx] and ctx.respuestas == []             # delega y vuelve: EITO no envia nada


# --- 2/3. Contenido y visibilidad de la ayuda de PSS ----------------------------------------------------------------
def lineas(embed):
    return {f.name: f.value.split("\n") for f in embed.fields}


async def test_un_miembro_ve_comunidad_y_utilidad_pero_no_moderacion(mod, fakes, perfil):
    ctx = ctx_de(mod, fakes, G_PSS, permisos=0)
    await perfil.enviar_ayuda(ctx)
    embed = ctx.respuestas[0][1]["embed"]
    assert embed.title == "📖 Comandos de Phantom Shadows Studios"
    campos = lineas(embed)
    assert list(campos) == ["🎮 Comunidad", "📊 Utilidad"]
    assert [x.split("`")[1] for x in campos["🎮 Comunidad"]] == [
        "!ping", "!avatar [@usuario]", "!serverinfo", "!miembros", "!nivel [@usuario]", "!top"]
    assert [x.split("`")[1] for x in campos["📊 Utilidad"]] == ["!encuesta <pregunta>", "!sugerencia <texto>"]
    assert "<#777>" in campos["📊 Utilidad"][1]                   # indica el canal de sugerencias (mencion)
    texto = "\n".join(f.value for f in embed.fields)
    for fuera in ("!perfil", "!steam", "!jugar", "!fundadores", "!darnivel", "!warn", "!kick", "!borrar",
                  "!permitir", "!anuncio", "!setxp", "!ayuda"):
        assert fuera not in texto, fuera


async def test_un_moderador_ve_ademas_la_moderacion(mod, fakes, perfil):
    ctx = ctx_de(mod, fakes, G_PSS, permisos=MODERADOR)
    await perfil.enviar_ayuda(ctx)
    campos = lineas(ctx.respuestas[0][1]["embed"])
    assert list(campos) == ["🎮 Comunidad", "📊 Utilidad", "🛡️ Moderación"]
    assert [x.split("`")[1].split()[0] for x in campos["🛡️ Moderación"]] == [
        "!borrar", "!kick", "!ban", "!mute", "!unmute", "!warn", "!warns", "!permitir", "!despermitir"]


async def test_la_administracion_la_ven_solo_quienes_pueden_usar_esos_comandos(mod, fakes, perfil):
    def nombres(ctx):
        campos = lineas(ctx.respuestas[0][1]["embed"])
        return [x.split("`")[1].split()[0] for x in campos.get("⚙️ Administración", [])]

    # un moderador: sin Administracion
    ctx = ctx_de(mod, fakes, G_PSS, permisos=MODERADOR)
    await perfil.enviar_ayuda(ctx)
    assert nombres(ctx) == []
    # un administrador que NO es el dueño: !anuncio (Gestionar servidor), pero no exportarserver/setxp/resetxp
    ctx = ctx_de(mod, fakes, G_PSS, permisos=discord.Permissions.all().value)
    await perfil.enviar_ayuda(ctx)
    assert nombres(ctx) == ["!anuncio"]
    # el dueño las ve las cuatro
    ctx = ctx_de(mod, fakes, G_PSS, permisos=discord.Permissions.all().value)
    ctx.guild.owner_id = ctx.author.id
    await perfil.enviar_ayuda(ctx)
    assert nombres(ctx) == ["!anuncio", "!exportarserver", "!setxp", "!resetxp"]


async def test_solo_ve_los_comandos_que_puede_ejecutar(mod, fakes, perfil):
    # puede expulsar pero no banear ni borrar mensajes: solo salen kick (y warns, por ser moderador)
    ctx = ctx_de(mod, fakes, G_PSS, permisos=discord.Permissions(kick_members=True).value)
    await perfil.enviar_ayuda(ctx)
    moderacion = lineas(ctx.respuestas[0][1]["embed"])["🛡️ Moderación"]
    nombres = [x.split("`")[1].split()[0] for x in moderacion]
    assert "!kick" in nombres and "!ban" not in nombres and "!borrar" not in nombres and "!warns" in nombres


async def test_sin_la_mencion_resuelta_se_muestra_el_nombre_del_canal(mod, fakes, perfil):
    perfil.ids = {}
    ctx = ctx_de(mod, fakes, G_PSS)
    await perfil.enviar_ayuda(ctx)
    assert "#💡・sugerencias" in ctx.respuestas[0][1]["embed"].fields[1].value


async def test_sin_seccion_ayuda_el_perfil_lo_dice(mod, fakes, perfil):
    from dataclasses import replace
    perfil.config = replace(perfil.config, ayuda=None)
    ctx = ctx_de(mod, fakes, G_PSS)
    await perfil.enviar_ayuda(ctx)
    assert "no tiene ayuda configurada" in ctx.respuestas[0][0]


# --- 2. Validacion de [ayuda] ----------------------------------------------------------------------------------------
BASE = {
    "perfil": {"guild_id": 10},
    "comandos": {"bloquear": ["steam"]},
    "roles": [{"key": "miembro", "nombre": "Miembro"}],
    "categorias": [{"key": "cat", "nombre": "A", "orden": 1}],
    "canales": [{"key": "sugerencias", "nombre": "sugerencias", "categoria": "cat"}],
    "ayuda": {"titulo": "Ayuda", "secciones": [
        {"titulo": "S", "comandos": [{"comando": "ping", "texto": "pong"}]}]},
}


def datos(**ayuda):
    import copy
    d = copy.deepcopy(BASE)
    d["ayuda"].update(ayuda)
    return d


def errores(d):
    with pytest.raises(ConfigInvalida) as e:
        parsear(d)
    return "\n".join(e.value.errores)


def test_ayuda_valida_y_opcional():
    a = parsear(BASE).ayuda
    assert a.titulo == "Ayuda" and a.secciones[0].entradas[0].linea() == "`!ping` — pong"
    sin = {k: v for k, v in BASE.items() if k != "ayuda"}
    assert parsear(sin).ayuda is None


def test_un_comando_bloqueado_no_puede_salir_en_la_ayuda():
    d = datos(secciones=[{"titulo": "S", "comandos": [{"comando": "steam", "texto": "x"}]}])
    assert "steam" in errores(d) and "bloquear" in errores(d)


def test_comando_repetido_texto_obligatorio_y_nombre_con_exclamacion():
    d = datos(secciones=[{"titulo": "S", "comandos": [{"comando": "ping", "texto": "a"}, {"comando": "ping", "texto": "b"}]},
                         {"titulo": "T", "comandos": [{"comando": "!avatar", "texto": "c"}, {"comando": "kick"}]}])
    texto = errores(d)
    assert "repetido" in texto and "!avatar" in texto and "texto" in texto and "obligatorio" in texto


def test_secciones_vacias_claves_desconocidas_y_menciones_inexistentes():
    assert "al menos una seccion" in errores(datos(secciones=[]))
    assert "al menos un comando" in errores(datos(secciones=[{"titulo": "S", "comandos": []}]))
    assert "clave desconocida" in errores(datos(extra=1))
    d = datos(secciones=[{"titulo": "S", "comandos": [{"comando": "ping", "texto": "mira {canal:fantasma} y {rol:nadie}"}]}])
    texto = errores(d)
    assert "{canal:fantasma}" in texto and "{rol:nadie}" in texto


def test_limites_de_embed_de_la_ayuda():
    largo = [{"comando": f"c{i}", "texto": "x" * 290} for i in range(5)]       # >1024 caracteres en una seccion
    assert "maximo 1024" in errores(datos(secciones=[{"titulo": "S", "comandos": largo}]))


def test_los_comandos_de_la_ayuda_existen_en_el_bot(mod):
    config = cargar(RUTA)
    assert comandos_de_ayuda_inexistentes(config, mod.bot) == []
    d = datos(secciones=[{"titulo": "S", "comandos": [{"comando": "nopuede", "texto": "x"}]}])
    assert any("nopuede" in e for e in comandos_de_ayuda_inexistentes(parsear(d), mod.bot))
    # y los comandos bloqueados del TOML tambien existen en el bot (no hay erratas)
    assert [n for n in config.comandos_bloqueados if mod.bot.get_command(n) is None] == []


async def test_la_extension_no_carga_si_la_ayuda_nombra_un_comando_que_no_existe(sin_bd, tmp_path, monkeypatch):
    malo = tmp_path / "malo.toml"
    malo.write_text(RUTA.read_text(encoding="utf-8").replace('comando = "ping"', 'comando = "pingg"'), encoding="utf-8")
    monkeypatch.setenv("PSS_PROFILE_CONFIG", str(malo))
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    for nombre in ("ping", "avatar", "serverinfo", "miembros", "encuesta", "sugerencia", "borrar", "kick",
                   "ban", "mute", "unmute", "warn", "warns"):
        bot.command(name=nombre)(_comando_vacio)
    with pytest.raises(commands.ExtensionFailed) as e:
        await bot.load_extension("profiles.pss")
    assert "pingg" in str(e.value.original)
    await bot.close()


def test_el_contenido_inicial_de_la_ayuda_de_pss():
    ayuda = cargar(RUTA).ayuda
    contenido = {s.titulo: [e.comando for e in s.entradas] for s in ayuda.secciones}
    assert contenido == {
        "🎮 Comunidad": ["ping", "avatar", "serverinfo", "miembros", "nivel", "top"],
        "📊 Utilidad": ["encuesta", "sugerencia"],
        "🛡️ Moderación": ["borrar", "kick", "ban", "mute", "unmute", "warn", "warns", "permitir", "despermitir"],
        "⚙️ Administración": ["anuncio", "exportarserver", "setxp", "resetxp"],
    }
    assert not {e.comando for s in ayuda.secciones for e in s.entradas} & set(cargar(RUTA).comandos_bloqueados)
    assert [e.solo_moderadores for s in ayuda.secciones for e in s.entradas if e.comando == "warns"] == [True]
    assert "{canal:sugerencias}" in next(e.texto for s in ayuda.secciones for e in s.entradas if e.comando == "sugerencia")


# --- 4. Comandos bloqueados --------------------------------------------------------------------------------------------
def test_los_nuevos_comandos_estan_bloqueados_y_el_check_los_para(perfil, mod, fakes):
    for nombre in NUEVOS_BLOQUEADOS:
        assert nombre in perfil.config.comandos_bloqueados
        ctx = ctx_de(mod, fakes, G_PSS, comando=nombre)
        with pytest.raises(commands.CommandError) as e:
            perfil._bloquear_comando(ctx)
        assert not isinstance(e.value, commands.CheckFailure)
        assert str(e.value) == MSG_NO_DISPONIBLE == "Este comando no está disponible en este servidor."
        assert perfil._bloquear_comando(ctx_de(mod, fakes, OTRO, comando=nombre)) is True    # en EITO siguen igual


@pytest.mark.parametrize("nombre", NUEVOS_BLOQUEADOS)
async def test_lo_que_responde_cada_comando_bloqueado(mod, fakes, perfil, nombre):
    """Pasa el error del check por el manejador .error REAL del comando (y por el cog)."""
    ctx = ctx_de(mod, fakes, G_PSS, comando=nombre)
    with pytest.raises(commands.CommandError) as e:
        await mod.bot.get_command(nombre).can_run(ctx)             # el check global, tal cual
    # dispatch_error llama al manejador .error del comando y despues bot.dispatch("command_error"),
    # que el bot real reparte a los listeners: aqui se reparte a mano (sin bucle de eventos de Discord)
    eventos = []
    ctx.bot = types.SimpleNamespace(dispatch=lambda *a: eventos.append(a))
    await mod.bot.get_command(nombre).dispatch_error(ctx, e.value)
    assert [ev[0] for ev in eventos] == ["command_error"]
    await perfil.on_command_error(ctx, e.value)
    respuestas = [r[0] for r in ctx.respuestas]
    # todos tienen manejador propio: contesta el manejador (una vez) y el cog no repite.
    # Ninguno dice «solo el dueño o un DEVELOPER» (el de !fundadores lo decia con cualquier CheckFailure).
    assert mod.bot.get_command(nombre).has_error_handler()
    assert respuestas == ["❌ Error: Este comando no está disponible en este servidor."]


async def test_un_comando_bloqueado_sin_manejador_lo_responde_el_perfil_y_con_manejador_no_se_repite(perfil):
    enviados = []

    async def send(texto, **kw):
        enviados.append(texto)

    error = PssComandoBloqueado(MSG_NO_DISPONIBLE)
    sin = types.SimpleNamespace(has_error_handler=lambda: False)
    con = types.SimpleNamespace(has_error_handler=lambda: True)
    await perfil.on_command_error(types.SimpleNamespace(send=send, command=sin, cog=None), error)
    assert enviados == ["❌ Este comando no está disponible en este servidor."]
    await perfil.on_command_error(types.SimpleNamespace(send=send, command=con, cog=None), error)
    await perfil.on_command_error(types.SimpleNamespace(send=send, command=sin, cog=None), commands.CommandError("otro"))
    assert len(enviados) == 1


async def test_la_ayuda_no_dispara_respuestas_al_comprobar_comandos_bloqueados(mod, fakes, perfil):
    ctx = ctx_de(mod, fakes, G_PSS, permisos=MODERADOR)
    await perfil.enviar_ayuda(ctx)
    assert len(ctx.respuestas) == 1                                 # solo la ayuda, ni un «no disponible»


# --- 5. !pss ayuda -----------------------------------------------------------------------------------------------------
async def test_pss_ayuda_lista_los_seis_subcomandos_y_solo_para_gestores(mod, fakes, perfil):
    comando = perfil.pss.get_command("ayuda")
    assert comando is not None and comando.cog is perfil
    ctx = ctx_de(mod, fakes, G_PSS)
    await perfil.ayuda.callback(perfil, ctx)
    embed = ctx.respuestas[0][1]["embed"]
    lineas_ = [x for x in embed.description.split("\n") if x.startswith("`")]
    assert [x.split("`")[1] for x in lineas_] == [
        "!pss plan", "!pss aplicar", "!pss recargar", "!pss estado", "!pss olvidar <key>", "!pss ayuda"]
    assert len(AYUDA_PSS) == 6 and all(" — " in x for x in lineas_)       # una linea por comando
    # lo reutilizan los permisos de todo el cog: ni un miembro corriente ni otro servidor
    guild = types.SimpleNamespace(id=G_PSS, owner_id=1)
    corriente = types.SimpleNamespace(id=2, guild=guild, roles=[])
    with pytest.raises(PssSinPermiso):
        await perfil.cog_check(types.SimpleNamespace(guild=guild, author=corriente))
    with pytest.raises(PssNoAplica):
        await perfil.cog_check(types.SimpleNamespace(guild=types.SimpleNamespace(id=OTRO), author=corriente))
    dueno = types.SimpleNamespace(id=1, guild=guild, roles=[])
    assert await perfil.cog_check(types.SimpleNamespace(guild=guild, author=dueno)) is True


# --- can_run de un comando bloqueado: lo capturan todas las ayudas ---------------------------------------------------
async def test_can_run_de_un_comando_bloqueado_lanza_commanderror_y_las_dos_ayudas_lo_capturan(mod, fakes, perfil):
    from profiles.pss_config import EntradaAyuda
    ctx = ctx_de(mod, fakes, G_PSS, comando="ayuda")
    with pytest.raises(commands.CommandError):
        await mod.bot.get_command("steam").can_run(ctx)
    assert await mod.comando_visible(ctx, "steam") is False                       # la ayuda de EITO
    assert await perfil._entrada_visible(ctx, EntradaAyuda("steam", "x")) is False    # la de PSS
    assert await mod.comando_visible(ctx_de(mod, fakes, OTRO, comando="ayuda"), "steam") is True   # en EITO, igual
    assert len(ctx.respuestas) == 0                                                # sin ruido


@pytest.mark.parametrize("quien", ["dueno", "moderador"])
async def test_ayuda_en_pss_por_el_dueno_y_por_un_moderador_no_falla_ni_muestra_bloqueados(mod, fakes, perfil, quien):
    import re
    todos = discord.Permissions.all().value
    ctx = ctx_de(mod, fakes, G_PSS, permisos=todos if quien == "dueno" else MODERADOR)
    if quien == "dueno":
        ctx.guild.owner_id = ctx.author.id
    await mod.ayuda.callback(ctx)                                  # el comando real, con el gancho: no lanza nada
    assert len(ctx.respuestas) == 1
    embed = ctx.respuestas[0][1]["embed"]
    assert embed.title == "📖 Comandos de Phantom Shadows Studios"
    texto = " ".join(f.value for f in embed.fields)
    for bloqueado in perfil.config.comandos_bloqueados:
        assert not re.search(rf"!{bloqueado}\b", texto), bloqueado
    assert "no está disponible" not in texto and "Error" not in texto
    assert ("⚙️ Administración" in [f.name for f in embed.fields]) == (quien == "dueno")


# --- el log de errores de comandos: no se ensucia, y el de siempre se mantiene ----------------------------------------
def registros(caplog):
    return [(r.name, r.levelno, r.getMessage()) for r in caplog.records if r.name == "discord.ext.commands.bot"]


async def test_los_bloqueos_de_pss_no_ensucian_el_log_y_los_demas_errores_se_registran_como_siempre(
        mod, fakes, perfil, caplog):
    caplog.set_level(logging.ERROR, logger="discord.ext.commands.bot")
    ping, steam = mod.bot.get_command("ping"), mod.bot.get_command("steam")
    assert not ping.has_error_handler() and steam.has_error_handler()
    fallo = commands.CommandInvokeError(RuntimeError("boom"))
    bloqueo = PssComandoBloqueado(MSG_NO_DISPONIBLE)

    # Referencia: un bot SIN el perfil (el de siempre) registra un error cualquiera de un comando sin manejador
    limpio = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    await limpio.on_command_error(types.SimpleNamespace(command=ping, cog=None), fallo)
    referencia = registros(caplog)
    assert referencia == [("discord.ext.commands.bot", logging.ERROR, "Ignoring exception in command ping")]
    caplog.clear()
    await limpio.on_command_error(types.SimpleNamespace(command=steam, cog=None), fallo)   # con manejador: nada
    assert registros(caplog) == []
    await limpio.close()

    # Con el perfil cargado, el on_command_error por defecto de discord.py no corre (hay un listener)...
    assert mod.bot.extra_events.get("on_command_error")
    await mod.bot.on_command_error(types.SimpleNamespace(command=ping, cog=None), fallo)
    assert registros(caplog) == []
    # ...y el listener del perfil repite exactamente el mismo registro, solo para lo que no es un bloqueo
    async def send(*a, **k):
        raise AssertionError("no debe contestar")

    await perfil.on_command_error(types.SimpleNamespace(command=ping, cog=None, send=send), fallo)
    assert registros(caplog) == referencia
    caplog.clear()
    await perfil.on_command_error(types.SimpleNamespace(command=steam, cog=None, send=send), fallo)   # con manejador
    assert registros(caplog) == []
    # Los bloqueos de PSS: ni una linea en el log, con manejador o sin el
    enviados = []

    async def contesta(texto, **k):
        enviados.append(texto)

    sin_manejador = types.SimpleNamespace(has_error_handler=lambda: False)
    await perfil.on_command_error(types.SimpleNamespace(command=steam, cog=None, send=send), bloqueo)
    await perfil.on_command_error(types.SimpleNamespace(command=sin_manejador, cog=None, send=contesta), bloqueo)
    assert registros(caplog) == [] and enviados == ["❌ Este comando no está disponible en este servidor."]
