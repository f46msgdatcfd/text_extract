# 高鲁棒性网页爬虫系统

这是一个基于 Streamlit 构建的网页内容提取工具，支持 Excel/CSV URL 列表批量抓取，并提供截图、内容提取、失败日志等功能。

## ✨ 功能亮点
- 📂 支持上传 Excel / CSV 文件
- 🌐 批量抓取网页正文、标题、发布时间、作者
- 📸 自动截图失败页面
- 📥 支持导出 JSON / Excel / CSV
- 🪵 自动记录失败日志

## 🚀 本地运行方式

```bash
pip install -r requirements.txt
playwright install
streamlit run Web_Scraper_App.py
```

## ☁️ 在线部署（Streamlit Cloud）

1. 推送此项目至 GitHub 仓库
2. 登录 https://streamlit.io/cloud
3. 选择 "New App" > 绑定 GitHub 仓库
4. 指定主文件为 `Web_Scraper_App.py`
5. 部署并获得在线访问链接

⚠️ 本工具仅供学习与科研用途。请确保您在使用本工具抓取网页内容时遵守目标网站的服务条款与法律规定。