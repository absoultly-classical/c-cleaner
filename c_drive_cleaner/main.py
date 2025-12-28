# -*- coding: utf-8 -*-
"""
C盘清理工具 - 主程序入口
"""

import sys
import os
import ctypes

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.main_window import main


def is_admin():
    """检查是否以管理员权限运行"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def run_as_admin():
    """请求管理员权限重新运行"""
    try:
        if sys.platform == 'win32':
            # 获取当前工作目录
            cwd = os.getcwd()
            ctypes.windll.shell32.ShellExecuteW(
                None, 
                "runas", 
                sys.executable, 
                " ".join(sys.argv), 
                cwd, 
                1
            )
    except:
        pass


if __name__ == "__main__":
    # 检查管理员权限
    if not is_admin():
        print("正在尝试以管理员身份重新运行...")
        run_as_admin()
        sys.exit()
    
    # 运行主程序
    main()
