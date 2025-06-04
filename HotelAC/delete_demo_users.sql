-- 删除示例用户的SQL脚本
-- 使用方法: python manage.py dbshell < delete_demo_users.sql

-- 先删除与这些用户关联的用户资料（如果有）
DELETE FROM core_userprofile 
WHERE user_id IN (
    SELECT id FROM auth_user 
    WHERE username IN ('guest1', 'guest2', 'receptionist1', 'admin1', 'manager1')
);

-- 删除用户与组的关联
DELETE FROM auth_user_groups 
WHERE user_id IN (
    SELECT id FROM auth_user 
    WHERE username IN ('guest1', 'guest2', 'receptionist1', 'admin1', 'manager1')
);

-- 删除用户与权限的关联
DELETE FROM auth_user_user_permissions 
WHERE user_id IN (
    SELECT id FROM auth_user 
    WHERE username IN ('guest1', 'guest2', 'receptionist1', 'admin1', 'manager1')
);

-- 最后删除用户本身
DELETE FROM auth_user 
WHERE username IN ('guest1', 'guest2', 'receptionist1', 'admin1', 'manager1');

-- 打印操作完成信息
SELECT '示例用户已成功删除' AS message; 