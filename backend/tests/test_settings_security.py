import unittest

from pydantic import ValidationError

from app.core.config import Settings


DEVELOPMENT_JWT_SECRET = "fly-arrangement-dev-secret-change-in-production"


class SettingsSecurityTests(unittest.TestCase):
    def test_production_rejects_the_built_in_development_jwt_secret(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                ENVIRONMENT="production",
                JWT_SECRET_KEY=DEVELOPMENT_JWT_SECRET,
            )

    def test_production_rejects_a_short_jwt_secret(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                ENVIRONMENT="production",
                JWT_SECRET_KEY="short-secret",
            )

    def test_production_accepts_a_supplied_long_jwt_secret(self) -> None:
        secret = "production-secret-" + "x" * 48
        settings = Settings(
            _env_file=None,
            ENVIRONMENT="production",
            JWT_SECRET_KEY=secret,
        )

        self.assertEqual(settings.JWT_SECRET_KEY, secret)


if __name__ == "__main__":
    unittest.main()
