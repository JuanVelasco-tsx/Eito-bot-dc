"""Panel +18: reaccionar con 🔞 en el mensaje configurado da el rol Cochipuercoso y
quitar la reaccion lo quita (on_raw_reaction_add / on_raw_reaction_remove)."""

import types

import discord
import pytest

MENSAJE = 777
ROL_ID = 50


class Miembro:
    """Miembro con add_roles/remove_roles que registran el rol (o lanzan `error`)."""

    def __init__(self, guild, id=10, bot=False, error=None):
        self.guild, self.id, self.bot, self.error = guild, id, bot, error
        self.dados, self.quitados = [], []

    async def add_roles(self, rol):
        if self.error:
            raise self.error
        self.dados.append(rol)

    async def remove_roles(self, rol):
        if self.error:
            raise self.error
        self.quitados.append(rol)


def payload(miembro, emoji="🔞", mensaje=MENSAJE, con_miembro=True):
    return types.SimpleNamespace(
        guild_id=miembro.guild.id, message_id=mensaje, emoji=emoji,
        member=miembro if con_miembro else None, user_id=miembro.id,
    )


def prohibido():
    return discord.Forbidden(types.SimpleNamespace(status=403, reason="x"), "sin permiso")


@pytest.fixture
def entorno(mod, fakes, monkeypatch):
    """Servidor con el rol, el mensaje del panel configurado y los logs capturados."""
    guild = fakes.Guild()
    guild.rol(ROL_ID, mod.ROL_COCHIPUERCO)
    miembros = {}
    guild.get_member = miembros.get
    logs = []
    estado = types.SimpleNamespace(guild=guild, miembros=miembros, logs=logs, mensaje=str(MENSAJE))

    async def get_mensaje(guild_id):
        return estado.mensaje

    async def registrar_log(g, texto):
        logs.append(texto)

    monkeypatch.setattr(mod, "get_mensaje_cochipuerco", get_mensaje)
    monkeypatch.setattr(mod, "registrar_log", registrar_log)
    monkeypatch.setattr(mod.bot, "get_guild", lambda ident: guild if ident == guild.id else None)

    def miembro(**kwargs):
        m = Miembro(guild, **kwargs)
        miembros[m.id] = m
        return m

    estado.miembro = miembro
    return estado


async def test_reaccion_en_el_mensaje_configurado_da_el_rol(mod, entorno):
    m = entorno.miembro()
    await mod.on_raw_reaction_add(payload(m))
    assert [r.id for r in m.dados] == [ROL_ID]
    assert entorno.logs == []


async def test_reaccion_en_otro_mensaje_no_hace_nada(mod, entorno):
    m = entorno.miembro()
    await mod.on_raw_reaction_add(payload(m, mensaje=MENSAJE + 1))
    assert m.dados == [] and entorno.logs == []


async def test_otro_emoji_no_hace_nada(mod, entorno):
    m = entorno.miembro()
    await mod.on_raw_reaction_add(payload(m, emoji="👍"))
    assert m.dados == [] and entorno.logs == []


async def test_reaccion_de_un_bot_no_hace_nada(mod, entorno):
    m = entorno.miembro(bot=True)
    await mod.on_raw_reaction_add(payload(m))
    await mod.on_raw_reaction_remove(payload(m, con_miembro=False))
    assert m.dados == [] and m.quitados == [] and entorno.logs == []


async def test_sin_mensaje_configurado_no_hace_nada_ni_registra(mod, entorno):
    entorno.mensaje = None
    m = entorno.miembro()
    await mod.on_raw_reaction_add(payload(m))
    await mod.on_raw_reaction_remove(payload(m, con_miembro=False))
    assert m.dados == [] and m.quitados == [] and entorno.logs == []


async def test_quitar_la_reaccion_quita_el_rol(mod, entorno):
    m = entorno.miembro()
    # Discord no envia payload.member al quitar una reaccion: se busca con get_member.
    await mod.on_raw_reaction_remove(payload(m, con_miembro=False))
    assert [r.id for r in m.quitados] == [ROL_ID]
    assert entorno.logs == []


async def test_sin_el_rol_en_el_servidor_lo_registra(mod, entorno):
    entorno.guild.roles.clear()
    m = entorno.miembro()
    await mod.on_raw_reaction_add(payload(m))
    await mod.on_raw_reaction_remove(payload(m, con_miembro=False))
    assert m.dados == [] and m.quitados == []
    assert len(entorno.logs) == 2
    assert all(mod.ROL_COCHIPUERCO in texto for texto in entorno.logs)


async def test_sin_permisos_lo_registra(mod, entorno):
    m = entorno.miembro(error=prohibido())
    await mod.on_raw_reaction_add(payload(m))
    await mod.on_raw_reaction_remove(payload(m, con_miembro=False))
    assert len(entorno.logs) == 2
    assert all("Sin permisos" in texto for texto in entorno.logs)
