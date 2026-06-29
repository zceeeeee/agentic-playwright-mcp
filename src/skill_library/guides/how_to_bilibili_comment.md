# Bilibili 视频评论

用于进入指定 Bilibili 视频页面，点击右上角登录按钮，切换短信登录，填写手机号并点击发送验证码。登录完成后等待 20 秒，下滑找到评论框，填写评论内容并点击评论框右下角蓝色“发布”按钮。

真人认证和短信验证码输入需要用户在浏览器弹窗中手动完成。

```python
from skill_library.comment.bilibili_comment import run

# 在指定视频下发布评论
run("13574133406", "这是一条测试评论", "https://www.bilibili.com/video/BV1oh7b6xE4R")

# 使用默认视频URL
run("13574133406", "test")
```
