# 🚀 团队/公司局域网部署启动器
# 自动检测本机 IP，提供访问地址
# 自动运行 web_scraper_app.py 并监听所有设备

import os
import socket
import subprocess
import time

def get_local_ip():
    """获取本机局域网 IP 地址"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # 连接到一个外部地址但不发送数据
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

if __name__ == "__main__":
    local_ip = get_local_ip()
    port = 8501

    print("""
🔧 启动局域网网页爬虫工具...
========================================
📍 局域网访问地址：
👉 http://{ip}:{port}

💻 本机访问地址：
👉 http://localhost:{port}

按 Ctrl+C 可随时退出服务
========================================
""".format(ip=local_ip, port=port))

    time.sleep(1)
    subprocess.run([
        "streamlit", "run", "web_scraper_app.py",
        "--server.address=0.0.0.0",
        f"--server.port={port}"
    ])
