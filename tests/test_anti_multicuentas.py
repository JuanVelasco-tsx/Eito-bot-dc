"""Anti-multicuentas: integracion del cog en el bot (registro, on_member_join, DM)."""

import types

import discord
import pytest
from discord.ext import commands

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
