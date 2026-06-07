import tempfile
import unittest
from pathlib import Path

from auth import cookie_token, create_session, hash_password, token_hash, verify_password
from node_database import NodeDatabase


class AuthTest(unittest.TestCase):
    def test_password_hash_verification(self):
        stored = hash_password("admin888")
        self.assertTrue(verify_password("admin888", stored))
        self.assertFalse(verify_password("wrong-password", stored))

    def test_admin_session_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                database.ensure_admin_user("admin", hash_password("admin888"))
                user = database.admin_user_by_username("admin")
                token = create_session(database, int(user["id"]), "127.0.0.1", "unittest")
                session_user = database.admin_user_by_session(token_hash(token))
                self.assertEqual(session_user["username"], "admin")
                database.delete_admin_session(token_hash(token))
                self.assertIsNone(database.admin_user_by_session(token_hash(token)))

    def test_extracts_login_cookie_token(self):
        self.assertEqual(cookie_token("huage_admin_session=abc123; other=value"), "abc123")
        self.assertEqual(cookie_token("other=value"), "")


if __name__ == "__main__":
    unittest.main()
