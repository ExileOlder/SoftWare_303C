def fix_indentation():
    # 读取文件内容
    with open('hotel_ac/room/views.py', 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # 修复问题行的缩进
    for i in range(len(lines)):
        # 查找 "rooms = Room.objects.all()" 行
        if "rooms = Room.objects.all()" in lines[i] and lines[i].strip().startswith("rooms"):
            # 获取前面行的缩进级别
            prev_line = lines[i-1]
            indentation = ""
            for char in prev_line:
                if char == ' ' or char == '\t':
                    indentation += char
                else:
                    break
            
            # 修复当前行和下一行的缩进
            lines[i] = indentation + lines[i].lstrip()
    
    # 写回文件
    with open('hotel_ac/room/views.py', 'w', encoding='utf-8') as f:
        f.writelines(lines)
    
    print("缩进问题已修复")

if __name__ == "__main__":
    fix_indentation() 