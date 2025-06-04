# 修复缩进问题
with open('hotel_ac/room/views.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 替换有问题的行
fixed_content = content.replace('        rooms = Room.objects.all()', '            rooms = Room.objects.all()')

# 写回文件
with open('hotel_ac/room/views.py', 'w', encoding='utf-8') as f:
    f.write(fixed_content)

print("文件已修复") 