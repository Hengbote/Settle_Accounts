# ui/ui_components.py

import tkinter as tk
from tkinter import ttk
from functools import partial
from typing import Optional

from database.models import Product

class UIComponents:
    """
    用户界面组件类，负责创建和管理所有界面元素。
    """

    def __init__(self, app):
        """
        初始化 UIComponents。

        :param app: 主应用程序实例
        """
        self.app = app
        self._current_mousewheel_widget = None  # 当前滚轮目标控件

    def create_store_management_section(self, parent: ttk.Frame) -> None:
        """
        创建店号管理区域，包括新增店号、选择店号、删除和导入按钮。
        """
        # 店号管理区块
        self.store_mgmt_frame = ttk.LabelFrame(parent, text="店号管理", padding="5")
        self.store_mgmt_frame.pack(fill='x', pady=2)
        store_management_frame = self.store_mgmt_frame

        # 新增店号输入框和按钮
        ttk.Label(store_management_frame, text="新增店号：").grid(row=0, column=0, padx=2, pady=2, sticky='e')
        self.app.store_name_entry = ttk.Entry(store_management_frame, width=20)
        self.app.store_name_entry.grid(row=0, column=1, padx=2, pady=2, sticky='w')
        self.store_name_entry = self.app.store_name_entry
        ttk.Button(store_management_frame, text="添加", command=self.app.add_new_store).grid(row=0, column=2, padx=2, pady=2)

        # 店号选择下拉框和相关按钮
        ttk.Label(store_management_frame, text="选择店号：").grid(row=1, column=0, padx=2, pady=2, sticky='e')
        self.app.store_combobox = ttk.Combobox(store_management_frame, state="readonly", width=20)
        self.app.store_combobox.grid(row=1, column=1, padx=2, pady=2, sticky='w')
        self.store_combobox = self.app.store_combobox
        self.app.store_combobox.bind("<<ComboboxSelected>>", self.app.handle_store_selection)

        # 删除和导入店号按钮
        ttk.Button(store_management_frame, text="删除", command=self.app.remove_store).grid(row=1, column=2, padx=2, pady=2)
        ttk.Button(store_management_frame, text="导入", command=self.app.show_import_products_section).grid(row=1, column=3, padx=2, pady=2)

    def create_add_product_section(self, parent: ttk.Frame) -> None:
        """
        创建产品添加区域，包括型号、缩写、单价输入框和添加/删除按钮。
        """
        # 产品添加区块
        self.add_product_frame = ttk.LabelFrame(parent, text="添加产品", padding="5")
        self.add_product_frame.pack(fill='x', pady=2)
        add_product_frame = self.add_product_frame

        # 型号输入
        ttk.Label(add_product_frame, text="型号：").grid(row=0, column=0, padx=2, pady=2, sticky='e')
        self.model_entry = ttk.Entry(add_product_frame, width=20)
        self.model_entry.grid(row=0, column=1, padx=2, pady=2, sticky='w')
        self.app.model_entry = self.model_entry

        # 缩写输入
        ttk.Label(add_product_frame, text="缩写：").grid(row=0, column=2, padx=2, pady=2, sticky='e')
        self.abbreviations_entry = ttk.Entry(add_product_frame, width=20)
        self.abbreviations_entry.grid(row=0, column=3, padx=2, pady=2, sticky='w')
        self.app.abbreviations_entry = self.abbreviations_entry
        ttk.Label(add_product_frame, text="（用逗号分隔）").grid(row=0, column=4, padx=2, pady=2, sticky='w')

        # 单价输入
        ttk.Label(add_product_frame, text="单价：").grid(row=1, column=0, padx=2, pady=2, sticky='e')
        vcmd = (self.app.root.register(self.app.validate_price_input), '%P')
        self.price_entry = ttk.Entry(add_product_frame, validate='key', validatecommand=vcmd, width=20)
        self.price_entry.grid(row=1, column=1, padx=2, pady=2, sticky='w')
        self.app.price_entry = self.price_entry

        # 添加和删除产品按钮
        button_frame = ttk.Frame(add_product_frame)
        button_frame.grid(row=1, column=3, padx=2, pady=2, sticky='w')
        ttk.Button(button_frame, text="添加", command=self.app.add_product).pack(side='left', padx=5)
        ttk.Button(button_frame, text="删除", command=self.app.delete_product).pack(side='left', padx=5)

    def create_search_section(self, parent: ttk.Frame) -> None:
        """
        创建搜索区域，包括搜索输入框和搜索按钮。
        """
        self.search_frame = ttk.LabelFrame(parent, text="搜索产品", padding="5")
        self.search_frame.pack(fill='x', pady=2)
        search_frame = self.search_frame

        # 搜索输入框和按钮
        ttk.Label(search_frame, text="搜索：").grid(row=0, column=0, padx=2, pady=2, sticky='e')
        self.search_entry = ttk.Entry(search_frame, width=30)
        self.search_entry.grid(row=0, column=1, padx=2, pady=2, sticky='w')
        self.search_entry.bind('<KeyRelease>', self.app.handle_search_key_release)
        self.app.search_entry = self.search_entry
        ttk.Button(search_frame, text="搜索", command=self.app.handle_search_button_click).grid(row=0, column=2, padx=2, pady=2)

    def create_product_list_section(self, parent: ttk.Frame) -> None:
        """
        创建产品列表区域，包括 Treeview 和滚动条。
        """
        self.product_list_frame = ttk.LabelFrame(parent, text="产品列表", padding="5")
        self.product_list_frame.pack(fill='both', expand=True, pady=2)
        list_frame = self.product_list_frame

        # 定义Treeview列
        self.base_columns = ("型号", "缩写", "单价")
        self.store_column = "店号"
        self.all_columns = self.base_columns + (self.store_column,)

        self.app.base_columns = self.base_columns
        self.app.store_column = self.store_column
        self.app.all_columns = self.all_columns

        # 产品列表表格
        self.tree = ttk.Treeview(list_frame, columns=self.app.all_columns, show='headings', selectmode='browse')
        self.tree.pack(side='left', fill='both', expand=True)
        self.app.tree = self.tree  # 让主程序也能访问

        # 设置显示行数
        self.app.tree.configure(height=20)

        # 列宽设置
        equal_width = 150
        store_width = 80
        self.column_widths = {
            "型号": equal_width,
            "缩写": equal_width,
            "单价": equal_width,
            "店号": store_width
        }
        self.app.column_widths = self.column_widths

        # 配置列和排序功能
        for col in self.app.all_columns:
            self.app.tree.heading(col, text=col, command=partial(self.app.sort_by_column, col))
            self.app.tree.column(col, width=self.app.column_widths[col], anchor='center', stretch=True if col != self.app.store_column else False)

        self.app.is_store_column_displayed = False
        self.app.hide_store_column()

        # 垂直滚动条
        self.app.vertical_scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.app.tree.yview)
        self.app.tree.configure(yscrollcommand=self.app.vertical_scrollbar.set)
        self.app.vertical_scrollbar.pack(side='right', fill='y')

    def create_status_label(self, parent: ttk.Frame) -> None:
        """
        创建状态标签，用于显示操作反馈信息。
        """
        self.status_label = ttk.Label(parent, text="", foreground="blue")
        self.status_label.pack(fill='x', pady=2)
        self.app.status_label = self.status_label  # 让主程序和UI都能访问

    def create_import_products_section(self, parent):
        """
        创建导入产品专用区块，包括源店选择、目标店多选、差异显示和导入按钮，并支持整体滚动。
        """
        # 外层Frame
        self.import_frame = ttk.Frame(parent, padding="0")
        self.import_frame.pack(fill='both', expand=True)
        self.import_frame.place_forget()  # 初始隐藏

        # Canvas + Scrollbar
        self.import_canvas = tk.Canvas(self.import_frame, borderwidth=0, highlightthickness=0)
        self.import_scrollbar = ttk.Scrollbar(self.import_frame, orient="vertical", command=self.import_canvas.yview)
        self.import_canvas.configure(yscrollcommand=self.import_scrollbar.set)
        self.import_canvas.pack(side="left", fill="both", expand=True)
        self.import_scrollbar.pack(side="right", fill="y")

        # 内容Frame
        self.import_content = ttk.Frame(self.import_canvas)
        self.import_canvas.create_window((0, 0), window=self.import_content, anchor="nw")

        # Canvas滚动区域自适应
        def _on_frame_configure(event):
            self.import_canvas.configure(scrollregion=self.import_canvas.bbox("all"))
        self.import_content.bind("<Configure>", _on_frame_configure)

        # 鼠标滚轮支持（内容区和canvas空白区都能滚动）
        self.import_content.bind("<Enter>", lambda e: self._set_mousewheel_target(self.import_canvas))
        self.import_content.bind("<Leave>", lambda e: self._set_mousewheel_target(None))
        self.import_canvas.bind("<Enter>", lambda e: self._set_mousewheel_target(self.import_canvas))
        self.import_canvas.bind("<Leave>", lambda e: self._set_mousewheel_target(None))

        # 差异搜索 输入框
        ttk.Label(self.import_content, text="差异搜索：").grid(row=0, column=0, sticky='w', padx=2, pady=2)
        self.search_diff_entry = ttk.Entry(self.import_content, width=30)
        self.search_diff_entry.grid(row=0, column=1, sticky='w', padx=2, pady=2)
        self.search_diff_entry.bind('<KeyRelease>', self.app.handle_diff_search)

        # 源店选择
        ttk.Label(self.import_content, text="选择源店:").grid(row=1, column=0, sticky='w')
        self.source_store_var = tk.StringVar()
        self.source_store_cb = ttk.Combobox(self.import_content, textvariable=self.source_store_var, state='readonly')
        self.source_store_cb.grid(row=1, column=1, sticky='w')

        # 目标店多选
        ttk.Label(self.import_content, text="选择目标店(可多选):").grid(row=2, column=0, sticky='nw')
        self.target_store_vars = {}
        self.target_store_checks = {}
        self.target_store_frame = ttk.Frame(self.import_content)
        self.target_store_frame.grid(row=2, column=1, sticky='w')

        # 差异显示区
        self.diff_frame = ttk.Frame(self.import_content)
        self.diff_frame.grid(row=3, column=0, columnspan=2, sticky='we', pady=10)

        # 导入与取消按钮
        self.import_btn = ttk.Button(self.import_content, text="执行导入", command=self.app.on_import_execute)
        self.import_btn.grid(row=4, column=0, pady=10)
        self.cancel_btn = ttk.Button(self.import_content, text="取消", command=self.app.hide_import_products_section)
        self.cancel_btn.grid(row=4, column=1, pady=10)

        # 绑定事件
        self.source_store_cb.bind("<<ComboboxSelected>>", self.app.on_source_store_selected)

    def _set_mousewheel_target(self, widget):
        """
        设置当前滚轮目标控件，实现局部或全局滚动。
        """
        if self._current_mousewheel_widget:
            self._current_mousewheel_widget.unbind_all("<MouseWheel>")
        self._current_mousewheel_widget = widget
        if widget:
            widget.bind_all("<MouseWheel>", lambda e: widget.yview_scroll(int(-1*(e.delta/120)), "units"))

    def show_import_products_section(self):
        """
        显示导入产品区块，隐藏主界面其他区块，并初始化下拉框和多选框。
        """
        self.import_frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.hide_main_sections()
        # 初始化源店下拉框
        store_names = list(self.app.stores.keys())
        self.source_store_cb['values'] = store_names
        self.source_store_var.set('')
        # 清空目标店多选
        for widget in self.target_store_frame.winfo_children():
            widget.destroy()
        self.target_store_vars.clear()
        self.target_store_checks.clear()
        # 清空差异区
        for widget in self.diff_frame.winfo_children():
            widget.destroy()

    def hide_import_products_section(self):
        """
        隐藏导入产品区块，恢复主界面区块。
        """
        self.import_frame.place_forget()
        self.show_main_sections()

    def hide_main_sections(self):
        """
        隐藏主界面区块（如店号管理、产品添加、搜索、产品列表、状态栏）。
        """
        self.store_mgmt_frame.pack_forget()
        self.add_product_frame.pack_forget()
        self.search_frame.pack_forget()
        self.product_list_frame.pack_forget()
        self.status_label.pack_forget()

    def show_main_sections(self):
        """
        显示主界面区块。
        """
        self.store_mgmt_frame.pack(fill='x')
        self.add_product_frame.pack(fill='x')
        self.search_frame.pack(fill='x')
        self.product_list_frame.pack(fill='both', expand=True)
        self.status_label.pack(fill='x')
