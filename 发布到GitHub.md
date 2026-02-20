# 将 JARVIS-M4 发布到 GitHub

仓库地址：**https://github.com/qhdhao13/jarvis-m4**（SSH：`git@github.com:qhdhao13/jarvis-m4.git`）

你已在本地配置好 SSH 密钥，按下面步骤即可推送。

---

## 1. 在 GitHub 上新建仓库

1. 打开 https://github.com/new  
2. **Repository name** 填：`jarvis-m4`  
3. **Owner** 选：`qhdhao13`  
4. 选择 **Public**，**不要**勾选 “Add a README” / “Add .gitignore”（本地已有）  
5. 点击 **Create repository**

---

## 2. 本地初始化为 Git 并推送

在项目根目录（JARVIS-M4）执行：

```bash
cd /Users/qhdh/JARVIS-M4

# 若尚未初始化
git init
git add .
git commit -m "Initial commit: JARVIS-M4 语音助手（祖蛙 / qhdhao）"

# 添加远程并推送（主分支使用 main）
git remote add origin git@github.com:qhdhao13/jarvis-m4.git
git branch -M main
git push -u origin main
```

若之前已经 `git init` 过，只需：

```bash
git add .
git commit -m "README、LICENSE 与发布说明"
git remote add origin git@github.com:qhdhao13/jarvis-m4.git
git branch -M main
git push -u origin main
```

若远程已存在且曾用其他分支名，可先执行：

```bash
git remote add origin git@github.com:qhdhao13/jarvis-m4.git   # 仅首次
git push -u origin main
```

---

## 3. 推送失败时

- **Permission denied (publickey)**：检查 SSH 密钥是否加入 ssh-agent，且 GitHub 账号中已添加对应公钥。  
- **remote: Repository not found**：确认 GitHub 上已创建 `qhdhao13/jarvis-m4` 且当前账号有推送权限。  
- **rejected (non-fast-forward)**：先执行 `git pull origin main --rebase` 再 `git push origin main`。

完成以上步骤后，项目会出现在 https://github.com/qhdhao13/jarvis-m4 ，README 与 LICENSE 会按仓库内文件展示。
