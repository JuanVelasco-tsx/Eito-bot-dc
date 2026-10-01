"""Capa de persistencia con PostgreSQL (SQLAlchemy async + asyncpg).

Reemplaza el guardado en archivos JSON (niveles.json, avisos.json) por
tablas en una base de datos PostgreSQL, para que los datos persistan
entre despliegues y escalen mejor que un archivo plano.
"""

import os

from sqlalchemy import (
    BigInteger, DateTime, Index, Integer, String, Text, UniqueConstraint, and_, func, select,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Cargar variables desde un archivo .env local (si existe).
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --- CONEXION ---
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://usuario:contraseña@localhost/eito_db"
)
# SQLAlchemy async necesita el driver asyncpg explicito en la URL.
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(AsyncAttrs, DeclarativeBase):
    pass


# =====================================================================
#  MODELOS
# =====================================================================
class UserXP(Base):
    """XP acumulada por un usuario en un servidor."""

    __tablename__ = "user_xp"
    __table_args__ = (
        UniqueConstraint("guild_id", "user_id", name="uq_user_xp_guild_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    xp: Mapped[int] = mapped_column(BigInteger, default=0)


class UserWarn(Base):
    """Aviso (warn) de moderacion aplicado a un usuario en un servidor."""

    __tablename__ = "user_warns"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text)
    moderator: Mapped[str] = mapped_column(String(100))
    timestamp: Mapped["object"] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConfigServidor(Base):
    """Configuracion propia de cada servidor (un registro por guild_id)."""

    __tablename__ = "config_servidor"

    guild_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    mensaje_cochipuerco_id: Mapped[str] = mapped_column(String(32), nullable=True)


class XPMensual(Base):
    """XP ganada por un usuario en un mes concreto (para el Activo del mes).

    `mes` es "YYYY-MM" en UTC. Solo la escribe on_message (y la importacion
    de niveles); los comandos admin de XP total no la tocan."""

    __tablename__ = "xp_mensual"
    __table_args__ = (
        UniqueConstraint("guild_id", "user_id", "mes", name="uq_xp_mensual_guild_user_mes"),
        Index("ix_xp_mensual_guild_mes", "guild_id", "mes"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32))
    user_id: Mapped[str] = mapped_column(String(32))
    mes: Mapped[str] = mapped_column(String(7))
    xp: Mapped[int] = mapped_column(BigInteger, default=0)


class GanadorMes(Base):
    """Historial de ganadores del Activo del mes (evita premiar dos veces)."""

    __tablename__ = "ganadores_mes"
    __table_args__ = (
        UniqueConstraint("guild_id", "mes", "puesto", name="uq_ganadores_mes_guild_mes_puesto"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    mes: Mapped[str] = mapped_column(String(7))
    user_id: Mapped[str] = mapped_column(String(32))
    puesto: Mapped[int] = mapped_column(Integer)
    xp: Mapped[int] = mapped_column(BigInteger)


class MensajeFijo(Base):
    """Mensaje fijo del bot (reglas, guia, panel de roles...) para editarlo en
    vez de publicar uno nuevo cada vez. `clave` identifica el mensaje."""

    __tablename__ = "mensajes_fijos"
    __table_args__ = (
        UniqueConstraint("guild_id", "clave", name="uq_mensajes_fijos_guild_clave"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32))
    clave: Mapped[str] = mapped_column(String(50))
    canal_id: Mapped[str] = mapped_column(String(32))
    mensaje_id: Mapped[str] = mapped_column(String(32))


async def crear_tablas():
    """Crea las tablas en la base de datos si todavia no existen."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# =====================================================================
#  HELPERS: XP / NIVELES
# =====================================================================
async def get_user_xp(guild_id, user_id) -> int:
    """Devuelve la XP total de un usuario en un servidor (0 si no tiene)."""
    async with SessionLocal() as session:
        resultado = await session.execute(
            select(UserXP.xp).where(
                UserXP.guild_id == str(guild_id), UserXP.user_id == str(user_id)
            )
        )
        xp = resultado.scalar_one_or_none()
        return xp or 0


async def add_user_xp(guild_id, user_id, cantidad) -> int:
    """Suma `cantidad` de XP a un usuario (crea el registro si no existe).

    Devuelve la XP total resultante. `cantidad` puede ser negativa para
    restar (por ejemplo, para fijar un total exacto).
    """
    async with SessionLocal() as session:
        stmt = pg_insert(UserXP).values(
            guild_id=str(guild_id), user_id=str(user_id), xp=cantidad
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["guild_id", "user_id"],
            set_={"xp": UserXP.__table__.c.xp + cantidad},
        ).returning(UserXP.xp)
        resultado = await session.execute(stmt)
        nueva_xp = resultado.scalar_one()
        await session.commit()
        return nueva_xp


async def set_user_xp(guild_id, user_id, xp) -> None:
    """Fija la XP total de un usuario a `xp` (crea el registro si no existe).

    Solo toca user_xp: no modifica xp_mensual."""
    async with SessionLocal() as session:
        stmt = pg_insert(UserXP).values(
            guild_id=str(guild_id), user_id=str(user_id), xp=xp
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["guild_id", "user_id"],
            set_={"xp": xp},
        )
        await session.execute(stmt)
        await session.commit()


async def get_all_xp(guild_id) -> dict:
    """Devuelve un diccionario {user_id: xp} con toda la XP de un servidor."""
    async with SessionLocal() as session:
        resultado = await session.execute(
            select(UserXP.user_id, UserXP.xp).where(UserXP.guild_id == str(guild_id))
        )
        return {user_id: xp for user_id, xp in resultado.all()}


# =====================================================================
#  HELPERS: ACTIVO DEL MES (XP mensual y ganadores)
# =====================================================================
async def add_xp_mensual(guild_id, user_id, mes, cantidad) -> int:
    """Suma `cantidad` de XP al mes `mes` ("YYYY-MM") de un usuario (upsert).

    Devuelve la XP mensual resultante."""
    async with SessionLocal() as session:
        stmt = pg_insert(XPMensual).values(
            guild_id=str(guild_id), user_id=str(user_id), mes=mes, xp=cantidad
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["guild_id", "user_id", "mes"],
            set_={"xp": XPMensual.__table__.c.xp + cantidad},
        ).returning(XPMensual.xp)
        resultado = await session.execute(stmt)
        nueva_xp = resultado.scalar_one()
        await session.commit()
        return nueva_xp


async def top_xp_mensual(guild_id, mes, limite) -> list:
    """Devuelve [(user_id, xp), ...] del mes, de mayor a menor XP (ordenado en SQL).

    Ante empate en XP mensual gana quien tiene mas XP total (user_xp; sin fila
    cuenta como 0) y, si sigue el empate, quien tiene el registro mas antiguo."""
    async with SessionLocal() as session:
        resultado = await session.execute(
            select(XPMensual.user_id, XPMensual.xp)
            .select_from(XPMensual)
            .outerjoin(
                UserXP,
                and_(
                    UserXP.guild_id == XPMensual.guild_id,
                    UserXP.user_id == XPMensual.user_id,
                ),
            )
            .where(XPMensual.guild_id == str(guild_id), XPMensual.mes == mes)
            .order_by(
                XPMensual.xp.desc(),
                func.coalesce(UserXP.xp, 0).desc(),
                XPMensual.id,
            )
            .limit(limite)
        )
        return [(user_id, xp) for user_id, xp in resultado.all()]


async def mes_ya_premiado(guild_id, mes) -> bool:
    """True si ya hay ganadores guardados para ese mes en ese servidor."""
    async with SessionLocal() as session:
        resultado = await session.execute(
            select(GanadorMes.id)
            .where(GanadorMes.guild_id == str(guild_id), GanadorMes.mes == mes)
            .limit(1)
        )
        return resultado.first() is not None


async def guardar_ganadores(guild_id, mes, lista):
    """Guarda los ganadores del mes. `lista` = [(user_id, puesto, xp), ...].

    Si el puesto ya existia para ese mes no lo pisa (UNIQUE guild+mes+puesto)."""
    if not lista:
        return
    async with SessionLocal() as session:
        stmt = pg_insert(GanadorMes).values([
            {"guild_id": str(guild_id), "mes": mes, "user_id": str(user_id),
             "puesto": puesto, "xp": xp}
            for user_id, puesto, xp in lista
        ])
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["guild_id", "mes", "puesto"]
        )
        await session.execute(stmt)
        await session.commit()


async def importar_xp_mensual(guild_id, mes, datos) -> int:
    """Importa XP mensual aproximada: `datos` = {user_id: xp}.

    Upsert con greatest(existente, importado): no pisa ni duplica la XP que
    ya registro on_message. Devuelve cuantas filas se procesaron."""
    if not datos:
        return 0
    async with SessionLocal() as session:
        stmt = pg_insert(XPMensual).values([
            {"guild_id": str(guild_id), "user_id": str(user_id), "mes": mes, "xp": xp}
            for user_id, xp in datos.items()
        ])
        stmt = stmt.on_conflict_do_update(
            index_elements=["guild_id", "user_id", "mes"],
            set_={"xp": func.greatest(XPMensual.__table__.c.xp, stmt.excluded.xp)},
        )
        await session.execute(stmt)
        await session.commit()
        return len(datos)


# =====================================================================
#  HELPERS: AVISOS (WARNS)
# =====================================================================
async def get_warns(guild_id, user_id) -> list:
    """Devuelve la lista de avisos de un usuario en un servidor."""
    async with SessionLocal() as session:
        resultado = await session.execute(
            select(UserWarn)
            .where(UserWarn.guild_id == str(guild_id), UserWarn.user_id == str(user_id))
            .order_by(UserWarn.timestamp)
        )
        return [
            {"reason": w.reason, "moderator": w.moderator, "timestamp": w.timestamp}
            for w in resultado.scalars().all()
        ]


async def add_warn(guild_id, user_id, reason, moderator) -> int:
    """Registra un aviso nuevo y devuelve el total de avisos del usuario."""
    async with SessionLocal() as session:
        session.add(
            UserWarn(
                guild_id=str(guild_id),
                user_id=str(user_id),
                reason=reason,
                moderator=moderator,
            )
        )
        await session.commit()

        total = await session.scalar(
            select(func.count())
            .select_from(UserWarn)
            .where(UserWarn.guild_id == str(guild_id), UserWarn.user_id == str(user_id))
        )
        return total


# =====================================================================
#  HELPERS: CONFIGURACION DEL SERVIDOR
# =====================================================================
async def set_mensaje_cochipuerco(guild_id: str, message_id: str):
    """Guarda el ID del mensaje-panel del rol +18 para este servidor (upsert)."""
    async with SessionLocal() as session:
        stmt = pg_insert(ConfigServidor).values(
            guild_id=str(guild_id), mensaje_cochipuerco_id=str(message_id)
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["guild_id"],
            set_={"mensaje_cochipuerco_id": str(message_id)},
        )
        await session.execute(stmt)
        await session.commit()


async def get_mensaje_cochipuerco(guild_id: str) -> str | None:
    """Devuelve el ID del mensaje-panel del rol +18 de este servidor, o None."""
    async with SessionLocal() as session:
        resultado = await session.execute(
            select(ConfigServidor.mensaje_cochipuerco_id).where(
                ConfigServidor.guild_id == str(guild_id)
            )
        )
        return resultado.scalar_one_or_none()


# =====================================================================
#  HELPERS: MENSAJES FIJOS
# =====================================================================
async def get_mensaje_fijo(guild_id, clave):
    """Devuelve (canal_id, mensaje_id) del mensaje fijo `clave`, o None."""
    async with SessionLocal() as session:
        resultado = await session.execute(
            select(MensajeFijo.canal_id, MensajeFijo.mensaje_id).where(
                MensajeFijo.guild_id == str(guild_id), MensajeFijo.clave == clave
            )
        )
        fila = resultado.first()
        return (fila[0], fila[1]) if fila else None


async def set_mensaje_fijo(guild_id, clave, canal_id, mensaje_id):
    """Guarda (o reemplaza) el canal y el mensaje de la clave `clave` (upsert)."""
    async with SessionLocal() as session:
        stmt = pg_insert(MensajeFijo).values(
            guild_id=str(guild_id), clave=clave,
            canal_id=str(canal_id), mensaje_id=str(mensaje_id),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["guild_id", "clave"],
            set_={"canal_id": str(canal_id), "mensaje_id": str(mensaje_id)},
        )
        await session.execute(stmt)
        await session.commit()
