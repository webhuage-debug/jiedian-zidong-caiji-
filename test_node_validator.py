import tempfile
import sys
import unittest
from pathlib import Path

from node_validator import config_for, resolve_xray_path


class NodeValidatorCompatibilityTest(unittest.TestCase):
    def test_resolves_windows_xray_exe_when_default_path_has_no_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "xray.exe"
            exe.write_text("", encoding="utf-8")
            self.assertEqual(resolve_xray_path(root / "xray"), exe.resolve())

    def test_resolves_linux_xray_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "xray"
            binary.write_text("", encoding="utf-8")
            self.assertEqual(resolve_xray_path(binary), binary.resolve())

    def test_prefers_windows_xray_exe_when_both_binaries_exist_on_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "xray"
            exe = root / "xray.exe"
            binary.write_text("", encoding="utf-8")
            exe.write_text("", encoding="utf-8")
            expected = exe if sys.platform.startswith("win") else binary
            self.assertEqual(resolve_xray_path(binary), expected.resolve())

    def test_xray_config_uses_local_socks_inbound_for_connectivity_probe(self):
        config = config_for("vless://uuid@example.com:443?security=tls&sni=sni.example.com", 10808)
        inbound = config["inbounds"][0]
        self.assertEqual(inbound["listen"], "127.0.0.1")
        self.assertEqual(inbound["port"], 10808)
        self.assertEqual(inbound["protocol"], "socks")
        self.assertEqual(config["outbounds"][0]["protocol"], "vless")


if __name__ == "__main__":
    unittest.main()
