from abc import ABC, abstractmethod
from typing import Tuple, Dict, Any, Optional

class BaseStorage(ABC):
    """通用知识库存储抽象基类 (Storage Provider Interface)"""

    @property
    @abstractmethod
    def default_folder(self) -> str:
        """全局兜底归档目录"""
        pass

    @property
    @abstractmethod
    def alias_map(self) -> Dict[str, str]:
        """目录代号/别名映射字典"""
        pass

    @property
    @abstractmethod
    def storage_name(self) -> str:
        """存储介质标识名称（如 R2 / Local / WebDAV）"""
        pass

    @abstractmethod
    def resolve_folder(self, raw_folder: Optional[str]) -> Tuple[str, str]:
        """将用户输入的别名解析为标准物理路径"""
        pass

    @abstractmethod
    def exists(self, rel_path: str) -> bool:
        """检查相对路径文件是否存在（用于冲突检测）"""
        pass

    @abstractmethod
    def save_attachment(self, filename: str, file_bytes: bytes, content_type: Optional[str] = None) -> str:
        """将附件/配图统一存入 Attachments/ 目录，返回保存后的文件名"""
        pass

    @abstractmethod
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
        """归档主流程：保存实体文件与伴生 Markdown 档案"""
        pass
    @abstractmethod
    def set_default_folder(self, new_folder: str) -> bool:
        """动态修改全局默认归档目录并持久化落盘"""
        pass
