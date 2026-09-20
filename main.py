from core.config import load_config
import asyncio
import os
import re
import yaml
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response

from wecom_crypto import WeComCrypto
from wecom_client import WeComClient
from core.storage import get_storage
from pending_manager import PendingManager
from services.dispatcher import MessageDispatcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("main")

config = load_config()

# 初始化凭证与客户端
crypto = WeComCrypto(
    token=config.get("token"),
    encoding_aes_key=config.get("encoding_aes_key"),
    corp_id=config.get("corp_id")
)
wecom_client = WeComClient(
    corp_id=config.get("corp_id"),
    secret=config.get("kf_secret")
)

# 加载插件化存储引擎与分发器
storage = get_storage(config)
pending_mgr = PendingManager()
dispatcher = MessageDispatcher(
    wecom_client=wecom_client,
    storage=storage,
    pending_manager=pending_mgr,
    config=config
)

CURSOR_FILE = os.path.expanduser("~/wecom-archive/cursor.dat")

def load_cursor() -> str:
    if os.path.exists(CURSOR_FILE):
        try:
            with open(CURSOR_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return ""
    return ""

def save_cursor(cursor: str):
    try:
        with open(CURSOR_FILE, "w", encoding="utf-8") as f:
            f.write(cursor.strip())
    except Exception as e:
        logger.error(f"保存 cursor 失败: {e}")

sync_lock = asyncio.Lock()
sync_requested = False

async def sync_and_dispatch():
    global sync_requested
    if sync_lock.locked():
        sync_requested = True
        return

    async with sync_lock:
        while True:
            sync_requested = False
            # 缓冲等待 1 秒，聚合微信同时发出的卡片与留言附言
            await asyncio.sleep(1.0)
            try:
                cursor = load_cursor()
                has_more = 1
                while has_more == 1:
                    data = await wecom_client.sync_messages(token=None, cursor=cursor, open_kfid=config.get("open_kfid"))
                    msg_list = data.get("msg_list", [])
                    has_more = data.get("has_more", 0)
                    next_cursor = data.get("next_cursor", "")
                    if next_cursor:
                        cursor = next_cursor
                        save_cursor(cursor)
                    if msg_list:
                        logger.info(f"[合并拉取] 批次消息数: {len(msg_list)}, has_more: {has_more}")
                        await dispatcher.process_batch_messages(msg_list, default_kfid=config.get("open_kfid"))
                    if not msg_list and has_more == 0:
                        break
            except Exception as e:
                logger.error(f"[同步异常]: {e}")

            if not sync_requested:
                break

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"[服务启动] 当前挂载存储插件: {storage.storage_name}")
    asyncio.create_task(sync_and_dispatch())
    yield
    logger.info("[服务关闭]")

app = FastAPI(lifespan=lifespan)

@app.get("/wecom/callback")
async def verify_url(msg_signature: str, timestamp: str, nonce: str, echostr: str):
    try:
        reply_echo = crypto.verify_url(msg_signature, timestamp, nonce, echostr)
        return Response(content=reply_echo, media_type="text/plain")
    except Exception as e:
        logger.error(f"[URL 验签失败]: {e}")
        return Response(content="签名验证失败", status_code=403)

@app.post("/wecom/callback")
async def handle_callback(request: Request, msg_signature: str, timestamp: str, nonce: str):
    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8")

    encrypt_match = re.search(r"<Encrypt><!\[CDATA\[(.*?)\]\]></Encrypt>", body_str, re.DOTALL)
    if not encrypt_match:
        encrypt_match = re.search(r"<Encrypt>(.*?)</Encrypt>", body_str, re.DOTALL)
    if not encrypt_match:
        return Response(content="缺少 Encrypt 节点", status_code=400)

    encrypt_text = encrypt_match.group(1).strip()
    if crypto._get_signature(timestamp, nonce, encrypt_text) != msg_signature:
        logger.warning("[回调拦截] 签名不匹配")
        return Response(content="签名验证失败", status_code=403)

    try:
        xml_content = crypto.decrypt(encrypt_text)
    except Exception as e:
        logger.error(f"[回调解密失败]: {e}")
        return Response(content="解密失败", status_code=403)

    event_match = re.search(r"<Event><!\[CDATA\[(.*?)\]\]></Event>", xml_content)
    if not event_match:
        event_match = re.search(r"<Event>(.*?)</Event>", xml_content)
    event_type = event_match.group(1).strip() if event_match else ""

    if event_type == "kf_msg_or_event":
        asyncio.create_task(sync_and_dispatch())

    return Response(content="success", media_type="text/plain")

from routes_api import register_api_routes
register_api_routes(app, storage, config)
