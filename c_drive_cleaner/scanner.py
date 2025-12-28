# -*- coding: utf-8 -*-
"""
C盘清理工具 - 扫描模块
负责扫描系统垃圾文件
"""

import os
import ctypes
from pathlib import Path
from typing import Dict, List, Callable, Optional
from dataclasses import dataclass, field
import winreg

from config import CLEANUP_ITEMS


@dataclass
class ScanResult:
    """扫描结果数据类"""
    item_id: str
    item_name: str
    total_size: int = 0
    file_count: int = 0
    files: List[str] = field(default_factory=list)
    error: Optional[str] = None


class Scanner:
    """垃圾文件扫描器"""
    
    def __init__(self, progress_callback: Callable[[str, int], None] = None):
        """
        初始化扫描器
        
        Args:
            progress_callback: 进度回调函数，参数为(当前扫描项名称, 进度百分比)
        """
        self.progress_callback = progress_callback
        self.results: Dict[str, ScanResult] = {}
        self._cancelled = False
    
    def cancel(self):
        """取消扫描"""
        self._cancelled = True
    
    def scan_all(self) -> Dict[str, ScanResult]:
        """
        扫描所有配置的清理项目
        
        Returns:
            包含所有扫描结果的字典
        """
        self._cancelled = False
        self.results.clear()
        
        total_items = len(CLEANUP_ITEMS)
        
        for index, item in enumerate(CLEANUP_ITEMS):
            if self._cancelled:
                break
                
            item_id = item["id"]
            item_name = item["name"]
            
            if self.progress_callback:
                progress = int((index / total_items) * 100)
                self.progress_callback(item_name, progress)
            
            # 特殊处理回收站
            if item.get("special") == "recycle_bin":
                result = self._scan_recycle_bin(item_id, item_name)
            else:
                result = self._scan_item(item)
            
            self.results[item_id] = result
        
        if self.progress_callback:
            self.progress_callback("扫描完成", 100)
        
        return self.results
    
    def _scan_item(self, item: dict) -> ScanResult:
        """
        扫描单个清理项目
        
        Args:
            item: 清理项目配置
            
        Returns:
            扫描结果
        """
        result = ScanResult(
            item_id=item["id"],
            item_name=item["name"]
        )
        
        paths = item.get("paths", [])
        extensions = item.get("extensions")
        pattern = item.get("pattern")
        
        for path in paths:
            if self._cancelled:
                break
                
            if not os.path.exists(path):
                continue
            
            try:
                self._scan_directory(
                    path, 
                    result, 
                    extensions=extensions,
                    pattern=pattern
                )
            except PermissionError:
                result.error = "权限不足，需要管理员权限"
            except Exception as e:
                result.error = str(e)
        
        return result
    
    def _scan_directory(
        self, 
        directory: str, 
        result: ScanResult,
        extensions: List[str] = None,
        pattern: str = None
    ):
        """
        递归扫描目录
        
        Args:
            directory: 目录路径
            result: 扫描结果对象
            extensions: 文件扩展名过滤
            pattern: 路径模式匹配
        """
        try:
            for entry in os.scandir(directory):
                if self._cancelled:
                    return
                    
                try:
                    if entry.is_file(follow_symlinks=False):
                        # 检查扩展名过滤
                        if extensions:
                            ext = Path(entry.path).suffix.lower()
                            if ext not in extensions:
                                continue
                        
                        # 检查模式匹配
                        if pattern and pattern.lower() not in entry.path.lower():
                            continue
                        
                        size = entry.stat().st_size
                        result.total_size += size
                        result.file_count += 1
                        result.files.append(entry.path)
                        
                    elif entry.is_dir(follow_symlinks=False):
                        # 检查模式匹配（目录级别）
                        if pattern and pattern.lower() not in entry.path.lower():
                            # 继续递归，但不统计此目录下的文件
                            self._scan_directory(entry.path, result, extensions, pattern)
                        else:
                            self._scan_directory(entry.path, result, extensions, None if pattern else None)
                            
                except (PermissionError, OSError):
                    # 跳过无权限访问的文件
                    continue
                    
        except (PermissionError, OSError):
            pass
    
    def _scan_recycle_bin(self, item_id: str, item_name: str) -> ScanResult:
        """
        扫描回收站
        
        Args:
            item_id: 项目ID
            item_name: 项目名称
            
        Returns:
            扫描结果
        """
        result = ScanResult(item_id=item_id, item_name=item_name)
        
        try:
            # 使用 Windows Shell API 获取回收站大小
            shell32 = ctypes.windll.shell32
            
            # SHQUERYRBINFO 结构体
            class SHQUERYRBINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_ulong),
                    ("i64Size", ctypes.c_longlong),
                    ("i64NumItems", ctypes.c_longlong),
                ]
            
            info = SHQUERYRBINFO()
            info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
            
            # 查询回收站 (None 表示所有驱动器)
            ret = shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
            
            if ret == 0:  # S_OK
                result.total_size = info.i64Size
                result.file_count = info.i64NumItems
            else:
                result.error = "无法获取回收站信息"
                
        except Exception as e:
            result.error = str(e)
        
        return result
    
    def get_total_size(self) -> int:
        """获取所有扫描结果的总大小"""
        return sum(r.total_size for r in self.results.values())
    
    def get_selected_size(self, selected_ids: List[str]) -> int:
        """获取选中项目的总大小"""
        return sum(
            self.results[id].total_size 
            for id in selected_ids 
            if id in self.results
        )


def format_size(size_bytes: int) -> str:
    """
    格式化文件大小显示
    
    Args:
        size_bytes: 字节大小
        
    Returns:
        格式化后的字符串
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
