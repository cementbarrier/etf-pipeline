"""
本地持久化任务队列管理器：基于 JSON 文件的轻量级任务队列
"""
import json
import os
import uuid
import threading
from datetime import datetime
from typing import Optional, Literal

QUEUE_DIR = os.path.join(os.path.dirname(__file__), "task_queue")
QUEUE_FILE = os.path.join(QUEUE_DIR, "llm_delay_queue.json")
_lock = threading.Lock()

TaskType = Literal["single_summary", "daily_report", "batch_parse"]
TaskStatus = Literal["pending", "finished", "failed", "cancelled"]


def _ensure_dir():
    os.makedirs(QUEUE_DIR, exist_ok=True)


def _read_queue() -> list[dict]:
    """读取队列全部任务"""
    _ensure_dir()
    if not os.path.exists(QUEUE_FILE):
        return []
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def _write_queue(tasks: list[dict]):
    """写入队列"""
    _ensure_dir()
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)


def enqueue(
    task_type: TaskType,
    payload: dict,
    result_save_path: str = "",
) -> str:
    """入队一个新任务，返回 task_id"""
    with _lock:
        tasks = _read_queue()
        task_id = uuid.uuid4().hex[:12]
        task = {
            "task_id": task_id,
            "task_type": task_type,
            "create_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "target_execute_window": "valley",
            "payload": payload,
            "status": "pending",
            "result_save_path": result_save_path,
            "retry_count": 0,
            "error_msg": "",
        }
        tasks.append(task)
        _write_queue(tasks)
    return task_id


def dequeue(limit: int = 10) -> list[dict]:
    """取出最多 limit 条 status=pending 的任务（不移除，执行完后需更新状态）"""
    with _lock:
        tasks = _read_queue()
        pending = [t for t in tasks if t.get("status") == "pending"]
        return pending[:limit]


def update_status(
    task_id: str,
    status: TaskStatus,
    error_msg: str = "",
    result_save_path: str = "",
):
    """更新任务状态"""
    with _lock:
        tasks = _read_queue()
        for t in tasks:
            if t.get("task_id") == task_id:
                t["status"] = status
                if error_msg:
                    t["error_msg"] = error_msg
                if result_save_path:
                    t["result_save_path"] = result_save_path
                break
        _write_queue(tasks)


def increment_retry(task_id: str) -> int:
    """重试计数+1，返回新的重试次数"""
    with _lock:
        tasks = _read_queue()
        for t in tasks:
            if t.get("task_id") == task_id:
                t["retry_count"] = t.get("retry_count", 0) + 1
                _write_queue(tasks)
                return t["retry_count"]
    return 0


def get_pending_count() -> int:
    """获取待执行任务数量（线程安全）"""
    with _lock:
        tasks = _read_queue()
        return sum(1 for t in tasks if t.get("status") == "pending")


def get_queue_stats() -> dict:
    """获取队列统计概览"""
    tasks = _read_queue()
    status_counts = {}
    for t in tasks:
        s = t.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1
    recent_failed = []
    for t in tasks:
        if t.get("status") == "failed" and t.get("error_msg"):
            recent_failed.append({
                "task_id": t.get("task_id"),
                "task_type": t.get("task_type"),
                "error": t["error_msg"],
            })
            if len(recent_failed) >= 3:
                break
    return {
        "total": len(tasks),
        "by_status": status_counts,
        "recent_failed": recent_failed,
    }


def clean_finished(days: int = 7):
    """清理超过指定天数已完成的旧任务"""
    with _lock:
        tasks = _read_queue()
        cutoff = datetime.now().strftime("%Y-%m-%d")
        kept = []
        for t in tasks:
            if t.get("status") in ("finished", "cancelled"):
                create = t.get("create_time", "")[:10]
                if create and create < cutoff:
                    continue
            kept.append(t)
        _write_queue(kept)

