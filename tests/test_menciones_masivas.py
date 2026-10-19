"""Ningun texto de un usuario puede generar una mencion masiva (@everyone, @here, roles), ni siquiera
si el bot tiene el permiso «Mencionar @everyone, @here y todos los roles».

Ese permiso solo decide si una mencion NOTIFICA cuando el envio la permite con allowed_mentions; el bot
nace con everyone=False y roles=False, y solo estos envios piden otra cosa (lista cerrada, con test)."""

import re
import types
from pathlib import Path

import pytest

FUENTE = Path(__file__).resolve().parent.parent / "eito_setup_bot.py"
MALICIOSO = "@everyone @here <@&1234567890> hola"


def sin_masivas(permitido):
    """El allowed_mentions efectivo no admite everyone ni roles."""
    assert "everyone" not in permitido.get("parse", []) and "roles" not in permitido.get("parse", [])
    assert not permitido.get("roles")


class Mensaje:
    def __init__(self):
        self.reacciones = []

    async def add_reaction(self, emoji):
        self.reacciones.append(emoji)


def canal_con_reacciones(canal):
    async def send(content=None, **kwargs):
        canal.enviados.append((content, kwargs))
        return Mensaje()

    canal.send = send
    return canal


# --- Lista cerrada de envios que piden mas que el default ---------------------------------------------------
def test_los_unicos_envios_que_permiten_roles_o_everyone_son_los_conocidos():
    codigo = FUENTE.read_text(encoding="utf-8")
    llamadas = re.findall(r"allowed_mentions=discord\.AllowedMentions\((.*?)\)\s*[,)]", codigo, flags=re.S)
    con_roles = [c for c in llamadas if re.search(r"roles=(?!False)", c)]
    con_everyone = [c for c in llamadas if "everyone=True" in c]
    # roles: webhook de releases, aviso de !jugar, ping de tickets (y el default global, roles=False)
    assert sorted(re.sub(r"\s+", " ", c) for c in con_roles) == sorted(["roles=[rol]", "roles=[rol]", "users=[usuario], roles=pings, everyone=False"])
    # everyone=True: solo !anuncio con la palabra clave, y su content es el literal «@everyone»/«@here»
    assert len(con_everyone) == 1 and "roles=False" in con_everyone[0]
    assert codigo.count('content=f"@{ping}"') == 1
    assert "parse=" not in codigo                              # nadie usa parse=["everyone", ...]


# --- Textos del usuario -------------------------------------------------------------------------------------
async def test_sugerencia_y_encuesta_no_mencionan_en_masa(mod, fakes, efectivo):
    guild = fakes.Guild()
    sugerencias = canal_con_reacciones(guild.canal(mod.CANAL_SUGERENCIAS))
    ctx = fakes.Ctx(guild=guild, canal=sugerencias)
    await mod.sugerencia.callback(ctx, texto=MALICIOSO)
    contenido, kwargs = sugerencias.enviados[0]
    assert contenido is None and MALICIOSO in kwargs["embed"].description      # va en un embed: no notifica
    sin_masivas(efectivo(kwargs))

    aqui = canal_con_reacciones(fakes.Canal("general"))
    ctx = fakes.Ctx(guild=guild, canal=aqui)

    async def send(content=None, **kwargs):
        ctx.respuestas.append((content, kwargs))
        return Mensaje()

    ctx.send = send
    await mod.encuesta.callback(ctx, pregunta=MALICIOSO)
    contenido, kwargs = ctx.respuestas[0]
    assert contenido is None and MALICIOSO in kwargs["embed"].description
    sin_masivas(efectivo(kwargs))


async def test_los_registros_de_moderacion_con_texto_del_usuario_no_mencionan_en_masa(mod, fakes, efectivo):
    guild = fakes.Guild()
    logs = guild.canal(mod.CANAL_LOGS)
    await mod.registrar_log(guild, f"🔨 **Ana** baneó a **Pepe**. Razón: {MALICIOSO}")
    contenido, kwargs = logs.enviados[0]
    assert MALICIOSO in contenido
    sin_masivas(efectivo(kwargs))


async def test_anuncio_sin_palabra_clave_publica_un_embed_sin_menciones_masivas(mod, fakes, efectivo):
    guild = fakes.Guild()
    anuncios = guild.canal(mod.CANAL_ANUNCIOS)
    ctx = fakes.Ctx(guild=guild)
    await mod.anuncio.callback(ctx, texto=MALICIOSO)          # «@everyone» no es la PRIMERA palabra ni va sin @: es texto
    contenido, kwargs = anuncios.enviados[0]
    assert contenido is None
    sin_masivas(efectivo(kwargs))
    for _c, kw in ctx.respuestas:                             # la confirmacion tampoco menciona
        sin_masivas(efectivo(kw))


async def test_anuncio_con_everyone_menciona_solo_con_la_palabra_clave_y_el_permiso(mod, fakes, efectivo):
    guild = fakes.Guild()
    anuncios = guild.canal(mod.CANAL_ANUNCIOS)
    ctx = fakes.Ctx(guild=guild)
    await mod.anuncio.callback(ctx, texto="everyone hola <@&1234567890> @here")
    contenido, kwargs = anuncios.enviados[0]
    assert contenido == "@everyone"                            # el content es fijo: el texto va al embed
    permitido = efectivo(kwargs)
    assert permitido["parse"] == ["everyone"] and not permitido.get("roles")


# --- Bienvenida ---------------------------------------------------------------------------------------------
async def test_la_bienvenida_de_eito_va_en_un_embed_y_sin_menciones_masivas(mod, fakes, efectivo, monkeypatch):
    guild = fakes.Guild()
    guild.rol(int(mod.ROL_AUTOMATICO), "COMUNIDAD")
    bienvenida = guild.canal(mod.CANAL_BIENVENIDA)
    guild.member_count = 3

    async def get_fundador(*a):
        return None

    monkeypatch.setattr(mod, "get_fundador", get_fundador)
    monkeypatch.setattr(mod.bot, "get_cog", lambda n: None)

    class Nuevo:
        id, bot, mention, name = 7, False, "<@7>", "@everyone"
        display_avatar = types.SimpleNamespace(url="https://cdn/a.png")

        async def add_roles(self, *r, **k):
            pass

    Nuevo.guild = guild
    await mod.on_member_join(Nuevo())
    contenido, kwargs = bienvenida.enviados[0]
    assert contenido is None
    sin_masivas(efectivo(kwargs))


async def test_la_bienvenida_de_pss_va_en_un_embed_y_sin_menciones_masivas(tmp_path):
    from tests.test_pss_gancho import FGuild, FMiembro, FTexto, PerfilPSS, RUTA, cargar, con_eventos
    cog = PerfilPSS(types.SimpleNamespace(get_cog=lambda n: None), cargar(RUTA), RUTA)
    cog.config = con_eventos(cog.config, anti_multicuentas=False, rol_al_entrar="")
    guild = FGuild()
    canal = guild.canales[80] = FTexto(80)
    cog.ids = {"bienvenida": 80}
    miembro = FMiembro(guild)
    miembro.mention = "@everyone"                               # el peor caso: la «mencion» del usuario es @everyone
    await cog.al_entrar(miembro)
    contenido, kwargs = canal.enviados[0]
    assert contenido is None and "embed" in kwargs
    # sin allowed_mentions propio: manda el default del bot (everyone=False, roles=False)
    assert "allowed_mentions" not in kwargs


# --- Los que SI mencionan, solo lo previsto -----------------------------------------------------------------
async def test_ticket_ping_no_permite_everyone_ni_roles_ajenos(mod, perfil_tickets):
    guild, inter = perfil_tickets
    await mod.ticket_abrir(inter)
    contenido, kwargs = guild.creados[0].enviados[0]
    permitido = kwargs["allowed_mentions"]
    assert permitido.everyone is False
    assert {r.id for r in permitido.roles} == {21, 22}                   # solo Propietario y Administrador
    assert [u.id for u in permitido.users] == [9]                        # y la persona que abre el ticket
    assert "@everyone" not in contenido and "@here" not in contenido


@pytest.fixture
async def perfil_tickets(mod, sin_bd):
    from profiles.pss import PerfilPSS
    from profiles.pss_config import cargar
    from tests.test_fase2 import Ent, Interaccion, guild_de_tickets
    from tests.test_recursos import RUTA
    cog = PerfilPSS(mod.bot, cargar(RUTA), RUTA)
    await mod.bot.add_cog(cog)
    guild = guild_de_tickets(cog)
    yield guild, Interaccion(guild, Ent(id=9, name="@everyone", mention="<@9>"))
    await mod.bot.remove_cog("PerfilPSS")


from tests.test_recursos import sin_bd  # noqa: E402,F401
