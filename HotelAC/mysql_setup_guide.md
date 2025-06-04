# MySQL 配置指南

## 创建数据库

1. 打开 MySQL Workbench 或其他 MySQL 客户端工具
2. 使用您的 root 账号或其他有管理权限的账号登录
3. 运行以下 SQL 命令创建数据库：

```sql
CREATE DATABASE IF NOT EXISTS hotel_ac_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

或者，您可以直接导入项目根目录下的 `create_mysql_db.sql` 文件。

## 修改 Django 配置

1. 打开 `hotel_ac/settings.py` 文件
2. 找到数据库配置部分，修改为您的 MySQL 用户名和密码：

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'hotel_ac_db',
        'USER': '您的MySQL用户名',
        'PASSWORD': '您的MySQL密码',
        'HOST': 'localhost',
        'PORT': '3306',
        'OPTIONS': {
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            'charset': 'utf8mb4',
        },
    }
}
```

## 创建数据库表

1. 打开命令行，进入项目根目录
2. 运行以下命令创建数据库表：

```bash
python manage.py migrate
```

## 故障排除

如果遇到 MySQL 连接问题，请尝试以下解决方案：

1. **检查 MySQL 服务是否运行**：
   - 在 Windows 上，打开服务管理器，确认 MySQL 服务正在运行

2. **验证用户名和密码**：
   - 尝试在命令行中手动连接 MySQL：`mysql -u 您的用户名 -p`

3. **检查数据库权限**：
   - 确保您的 MySQL 用户对 `hotel_ac_db` 数据库有完全访问权限

4. **临时使用 SQLite**：
   - 如果问题无法解决，可以暂时使用 SQLite。在 `settings.py` 中注释掉 MySQL 配置，取消 SQLite 配置的注释。

## 创建专用数据库用户（可选但推荐）

为了提高安全性，建议为应用创建专用的数据库用户，而不是使用 root 用户：

```sql
CREATE USER 'hotel_user'@'localhost' IDENTIFIED BY '您的密码';
GRANT ALL PRIVILEGES ON hotel_ac_db.* TO 'hotel_user'@'localhost';
FLUSH PRIVILEGES;
```

然后在 `settings.py` 中使用这个新用户的凭据。 