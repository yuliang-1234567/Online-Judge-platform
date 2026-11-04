from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


# 仓储接收请求级会话，只查询/写入用户；服务决定事务边界，依赖负责最终关闭。
class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def by_username(self, username: str) -> User | None:
        # 大小写唯一性由既有 MySQL 排序规则决定，不能用应用预查询替代唯一约束。
        return await self.session.scalar(select(User).where(User.username == username))

    async def by_id(self, user_id: int) -> User | None:
        return await self.session.scalar(select(User).where(User.id == user_id))

    # add 仅把对象纳入会话；flush 发出 INSERT，使自增 ID 和唯一约束错误在事务内出现。
    # refresh 再读数据库生成的默认值（如时间列）；三步均不表示事务已经提交。
    # 不能在仓储里 commit，否则服务无法把后续步骤与本次写入作为一个单元回滚。
    async def create(self, username: str, password_hash: str) -> User:
        return await self._create(username, password_hash, role="USER")

    # 管理员命令使用独立入口；普通注册仍只能进入上面的 USER 路径。
    async def create_admin(self, username: str, password_hash: str) -> User:
        return await self._create(username, password_hash, role="ADMIN")

    # 仅复用构造、flush、refresh；角色由两个固定入口决定，事务仍属于调用方。
    async def _create(
        self, username: str, password_hash: str, *, role: Literal["USER", "ADMIN"]
    ) -> User:
        user = User(
            username=username, password_hash=password_hash, role=role, status="ACTIVE"
        )
        self.session.add(user)
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def page(
        self, *, page: int, size: int, username: str | None
    ) -> tuple[list[User], int]:
        filters = []
        if username:
            # 搜索按字面子串处理，转义 LIKE 的 %/_，参数继续由驱动绑定。
            filters.append(User.username.contains(username, autoescape=True))
        total = await self.session.scalar(select(func.count(User.id)).where(*filters))
        rows = await self.session.scalars(
            select(User)
            .where(*filters)
            .order_by(User.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        return list(rows.all()), int(total or 0)

    async def lock_active_admin_ids(self) -> list[int]:
        # 所有减少有效管理员的事务先执行此锁定读，按 id 升序建立相同锁顺序。
        # 无 role/status 索引时物理锁范围可能更广；不能把替身验证当作 InnoDB 锁证据。
        rows = await self.session.scalars(
            select(User.id)
            .where(User.role == "ADMIN", User.status == "ACTIVE")
            .order_by(User.id)
            .with_for_update()
        )
        return list(rows.all())

    async def lock_by_id(self, user_id: int) -> User | None:
        # 同一请求的鉴权可能已加载此对象；锁定 SQL 必须覆盖 identity map 中的旧值。
        return await self.session.scalar(
            select(User)
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def update_access(self, user: User, *, role: str, status: str) -> None:
        user.role = role
        user.status = status
        await self.session.flush()
        await self.session.refresh(user)
