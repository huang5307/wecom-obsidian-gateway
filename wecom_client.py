import time
import httpx
import urllib.parse

class WeComClient:
    def __init__(self, corp_id: str, secret: str):
        self.corp_id = corp_id
        self.secret = secret
        self.token_cache = {"token": "", "expires_at": 0}

    async def get_access_token(self) -> str:
        now = time.time()
        if self.token_cache["token"] and self.token_cache["expires_at"] > now + 300:
            return self.token_cache["token"]
        url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params={"corpid": self.corp_id, "corpsecret": self.secret})
            data = resp.json()
            if data.get("errcode") != 0:
                raise RuntimeError(f"获取 Token 失败: {data}")
            self.token_cache["token"] = data["access_token"]
            self.token_cache["expires_at"] = now + data["expires_in"]
            return self.token_cache["token"]

    async def sync_messages(self, token: str = None, cursor: str = None, open_kfid: str = None) -> dict:
        access_token = await self.get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/kf/sync_msg?access_token={access_token}"
        payload = {"limit": 10}
        # 腾讯规范：事件回调必须优先使用 token 鉴权拉取
        if token:
            payload["token"] = token
        elif cursor:
            payload["cursor"] = cursor
        if open_kfid:
            payload["open_kfid"] = open_kfid
            
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload)
            return resp.json()

    async def get_service_state(self, open_kfid: str, external_userid: str) -> int:
        access_token = await self.get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/kf/service_state/get?access_token={access_token}"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json={"open_kfid": open_kfid, "external_userid": external_userid})
            return resp.json().get("service_state", -1)

    async def trans_service_state(self, open_kfid: str, external_userid: str, service_state: int) -> dict:
        access_token = await self.get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/kf/service_state/trans?access_token={access_token}"
        payload = {
            "open_kfid": open_kfid,
            "external_userid": external_userid,
            "service_state": service_state
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload)
            return resp.json()

    async def send_text_message(self, open_kfid: str, external_userid: str, content: str):
        access_token = await self.get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/kf/send_msg?access_token={access_token}"
        payload = {
            "touser": external_userid,
            "open_kfid": open_kfid,
            "msgtype": "text",
            "text": {"content": content}
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload)
            return resp.json()

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        """下载临时素材二进制流并解码原始文件名"""
        access_token = await self.get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/media/get?access_token={access_token}&media_id={media_id}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url)
            disp = resp.headers.get("content-disposition", "")
            filename = ""
            if "filename=" in disp:
                raw = disp.split("filename=")[-1].strip('"; ')
                filename = urllib.parse.unquote(raw)
            elif "filename*=" in disp:
                raw = disp.split("filename*=")[-1].split("''")[-1].strip('"; ')
                filename = urllib.parse.unquote(raw)
            return resp.content, filename
