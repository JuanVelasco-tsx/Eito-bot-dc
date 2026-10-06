"""Anti-multicuentas: integracion del cog en el bot (registro, on_member_join, DM),
lectura de EDAD_MINIMA_DIAS, filtro y errores internos de los comandos."""

import os
import subprocess
import sys
import types
from datetime import timedelta
from pathlib import Path

import discord
import pytest
from discord.ext import commands

import anti_multicuentas
from anti_multicuentas import AntiMulticuentas


@pytest.fixture
async def cog(mod):
    """El cog registrado en el bot (como lo deja setup_hook)."""
    if mod.bot.get_cog("AntiMulticuentas") is None:
        await mod.bot.add_cog(AntiMulticuentas(mod.bot, mod.registrar_log))
    return mod.bot.get_cog("AntiMulticuentas")


class Miembro:
    """Miembro que entra al servidor: guarda los roles que se le dan."""

    def __init__(self, guild):
        self.guild, self.id, self.name, self.bot = guild, 7, "Nuevo", False
        self.mention = "<@7>"
        self.display_avatar = types.SimpleNamespace(url="https://cdn.test/avatar.png")
        self.roles_dados = []

    async def add_roles(self, *roles, reason=None):
        self.roles_dados.extend(roles)


@pytest.fixture
def entrada(mod, fakes, monkeypatch):
    """Servidor con rol automatico y canal de bienvenida; la BD de fundadores parcheada."""
    guild = fakes.Guild()
    guild.rol(int(mod.ROL_AUTOMATICO), "COMUNIDAD")
    bienvenida = guild.canal(mod.CANAL_BIENVENIDA)
    guild.member_count = 10

    async def get_fundador(*args):
        return None

    monkeypatch.setattr(mod, "get_fundador", get_fundador)
    return guild, bienvenida


def filtro_falso(mod, monkeypatch, resultado):
    """Sustituye el cog por uno cuyo filtro devuelve `resultado`."""
    llamados = []

    async def filtrar_miembro(member):
        llamados.append(member)
        return resultado

    falso = types.SimpleNamespace(filtrar_miembro=filtrar_miembro)
    monkeypatch.setattr(mod.bot, "get_cog", lambda nombre: falso if nombre == "AntiMulticuentas" else None)
    return llamados


async def test_cuenta_rechazada_no_recibe_rol_ni_bienvenida(mod, entrada, monkeypatch):
    guild, bienvenida = entrada
    llamados = filtro_falso(mod, monkeypatch, False)
    miembro = Miembro(guild)

    await mod.on_member_join(miembro)

    assert llamados == [miembro]
    assert miembro.roles_dados == []
    assert bienvenida.enviados == []


async def test_cuenta_aceptada_sigue_el_flujo_normal(mod, entrada, monkeypatch):
    guild, bienvenida = entrada
    filtro_falso(mod, monkeypatch, True)
    miembro = Miembro(guild)

    await mod.on_member_join(miembro)

    assert [r.name for r in miembro.roles_dados] == ["COMUNIDAD"]
    assert len(bienvenida.enviados) == 1


async def test_sin_cog_la_entrada_funciona_igual(mod, entrada, monkeypatch):
    guild, bienvenida = entrada
    monkeypatch.setattr(mod.bot, "get_cog", lambda nombre: None)
    miembro = Miembro(guild)

    await mod.on_member_join(miembro)

    assert len(bienvenida.enviados) == 1


# --- Registro en setup_hook -------------------------------------------------------------
async def test_setup_hook_registra_el_cog_una_sola_vez(mod, monkeypatch):
    async def nada():
        return None

    monkeypatch.setattr(mod, "crear_tablas", nada)
    monkeypatch.setattr(mod, "start_web_server", nada)
    monkeypatch.setattr(mod.bot, "add_view", lambda vista: None)
    for nombre in ("premiar_activo_mes", "actualizar_rangos",
                   "cerrar_convocatorias_vencidas", "contar_voz"):
        monkeypatch.setattr(getattr(mod, nombre), "start", lambda: None)

    await mod.setup_hook()
    await mod.setup_hook()  # no debe fallar con "Cog already loaded"
    await mod.tarea_web

    assert isinstance(mod.bot.get_cog("AntiMulticuentas"), AntiMulticuentas)
    assert mod.bot.get_command("permitir") is not None
    assert mod.bot.get_command("despermitir") is not None


# --- Mensajes privados: un solo aviso, en español ----------------------------------------
@pytest.mark.parametrize("nombre", ["permitir", "despermitir"])
async def test_en_mensaje_privado_responde_una_sola_vez_en_espanol(mod, fakes, cog, nombre, monkeypatch):
    comando = mod.bot.get_command(nombre)
    assert comando.cog is cog
    ctx = fakes.Ctx(guild=None, comando=comando)
    ctx.bot = mod.bot  # Command.can_run / dispatch_error usan ctx.bot
    # Sin conexion el bot no tiene loop para despachar eventos: se registran
    despachados = []
    monkeypatch.setattr(mod.bot, "dispatch", lambda evento, *args: despachados.append(evento))

    # Mismo camino que discord.py: prepare() -> can_run() falla -> dispatch_error()
    with pytest.raises(commands.NoPrivateMessage) as error:
        await comando.can_run(ctx)
    await comando.dispatch_error(ctx, error.value)
    # ...y el on_command_error global, que es lo que habria despachado
    assert despachados == ["command_error"]
    await mod.bot.on_command_error(ctx, error.value)

    assert [texto for texto, _kw in ctx.respuestas] == [
        "❌ Este comando solo funciona en el servidor."
    ]


# --- Permisos: Moderar miembros (Helper solo tiene Expulsar) ------------------------------
def ctx_con_permisos(fakes, comando, **permisos):
    ctx = fakes.Ctx(guild=fakes.Guild(), comando=comando)
    ctx.bot = comando.cog.bot  # Command.can_run usa ctx.bot
    ctx.permissions = discord.Permissions(**permisos)  # lo que lee has_permissions
    return ctx


@pytest.mark.parametrize("nombre", ["permitir", "despermitir"])
async def test_con_expulsar_pero_sin_moderar_no_puede_usarlo(mod, fakes, cog, nombre):
    comando = mod.bot.get_command(nombre)
    ctx = ctx_con_permisos(fakes, comando, kick_members=True)  # como Helper

    with pytest.raises(commands.MissingPermissions) as error:
        await comando.can_run(ctx)
    await cog.cog_command_error(ctx, error.value)

    assert ctx.respuestas[0][0] == "❌ Necesitas el permiso de Moderar miembros."
    assert await mod.comando_visible(ctx, nombre) is False  # tampoco sale en !ayuda


@pytest.mark.parametrize("nombre", ["permitir", "despermitir"])
async def test_con_moderar_miembros_puede_usarlo(mod, fakes, cog, nombre):
    comando = mod.bot.get_command(nombre)
    ctx = ctx_con_permisos(fakes, comando, moderate_members=True)  # como Admins / Moderador

    assert await comando.can_run(ctx) is True
    assert await mod.comando_visible(ctx, nombre) is True
    assert ctx.respuestas == []


def test_ayuda_lista_permitir_y_despermitir_en_moderacion(mod):
    moderacion = dict(mod.AYUDA_SECCIONES)["🛡️ Moderación"]
    nombres = [nombre for nombre, _texto, _cond in moderacion]
    assert nombres[-2:] == ["permitir", "despermitir"]


# --- EDAD_MINIMA_DIAS: nunca impide arrancar ----------------------------------------------
@pytest.mark.parametrize("valor, esperado, avisa", [
    (None, 7, False),       # sin variable
    ("", 7, False),         # vacia
    ("10", 10, False),
    ("0", 0, False),        # 0 = filtro desactivado
    ("-3", 7, True),        # negativa
    ("7 dias", 7, True),    # no numerica
])
def test_leer_edad_minima(monkeypatch, capsys, valor, esperado, avisa):
    if valor is None:
        monkeypatch.delenv("EDAD_MINIMA_DIAS", raising=False)
    else:
        monkeypatch.setenv("EDAD_MINIMA_DIAS", valor)

    assert anti_multicuentas._leer_edad_minima() == esperado

    salida = capsys.readouterr().out
    if avisa:
        assert repr(valor) in salida  # el aviso muestra el valor recibido
    else:
        assert salida == ""


def test_un_valor_invalido_no_impide_importar_el_modulo():
    # Proceso aparte: importa el modulo desde cero, como al arrancar el bot en Railway
    entorno = {**os.environ, "EDAD_MINIMA_DIAS": "7 dias", "PYTHONIOENCODING": "utf-8"}
    resultado = subprocess.run(
        [sys.executable, "-c", "import anti_multicuentas as m; print(m.EDAD_MINIMA_DIAS)"],
        cwd=Path(__file__).resolve().parent.parent, env=entorno,
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.strip().splitlines()[-1] == "7"


# --- Filtro -------------------------------------------------------------------------------
class Entrante:
    """Miembro que acaba de entrar: registra DMs y expulsiones."""

    def __init__(self, guild, edad):
        self.guild, self.id, self.name, self.bot = guild, 8, "Recien", False
        self.created_at = discord.utils.utcnow() - edad
        self.dms, self.expulsado = [], False

    def __str__(self):
        return self.name

    async def send(self, **kwargs):
        self.dms.append(kwargs)

    async def kick(self, reason=None):
        self.expulsado = True


@pytest.fixture
def filtro(fakes, monkeypatch):
    """Cog suelto (sin registrar) con la BD de permitidos y los logs parcheados."""
    logs = []

    async def registrar_log(guild, texto):
        logs.append(texto)

    async def no_permitido(*args):
        return False

    monkeypatch.setattr(anti_multicuentas, "es_usuario_permitido", no_permitido)
    return AntiMulticuentas(bot=None, registrar_log=registrar_log), fakes.Guild(), logs


async def test_con_edad_minima_7_una_cuenta_nueva_se_expulsa(filtro, monkeypatch):
    cog, guild, logs = filtro
    monkeypatch.setattr(anti_multicuentas, "EDAD_MINIMA_DIAS", 7)
    miembro = Entrante(guild, timedelta(0))

    assert await cog.filtrar_miembro(miembro) is False
    assert miembro.expulsado and len(miembro.dms) == 1 and len(logs) == 1


@pytest.mark.parametrize("edad", [
    timedelta(0),             # cuenta de 0 dias
    -timedelta(seconds=5),    # reloj del bot un poco por detras de Discord
])
async def test_con_edad_minima_0_todas_las_cuentas_pasan(filtro, monkeypatch, edad):
    cog, guild, logs = filtro
    monkeypatch.setattr(anti_multicuentas, "EDAD_MINIMA_DIAS", 0)
    miembro = Entrante(guild, edad)

    assert await cog.filtrar_miembro(miembro) is True
    assert not miembro.expulsado and miembro.dms == [] and logs == []


# --- Errores internos: mensaje generico al usuario, detalle a consola ---------------------
async def test_si_la_bd_falla_en_permitir_no_se_muestra_el_error(mod, fakes, cog, monkeypatch, capsys):
    secreto = "password authentication failed for user postgres"

    async def bd_caida(*args):
        raise ConnectionError(secreto)

    async def buscar_usuario(user_id):
        return fakes.Usuario(user_id, "Nuevo")

    monkeypatch.setattr(anti_multicuentas, "permitir_usuario", bd_caida)
    monkeypatch.setattr(cog, "_buscar_usuario", buscar_usuario)
    comando = mod.bot.get_command("permitir")
    ctx = fakes.Ctx(guild=fakes.Guild(), comando=comando)

    # Como discord.py: la excepcion del callback llega envuelta en CommandInvokeError
    with pytest.raises(ConnectionError) as error:
        await comando.callback(cog, ctx, 123)
    await cog.cog_command_error(ctx, commands.CommandInvokeError(error.value))

    textos = [texto for texto, _kw in ctx.respuestas]
    assert textos == ["❌ No pude completar la acción. Inténtalo de nuevo en un rato."]
    assert not any(secreto in texto for texto in textos)
    assert secreto in capsys.readouterr().out  # el detalle queda en los logs
