import tempfile
import unittest
from pathlib import Path

from runtime_tasks import LogBus, normalize_task_output


class RuntimeTasksTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
