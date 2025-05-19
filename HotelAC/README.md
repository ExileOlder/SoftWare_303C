# 波特普大学快捷廉价酒店空调管理系统

## 项目简介

本项目是波特普大学快捷廉价酒店的中央空调管理系统，基于Django框架开发。系统实现了自助计费式中央温控系统，使酒店客户可以根据需求设定温度和风速，并实时显示费用。系统还提供了前台结账功能和管理员监控功能。

## 系统功能

- **客户端功能**：
  - 空调开关控制
  - 温度调节（制冷模式：18-25度，制热模式：25-30度）
  - 风速调节（高风、中风、低风）
  - 实时显示当前温度和目标温度
  - 实时计费显示

- **前台功能**：
  - 客房管理（入住、退房）
  - 空调费用账单生成
  - 空调使用详单查看

- **管理员功能**：
  - 实时监控所有房间空调状态
  - 服务队列和等待队列管理
  - 系统参数设置
  - 运行状态统计

## 技术架构

- **前端**：HTML、CSS、JavaScript
- **后端**：Python + Django + Django Channels
- **数据库**：Django ORM
- **实时通信**：WebSocket

## 项目结构

```
HotelAC/                     # 项目根目录
├── hotel_ac/                # Django项目配置
│   ├── __init__.py
│   ├── settings.py          # 项目设置
│   ├── urls.py              # 主URL配置
│   ├── asgi.py              # ASGI配置(WebSocket)
│   └── wsgi.py              # WSGI配置
│
├── core/                    # 核心应用(中央空调系统)
│   ├── __init__.py
│   ├── models.py            # 数据模型
│   ├── views.py             # API视图
│   ├── consumers.py         # WebSocket消费者
│   ├── services/            # 业务服务
│   │   ├── __init__.py
│   │   ├── scheduler.py     # 调度服务
│   │   └── temperature.py   # 温度计算服务
│   ├── urls.py              # URL路由
│   └── routing.py           # WebSocket路由
│
├── room/                    # 客房应用
│   ├── __init__.py
│   ├── models.py            # 房间和温控数据模型
│   ├── views.py             # 房间API视图
│   ├── consumers.py         # 房间WebSocket消费者
│   ├── urls.py
│   └── serializers.py       # 序列化器
│
├── admin_panel/             # 管理员应用
│   ├── __init__.py
│   ├── models.py
│   ├── views.py             # 管理员监控API
│   ├── consumers.py         # 管理员实时监控消费者
│   └── urls.py
│
├── reception/               # 前台应用
│   ├── __init__.py
│   ├── models.py            # 账单模型
│   ├── views.py             # 账单API
│   └── urls.py
│
├── static/                  # 静态资源
│   ├── css/                 # 样式文件
│   ├── js/                  # JavaScript文件
│   └── img/                 # 图片资源
│
├── templates/               # HTML模板
│   ├── room/                # 客户端模板
│   ├── admin/               # 管理员模板
│   └── reception/           # 前台模板
│
├── requirements.txt         # 项目依赖
└── README.md                # 项目说明
```

## 安装和运行

### 依赖环境

- Python 3.8+
- Django 4.2.0
- Django REST Framework 3.14.0
- Django Channels 4.0.0
- Redis (用于Channels)

### 安装步骤

1. 克隆项目

```bash
git clone <repository-url>
cd HotelAC
```

2. 创建虚拟环境并激活

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```

3. 安装依赖

```bash
pip install -r requirements.txt
```

4. 初始化数据库

```bash
python manage.py makemigrations
python manage.py migrate
```

5. 创建超级用户

```bash
python manage.py createsuperuser
```

6. 运行开发服务器

```bash
python manage.py runserver
```

访问 http://localhost:8000/ 查看应用。

## 系统配置

系统主要参数在`settings.py`中配置：

- `MAX_SERVICE_ROOMS`: 最大同时服务房间数
- `WAITING_TIME_SLICE`: 等待时间片（秒）
- `TEMPERATURE_CHANGE_RATES`: 温度变化率配置
- `FEE_RATES`: 费用计算率

## API接口

系统提供了一系列RESTful API接口，详细接口文档可通过访问 http://localhost:8000/api/docs/ 查看。

主要接口包括：

- 温控请求接口
- 状态查询接口
- 账单生成接口
- 监控数据接口

## 前后端分离

本项目采用前后端分离的架构：

- 前端通过HTML/CSS/JavaScript实现用户界面
- 后端通过Django REST Framework提供API
- 使用Django Channels实现WebSocket通信，保证实时数据传输

## 系统特点

1. **实时温控**：客户端可实时控制和监测房间温度
2. **智能调度**：使用优先级调度和时间片调度算法
3. **精确计费**：根据风速和使用时间精确计算费用
4. **全面监控**：管理员可监控所有房间状态和系统运行情况

## 未来工作

- 移动端应用开发
- 数据分析和报表功能增强
- 多语言支持
- 更高级的调度算法

## 许可证

本项目采用MIT许可证 