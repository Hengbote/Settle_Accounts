import os, sys, sqlite3, json
import tkinter as tk
import ctypes
from tkinter import ttk, messagebox
from datetime import datetime
from dataclasses import dataclass, field
from PIL import Image, ImageTk
from zoneinfo import ZoneInfo
from functools import partial 
import re

@dataclass
class ProductRow:
    quantity_var: tk.StringVar
    model_var: tk.StringVar
    price_var: tk.StringVar
    total_var: tk.StringVar
    model_entry: ttk.Entry = None
    suggestion_listbox: tk.Listbox = None
    suggestions: list = field(default_factory=list)
    suggestion_index: int = -1
    quantity_entry: ttk.Entry = None

class OrderTab:
    """
    每个标签（订单）的封装：独立 UI、独立数据（entries、total_price_var、store_id）；
    使用 app 提供的数据库连接与 store 列表（共享）。
    """
    def __init__(self, app, notebook, title="新订单"):
        self.app = app                # 指向主程序（共享 DB、stores）
        self.root = app.root

        self.frame = None

        # 每个订单独立数据
        self.entries = []
        self.total_price_var = tk.StringVar(value="")
        self.store_id = None
        self._date_after_id = None

        # UI 元素占位（会在 setup_ui 中初始化）
        self.store_combo = None
        self.date_entry = None
        self.customer_entry = None
        self.customer_suggestion_frame = None
        self.customer_suggestion_listbox = None
        self.customer_scrollbar = None
        self.customer_suggestion_listbox_visible = False
        self.customer_suggestion_index = -1
        self._restoring_state = False

    # ---------- UI 构建 ----------
    def setup_ui(self, parent):
        """在 parent (notebook page 的 frame) 内建立订单页面"""
        # 主框架
        self.main_frame = ttk.Frame(parent)
        self.main_frame.pack(fill='both', expand=True, padx=5, pady=5)

        # 顶部：Logo + 文本 + 按钮区域
        top_frame = ttk.Frame(self.main_frame)
        top_frame.pack(fill='x', pady=5)

        header_frame = ttk.Frame(top_frame)
        header_frame.pack(side='left', fill='x', expand=True)

        # 尝试加载 logo（若失败使用文本占位）
        logo_path = os.path.join(self.app.BASE_DIR, 'HUANG_Logo.PNG')
        try:
            logo_image = Image.open(logo_path)
            logo_image = logo_image.resize((90, 90), Image.LANCZOS)
            self.logo_photo = ImageTk.PhotoImage(logo_image)
            logo_label = ttk.Label(header_frame, image=self.logo_photo)
        except Exception:
            self.logo_photo = None
            logo_label = ttk.Label(header_frame, text="[Logo]", font=("Arial", 16, "bold"))
        logo_label.pack(side='left', padx=(0,10))

        text_frame = ttk.Frame(header_frame)
        text_frame.pack(side='left', fill='x', expand=True)
        ttk.Label(text_frame, text="PELICULAS - CAPAS PARA", font=("Arial", 10, "bold")).pack(anchor='w')
        ttk.Label(text_frame, text="CELULAR E ACESSORIOS", font=("Arial", 10, "bold")).pack(anchor='w')
        ttk.Label(text_frame, text="📞: (11)95066-6669 Ting", font=("Arial", 9)).pack(anchor='w')
        ttk.Label(text_frame, text="📞: (11)99798-8888 Henney", font=("Arial", 9)).pack(anchor='w')

        # 按钮区域（垂直放置在右上角）
        button_frame = ttk.Frame(top_frame)
        button_frame.pack(side='right', anchor='n', padx=8)

        self.add_row_button = ttk.Button(button_frame, text="添加新产品行", command=self.add_row)
        self.add_row_button.pack(side='top', pady=2)
        self.save_button = ttk.Button(button_frame, text="保存数据", command=self.save_data)
        self.save_button.pack(side='top', pady=2)

        # 店号和日期
        store_date_frame = ttk.Frame(self.main_frame)
        store_date_frame.pack(fill='x', pady=5)

        store_frame = ttk.Frame(store_date_frame)
        store_frame.pack(side='left', fill='x', expand=True)

        ttk.Label(store_frame, text="店号：", font=("Segoe UI", 12, "bold")).pack(side='left')
        self.store_combo = ttk.Combobox(store_frame, state="readonly", width=18, font=("Segoe UI", 12, "bold"))
        self.store_combo.pack(side='left', fill='x', expand=True)
        # 当 stores 已由 app.load_stores 填充时，需要把值 set 到当前 tab 的 store_combo
        # 所以通过 app.register_tab_to_stores 来更新（在主程序 load_stores 调用）
        self.store_combo.bind("<<ComboboxSelected>>", lambda e: self.on_store_selected())

        date_frame = ttk.Frame(store_date_frame)
        date_frame.pack(side='right')
        ttk.Label(date_frame, text="理货日期：", font=("Segoe UI", 12, "bold")).pack(side='left')
        self.date_entry = ttk.Entry(date_frame, width=40, font=("Segoe UI", 12, "bold"))
        self.date_entry.pack(side='left')
        self.date_entry.bind('<KeyRelease>', lambda e: self.mark_draft_dirty())
        self.set_current_datetime()

        # 客人 + 发货时间在同一行
        customer_frame = ttk.Frame(self.main_frame)
        customer_frame.pack(fill='x', pady=0)

        ttk.Label(customer_frame, text="客人：", font=("Segoe UI", 12, "bold")).pack(side='left')
        self.customer_entry = ttk.Entry(customer_frame, width=20, font=("Segoe UI", 12, "bold"))
        self.customer_entry.pack(side='left', fill='x', expand=True)
        self.customer_entry.bind('<KeyRelease>', self.on_customer_keyrelease)
        self.customer_entry.bind('<Down>', self.on_customer_down_key)
        self.customer_entry.bind('<Up>', self.on_customer_up_key)
        self.customer_entry.bind('<Return>', self.on_customer_enter)
        self.customer_entry.bind('<FocusOut>', self.on_customer_focus_out)

        # 自动完成 Listbox（放在 root 层使用 place，避免被 canvas 遮挡）
        self.customer_suggestion_frame = tk.Frame(self.root, bd=1, relief="solid")
        self.customer_suggestion_listbox = tk.Listbox(self.customer_suggestion_frame, height=6, font=("Segoe UI", 11))
        self.customer_scrollbar = ttk.Scrollbar(self.customer_suggestion_frame, orient="vertical",
                                                command=self.customer_suggestion_listbox.yview)
        self.customer_suggestion_listbox.configure(yscrollcommand=self.customer_scrollbar.set)
        self.customer_suggestion_listbox.pack(side='left', fill='both', expand=True)
        self.customer_scrollbar.pack(side='right', fill='y')
        self.customer_suggestion_frame.place_forget()
        self.customer_suggestion_listbox_visible = False
        self.customer_suggestion_listbox.bind("<ButtonRelease-1>", self.on_customer_listbox_click)
        self.customer_suggestion_listbox.bind("<<ListboxSelect>>", self.on_customer_listbox_select)
        self.customer_suggestion_listbox.bind("<Return>", self.on_customer_enter)
        self.customer_suggestion_listbox.bind("<FocusOut>", self.on_listbox_focus_out)

        # 发货时间输入
        ship_frame = ttk.Frame(customer_frame)
        ship_frame.pack(side='left')
        ttk.Label(ship_frame, text="发货时间：", font=("Segoe UI", 12, "bold")).pack(side='left')
        self.ship_time_entry = ttk.Entry(ship_frame, width=20, font=("Segoe UI", 12))
        self.ship_time_entry.pack(side='left')
        self.ship_time_entry.bind('<KeyRelease>', lambda e: self.mark_draft_dirty())

        # 总价显示
        total_frame = ttk.Frame(self.main_frame)
        total_frame.pack(fill='x', pady=5)
        ttk.Label(total_frame, text="所有产品总价：", font=("Segoe UI", 16, "bold")).pack(side='left')
        ttk.Label(total_frame, textvariable=self.total_price_var, font=("Segoe UI", 16, "bold")).pack(side='left', padx=(10,0))

        # 表格区：Canvas + 内部 frame（table_frame）
        self.canvas = tk.Canvas(self.main_frame, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self.main_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)

        # 鼠标进入 canvas 时绑定滚轮
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._on_mousewheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

        self.table_frame = ttk.Frame(self.canvas)
        self.table_window = self.canvas.create_window((0,0), window=self.table_frame, anchor='nw')
        self.table_frame.bind("<Configure>", lambda e: self.on_frame_configure(e))
        self.canvas.bind("<Configure>", lambda e: self.on_canvas_configure(e))

        self.create_table_headers()

        # 默认添加若干行（可按需）
        for _ in range(16):
            self.add_row()

        # 让主程序知道这个 tab（用于主程序查找/保存）
        # notebook.add() 在主程序里完成；这里只是建立完 UI
        return

    # ---------- 表格与行控制 ----------
    def create_table_headers(self):
        """创建表格头"""
        headers = ["数量", "型号", "单价", "型号总价"]
        column_widths = [8, 18, 8, 12]
        for idx, header in enumerate(headers):
            ttk.Label(self.table_frame, text=header, font=("Segoe UI", 12, "bold"), width=column_widths[idx]).grid(
                row=0, column=idx, sticky='w', padx=2, pady=2)

    def add_row(self):
        """添加一行产品输入"""
        row_index = len(self.entries) + 1
        # 为每个 tab 的变量设定 master 为该 tab 的 frame，避免不同 tab 变量混用
        product_row = ProductRow(
            quantity_var = tk.StringVar(master=self.table_frame),
            model_var = tk.StringVar(master=self.table_frame),
            price_var = tk.StringVar(master=self.table_frame),
            total_var = tk.StringVar(master=self.table_frame, value="")
        )
        self.create_product_row_widgets(row_index, product_row)
        self.entries.append(product_row)

    def create_product_row_widgets(self, row_index, product_row):
        """创建单行产品输入控件"""
        vars_list = [product_row.quantity_var, product_row.model_var, product_row.price_var, product_row.total_var]
        column_widths = [8, 18, 8, 12]
        for idx, var in enumerate(vars_list):
            state = 'readonly' if idx == 3 else 'normal'
            entry = ttk.Entry(self.table_frame, textvariable=var, font=("Segoe UI", 12, "bold"),
                              width=column_widths[idx], state=state)
            entry.grid(row=row_index, column=idx, sticky='w', padx=2, pady=1)

            if idx == 0:
                product_row.quantity_entry = entry
            elif idx == 1:
                product_row.model_entry = entry

            # 绑定左右上下键移动
            for arrow_key in ['<Up>','<Down>','<Left>','<Right>']:
                entry.bind(arrow_key, lambda e, pr=product_row, col=idx: self.navigate_entry(e, pr, col))

        # 绑定变量监听
        product_row.quantity_var.trace_add('write', lambda *a, pr=product_row: self.on_quantity_or_price_change(pr))
        product_row.model_var.trace_add('write', lambda *a, pr=product_row: self.on_model_var_change(pr))
        product_row.price_var.trace_add('write', lambda *a, pr=product_row: self.on_quantity_or_price_change(pr))

        # 型号输入键事件
        product_row.model_entry.bind('<KeyRelease>', lambda e, pr=product_row: self.on_model_entry_keyrelease(e, pr))

    def navigate_entry(self, event, product_row, column):
        """处理方向键在各个输入框之间进行切换的操作"""
        # 如果有 suggestion list 可见，允许它处理上下键
        if product_row.suggestion_listbox and product_row.suggestion_listbox.winfo_viewable():
            return

        try:
            current_row = int(event.widget.grid_info()['row'])
            current_col = int(event.widget.grid_info()['column'])
        except Exception:
            return

        if event.keysym == 'Up':
            target_row = current_row - 1
            target_col = current_col
        elif event.keysym == 'Down':
            target_row = current_row + 1
            target_col = current_col
        elif event.keysym == 'Left':
            target_row = current_row
            target_col = current_col - 1
        elif event.keysym == 'Right':
            target_row = current_row
            target_col = current_col + 1
        else:
            return

        if target_row < 1 or target_col < 0 or target_col > 3:
            return "break"

        widgets = self.table_frame.grid_slaves(row=target_row, column=target_col)
        if widgets:
            widgets[0].focus_set()
            return "break"
        return "break"

    # ---------- 型号建议 & 价格查询 ----------
    def on_model_var_change(self, product_row):
        """当型号变量改变时更新建议列表或清空相关字段"""
        if self._restoring_state:
            return

        value = product_row.model_var.get()
        if value == '':
            self.hide_suggestion_listbox(product_row)
            product_row.price_var.set('')
            self.update_total_price(product_row)
        else:
            self.show_suggestions(product_row, value)

        self.mark_draft_dirty()

    def on_model_entry_keyrelease(self, event, product_row):
        """处理型号输入框的键盘事件"""
        if event.keysym in ("Up","Down","Return","Escape"):
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
        """从共享 DB 查询型号并在表格附近显示 listbox"""
        if not self.store_id:
            return
        query = f"%{text}%"
        try:
            cur = self.app.cursor_main
            cur.execute('''
                SELECT model FROM products
                WHERE store_id = ? AND (model LIKE ? COLLATE NOCASE OR abbreviations LIKE ? COLLATE NOCASE)
                LIMIT 50
            ''', (self.store_id, query, query))
            results = cur.fetchall()
            suggestions = [r[0] for r in results]
        except Exception as e:
            suggestions = []
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
            product_row.suggestion_listbox.config(height=min(len(suggestions),10))

        for s in suggestions:
            product_row.suggestion_listbox.insert(tk.END, s)

        # 放置在型号输入框正下方（相对于 table_frame）
        self.root.update_idletasks()
        entry = product_row.model_entry
        x = entry.winfo_rootx() - self.table_frame.winfo_rootx()
        y = entry.winfo_rooty() - self.table_frame.winfo_rooty() + entry.winfo_height()
        product_row.suggestion_listbox.place(x=x, y=y, width=entry.winfo_width())
        product_row.suggestion_index = -1

    def hide_suggestion_listbox(self, product_row):
        """隐藏建议列表框"""
        if product_row.suggestion_listbox:
            product_row.suggestion_listbox.place_forget()
            product_row.suggestion_listbox.destroy()
            product_row.suggestion_listbox = None
            product_row.suggestions = []
            product_row.suggestion_index = -1

    def move_in_suggestions(self, product_row, delta):
        """在建议列表中移动选择"""
        if not product_row.suggestions:
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
        """选择建议列表中的型号"""
        if product_row.suggestions and product_row.suggestion_index >= 0:
            selected = product_row.suggestions[product_row.suggestion_index]
            product_row.model_var.set(selected)
            self.hide_suggestion_listbox(product_row)
            self.fetch_price(product_row)

    def on_listbox_select(self, product_row, event):
        """处理Listbox选择事件（无需操作）"""
        pass

    def on_listbox_click(self, product_row, event):
        """处理Listbox点击事件"""
        idx = product_row.suggestion_listbox.nearest(event.y)
        selected = product_row.suggestion_listbox.get(idx)
        product_row.model_var.set(selected)
        self.hide_suggestion_listbox(product_row)
        self.fetch_price(product_row)

    def fetch_price(self, product_row):
        """根据型号获取价格并更新"""
        model = product_row.model_var.get().strip()
        if model and self.app.conn_main and self.store_id:
            try:
                cur = self.app.cursor_main
                cur.execute('SELECT price FROM products WHERE model = ? AND store_id = ?', (model, self.store_id))
                r = cur.fetchone()
                if r:
                    product_row.price_var.set(f"{r[0]:.2f}")
                else:
                    product_row.price_var.set('')
            except Exception:
                product_row.price_var.set('')
        else:
            product_row.price_var.set('')
        self.update_total_price(product_row)

    def update_total_price(self, product_row):
        """更新单行和总价"""
        model = product_row.model_var.get().strip()
        if not model:
            product_row.total_var.set("")
            self.calculate_total_price()
            return
        try:
            qty = float(product_row.quantity_var.get() or 0)
            price = float(product_row.price_var.get() or 0)
            total = qty * price
            product_row.total_var.set("" if total==0 else f"{total:.2f}")
        except ValueError:
            product_row.total_var.set("")
        self.calculate_total_price()

    def calculate_total_price(self):
        """计算所有产品的总价"""
        total = 0.0
        has = False
        for pr in self.entries:
            if pr.model_var.get().strip():
                has = True
                try:
                    total += float(pr.total_var.get() or 0)
                except ValueError:
                    pass
        self.total_price_var.set(f"{total:.2f}" if has else "")

    # ---------- 草稿相关方法 ----------

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
        注意：这里不直接保存，而是交给 app 统一做延迟保存"""
        if self._restoring_state or getattr(self.app, '_restoring_drafts', False):
            return
        self.app.schedule_draft_save()

    def get_current_datetime_text(self):
        """获取当前圣保罗时间，并格式化成字符串"""
        sao_paulo_tz = ZoneInfo("America/Sao_Paulo")
        return datetime.now(sao_paulo_tz).strftime("%d/%m/%Y %H:%M")

    def set_date_value(self, value):
        """设置“日期输入框”的值"""
        self.date_entry.delete(0, tk.END)
        self.date_entry.insert(0, value)

    def set_current_datetime(self):
        """把日期输入框设置为“当前时间”"""
        self.set_date_value(self.get_current_datetime_text())

    def has_meaningful_data(self):
        """ 判断当前这个订单页是否“真的有内容”
            只有有内容的 tab 才值得保存成草稿"""
        if self.customer_entry.get().strip():
            return True
        if self.ship_time_entry.get().strip():
            return True

        for pr in self.entries:
            if (pr.quantity_var.get().strip() or
                pr.model_var.get().strip() or
                pr.price_var.get().strip() or
                pr.total_var.get().strip()):
                return True

        return False
 
    def get_draft_data(self):
        """把当前订单页导出为“可保存的草稿数据”
            返回一个字典，之后会被写入 JSON 文件"""
        rows = []

        # 把每一行产品数据都收集起来
        for pr in self.entries:
            rows.append({
                'quantity': pr.quantity_var.get(),  # 数量
                'model': pr.model_var.get(),        # 型号
                'price': pr.price_var.get(),        # 单价
                'total': pr.total_var.get(),        # 该行总价
            })

        # 返回整个订单页的数据结构
        return {
            'store_id': self.store_id,                 # 当前店铺ID
            'store_name': self.store_combo.get(),      # 当前店铺名称（双保险）
            'date': self.date_entry.get(),             # 日期
            'customer': self.customer_entry.get(),     # 客人
            'ship_time': self.ship_time_entry.get(),   # 发货时间
            'rows': rows,                              # 所有产品行
        }

    def apply_draft_data(self, draft_data):
        """把一份草稿数据重新恢复到当前订单页界面"""
        self._restoring_state = True
        try:
            store_id = draft_data.get('store_id')
            store_name = draft_data.get('store_name', '')
            resolved_name = self.app.stores_by_id.get(store_id, store_name)

            if resolved_name:
                self.store_combo.set(resolved_name)
                for sid, name in self.app.stores_by_id.items():
                    if name == resolved_name:
                        self.store_id = sid
                        break
            else:
                self.store_id = None
                self.store_combo.set('')

            self.set_date_value(draft_data.get('date', self.get_current_datetime_text()))

            self.customer_entry.delete(0, tk.END)
            self.customer_entry.insert(0, draft_data.get('customer', ''))

            self.ship_time_entry.delete(0, tk.END)
            self.ship_time_entry.insert(0, draft_data.get('ship_time', ''))

            rows = draft_data.get('rows', [])
            target_count = max(16, len(rows))
            while len(self.entries) < target_count:
                self.add_row()

            for idx, pr in enumerate(self.entries):
                row = rows[idx] if idx < len(rows) else {}
                pr.quantity_var.set(row.get('quantity', ''))
                pr.model_var.set(row.get('model', ''))
                pr.price_var.set(row.get('price', ''))
                pr.total_var.set(row.get('total', ''))

            self.calculate_total_price()
            self.app.update_tab_title(self, draft_data.get('customer', ''))
        finally:
            self._restoring_state = False

    # ---------- 客人自动完成（在 root 层显示，防止被 canvas 遮挡） ----------
    def on_customer_keyrelease(self, event):
        """当在客人输入框中键盘释放时，更新建议列表"""

        if event.keysym in ("Up", "Down", "Return", "Escape"):
            return
        
        text = self.customer_entry.get()
        if text == '':
            self.hide_customer_suggestion()
            # 更新 tab 名称为空或默认
            self.app.update_tab_title(self, "新订单")
            self.mark_draft_dirty()
            return
        # 动态更新 tab 名称为输入值（即时）
        self.app.update_tab_title(self, text)
        self.update_customer_suggestions(text)
        self.mark_draft_dirty()

    def update_customer_suggestions(self, text):
        """ 根据输入的文本更新客人建议列表
            客人输入格式为 "店号 客人"，例如 "123 Alice"
            我们将匹配包含店号和客人名称的完整字符串        """
        if not self.app.conn_saved:
            return
        q = f"%{text}%"
        try:
            cur = self.app.cursor_saved
            cur.execute('SELECT DISTINCT customer FROM entries WHERE customer LIKE ? COLLATE NOCASE ORDER BY customer ASC LIMIT 10', (q,))
            rows = cur.fetchall()
            suggestions = [r[0] for r in rows]
        except Exception:
            suggestions = []
        if suggestions:
            self.show_customer_suggestion(suggestions)
        else:
            self.hide_customer_suggestion()

    def show_customer_suggestion(self, suggestions):
        """显示客人自动完成框"""
        self.customer_suggestion_listbox.delete(0, tk.END)
        for s in suggestions:
            self.customer_suggestion_listbox.insert(tk.END, s)

        x = self.customer_entry.winfo_rootx() - self.root.winfo_rootx()
        y = self.customer_entry.winfo_rooty() - self.root.winfo_rooty() + self.customer_entry.winfo_height()
        self.customer_suggestion_frame.place(x=x, y=y, width=self.customer_entry.winfo_width())
        self.customer_suggestion_frame.lift()

        self.customer_suggestion_index = -1
        self.customer_suggestion_listbox.selection_clear(0, tk.END)

        self.customer_suggestion_listbox_visible = True

    def hide_customer_suggestion(self):
        """隐藏客人自动完成"""
        self.customer_suggestion_frame.place_forget()
        self.customer_suggestion_listbox_visible = False
        self.customer_suggestion_index = -1

    def on_customer_listbox_select(self, event):
        """同步当前高亮索引，不直接确认"""
        sel = self.customer_suggestion_listbox.curselection()
        if sel:
            self.customer_suggestion_index = sel[0]

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
        """当在客人输入框中按下Down键时，移动建议高亮，不切焦点"""
        if self.customer_suggestion_listbox_visible:
            self.move_customer_selection(1)
            return "break"
        
    def on_customer_up_key(self, event):
        """在输入框中按下 Up，移动建议高亮，不切焦点"""
        if self.customer_suggestion_listbox_visible:
            self.move_customer_selection(-1)
            return "break"

    def on_customer_enter(self, event):
        """客人 Enter收起建议框"""
        if self.customer_suggestion_listbox_visible:
            self.hide_customer_suggestion()
            return "break"

    def on_customer_focus_out(self, event):
        """延迟检查焦点，避免方向键/鼠标切换时误隐藏"""
        self.root.after(1, self._check_customer_focus)

    def on_listbox_focus_out(self, event):
        """Listbox 失去焦点时延迟检查"""
        self.root.after(1, self._check_customer_focus)

    def _check_customer_focus(self):
        widget = self.root.focus_get()
        if widget in (self.customer_entry, self.customer_suggestion_listbox, self.customer_scrollbar):
            return
        self.hide_customer_suggestion()

    def move_customer_selection(self, delta):
        """在客人建议列表中移动高亮，并把当前客人实际改成高亮项"""
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

        # 关键：不是预览，而是实际修改当前客人
        val = self.customer_suggestion_listbox.get(self.customer_suggestion_index)
        self.customer_entry.delete(0, tk.END)
        self.customer_entry.insert(0, val)
        self.customer_entry.icursor(tk.END)

        # 同步 tab 名称和店铺
        self.app.update_tab_title(self, val)
        self.update_store_based_on_customer(val)
        self.mark_draft_dirty()


    def apply_customer_selection(self):
        """确认当前高亮的客人建议"""
        if not self.customer_suggestion_listbox_visible:
            return

        sel = self.customer_suggestion_listbox.curselection()
        if not sel:
            return

        val = self.customer_suggestion_listbox.get(sel[0])
        self.customer_entry.delete(0, tk.END)
        self.customer_entry.insert(0, val)
        self.customer_entry.focus_set()
        self.customer_entry.icursor(tk.END)

        self.app.update_tab_title(self, val)
        self.update_store_based_on_customer(val)
        self.mark_draft_dirty()
        self.hide_customer_suggestion()

    # ---------- 店铺、保存等 ----------
    def extract_store_id_from_customer(self, customer_name):
        """
        从客人名称中提取店号。
        假设输入格式为 "店号 客人"，例如 "123 Alice"
        返回店号的ID（整数），如果不存在则返回None。
        """
        tokens = customer_name.strip().split()
        if tokens and tokens[0].isdigit():
            return self.app.stores_by_number.get(tokens[0])
        return None

    def get_store_name_by_id(self, store_id):
        """根据店号ID获取店铺名称"""
        return self.app.stores_by_id.get(store_id, "")

    def update_store_based_on_customer(self, customer_name):
        """根据客人名称中包含的店号自动更新店号"""
        sid = self.extract_store_id_from_customer(customer_name)
        if sid and sid in self.app.stores_by_id:
            self.store_combo.set(self.app.stores_by_id[sid])
            self.store_id = sid
            self.update_all_prices()
            self.mark_draft_dirty()
        # 如果客人名称中包含的店号不存在，则使用默认店号（当前选择的店铺）

    def on_store_selected(self):
        """当选择店铺时，更新 store_id 并更新所有产品行的单价"""
        name = self.store_combo.get()
        for sid, n in self.app.stores_by_id.items():
            if n == name:
                self.store_id = sid
                break
        self.update_all_prices()
        self.mark_draft_dirty()

    def update_all_prices(self):
        """根据当前店号更新所有产品行的单价和总价"""
        for pr in self.entries:
            model = pr.model_var.get().strip()
            if model and self.store_id:
                try:
                    cur = self.app.cursor_main
                    cur.execute('SELECT price FROM products WHERE model = ? AND store_id = ?', (model, self.store_id))
                    r = cur.fetchone()
                    pr.price_var.set(f"{r[0]:.2f}" if r else '')
                except Exception:
                    pr.price_var.set('')
            else:
                pr.price_var.set('')
            self.update_total_price(pr)

    def save_data(self):
        """把当前 tab 的数据保存到 saved_data.db（使用 app 的 cursor_saved）"""
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

        # 收集产品
        product_data = []
        for pr in self.entries:
            q = pr.quantity_var.get().strip()
            m = pr.model_var.get().strip()
            p = pr.price_var.get().strip()
            t = pr.total_var.get().strip()
            # 只保存有型号的行（模型为空视为未使用）
            if not m:
                continue
            try:
                qty_f = float(q) if q else 0.0
                price_f = float(p) if p else 0.0
                total_f = float(t) if t else qty_f * price_f
                product_data.append((qty_f, m, price_f, total_f))
            except ValueError:
                messagebox.showwarning("输入错误", f"数值格式错误: 数量或单价格式不正确 (数量={q} 单价={p})")
                return

        if not product_data:
            messagebox.showwarning("输入错误", "没有产品数据可保存")
            return

        try:
            cur = self.app.cursor_saved
            cur.execute('INSERT INTO entries (store_id, customer, date) VALUES (?, ?, ?)', (self.store_id, customer, date))
            entry_id = cur.lastrowid
            for row in product_data:
                cur.execute('INSERT INTO products (entry_id, quantity, model, price, total_price) VALUES (?, ?, ?, ?, ?)',
                            (entry_id, row[0], row[1], row[2], row[3]))
            self.app.conn_saved.commit()
            # 清空当前表单
            self.customer_entry.delete(0, tk.END)
            self.ship_time_entry.delete(0, tk.END)
            self.hide_customer_suggestion()
            self.app.update_tab_title(self, "")
            self.set_current_datetime()
            for pr in self.entries:
                pr.quantity_var.set('')
                pr.model_var.set('')
                pr.price_var.set('')
                pr.total_var.set('')
            self.calculate_total_price()
            self.app.save_drafts_now()

        except Exception as e:
            self.app.conn_saved.rollback()
            messagebox.showerror("数据库错误", f"保存失败: {e}")

    def close_this_tab(self):
        # 关闭自身所在 tab
        self.app._close_tab(self)

    # ---------- Canvas helper(表格区功能) ----------
    def on_frame_configure(self, event):
        """调整Canvas滚动区域"""
        bbox = self.canvas.bbox("all")
        if not bbox:
            return
        x1, y1, x2, y2 = bbox
        content_height = y2 - y1
        view_height = self.canvas.winfo_height()
        scroll_height = max(content_height, view_height)
        self.canvas.configure(scrollregion=(0,0,x2,scroll_height))

    def on_canvas_configure(self, event):
        # event.width 就是 Canvas 当前可视宽度
        # 将 table_frame 对应的窗口项目宽度设置成相同值
        self.canvas.itemconfigure(self.table_window, width=event.width)

    def _on_mousewheel(self, event):
        """绑定鼠标滚轮事件"""
        if event.num == 5 or event.delta == -120:
            self.canvas.yview_scroll(1, "units")
        elif event.num == 4 or event.delta == 120:
            self.canvas.yview_scroll(-1, "units")

    # ------------------ 日期功能 ------------------

    def update_date_entry(self):
        """更新日期为圣保罗时间（并记录 after id，便于取消）"""
        self.set_current_datetime()

    def cleanup(self):
        """关闭 tab 前的清理：取消定时器、隐藏/销毁 suggestion listboxes"""
        # 取消定时器
        if getattr(self, '_date_after_id', None):
            try:
                self.root.after_cancel(self._date_after_id)
            except Exception:
                pass
            self._date_after_id = None
        # 隐藏并销毁任何存在的 product suggestion listboxes
        for pr in getattr(self, 'entries', []):
            try:
                if pr.suggestion_listbox:
                    pr.suggestion_listbox.place_forget()
                    pr.suggestion_listbox.destroy()
                    pr.suggestion_listbox = None
            except Exception:
                pass
        # 隐藏客户 suggestion
        try:
            self.hide_customer_suggestion()
        except Exception:
            pass


class ProductEntryApp:
    def __init__(self, root):
        self.root = root
        self.root.title("订单系统")
        self.root.geometry("480x720")
        self.root.overrideredirect(True)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.attributes("-topmost", False)

        # TitleBar（放自定义 tab 按钮 + 窗口控制）
        self.title_bar = tk.Frame(self.root, bg="#f0f0f0", height=36)
        self.title_bar.pack(side="top", fill="x")

        # 左侧：自定义 tab 按钮容器（会放多个 tab button）
        self.tab_buttons_frame = tk.Frame(self.title_bar, bg="#ffffff")
        self.tab_buttons_frame.pack(side="left", fill="x", expand=True)

        # 允许拖动窗口
        #self.title_bar.bind("<Button-1>", self.start_move)
        #self.title_bar.bind("<B1-Motion>", self.do_move)
        self.tab_buttons_frame.bind("<Button-1>", self.start_move)
        self.tab_buttons_frame.bind("<B1-Motion>", self.do_move)

        # 右侧：窗口控制按钮
        window_buttons = tk.Frame(self.title_bar, bg="#f0f0f0")
        window_buttons.pack(side="right")

        min_btn = tk.Button(window_buttons, text="—", width=3, command=self.minimize_window)
        close_btn = tk.Button(window_buttons, text="x", width=3, command=self.on_closing)

        close_btn.pack(side="right", padx=2, pady=4)
        min_btn.pack(side="right", padx=2, pady=4)

        # 标题栏下方：主内容区（页面将在这里切换显示）
        self.content_frame = tk.Frame(self.root)
        self.content_frame.pack(side="top", fill="both", expand=True)

        # 存放 OrderTab 和 其对应的 tab 按钮引用
        self.order_tabs = []        # 列表 of OrderTab
        self.tab_button_widgets = {}   # tab -> (button_frame, label_btn, close_btn)

        # 在标题栏放一个 + 按钮用于新建 tab（靠左）
        self.plus_button = tk.Button(self.tab_buttons_frame, text="+", command=lambda: self.create_new_order())
        self.plus_button.pack(side="left", padx=(6,2), pady=4)

        # base dir
        self.BASE_DIR = os.path.dirname(os.path.abspath(__file__))

        self._draft_save_after_id = None
        self._restoring_drafts = False
        self.DRAFT_FILE = os.path.join(self.BASE_DIR, 'order_drafts.json')

        # 存放 tab 引用
        self.order_tabs = []

        # 先初始化数据库（OrderTab 需要共享 cursor）
        self.setup_databases()

        # 把 DB 店铺信息载入各 tab（若创建 tab 在 load_stores 之后会在 create_new_order 内处理）
        self.load_stores()

        # 先尝试恢复草稿；没有草稿时再创建空白订单页
        if not self.restore_drafts():
            # 载入店铺列表并在后续 tab 中填充（load_stores 会更新每个 tab 的 store_combo）
            # 创建第一个订单 tab
            self.create_new_order()

        # 快捷键 保存 Ctrl+S 保存当前 tab
        self.root.bind('<Control-s>', lambda e: self.save_current_order())

        # Ctrl+W 关闭当前 tab
        self.root.bind('<Control-w>', lambda e: self.close_current_tab())

    # ---------- 窗口控制----------
    def start_move(self, event):
        self.offset_x = event.x_root - self.root.winfo_x()
        self.offset_y = event.y_root - self.root.winfo_y()

    def do_move(self, event):
        x = event.x_root - self.offset_x
        y = event.y_root - self.offset_y
        self.root.geometry(f"+{x}+{y}")

    def minimize_window(self):
        """最小化按钮"""
        self.root.overrideredirect(False)
        self.root.iconify()

        self.root.after(
            10,
            lambda: self.root.overrideredirect(True)
        )

    def maximize_window(self):

        w = self.root.winfo_screenwidth()
        h = self.root.winfo_screenheight()

        self.root.geometry(f"{w}x{h}+0+0")

    # ---------- DB (数据库)----------
    def setup_databases(self):
        """设置数据库连接和表结构"""
        # 主要数据库: store_products.db
        try:
            self.conn_main = sqlite3.connect(os.path.join(self.BASE_DIR, 'store_products.db'))
            self.cursor_main = self.conn_main.cursor()
            self.cursor_main.execute('''
                CREATE TABLE IF NOT EXISTS stores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE
                )
            ''')
            self.cursor_main.execute('''
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model TEXT NOT NULL,
                    abbreviations TEXT,
                    price REAL NOT NULL,
                    store_id INTEGER NOT NULL,
                    FOREIGN KEY(store_id) REFERENCES stores(id) ON DELETE CASCADE
                )
            ''')
            self.conn_main.commit()
        except Exception as e:
            messagebox.showerror("数据库错误", f"无法连接主要数据库: {e}")
            self.conn_main = None
            self.cursor_main = None

        # 新数据库: saved_data.db
        try:
            self.conn_saved = sqlite3.connect(os.path.join(self.BASE_DIR, 'saved_data.db'))
            self.cursor_saved = self.conn_saved.cursor()
            self.cursor_saved.execute('''
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    store_id INTEGER NOT NULL,
                    customer TEXT,
                    date TEXT,
                    FOREIGN KEY(store_id) REFERENCES stores(id)
                )
            ''')
            self.cursor_saved.execute('''
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id INTEGER NOT NULL,
                    quantity REAL,
                    model TEXT,
                    price REAL,
                    total_price REAL,
                    FOREIGN KEY(entry_id) REFERENCES entries(id) ON DELETE CASCADE
                )
            ''')
            self.conn_saved.commit()
        except Exception as e:
            messagebox.showerror("数据库错误", f"无法连接保存数据库: {e}")
            self.conn_saved = None
            self.cursor_saved = None

    def load_stores(self):
        """加载 stores 并把选项填入已存在 tab 的 store_combo"""
        if not self.cursor_main:
            return
        try:
            self.cursor_main.execute('SELECT id, name FROM stores')
            rows = self.cursor_main.fetchall()
            self.stores_by_id = {r[0]: r[1] for r in rows}
            self.stores_by_number = {str(r[0]): r[0] for r in rows}
            #store_names = list(self.stores_by_id.values())
            # 填充每个 tab 的 combobox
            for tab in self.order_tabs:
                """tab.store_combo['values'] = store_names
                if store_names and (tab.store_id is None):
                    tab.store_combo.current(0)
                    tab.store_id = list(self.stores_by_id.keys())[0]"""

                self.init_tab_store(tab)
        except Exception as e:
            messagebox.showerror("数据库错误", f"加载店铺失败: {e}")

    # ---------- 店铺数据 ----------
    def init_tab_store(self, tab):
        """初始化店铺"""
        if hasattr(self, "stores_by_id") and self.stores_by_id:
            store_names = list(self.stores_by_id.values())
            tab.store_combo['values'] = store_names
            tab.store_combo.current(0)
            tab.store_id = list(self.stores_by_id.keys())[0]

    # ---------- Tab 管理 ----------
    
    def create_new_order(self, title="新订单"):
        """
        新建 OrderTab，并在标题栏创建对应按钮。
        新页面的 frame 都是 parent=self.content_frame（而不是 notebook）。
        """
        tab = OrderTab(self, None, title=title)   # note: 我们不把 notebook 传入 OrderTab
        # 将 OrderTab 的 UI parent 改为 content_frame（确保 OrderTab.setup_ui 接受 parent）
        # 如果 OrderTab.setup_ui 现在使用 parent=self.frame（frame 是 notebook child），
        # 请在 OrderTab.__init__ 将 self.frame = ttk.Frame(parent) 改为:
        tab.frame = ttk.Frame(self.content_frame)
        tab.frame.order_tab = tab
        # 重新构建 UI 到正确 parent（简单做法是：在 OrderTab.__init__ 接受 parent）
        tab.setup_ui(parent=tab.frame)

        self.init_tab_store(tab)

        # keep reference
        self.order_tabs.append(tab)

        # 把这个 tab 的 frame pack 到 content_frame（但先隐藏）
        tab.frame.pack_forget()

        # 在 title_bar 创建 tab 按钮（label + 小 ×）
        btn_frame, label_btn, close_btn = self._make_tab_button(tab, title)
        self.tab_button_widgets[tab] = (btn_frame, label_btn, close_btn)

        # 选中并显示此 tab
        self.select_tab(tab)
        return tab

    def _make_tab_button(self, tab, title):
        """在 tab_buttons_frame 创建一个按钮组：label(点击激活) + 小 × (关闭)"""
        btn_frame = tk.Frame(self.tab_buttons_frame, bg="#f0f0f0")
        btn_frame.pack(side="left", padx=(4,0), pady=4)

        label_btn = tk.Button(btn_frame, text=title, relief="flat", padx=6,
                              command=lambda t=tab: self.select_tab(t))
        label_btn.pack(side="left")

        close_btn = tk.Button(btn_frame, text="×", width=2, relief="flat",
                              command=lambda t=tab: self._close_tab(t))
        close_btn.pack(side="left", padx=(2,0))

        return btn_frame, label_btn, close_btn

    def select_tab(self, tab):
        """显示 tab 的内容（将其它 tab 的 frame 隐藏）"""
        # hide all
        for t in self.order_tabs:
            try:
                t.frame.pack_forget()
            except Exception:
                pass
        # show requested
        tab.frame.pack(fill="both", expand=True)
        # visually mark selected label button (简单背景色)
        for t, widgets in self.tab_button_widgets.items():
            bf, lb, cb = widgets
            if t is tab:
                lb.config(bg="#dcdcdc")
            else:
                lb.config(bg="#f0f0f0")

    def _close_tab(self, tab):
        """关闭指定 tab（由标题栏 × 调用）"""
        if tab not in self.order_tabs:
            return
        
        # 先做 tab 自身清理（取消 after、销毁浮动 widget 等）
        try:
            if hasattr(tab, 'cleanup'):
                tab.cleanup()
        except Exception:
            pass

        # 卸载 UI
        try:
            tab.frame.destroy()
        except Exception:
            pass
        # 移除按钮
        widgets = self.tab_button_widgets.pop(tab, None)
        if widgets:
            widgets[0].destroy()
        # 从列表移除
        self.order_tabs.remove(tab)

        # 如果还有 tab，切到最后一个；如果一个都没了，补一个空白页
        if self.order_tabs:
            self.select_tab(self.order_tabs[-1])
        else:
            self.create_new_order()

        self.save_drafts_now()

    def close_current_tab(self):
        """关闭当前 tab（快捷键或右键菜单调用）"""
        current = self.get_current_tab()
        if current:
            self._close_tab(current)

    def get_current_tab(self):
        """返回当前显示的 tab（第一个 frame 在 content_frame 中的 tab）"""
        # 找到哪个 tab 的 frame 正在 mapped/show
        for tab in self.order_tabs:
            if tab.frame.winfo_ismapped():
                return tab
        return None
    
    def update_tab_title(self, tab, title):
        """设置tab名"""
        if tab not in self.tab_button_widgets:
            return

        _, label_btn, _ = self.tab_button_widgets[tab]

        if not title:
            label_btn.config(text="新订单")
            return

        short_title = title.strip()[:3]
        label_btn.config(text=short_title)

    def save_current_order(self):
        """保存快捷键"""
        tab = self.get_current_tab()
        if tab:
            tab.save_data()

    # ---------- 应用级草稿方法 ----------        

    def schedule_draft_save(self):
        """安排一次“延迟保存草稿”"""
        if self._restoring_drafts:
            return

        if self._draft_save_after_id:
            try:
                self.root.after_cancel(self._draft_save_after_id)
            except Exception:
                pass

        self._draft_save_after_id = self.root.after(1000, self.save_drafts_now)

    def save_drafts_now(self):
        """立即把所有有内容的订单页保存到草稿文件"""
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
        current_tab_index = 0
        if current_tab in meaningful_tabs:
            current_tab_index = meaningful_tabs.index(current_tab)

        payload = {
            "version": 1,
            "saved_at": datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat(),
            "current_tab_index": current_tab_index,
            "tabs": [tab.get_draft_data() for tab in meaningful_tabs]
        }

        try:
            with open(self.DRAFT_FILE, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存草稿失败: {e}")

    def restore_drafts(self):
        """启动程序时，尝试从草稿文件恢复所有未完成订单
            恢复成功返回 True，没有草稿或恢复失败返回 False"""
        if not os.path.exists(self.DRAFT_FILE):
            return False

        try:
            with open(self.DRAFT_FILE, 'r', encoding='utf-8') as f:
                payload = json.load(f)
        except Exception:
            return False

        tabs_data = payload.get("tabs") or []
        if not tabs_data:
            return False

        self._restoring_drafts = True
        try:
            for draft_data in tabs_data:
                tab = self.create_new_order(title="新订单")
                tab.apply_draft_data(draft_data)

            current_tab_index = payload.get("current_tab_index", 0)
            if self.order_tabs:
                current_tab_index = max(0, min(current_tab_index, len(self.order_tabs) - 1))
                self.select_tab(self.order_tabs[current_tab_index])

            return True
        finally:
            self._restoring_drafts = False

    # ---------- 关闭程序 ----------
    def on_closing(self):
        """关闭应用时先保存草稿，再关闭数据库连接"""
        self.save_drafts_now()

        if hasattr(self, 'conn_main') and self.conn_main:
            self.conn_main.close()
        if hasattr(self, 'conn_saved') and self.conn_saved:
            self.conn_saved.close()
        self.root.destroy()

    # 运行入口
    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()

def main():
    root = tk.Tk()
    app = ProductEntryApp(root)
    app.run()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
