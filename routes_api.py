import logging, os, re, time
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from services.url_archiver import extract_first_url, fetch_url_to_markdown

logger = logging.getLogger("wecom-archive")
api_router = APIRouter()
API_KEY = APIKeyHeader(name="X-API-Key", auto_error=False)

class Req(BaseModel):
    content: str
    instruction: str = ""
    folder: str = ""

async def _bg(c, ins, st):
    url, _ = extract_first_url(c)
    target_f, _ = st.resolve_folder(ins)
    print(f"⚙️ [后台保存] 目录已锁定为: '{target_f}' | 文章/内容: {c[:40]}...", flush=True)
    try:
        if url:
            doc = await fetch_url_to_markdown(url=url, storage=st, target_folder=target_f)
            t = re.sub(r'[\s\\/:*?"<>|]+', '_', doc.get("title") or "网页归档").strip('_') or "网页归档"
            st.upload_archive(target_folder=target_f, base_name=t, ext="md", file_bytes=doc["markdown"].encode("utf-8"), original_filename=f"{t}.md")
            logger.info(f"归档成功: {t}")
        else:
            n = f"{time.strftime('%Y%m%d_%H%M%S')}_随手记"
            st.upload_archive(target_folder=target_f, base_name=n, ext="md", file_bytes=f"# 随手记\n\n{c}\n".encode("utf-8"), original_filename=f"{n}.md")
    except Exception as e:
        logger.error(f"归档异常: {e}")

@api_router.post("/api/archive")
async def archive(r: Req, req: Request, bg: BackgroundTasks, k: str = Security(API_KEY)):
    st = req.app.state.storage
    if k != req.app.state.config.get("server", {}).get("api_key", "sec_obsidian_gateway_2026"):
        raise HTTPException(401, "Invalid Key")
    
    raw_ins = r.instruction or r.folder or ""
    f, _ = st.resolve_folder(raw_ins)
    
    print(f"📥 [API收到请求] 手机客户端传参 instruction='{raw_ins}' -> 解析目标: '{f}'", flush=True)
    
    bg.add_task(_bg, r.content.strip(), raw_ins.strip(), st)
    return {"code": 0, "message": f"已接收，转存至 {f}/", "data": {"status": "processing", "target_folder": f}}

def register_api_routes(app, storage=None, config=None, *args, **kwargs):
    if storage:
        app.state.storage = storage
    if config:
        app.state.config = config
    app.include_router(api_router)
