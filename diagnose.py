import asyncio
import yaml
import httpx

async def run():
    with open("config.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    corp_id = cfg["corp_id"]
    secret = cfg["kf_secret"]
    open_kfid = "wkaSgqVAAAYTetbtsUPiG_fjk4QdYVbg"
    external_userid = "wmaSgqVAAAZMBzcfxyojSgu5TaHtE85Q"

    async with httpx.AsyncClient() as client:
        # 1. 换取 Token
        t_res = await client.get(
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
            params={"corpid": corp_id, "corpsecret": secret}
        )
        token = t_res.json()["access_token"]
        print("[1] Token 获取成功")

        # 2. 查询当前真实状态
        s_res = await client.post(
            f"https://qyapi.weixin.qq.com/cgi-bin/kf/service_state/get?access_token={token}",
            json={"open_kfid": open_kfid, "external_userid": external_userid}
        )
        s_data = s_res.json()
        state = s_data.get("service_state")
        state_desc = {0: "未处理", 1: "智能助手接待", 2: "排队中", 3: "人工接待中", 4: "已结束"}.get(state, "未知")
        print(f"[2] 当前底层真实状态: {state} ({state_desc}), 坐席: {s_data.get('servicer_userid', '无')}")

        # 3. 合规状态流转
        if state in (2, 3):
            print("[3] 检测到人工占用，执行 3 -> 4 释放人工席位...")
            r4 = await client.post(
                f"https://qyapi.weixin.qq.com/cgi-bin/kf/service_state/trans?access_token={token}",
                json={"open_kfid": open_kfid, "external_userid": external_userid, "service_state": 4}
            )
            print(f"    释放结果: {r4.json()}")

        print("[4] 执行 -> 1 由智能助手正式接管...")
        r1 = await client.post(
            f"https://qyapi.weixin.qq.com/cgi-bin/kf/service_state/trans?access_token={token}",
            json={"open_kfid": open_kfid, "external_userid": external_userid, "service_state": 1}
        )
        print(f"    接管结果: {r1.json()}")

        # 4. 推送验证消息
        print("[5] 推送测试消息到微信...")
        send_res = await client.post(
            f"https://qyapi.weixin.qq.com/cgi-bin/kf/send_msg?access_token={token}",
            json={
                "touser": external_userid,
                "open_kfid": open_kfid,
                "msgtype": "text",
                "text": {"content": "Pong: 通信链路已完全打通！"}
            }
        )
        print(f"[6] 发送最终结果: {send_res.json()}")

asyncio.run(run())
