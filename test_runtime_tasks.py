import tempfile
import unittest
from unittest.mock import Mock, patch
from pathlib import Path
from types import SimpleNamespace

from runtime_tasks import LogBus, kill_process, normalize_task_output, task_environment, terminate_process


class RuntimeTasksTest(unittest.TestCase):
    def test_task_environment_forces_utf8_output(self):
        env = task_environment()
        self.assertEqual(env["PYTHONIOENCODING"], "utf-8")
        self.assertNotIn("PYTHONUTF8", env)

    def test_process_stop_uses_windows_process_methods(self):
        process = Mock(pid=12345)
        with patch("runtime_tasks.os.name", "nt"):
            terminate_process(process)
            kill_process(process)
        process.terminate.assert_called_once()
        process.kill.assert_called_once()

    def test_normalizes_scrapling_timeout_messages_to_chinese(self):
        message = (
            "ERROR: Failed after 2 attempts: Failed to perform, curl: (28) "
            "Operation timed out after 20003 milliseconds with 0 bytes received."
        )
        self.assertEqual(
            normalize_task_output(message),
            "底层请求最终失败 | 请求超时：在超时时间内没有收到数据",
        )

    def test_log_bus_keeps_memory_events_and_writes_runtime_log(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "runtime.log"
            bus = LogBus(size=2, log_file=log_path)
            bus.emit("collector", "开始采集", "info")
            bus.emit("validator", "验证完成", "success")
            bus.emit("system", "第三条", "warning")

            self.assertEqual([event["message"] for event in bus.after(0)], ["验证完成", "第三条"])
            text = log_path.read_text(encoding="utf-8")
            self.assertIn("[collector] info | 开始采集", text)
            self.assertIn("[validator] success | 验证完成", text)

    def test_log_bus_keeps_configured_runtime_log_backups(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "runtime.log"
            config = SimpleNamespace(runtime_log_max_bytes=1, runtime_log_backup_count=2)
            with patch("runtime_tasks.CONFIG", config):
                bus = LogBus(size=10, log_file=log_path)
                bus.emit("system", "one", "info")
                bus.emit("system", "two", "info")
                bus.emit("system", "three", "info")
                bus.emit("system", "four", "info")

            self.assertTrue(log_path.exists())
            self.assertTrue(log_path.with_name("runtime.log.1").exists())
            self.assertTrue(log_path.with_name("runtime.log.2").exists())
            self.assertFalse(log_path.with_name("runtime.log.3").exists())


if __name__ == "__main__":
    unittest.main()
