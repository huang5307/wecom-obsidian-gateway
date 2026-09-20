import os
import re
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, Any
from core.storage.base import BaseStorage
import logging

logger = logging.getLogger("R2Storage")

class R2Storage(BaseStorage):
    def __init__(self, config: dict):
        r2_cfg = config.get("r2") if isinstance(config.get("r2"), dict) else config
        self.bucket_name = r2_cfg["bucket_name"]
        self._default_folder = str(r2_cfg.get("default_folder") or config.get("default_folder", "9-稍后处理")).strip().strip("/")
        self.endpoint_url = r2_cfg.get("endpoint_url")
        if not self.endpoint_url and r2_cfg.get("account_id"):
            self.endpoint_url = f"https://{r2_cfg['account_id']}.r2.cloudflarestorage.com"

        self.s3_client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=r2_cfg["access_key_id"],
            aws_secret_access_key=r2_cfg["secret_access_key"],
            region_name="auto"
        )
        raw_aliases = r2_cfg.get("aliases") or config.get("aliases", {})
        self._alias_map = self._parse_aliases(raw_aliases)

    def _parse_aliases(self, raw_aliases: dict) -> Dict[str, str]:
        mapping = {}
        for keys, target in (raw_aliases or {}).items():
            clean_target = str(target).strip().strip("/")
            for k in re.split(r"[,，]", str(keys)):
                clean_k = k.strip().strip('"').strip("'")
                if clean_k:
                    mapping[clean_k] = clean_target
                    mapping[clean_k.lower()] = clean_target
        return mapping

    @property
    def default_folder(self) -> str:
        return self._default_folder

    @property
    def alias_map(self) -> Dict[str, str]:
        return self._alias_map

    @property
    def storage_name(self) -> str:
        return f"Cloudflare R2 ({self.bucket_name})"

    def resolve_folder(self, raw_folder: Optional[str]) -> Tuple[str, str]:
        if not raw_folder:
            return self._default_folder, "default_unspecified"
        clean_req = str(raw_folder).strip().strip("/")
        if clean_req in self._alias_map:
            return self._alias_map[clean_req], "normal"
        if clean_req.lower() in self._alias_map:
            return self._alias_map[clean_req.lower()], "normal"
        for target in self._alias_map.values():
            if clean_req.lower() == target.lower():
                return target, "normal"
        if clean_req:
            return clean_req, "custom"
        return self._default_folder, "default_unspecified"

    def exists(self, rel_path: str) -> bool:
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=rel_path.lstrip("/"))
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "404":
                return False
            return False
        except Exception:
            return False

    def object_exists(self, key: str) -> bool:
        return self.exists(key)

    def check_conflict(self, target_folder: str, base_name: str, ext: str) -> bool:
        md_key = f"{target_folder}/{base_name}.md"
        att_key = f"{target_folder}/Attachments/{base_name}.{ext}" if ext else f"{target_folder}/Attachments/{base_name}"
        return self.exists(md_key) or self.exists(att_key)

    def save_attachment(self, filename: str, file_bytes: bytes, content_type: Optional[str] = None, target_folder: Optional[str] = None) -> str:
        clean_name = os.path.basename(filename)
        folder = (target_folder or getattr(self, 'default_folder', '')).strip('/')
        key = f"{folder}/Attachments/{clean_name}" if folder else f"Attachments/{clean_name}"
        extra = {}
        if content_type:
            extra["ContentType"] = content_type
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=file_bytes,
            **extra
        )
        return clean_name

    def build_markdown_content(
        self,
        base_name: str,
        ext: str,
        target_folder: str,
        routing_status: str,
        original_filename: str,
        title_source: str = "meaningful_filename"
    ) -> str:
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        now_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        att_rel_path = f"Attachments/{base_name}.{ext}" if ext else f"Attachments/{base_name}"

        return f"""---
title: "{base_name}"
source: "wecom"
saved_at: "{now_utc}"
target_folder: "{target_folder}"
routing_status: "{routing_status}"
title_source: "{title_source}"
original_filename: "{original_filename}"
attachment: "[[{att_rel_path}]]"
processing_status: "pending"
---

# {base_name}

![[{att_rel_path}]]

- 来源：微信客服
- 保存时间：{now_local}
- 目录：`{target_folder}/`
- 原始文件名：`{original_filename}`
"""

    def upload_archive(
        self,
        target_folder: str,
        base_name: str,
        ext: str,
        file_bytes: bytes,
        original_filename: str,
        routing_status: str = "normal",
        title_source: str = "user_provided"
    ) -> Dict[str, Any]:
        final_base_name = base_name
        if self.check_conflict(target_folder, final_base_name, ext):
            suffix = datetime.now().strftime("_%Y%m%d_%H%M%S")
            final_base_name = f"{base_name}{suffix}"

        att_key = f"{target_folder}/Attachments/{final_base_name}.{ext}" if ext else f"{target_folder}/Attachments/{final_base_name}"
        md_key = f"{target_folder}/{final_base_name}.md"

        # 【原生直通】如果本身就是 Markdown 文章/笔记，直接原样保存正文，不进 Attachments，不套引用，不加任何注记
        if ext.lower() in ("md", "markdown"):
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=md_key,
                Body=file_bytes,
                ContentType="text/markdown; charset=utf-8"
            )
            return {
                "key": md_key,
                "attachment_key": None,
                "folder": target_folder,
                "filename": f"{final_base_name}.md"
            }

        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=att_key,
            Body=file_bytes
        )

        md_content = self.build_markdown_content(
            base_name=final_base_name,
            ext=ext,
            target_folder=target_folder,
            routing_status=routing_status,
            original_filename=original_filename,
            title_source=title_source
        )
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=md_key,
            Body=md_content.encode("utf-8"),
            ContentType="text/markdown; charset=utf-8"
        )

        return {
            "success": True,
            "target_folder": target_folder,
            "base_name": final_base_name,
            "markdown_key": md_key,
            "attachment_key": att_key
        }

    def save_file(self, path: str, content: bytes, content_type: str = "text/markdown; charset=utf-8") -> bool:
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=path.lstrip("/"),
                Body=content,
                ContentType=content_type
            )
            return True
        except Exception as e:
            logger.error(f"Save file failed for {path}: {e}")
            return False

    def upload_bytes(self, data: bytes, key: str, content_type: str = "application/octet-stream"):
        return self.save_file(key, data, content_type)

    def upload_file(self, file_path: str, key: str):
        with open(file_path, "rb") as f:
            return self.save_file(key, f.read())
    def set_default_folder(self, new_folder: str) -> bool:
        clean = str(new_folder).strip().strip("/")
        self._default_folder = clean
        
        # 持久化回写 configs/storage_r2.yaml 与根目录 config.yaml
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        for rel in ["configs/storage_r2.yaml", "config.yaml"]:
            p = os.path.join(base_dir, rel)
            if os.path.exists(p):
                try:
                    import yaml
                    with open(p, "r", encoding="utf-8") as f:
                        d = yaml.safe_load(f) or {}
                    d["default_folder"] = clean
                    with open(p, "w", encoding="utf-8") as f:
                        yaml.dump(d, f, allow_unicode=True, sort_keys=False)
                    logger.info(f"[{rel}] 默认目录已永久更新落盘: {clean}")
                except Exception as e:
                    logger.error(f"持久化 {rel} 失败: {e}")
        return True
