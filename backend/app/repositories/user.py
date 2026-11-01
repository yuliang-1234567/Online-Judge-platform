from sqlalchemy import select
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
        user = User(
            username=username, password_hash=password_hash, role="USER", status="ACTIVE"
        )
        self.session.add(user)
        await self.session.flush()
        await self.session.refresh(user)
        return user
