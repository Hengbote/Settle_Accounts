# app/app.py

import config
import tkinter as tk
from tkinter import messagebox, ttk
from typing import List, Optional
from functools import partial

from database import DatabaseManager, Product
from dialogs import StoreCopyDialog
from ui import UIComponents


class ProductManagerApp:
    """
    产品管理应用主类，负责初始化和管理整个应用的UI和逻辑。
    """

    def __init__(self, root: tk.Tk):
        """
        初始化应用，包括界面和数据库管理器。

        :param root: Tkinter主窗口
        """
        self.root = root
        self.db_manager = DatabaseManager(db_path=config.DB_PATH)

        self.stores: dict[str, int] = {}  # 店号字典，格式为 {店名: 店ID, ...}
        self.selected_store_id: Optional[int] = None  # 当前选中的店号ID

        self.sort_column: Optional[str] = None  # 当前排序的列名
        self.sort_ascending: bool = True  # 排序方向，True表示升序

        self.editing_entry: Optional[tk.Entry] = None  # 当前正在编辑的表格输入框

        self.last_click_time: float = 0.0  # 上一次点击时间，用于检测双击排序
        self.last_clicked_column: Optional[str] = None  # 上一次点击的列

        self.is_store_column_displayed: bool = False  # 是否显示“店号”列

        # 初始化UI组件
        self.ui = UIComponents(self)
        self.setup_ui()

        # 绑定UI组件到主类属性，确保后续方法可访问
        self.tree                = self.ui.tree                # 树形控件，比如展示数据表格
        self.store_combobox      = self.ui.store_combobox      # 店铺下拉框
        self.store_name_entry    = self.ui.store_name_entry    # 店铺名称输入框
        self.status_label        = self.ui.status_label        # 状态栏（标签）
        self.model_entry         = self.ui.model_entry         # 型号输入框
        self.abbreviations_entry = self.ui.abbreviations_entry # 缩写输入框
        self.price_entry         = self.ui.price_entry         # 价格输入框
        self.search_entry        = self.ui.search_entry        # 搜索输入框
        self.all_columns         = self.ui.all_columns         # 全部列字段列表
        self.base_columns        = self.ui.base_columns        # 基础列字段列表
        self.store_column        = self.ui.store_column        # 店铺列字段
        self.column_widths       = self.ui.column_widths       # 每一列的宽度设置


        # 绑定关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.handle_application_close)

        # 绑定单击事件，用于双击排序
        self.tree.bind("<Button-1>", self.handle_treeview_click) 
        self.tree.bind("<Double-1>", self.handle_treeview_double_click)

        # 加载店号并确保默认店号存在
        self.load_stores()
        self.ensure_default_store()

    def setup_ui(self) -> None:
        """初始化用户界面，包括添加店号、选择店号、添加产品、搜索和产品列表。"""
        # 创建主框架
        main_frame = ttk.Frame(self.root, padding="5")
        main_frame.pack(fill='both', expand=True)

        # 使用UIComponents创建各个UI部分
        self.ui.create_store_management_section(main_frame)
        self.ui.create_add_product_section(main_frame)
        self.ui.create_search_section(main_frame)
        self.ui.create_product_list_section(main_frame)
        self.ui.create_status_label(main_frame)
        self.ui.create_import_products_section(main_frame)  # 新增导入区块

    def validate_price_input(self, new_value: str) -> bool:
        """
        验证单价输入，允许数字和小数点。

        :param new_value: 输入框的新值
        :return: 是否通过验证
        """
        if not new_value:
            return True
        if new_value == '.':
            return True
        try:
            float(new_value)
            return True
        except ValueError:
            return False

    def ensure_default_store(self) -> None:
        """
        确保存在一个默认店号，如果不存在则创建。
        """
        default_store_name = config.DEFAULT_STORE_NAME
        if default_store_name not in self.stores:
            store_id = self.db_manager.add_store(default_store_name)
            if store_id:
                self.load_stores()
                self.store_combobox.set(default_store_name)
                self.handle_store_selection()

    def load_stores(self) -> None:
        """
        加载店号列表，并更新店号下拉选择框。
        """
        stores = self.db_manager.get_stores()
        self.stores = {store.name: store.id for store in stores}  # 修正这里的映射
        self.store_combobox['values'] = list(self.stores.keys())

    def add_new_store(self) -> None:
        """
        添加店号到数据库，并根据用户选择复制源店的产品。
        """
        name = self.store_name_entry.get().strip()
        if not name:
            messagebox.showwarning("输入错误", "请填写店号。")
            return

        if name.lower() == config.DEFAULT_STORE_NAME.lower():
            messagebox.showwarning("输入错误", f"店号不能为 '{config.DEFAULT_STORE_NAME}'。")
            return

        store_id = self.db_manager.add_store(name)
        if store_id:
            # 更新店号列表
            self.load_stores()

            # 选择源店号进行复制
            if len(self.stores) > 1:
                copy_dialog = StoreCopyDialog(self.root, self.stores)
                self.root.wait_window(copy_dialog.top)
                source_store_id = copy_dialog.source_store_id

                if source_store_id and source_store_id != store_id:
                    self.db_manager.copy_products_between_stores(source_store_id, store_id)
            else:
                # 自动复制默认店的数据
                default_store_id = self.db_manager.get_default_store_id()
                if default_store_id and default_store_id != store_id:
                    self.db_manager.copy_products_between_stores(default_store_id, store_id)

            self.store_combobox.set(name)
            self.handle_store_selection()
            self.store_name_entry.delete(0, tk.END)
            self.status_label.config(text="店号添加成功。")

    def remove_store(self) -> None:
        """
        删除选定的店号及其关联的产品。
        """
        store_name = self.store_combobox.get()
        if not store_name:
            messagebox.showwarning("未选择店号", "请先选择要删除的店号。")
            return

        if store_name.lower() == config.DEFAULT_STORE_NAME.lower():
            messagebox.showwarning("操作错误", f"默认店不能被删除。")
            return

        if messagebox.askyesno("确认删除", f"确定要删除店号 '{store_name}' 及其所有产品吗？"):
            store_id = self.stores.get(store_name)
            if store_id:
                self.db_manager.delete_store(store_id)
                self.load_stores()
                self.store_combobox.set('')
                self.selected_store_id = None
                self.refresh_product_list()
                self.status_label.config(text="店号删除成功。")

    def handle_store_selection(self, event: Optional[tk.Event] = None) -> None:
        """
        当选择店号时，更新产品列表显示，并隐藏“店号”列。

        :param event: 事件对象
        """
        store_name = self.store_combobox.get()
        if store_name:
            self.selected_store_id = self.stores.get(store_name)
            self.refresh_product_list()
            self.status_label.config(text="")
        else:
            self.selected_store_id = None
            self.refresh_product_list()

    def add_product(self) -> None:
        """
        添加产品到数据库，并更新产品列表显示。
        """
        if not self.selected_store_id:
            messagebox.showwarning("未选择店号", "请先选择一个店号。")
            return

        model = self.model_entry.get().strip()
        abbreviations = self.abbreviations_entry.get().strip()
        price = self.price_entry.get().strip()

        if not model or not price:
            messagebox.showwarning("输入错误", "请至少填写型号和单价。")
            return

        try:
            price = float(price)
        except ValueError:
            messagebox.showerror("输入错误", "单价必须是数字。")
            return

        # 添加产品到数据库
        self.db_manager.add_product(model, abbreviations, price, self.selected_store_id)

        # 清空输入框
        self.model_entry.delete(0, tk.END)
        self.abbreviations_entry.delete(0, tk.END)
        self.price_entry.delete(0, tk.END)

        # 更新产品列表显示
        self.refresh_product_list()
        self.status_label.config(text="产品添加成功。")

    def delete_product(self) -> None:
        """
        删除选定的产品。
        """
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("未选择产品", "请先选择要删除的产品。")
            return

        product_id = selected_item[0]
        if messagebox.askyesno("确认删除", "确定要删除选定的产品吗？"):
            self.db_manager.delete_product(int(product_id))  # 转换为整数
            self.refresh_product_list()
            self.status_label.config(text="产品删除成功。")

    def refresh_product_list(self, products: Optional[List[Product]] = None) -> None:
        """
        更新产品列表显示。

        :param products: 可选，指定显示的产品列表
        """
        self.tree.delete(*self.tree.get_children())

        if self.selected_store_id:
            # 局部视图：显示选定店号下的产品，不显示“店号”列
            if products is None:
                products = self.db_manager.get_products(
                    store_id=self.selected_store_id,
                    order_by=self.sort_column,
                    ascending=self.sort_ascending
                )
            self.hide_store_column()
            items = [
                (product.model, product.abbreviations, f"{product.price:.2f}")
                for product in products
            ]
        else:
            # 全局视图：显示所有店号下的产品，显示“店号”列
            if products is None:
                products = self.db_manager.get_products(
                    store_id=None,
                    order_by=self.sort_column,
                    ascending=self.sort_ascending
                )
            self.display_store_column()
            items = [
                (product.model, product.abbreviations, f"{product.price:.2f}", product.store_name)
                for product in products
            ]

        # 使用批量插入提升性能
        for product, values in zip(products, items):
            self.tree.insert('', tk.END, values=values, iid=str(product.id))

    def sort_by_column(self, column_name: str) -> None:
        """
        根据列名排序产品列表，并切换排序方向。

        :param column_name: 要排序的列名
        """
        if self.sort_column == column_name:
            # 切换排序方向
            self.sort_ascending = not self.sort_ascending
        else:
            # 切换到新的排序列，默认升序
            self.sort_column = column_name
            self.sort_ascending = True
        self.refresh_product_list()

    def handle_treeview_click(self, event: tk.Event) -> None:
        """
        处理Treeview中点击事件，用于实现双击排序。

        :param event: 事件对象
        """
        # 不再处理排序，排序只在双击表头时处理
        pass

    def handle_treeview_double_click(self, event: tk.Event) -> None:
        """
        处理双击事件：如果双击表头则排序，否则进入编辑模式。
        """
        region = self.tree.identify("region", event.x, event.y)
        if region == "heading":
            column = self.tree.identify_column(event.x)
            col_index = int(column.replace('#', '')) - 1
            if col_index < len(self.all_columns):
                column_name = self.all_columns[col_index]
                self.sort_by_column(column_name)
            return

        if region == "cell":
            # 进入编辑模式
            self._start_edit_cell(event)

    def _start_edit_cell(self, event: tk.Event):
        """
        进入单元格编辑模式。
        """
        if self.editing_entry:
            self.editing_entry.destroy()
            self.editing_entry = None

        item_id = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if not item_id or not column:
            return

        column_index = int(column.replace('#', '')) - 1
        allowed_columns = [0, 1, 2]  # 型号、缩写、单价

        if column_index not in allowed_columns:
            return

        bbox = self.tree.bbox(item_id, column)
        if not bbox:
            return

        x, y, width, height = bbox
        value = self.tree.set(item_id, column)

        if column_index == 2:  # 单价
            vcmd = (self.root.register(self.validate_price_input), '%P')
            self.editing_entry = tk.Entry(self.tree, validate='key', validatecommand=vcmd)
        else:
            self.editing_entry = tk.Entry(self.tree)

        self.editing_entry.place(x=x, y=y, width=width, height=height)
        self.editing_entry.insert(0, value)
        self.editing_entry.focus()
        self.editing_entry.select_range(0, tk.END)

        # 自动保存（失去焦点或按方向键时）
        def save_edit(event=None):
            new_value = self.editing_entry.get().strip()
            if column_index == 0 and not new_value:
                messagebox.showwarning("输入错误", "型号不能为空。")
                return
            if column_index == 2:
                try:
                    new_price = float(new_value)
                    new_value_formatted = f"{new_price:.2f}"
                except ValueError:
                    messagebox.showerror("输入错误", "单价必须是数字。")
                    return
            else:
                new_price = None
                new_value_formatted = new_value

            product_id = int(item_id)
            product: Optional[Product] = self.db_manager.get_product_by_id(product_id)
            if not product:
                messagebox.showerror("错误", "无法找到产品信息。")
                self.editing_entry.destroy()
                self.editing_entry = None
                return

            updated_model = product.model
            updated_abbr = product.abbreviations
            updated_price = product.price

            if column_index == 0:
                updated_model = new_value
            elif column_index == 1:
                updated_abbr = new_value
            elif column_index == 2:
                updated_price = new_price

            self.db_manager.update_product(product_id, updated_model, updated_abbr, updated_price)
            self.tree.set(item_id, column, new_value_formatted)
            self.editing_entry.destroy()
            self.editing_entry = None
            self.status_label.config(text="产品信息更新成功。")
            # 新增：回车后让焦点回到tree，避免再次进入编辑
            self.tree.focus_set()

        self.editing_entry.bind('<FocusOut>', lambda e: save_edit())
        self.editing_entry.bind('<Return>', lambda e: save_edit())  # 新增：回车保存并退出
        # 支持方向键切换单元格
        def move_edit(event):
            save_edit()
            direction = None
            if event.keysym in ("Up", "Down", "Left", "Right"):
                direction = event.keysym
            if direction:
                next_item, next_col = self._get_next_cell(item_id, column_index, direction)
                if next_item and next_col is not None:
                    bbox = self.tree.bbox(next_item, f"#{next_col+1}")
                    if bbox:
                        new_event = tk.Event()
                        new_event.x = bbox[0] + bbox[2] // 2
                        new_event.y = bbox[1] + bbox[3] // 2
                        self._start_edit_cell(new_event)
        self.editing_entry.bind('<Up>', move_edit)
        self.editing_entry.bind('<Down>', move_edit)
        self.editing_entry.bind('<Left>', move_edit)
        self.editing_entry.bind('<Right>', move_edit)

    def _get_next_cell(self, item_id, col_index, direction):
        # 获取下一个可编辑单元格的位置
        children = self.tree.get_children()
        idx = children.index(item_id)
        if direction == "Up" and idx > 0:
            return children[idx-1], col_index
        if direction == "Down" and idx < len(children)-1:
            return children[idx+1], col_index
        if direction == "Left" and col_index > 0:
            return item_id, col_index-1
        if direction == "Right" and col_index < 2:
            return item_id, col_index+1
        return None, None

    def search_products_globally(self) -> None:
        """
        触发全局搜索产品，根据搜索关键词在所有店号中搜索匹配的产品，并支持排序。
        """
        search_term = self.search_entry.get().strip()
        if not search_term:
            # 不执行任何操作，当搜索框为空时
            self.status_label.config(text="")
            self.refresh_product_list()
            return

        # 全局搜索
        results = self.db_manager.search_products(
            search_term,
            store_id=None,
            order_by=self.sort_column,
            ascending=self.sort_ascending
        )
        if results:
            self.display_search_results(results, global_search=True)
            self.status_label.config(text=f"找到 {len(results)} 条结果。")
        else:
            # 不弹出弹窗，显示状态
            self.status_label.config(text="未找到符合条件的产品。")
            self.refresh_product_list()
            self.tree.delete(*self.tree.get_children())

    def display_search_results(self, results: List[Product], global_search: bool = False) -> None:
        """
        显示搜索结果到Treeview。

        :param results: 搜索结果列表
        :param global_search: 是否为全局搜索
        """
        self.tree.delete(*self.tree.get_children())
        if global_search:
            self.display_store_column()  # 显示“店号”列
            items = [
                (product.model, product.abbreviations, f"{product.price:.2f}", product.store_name)
                for product in results
            ]
        else:
            self.hide_store_column()  # 隐藏“店号”列
            items = [
                (product.model, product.abbreviations, f"{product.price:.2f}")
                for product in results
            ]

        for product, values in zip(results, items):
            self.tree.insert('', tk.END, values=values, iid=str(product.id))

    def handle_search_key_release(self, event: Optional[tk.Event] = None) -> None:
        """
        根据选定店号动态搜索：
        - 如果选定了店号，则搜索该店号内的产品；
        - 如果未选定店号，则进行全局搜索。

        :param event: 事件对象
        """
        search_term = self.search_entry.get().strip()
        if not search_term:
            # 如果搜索框为空，恢复显示模式，不清空列表
            self.refresh_product_list()
            self.status_label.config(text="")
            return

        if self.selected_store_id:
            # 局部搜索
            products = self.db_manager.search_products(
                search_term,
                store_id=self.selected_store_id,
                order_by=self.sort_column,
                ascending=self.sort_ascending
            )
            self.display_search_results(products, global_search=False)

            # 更新状态标签
            if products:
                self.status_label.config(text=f"找到 {len(products)} 条结果。")
            else:
                self.status_label.config(text="未找到符合条件的产品。")
        else:
            # 全局搜索
            self.search_products_globally()

    def show_import_products_section(self):
        """
        显示导入产品区块，并初始化源店、目标店选择和差异比对。
        """
        self.ui.show_import_products_section()  # 只调用UI层方法

    def hide_import_products_section(self):
        """
        隐藏导入产品区块，恢复主界面区块。
        """
        self.ui.hide_import_products_section()
        
    def on_source_store_selected(self, event=None):
        """
        源店选择后，刷新目标店多选列表和差异显示区。
        """
        source_store = self.ui.source_store_var.get()
        source_id = self.stores.get(source_store)
        target_names = [name for name in self.stores if name != source_store]
        # 清空目标店多选
        for widget in self.ui.target_store_frame.winfo_children():
            widget.destroy()
        self.ui.target_store_vars.clear()
        self.ui.target_store_checks.clear()
        # 横向排列，每行最多4个
        max_per_row = 4
        for idx, name in enumerate(target_names):
            var = tk.BooleanVar()
            chk = ttk.Checkbutton(self.ui.target_store_frame, text=name, variable=var, command=self.refresh_diff_frame)
            row, col = divmod(idx, max_per_row)
            chk.grid(row=row, column=col, sticky='w', padx=5, pady=2)
            self.ui.target_store_vars[name] = var
            self.ui.target_store_checks[name] = chk
        self.refresh_diff_frame()

    def refresh_diff_frame(self):
        """
        刷新差异显示区，根据当前选择的源店和目标店，显示每个目标店与源店的产品差异，并为每个差异项添加勾选框。
        """
        # 获取差异搜索关键词，统一小写
        search_term = self.ui.search_diff_entry.get().strip().lower()
        for widget in self.ui.diff_frame.winfo_children():
            widget.destroy()
        source_store = self.ui.source_store_var.get()
        source_id = self.stores.get(source_store)
        row = 0
        self.diff_overwrite_vars = {}  # {(target_name, model, field): bool}
        for target_name, var in self.ui.target_store_vars.items():
            if not var.get():
                continue
            target_id = self.stores.get(target_name)
            diffs = self.db_manager.compare_store_products(source_id, target_id)
            # 如果有搜索关键词，则过滤差异
            if search_term:
                filtered = {}
                for model, diff in diffs.items():
                    text = model.lower()
                    if diff['type'] == '新增':
                        text += diff['source'].abbreviations.lower() + str(diff['source'].price).lower()
                    else:
                        text += (diff['source'].abbreviations.lower() + str(diff['source'].price).lower() +
                                 diff['target'].abbreviations.lower() + str(diff['target'].price).lower())
                    if search_term in text:
                        filtered[model] = diff
                diffs = filtered
            if not diffs:
                ttk.Label(self.ui.diff_frame, text=f"{target_name}：无差异", foreground='green').grid(row=row, column=0, sticky='w')
                row += 1
                continue

            ttk.Label(self.ui.diff_frame, text=f"{source_store} → {target_name} 差异：", foreground='red').grid(row=row, column=0, sticky='w')
            row += 1
            columns = ("型号", "字段", f"{source_store}", f"{target_name}", "覆盖")
            tree = ttk.Treeview(self.ui.diff_frame, columns=columns, show="headings", height=min(len(diffs)*2, 10))
            for col in columns:
                tree.heading(col, text=col)
                tree.column(col, width=110, anchor='center')
            tree.grid(row=row, column=0, sticky='nsew')
            row += 1

            for model, diff in diffs.items():
                if diff['type'] == '新增':
                    tree.insert('', 'end', values=(model, "全部", getattr(diff['source'], 'abbreviations', ''), '', '自动导入'))
                elif diff['type'] == '不同':
                    for field in ['abbreviations', 'price']:
                        src_val = getattr(diff['source'], field, '')
                        tgt_val = getattr(diff['target'], field, '')
                        if src_val != tgt_val:
                            field_cn = "缩写" if field == 'abbreviations' else "单价"
                            iid = f"{target_name}|{model}|{field}"
                            self.diff_overwrite_vars[(target_name, model, field)] = False
                            tree.insert('', 'end', iid=iid, values=(model, field_cn, src_val, tgt_val, ''))

            # 绑定点击事件（必须在tree定义后、循环体内）
            def on_tree_click(event, target_name=target_name):
                tree = event.widget
                region = tree.identify("region", event.x, event.y)
                if region != "cell":
                    return
                col = tree.identify_column(event.x)
                if col != f"#{len(columns)}":  # “覆盖”列
                    return
                row_id = tree.identify_row(event.y)
                if not row_id:
                    return
                vals = tree.item(row_id, "values")
                model = vals[0]
                field_cn = vals[1]
                field = "abbreviations" if field_cn == "缩写" else "price"
                key = (target_name, model, field)
                self.diff_overwrite_vars[key] = not self.diff_overwrite_vars.get(key, False)
                tree.set(row_id, "覆盖", "√" if self.diff_overwrite_vars[key] else "")

            tree.bind("<Button-1>", on_tree_click)
            tree.bind("<MouseWheel>", lambda e: tree.yview_scroll(int(-1*(e.delta/120)), "units"))
            tree.configure(yscrollcommand=lambda *args: None)
            # 鼠标进入tree时，滚轮只滚tree
            tree.bind("<Enter>", lambda e, tree=tree: self.ui._set_mousewheel_target(tree))
            tree.bind("<Leave>", lambda e: self.ui._set_mousewheel_target(self.ui.import_canvas))

    def on_import_execute(self):
        """
        执行导入操作，根据用户选择的目标店和覆盖勾选，批量导入产品。
        """
        source_store = self.ui.source_store_var.get()
        source_id = self.stores.get(source_store)
        target_names = [name for name, var in self.ui.target_store_vars.items() if var.get()]
        overwrite_dict = {}  # {target_id: {model: {field: True/False}}}
        for target_name in target_names:
            target_id = self.stores.get(target_name)
            overwrite_dict[target_id] = {}
            diffs = self.db_manager.compare_store_products(source_id, target_id)
            for model, diff in diffs.items():
                if diff['type'] == '不同':
                    overwrite_dict[target_id][model] = {}
                    for field in ['abbreviations', 'price']:
                        key = (target_name, model, field)
                        checked = self.diff_overwrite_vars.get(key, False)
                        overwrite_dict[target_id][model][field] = checked
                elif diff['type'] == '新增':
                    overwrite_dict[target_id][model] = {'abbreviations': True, 'price': True}
        # 调用数据库批量导入（你需同步修改数据库方法以支持字段级覆盖）
        self.db_manager.copy_products_between_stores_batch(source_id, overwrite_dict)
        self.hide_import_products_section()
        self.status_label.config(text="产品批量导入完成。")
        self.load_stores()
        self.handle_store_selection()

    def display_store_column(self) -> None:
        """显示“店号”列并调整列宽。"""
        if not self.is_store_column_displayed:
            self.tree["displaycolumns"] = self.all_columns
            self.is_store_column_displayed = True
            # 重新配置列以确保排序命令仍然有效
            for col in self.all_columns:
                self.tree.heading(col, text=col, command=partial(self.sort_by_column, col))
                self.tree.column(col, width=self.column_widths[col], anchor='center', stretch=True if col != self.store_column else False)

    def hide_store_column(self) -> None:
        """隐藏“店号”列并调整列宽。"""
        if self.is_store_column_displayed:
            self.tree["displaycolumns"] = self.base_columns
            self.is_store_column_displayed = False
            # 重新配置列以确保排序命令仍然有效
            for col in self.base_columns:
                self.tree.heading(col, text=col, command=partial(self.sort_by_column, col))
                self.tree.column(col, width=self.column_widths[col], anchor='center', stretch=True)

    def handle_application_close(self) -> None:
        """关闭程序时的处理，包括关闭数据库连接。"""
        self.db_manager.close()
        self.root.destroy()

    def handle_search_button_click(self):
        """
        搜索按钮点击时，清空店号选择，进行全局搜索。
        """
        self.store_combobox.set('')  # 清空店号选择
        self.selected_store_id = None
        self.search_products_globally()

    # 差异搜索处理
    def handle_diff_search(self, event: Optional[tk.Event] = None) -> None:
        """
        根据差异搜索框内容刷新差异显示区。
        """
        self.refresh_diff_frame()
