# 开黑协调工具

PC 游戏群的开黑协调工具。完整需求见上级目录的 `开黑协调工具_PRD_v1.0.docx`。

当前进度：**第 1 步 / 10 —— 骨架已跑通**

---

## 怎么跑起来

```powershell
cd C:\1\newtonew\kahei
.\.venv\Scripts\Activate.ps1      # 激活虚拟环境，命令行前面会出现 (.venv)
python manage.py runserver
```

然后打开：

- <http://127.0.0.1:8000/> —— 首页
- <http://127.0.0.1:8000/admin/> —— 后台

退出虚拟环境用 `deactivate`。

### 管理员账号

数据库 `db.sqlite3` 不进仓库，所以**克隆下来后一个账号都没有**。第一次运行自己建：

```powershell
python manage.py createsuperuser
```

> 账号密码只存在你本机的数据库里。**不要写进任何会被提交的文件**——
> 这个仓库是公开的，README、settings.py、测试代码都算"会被提交"。
> 要改密码：`python manage.py changepassword admin`

后台和前台的**登录页是同一个**：没登录访问 `/admin/` 会被送到 `/login/`，
登录完自动回到后台。管理员登录后，「我的」菜单里会多一项「后台管理」。

### 密钥配置

`config/settings.py` 里的 `SECRET_KEY` 从 `.env` 读取，`.env` 已被 git 忽略。
新克隆下来照 `.env.example` 复制一份、自己填：

```powershell
Copy-Item .env.example .env
python -c "from django.core.management.utils import get_random_secret_key as g; print('DJANGO_SECRET_KEY=' + g())"
```

把上面命令输出的那一行写进 `.env` 即可。

### 造点数据再看

```powershell
python manage.py seed_demo        # 演示群「深夜食堂」+ 6 个成员 + 空闲时段
python manage.py seed_test_users  # 3 个能登录的测试账号
```

测试账号统一密码 `TestPass2026`：

| 邮箱 | 昵称 |
|---|---|
| `test1@example.com` | 测试一号 |
| `test2@example.com` | 测试二号 |
| `test3@example.com` | 测试三号 |

> `seed_demo` 造的 `demo_*` 账号是纯数据账号，**没有密码、登不进去**，
> 只用来把热力图撑起来。

### 现在能做什么

登录之后：

| 地址 | 作用 |
|---|---|
| `/` | 未登录是落地页；**登录后直接跳到你上次看的群** |
| `/me/` | 账号菜单：我的群、填时间、我的游戏、建群、加入群 |
| `/groups/new/` | 建群，创建者自动成为群主 |
| `/groups/join/` | 填邀请码入群 |
| `/me/schedule/` | 填我的每周作息（人级默认，对所有群生效） |
| `/me/games/` | 勾选我拥有的游戏、标常玩；保存后弹「已保存」 |
| `/g/群标识/` | 看这个群的时间热力图；**是成员就能直接点格子标自己的时间** |
| `/g/群标识/?game=ID` | 只看某一款游戏的热力图（只统计拥有这款的人） |

热力图上的格子：**点击一格**，或者**按住左键拖出一段**，松手后会弹出菜单
让你选「有空 / 没空 / 清除」，选完才生效。
格子右上角的小圆点表示「你自己」的状态：绿=有空、红=没空。

默认写的是**人级默认**（对所有群生效）；勾上「只改这个群」就只影响当前这个群。

热力图上方有一排游戏筛选：点某个游戏名，热力图就只统计「拥有这款游戏的人」，
一眼看出这款游戏什么时候人最齐。

演示群的邀请码在 `seed_demo` 的输出里，也可以去 `/admin/core/group/` 查。

---

## 目录说明

```
kahei/
├── .venv/              虚拟环境（不要提交到 git）
├── manage.py           Django 的管理命令入口
├── db.sqlite3          SQLite 数据库（自动生成，不要提交）
├── config/             项目配置
│   ├── settings.py     全局设置：数据库、语言、时区、装哪些 app
│   └── urls.py         路由表：哪个网址对应哪个页面
└── core/               我们自己的功能
    ├── models.py       数据表定义（6 张表）
    ├── services.py     计算核心：把区间叠起来、算成热力图
    ├── forms.py        注册、建群、入群、填时间的表单
    ├── utils.py        小工具（随机邀请码）
    ├── views.py        页面逻辑
    ├── admin.py        后台配置
    ├── management/
    │   └── commands/
    │       ├── seed_demo.py        造演示群和空闲时段
    │       └── seed_test_users.py  造测试账号
    └── templates/
        ├── core/
        │   ├── index.html      首页
        │   ├── heatmap.html    群时间热力图
        │   ├── schedule.html   我的每周作息
        │   ├── group_new.html  建群
        │   ├── group_join.html 加入群
        │   ├── register.html   注册
        │   ├── auth_base.html  登录/注册/建群/入群共用的外壳
        │   └── _nav.html       右上角的登录状态
        └── registration/
            └── login.html      登录（Django 内置视图要求这个路径）
```

---

## 技术栈

| | |
|---|---|
| 框架 | Django 6.1.2 |
| Python | 3.14.2（虚拟环境隔离，不动系统 Python） |
| 数据库 | SQLite（一个文件，零配置） |
| 时区 | Asia/Shanghai |
| 界面语言 | 中文（简体） |

---

## 十步计划

- [x] 1. 骨架跑起来（路由 → 视图 → 模板）
- [x] 2. 建数据模型：User / Group / Membership / Availability / Game / OwnedGame
- [x] 3. **群时间热力图（假数据）** ← 提前做了，先看见产品
- [x] 4. 热力图接真实数据（查 `Availability` 表 + 覆盖优先级 + 跨午夜）
- [x] 5. 注册、登录、登出
- [x] 6. 建群 + 邀请码入群
- [x] 7. 填空闲时间（区间输入）
- [x] 8. 勾选拥有的游戏
- [ ] 9. 点时段出匹配结果
- [ ] 10. 确定开黑 + 生成群文案

> 顺序调整过：原本热力图排在最后，但它是产品的脸，
> 也是最难排版的界面，所以提前到第 3 步，先用假数据把视觉定下来。

---

## 常用命令

```powershell
python manage.py check          # 检查有没有配置错误
python manage.py migrate        # 把数据表结构的改动同步到数据库
python manage.py makemigrations # 改完 models.py 后生成迁移文件
python manage.py createsuperuser # 新建管理员
python manage.py shell          # 进交互式命令行，调试用
```

---

## 常见问题

### `git push` 报 `Connection was reset` / `Failed to connect`

国内直连 GitHub 不稳定，需要走本地代理。已经按域名配好了（只对 github.com 生效，
不影响 gitee 等其他站点）：

```powershell
git config --global http.https://github.com.proxy http://127.0.0.1:7890
```

推之前确认代理工具是开着的。代理关掉时 `push` 会报连接被拒绝，把代理打开再推就行。

### 提交前先扫一遍密钥

```powershell
git grep -n -i -E --cached -e "password\s*=" -e "secret[_-]?key" -e "api[_-]?key" -e "django-insecure"
```

输出为空（或只有占位符、说明文字）才提交。这个仓库是公开的。

