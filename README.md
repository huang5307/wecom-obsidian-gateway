# WeCom Obsidian Gateway

> 微信客服 ➔ Obsidian 自动化双链知识库归档网关。支持公众号抓取、图片本地防盗链转存、YAML 属性生成与快速代号路由。

## 核心特性
- 微信官方客服接口直连，长效稳定。
- 配图自动下载至 `Attachments/` 目录，生成原生 `![[Attachments/xxx]]` 双链。
- 自动提取文章标题、时间生成 YAML 属性（Properties）。
- 消息防抖合并，支持附言代号快速归档（如附言 `1` 归档到指定目录）。
- 存储层抽象（默认 Cloudflare R2）。

## 运行要求
- Python 3.10+
- 企业微信客服应用权限
- Cloudflare R2 / S3 兼容存储

## 快速配置
1. 复制 `configs/*.example.yaml` 为 `configs/*.yaml` 并填入真实凭证。
2. 安装依赖：`pip install -r requirements.txt`
3. 启动服务：`uvicorn main:app --host 127.0.0.1 --port 8080`
