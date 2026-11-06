# 只查询或 flush；题目锁、数量限制、审计与事务都由服务持有。
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.test_case import TestCase


class TestCaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def problem_id_for(self, case_id: int) -> int | None:
        # 这里只定位归属；不可在取得题目锁之前锁测试点，随后必须锁定重读。
        return await self.session.scalar(
            select(TestCase.problem_id).where(TestCase.id == case_id)
        )

    async def lock_by_id(self, case_id: int, problem_id: int) -> TestCase | None:
        return await self.session.scalar(
            select(TestCase)
            .where(TestCase.id == case_id, TestCase.problem_id == problem_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def locked_ids(self, problem_id: int) -> list[int]:
        # 父题目已锁；以当前读取得最多 50 个 ID，不能用定位归属时的旧快照计数。
        return list(
            (
                await self.session.scalars(
                    select(TestCase.id)
                    .where(TestCase.problem_id == problem_id)
                    .order_by(TestCase.id)
                    .with_for_update()
                )
            ).all()
        )

    async def create(self, *, problem_id: int, **values) -> TestCase:
        case = TestCase(problem_id=problem_id, **values)
        self.session.add(case)
        await self.session.flush()
        await self.session.refresh(case)
        return case

    async def update(self, case: TestCase, **values) -> None:
        for field in (
            "case_index",
            "is_sample",
            "input_data",
            "expected_output",
            "input_size",
            "output_size",
            "sha256",
        ):
            setattr(case, field, values[field])
        await self.session.flush()
        await self.session.refresh(case)

    async def delete(self, case: TestCase) -> None:
        # 不重写历史明细；迁移中的 fk_sc_case 负责 SET NULL。
        await self.session.delete(case)
        await self.session.flush()

    async def page(self, problem_id: int, *, page: int, size: int) -> tuple[list, int]:
        total = await self.session.scalar(
            select(func.count(TestCase.id)).where(TestCase.problem_id == problem_id)
        )
        rows = await self.session.scalars(
            select(TestCase)
            .where(TestCase.problem_id == problem_id)
            .order_by(TestCase.case_index, TestCase.id)
            .offset((page - 1) * size)
            .limit(size)
        )
        return list(rows.all()), int(total or 0)
