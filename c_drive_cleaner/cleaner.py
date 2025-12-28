# -*- coding: utf-8 -*-
"""
C盘清理工具 - 清理模块
负责安全删除垃圾文件
"""

import os
import shutil
import ctypes
from pathlib import Path
from typing import Dict, List, Callable, Optional
from dataclasses import dataclass

from scanner import ScanResult
from config import CLEANUP_ITEMS


@dataclass
class CleanResult:
    """清理结果数据类"""
    item_id: str
    item_name: str
    cleaned_size: int = 0
    cleaned_count: int = 0
    failed_count: int = 0
    errors: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class Cleaner:
    """垃圾文件清理器"""
    
    def __init__(
        self, 
        progress_callback: Callable[[str, int, int], None] = None,
        log_callback: Callable[[str], None] = None
    ):
        """
        初始化清理器
        
        Args:
            progress_callback: 进度回调函数，参数为(项目名称, 当前进度, 总进度)
            log_callback: 日志回调函数，参数为(日志信息)
        """
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self._cancelled = False
    
    def _log(self, message: str):
        """内部日志处理"""
        if self.log_callback:
            self.log_callback(message)

    def cancel(self):
        """取消清理"""
        self._cancelled = True
    
    def clean(
        self, 
        scan_results: Dict[str, ScanResult], 
        selected_ids: List[str]
    ) -> Dict[str, CleanResult]:
        """
        执行清理操作
        """
        self._cancelled = False
        results: Dict[str, CleanResult] = {}
        
        # 计算总文件数
        total_files = sum(
            scan_results[id].file_count 
            for id in selected_ids 
            if id in scan_results
        )
        cleaned_files = 0
        
        for item_id in selected_ids:
            if self._cancelled:
                break
                
            if item_id not in scan_results:
                continue
            
            scan_result = scan_results[item_id]
            
            # 获取清理项配置
            item_config = next(
                (item for item in CLEANUP_ITEMS if item["id"] == item_id), 
                None
            )
            
            if not item_config:
                continue
            
            # 特殊处理回收站
            if item_config.get("special") == "recycle_bin":
                result = self._clean_recycle_bin(item_id, scan_result.item_name)
            else:
                result = self._clean_files(
                    item_id,
                    scan_result,
                    lambda count: self._update_progress(
                        scan_result.item_name, 
                        cleaned_files + count, 
                        total_files
                    )
                )
                cleaned_files += scan_result.file_count
            
            results[item_id] = result
        
        return results
    
    def _update_progress(self, item_name: str, current: int, total: int):
        """更新进度"""
        if self.progress_callback:
            self.progress_callback(item_name, current, total)
    
    def _clean_files(
        self, 
        item_id: str, 
        scan_result: ScanResult,
        progress_update: Callable[[int], None] = None
    ) -> CleanResult:
        """
        清理文件列表
        """
        result = CleanResult(item_id=item_id, item_name=scan_result.item_name)
        
        # 批量更新进度，减少UI回调频率
        update_interval = max(1, len(scan_result.files) // 100)
        
        self._log(f"开始清理 {scan_result.item_name}，共 {len(scan_result.files)} 个文件")
        
        for index, file_path in enumerate(scan_result.files):
            if self._cancelled:
                break
            
            try:
                if not os.path.exists(file_path):
                    continue
                    
                if os.path.isfile(file_path):
                    size = os.path.getsize(file_path)
                    os.remove(file_path)
                    result.cleaned_size += size
                    result.cleaned_count += 1
                    if index < 3: 
                        self._log(f"  √ 已删除: ...{os.path.basename(file_path)}")
                elif os.path.isdir(file_path):
                    size = self._get_dir_size(file_path)
                    shutil.rmtree(file_path, ignore_errors=True)
                    result.cleaned_size += size
                    result.cleaned_count += 1
                    if index < 3:
                        self._log(f"  √ 已删除目录: {os.path.basename(file_path)}")
                    
            except PermissionError:
                result.failed_count += 1
                if index < 2:
                    self._log(f"  × 权限不足(文件正在使用): {os.path.basename(file_path)}")
            except Exception as e:
                result.failed_count += 1
                if index < 2:
                    self._log(f"  × 删除失败: {os.path.basename(file_path)}")
            
            if progress_update and (index % update_interval == 0 or index == len(scan_result.files) - 1):
                progress_update(index + 1)
        
        from scanner import format_size
        self._log(f"完成 {scan_result.item_name}: 成功 {result.cleaned_count}，失败 {result.failed_count}，释放 {format_size(result.cleaned_size)}")
        
        self._clean_empty_dirs(scan_result)
        return result
    
    def _clean_empty_dirs(self, scan_result: ScanResult):
        """清理空目录"""
        # 获取所有涉及的目录
        dirs = set()
        for file_path in scan_result.files:
            parent = os.path.dirname(file_path)
            while parent:
                dirs.add(parent)
                new_parent = os.path.dirname(parent)
                if new_parent == parent:
                    break
                parent = new_parent
        
        # 按路径长度降序排序（先删除深层目录）
        sorted_dirs = sorted(dirs, key=len, reverse=True)
        
        for dir_path in sorted_dirs:
            try:
                if os.path.isdir(dir_path) and not os.listdir(dir_path):
                    os.rmdir(dir_path)
            except (PermissionError, OSError):
                pass
    
    def _get_dir_size(self, path: str) -> int:
        """获取目录大小"""
        total = 0
        try:
            for entry in os.scandir(path):
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat().st_size
                    elif entry.is_dir(follow_symlinks=False):
                        total += self._get_dir_size(entry.path)
                except (PermissionError, OSError):
                    pass
        except (PermissionError, OSError):
            pass
        return total
    
    def _clean_recycle_bin(self, item_id: str, item_name: str) -> CleanResult:
        """
        清空回收站
        
        Args:
            item_id: 项目ID
            item_name: 项目名称
            
        Returns:
            清理结果
        """
        result = CleanResult(item_id=item_id, item_name=item_name)
        
        try:
            # 使用 Windows Shell API 清空回收站
            # SHEmptyRecycleBin flags:
            # SHERB_NOCONFIRMATION = 0x00000001
            # SHERB_NOPROGRESSUI = 0x00000002
            # SHERB_NOSOUND = 0x00000004
            
            shell32 = ctypes.windll.shell32
            flags = 0x00000001 | 0x00000002 | 0x00000004  # 无确认、无进度UI、无声音
            
            ret = shell32.SHEmptyRecycleBinW(None, None, flags)
            
            if ret == 0:  # S_OK
                result.cleaned_count = 1
                # 注意：无法准确知道清理了多少字节，因为API不返回这个信息
            elif ret == -2147418113:  # 0x8000FFFF - 回收站已空
                pass  # 忽略
            else:
                result.failed_count = 1
                result.errors.append(f"清空回收站失败，错误码: {ret}")
                
        except Exception as e:
            result.failed_count = 1
            result.errors.append(str(e))
        
        return result


def get_disk_usage(drive: str = "C:") -> dict:
    """
    获取磁盘使用情况
    
    Args:
        drive: 驱动器号
        
    Returns:
        包含 total, used, free 的字典
    """
    try:
        import psutil
        usage = psutil.disk_usage(drive + "\\")
        return {
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": usage.percent
        }
    except Exception:
        return {
            "total": 0,
            "used": 0,
            "free": 0,
            "percent": 0
        }
