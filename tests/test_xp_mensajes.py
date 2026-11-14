"""XP por mensajes (on_message): los mensajes que empiezan por el prefijo "!" no dan XP;
los normales si (con cooldown). Los comandos se procesan siempre una vez."""

import types

import pytest


@pytest.fixture
def chat(mod, fakes, monkeypatch):
    """on_message con sumar_xp y process_commands capturados."""
    xp, comandos = [], []

    async def sumar_xp(miembro, cantidad, canal_fallback=None):
        xp.append((miembro.id, cantidad))

    async def process_commands(message):
        comandos.append(message.content)

    monkeypatch.setattr(mod, "sumar_xp", sumar_xp)
    monkeypatch.setattr(mod.bot, "process_commands", process_commands)
    monkeypatch.setattr(mod, "ultimo_xp", {})
    guild = fakes.Guild()
    canal = guild.canal("general")

    def mensaje(contenido, autor_id=9):
        autor = fakes.Usuario(autor_id, "Juan")
        return types.SimpleNamespace(content=contenido, author=autor, guild=guild, channel=canal)

    return types.SimpleNamespace(xp=xp, comandos=comandos, mensaje=mensaje)


@pytest.mark.parametrize("contenido", ["!perfil", "!perfil <@123>", "!hola"])
async def test_un_mensaje_que_empieza_por_el_prefijo_no_da_xp(mod, chat, contenido):
    await mod.on_message(chat.mensaje(contenido))
    assert chat.xp == []
    assert chat.comandos == [contenido]


async def test_un_mensaje_normal_da_xp_una_vez(mod, chat):
    await mod.on_message(chat.mensaje("hola"))
    assert chat.xp == [(9, mod.XP_POR_MENSAJE)]
    assert chat.comandos == ["hola"]
