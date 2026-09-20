import asyncio
import yaml
import os
from wecom_client import WeComClient
from r2_adapter import R2StorageAdapter
from filename_classifier import split_filename, is_meaningful_filename

async def run():
    with open("config.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    client = WeComClient(cfg["corp_id"], cfg["kf_secret"])
    r2 = R2StorageAdapter(cfg["r2"])
    kfid = cfg.get("open_kfid", "wkaSgqVAAAYTetbtsUPiG_fjk4QdYVbg")

    cursor = ""
    if os.path.exists("cursor.dat"):
        with open("cursor.dat", "r") as f:
            cursor = f.read().strip()

    print(f"[1] 开始从游标 '{cursor}' 追赶拉取队列消息...")
    has_more = 1
    total_msgs = []

    while has_more:
        res = await client.sync_messages(cursor=cursor, open_kfid=kfid)
        if res.get("errcode") != 0:
            print(f"拉取中断: {res}")
            break
        msgs = res.get("msg_list", [])
        total_msgs.extend(msgs)
        cursor = res.get("next_cursor", "")
        has_more = res.get("has_more", 0)
        print(f"    拉取到 {len(msgs)} 条，next_cursor: {cursor}, has_more: {has_more}")
        if not msgs:
            break

    with open("cursor.dat", "w") as f:
        f.write(cursor)
    print(f"[2] 累计拉取 {len(total_msgs)} 条消息，游标已同步至最新。")

    for msg in total_msgs:
        msgtype = msg.get("msgtype")
        if msg.get("origin") == 3 and msgtype == "file":
            file_info = msg.get("file", {})
            media_id = file_info.get("media_id")
            raw_filename = file_info.get("filename", "")
            ext_uid = msg.get("external_userid")
            msg_kfid = msg.get("open_kfid") or kfid

            print(f"\n[3] 锁定目标文件消息！media_id={media_id}, filename='{raw_filename}'")
            file_bytes, header_filename = await client.download_media(media_id)
            if header_filename:
                raw_filename = header_filename
            print(f"[4] 下载成功！体积={len(file_bytes)} 字节, 档名='{raw_filename}'")

            base_name, ext = split_filename(raw_filename)
            target_folder, routing_status = r2.resolve_folder()

            print(f"[5] 档名判定: '{base_name}' -> 有意义: {is_meaningful_filename(base_name)}")
            upload_res = r2.upload_archive(
                target_folder=target_folder,
                base_name=base_name,
                ext=ext,
                file_bytes=file_bytes,
                original_filename=raw_filename,
                routing_status=routing_status,
                title_source="meaningful_filename"
            )
            print(f"[6] R2 上传结果: {upload_res}")

            if upload_res.get("success"):
                att_name = f"{base_name}.{ext}" if ext else base_name
                reply_text = (
                    f"✅ 已保存\n"
                    f"📁 目录：{target_folder}/\n"
                    f"📄 档案：{base_name}.md\n"
                    f"📎 附件：Attachments/{att_name}"
                )
                send_res = await client.send_text_message(msg_kfid, ext_uid, reply_text)
                print(f"[7] 微信回执推送: {send_res}")

asyncio.run(run())
