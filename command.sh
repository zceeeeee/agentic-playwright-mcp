
#web GUI

pip install -e ".[dev,stealth]"
pytest
browser-agent.exe doctor
browser-agent.exe gui --host 127.0.0.1 --port 8080



#cmd终端

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,stealth]"
python -m playwright install chromium
browser-agent doctor
browser-agent run "登录GitHub账号，名称是feitianduowen，密码是xxxxxxxx" --max-steps 5 --headed --slow-mo 1000 --keep-open


bilibili账号，电话号码是13574133406，在视频https://www.bilibili.com/video/BV1oh7b6xE4R/?spm_id_from=333.1387.homepage.video_card.click&vd_source=6b653d6392c3b7bb0e204e07b9d93d96 下发布评论“test”。
小红书账号，电话号码是13574133406，发布内容“测试发布功能”。
小红书发布文章，标题是“测试发布功能”，内容“测试发布功能”。
小红书上传视频，地址是"D:\Users\qq275\xwechat_files\wxid_am0to805t4fn22_4242\msg\video\2026-06\c38426b78e62460e709392b4c04974d7.mp4"