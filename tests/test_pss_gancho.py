"""Ganchos del bot principal hacia el perfil PSS y el cog PerfilPSS (sin Discord ni BD).

Lo mas importante: con el perfil sin cargar, el bot se comporta exactamente como antes."""

import types
from dataclasses import replace
from pathlib import Path

import discord
import pytest
from discord.ext import commands

from profiles import pss, pss_db
from profiles.pss import ConfirmarAplicar, PanelEspecialidades, PerfilPSS, PssNoAplica, PssSinPermiso
from profiles.pss_config import cargar
from profiles.pss_plan import Accion, Plan

RUTA = Path(__file__).resolve().parent.parent / "profiles" / "pss.toml"
G_PSS = 1420403964746268684
OTRO = 5


@pytest.fixture
def config():
    return cargar(RUTA)


def con_eventos(config, **cambios):
    return replace(config, eventos=replace(config.eventos, **cambios))


@pytest.fixture
def cog(config):
    bot = types.SimpleNamespace(get_cog=lambda nombre: None)
    return PerfilPSS(bot, config, RUTA)


class FTexto(discord.TextChannel):
    """TextChannel real (para los isinstance) que guarda lo que se envia."""

    def __init__(self, id):
        self.id = id
        self.enviados = []

    async def send(self, content=None, **kwargs):
        self.enviados.append((content, kwargs))


class FGuild:
    def __init__(self, id=G_PSS, owner_id=1):
        self.id, self.owner_id, self.member_count = id, owner_id, 6
        self.name = "PSS"
        self.roles, self.canales = {}, {}

    def get_role(self, id):
        return self.roles.get(id)

    def get_channel(self, id):
        return self.canales.get(id)


class FMiembro:
    def __init__(self, guild, id=2, roles=(), bot=False):
        self.guild, self.id, self.bot, self.roles = guild, id, bot, list(roles)
        self.mention = f"<@{id}>"
        self.display_avatar = types.SimpleNamespace(url="https://cdn/a.png")
        self.agregados = []

    async def add_roles(self, *roles, reason=None):
        self.agregados.extend(roles)


# --- Sin perfil cargado: todo igual que antes ----------------------------------------------------
def test_el_perfil_esta_apagado_por_defecto(mod):
    assert mod.PSS_PROFILE_ENABLED is False
    assert mod.bot.get_cog("PerfilPSS") is None
    assert mod.evento_permitido(object(), "xp") is True and mod.evento_permitido(object(), "voz") is True


async def test_registrar_log_sin_perfil_busca_el_canal_de_eito(mod, fakes):
    guild = fakes.Guild()
    canal = guild.canal(mod.CANAL_LOGS)
    await mod.registrar_log(guild, "hola")
    assert canal.enviados == [("hola", {})]


async def test_sumar_xp_sin_perfil_sigue_funcionando(mod, fakes, monkeypatch):
    llamadas = []

    async def get_xp(g, u):
        llamadas.append("get")
        return 0

    async def add_xp(g, u, c):
        return 15

    async def add_mensual(*a):
        return 15

    monkeypatch.setattr(mod, "get_user_xp", get_xp)
    monkeypatch.setattr(mod, "add_user_xp", add_xp)
    monkeypatch.setattr(mod, "add_xp_mensual", add_mensual)
    miembro = fakes.Usuario(1)
    miembro.guild = fakes.Guild()
    assert await mod.sumar_xp(miembro, 15) == 15 and llamadas == ["get"]


# --- Con un perfil que desactiva cosas -----------------------------------------------------------------
class PerfilFalso:
    def __init__(self, maneja=True, permitidos=()):
        self._maneja, self.permitidos, self.entradas, self.canal = maneja, set(permitidos), [], None

    def maneja(self, guild):
        return self._maneja

    def permite(self, guild, evento):
        return evento in self.permitidos

    def canal_logs(self, guild):
        return self.canal

    async def al_entrar(self, member):
        self.entradas.append(member)


@pytest.fixture
def con_perfil(mod, monkeypatch):
    perfil = PerfilFalso()
    original = mod.bot.get_cog
    monkeypatch.setattr(mod.bot, "get_cog", lambda n: perfil if n == "PerfilPSS" else original(n))
    return perfil


async def test_sumar_xp_no_hace_nada_si_el_perfil_la_apaga(mod, con_perfil, monkeypatch):
    async def prohibido(*a):
        raise AssertionError("no debe tocar la BD")

    monkeypatch.setattr(mod, "get_user_xp", prohibido)
    miembro = types.SimpleNamespace(guild=object(), id=1)
    assert await mod.sumar_xp(miembro, 15) == 0


async def test_contar_voz_guild_sale_antes_de_recorrer_canales(mod, con_perfil):
    class Guild:
        @property
        def afk_channel(self):
            raise AssertionError("no debe recorrer la voz")

    await mod.contar_voz_guild(Guild())


async def test_on_member_join_delega_en_el_perfil_y_no_aplica_el_filtro_de_eito(mod, con_perfil, monkeypatch):
    class AntiFalso:
        async def filtrar_miembro(self, m):
            raise AssertionError("el filtro de EITO no debe correr: lo decide el perfil")

    original = mod.bot.get_cog
    monkeypatch.setattr(mod.bot, "get_cog", lambda n: AntiFalso() if n == "AntiMulticuentas" else (con_perfil if n == "PerfilPSS" else original(n)))
    miembro = types.SimpleNamespace(guild=object())
    await mod.on_member_join(miembro)
    assert con_perfil.entradas == [miembro]


async def test_on_member_join_en_otro_servidor_sigue_el_camino_de_eito(mod, con_perfil, monkeypatch, fakes):
    con_perfil._maneja = False
    visto = []

    class AntiFalso:
        async def filtrar_miembro(self, m):
            visto.append(m)
            return False       # cuenta nueva: se expulsa y no se sigue

    original = mod.bot.get_cog
    monkeypatch.setattr(mod.bot, "get_cog", lambda n: AntiFalso() if n == "AntiMulticuentas" else (con_perfil if n == "PerfilPSS" else original(n)))
    miembro = types.SimpleNamespace(guild=fakes.Guild())
    await mod.on_member_join(miembro)
    assert visto == [miembro] and con_perfil.entradas == []


async def test_registrar_log_usa_el_canal_del_perfil_y_si_no_hay_el_de_eito(mod, con_perfil, fakes):
    guild = fakes.Guild()
    de_eito = guild.canal(mod.CANAL_LOGS)
    del_perfil = guild.canal("registros")
    con_perfil.canal = del_perfil
    await mod.registrar_log(guild, "uno")
    assert del_perfil.enviados == [("uno", {})] and de_eito.enviados == []
    con_perfil.canal = None
    await mod.registrar_log(guild, "dos")
    assert de_eito.enviados == [("dos", {})]


# --- setup_hook ---------------------------------------------------------------------------------------------
@pytest.fixture
def arranque(mod, monkeypatch):
    cargadas = []

    async def sin_tablas():
        return None

    async def sin_web():
        return None

    async def load_extension(nombre):
        cargadas.append(nombre)

    monkeypatch.setattr(mod, "crear_tablas", sin_tablas)
    monkeypatch.setattr(mod, "start_web_server", sin_web)
    monkeypatch.setattr(mod.bot, "add_view", lambda v: None)
    monkeypatch.setattr(mod.bot, "load_extension", load_extension)
    for nombre in ("premiar_activo_mes", "actualizar_rangos", "cerrar_convocatorias_vencidas", "contar_voz"):
        monkeypatch.setattr(getattr(mod, nombre), "start", lambda: None)
    return cargadas


async def test_setup_hook_no_carga_el_perfil_si_la_variable_no_esta(mod, arranque, monkeypatch):
    monkeypatch.setattr(mod, "PSS_PROFILE_ENABLED", False)
    await mod.setup_hook()
    await mod.tarea_web
    assert arranque == []


async def test_setup_hook_carga_el_perfil_si_la_variable_esta(mod, arranque, monkeypatch):
    monkeypatch.setattr(mod, "PSS_PROFILE_ENABLED", True)
    await mod.setup_hook()
    await mod.tarea_web
    assert arranque == ["profiles.pss"]


async def test_si_el_perfil_falla_el_bot_arranca_igual(mod, arranque, monkeypatch, capsys):
    async def falla(nombre):
        raise RuntimeError("TOML roto")

    monkeypatch.setattr(mod, "PSS_PROFILE_ENABLED", True)
    monkeypatch.setattr(mod.bot, "load_extension", falla)
    iniciados = []
    monkeypatch.setattr(mod.contar_voz, "start", lambda: iniciados.append("voz"))
    await mod.setup_hook()                      # no debe propagar
    await mod.tarea_web
    assert "El perfil PSS no pudo cargarse" in capsys.readouterr().out
    assert iniciados == ["voz"]                 # los loops arrancan despues


# --- Cog: eventos y API ---------------------------------------------------------------------------------------------
def test_maneja_y_permite(cog):
    pss_guild, otro = FGuild(G_PSS), FGuild(OTRO)
    assert cog.maneja(pss_guild) and not cog.maneja(otro) and not cog.maneja(None)
    assert cog.permite(pss_guild, "xp") is False and cog.permite(pss_guild, "voz") is False
    assert cog.permite(pss_guild, "anti_multicuentas") is True       # PSS es publico: el filtro se aplica
    assert cog.permite(otro, "xp") is True and cog.permite(otro, "anti_multicuentas") is True
    assert cog.permite(pss_guild, "lo_que_sea") is True


async def test_al_entrar_con_anti_multicuentas_apagado_da_el_rol_y_bienvenida(cog, config):
    cog.config = con_eventos(config, anti_multicuentas=False)
    guild = FGuild()
    rol, general = types.SimpleNamespace(id=70, name="Miembro"), FTexto(80)
    guild.roles[70], guild.canales[80] = rol, general
    cog.ids = {"miembro": 70, "general": 80}
    cog.bot.get_cog = lambda n: (_ for _ in ()).throw(AssertionError("no debe consultar el filtro"))
    miembro = FMiembro(guild)
    await cog.al_entrar(miembro)
    assert miembro.agregados == [rol]
    assert len(general.enviados) == 1 and "<@2>" in general.enviados[0][1]["embed"].description


async def test_al_entrar_con_anti_multicuentas_activado_respeta_su_decision(cog, config):
    assert cog.config.eventos.anti_multicuentas is True              # es lo que trae pss.toml
    guild = FGuild()
    guild.roles[70] = types.SimpleNamespace(id=70, name="Miembro")
    cog.ids = {"miembro": 70}
    decisiones = iter([False, True])
    llamadas = []

    class Anti:
        async def filtrar_miembro(self, m):
            llamadas.append(m)
            return next(decisiones)

    cog.bot.get_cog = lambda n: Anti() if n == "AntiMulticuentas" else None
    expulsado, valido = FMiembro(guild, 2), FMiembro(guild, 3)
    await cog.al_entrar(expulsado)
    await cog.al_entrar(valido)
    assert llamadas == [expulsado, valido]
    assert expulsado.agregados == [] and len(valido.agregados) == 1


async def test_al_entrar_en_pss_expulsa_cuentas_nuevas_sin_dar_rol_ni_bienvenida(cog):
    """Con el pss.toml real: el filtro de EITO decide primero y, si expulsa, no hay rol ni bienvenida."""
    guild = FGuild()
    general = FTexto(80)
    guild.roles[70], guild.canales[80] = types.SimpleNamespace(id=70, name="Miembro"), general
    cog.ids = {"miembro": 70, "general": 80}

    class Anti:
        async def filtrar_miembro(self, m):
            return False

    cog.bot.get_cog = lambda n: Anti() if n == "AntiMulticuentas" else None
    nuevo = FMiembro(guild)
    await cog.al_entrar(nuevo)
    assert nuevo.agregados == [] and general.enviados == []


async def test_al_entrar_ignora_bots(cog):
    guild = FGuild()
    bot_nuevo = FMiembro(guild, 9, bot=True)
    cog.ids = {"miembro": 70}
    guild.roles[70] = types.SimpleNamespace(id=70)
    await cog.al_entrar(bot_nuevo)
    assert bot_nuevo.agregados == []


async def test_al_entrar_sin_rol_creado_no_falla(cog, capsys):
    miembro = FMiembro(FGuild())
    await cog.al_entrar(miembro)
    assert "aún no existe" in capsys.readouterr().out


def test_canal_logs_solo_en_pss_y_solo_si_es_de_texto(cog):
    guild, otro = FGuild(G_PSS), FGuild(OTRO)
    registros = FTexto(90)
    guild.canales[90] = registros
    cog.ids = {"registros": 90}
    assert cog.canal_logs(guild) is registros
    assert cog.canal_logs(otro) is None
    guild.canales[90] = types.SimpleNamespace(id=90)       # no es TextChannel
    assert cog.canal_logs(guild) is None
    cog.ids = {}
    assert cog.canal_logs(guild) is None


# --- Cog: bloqueo de comandos y permisos ------------------------------------------------------------------------------
def ctx_de(guild, comando):
    return types.SimpleNamespace(guild=guild, command=types.SimpleNamespace(qualified_name=comando))


def test_bloqueo_de_comandos_de_eito_solo_en_pss(cog):
    for nombre in ("setup", "info", "paneltickets", "panelroles", "reglas", "crearvcs"):
        with pytest.raises(commands.CheckFailure) as e:
            cog._bloquear_comando(ctx_de(FGuild(G_PSS), nombre))
        assert "no está disponible" in str(e.value)
        assert cog._bloquear_comando(ctx_de(FGuild(OTRO), nombre)) is True    # en EITO siguen igual
    for neutral in ("ping", "kick", "ban", "encuesta", "sugerencia", "nivel", "top", "ayuda", "warn", "exportarserver"):
        assert cog._bloquear_comando(ctx_de(FGuild(G_PSS), neutral)) is True
    assert cog._bloquear_comando(types.SimpleNamespace(guild=None, command=None)) is True


async def test_cog_check_solo_dueno_o_gestores_y_silencio_fuera_de_pss(cog, config):
    ctx = types.SimpleNamespace(guild=FGuild(OTRO), author=FMiembro(FGuild(OTRO)))
    with pytest.raises(PssNoAplica):
        await cog.cog_check(ctx)
    with pytest.raises(PssNoAplica):
        await cog.cog_check(types.SimpleNamespace(guild=None, author=None))
    guild = FGuild(G_PSS, owner_id=1)
    with pytest.raises(PssSinPermiso):
        await cog.cog_check(types.SimpleNamespace(guild=guild, author=FMiembro(guild, 2)))
    assert await cog.cog_check(types.SimpleNamespace(guild=guild, author=FMiembro(guild, 1))) is True
    # un gestor del TOML
    cog.config = replace(config, gestores=("colaborador",))
    cog.ids = {"colaborador": 60}
    gestor = FMiembro(guild, 3, roles=[types.SimpleNamespace(id=60)])
    assert await cog.cog_check(types.SimpleNamespace(guild=guild, author=gestor)) is True


async def test_errores_fuera_de_pss_no_responden_nada(cog):
    enviados = []

    async def send(*a, **k):
        enviados.append(a)

    ctx = types.SimpleNamespace(send=send, command=types.SimpleNamespace(qualified_name="pss plan"))
    await cog.cog_command_error(ctx, PssNoAplica())
    await cog.cog_command_error(ctx, commands.NoPrivateMessage())
    assert enviados == []
    await cog.cog_command_error(ctx, PssSinPermiso("nope"))
    assert enviados


# --- Vistas -------------------------------------------------------------------------------------------------------------------
async def test_los_custom_id_del_perfil_llevan_el_prefijo_pss(cog):
    panel = PanelEspecialidades(cog, ["scripter", "builder", "ui"])
    assert [b.custom_id for b in panel.children] == ["pss::rol::scripter", "pss::rol::builder", "pss::rol::ui"]
    assert panel.timeout is None
    confirmar = ConfirmarAplicar(cog, 1, "h")
    assert confirmar.timeout == 60
    assert all(b.custom_id.startswith("pss::") for b in confirmar.children)
    assert not any(b.custom_id.startswith("rol::") for b in panel.children)


async def test_solo_quien_invoco_puede_confirmar(cog):
    vista = ConfirmarAplicar(cog, autor_id=1, huella="h")
    respuestas = []

    async def send_message(texto, ephemeral=False):
        respuestas.append(texto)

    ajeno = types.SimpleNamespace(user=types.SimpleNamespace(id=2), response=types.SimpleNamespace(send_message=send_message))
    assert await vista.interaction_check(ajeno) is False and respuestas
    propio = types.SimpleNamespace(user=types.SimpleNamespace(id=1), response=None)
    assert await vista.interaction_check(propio) is True


class FMensajeBot:
    def __init__(self):
        self.ediciones = []
        self.channel = types.SimpleNamespace(send=self._enviar)
        self.enviados = []

    async def _enviar(self, **k):
        self.enviados.append(k)

    async def edit(self, **k):
        self.ediciones.append(k)


async def test_si_no_se_obtiene_el_lock_responde_que_ya_hay_una_aplicacion(cog, monkeypatch):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def sin_lock(guild_id):
        yield False

    async def prohibido(guild):
        raise AssertionError("no debe calcular ni aplicar sin el lock")

    monkeypatch.setattr(pss_db, "lock_aplicar", sin_lock)
    monkeypatch.setattr(cog, "_calcular", prohibido)
    msg = FMensajeBot()
    await cog.aplicar_confirmado(msg, FGuild(), "h")
    assert "ya hay una aplicación en curso" in msg.ediciones[-1]["content"].lower()


async def test_si_el_plan_cambio_entre_el_resumen_y_el_boton_no_se_aplica(cog, monkeypatch):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def con_lock(guild_id):
        yield True

    async def calcular(guild):
        return types.SimpleNamespace(huella=lambda: "otra"), {}

    async def prohibido(*a, **k):
        raise AssertionError("no debe ejecutar")

    monkeypatch.setattr(pss_db, "lock_aplicar", con_lock)
    monkeypatch.setattr(cog, "_calcular", calcular)
    monkeypatch.setattr(pss, "ejecutar", prohibido)
    msg = FMensajeBot()
    await cog.aplicar_confirmado(msg, FGuild(), "la_que_vio")
    assert "plan cambió" in msg.ediciones[-1]["content"]


async def test_boton_de_especialidad_no_da_roles_elevados(cog):
    guild = FGuild()
    elevado = types.SimpleNamespace(id=70, name="Scripter", permissions=discord.Permissions(manage_roles=True))
    guild.roles[70] = elevado
    cog.ids = {"scripter": 70}
    respuestas = []

    async def send_message(texto, ephemeral=False):
        respuestas.append(texto)

    usuario = FMiembro(guild)
    interaccion = types.SimpleNamespace(guild=guild, user=usuario, response=types.SimpleNamespace(send_message=send_message))
    await cog.alternar_especialidad(interaccion, "scripter")
    assert usuario.agregados == [] and "no se puede autoasignar" in respuestas[0]
    # un rol de otro servidor tampoco
    interaccion.guild = FGuild(OTRO)
    await cog.alternar_especialidad(interaccion, "scripter")
    assert usuario.agregados == [] and "no está disponible" in respuestas[1]


# --- Carga real como extension y comandos !pss ---------------------------------------------------------------
@pytest.fixture
def sin_bd_del_perfil(monkeypatch):
    async def nada(*a, **k):
        return None

    async def mapa(guild_id):
        return {}

    monkeypatch.setattr(pss_db, "asegurar_tabla", nada)
    monkeypatch.setattr(pss_db, "cargar_mapa", mapa)


async def test_la_extension_carga_en_un_bot_real_y_se_descarga_limpia(sin_bd_del_perfil, capsys):
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    checks_antes = len(bot._checks)
    await bot.load_extension("profiles.pss")
    # load_extension ejecuta el modulo otra vez, asi que la clase no es la importada arriba
    assert type(bot.get_cog("PerfilPSS")).__name__ == "PerfilPSS"
    assert {c.qualified_name for c in bot.walk_commands()} >= {
        "pss", "pss plan", "pss aplicar", "pss recargar", "pss estado", "pss olvidar"}
    assert len(bot._checks) == checks_antes + 1          # el check que bloquea comandos de EITO
    assert "Perfil PSS cargado" in capsys.readouterr().out
    await bot.unload_extension("profiles.pss")
    assert bot.get_cog("PerfilPSS") is None and len(bot._checks) == checks_antes
    await bot.close()


async def test_un_toml_invalido_impide_cargar_la_extension_con_todos_los_errores(monkeypatch, tmp_path):
    malo = tmp_path / "malo.toml"
    malo.write_text('[perfil]\nguild_id = 1\n[[roles]]\nkey = "a"\nnombre = "A"\npermisos = ["nope"]\n'
                    '[[canales]]\nkey = "c"\nnombre = "c"\ncategoria = "falta"\n', encoding="utf-8")
    monkeypatch.setenv("PSS_PROFILE_CONFIG", str(malo))
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    with pytest.raises(commands.ExtensionFailed) as e:
        await bot.load_extension("profiles.pss")
    texto = str(e.value.original)
    assert "nope" in texto and "falta" in texto
    assert bot.get_cog("PerfilPSS") is None
    await bot.close()


class CtxPlan:
    author = types.SimpleNamespace(id=1)

    def __init__(self, guild):
        self.guild, self.enviados = guild, []

    def typing(self):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _():
            yield

        return _()

    async def send(self, content=None, **kw):
        self.enviados.append((content, kw))
        return types.SimpleNamespace(edit=None)


async def test_pss_plan_envia_el_reporte_con_el_orden_de_despliegue(cog, monkeypatch):
    from profiles.pss_plan import Accion, Plan

    plan = Plan(acciones=[Accion("rol", "miembro", "omitir", "Miembro"),
                          Accion("rol", "ui", "crear", "UI")])

    async def calcular(guild):
        return plan, {}

    monkeypatch.setattr(cog, "_calcular", calcular)
    ctx = CtxPlan(FGuild())
    await cog.plan.callback(cog, ctx)
    embeds = [kw["embed"] for _c, kw in ctx.enviados]
    assert "no se tocó nada" in embeds[0].title
    assert "1099780189270" in embeds[-1].fields[0].value and "d)" in embeds[-1].fields[0].value


@pytest.mark.parametrize("otras", [[Accion("rol", "x", "bloqueado", "X", razon="r")],
                                   [Accion("rol", "x", "vincular", "X")]])
async def test_pss_plan_con_algo_pendiente_o_bloqueado_sigue_mostrando_el_orden_de_despliegue(cog, monkeypatch, otras):
    plan = Plan(acciones=[Accion("rol", "miembro", "omitir", "Miembro"), *otras])

    async def calcular(guild):
        return plan, {}

    monkeypatch.setattr(cog, "_calcular", calcular)
    ctx = CtxPlan(FGuild())
    await cog.plan.callback(cog, ctx)
    campo = ctx.enviados[-1][1]["embed"].fields[0].value
    assert "Orden de despliegue" in campo and "coincide" not in campo


@pytest.mark.parametrize("comando", ["plan", "aplicar"])
async def test_pss_con_todo_en_omitir_dice_que_el_servidor_coincide_y_no_el_orden_de_despliegue(cog, monkeypatch, comando):
    plan = Plan(acciones=[Accion("rol", "miembro", "omitir", "Miembro"), Accion("canal", "general", "omitir", "general")],
                manuales=["Categoría «🟥 Roblox»: queda **vacía**; bórrala a mano"])

    async def calcular(guild):
        return plan, {}

    monkeypatch.setattr(cog, "_calcular", calcular)
    ctx = CtxPlan(FGuild())
    await getattr(cog, comando).callback(cog, ctx)
    embed = ctx.enviados[-1][1]["embed"]
    assert embed.fields[0].value == "✅ El servidor coincide con la configuración"
    assert not any("Orden de despliegue" in (f.value or "") for _c, kw in ctx.enviados for f in kw["embed"].fields)
    assert "Roblox" in "".join(kw["embed"].description or "" for _c, kw in ctx.enviados)    # lo manual se sigue listando


async def test_pss_aplicar_sin_pendientes_no_pide_confirmacion(cog, monkeypatch):
    from profiles.pss_plan import Accion, Plan

    async def calcular(guild):
        return Plan(acciones=[Accion("rol", "miembro", "omitir", "Miembro")]), {}

    monkeypatch.setattr(cog, "_calcular", calcular)
    ctx = CtxPlan(FGuild())
    await cog.aplicar.callback(cog, ctx)
    assert all("view" not in kw for _c, kw in ctx.enviados)
    assert "Nada que aplicar" in ctx.enviados[0][1]["embed"].title


async def test_pss_aplicar_con_pendientes_pide_confirmacion_a_quien_lo_invoco(cog, monkeypatch):
    from profiles.pss_plan import Accion, Plan

    plan = Plan(acciones=[Accion("canal", "frontend", "actualizar", "frontend: mover", cambios={"mover": "cat_desarrollo"}),
                          Accion("rol", "x", "bloqueado", "X", razon="el bot no tiene manage_guild")])

    async def calcular(guild):
        return plan, {}

    monkeypatch.setattr(cog, "_calcular", calcular)
    ctx = CtxPlan(FGuild())
    await cog.aplicar.callback(cog, ctx)
    _contenido, kw = ctx.enviados[-1]
    assert isinstance(kw["view"], ConfirmarAplicar) and kw["view"].autor_id == 1
    assert kw["view"].huella == plan.huella()
    assert "frontend" in kw["embed"].description and "manage_guild" in kw["embed"].description
    assert "No se borran canales, categorías ni roles." in kw["embed"].description
    assert "Nada se borra" not in kw["embed"].description
