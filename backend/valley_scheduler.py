"""
后台低谷调度线程：每分钟检查时段，低谷时自动执行本地任务队列
"""
import threading
import time
import os
import logging
from pathlib import Path
from typing import Optional, Callable

from backend.time_price_judge import is_valley
from backend.task_queue_manager import dequeue, update_status, increment_retry, get_pending_count
from backend.llm_client import chat

logger = logging.getLogger("valley_scheduler")

_scheduler_thread: Optional[threading.Thread] = None
_running = False
_on_status_change: Optional[Callable[[int], None]] = None  # 队列数量变化回调（供 GUI 刷新）

MAX_TRANSCRIPT_LEN = 3000
POLL_INTERVAL = 60  # 轮询间隔（秒）
MAX_RETRY = 3


def start(callback: Optional[Callable[[int], None]] = None):
    """启动后台调度线程（程序启动时调用一次）"""
    global _scheduler_thread, _running, _on_status_change
    if _running:
        return
    _on_status_change = callback
    _running = True
    _scheduler_thread = threading.Thread(target=_loop, daemon=True, name="valley-scheduler")
    _scheduler_thread.start()
    logger.info("Valley scheduler started")


def stop():
    """停止调度线程"""
    global _running
    _running = False
    logger.info("Valley scheduler stopped")


def flush_now(force: bool = False) -> int:
    """
    手动立即执行所有待处理任务。
    force=True 时跳过峰谷检查（用于手动触发）。
    返回执行的任务数。
    """
    if not force and not is_valley():
        return 0
    tasks = dequeue(limit=50)
    executed = 0
    for task in tasks:
        try:
            _execute_one(task)
            executed += 1
        except Exception as e:
            logger.error(f"Flush task {task.get('task_id')}: {e}")
    _notify()
    return executed


def _loop():
    while _running:
        time.sleep(POLL_INTERVAL)
        try:
            if not is_valley():
                continue
            tasks = dequeue(limit=5)
            if not tasks:
                continue
            logger.info(f"Valley window: executing {len(tasks)} queued tasks")
            for task in tasks:
                try:
                    _execute_one(task)
                except Exception as e:
                    logger.error(f"Task {task.get('task_id')} failed: {e}")
            _notify()
        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")


def _execute_one(task: dict):
    task_id = task.get("task_id", "")
    task_type = task.get("task_type", "")
    payload = task.get("payload", {})

    if task_type == "single_summary":
        transcript = payload.get("transcript", "")
        title = payload.get("title", "")
        header = f"视频标题：{title}\n\n" if title else ""
        prompt = f"""{header}请用100字以内总结以下B站视频的核心观点。只输出总结，不要多余内容。

{transcript[:MAX_TRANSCRIPT_LEN]}"""
        result = chat(prompt)
        result_path = task.get("result_save_path", "")
        if result_path:
            try:
                Path(result_path).parent.mkdir(parents=True, exist_ok=True)
                Path(result_path).write_text(result, encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to save summary to {result_path}: {e}")
        update_status(task_id, "finished", result_save_path=result_path)

    elif task_type == "daily_report":
        logger.info("daily_report task type received but not yet implemented")
        update_status(task_id, "finished")

    elif task_type == "batch_parse":
        from backend.batch_parser import batch_parse
        uid_list = payload.get("uid_list", [])
        save_dir = payload.get("save_dir", "")
        target_date = payload.get("target_date", "")
        if not uid_list or not save_dir:
            update_status(task_id, "failed", error_msg="Missing uid_list or save_dir")
            return
        result = batch_parse(uid_list, save_dir, target_date=target_date or None)
        if result.get("success"):
            update_status(task_id, "finished",
                          result_save_path=os.path.join(save_dir, "batch_output"))
        else:
            update_status(task_id, "failed",
                          error_msg=result.get("error", "batch_parse failed"))

    else:
        logger.warning(f"Unknown task type: {task_type}")
        update_status(task_id, "failed", error_msg=f"Unknown type: {task_type}")


def _notify():
    """通知 GUI 队列状态变化"""
    if _on_status_change:
        try:
            _on_status_change(get_pending_count())
        except Exception:
            pass

