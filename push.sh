#!/usr/bin/env bash
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

echo "========================================="
echo "        WeCom Gateway 一键推送          "
echo "========================================="

# 1. 检查是否存在敏感真实配置文件被暂存
LEAK_FILES=$(git status --porcelain | grep -E 'configs/(app|wecom|storage_r2|ai_hermes)\.yaml|config\.yaml|\.env' || true)
if [ -n "$LEAK_FILES" ]; then
    echo "❌ [安全拦截] 检测到敏感真实配置文件尝试进入 Git 暂存区:"
    echo "$LEAK_FILES"
    echo "推送已紧急中止！请检查 .gitignore。"
    exit 1
fi

# 2. 收集变更
git add -A

# 再次复核暂存区
STAGED_LEAKS=$(git diff --cached --name-only | grep -E 'configs/(app|wecom|storage_r2|ai_hermes)\.yaml|config\.yaml|\.env' || true)
if [ -n "$STAGED_LEAKS" ]; then
    echo "❌ [安全拦截] 暂存区包含私密文件，立即撤销暂存！"
    git reset
    exit 1
fi

# 检查是否有文件改动需要提交
if git diff-index --quiet HEAD -- 2>/dev/null; then
    echo "💡 没有检测到代码变动，无需提交。"
    exit 0
fi

# 3. 提交信息处理
COMMIT_MSG="$1"
if [ -z "$COMMIT_MSG" ]; then
    CURRENT_TIME=$(date "+%Y-%m-%d %H:%M:%S")
    COMMIT_MSG="update: sync gateway codebase ($CURRENT_TIME)"
fi

git commit -m "$COMMIT_MSG"

# 4. 推送到 GitHub
echo "🚀 正在推送到 GitHub 私有仓库..."
git push origin main
echo "✅ 推送成功！"
