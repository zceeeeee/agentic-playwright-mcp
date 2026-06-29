# Gmail 登录

用于打开 `https://mail.google.com/mail?hl=zh-CN`，填写 Gmail 邮箱和密码，遇到“选择您想要使用的登录方式：”时点击下面的第一种登录方式，等待用户手动输入验证码后点击“下一步”，最后通过左上角 Gmail 图标确认登录成功。

```python
from skill_library.others.gmail_login import run

run("che53438@gmail.com", "8105432a")
```
