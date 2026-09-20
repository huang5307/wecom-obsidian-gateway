import asyncio
import logging
import httpx
import yaml

logger = logging.getLogger("hermes_client")

# 读取 config.yaml 配置
try:
    with open("config.yaml", "r", encoding="utf-8") as f:
        _cfg = yaml.safe_load(f).get("hermes", {})
except Exception as e:
    _cfg = {}
    logger.warning(f"读取 config.yaml hermes 配置失败: {e}")

HERMES_API_URL = _cfg.get("api_url", "https://api.example.com/v1/chat/completions")
HERMES_API_KEY = _cfg.get("api_key", "")
HERMES_MODEL = _cfg.get("model", "hermes-agent")

def split_text_chunks(text: str, max_chars: int = 1800) -> list[str]:
    """段落切片保护：微信客服单条文本上限 2048 字符"""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    current_chunk = []
    current_len = 0

    for paragraph in text.split("\n"):
        p_len = len(paragraph) + 1
        if current_len + p_len > max_chars:
            if current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_len = 0
            while len(paragraph) > max_chars:
                chunks.append(paragraph[:max_chars])
                paragraph = paragraph[max_chars:]
            current_chunk.append(paragraph)
            current_len = len(paragraph)
        else:
            current_chunk.append(paragraph)
            current_len += p_len

    if current_chunk:
        chunks.append("\n".join(current_chunk))
    return chunks

async def forward_to_hermes_and_reply(
    external_userid: str,
    open_kfid: str,
    content: str,
    wecom_client
):
    """异步后台任务：调用 Hermes 并推回微信"""
    headers = {
        "Authorization": f"Bearer {HERMES_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": HERMES_MODEL,
        "messages": [{"role": "user", "content": content}],
        "user": external_userid
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(HERMES_API_URL, json=payload, headers=headers)
            if resp.status_code != 200:
                logger.error(f"Hermes 调用失败: {resp.status_code} - {resp.text}")
                await wecom_client.send_text_message(open_kfid, external_userid, "【系统提示】大脑思考超时，请稍后重试。")
                return

            res_json = resp.json()
            reply_text = res_json["choices"][0]["message"]["content"]

        chunks = split_text_chunks(reply_text, max_chars=1800)
        for i, chunk in enumerate(chunks):
            await wecom_client.send_text_message(open_kfid, external_userid, chunk)
            if i < len(chunks) - 1:
                await asyncio.sleep(0.5)

    except Exception as e:
        logger.exception(f"Hermes 转发异常: {str(e)}")
        await wecom_client.send_text_message(open_kfid, external_userid, "【系统提示】消息转发处理异常。")
