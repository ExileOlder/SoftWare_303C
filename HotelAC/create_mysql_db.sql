-- 创建数据库（如果不存在）
CREATE DATABASE IF NOT EXISTS hotel_ac_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 使用数据库
USE hotel_ac_db;

-- 可选：创建专用用户（如果需要）
-- CREATE USER 'hotel_user'@'localhost' IDENTIFIED BY 'your_password';
-- GRANT ALL PRIVILEGES ON hotel_ac_db.* TO 'hotel_user'@'localhost';
-- FLUSH PRIVILEGES;

-- 提示：将此脚本导入MySQL客户端执行
-- 或通过命令行运行：mysql -u your_username -p < create_mysql_db.sql 