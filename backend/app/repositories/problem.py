# 请求级仓储只执行查询和 flush；事务、异常转换及审计由服务负责。
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.problem import Problem, ProblemTag, Tag

# 列表不选 MEDIUMTEXT，避免先加载完整题面再在响应中丢弃。
SUMMARY_COLUMNS = tuple(
    column for column in Problem.__table__.columns if column.name != "description"
)


class ProblemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, created_by: int, **values) -> Problem:
        problem = Problem(**values, created_by=created_by, status="DRAFT")
        self.session.add(problem)
        await self.session.flush()
        await self.session.refresh(problem)
        return problem

    async def by_id(self, problem_id: int) -> Problem | None:
        return await self.session.scalar(
            select(Problem).where(Problem.id == problem_id)
        )

    async def lock_by_id(self, problem_id: int) -> Problem | None:
        # 状态判断和修改使用同一锁定读；刷新会话中可能已有的旧 ORM 属性。
        return await self.session.scalar(
            select(Problem)
            .where(Problem.id == problem_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def page(self, *, page: int, size: int) -> tuple[list, int]:
        total = await self.session.scalar(select(func.count(Problem.id)))
        rows = await self.session.execute(
            select(*SUMMARY_COLUMNS)
            .order_by(Problem.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        return list(rows.mappings().all()), int(total or 0)

    async def update(self, problem: Problem, **values) -> None:
        # 显式白名单与服务 DTO 双重约束，不能用任意键覆盖 slug/status/created_by。
        for field in (
            "title",
            "description",
            "difficulty",
            "time_limit_ms",
            "memory_limit_mb",
        ):
            setattr(problem, field, values[field])
        await self.session.flush()
        await self.session.refresh(problem)

    async def replace_tags(self, problem_id: int, tag_ids: list[int]) -> None:
        # 与题目行锁、业务修改同事务；插入失败时，删除的旧关联也必须回滚。
        await self.session.execute(
            delete(ProblemTag).where(ProblemTag.problem_id == problem_id)
        )
        self.session.add_all(
            [ProblemTag(problem_id=problem_id, tag_id=tag_id) for tag_id in tag_ids]
        )
        await self.session.flush()


class TagRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def by_ids(self, tag_ids: list[int]) -> list[Tag]:
        if not tag_ids:
            return []
        rows = await self.session.scalars(
            select(Tag).where(Tag.id.in_(tag_ids)).order_by(Tag.id)
        )
        return list(rows.all())

    async def for_problems(self, problem_ids: list[int]) -> dict[int, list[Tag]]:
        if not problem_ids:
            return {}
        rows = await self.session.execute(
            select(ProblemTag.problem_id, Tag)
            .join(Tag, Tag.id == ProblemTag.tag_id)
            .where(ProblemTag.problem_id.in_(problem_ids))
            .order_by(Tag.id)
        )
        grouped: dict[int, list[Tag]] = {}
        for problem_id, tag in rows.all():
            grouped.setdefault(problem_id, []).append(tag)
        return grouped

    async def create(self, name: str) -> Tag:
        tag = Tag(name=name)
        self.session.add(tag)
        await self.session.flush()
        await self.session.refresh(tag)
        return tag

    async def page(self, *, page: int, size: int) -> tuple[list[Tag], int]:
        total = await self.session.scalar(select(func.count(Tag.id)))
        rows = await self.session.scalars(
            select(Tag).order_by(Tag.id.desc()).offset((page - 1) * size).limit(size)
        )
        return list(rows.all()), int(total or 0)
