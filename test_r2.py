import yaml
from r2_adapter import R2StorageAdapter

def main():
    print("=== [开始测试 Cloudflare R2 存储适配器] ===")
    with open("config.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    r2 = R2StorageAdapter(cfg["r2"])
    print(f"[1] 适配器初始化成功，目标存储桶: {r2.bucket_name}")
    print(f"    解析到的别名映射: {r2.alias_map}")

    # 1. 测试目录别名路由
    folder, status = r2.resolve_folder("临时")
    print(f"[2] 目录解析测试: 输入 '临时' -> 实际目录: '{folder}', 状态: {status}")
    assert folder == "9-稍后处理", "别名映射失败"

    # 2. 测试写入一份规范档案
    test_base_name = "模块2归档链路测试文档"
    test_ext = "txt"
    test_content = b"This is a test attachment payload for WeCom R2 Gateway."
    original_file = "模块2归档链路测试文档.txt"

    print(f"[3] 正在上传测试档案至: {folder}/ ...")
    res = r2.upload_archive(
        target_folder=folder,
        base_name=test_base_name,
        ext=test_ext,
        file_bytes=test_content,
        original_filename=original_file,
        routing_status=status
    )
    print("    上传执行结果:", res)
    assert res["success"] is True, "归档上传失败"

    # 3. 测试同名冲突保护（规则铁律：绝不覆盖）
    print("[4] 正在触发同名冲突测试（重新提交同名文件）...")
    conflict_res = r2.upload_archive(
        target_folder=folder,
        base_name=test_base_name,
        ext=test_ext,
        file_bytes=test_content,
        original_filename=original_file
    )
    print("    冲突拦截结果:", conflict_res)
    assert conflict_res["success"] is False and conflict_res["reason"] == "conflict", "同名冲突拦截失效！"
    print(f"    已成功拦截冲突，冲突对象: {conflict_res['conflict_key']}")

    print("\n=== [恭喜：Cloudflare R2 适配器全部单测通过！] ===")

if __name__ == "__main__":
    main()
