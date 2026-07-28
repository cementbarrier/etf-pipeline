"""
单视频 AI 摘要客户端：含时段判断分支，支持自动入队或强制执行
"""
from backend.llm_client import chat
from backend.time_price_judge import is_peak, get_warning_text, get_price_label
from backend.task_queue_manager import enqueue


MAX_TRANSCRIPT_LEN = 3000  # 送入 LLM 的最大转写文本长度


def summarize_single(
    bv_id: str,
    transcript: str,
    title: str = "",
    force: bool = False,
) -> dict:
    """
    单视频 AI 摘要。

    参数:
        bv_id:      视频 BV 号
        transcript: 完整转写文本
        title:      视频标题（可选）
        force:      True=强制执行（忽略时段），False=高峰自动入队

    返回:
        {"status": "done", "summary": "..."}  或
        {"status": "queued", "task_id": "xxx", "warning": "..."}
    """
    if not force and is_peak():
        task_id = enqueue(
            task_type="single_summary",
            payload={
                "bv_id": bv_id,
                "title": title,
                "transcript": transcript,
            },
        )
        return {
            "status": "queued",
            "task_id": task_id,
            "warning": get_warning_text(),
            "price_label": get_price_label(),
        }

    prompt = _build_prompt(transcript, title)
    try:
        summary = chat(prompt)
        return {"status": "done", "summary": summary}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _build_prompt(transcript: str, title: str = "") -> str:
    text = transcript[:MAX_TRANSCRIPT_LEN]
    header = ""
    if title:
        header = f"视频标题：{title}\n\n"
    return f"""{header}用80字以内总结以下B站视频中提到的股票核心观点。注意：所有股票名称/代码/公司名、数字（价格/点位/百分比/日期）、观点归属必须与原文严格一致，有疑问直接修正，不要输出修正过程。仅输出摘要正文，不要额外标记。

原文：
{text}"""



