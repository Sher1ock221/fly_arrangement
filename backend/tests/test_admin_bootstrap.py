import inspect
import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import main as main_module
from app.services import auth_service
from app.models.user import User
from app.services.auth_service import count_admin_users


class AdminBootstrapTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(User.__table__.create)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    def test_startup_does_not_call_the_default_admin_bootstrap(self) -> None:
        startup_source = inspect.getsource(main_module.lifespan)

        self.assertNotIn("init_default_admin_if_needed", startup_source)
        self.assertNotIn("admin123", startup_source)

    async def test_initial_admin_requires_explicit_strong_credentials(self) -> None:
        create_initial_admin = getattr(auth_service, "create_initial_admin", None)
        self.assertTrue(callable(create_initial_admin), "create_initial_admin is not implemented")
        if not callable(create_initial_admin):
            return

        async with self.sessions() as db:
            with self.assertRaises(ValueError):
                await create_initial_admin(db, username="owner", password="short")

            user = await create_initial_admin(
                db,
                username="owner",
                password="a-strong-initial-password",
            )
            await db.commit()

            self.assertEqual(user.username, "owner")
            self.assertEqual(user.role, "admin")
            self.assertTrue(user.is_active)
            self.assertFalse(user.must_change_password)
            self.assertNotEqual(user.password_hash, "a-strong-initial-password")
            self.assertEqual(await count_admin_users(db), 1)

            with self.assertRaises(ValueError):
                await create_initial_admin(
                    db,
                    username="second-owner",
                    password="another-strong-password",
                )


if __name__ == "__main__":
    unittest.main()
