import os
import re

# 规范 4.3 节无意义通用词根库（覆盖简/繁/英及各类工具默认前缀）[cite: 1]
GENERIC_STEMS = [
    # 扫描类
    "扫描文档", "扫描文件", "扫描件", "扫描全能王", "扫描",
    "掃描文件", "掃描檔案", "掃描件", "掃描",
    "scanned copy", "scanned_copy", "scanned doc", "scanned document", "scanned",
    "camscanner", "scanner", "scan", "cs",
    # 截图与截屏类
    "屏幕截图", "螢幕截圖", "截屏", "截图", "截圖",
    "screenshot", "screen_shot", "screen shot", "screen", "capture", "snapshot",
    # 相机与多媒体类
    "微信图片", "微信相片", "照片", "相片", "图片", "圖片",
    "img", "image", "photo", "picture", "pic", "dsc", "dcim", "wx_camera", "mmexport",
    # 默认新建与泛化模板[cite: 1]
    "新建文本文档", "新建文件", "新建表格", "新建工作表", "新建演示文稿",
    "新建 microsoft word 文档", "新建 microsoft excel 工作表", "新建",
    "未命名文档", "未命名", "文档", "文件", "表格", "檔案",
    "untitled", "document", "doc", "file", "new",
    # 副本与导出
    "副本", "copy", "backup", "备份", "備份", "export"
]

def split_filename(filename: str) -> tuple[str, str]:
    """分离文件名中的基础名与最后一个扩展名"""
    clean_name = os.path.basename(filename).strip()
    if "." in clean_name and not clean_name.startswith("."):
        base, ext = clean_name.rsplit(".", 1)
        return base.strip(), ext.strip()
    return clean_name, ""

def is_meaningful_filename(base_name: str) -> bool:
    """
    档名语义判定算法：
    1. 过滤纯符号/日期/哈希/企微内部 Token[cite: 1]。
    2. 剥离所有日期、时间戳、流水号及连接符[cite: 1, 2]。
    3. 剥离通用词根，检查是否存在剩余的有意义实体主题词素[cite: 1]。
    """
    if not base_name or base_name in (".", ".."):
        return False

    clean = base_name.strip()
    lower = clean.lower()

    # 1. 拦截企微 Media ID 或纯长哈希（连续 16 字符以上且无空格分词）[cite: 1]
    if re.match(r"^[0-9a-zA-Z_\-]{16,}$", clean):
        parts = clean.split("_")
        if len(parts) == 1 or len(clean) > 30:
            return False

    # 2. 剥离所有的日期、时间戳、纯数字（如 2025-08-22, 16-06-42, 260610_122604 等）[cite: 2]
    residual = re.sub(r"\d+", "", lower)
    # 剥离连接符号与空白
    residual = re.sub(r"[\s_\-\.\:\/\(\)\[\]（）]+", " ", residual).strip()

    # 若剔除数字和符号后为空（纯时间戳/纯数字），直接判定无意义[cite: 1]
    if not residual:
        return False

    # 3. 剥离泛化词根[cite: 1]
    for stem in sorted(GENERIC_STEMS, key=len, reverse=True):
        residual = residual.replace(stem, "").strip()

    # 4. 检查剩余的有效语义片段[cite: 1]
    has_chinese = bool(re.search(r"[\u4e00-\u9fa5]", residual))
    has_word = bool(re.search(r"[a-zA-Z]{2,}", residual))

    # 若剥离泛化词根后没有任何实质主题词素，判定为无意义[cite: 1]
    if not (has_chinese or has_word):
        return False

    return True
