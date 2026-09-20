import base64
import hashlib
import struct
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

class WeComCrypto:
    def __init__(self, token: str, encoding_aes_key: str, corp_id: str):
        self.token = token
        self.corp_id = corp_id
        self.aes_key = base64.b64decode(encoding_aes_key + "=")

    def _get_signature(self, timestamp: str, nonce: str, encrypt: str) -> str:
        return hashlib.sha1("".join(sorted([self.token, timestamp, nonce, encrypt])).encode("utf-8")).hexdigest()

    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
        if self._get_signature(timestamp, nonce, echostr) != msg_signature:
            raise ValueError("签名校验失败")
        return self.decrypt(echostr)

    def decrypt(self, encrypt_text: str) -> str:
        cipher = Cipher(algorithms.AES(self.aes_key), modes.CBC(self.aes_key[:16]))
        decryptor = cipher.decryptor()
        plain = decryptor.update(base64.b64decode(encrypt_text)) + decryptor.finalize()
        pad = plain[-1]
        plain = plain[:-pad]
        content = plain[16:]
        xml_len = struct.unpack(">I", content[:4])[0]
        xml_content = content[4:4 + xml_len].decode("utf-8")
        from_receiveid = content[4 + xml_len:].decode("utf-8")
        if from_receiveid != self.corp_id:
            raise ValueError("CorpID 不匹配")
        return xml_content
