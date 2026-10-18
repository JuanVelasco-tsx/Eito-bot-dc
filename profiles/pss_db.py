"""Estado del perfil PSS en PostgreSQL: tabla `perfil_recursos` y el lock por servidor.

La tabla es nueva y aditiva: se declara sobre `database.Base`, pero solo existe si este
modulo se importa (es decir, si el perfil esta activo) y la crea `asegurar_tabla()`, no
`crear_tablas()` de database.py (que ya habra corrido). No toca ninguna tabla existente.
Para retirarla: DROP TABLE perfil_recursos.
"""

from contextlib import asynccontextmanager

from sqlalchemy import (
    Boolean, DateTime, String, UniqueConstraint, case, delete, func, or_, select,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Mapped, mapped_column

import database
from database import Base
from profiles.pss_plan import Registro


class PerfilRecurso(Base):
    """Recurso del TOML (rol, categoria, canal o mensaje) y su ID en Discord.

    `key` es la clave estable del TOML. Para un mensaje, `canal_id` es el canal donde se
    publico y `hash_contenido` el hash del embed ya renderizado. `creado` indica que lo
    creo el perfil (solo esos se actualizan sin `adoptar = true`)."""

    __tablename__ = "perfil_recursos"
    __table_args__ = (
        UniqueConstraint("guild_id", "key", name="uq_perfil_recursos_guild_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32))
    key: Mapped[str] = mapped_column(String(100))
    tipo: Mapped[str] = mapped_column(String(20))
    discord_id: Mapped[str] = mapped_column(String(32))
    canal_id: Mapped[str] = mapped_column(String(32), nullable=True)
    hash_contenido: Mapped[str] = mapped_column(String(64), nullable=True)
    creado: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    actualizado: Mapped["object"] = mapped_column(DateTime(timezone=True), server_default=func.now())


_tabla_lista = False


async def asegurar_tabla():
    """Crea `perfil_recursos` si falta (idempotente; solo trabaja una vez por proceso)."""
    global _tabla_lista
    if _tabla_lista:
        return
    async with database.engine.begin() as conn:
        await conn.run_sync(PerfilRecurso.__table__.create, checkfirst=True)
    _tabla_lista = True


def _a_int(valor):
    return int(valor) if valor is not None else None


async def cargar_mapa(guild_id) -> dict:
    """{key: Registro} de todo lo guardado para ese servidor."""
    async with database.SessionLocal() as session:
        resultado = await session.execute(
            select(PerfilRecurso).where(PerfilRecurso.guild_id == str(guild_id))
        )
        return {
            f.key: Registro(f.tipo, int(f.discord_id), _a_int(f.canal_id), f.hash_contenido, f.creado)
            for f in resultado.scalars().all()
        }


async def guardar(guild_id, key, tipo, discord_id, canal_id=None, hash_contenido=None, creado=False):
    """Guarda o actualiza el mapeo `(guild_id, key) -> discord_id` (upsert).

    `creado` nunca baja de True mientras el ID no cambie; si el ID cambia es otro recurso
    y vale lo que se pase."""
    tabla = PerfilRecurso.__table__
    async with database.SessionLocal() as session:
        stmt = pg_insert(PerfilRecurso).values(
            guild_id=str(guild_id), key=key, tipo=tipo, discord_id=str(discord_id),
            canal_id=str(canal_id) if canal_id is not None else None,
            hash_contenido=hash_contenido, creado=creado,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["guild_id", "key"],
            set_={
                "tipo": tipo,
                "discord_id": str(discord_id),
                "canal_id": str(canal_id) if canal_id is not None else None,
                "hash_contenido": hash_contenido,
                "creado": case(
                    (tabla.c.discord_id == stmt.excluded.discord_id, or_(tabla.c.creado, stmt.excluded.creado)),
                    else_=stmt.excluded.creado,
                ),
                "actualizado": func.now(),
            },
        )
        await session.execute(stmt)
        await session.commit()


async def borrar(guild_id, key) -> bool:
    """Olvida el mapeo de `key` (no toca nada en Discord). True si existia."""
    async with database.SessionLocal() as session:
        resultado = await session.execute(
            delete(PerfilRecurso)
            .where(PerfilRecurso.guild_id == str(guild_id), PerfilRecurso.key == key)
            .returning(PerfilRecurso.id)
        )
        existia = resultado.first() is not None
        await session.commit()
        return existia


# --- Lock por servidor (pg_try_advisory_lock) -----------------------------------------------
# Namespace para no chocar con otros usos de advisory locks (xor con el ID del servidor).
_NAMESPACE_LOCK = 0x5053530000000000


def clave_lock(guild_id) -> int:
    """Clave bigint (positiva) del advisory lock de ese servidor."""
    return (int(guild_id) ^ _NAMESPACE_LOCK) & 0x7FFFFFFFFFFFFFFF


@asynccontextmanager
async def lock_aplicar(guild_id):
    """Lock de sesion de PostgreSQL por servidor durante `!pss aplicar`.

    Entrega True si se obtuvo y False si otra aplicacion lo tiene (de este proceso o de
    otra instancia de Railway). Un advisory lock de sesion pertenece a UNA conexion, asi
    que se reserva una durante todo el bloque (no la del pool de las sesiones normales).
    Si no se puede soltar limpiamente, la conexion se invalida para que se cierre y el
    servidor libere el lock."""
    clave = clave_lock(guild_id)
    async with database.engine.connect() as conn:
        obtenido = bool(await conn.scalar(select(func.pg_try_advisory_lock(clave))))
        await conn.commit()   # el lock es de sesion: sobrevive al commit y no deja la transaccion abierta
        try:
            yield obtenido
        finally:
            if obtenido:
                try:
                    await conn.scalar(select(func.pg_advisory_unlock(clave)))
                    await conn.commit()
                except Exception:
                    await conn.invalidate()
