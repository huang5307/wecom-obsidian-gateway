import asyncio
import os
import re
import time
import logging
from instruction_parser import parse_companion_instruction
from filename_classifier import is_meaningful_filename, split_filename
from commands.hermes import handle_hermes_command
from services.url_archiver import extract_first_url, fetch_url_to_markdown

logger = logging.getLogger("services.dispatcher")

class MessageDispatcher:
    def __init__(self, wecom_client, storage=None, r2_adapter=None, pending_manager=None, config=None, temp_dir="temp_quarantine"):
        self.client = wecom_client
        self.storage = storage or r2_adapter
        self.r2 = self.storage
        self.pending_mgr = pending_manager
        self.config = config
        self.temp_dir = temp_dir
        self.active_conflicts = {}  # 用于管理同名冲突的异步响应
        os.makedirs(self.temp_dir, exist_ok=True)

    def cleanup_quarantine(self, max_age_hours: int = 24):
        """自动清理超过 24 小时的孤儿临时文件"""
        try:
            now = time.time()
            max_age_sec = max_age_hours * 3600
            if not os.path.exists(self.temp_dir):
                return
            for fname in os.listdir(self.temp_dir):
                fpath = os.path.join(self.temp_dir, fname)
                if os.path.isfile(fpath):
                    if now - os.path.getmtime(fpath) > max_age_sec:
                        os.remove(fpath)
                        logger.info(f"已自动清理过期暂存文件: {fname}")
        except Exception as e:
            logger.warning(f"清理暂存文件异常: {e}")

    def check_file_exists(self, target_folder: str, base_name: str, ext: str = "md") -> bool:
        """检查目标目录下是否已存在同名档案（走存储抽象接口）"""
        return self.storage.exists(f"{target_folder}/{base_name}.{ext}")

    def get_next_available_name(self, target_folder: str, base_name: str, ext: str = "md") -> str:
        """查找下一个可用文件名（追加 _1, _2 等）"""
        idx = 1
        while True:
            candidate = f"{base_name}_{idx}"
            if not self.check_file_exists(target_folder, candidate, ext):
                return candidate
            idx += 1

    async def ensure_service_state(self, open_kfid: str, external_userid: str):
        try:
            curr_state = await self.client.get_service_state(open_kfid, external_userid)
            if curr_state != 3:
                await self.client.trans_service_state(open_kfid, external_userid, 3)
        except Exception as e:
            logger.warning(f"服务状态转换异常 (忽略): {e}")

    async def process_batch_messages(self, msg_list: list, default_kfid: str):
        self.cleanup_quarantine()

        user_buckets = {}
        for m in msg_list:
            uid = m.get("external_userid")
            if uid:
                user_buckets.setdefault(uid, []).append(m)

        for external_userid, msgs in user_buckets.items():
            msgs.sort(key=lambda x: x.get("send_time", 0))

            media_msgs = [m for m in msgs if m.get("msgtype") in ("file", "image")]
            link_msgs = [m for m in msgs if m.get("msgtype") == "link"]
            text_msgs = [m for m in msgs if m.get("msgtype") == "text"]

            paired_text_ids = set()

            for media_msg in media_msgs:
                m_time = media_msg.get("send_time", 0)
                companion_text = ""
                for text_msg in text_msgs:
                    t_time = text_msg.get("send_time", 0)
                    if abs(t_time - m_time) <= 2 and text_msg["msgid"] not in paired_text_ids:
                        companion_text = text_msg.get("text", {}).get("content", "").strip()
                        paired_text_ids.add(text_msg["msgid"])
                        break

                try:
                    await self.handle_media_archive(
                        msg=media_msg,
                        external_userid=external_userid,
                        default_kfid=default_kfid,
                        companion_text=companion_text
                    )
                except Exception as e:
                    logger.error(f"[附件处理异常]: {e}")

            for link_msg in link_msgs:
                l_time = link_msg.get("send_time", 0)
                companion_text = ""
                for text_msg in text_msgs:
                    t_time = text_msg.get("send_time", 0)
                    if abs(t_time - l_time) <= 2 and text_msg["msgid"] not in paired_text_ids:
                        companion_text = text_msg.get("text", {}).get("content", "").strip()
                        paired_text_ids.add(text_msg["msgid"])
                        break

                try:
                    await self.handle_link_archive(
                        msg=link_msg,
                        external_userid=external_userid,
                        default_kfid=default_kfid,
                        companion_text=companion_text
                    )
                except Exception as e:
                    logger.error(f"[Link 卡片归档异常]: {e}")

            for text_msg in text_msgs:
                if text_msg["msgid"] in paired_text_ids:
                    continue
                try:
                    await self.handle_standalone_text(
                        msg=text_msg,
                        external_userid=external_userid,
                        default_kfid=default_kfid
                    )
                except Exception as e:
                    logger.error(f"[文本处理异常]: {e}")

    async def handle_link_archive(self, msg: dict, external_userid: str, default_kfid: str, companion_text: str = ""):
        msg_kfid = msg.get("open_kfid") or default_kfid
        await self.ensure_service_state(msg_kfid, external_userid)

        link_info = msg.get("link", {})
        url = link_info.get("url", "").strip()
        card_title = link_info.get("title", "").strip()
        if not url:
            return

        req_folder, explicit_name = parse_companion_instruction(companion_text, self.r2.alias_map)
        session_folder = self.pending_mgr.get_session_folder(external_userid)
        target_folder, routing_status = self.r2.resolve_folder(req_folder or session_folder)

        await self._archive_url_content(
            url=url,
            fallback_title=card_title,
            explicit_name=explicit_name,
            target_folder=target_folder,
            routing_status=routing_status,
            msg_kfid=msg_kfid,
            external_userid=external_userid
        )

    async def _archive_url_content(self, url: str, fallback_title: str, explicit_name: str | None,
                                   target_folder: str, routing_status: str, msg_kfid: str, external_userid: str):
        await self.client.send_text_message(msg_kfid, external_userid, "⏳ 正在抓取正文及配图并转换 Markdown...")
        parsed = await fetch_url_to_markdown(url, fallback_title=fallback_title, storage=self.storage)

        title = explicit_name if explicit_name else parsed["title"]
        safe_title = re.sub(r'[\r\n\t\\/:*?"<>| ]+', '_', title).strip('_') or "网页归档"
        final_base_name = safe_title

        # 同名检测与冲突确认
        if self.check_file_exists(target_folder, final_base_name, "md"):
            candidate_name = self.get_next_available_name(target_folder, final_base_name, "md")
            evt = asyncio.Event()
            conflict_info = {"event": evt, "decision": "timeout", "new_name": candidate_name, "target_folder": target_folder}
            self.active_conflicts[external_userid] = conflict_info

            warn_text = (
                f"⚠️ 提示：在【{target_folder}/】中已存在同名档案“{final_base_name}.md”。\n"
                f"• 直接回复新名称：按新名称保存\n"
                f"• 回复“取消”：放弃本次归档\n"
                f"⏱️ 20 秒内未回复将自动保存为：{candidate_name}.md"
            )
            await self.client.send_text_message(msg_kfid, external_userid, warn_text)

            try:
                await asyncio.wait_for(evt.wait(), timeout=20.0)
            except asyncio.TimeoutError:
                pass
            finally:
                self.active_conflicts.pop(external_userid, None)

            if conflict_info["decision"] == "cancel":
                await self.client.send_text_message(msg_kfid, external_userid, "已取消本次保存。")
                return
            elif conflict_info["decision"] == "rename":
                final_base_name = re.sub(r'[\r\n\t\\/:*?"<>| ]+', '_', conflict_info["new_name"]).strip('_')
                target_folder = conflict_info.get("target_folder", target_folder)
            else:
                final_base_name = candidate_name

        upload_res = self.r2.upload_archive(
            target_folder=target_folder,
            base_name=final_base_name,
            ext="md",
            file_bytes=parsed["markdown"].encode("utf-8"),
            original_filename=f"{final_base_name}.md",
            routing_status=routing_status,
            title_source="user_provided" if explicit_name else "meaningful_filename"
        )

        saved_name = upload_res["base_name"]
        reply_text = (
            f"✅ 网页已归档\n"
            f"📁 目录：{target_folder}/\n"
            f"📄 档案：{saved_name}.md\n"
            f"🔗 标题：{parsed['title']}"
        )
        await self.client.send_text_message(msg_kfid, external_userid, reply_text)

    async def handle_media_archive(self, msg: dict, external_userid: str, default_kfid: str, companion_text: str = ""):
        msg_kfid = msg.get("open_kfid") or default_kfid
        msgtype = msg.get("msgtype")
        await self.ensure_service_state(msg_kfid, external_userid)

        req_folder, explicit_name = parse_companion_instruction(companion_text, self.r2.alias_map)
        session_folder = self.pending_mgr.get_session_folder(external_userid)
        target_folder, routing_status = self.r2.resolve_folder(req_folder or session_folder)

        media_id = ""
        raw_filename = ""
        if msgtype == "file":
            file_info = msg.get("file", {})
            media_id = file_info.get("media_id")
            raw_filename = file_info.get("filename", "")
        elif msgtype == "image":
            image_info = msg.get("image", {})
            media_id = image_info.get("media_id")
            raw_filename = f"IMG_{int(time.time())}.jpg"

        file_bytes, header_filename = await self.client.download_media(media_id)
        if header_filename and not header_filename.startswith(media_id) and msgtype == "file":
            raw_filename = header_filename

        orig_base, ext = split_filename(raw_filename)
        final_base_name = explicit_name if explicit_name else orig_base
        title_src = "user_provided" if explicit_name else "meaningful_filename"

        if is_meaningful_filename(final_base_name):
            # 同名检测与冲突处理
            if self.check_file_exists(target_folder, final_base_name, "md"):
                candidate_name = self.get_next_available_name(target_folder, final_base_name, "md")
                evt = asyncio.Event()
                conflict_info = {"event": evt, "decision": "timeout", "new_name": candidate_name, "target_folder": target_folder}
                self.active_conflicts[external_userid] = conflict_info

                warn_text = (
                    f"⚠️ 提示：在【{target_folder}/】中已存在同名档案“{final_base_name}.md”。\n"
                    f"• 直接回复新名称：按新名称保存\n"
                    f"• 回复“取消”：放弃本次保存\n"
                    f"⏱️ 20 秒内未回复将自动保存为：{candidate_name}.md"
                )
                await self.client.send_text_message(msg_kfid, external_userid, warn_text)

                try:
                    await asyncio.wait_for(evt.wait(), timeout=20.0)
                except asyncio.TimeoutError:
                    pass
                finally:
                    self.active_conflicts.pop(external_userid, None)

                if conflict_info["decision"] == "cancel":
                    await self.client.send_text_message(msg_kfid, external_userid, "已取消本次保存。")
                    return
                elif conflict_info["decision"] == "rename":
                    final_base_name = conflict_info["new_name"]
                    target_folder = conflict_info.get("target_folder", target_folder)
                else:
                    final_base_name = candidate_name

            upload_res = self.r2.upload_archive(
                target_folder=target_folder,
                base_name=final_base_name,
                ext=ext,
                file_bytes=file_bytes,
                original_filename=raw_filename,
                routing_status=routing_status,
                title_source=title_src
            )
            saved_name = upload_res["base_name"]
            att_name = f"{saved_name}.{ext}" if ext else saved_name
            reply_text = (
                f"✅ 已保存\n"
                f"📁 目录：{target_folder}/\n"
                f"📄 档案：{saved_name}.md\n"
                f"📎 附件：Attachments/{att_name}"
            )
            await self.client.send_text_message(msg_kfid, external_userid, reply_text)
        else:
            temp_file = os.path.join(self.temp_dir, f"{media_id}.bin")
            with open(temp_file, "wb") as f:
                f.write(file_bytes)
            self.pending_mgr.create_pending(
                user_id=external_userid,
                temp_file_path=temp_file,
                original_filename=raw_filename,
                ext=ext,
                target_folder=target_folder,
                routing_status=routing_status,
                reason="awaiting_title"
            )
            ask_text = (
                f"收到文件，但档名“{raw_filename}”不适合作为归档名称。\n"
                f"请回复希望保存成的名称；也可以回复“取消”。\n"
                f"当前目录：{target_folder}/"
            )
            await self.client.send_text_message(msg_kfid, external_userid, ask_text)

    async def handle_standalone_text(self, msg: dict, external_userid: str, default_kfid: str):
        msg_kfid = msg.get("open_kfid") or default_kfid
        raw_text = msg.get("text", {}).get("content", "").strip()
        await self.ensure_service_state(msg_kfid, external_userid)

        # 0. 优先响应同名冲突交互
        if external_userid in self.active_conflicts:
            conflict = self.active_conflicts[external_userid]
            if raw_text in ("取消", "不要保存", "放弃"):
                conflict["decision"] = "cancel"
                conflict["event"].set()
                return
            else:
                req_folder, explicit_name = parse_companion_instruction(raw_text, self.r2.alias_map)
                conflict["decision"] = "rename"
                conflict["new_name"] = explicit_name if explicit_name else raw_text
                if req_folder:
                    conflict["target_folder"], _ = self.r2.resolve_folder(req_folder)
                conflict["event"].set()
                return

        # 1. 帮助说明菜单
        if raw_text in ("/help", "帮助", "/", "help", "？", "?"):
            help_text = (
                "📖 知识库归档网关 - 使用指南\n\n"
                "【目录代号切换】\n"
                "直接发送数字或简称切换当前会话目录：\n"
                "• 1 : 1-信息收集/\n"
                "• 2 : 2-价值信息/\n"
                "• 3 : 3-设计实施/\n"
                "• 4 : 4-商务管理/\n"
                "• 5 : 5-生活随笔/\n"
                "• 6 : 6-内容记录/\n"
                "• 9 : 9-稍后处理/ (默认)\n"
                "• 发送“恢复默认”清除目录锁定\n\n"
                "【核心功能】\n"
                "• 网页归档：发送链接或卡片，正文与配图自动本地化\n"
                "• 随手记：发送普通文本，生成带 Properties 的 Markdown\n"
                "• 状态查询：发送“状态”或“pwd”查看当前目录绑定\n"
                "• 智能问答：/hermes <问题> 咨询 AI 大脑"
            )
            await self.client.send_text_message(msg_kfid, external_userid, help_text)
            return

        # 2. 当前状态查询
        if raw_text.lower() in ("状态", "当前", "pwd", "status"):
            session_folder = self.pending_mgr.get_session_folder(external_userid)
            curr_folder = session_folder or self.r2.default_folder
            lock_desc = "会话锁定" if session_folder else "默认未锁定"
            status_text = (
                f"📊 当前系统状态\n"
                f"📁 当前归档目录：{curr_folder}/ ({lock_desc})\n"
                f"🗄 目标存储桶：{self.r2.bucket_name}\n\n"
                f"💡 发送数字 1~6 随时切换目录，发送“恢复默认”清除锁定。"
            )
            await self.client.send_text_message(msg_kfid, external_userid, status_text)
            return

        # 3. 斜杠命令（/hermes）
        if raw_text.startswith("/"):
            cmd_match = re.match(r"^/([a-zA-Z0-9_-]+)(?:\s+(.*))?$", raw_text, re.DOTALL)
            if cmd_match:
                command = cmd_match.group(1).lower()
                prompt = (cmd_match.group(2) or "").strip()

                if command == "hermes":
                    asyncio.create_task(
                        handle_hermes_command(
                            external_userid=external_userid,
                            open_kfid=msg_kfid,
                            prompt=prompt,
                            wecom_client=self.client
                        )
                    )
                    return
                elif command == "help":
                    # 已由上方帮助分支处理
                    return
                else:
                    await self.client.send_text_message(
                        msg_kfid,
                        external_userid,
                        f"⚠️ 未知指令 /{command}\n发送 /help 查看所有可用指令。"
                    )
                    return

        # 4. 纯文本包含 URL 处理
        url_found, remaining_instruction = extract_first_url(raw_text)
        if url_found:
            req_folder, explicit_name = parse_companion_instruction(remaining_instruction, self.r2.alias_map)
            session_folder = self.pending_mgr.get_session_folder(external_userid)
            target_folder, routing_status = self.r2.resolve_folder(req_folder or session_folder)

            await self._archive_url_content(
                url=url_found,
                fallback_title="",
                explicit_name=explicit_name,
                target_folder=target_folder,
                routing_status=routing_status,
                msg_kfid=msg_kfid,
                external_userid=external_userid
            )
            return

        # 5. 会话默认目录清除指令
        if raw_text in ("恢复默认", "取消当前目录", "不指定目录", "清除目录"):
            self.pending_mgr.clear_session_folder(external_userid)
            await self.client.send_text_message(
                msg_kfid,
                external_userid,
                f"已清除会话目录设定，后续文件将恢复默认保存至：{self.r2.default_folder}/"
            )
            return

        # 5.5 全局默认目录修改指令（设默认 1 / 改默认 2）
        set_global_match = re.match(r"^(?:设默认|改默认|设为默认|设置默认|全局默认|修改默认)(?:目录)?(?:为|到)?(?:\s*[:：]?\s*(.+))?$", raw_text)
        if set_global_match:
            raw_folder_str = (set_global_match.group(1) or "").strip()
            if not raw_folder_str:
                help_msg = (
                    "💡 请指定目标目录或代号，例如：\n"
                    "• 设默认 1 （设为 1-信息收集）\n"
                    "• 设默认 2 （设为 2-价值信息）\n"
                    "• 设默认 9 （设为 9-稍后处理）"
                )
                await self.client.send_text_message(msg_kfid, external_userid, help_msg)
                return

            storage_target = getattr(self, "storage", None) or getattr(self, "r2", None)
            target_folder, _ = storage_target.resolve_folder(raw_folder_str)
            if storage_target and hasattr(storage_target, "set_default_folder"):
                storage_target.set_default_folder(target_folder)
                reply = (
                    f"⚙️ 【全局默认目录】更新成功！\n"
                    f"• 当前默认：📁 {target_folder}/\n"
                    f"• 外部 API 闪存与未指定代号的消息将默认保存至此。"
                )
            else:
                reply = "❌ 更新失败：当前存储引擎未就绪。"

            await self.client.send_text_message(msg_kfid, external_userid, reply)
            return

        # 6. 会话默认目录切换指令（必须包含显式命令动词，禁止裸数字误触锁定）
        set_folder_match = re.match(r"^(?:锁定目录|设置目录|默认目录|切换目录|接下来(?:都)?(?:存到|保存到|放到)|会话目录)(?:为|到)?\s*[:：]?\s*(.+)$", raw_text)

        if set_folder_match:
            raw_folder_str = set_folder_match.group(1).strip()
            target_folder, _ = self.r2.resolve_folder(raw_folder_str)
            self.pending_mgr.set_session_folder(external_userid, target_folder)
            await self.client.send_text_message(
                msg_kfid,
                external_userid,
                f"👌 已将当前会话默认目录设置为：{target_folder}/\n后续发送的文件、网页或随手记将自动归档至此。"
            )
            return

        # 6.5 拦截孤立的目录别名/数字（防止误落库生成垃圾随手记）
        if (raw_text in self.r2.alias_map) or (raw_text.lower() in self.r2.alias_map):
            matched_folder, _ = self.r2.resolve_folder(raw_text)
            pending_item = self.pending_mgr.get_pending(external_userid)
            if not pending_item:
                warn_msg = (
                    f"💡 收到目录代号【{matched_folder}/】，但未检测到随附文件或链接。\n\n"
                    f"• 若要锁定会话目录，请发送：锁定目录 {raw_text}\n"
                    f"• 若要归档随手记，请发送具体的文本内容。"
                )
                await self.client.send_text_message(msg_kfid, external_userid, warn_msg)
                return

        # 6.5 拦截孤立的目录代号（防止生成单字垃圾随手记）
        alias_keys = [str(k).strip() for k in self.storage.alias_map.keys()]
        if (raw_text in alias_keys) or (raw_text.lower() in [k.lower() for k in alias_keys]):
            pending_item = self.pending_mgr.get_pending(external_userid)
            if not pending_item:
                target_f, _ = self.storage.resolve_folder(raw_text)
                warn_msg = (
                    f"💡 收到目录代号【{target_f}/】，但未检测到随附文章或文件。\n\n"
                    f"• 若要锁定会话目录，请发送：锁定目录 {raw_text}\n"
                    f"• 若要记录随手记，请发送具体的备忘内容。"
                )
                await self.client.send_text_message(msg_kfid, external_userid, warn_msg)
                return

        # 7. 待确认命名任务响应
        pending_item = self.pending_mgr.get_pending(external_userid)
        if pending_item:
            if raw_text in ("取消", "不要保存", "放弃"):
                self.pending_mgr.clear_pending(external_userid)
                await self.client.send_text_message(msg_kfid, external_userid, "已取消本次保存。")
                return

            req_f, new_name = parse_companion_instruction(raw_text, self.r2.alias_map)
            new_base_name = new_name if new_name else raw_text
            target_folder = self.r2.resolve_folder(req_f)[0] if req_f else pending_item["target_folder"]
            temp_path = pending_item["temp_file_path"]
            ext = pending_item["ext"]
            orig_filename = pending_item["original_filename"]

            if not os.path.exists(temp_path):
                self.pending_mgr.pop_pending(external_userid)
                await self.client.send_text_message(msg_kfid, external_userid, "暂存文件已过期失效，请重新发送。")
                return

            with open(temp_path, "rb") as f:
                file_bytes = f.read()

            upload_res = self.r2.upload_archive(
                target_folder=target_folder,
                base_name=new_base_name,
                ext=ext,
                file_bytes=file_bytes,
                original_filename=orig_filename,
                routing_status=pending_item["routing_status"],
                title_source="user_provided"
            )

            self.pending_mgr.clear_pending(external_userid)
            saved_name = upload_res["base_name"]
            att_name = f"{saved_name}.{ext}" if ext else saved_name
            reply_text = (
                f"✅ 已保存\n"
                f"📁 目录：{target_folder}/\n"
                f"📄 档案：{saved_name}.md\n"
                f"📎 附件：Attachments/{att_name}"
            )
            await self.client.send_text_message(msg_kfid, external_userid, reply_text)
            return

        # 8. 独立纯文本随手记（写入标准 YAML Frontmatter）
        session_folder = self.pending_mgr.get_session_folder(external_userid)
        target_folder = session_folder or self.r2.default_folder
        now_str = time.strftime("%Y-%m-%d_%H%M%S")
        now_full = time.strftime("%Y-%m-%d %H:%M:%S")
        snippet = re.sub(r'[\r\n\t\\/:*?"<>| ]+', '_', raw_text[:12]).strip('_') or "随手记"
        note_name = f"{now_str}_{snippet}"

        md_content = (
            f"---\n"
            f"created: {now_full}\n"
            f"source: wecom-quicknote\n"
            f"tags:\n"
            f"  - quicknote\n"
            f"---\n\n"
            f"# 随手记 - {now_full}\n\n"
            f"{raw_text}\n"
        )

        upload_res = self.r2.upload_archive(
            target_folder=target_folder,
            base_name=note_name,
            ext="md",
            file_bytes=md_content.encode("utf-8"),
            original_filename=f"{note_name}.md",
            routing_status="normal",
            title_source="user_provided"
        )
        await self.client.send_text_message(
            msg_kfid,
            external_userid,
            f"📝 随手记已归档\n📁 目录：{target_folder}/\n📄 档案：{upload_res['base_name']}.md"
        )
