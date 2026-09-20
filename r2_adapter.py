import os
import boto3
from botocore.exceptions import ClientError
from datetime import datetime, timezone

class R2StorageAdapter:
    def __init__(self, r2_config: dict):
        self.bucket_name = r2_config["bucket_name"]
        self.default_folder = r2_config.get("default_folder", "9-稍后处理").strip().strip("/")
        self.endpoint_url = r2_config.get("endpoint_url")
        if not self.endpoint_url:
            self.endpoint_url = f"https://{r2_config['account_id']}.r2.cloudflarestorage.com"
        
        self.s3_client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=r2_config["access_key_id"],
            aws_secret_access_key=r2_config["secret_access_key"],
            region_name="auto"
        )
        self.alias_map = self._parse_aliases(r2_config.get("aliases", {}))

    def _parse_aliases(self, raw_aliases: dict) -> dict:
        mapping = {}
        for keys, target in (raw_aliases or {}).items():
            clean_target = str(target).strip().strip("/")
            for k in str(keys).split(","):
                clean_k = k.strip().strip('"').strip("'")
                if clean_k:
                    mapping[clean_k] = clean_target
        return mapping

    def resolve_folder(self, requested_folder: str = None) -> tuple[str, str]:
        if not requested_folder:
            return self.default_folder, "default_unspecified"
        
        clean_req = requested_folder.strip().strip("/")
        if clean_req in self.alias_map:
            return self.alias_map[clean_req], "explicit_alias"
        if clean_req:
            return clean_req, "explicit_path"
        return self.default_folder, "default_unspecified"

    def object_exists(self, key: str) -> bool:
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise

    def check_conflict(self, target_folder: str, base_name: str, ext: str) -> bool:
        md_key = f"{target_folder}/{base_name}.md"
        att_key = f"{target_folder}/Attachments/{base_name}.{ext}" if ext else f"{target_folder}/Attachments/{base_name}"
        return self.object_exists(md_key) or self.object_exists(att_key)

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
        routing_status: str = "default_unspecified",
        title_source: str = "meaningful_filename"
    ) -> dict:
        # 遇同名自动在基础档名后附加时间戳
        final_base_name = base_name
        if self.check_conflict(target_folder, final_base_name, ext):
            suffix = datetime.now().strftime("_%Y%m%d_%H%M%S")
            final_base_name = f"{base_name}{suffix}"

        att_key = f"{target_folder}/Attachments/{final_base_name}.{ext}" if ext else f"{target_folder}/Attachments/{final_base_name}"
        md_key = f"{target_folder}/{final_base_name}.md"

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
