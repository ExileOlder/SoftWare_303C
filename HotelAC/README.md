# 波特普大学快捷廉价酒店 - 中央温控系统

这是波特普大学快捷廉价酒店的中央温控系统，基于Django框架开发，实现了自助计费式中央温控系统的各项功能。系统支持客户端温控、前台入住与结账、管理员监控和经理报表查询。

## 系统功能

### 客户端功能
- 根据房间号和姓名登录
- 调节温度、风速和模式（制冷/制热）
- 开关空调
- 实时显示房间温度和费用
- 查看空调使用历史记录

### 前台功能
- 办理入住和退房
- 查看所有房间状态
- 生成结账账单
- 查看空调使用详单

### 管理员功能
- 实时监控所有房间空调状态
- 查看服务队列和等待队列
- 调整请求优先级
- 查看系统日志和状态

### 经理功能
- 查看各类统计报表
- 分析空调使用数据
- 查看营收情况

## 技术架构

系统采用Django框架，遵循MVT(Model-View-Template)架构模式，核心特点：

- **分布式架构**：采用前后端分离设计，后端提供API服务
- **实时通信**：使用WebSocket实现状态实时更新
- **调度算法**：实现了优先级调度和时间片调度算法
- **温度模拟**：实现了房间温度动态变化的模拟算法

### 系统模块

- **Core**: 核心功能模块，实现调度服务、队列管理和计费功能
- **Room**: 客房空调控制模块，提供温控界面和API
- **Reception**: 前台结账模块，管理入住和退房
- **Admin_app**: 管理员监控模块，实现系统监控
- **Manager**: 经理报表模块，提供数据分析功能
- **Accounts**: 账户管理模块，处理登录和注册

## 快速开始

### 环境要求

- Python 3.8+
- Django 4.0+
- Redis (用于WebSocket通信)

### 安装步骤

1. **克隆项目并安装依赖**

```bash
git clone <repository-url>
cd HotelAC
pip install -r requirements.txt
```

2. **初始化数据库**

如果您是第一次运行项目，可以使用SQLite数据库进行快速开始：

```bash
python manage.py migrate  # 应用数据库迁移
python reset_db.py        # 重置数据库并创建初始数据
```

3. **启动开发服务器**

```bash
python manage.py runserver 0.0.0.0:8000
```

4. **访问系统**

在浏览器中访问 http://localhost:8000/

### 默认账号

初始化后系统会创建以下默认账号：

- **超级管理员**：
  - 用户名：admin
  - 密码：admin123456

其他用户需要通过系统注册功能创建。

## 核心业务逻辑

### 温控系统规则

- **温度范围**：制冷模式（18-25度），制热模式（25-30度）
- **计费标准**：1元/度
- **耗电标准**：
  - 高风：1度/1分钟
  - 中风：1度/2分钟
  - 低风：1度/3分钟
- **温度变化模式**：
  - 中风模式下每分钟变化0.5度
  - 高风模式每分钟变化率提高20%
  - 低风模式每分钟变化率减小20%

### 调度算法

系统实现了优先级调度+时间片调度算法：

1. **优先级调度**：新送风请求的风速若高于正在接受服务的某个送风请求，则将立即服务高风速请求
2. **时间片调度**：风速相同的请求采用时间片轮转，保证服务公平性

## 目录结构

```
HotelAC/
├── hotel_ac/              # Django项目目录
│   ├── core/              # 核心应用（调度服务、队列管理）
│   ├── room/              # 房间空调控制应用
│   ├── reception/         # 前台应用
│   ├── admin_app/         # 管理员应用
│   ├── manager/           # 经理应用
│   ├── accounts/          # 账户管理应用
│   └── settings.py        # 项目配置
├── static/                # 静态文件
├── templates/             # HTML模板
├── manage.py              # Django管理脚本
├── requirements.txt       # 项目依赖
├── reset_db.py            # 数据库重置脚本
└── README.md              # 项目说明
```

## 开发与部署

### 开发模式

```bash
python manage.py runserver 0.0.0.0:8000
```

### 生产环境部署

1. 修改 `settings.py`，设置 `DEBUG = False`
2. 配置合适的数据库（推荐MySQL）
3. 使用Nginx + Gunicorn部署

```bash
# 安装Gunicorn
pip install gunicorn

# 启动Gunicorn
gunicorn hotel_ac.wsgi:application --bind 0.0.0.0:8000
```

## 常见问题

### 如果系统时间显示错误

时间相关问题通常与Django的时区设置有关。在 `settings.py` 中：

```python
TIME_ZONE = 'Asia/Shanghai'  # 设置为中国时区
USE_TZ = True                # 启用时区支持
```

### 如果无法连接WebSocket

确保Redis服务已启动，并在 `settings.py` 中正确配置：

```python
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [('localhost', 6379)],
        },
    },
}
```

## 项目贡献

欢迎提交问题报告和功能建议。如需贡献代码，请遵循以下步骤：

1. Fork项目
2. 创建您的特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交您的更改 (`git commit -m 'Add some amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 打开Pull Request

## 许可证

本项目采用MIT许可证 - 详情请参阅 LICENSE 文件 