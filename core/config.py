import os
import yaml
import logging

logger = logging.getLogger("ConfigLoader")

def load_config() -> dict:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg_dir = os.path.join(base_dir, "configs")
    
    merged = {}
    
    # 若存在新版模块化配置目录，优先合并加载
    if os.path.exists(cfg_dir):
        # 1. 加载 app.yaml
        app_file = os.path.join(cfg_dir, "app.yaml")
        if os.path.exists(app_file):
            with open(app_file, "r", encoding="utf-8") as f:
                merged.update(yaml.safe_load(f) or {})

        # 2. 加载 wecom.yaml
        wecom_file = os.path.join(cfg_dir, "wecom.yaml")
        if os.path.exists(wecom_file):
            with open(wecom_file, "r", encoding="utf-8") as f:
                merged.update(yaml.safe_load(f) or {})

        # 3. 加载 storage_r2.yaml
        r2_file = os.path.join(cfg_dir, "storage_r2.yaml")
        if os.path.exists(r2_file):
            with open(r2_file, "r", encoding="utf-8") as f:
                r2_data = yaml.safe_load(f) or {}
                merged["r2"] = r2_data
                merged["storage_type"] = merged.get("active_storage", "r2")
                # 兼容旧代码直读根级属性
                for k in ["default_folder", "aliases", "endpoint_url", "access_key_id", "secret_access_key", "bucket_name"]:
                    if k in r2_data and k not in merged:
                        merged[k] = r2_data[k]

        # 4. 加载 ai_hermes.yaml
        hermes_file = os.path.join(cfg_dir, "ai_hermes.yaml")
        if os.path.exists(hermes_file):
            with open(hermes_file, "r", encoding="utf-8") as f:
                merged["hermes"] = yaml.safe_load(f) or {}

        return merged

    # 兜底旧版单文件 config.yaml
    old_file = os.path.join(base_dir, "config.yaml")
    if os.path.exists(old_file):
        with open(old_file, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    raise FileNotFoundError("未找到有效配置文件！请检查 configs/ 目录或 config.yaml")
