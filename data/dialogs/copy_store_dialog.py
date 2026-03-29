# dialogs/copy_store_dialog.py

import tkinter as tk
import config
from tkinter import ttk, messagebox
from typing import Optional, Dict

class StoreCopyDialog:
    """
    店号复制对话框，允许用户选择要复制数据的父店。
    """

    def __init__(self, parent: tk.Tk, stores: Dict[str, int]):
        """
        初始化店号复制对话框。

        :param parent: 父窗口
        :param stores: 店号字典，格式为 {店名: 店ID, ...}
        """
        self.top = tk.Toplevel(parent)
        self.top.title("选择复制数据的店号")
        self.top.grab_set()  # 使对话框成为模态窗口
        self.top.resizable(False, False)

        self.stores = stores
        self.source_store_id: Optional[int] = None

        self.create_widgets()

    def create_widgets(self):
        """创建对话框的所有控件。"""
        padding = {'padx': 10, 'pady': 10}

        ttk.Label(self.top, text="选择要复制数据的店号：").pack(**padding)
        self.source_combobox = ttk.Combobox(self.top, values=list(self.stores.keys()), state="readonly", width=30)
        self.source_combobox.pack(pady=5, padx=10)
        self.source_combobox.set(config.DEFAULT_STORE_NAME)  # 默认选择默认店

        # 按钮框架
        button_frame = ttk.Frame(self.top)
        button_frame.pack(pady=10)

        # 确定和取消按钮
        ttk.Button(button_frame, text="确定", command=self.on_confirm).pack(side='left', padx=5)
        ttk.Button(button_frame, text="取消", command=self.top.destroy).pack(side='left', padx=5)

    def on_confirm(self):
        """处理确认按钮点击事件，设置源店号ID。"""
        source = self.source_combobox.get()
        if not source:
            messagebox.showwarning("输入错误", "请先选择一个源店号。")
            return
        self.source_store_id = self.stores.get(source)
        self.top.destroy()
