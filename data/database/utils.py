# database/utils.py

from tkinter import messagebox
import logging
import config  # 导入配置

# 配置日志记录
logging.basicConfig(
    filename=config.LOG_FILE,
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def show_error(title: str, message: str):
    """统一的错误显示方法，并记录日志。"""
    messagebox.showerror(title, message)
    logging.error(f"{title}: {message}")
