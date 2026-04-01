
import json
import os
import sqlite3
import sys
import tkinter as tk
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from tkinter import messagebox, ttk

from PIL import Image, ImageTk
from zoneinfo import ZoneInfo


# ===== 全局配置 =====
APP_TIMEZONE = ZoneInfo("America/Sao_Paulo")    # 统一使用圣保罗时区
DEFAULT_TAB_TITLE = "新订单"                    # 新标签页默认标题
DEFAULT_ROW_COUNT = 16                          # 每个订单页默认创建的产品行数
DRAFT_SAVE_DELAY_MS = 1000                      # 草稿延迟保存时间（毫秒）
TAB_TITLE_MAX_LEN = 3                           # tab 标题最多显示多少个字符


@dataclass
class ProductRow:
    """
    表格中一行产品的状态对象

    作用：
    1. 保存这一行对应的 4 个核心数据变量
    2. 保存这一行部分控件的引用（后面做焦点跳转、建议框定位时要用）
    3. 保存型号自动补全相关状态
    """
    # ===== 这一行产品对应的 4 个核心数据变量 =====
    quantity_var: tk.StringVar      # 数量
    model_var: tk.StringVar         # 型号
    price_var: tk.StringVar         # 单价
    total_var: tk.StringVar         # 该行总价 = 数量 × 单价

    # ===== 这一行里部分控件的引用 =====
    # 保存控件引用的目的，是为了后面做焦点跳转、弹出建议框定位、键盘操作等
    model_entry: ttk.Entry = None       # 型号输入框
    quantity_entry: ttk.Entry = None    # 数量输入框

    # ===== 型号自动补全相关状态 =====
    suggestion_listbox: tk.Listbox = None   # 当前这一行型号建议框
    suggestions: list = field(default_factory=list)  # 当前建议项列表
    suggestion_index: int = -1              # 当前高亮项索引，-1 表示还没选中任何项


class OrderTab:
    """
    每个标签（订单）的封装：独立 UI、独立数据（entries、total_price_var、store_id）；
    使用 app 提供的数据库连接与店铺列表（共享）。
    """

    def __init__(self, app, notebook=None, title=DEFAULT_TAB_TITLE):
        """app 是主程序对象 ProductEntryApp
            通过它可以访问：
            1. 主窗口 root
            2. 数据库连接
            3. 店铺数据
            4. tab 管理方法 """

        self.app = app                # 指向主程序（共享 DB、stores）
        self.root = app.root
        self.notebook = notebook      # 预留参数；当前自定义 tab 方案里实际没使用 ttk.Notebook
        self.title = title            # 当前标签页标题（逻辑标题，不一定等于按钮最终显示文本）

        # 当前订单页自己的外层 frame / UI 关键区域引用
        self.frame = None          # 当前 tab 对应的最外层容器；切换 tab 时显示/隐藏的就是它
        self.main_frame = None     # 当前订单页的主框架；页面里的大部分区域都挂在它下面
        self.table_frame = None    # 商品表格真正承载内容的内部 frame；每一行产品控件都放在这里
        self.table_window = None   # Canvas 中承载 table_frame 的“窗口对象 id”；后面要靠它同步宽度
        self.canvas = None         # 商品表格区的 Canvas；用于实现滚动区域
        self.scrollbar = None      # 商品表格区右侧滚动条；和 canvas.yview 联动
        self.logo_photo = None     # Logo 对应的 PhotoImage 引用；必须保存引用，否则 Tkinter 图片会消失

        # ===== 当前订单页独立拥有的数据 =====
        self.entries = []                         # 当前 tab 中所有产品行（ProductRow）
        self.total_price_var = tk.StringVar(value="")   # 当前订单页“所有产品总价”
        self.store_id = None                      # 当前订单页选中的店铺 ID
        self._date_after_id = None               # after 定时器 id（预留给日期更新/取消）
        self._restoring_state = False            # 是否正处于恢复草稿/批量回填状态

        # ===== 先 UI 元素占位，后面 setup_ui() 再创建实际控件 =====
        self.store_combo = None       # 店铺下拉框；选择店铺后会决定型号建议和单价查询的范围
        self.date_entry = None        # 日期输入框；默认显示当前时间，也会随草稿恢复而回填
        self.customer_entry = None    # 客人输入框；支持历史客户自动补全
        self.ship_time_entry = None   # 发货时间输入框；作为订单附加信息保存进草稿/正式数据

        self.customer_suggestion_frame = None        # 客人建议框最外层容器；用于整体 place / 隐藏
        self.customer_suggestion_listbox = None      # 客人建议列表本体；真正显示候选客户名称
        self.customer_scrollbar = None               # 客人建议列表滚动条；建议项多时可滚动查看
        self.customer_suggestion_listbox_visible = False  # 当前客人建议框是否处于显示状态
        self.customer_suggestion_index = -1          # 当前客人建议高亮索引；-1 表示还没选中任何项

    # ---------- UI 构建 ----------
    def setup_ui(self, parent):
        """在 parent 内建立订单页面
        """
        # 主框架
        self.main_frame = ttk.Frame(parent)
        self.main_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # 把原来的长 UI 构建流程拆成多个小步骤
        self._build_header()                  # 顶部：Logo + 文本 + 按钮区域
        self._build_store_and_date_section()  # 店号 + 日期
        self._build_customer_section()        # 客人 + 自动完成 + 发货时间
        self._build_total_section()           # 总价显示
        self._build_table_section()           # 商品表格区（Canvas + Frame）

        # 默认添加若干行
        for _ in range(DEFAULT_ROW_COUNT):
            self.add_row()

    def _build_header(self):
        """构建顶部区域：Logo、公司信息、功能按钮"""
        top_frame = ttk.Frame(self.main_frame)
        top_frame.pack(fill="x", pady=5)

        header_frame = ttk.Frame(top_frame)
        header_frame.pack(side="left", fill="x", expand=True)

        logo_label = self._build_logo_label(header_frame)
        logo_label.pack(side="left", padx=(0, 10))

        text_frame = ttk.Frame(header_frame)
        text_frame.pack(side="left", fill="x", expand=True)
        ttk.Label(text_frame, text="PELICULAS - CAPAS PARA", font=("Arial", 10, "bold")).pack(anchor="w")
        ttk.Label(text_frame, text="CELULAR E ACESSORIOS", font=("Arial", 10, "bold")).pack(anchor="w")
        ttk.Label(text_frame, text="📞: (11)95066-6669 Ting", font=("Arial", 9)).pack(anchor="w")
        ttk.Label(text_frame, text="📞: (11)99798-8888 Henney", font=("Arial", 9)).pack(anchor="w")

        # 按钮区域（垂直放置在右上角）
        button_frame = ttk.Frame(top_frame)
        button_frame.pack(side="right", anchor="n", padx=8)

        self.add_row_button = ttk.Button(button_frame, text="添加新产品行", command=self.add_row)
        self.add_row_button.pack(side="top", pady=2)

        self.save_button = ttk.Button(button_frame, text="保存数据", command=self.save_data)
        self.save_button.pack(side="top", pady=2)

    def _build_logo_label(self, parent):
        """尝试加载 Logo；失败时使用文本占位
        """
        logo_path = self.app.resource_path("HUANG_Logo.PNG")
        try:
            logo_image = Image.open(logo_path)
            logo_image = logo_image.resize((90, 90), Image.LANCZOS)
            self.logo_photo = ImageTk.PhotoImage(logo_image)
            return ttk.Label(parent, image=self.logo_photo)
        except Exception:
            self.logo_photo = None
            return ttk.Label(parent, text="[Logo]", font=("Arial", 16, "bold"))

    def _build_store_and_date_section(self):
        """构建“店号 + 日期”这一行"""
        store_date_frame = ttk.Frame(self.main_frame)
        store_date_frame.pack(fill="x", pady=5)

        store_frame = ttk.Frame(store_date_frame)
        store_frame.pack(side="left", fill="x", expand=True)

        ttk.Label(store_frame, text="店号：", font=("Segoe UI", 12, "bold")).pack(side="left")
        self.store_combo = ttk.Combobox(store_frame, state="readonly", width=18, font=("Segoe UI", 12, "bold"))
        self.store_combo.pack(side="left", fill="x", expand=True)
        self.store_combo.bind("<<ComboboxSelected>>", lambda e: self.on_store_selected())

        date_frame = ttk.Frame(store_date_frame)
        date_frame.pack(side="right")
        ttk.Label(date_frame, text="理货日期：", font=("Segoe UI", 12, "bold")).pack(side="left")

        self.date_entry = ttk.Entry(date_frame, width=40, font=("Segoe UI", 12, "bold"))
        self.date_entry.pack(side="left")
        self.date_entry.bind("<KeyRelease>", lambda e: self.mark_draft_dirty())
        self.set_current_datetime()

    def _build_customer_section(self):
        """构建“客人 + 自动补全 + 发货时间”区域"""
        customer_frame = ttk.Frame(self.main_frame)
        customer_frame.pack(fill="x", pady=0)

        ttk.Label(customer_frame, text="客人：", font=("Segoe UI", 12, "bold")).pack(side="left")
        self.customer_entry = ttk.Entry(customer_frame, width=20, font=("Segoe UI", 12, "bold"))
        self.customer_entry.pack(side="left", fill="x", expand=True)
        self.customer_entry.bind("<KeyRelease>", self.on_customer_keyrelease)
        self.customer_entry.bind("<Down>", self.on_customer_down_key)
        self.customer_entry.bind("<Up>", self.on_customer_up_key)
        self.customer_entry.bind("<Return>", self.on_customer_enter)
        self.customer_entry.bind("<FocusOut>", self.on_customer_focus_out)

        # 自动完成 Listbox（放在 root 层使用 place，避免被 canvas 遮挡）
        self.customer_suggestion_frame = tk.Frame(self.root, bd=1, relief="solid")
        self.customer_suggestion_listbox = tk.Listbox(self.customer_suggestion_frame, height=6, font=("Segoe UI", 11))
        self.customer_scrollbar = ttk.Scrollbar(
            self.customer_suggestion_frame,
            orient="vertical",
            command=self.customer_suggestion_listbox.yview,
        )
        self.customer_suggestion_listbox.configure(yscrollcommand=self.customer_scrollbar.set)
        self.customer_suggestion_listbox.pack(side="left", fill="both", expand=True)
        self.customer_scrollbar.pack(side="right", fill="y")
        self.customer_suggestion_frame.place_forget()

        self.customer_suggestion_listbox.bind("<ButtonRelease-1>", self.on_customer_listbox_click)
        self.customer_suggestion_listbox.bind("<<ListboxSelect>>", self.on_customer_listbox_select)
        self.customer_suggestion_listbox.bind("<Return>", self.on_customer_enter)
        self.customer_suggestion_listbox.bind("<FocusOut>", self.on_listbox_focus_out)

        ship_frame = ttk.Frame(customer_frame)
        ship_frame.pack(side="left")
        ttk.Label(ship_frame, text="发货时间：", font=("Segoe UI", 12, "bold")).pack(side="left")

        self.ship_time_entry = ttk.Entry(ship_frame, width=20, font=("Segoe UI", 12))
        self.ship_time_entry.pack(side="left")
        self.ship_time_entry.bind("<KeyRelease>", lambda e: self.mark_draft_dirty())

    def _build_total_section(self):
        """构建总价显示区"""
        total_frame = ttk.Frame(self.main_frame)
        total_frame.pack(fill="x", pady=5)
        ttk.Label(total_frame, text="所有产品总价：", font=("Segoe UI", 16, "bold")).pack(side="left")
        ttk.Label(total_frame, textvariable=self.total_price_var, font=("Segoe UI", 16, "bold")).pack(side="left", padx=(10, 0))

    def _build_table_section(self):
        """构建商品表格区：Canvas + 内部 Frame + 滚动条
        """
        self.canvas = tk.Canvas(self.main_frame, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self.main_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        # 鼠标进入 canvas 时绑定滚轮；离开时解绑，避免影响别的区域
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._on_mousewheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

        self.table_frame = ttk.Frame(self.canvas)
        self.table_window = self.canvas.create_window((0, 0), window=self.table_frame, anchor="nw")

        self.table_frame.bind("<Configure>", self.on_frame_configure)
        self.canvas.bind("<Configure>", self.on_canvas_configure)

        self.create_table_headers()

    # ---------- 数据读取辅助 ----------
    def _get_var_text(self, var):
        """统一读取 StringVar 文本，并顺手 strip()

        这是重构里新增的小工具方法。
        目的：减少满文件反复写 var.get().strip()。
        """
        return var.get().strip()

    def _set_entry_text(self, entry, value):
        """统一设置输入框文本：先清空，再插入新值"""
        entry.delete(0, tk.END)
        entry.insert(0, value)

    def _clear_product_row(self, product_row):
        """清空一行产品数据，并顺手隐藏这行的建议框

        这是保存成功后清表单时会复用的动作。
        抽成方法后，不用在多个地方重复写四次 set("")。
        """
        product_row.quantity_var.set("")
        product_row.model_var.set("")
        product_row.price_var.set("")
        product_row.total_var.set("")
        self.hide_suggestion_listbox(product_row)

    def _apply_customer_value(self, value, keep_focus=False, hide_suggestion=False):
        """把某个客人值真正应用到输入框中

        这个方法是重构新增的。
        原版里“方向键切换客人”和“确认客人选择”两处代码高度重复：
        都要改输入框、改 tab 标题、同步店铺、标记草稿。
        现在统一收口到这里。
        """
        self._set_entry_text(self.customer_entry, value)
        if keep_focus:
            self.customer_entry.focus_set()
            self.customer_entry.icursor(tk.END)

        self.app.update_tab_title(self, value)
        self.update_store_based_on_customer(value)
        self.mark_draft_dirty()

        if hide_suggestion:
            self.hide_customer_suggestion()

    def _sync_store_from_combo(self):
        """根据当前下拉框中的店铺名称，同步出 store_id

        原版是遍历 stores_by_id 做反向查找。
        现在 app 里多维护了一张 store_name_to_id 映射表，
        这里就能 O(1) 查到店铺 id。
        """
        store_name = self.store_combo.get()
        self.store_id = self.app.store_name_to_id.get(store_name)

    # ---------- 表格与行控制 ----------
    def create_table_headers(self):
        """创建表格头
            表头只创建一次，后续 add_row() 添加的都是数据行。
            这里把列名和列宽集中写在一起，后面改表头布局时更容易统一调整。"""
        headers = ["数量", "型号", "单价", "型号总价"]
        column_widths = [8, 18, 8, 12]
        for idx, header in enumerate(headers):
            ttk.Label(
                self.table_frame,
                text=header,
                font=("Segoe UI", 12, "bold"),
                width=column_widths[idx],
            ).grid(row=0, column=idx, sticky="w", padx=2, pady=2)

    def add_row(self):
        """添加一行产品输入
            每调用一次 add_row()，就向当前订单页追加一行商品输入。
            这里返回 product_row，方便后面如果要“新增一行后立刻聚焦”之类的扩展。"""
        row_index = len(self.entries) + 1
        # 为每个 tab 的变量设定 master 为该 tab 的 table_frame，
        # 避免不同 tab 变量混用。
        product_row = ProductRow(
            quantity_var=tk.StringVar(master=self.table_frame),
            model_var=tk.StringVar(master=self.table_frame),
            price_var=tk.StringVar(master=self.table_frame),
            total_var=tk.StringVar(master=self.table_frame, value=""),
        )
        self.create_product_row_widgets(row_index, product_row)
        self.entries.append(product_row)
        return product_row

    def create_product_row_widgets(self, row_index, product_row):
        """创建单行产品输入控件
            1. 创建输入框并放到 grid 中
            2. 保存关键控件引用（数量框、型号框）
            3. 绑定变量联动和键盘事件"""
        vars_list = [product_row.quantity_var, product_row.model_var, product_row.price_var, product_row.total_var]
        column_widths = [8, 18, 8, 12]

        for idx, var in enumerate(vars_list):
            state = "readonly" if idx == 3 else "normal"
            entry = ttk.Entry(
                self.table_frame,
                textvariable=var,
                font=("Segoe UI", 12, "bold"),
                width=column_widths[idx],
                state=state,
            )
            entry.grid(row=row_index, column=idx, sticky="w", padx=2, pady=1)

            if idx == 0:
                product_row.quantity_entry = entry
            elif idx == 1:
                product_row.model_entry = entry

            # 绑定左右上下键移动
            for arrow_key in ("<Up>", "<Down>", "<Left>", "<Right>"):
                entry.bind(arrow_key, lambda e, pr=product_row, col=idx: self.navigate_entry(e, pr, col))

        product_row.quantity_var.trace_add("write", lambda *a, pr=product_row: self.on_quantity_or_price_change(pr))
        product_row.model_var.trace_add("write", lambda *a, pr=product_row: self.on_model_var_change(pr))
        product_row.price_var.trace_add("write", lambda *a, pr=product_row: self.on_quantity_or_price_change(pr))

        product_row.model_entry.bind("<KeyRelease>", lambda e, pr=product_row: self.on_model_entry_keyrelease(e, pr))

    def navigate_entry(self, event, product_row, column):
        """处理方向键在各个输入框之间进行切换的操作
            方向键导航：让表格里的输入框像表格一样上下左右移动。
            但如果当前型号建议框正开着，上下键就优先交给建议框处理，
            否则用户想选建议项时会被直接切走焦点。"""
        # 如果当前这一行有 suggestion listbox 可见，优先让建议框处理方向键
        if product_row.suggestion_listbox and product_row.suggestion_listbox.winfo_viewable():
            return

        try:
            current_row = int(event.widget.grid_info()["row"])
            current_col = int(event.widget.grid_info()["column"])
        except Exception:
            return

        if event.keysym == "Up":
            target_row, target_col = current_row - 1, current_col
        elif event.keysym == "Down":
            target_row, target_col = current_row + 1, current_col
        elif event.keysym == "Left":
            target_row, target_col = current_row, current_col - 1
        elif event.keysym == "Right":
            target_row, target_col = current_row, current_col + 1
        else:
            return

        if target_row < 1 or target_col < 0 or target_col > 3:
            return "break"

        widgets = self.table_frame.grid_slaves(row=target_row, column=target_col)
        if widgets:
            widgets[0].focus_set()
        return "break"

    # ---------- 型号建议 & 价格查询 ----------
    def on_model_var_change(self, product_row):
        """当型号变量改变时更新建议列表或清空相关字段"""
        if self._restoring_state:
            return

        value = product_row.model_var.get()
        if value == "":
            self.hide_suggestion_listbox(product_row)
            product_row.price_var.set("")
            self.update_total_price(product_row)
        else:
            self.show_suggestions(product_row, value)

        self.mark_draft_dirty()

    def on_model_entry_keyrelease(self, event, product_row):
        """处理型号输入框的键盘事件
            普通字符：走“重新查建议”
            上下/回车/Esc：走“操作建议框”"""
        if event.keysym in ("Up", "Down", "Return", "Escape"):
            if product_row.suggestion_listbox and product_row.suggestion_listbox.winfo_viewable():
                if event.keysym == "Up":
                    self.move_in_suggestions(product_row, -1)
                elif event.keysym == "Down":
                    self.move_in_suggestions(product_row, 1)
                elif event.keysym == "Return":
                    self.select_suggestion(product_row)
                elif event.keysym == "Escape":
                    self.hide_suggestion_listbox(product_row)
            return

        if not event.char:
            return

        self.on_model_var_change(product_row)

    def show_suggestions(self, product_row, text):
        """从共享 DB 查询型号并在表格附近显示 listbox

        优化点：
        原版直接在这个方法里写 SQL。
        现在改为调用 self.app.get_model_suggestions(...)，
        让订单页少直接碰数据库细节。
        """
        if not self.store_id:
            self.hide_suggestion_listbox(product_row)
            return

        suggestions = self.app.get_model_suggestions(self.store_id, text)
        if not suggestions:
            self.hide_suggestion_listbox(product_row)
            return

        product_row.suggestions = suggestions
        if product_row.suggestion_listbox is None:
            height = min(len(suggestions), 10)
            product_row.suggestion_listbox = tk.Listbox(self.table_frame, height=height, width=20)
            product_row.suggestion_listbox.bind("<<ListboxSelect>>", partial(self.on_listbox_select, product_row))
            product_row.suggestion_listbox.bind("<Button-1>", partial(self.on_listbox_click, product_row))
        else:
            product_row.suggestion_listbox.delete(0, tk.END)
            product_row.suggestion_listbox.config(height=min(len(suggestions), 10))

        for suggestion in suggestions:
            product_row.suggestion_listbox.insert(tk.END, suggestion)

        self.root.update_idletasks()
        entry = product_row.model_entry
        x = entry.winfo_rootx() - self.table_frame.winfo_rootx()
        y = entry.winfo_rooty() - self.table_frame.winfo_rooty() + entry.winfo_height()
        product_row.suggestion_listbox.place(x=x, y=y, width=entry.winfo_width())
        product_row.suggestion_index = -1

    def hide_suggestion_listbox(self, product_row):
        """隐藏建议列表框
            统一关闭某一行的型号建议框，并把建议状态清空。
            以后只要需要“收起建议框”，都尽量走这个方法，避免销毁逻辑写散。"""
        if product_row.suggestion_listbox:
            product_row.suggestion_listbox.place_forget()
            product_row.suggestion_listbox.destroy()
            product_row.suggestion_listbox = None
        product_row.suggestions = []
        product_row.suggestion_index = -1

    def move_in_suggestions(self, product_row, delta):
        """在型号建议列表中移动高亮项选择
            这里只改“高亮位置”，不直接确认；确认动作交给 select_suggestion()"""
        if not product_row.suggestions or not product_row.suggestion_listbox:
            return

        product_row.suggestion_index += delta
        if product_row.suggestion_index < 0:
            product_row.suggestion_index = len(product_row.suggestions) - 1
        elif product_row.suggestion_index >= len(product_row.suggestions):
            product_row.suggestion_index = 0

        product_row.suggestion_listbox.selection_clear(0, tk.END)
        product_row.suggestion_listbox.selection_set(product_row.suggestion_index)
        product_row.suggestion_listbox.activate(product_row.suggestion_index)

    def select_suggestion(self, product_row):
        """选择建议列表中的型号
            确认当前高亮的型号建议。
            一旦确认：写回型号 -> 关闭建议框 -> 自动查单价"""
        if product_row.suggestions and product_row.suggestion_index >= 0:
            selected = product_row.suggestions[product_row.suggestion_index]
            product_row.model_var.set(selected)
            self.hide_suggestion_listbox(product_row)
            self.fetch_price(product_row)

    def on_listbox_select(self, product_row, event):
        """处理 Listbox 选择事件（这里不直接做额外动作）"""
        pass

    def on_listbox_click(self, product_row, event):
        """处理Listbox点击事件
            鼠标点击型号建议时，直接把点击项作为最终结果。
            这和键盘回车确认的业务效果是一致的。"""
        if not product_row.suggestion_listbox:
            return

        idx = product_row.suggestion_listbox.nearest(event.y)
        selected = product_row.suggestion_listbox.get(idx)
        product_row.model_var.set(selected)
        self.hide_suggestion_listbox(product_row)
        self.fetch_price(product_row)

    def fetch_price(self, product_row):
        """根据型号获取价格并更新
            走 self.app.get_product_price(...)。"""
        
        model = self._get_var_text(product_row.model_var)
        price = self.app.get_product_price(model, self.store_id)
        product_row.price_var.set("" if price is None else f"{price:.2f}")
        self.update_total_price(product_row)

    def update_total_price(self, product_row, recalculate_order_total=True):
        """更新单行和总价
        - 平时改单行时，保持原来的行为：顺手重算整单总价
        - 批量更新所有行价格时，可以先只算每一行，最后统一整单重算一次
        """
        model = self._get_var_text(product_row.model_var)
        if not model:
            product_row.total_var.set("")
            if recalculate_order_total:
                self.calculate_total_price()
            return

        try:
            qty = float(product_row.quantity_var.get() or 0)
            price = float(product_row.price_var.get() or 0)
            total = qty * price
            product_row.total_var.set("" if total == 0 else f"{total:.2f}")
        except ValueError:
            product_row.total_var.set("")

        if recalculate_order_total:
            self.calculate_total_price()

    def calculate_total_price(self):
        """计算所有产品的总价"""
        total = 0.0
        has_product = False
        for product_row in self.entries:
            if self._get_var_text(product_row.model_var):
                has_product = True
                try:
                    total += float(product_row.total_var.get() or 0)
                except ValueError:
                    continue

        self.total_price_var.set(f"{total:.2f}" if has_product else "")

    # ---------- 草稿相关 ----------
    def on_quantity_or_price_change(self, product_row):
        """当“数量”或“单价”发生变化时调用
            作用：
            1. 重新计算这一行的小计和整单总价
            2. 标记当前订单页需要保存草稿"""
        if self._restoring_state:
            return
        self.update_total_price(product_row)
        self.mark_draft_dirty()

    def mark_draft_dirty(self):
        """标记当前订单页“草稿已变脏”
        注意：这里不直接保存，而是交给 app 统一做延迟保存。
        """
        if self._restoring_state or self.app._restoring_drafts:
            return
        self.app.schedule_draft_save()

    def get_current_datetime_text(self):
        """统一生成当前时间文本
            获取当前圣保罗时间，并格式化成字符串"""
        return datetime.now(APP_TIMEZONE).strftime("%d/%m/%Y %H:%M")

    def set_date_value(self, value):
        """向日期输入框写值的统一入口"""
        self._set_entry_text(self.date_entry, value)

    def set_current_datetime(self):
        """把日期输入框设置为“当前时间
            保存成功后清表、首次建页时都会用到。”"""
        self.set_date_value(self.get_current_datetime_text())

    def has_meaningful_data(self):
        """判断当前 tab 是否“值得保存成草稿”
            只要客人、发货时间或任意一行商品有内容，就认为这个页有意义
        """
        if self.customer_entry.get().strip():
            return True
        if self.ship_time_entry.get().strip():
            return True

        return any(
            self._get_var_text(product_row.quantity_var)
            or self._get_var_text(product_row.model_var)
            or self._get_var_text(product_row.price_var)
            or self._get_var_text(product_row.total_var)
            for product_row in self.entries
        )

    def get_draft_data(self):
        """把当前订单页导出为“可保存的草稿数据”
            把当前订单页序列化成一个纯字典，供 JSON 草稿保存使用。
            这里不保存控件对象，只保存真正需要恢复的数据。"""
        # 把每一行产品数据都收集起来
        rows = [
            {
                "quantity": product_row.quantity_var.get(), # 数量
                "model": product_row.model_var.get(),       # 型号
                "price": product_row.price_var.get(),       # 单价
                "total": product_row.total_var.get(),       # 该行总价
            }
            for product_row in self.entries
        ]

        # 返回整个订单页的数据结构
        return {
            "store_id": self.store_id,               # 当前店铺 ID
            "store_name": self.store_combo.get(),    # 当前店铺名称（双保险）
            "date": self.date_entry.get(),           # 日期
            "customer": self.customer_entry.get(),   # 客人
            "ship_time": self.ship_time_entry.get(), # 发货时间
            "rows": rows,                            # 所有产品行
        }

    def apply_draft_data(self, draft_data):
        """把一份草稿数据重新恢复到当前订单页界面
            把草稿字典重新灌回当前订单页。
            这里一定要先进入 _restoring_state，避免回填过程中触发联动保存。"""
        self._restoring_state = True
        try:
            store_id = draft_data.get("store_id")
            store_name = draft_data.get("store_name", "")
            resolved_name = self.app.stores_by_id.get(store_id, store_name)

            if resolved_name:
                self.store_combo.set(resolved_name)
                self.store_id = self.app.store_name_to_id.get(resolved_name)
            else:
                self.store_id = None
                self.store_combo.set("")

            self.set_date_value(draft_data.get("date", self.get_current_datetime_text()))
            self._set_entry_text(self.customer_entry, draft_data.get("customer", ""))
            self._set_entry_text(self.ship_time_entry, draft_data.get("ship_time", ""))

            rows = draft_data.get("rows", [])
            target_count = max(DEFAULT_ROW_COUNT, len(rows))
            while len(self.entries) < target_count:
                self.add_row()

            for idx, product_row in enumerate(self.entries):
                row = rows[idx] if idx < len(rows) else {}
                product_row.quantity_var.set(row.get("quantity", ""))
                product_row.model_var.set(row.get("model", ""))
                product_row.price_var.set(row.get("price", ""))
                product_row.total_var.set(row.get("total", ""))

            self.calculate_total_price()
            self.app.update_tab_title(self, draft_data.get("customer", ""))
        finally:
            self._restoring_state = False

    # ---------- 客人自动完成 ----------
    def on_customer_keyrelease(self, event):
        """客人输入框的主入口：
        - 普通输入：刷新 tab 名、刷新建议
        - 上下/回车/Esc：交给其他专门方法处理"""
        if event.keysym in ("Up", "Down", "Return", "Escape"):
            return

        text = self.customer_entry.get()
        if text == "":
            self.hide_customer_suggestion()
            # 更新 tab 名称为空或默认
            self.app.update_tab_title(self, DEFAULT_TAB_TITLE)
            self.mark_draft_dirty()
            return

        # 动态更新 tab 名称为输入值（即时）
        self.app.update_tab_title(self, text)
        self.update_customer_suggestions(text)
        self.mark_draft_dirty()

    def update_customer_suggestions(self, text):
        """根据客人输入文本去历史订单里查建议。
        调用 self.app.get_customer_suggestions(text)。
        """
        suggestions = self.app.get_customer_suggestions(text)
        if suggestions:
            self.show_customer_suggestion(suggestions)
        else:
            self.hide_customer_suggestion()

    def show_customer_suggestion(self, suggestions):
        """显示客人自动完成框，并把它定位到客人输入框正下方"""
        self.customer_suggestion_listbox.delete(0, tk.END)
        for suggestion in suggestions:
            self.customer_suggestion_listbox.insert(tk.END, suggestion)

        x = self.customer_entry.winfo_rootx() - self.root.winfo_rootx()
        y = self.customer_entry.winfo_rooty() - self.root.winfo_rooty() + self.customer_entry.winfo_height()
        self.customer_suggestion_frame.place(x=x, y=y, width=self.customer_entry.winfo_width())
        self.customer_suggestion_frame.lift()

        self.customer_suggestion_index = -1
        self.customer_suggestion_listbox.selection_clear(0, tk.END)
        self.customer_suggestion_listbox_visible = True

    def hide_customer_suggestion(self):
        """统一隐藏客人建议框，并清空“当前高亮索引”"""
        self.customer_suggestion_frame.place_forget()
        self.customer_suggestion_listbox_visible = False
        self.customer_suggestion_index = -1

    def on_customer_listbox_select(self, event):
        """同步当前高亮索引，不立刻确认
            真正确认由点击事件或 apply_customer_selection() 完成"""
        selection = self.customer_suggestion_listbox.curselection()
        if selection:
            self.customer_suggestion_index = selection[0]

    def on_customer_listbox_click(self, event):
        """鼠标点击时直接确认当前项"""
        idx = self.customer_suggestion_listbox.nearest(event.y)
        if idx < 0:
            return "break"

        self.customer_suggestion_listbox.selection_clear(0, tk.END)
        self.customer_suggestion_listbox.selection_set(idx)
        self.customer_suggestion_listbox.activate(idx)
        self.customer_suggestion_index = idx

        self.apply_customer_selection()
        return "break"

    def on_customer_down_key(self, event):
        """当在客人输入框中按下 Down 键时，移动建议高亮，不切焦点"""
        if self.customer_suggestion_listbox_visible:
            self.move_customer_selection(1)
            return "break"

    def on_customer_up_key(self, event):
        """在输入框中按下 Up 键，移动建议高亮，不切焦点"""
        if self.customer_suggestion_listbox_visible:
            self.move_customer_selection(-1)
            return "break"

    def on_customer_enter(self, event):
        """客人 Enter：收起建议框"""
        if self.customer_suggestion_listbox_visible:
            self.hide_customer_suggestion()
            return "break"

    def on_customer_focus_out(self, event):
        """延迟检查焦点，避免方向键/鼠标切换时误隐藏
            失焦时不立刻隐藏建议框，而是 after 一下再检查"""
        self.root.after(1, self._check_customer_focus)

    def on_listbox_focus_out(self, event):
        """Listbox 失焦也走同样的延迟检查逻辑"""
        self.root.after(1, self._check_customer_focus)

    def _check_customer_focus(self):
        """统一检查焦点是否仍在客人输入/建议框相关控件上
            只有完全离开输入框 / listbox / 滚动条时，才真正隐藏建议框。"""
        widget = self.root.focus_get()
        if widget in (self.customer_entry, self.customer_suggestion_listbox, self.customer_scrollbar):
            return
        self.hide_customer_suggestion()

    def move_customer_selection(self, delta):
        """在客人建议列表中移动高亮
            直接把高亮项写回输入框"""
        if not self.customer_suggestion_listbox_visible:
            return

        count = self.customer_suggestion_listbox.size()
        if count <= 0:
            return

        if self.customer_suggestion_index < 0:
            self.customer_suggestion_index = 0 if delta > 0 else count - 1
        else:
            self.customer_suggestion_index = (self.customer_suggestion_index + delta) % count

        self.customer_suggestion_listbox.selection_clear(0, tk.END)
        self.customer_suggestion_listbox.selection_set(self.customer_suggestion_index)
        self.customer_suggestion_listbox.activate(self.customer_suggestion_index)
        self.customer_suggestion_listbox.see(self.customer_suggestion_index)

        # 修改当前客人
        value = self.customer_suggestion_listbox.get(self.customer_suggestion_index)
        self._apply_customer_value(value)

    def apply_customer_selection(self):
        """确认当前高亮的客人建议
            把焦点放回输入框，并收起建议框"""
        if not self.customer_suggestion_listbox_visible:
            return

        selection = self.customer_suggestion_listbox.curselection()
        if not selection:
            return

        value = self.customer_suggestion_listbox.get(selection[0])
        self._apply_customer_value(value, keep_focus=True, hide_suggestion=True)

    # ---------- 店铺、保存等 ----------
    def extract_store_id_from_customer(self, customer_name):
        """从客人名称中提取店号。
        假设输入格式为“店号 客人”，例如 “123 Alice”。
        返回店号对应的 id（整数），不存在则返回 None。
        """
        tokens = customer_name.strip().split()
        if tokens and tokens[0].isdigit():
            return self.app.stores_by_number.get(tokens[0])
        return None

    def get_store_name_by_id(self, store_id):
        """通过店铺 id 反查店铺名"""
        return self.app.stores_by_id.get(store_id, "")

    def update_store_based_on_customer(self, customer_name):
        """当客人名里带有店号时，自动同步当前店铺
            同步后要立即刷新所有商品价格，因为不同店铺价格可能不同
            如果客人名称中包含的店号不存在，则使用默认店号（当前选择的店铺）"""
        store_id = self.extract_store_id_from_customer(customer_name)
        if store_id and store_id in self.app.stores_by_id:
            self.store_combo.set(self.app.stores_by_id[store_id])
            self.store_id = store_id
            self.update_all_prices()
            self.mark_draft_dirty()

    def on_store_selected(self):
        """手动切换店铺
        1. 同步 store_id
        2. 刷新所有已有商品的单价
        3. 标记草稿已变更"""
        self._sync_store_from_combo()
        self.update_all_prices()
        self.mark_draft_dirty()

    def update_all_prices(self):
        """根据当前店号更新所有产品行的单价和总价
        1. 逐行更新价格和行总价
        2. 最后统一 calculate_total_price() 一次
        """
        for product_row in self.entries:
            model = self._get_var_text(product_row.model_var)
            price = self.app.get_product_price(model, self.store_id)
            product_row.price_var.set("" if price is None else f"{price:.2f}")
            self.update_total_price(product_row, recalculate_order_total=False)

        # 所有行处理完后，再统一整单重算一次
        self.calculate_total_price()

    def _collect_product_data(self):
        """收集当前表单里的产品数据，并做基础数值校验

        保存前先把所有商品行收集成纯数据。
        这样 save_data() 就不用同时负责“取值 + 校验 + 入库”，职责更清晰。
        目的：把“收集数据”和“保存到数据库”拆开，减少 save_data() 的负担。
        """
        product_data = []
        for product_row in self.entries:
            quantity_text = self._get_var_text(product_row.quantity_var)
            model = self._get_var_text(product_row.model_var)
            price_text = self._get_var_text(product_row.price_var)
            total_text = self._get_var_text(product_row.total_var)

            if not model:
                continue

            try:
                quantity = float(quantity_text) if quantity_text else 0.0
                price = float(price_text) if price_text else 0.0
                total = float(total_text) if total_text else quantity * price
            except ValueError:
                raise ValueError(f"数值格式错误: 数量或单价格式不正确 (数量={quantity_text} 单价={price_text})")

            product_data.append((quantity, model, price, total))

        return product_data

    def clear_form(self):
        """清空当前订单页表单
        1. 进入 _restoring_state，避免触发联动保存
        2. 保存成功后 清空客人、发货时间输入框，隐藏客人建议
        """
        self._restoring_state = True
        try:
            self._set_entry_text(self.customer_entry, "")
            self._set_entry_text(self.ship_time_entry, "")
            self.hide_customer_suggestion()
            self.app.update_tab_title(self, "")
            self.set_current_datetime()

            for product_row in self.entries:
                self._clear_product_row(product_row)

            self.calculate_total_price()
        finally:
            self._restoring_state = False

    def save_data(self):
        """把当前 tab 的数据保存到 saved_data.db
            保存流程被整理成：校验 -> 收集产品 -> 写主表 -> 批量写明细 -> 清空表单。"""
        if not self.app.conn_saved:
            messagebox.showerror("数据库错误", "保存数据库未连接")
            return

        store_name = self.store_combo.get()
        customer = self.customer_entry.get()
        date = self.date_entry.get()

        if not store_name:
            messagebox.showwarning("输入错误", "请选择店号")
            return
        if not self.store_id:
            messagebox.showwarning("输入错误", "当前店号无效")
            return

        try:
            product_data = self._collect_product_data()
        except ValueError as exc:
            messagebox.showwarning("输入错误", str(exc))
            return

        if not product_data:
            messagebox.showwarning("输入错误", "没有产品数据可保存")
            return

        try:
            cursor = self.app.cursor_saved
            cursor.execute(
                "INSERT INTO entries (store_id, customer, date) VALUES (?, ?, ?)",
                (self.store_id, customer, date),
            )
            entry_id = cursor.lastrowid

            # 先准备整批数据，再 executemany() 批量写入。
            rows_to_insert = [(entry_id, quantity, model, price, total) for quantity, model, price, total in product_data]
            cursor.executemany(
                "INSERT INTO products (entry_id, quantity, model, price, total_price) VALUES (?, ?, ?, ?, ?)",
                rows_to_insert,
            )
            self.app.conn_saved.commit()

            self.clear_form()
            self.app.save_drafts_now()

        except Exception as exc:
            self.app.conn_saved.rollback()
            messagebox.showerror("数据库错误", f"保存失败: {exc}")

    def close_this_tab(self):
        """关闭自身所在的标签页"""
        self.app._close_tab(self)

    # ---------- Canvas helper(表格区功能) ----------
    def on_frame_configure(self, event):
        """调整 Canvas 滚动区域
            table_frame 尺寸变化时，同步更新 canvas 的可滚动区域"""
        bbox = self.canvas.bbox("all")
        if not bbox:
            return
        _, _, x2, y2 = bbox
        content_height = y2
        view_height = self.canvas.winfo_height()
        scroll_height = max(content_height, view_height)
        self.canvas.configure(scrollregion=(0, 0, x2, scroll_height))

    def on_canvas_configure(self, event):
        """让 table_frame 宽度始终跟着 Canvas 可视宽度走
            event.width 就是 Canvas 当前可视宽度"""
        self.canvas.itemconfigure(self.table_window, width=event.width)

    def _on_mousewheel(self, event):
        """绑定鼠标滚轮事件
            鼠标滚轮滚动表格区域"""
        if event.num == 5 or event.delta == -120:
            self.canvas.yview_scroll(1, "units")
        elif event.num == 4 or event.delta == 120:
            self.canvas.yview_scroll(-1, "units")

    # ---------- 日期 ----------
    def update_date_entry(self):
        """更新日期为当前圣保罗时间"""
        self.set_current_datetime()


    def cleanup(self):
        """关闭 tab 前的收尾工作：
        - 取消 after 定时器
        - 关闭所有型号建议框
        - 关闭客人建议框"""
        # 取消定时器
        if self._date_after_id:
            try:
                self.root.after_cancel(self._date_after_id)
            except Exception:
                pass
            self._date_after_id = None
        # 隐藏并销毁任何存在的 product suggestion listboxes
        for product_row in self.entries:
            try:
                self.hide_suggestion_listbox(product_row)
            except Exception:
                continue
        # 隐藏客户 suggestion框
        try:
            self.hide_customer_suggestion()
        except Exception:
            pass


class ProductEntryApp:
    """
    应用总控：
    负责窗口、路径、数据库、tab 管理、草稿管理。

    简单理解：
    - OrderTab 管“单个订单页”
    - ProductEntryApp 管“整个程序壳层 + 多个订单页”
    """

    # ProductEntryApp 是整个程序的总控。
    # 这里的初始化顺序也被整理过：先准备状态，再建窗口，再连数据库，再恢复草稿。
    def __init__(self, root):
        self.root = root

        # ===== tab 管理相关 =====
        self.order_tabs = []             # 所有 OrderTab
        self.tab_button_widgets = {}     # tab -> (button_frame, label_btn, close_btn)

        # ===== 店铺映射缓存 =====
        self.stores_by_id = {}           # store_id -> 店铺名
        self.stores_by_number = {}       # "店号数字字符串" -> store_id
        self.store_name_to_id = {}       # 店铺名 -> store_id（新增，用于 O(1) 反查）

        # ===== 草稿保存相关 =====
        self._draft_save_after_id = None # 草稿自动保存的 after 定时器 ID
        self._restoring_drafts = False   # 是否正在恢复草稿（全局标志，恢复草稿时 app 和 tab 都会用到）

        # ===== 路径相关 =====
        # 优化点：
        # 这里把“基础目录怎么找”和“资源文件怎么拼路径”统一收口，
        # 图片 / 数据库 / 草稿都走同一套入口。
        self.base_dir = self._resolve_base_dir()   
        self.DRAFT_FILE = self.resource_path("order_drafts.json")  
        self.main_db_path = self.resource_path("store_products.db")
        self.saved_db_path = self.resource_path("saved_data.db")

        # ===== 数据库连接占位 =====
        self.conn_main = None      # 主数据库连接（store_products.db）；存店铺和商品价格资料
        self.cursor_main = None    # 主数据库游标；查店铺、查型号建议、查价格都靠它
        self.conn_saved = None     # 保存数据库连接（saved_data.db）；存历史订单记录
        self.cursor_saved = None   # 保存数据库游标；查历史客户、写正式订单都靠它

        # ===== 启动流程 =====
        self._setup_window()
        self._build_title_bar()
        self._build_content_area()
        self.setup_databases()
        self.load_stores()

        # 启动时优先恢复草稿；没有草稿再创建空白订单页
        if not self.restore_drafts():
            self.create_new_order()

        # ===== 快捷键 =====
        self.root.bind("<Control-s>", lambda e: self.save_current_order())
        self.root.bind("<Control-w>", lambda e: self.close_current_tab())

    # ---------- 路径 ----------
    def _resolve_base_dir(self):
        """解析程序的基础目录

        - 直接运行 .py：返回脚本所在目录
        - 打包成 .exe：返回 exe 所在目录

        这样草稿、数据库、图片资源在打包后也能落到预期位置。
        """
        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))

    def resource_path(self, filename):
        """根据基础目录拼出资源文件完整路径"""
        return os.path.join(self.base_dir, filename)

    # ---------- UI ----------
    def _setup_window(self):
        """主窗口基础设置"""
        self.root.title("订单系统")
        self.root.geometry("480x720")
        self.root.overrideredirect(True)        # 去掉系统原生标题栏，后面自己画一个自定义标题栏
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing) # 点击关闭窗口时，执行自己的关闭逻辑
        self.root.attributes("-topmost", False) # 默认不置顶

    def _build_title_bar(self):
        """构建自定义标题栏：tab 按钮区 + 窗口控制按钮"""
        # TitleBar（放自定义 tab 按钮 + 窗口控制）
        self.title_bar = tk.Frame(self.root, bg="#f0f0f0", height=36)
        self.title_bar.pack(side="top", fill="x")

        # 左侧：自定义 tab 按钮容器（会放多个 tab button）
        self.tab_buttons_frame = tk.Frame(self.title_bar, bg="#ffffff")
        self.tab_buttons_frame.pack(side="left", fill="x", expand=True)
        # 允许拖动窗口：绑定鼠标事件到整个 tab 按钮区，用户点击并拖动这个区域时都能移动窗口
        self.tab_buttons_frame.bind("<Button-1>", self.start_move)
        self.tab_buttons_frame.bind("<B1-Motion>", self.do_move)

        # 右侧：窗口控制按钮（最小化、关闭）
        window_buttons = tk.Frame(self.title_bar, bg="#f0f0f0")
        window_buttons.pack(side="right")

        min_btn = tk.Button(window_buttons, text="—", width=3, command=self.minimize_window)
        close_btn = tk.Button(window_buttons, text="x", width=3, command=self.on_closing)

        close_btn.pack(side="right", padx=2, pady=4)
        min_btn.pack(side="right", padx=2, pady=4)

        # 在标题栏放一个 + 按钮用于新建 tab
        self.plus_button = tk.Button(self.tab_buttons_frame, text="+", command=self.create_new_order)
        self.plus_button.pack(side="left", padx=(6, 2), pady=4)

    def _build_content_area(self):
        """主内容区：所有订单页都显示在这里
            自定义 tab 切换时，本质上就是在这里 pack / forget 各个订单页 frame"""
        self.content_frame = tk.Frame(self.root)
        self.content_frame.pack(side="top", fill="both", expand=True)

    # ---------- 窗口控制 ----------
    def start_move(self, event):
        """记录鼠标与窗口左上角之间的偏移量
            记录窗口拖动起点坐标，后续移动时用这个偏移量计算新窗口位置。"""
        self.offset_x = event.x_root - self.root.winfo_x()
        self.offset_y = event.y_root - self.root.winfo_y()

    def do_move(self, event):
        """根据鼠标拖动实时移动窗口"""
        x = event.x_root - self.offset_x
        y = event.y_root - self.offset_y
        self.root.geometry(f"+{x}+{y}")

    def minimize_window(self):
        """最小化按钮
        最小化时暂时取消 overrideredirect，最小化后再恢复"""
        self.root.overrideredirect(False)
        self.root.iconify()
        self.root.after(10, lambda: self.root.overrideredirect(True))

    def maximize_window(self):
        """最大化窗口（当前代码未主动绑定按钮）"""
        width = self.root.winfo_screenwidth()
        height = self.root.winfo_screenheight()
        self.root.geometry(f"{width}x{height}+0+0")

    # ---------- DB (数据库) ----------
    def _connect_db(self, path):
        """创建 SQLite 连接，并打开外键约束
        """
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def setup_databases(self):
        """设置数据库连接和表结构
            初始化两个数据库：
            1. store_products.db：基础资料（店铺 / 型号 / 单价）
            2. saved_data.db：历史订单流水"""
        # 主要数据库: store_products.db 基础资料（店铺 / 型号 / 单价）
        try:
            self.conn_main = self._connect_db(self.main_db_path)
            self.cursor_main = self.conn_main.cursor()
            self.cursor_main.execute(
                """
                CREATE TABLE IF NOT EXISTS stores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE
                )
                """
            )
            self.cursor_main.execute(
                """
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model TEXT NOT NULL,
                    abbreviations TEXT,
                    price REAL NOT NULL,
                    store_id INTEGER NOT NULL,
                    FOREIGN KEY(store_id) REFERENCES stores(id) ON DELETE CASCADE
                )
                """
            )
            self.conn_main.commit()
        except Exception as exc:
            messagebox.showerror("数据库错误", f"无法连接主要数据库: {exc}")
            self.conn_main = None
            self.cursor_main = None

        # 新数据库: saved_data.db 历史订单流水
        try:
            self.conn_saved = self._connect_db(self.saved_db_path)
            self.cursor_saved = self.conn_saved.cursor()
            self.cursor_saved.execute(
                """
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    store_id INTEGER NOT NULL,
                    customer TEXT,
                    date TEXT,
                    FOREIGN KEY(store_id) REFERENCES stores(id)
                )
                """
            )
            self.cursor_saved.execute(
                """
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id INTEGER NOT NULL,
                    quantity REAL,
                    model TEXT,
                    price REAL,
                    total_price REAL,
                    FOREIGN KEY(entry_id) REFERENCES entries(id) ON DELETE CASCADE
                )
                """
            )
            self.conn_saved.commit()
        except Exception as exc:
            messagebox.showerror("数据库错误", f"无法连接保存数据库: {exc}")
            self.conn_saved = None
            self.cursor_saved = None

    def get_model_suggestions(self, store_id, text):
        """查询某个店铺下的型号建议列表
        """
        if not self.cursor_main or not store_id or not text:
            return []

        query = f"%{text}%"
        try:
            self.cursor_main.execute(
                """
                SELECT model FROM products
                WHERE store_id = ? AND (
                    model LIKE ? COLLATE NOCASE
                    OR abbreviations LIKE ? COLLATE NOCASE
                )
                LIMIT 50
                """,
                (store_id, query, query),
            )
            return [row[0] for row in self.cursor_main.fetchall()]
        except Exception:
            return []

    def get_product_price(self, model, store_id):
        """查询某个店铺下某个型号的价格
            根据型号 + 店铺 id 查询价格"""
        if not self.cursor_main or not model or not store_id:
            return None

        try:
            self.cursor_main.execute(
                "SELECT price FROM products WHERE model = ? AND store_id = ?",
                (model, store_id),
            )
            row = self.cursor_main.fetchone()
            return row[0] if row else None
        except Exception:
            return None

    def get_customer_suggestions(self, text):
        """从历史订单中查询客人建议列表
            从历史 entries 表中拿客人建议，供客人自动补全使用"""
        if not self.cursor_saved or not text:
            return []

        query = f"%{text}%"
        try:
            self.cursor_saved.execute(
                """
                SELECT DISTINCT customer
                FROM entries
                WHERE customer LIKE ? COLLATE NOCASE
                ORDER BY customer ASC
                LIMIT 10
                """,
                (query,),
            )
            return [row[0] for row in self.cursor_saved.fetchall()]
        except Exception:
            return []

    def load_stores(self):
        """加载 stores，并把选项填入已存在 tab 的 store_combo
            读取店铺表，并建立多种映射缓存。
             - id -> 名称
             - 数字店号 -> id
             - 店铺名 -> id"""
        if not self.cursor_main:
            return

        try:
            self.cursor_main.execute("SELECT id, name FROM stores")
            rows = self.cursor_main.fetchall()
            self.stores_by_id = {store_id: name for store_id, name in rows}
            self.stores_by_number = {str(store_id): store_id for store_id, _ in rows}
            self.store_name_to_id = {name: store_id for store_id, name in rows}  # 新增：店铺名 -> id

            for tab in self.order_tabs:
                self.init_tab_store(tab)
        except Exception as exc:
            messagebox.showerror("数据库错误", f"加载店铺失败: {exc}")

    def init_tab_store(self, tab):
        """初始化某个 tab 的店铺下拉框
            如果 tab 本来就有合法 store_id，优先保留原状态"""
        if not self.stores_by_id:
            return

        store_names = list(self.stores_by_id.values())
        tab.store_combo["values"] = store_names

        # 如果当前 tab 已经有合法 store_id，优先恢复它；
        # 只有没有值时，才退回默认第一家店。
        if tab.store_id in self.stores_by_id:
            tab.store_combo.set(self.stores_by_id[tab.store_id])
            return

        first_store_id, first_store_name = next(iter(self.stores_by_id.items()))
        tab.store_combo.set(first_store_name)
        tab.store_id = first_store_id

    # ---------- Tab 管理 ----------
    def create_new_order(self, title=DEFAULT_TAB_TITLE):
        """
        新建一个订单页，并为它创建标题栏按钮。
        1. 创建 OrderTab 实例，构建 UI
        2. 把它添加到 self.order_tabs 管理起来
        3. 创建标题栏按钮，并把它们的引用保存在 self.tab_button_widgets 里
         这样后续切换/关闭 tab 时能找到对应的按钮进行状态更新
        4. 切换到新建的 tab
        注意：新建 tab 时默认切换到它，用户可以直接开始输入。
        这里的 title 参数允许指定初始标题，默认为 DEFAULT_TAB_TITLE。
        """
        tab = OrderTab(self, title=title)
        # 每个订单页的 UI 都挂在 content_frame 里
        tab.frame = ttk.Frame(self.content_frame)
        tab.frame.order_tab = tab
        # 由 OrderTab 自己负责在自己的 frame 里搭建 UI，tab 只负责提供一个容器和调用接口
        tab.setup_ui(parent=tab.frame)

        # 把新 tab 添加到管理列表里，并初始化它的店铺选项
        self.order_tabs.append(tab)
        self.init_tab_store(tab)

        # 新建时先不把 tab.frame pack 出来，等 select_tab() 统一处理显示和隐藏
        tab.frame.pack_forget()

        #在 title_bar 创建 tab 按钮（label + 小 ×）
        btn_frame, label_btn, close_btn = self._make_tab_button(tab, title)
        self.tab_button_widgets[tab] = (btn_frame, label_btn, close_btn)

        # 切换到新建的 tab
        self.select_tab(tab)
        return tab

    def _make_tab_button(self, tab, title):
        """为某个订单页创建顶部按钮组：标题按钮 + 关闭按钮
            在 tab_buttons_frame 中创建一个 tab 按钮组：标题 + 关闭按钮"""
        btn_frame = tk.Frame(self.tab_buttons_frame, bg="#f0f0f0")
        btn_frame.pack(side="left", padx=(4, 0), pady=4)

        label_btn = tk.Button(btn_frame, text=title, relief="flat", padx=6, command=lambda t=tab: self.select_tab(t))
        label_btn.pack(side="left")

        close_btn = tk.Button(btn_frame, text="×", width=2, relief="flat", command=lambda t=tab: self._close_tab(t))
        close_btn.pack(side="left", padx=(2, 0))

        return btn_frame, label_btn, close_btn

    def select_tab(self, tab):
        """切换当前显示的订单页。
            把别的 frame 隐藏、当前 frame 显示。"""
        for order_tab in self.order_tabs:
            try:
                order_tab.frame.pack_forget()
            except Exception:
                continue
        # 只 pack 当前 tab 的 frame，其他 tab 的 frame 都先 forget 掉
        tab.frame.pack(fill="both", expand=True)
        # 更新标题栏按钮状态：当前 tab 的按钮高亮，其他按钮恢复默认
        for order_tab, widgets in self.tab_button_widgets.items():
            _, label_btn, _ = widgets
            label_btn.config(bg="#dcdcdc" if order_tab is tab else "#f0f0f0")

    def _close_tab(self, tab):
        """关闭指定 tab（由标题栏 × 调用）
            顺序上要先 cleanup，再销毁 UI，再从管理结构里移除"""
        if tab not in self.order_tabs:
            return

        # 关闭前先 cleanup，取消定时器、销毁建议框等
        try:
            tab.cleanup()
        except Exception:
            pass

        # 销毁 tab 的 UI 组件，先销毁 frame（订单页主体），再销毁标题栏按钮
        try:
            tab.frame.destroy()
        except Exception:
            pass
        # 从标题栏按钮管理里移除对应的按钮组件引用，并销毁按钮组件
        widgets = self.tab_button_widgets.pop(tab, None)
        if widgets:
            widgets[0].destroy()
        # 最后从订单页管理列表里移除这个 tab 实例
        self.order_tabs.remove(tab)

        # 关闭后如果还有其他 tab，切换到最后一个；没有 tab 了就新建一个空白订单页
        if self.order_tabs:
            self.select_tab(self.order_tabs[-1])
        else:
            self.create_new_order()

        self.save_drafts_now()

    def close_current_tab(self):
        """关闭当前显示的 tab"""
        current = self.get_current_tab()
        if current:
            self._close_tab(current)

    def get_current_tab(self):
        """返回当前正在显示的订单页"""
        for tab in self.order_tabs:
            if tab.frame.winfo_ismapped():
                return tab
        return None

    def update_tab_title(self, tab, title):
        """更新顶部 tab 文本。
            过长内容会被截断，避免标题栏被撑爆"""
        if tab not in self.tab_button_widgets:
            return

        _, label_btn, _ = self.tab_button_widgets[tab]
        if not title:
            label_btn.config(text=DEFAULT_TAB_TITLE)
            return

        # 标题过长时只显示前几个字符，避免挤占标题栏空间
        label_btn.config(text=title.strip()[:TAB_TITLE_MAX_LEN])

    def save_current_order(self):
        """Ctrl+S 的落点：保存当前正在看的订单页"""
        tab = self.get_current_tab()
        if tab:
            tab.save_data()

    # ---------- 草稿 ----------
    def schedule_draft_save(self):
        """安排一次“延迟保存草稿”
        防抖思路：连续输入时，不要每敲一个字就写磁盘。
        """
        if self._restoring_drafts:
            return

        if self._draft_save_after_id:
            try:
                self.root.after_cancel(self._draft_save_after_id)
            except Exception:
                pass

        # 重新安排一次延迟保存
        self._draft_save_after_id = self.root.after(DRAFT_SAVE_DELAY_MS, self.save_drafts_now)

    def save_drafts_now(self):
        """立即把所有有内容的订单页保存到草稿文件
            滤掉完全空白的订单页"""
        if self._restoring_drafts:
            return

        if self._draft_save_after_id:
            try:
                self.root.after_cancel(self._draft_save_after_id)
            except Exception:
                pass
            self._draft_save_after_id = None

        meaningful_tabs = [tab for tab in self.order_tabs if tab.has_meaningful_data()]
        if not meaningful_tabs:
            if os.path.exists(self.DRAFT_FILE):
                try:
                    os.remove(self.DRAFT_FILE)
                except Exception:
                    pass
            return

        current_tab = self.get_current_tab()
        current_tab_index = meaningful_tabs.index(current_tab) if current_tab in meaningful_tabs else 0

        payload = {
            "version": 1,
            "saved_at": datetime.now(APP_TIMEZONE).isoformat(),
            "current_tab_index": current_tab_index,
            "tabs": [tab.get_draft_data() for tab in meaningful_tabs],
        }

        # 先写到临时文件，再 os.replace() 原子替换。
        # 这样即使中途异常，也不容易把正式草稿写成半截坏 JSON。
        tmp_path = f"{self.DRAFT_FILE}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.DRAFT_FILE)
        except Exception as exc:
            print(f"保存草稿失败: {exc}")
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

    def restore_drafts(self):
        """启动程序时，尝试从草稿文件恢复所有未完成订单
            恢复成功返回 True，没有草稿或恢复失败返回 False。
        """
        if not os.path.exists(self.DRAFT_FILE):
            return False

        try:
            with open(self.DRAFT_FILE, "r", encoding="utf-8") as file:
                payload = json.load(file)
        except Exception:
            return False

        tabs_data = payload.get("tabs") or []
        if not tabs_data:
            return False

        self._restoring_drafts = True
        try:
            for draft_data in tabs_data:
                tab = self.create_new_order(title=DEFAULT_TAB_TITLE)
                tab.apply_draft_data(draft_data)

            current_tab_index = payload.get("current_tab_index", 0)
            if self.order_tabs:
                current_tab_index = max(0, min(current_tab_index, len(self.order_tabs) - 1))
                self.select_tab(self.order_tabs[current_tab_index])

            return True
        finally:
            self._restoring_drafts = False

    # ---------- 关闭 ----------
    def on_closing(self):
        """关闭程序时的统一出口：先存草稿，再关数据库，再销毁窗口"""
        self.save_drafts_now()

        if self.conn_main:
            self.conn_main.close()
        if self.conn_saved:
            self.conn_saved.close()

        self.root.destroy()

    def run(self):
        """运行入口：启动 Tk 事件循环"""
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()

def main():
    """程序启动入口"""
    root = tk.Tk()
    app = ProductEntryApp(root)
    app.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
