from __future__ import annotations

import logging

from sqlalchemy import select, update

from ...domain.persona import PersonaContract, builtin_personas
from ..models import PersonaRow
from .base import Repository

logger = logging.getLogger(__name__)


class PersonaRepository(Repository):
    @staticmethod
    def _to_domain(row: PersonaRow) -> PersonaContract:
        contract = PersonaContract.model_validate(row.payload)
        contract.id = row.id
        contract.is_builtin = row.is_builtin
        return contract

    async def ensure_builtins(self) -> None:
        """内置人设逐条落库，已存在则跳过，不做批量 upsert 以免锁表。"""
        for preset in builtin_personas():
            async with self.db.session() as session:
                stmt = select(PersonaRow.id).where(PersonaRow.name == preset.name)
                exists = (await session.execute(stmt)).scalar_one_or_none()
            if exists is not None:
                continue
            async with self.db.transaction() as session:
                session.add(
                    PersonaRow(
                        name=preset.name,
                        archetype=preset.archetype.value,
                        is_builtin=True,
                        payload=preset.model_dump(mode="json"),
                    )
                )
            logger.info("写入内置人设: %s", preset.name)

    async def list_all(self) -> list[PersonaContract]:
        async with self.db.session() as session:
            stmt = select(PersonaRow).order_by(
                PersonaRow.is_builtin.desc(), PersonaRow.usage_count.desc(), PersonaRow.id
            )
            rows = (await session.execute(stmt)).scalars().all()
        return [self._to_domain(r) for r in rows]

    async def get(self, persona_id: int) -> PersonaContract | None:
        async with self.db.session() as session:
            row = await session.get(PersonaRow, persona_id)
            return self._to_domain(row) if row else None

    async def save(self, contract: PersonaContract) -> PersonaContract:
        payload = contract.model_dump(mode="json", exclude={"id"})
        async with self.db.transaction() as session:
            if contract.id is not None:
                row = await session.get(PersonaRow, contract.id)
                if row is None:
                    raise ValueError(f"人设 {contract.id} 不存在")
                row.name = contract.name
                row.archetype = contract.archetype.value
                row.payload = payload
            else:
                row = PersonaRow(
                    name=contract.name,
                    archetype=contract.archetype.value,
                    is_builtin=False,
                    payload=payload,
                )
                session.add(row)
            await session.flush()
            new_id = row.id
        result = contract.model_copy(update={"id": new_id})
        return result

    async def duplicate(self, persona_id: int, new_name: str) -> PersonaContract:
        source = await self.get(persona_id)
        if source is None:
            raise ValueError(f"人设 {persona_id} 不存在")
        clone = source.model_copy(update={"id": None, "name": new_name, "is_builtin": False})
        return await self.save(clone)

    async def delete(self, persona_id: int) -> None:
        async with self.db.transaction() as session:
            row = await session.get(PersonaRow, persona_id)
            if row is None:
                return
            if row.is_builtin:
                raise ValueError("内置人设不可删除，请复制后修改")
            await session.delete(row)

    async def bump_usage(self, persona_id: int) -> None:
        async with self.db.transaction() as session:
            await session.execute(
                update(PersonaRow)
                .where(PersonaRow.id == persona_id)
                .values(usage_count=PersonaRow.usage_count + 1)
            )

    async def unique_name(self, base: str) -> str:
        async with self.db.session() as session:
            existing = set((await session.execute(select(PersonaRow.name))).scalars().all())
        if base not in existing:
            return base
        for i in range(2, 100):
            candidate = f"{base} {i}"
            if candidate not in existing:
                return candidate
        return f"{base} {len(existing) + 1}"
