from core.storage.base import BaseStorage
from core.storage.r2 import R2Storage

def get_storage(config: dict) -> BaseStorage:
    """根据配置动态加载具体的存储插件，默认使用 R2"""
    storage_type = config.get("storage_type", "r2").lower()
    
    if storage_type == "r2":
        return R2Storage(config)
    # 未来可在此扩展：
    # elif storage_type == "local":
    #     return LocalStorage(config)
    # elif storage_type == "webdav":
    #     return WebDavStorage(config)
    else:
        raise ValueError(f"不支持的存储介质: {storage_type}")
