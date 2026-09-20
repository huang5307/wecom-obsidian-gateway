import json
import os
import time

PENDING_FILE = "pending_tasks.json"
TEMP_DIR = "/root/wecom-archive/temp_quarantine"
os.makedirs(TEMP_DIR, exist_ok=True)

class PendingManager:
    def __init__(self, file_path: str = PENDING_FILE):
        self.file_path = file_path
        self.data = self._load()

    def _load(self) -> dict:
        default_data = {"pending_tasks": {}, "session_folders": {}}
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    if isinstance(content, dict):
                        if "pending_tasks" not in content:
                            content = {"pending_tasks": content, "session_folders": {}}
                        if "session_folders" not in content:
                            content["session_folders"] = {}
                        return content
            except Exception:
                pass
        return default_data

    def _save(self):
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    # ---------- 会话默认目录管理 ----------
    def set_session_folder(self, user_id: str, folder: str):
        self.data.setdefault("session_folders", {})[user_id] = {
            "folder": folder,
            "set_at": time.time()
        }
        self._save()

    def get_session_folder(self, user_id: str) -> str | None:
        item = self.data.get("session_folders", {}).get(user_id)
        return item.get("folder") if item else None

    def clear_session_folder(self, user_id: str):
        if user_id in self.data.get("session_folders", {}):
            del self.data["session_folders"][user_id]
            self._save()

    # ---------- 待确认任务管理 ----------
    def create_pending(
        self,
        user_id: str,
        temp_file_path: str,
        original_filename: str,
        ext: str,
        target_folder: str,
        routing_status: str,
        reason: str = "awaiting_title"
    ) -> str:
        pending_id = f"p-{int(time.time()) % 10000:04d}"
        self.data.setdefault("pending_tasks", {})[user_id] = {
            "pending_id": pending_id,
            "temp_file_path": temp_file_path,
            "original_filename": original_filename,
            "ext": ext,
            "target_folder": target_folder,
            "routing_status": routing_status,
            "reason": reason,
            "created_at": time.time()
        }
        self._save()
        return pending_id

    def get_pending(self, user_id: str) -> dict | None:
        return self.data.get("pending_tasks", {}).get(user_id)

    def pop_pending(self, user_id: str) -> dict | None:
        tasks = self.data.get("pending_tasks", {})
        item = tasks.pop(user_id, None)
        if item:
            self._save()
        return item

    def clear_pending(self, user_id: str):
        tasks = self.data.get("pending_tasks", {})
        if user_id in tasks:
            temp_path = tasks[user_id].get("temp_file_path")
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            del tasks[user_id]
            self._save()
