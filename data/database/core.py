# database/core.py

import sqlite3
from typing import List, Optional, Tuple
from tkinter import messagebox

from .models import Store, Product
from .utils import show_error
import config 

# ==============================
# 数据库管理器模块
# ==============================

class DatabaseManager:
    """
    数据库管理器，用于处理与店号和产品相关的所有数据库操作。
    """

    def __init__(self, db_path: str = config.DB_PATH):
        """
        初始化数据库管理器，连接到SQLite数据库并创建必要的表。

        :param db_path: 数据库文件路径
        """
        self.db_path = db_path
        self.conn = self.connect()
        self.create_tables()

    def connect(self) -> Optional[sqlite3.Connection]:
        """连接到SQLite数据库，并启用外键支持。"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA foreign_keys = 1")  # 启用外键支持
            return conn
        except sqlite3.Error as e:
            show_error("数据库错误", f"无法连接到数据库: {e}")
            return None

    def create_tables(self):
        """创建或检查必要的表（店号表和产品表）。"""
        if not self.conn:
            return
        try:
            with self.conn:
                self.conn.execute('''
                    CREATE TABLE IF NOT EXISTS stores (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL UNIQUE
                    )
                ''')
                self.conn.execute('''
                    CREATE TABLE IF NOT EXISTS products (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        model TEXT NOT NULL,
                        abbreviations TEXT,
                        price REAL NOT NULL,
                        store_id INTEGER NOT NULL,
                        FOREIGN KEY(store_id) REFERENCES stores(id) ON DELETE CASCADE
                    )
                ''')
        except sqlite3.Error as e:
            self.show_db_error("无法创建表", e)

    def execute_query(
        self,
        query: str,
        params: Tuple = (),
        fetchone: bool = False,
        fetchall: bool = False,
        commit: bool = False
    ) -> Optional[List[Tuple]]:
        """
        统一的数据库查询和执行方法，简化错误处理。

        :param query: SQL查询语句
        :param params: 查询参数
        :param fetchone: 是否获取单条结果
        :param fetchall: 是否获取所有结果
        :param commit: 是否提交事务
        :return: 查询结果
        """
        if not self.conn:
            return None
        try:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            if commit:
                self.conn.commit()
            if fetchone:
                return cursor.fetchone()
            if fetchall:
                return cursor.fetchall()
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint" in str(e):
                return None
            self.show_db_error("数据库完整性错误", e)
        except sqlite3.Error as e:
            self.show_db_error("数据库错误", e)
        return None

    def show_db_error(self, title: str, error: Exception):
        """统一的数据库错误显示方法。"""
        show_error(title, f"{title}: {error}")

    # 店号相关操作
    def add_store(self, name: str) -> Optional[int]:
        """
        添加店号到数据库。如果店号已存在，则返回其ID。

        :param name: 店号名称
        :return: 新插入的店号ID或已存在的店号ID
        """
        query = 'INSERT INTO stores (name) VALUES (?)'
        self.execute_query(query, (name,), commit=True)
        return self.get_store_id(name)

    def get_store_id(self, name: str) -> Optional[int]:
        """
        根据店号名称获取其ID。

        :param name: 店号名称
        :return: 店号ID或None
        """
        query = 'SELECT id FROM stores WHERE name = ? COLLATE NOCASE'
        result = self.execute_query(query, (name,), fetchone=True)
        return result[0] if result else None

    def delete_store(self, store_id: int):
        """
        删除店号及其关联的产品。

        :param store_id: 店号ID
        """
        query = 'DELETE FROM stores WHERE id = ?'
        self.execute_query(query, (store_id,), commit=True)

    def get_stores(self) -> List[Store]:
        """
        获取所有店号。

        :return: 店号列表
        """
        query = 'SELECT id, name FROM stores ORDER BY name COLLATE NOCASE'
        results = self.execute_query(query, fetchall=True) or []
        return [Store(id=row[0], name=row[1]) for row in results]

    # 产品相关操作
    def add_product(self, model: str, abbreviations: str, price: float, store_id: int):
        """
        添加产品到数据库。

        :param model: 产品型号
        :param abbreviations: 产品缩写
        :param price: 产品单价
        :param store_id: 关联的店号ID
        """
        query = '''
            INSERT INTO products (model, abbreviations, price, store_id)
            VALUES (?, ?, ?, ?)
        '''
        self.execute_query(query, (model, abbreviations, price, store_id), commit=True)

    def get_products(
        self,
        store_id: Optional[int] = None,
        order_by: Optional[str] = None,
        ascending: bool = True
    ) -> List[Product]:
        """
        获取产品列表。

        :param store_id: 店号ID（可选，若为None，则获取所有店号的产品）
        :param order_by: 排序列名（"型号"、"单价" 或 "店号"）
        :param ascending: 是否升序排序
        :return: 产品列表
        """
        base_query = '''
            SELECT products.id, products.model, products.abbreviations, products.price
        '''
        if store_id is None:
            base_query += ', stores.name '
        base_query += '''
            FROM products
            JOIN stores ON products.store_id = stores.id
        '''
        params = []
        if store_id:
            base_query += 'WHERE store_id = ? '
            params.append(store_id)
        if order_by:
            column_map = {
                "型号": "products.model",
                "单价": "products.price",
                "店号": "stores.name"
            }
            db_order_by = column_map.get(order_by)
            if db_order_by:
                direction = 'ASC' if ascending else 'DESC'
                base_query += f'ORDER BY {db_order_by} COLLATE NOCASE {direction}'
        query = base_query
        results = self.execute_query(query, tuple(params), fetchall=True) or []
        if store_id is None:
            return [Product(id=row[0], model=row[1], abbreviations=row[2], price=row[3], store_id=0, store_name=row[4]) for row in results]
        else:
            return [Product(id=row[0], model=row[1], abbreviations=row[2], price=row[3], store_id=store_id) for row in results]

    def search_products(
        self,
        search_term: str,
        store_id: Optional[int] = None,
        order_by: Optional[str] = None,
        ascending: bool = True
    ) -> List[Product]:
        """
        搜索产品，根据型号或缩写匹配。

        :param search_term: 搜索关键词
        :param store_id: 店号ID（可选，进行局部搜索）
        :param order_by: 排序列名（"型号"、"单价" 或 "店号"）
        :param ascending: 是否升序排序
        :return: 搜索结果列表
        """
        search_pattern = f"%{search_term}%"
        if store_id:
            query = '''
                SELECT id, model, abbreviations, price FROM products
                WHERE store_id = ? AND (
                    model LIKE ? COLLATE NOCASE OR
                    abbreviations LIKE ? COLLATE NOCASE
                )
            '''
            params = (store_id, search_pattern, search_pattern)
            if order_by:
                column_map = {
                    "型号": "model",
                    "单价": "price"
                }
                db_order_by = column_map.get(order_by)
                if db_order_by:
                    direction = 'ASC' if ascending else 'DESC'
                    query += f' ORDER BY {db_order_by} COLLATE NOCASE {direction}'
        else:
            query = '''
                SELECT products.id, products.model, products.abbreviations, products.price, stores.name
                FROM products
                JOIN stores ON products.store_id = stores.id
                WHERE products.model LIKE ? COLLATE NOCASE 
                OR products.abbreviations LIKE ? COLLATE NOCASE
            '''
            params = (search_pattern, search_pattern)
            if order_by:
                column_map = {
                    "型号": "products.model",
                    "单价": "products.price",
                    "店号": "stores.name"
                }
                db_order_by = column_map.get(order_by)
                if db_order_by:
                    direction = 'ASC' if ascending else 'DESC'
                    query += f' ORDER BY {db_order_by} COLLATE NOCASE {direction}'
        results = self.execute_query(query, params, fetchall=True) or []
        if store_id is None:
            return [Product(id=row[0], model=row[1], abbreviations=row[2], price=row[3], store_id=0, store_name=row[4]) for row in results]
        else:
            return [Product(id=row[0], model=row[1], abbreviations=row[2], price=row[3], store_id=store_id) for row in results]

    def update_product(self, product_id: int, model: str, abbreviations: str, price: float):
        """
        更新产品信息。

        :param product_id: 产品ID
        :param model: 新型号
        :param abbreviations: 新缩写
        :param price: 新单价
        """
        query = '''
            UPDATE products
            SET model = ?, abbreviations = ?, price = ?
            WHERE id = ?
        '''
        self.execute_query(query, (model, abbreviations, price, product_id), commit=True)

    def delete_product(self, product_id: int):
        """
        删除产品。

        :param product_id: 产品ID
        """
        query = 'DELETE FROM products WHERE id = ?'
        self.execute_query(query, (product_id,), commit=True)

    def copy_products_between_stores(self, source_store_id: int, target_store_id: int):
        """
        将源店的产品复制到目标店。如果目标店已存在相同型号的产品，提示用户是否覆盖。

        :param source_store_id: 源店号ID
        :param target_store_id: 目标店号ID
        """
        source_products = self.get_products(store_id=source_store_id)
        for product in source_products:
            model = product.model
            abbreviations = product.abbreviations
            price = product.price
            existing_product = self.get_product_by_model(target_store_id, model)
            if existing_product:
                abbreviations_match = (existing_product.abbreviations.lower() == (abbreviations or '').lower())
                price_match = (existing_product.price == price)
                if abbreviations_match and price_match:
                    continue  # 数据相同，跳过
                else:
                    # 需要在主线程中弹出对话框，这里假设是在主线程
                    result = messagebox.askyesno(
                        "确认覆盖",
                        f"店号已存在型号 '{model}'，数据有变化，是否覆盖？"
                    )
                    if result:
                        self.update_product(existing_product.id, model, abbreviations, price)
            else:
                self.add_product(model, abbreviations, price, target_store_id)

    def get_product_by_model(self, store_id: int, model: str) -> Optional[Product]:
        """
        根据型号获取产品（不区分大小写）。

        :param store_id: 店号ID
        :param model: 产品型号
        :return: 产品信息或None
        """
        query = '''
            SELECT id, model, abbreviations, price FROM products
            WHERE store_id = ? AND model = ? COLLATE NOCASE
        '''
        result = self.execute_query(query, (store_id, model), fetchone=True)
        if result:
            return Product(id=result[0], model=result[1], abbreviations=result[2], price=result[3], store_id=store_id)
        return None

    def get_product_by_id(self, product_id: int) -> Optional[Product]:
        """
        根据产品ID获取产品信息。

        :param product_id: 产品ID
        :return: Product对象或None
        """
        query = '''
            SELECT products.id, products.model, products.abbreviations, products.price, products.store_id, stores.name
            FROM products
            JOIN stores ON products.store_id = stores.id
            WHERE products.id = ?
        '''
        result = self.execute_query(query, (product_id,), fetchone=True)
        if result:
            return Product(
                id=result[0],
                model=result[1],
                abbreviations=result[2],
                price=result[3],
                store_id=result[4],
                store_name=result[5]
            )
        return None

    def get_default_store_id(self) -> Optional[int]:
        """
        获取默认店的ID。如果不存在，返回None。

        :return: 默认店ID或None
        """
        return self.get_store_id(config.DEFAULT_STORE_NAME)
    
    def compare_store_products(self, source_store_id, target_store_id):
        """
        比较源店和目标店的产品，返回差异字典。
        :return: {model: {'type': '新增'/'不同'/'相同', 'source': {...}, 'target': {...}}}
        """
        source_products = {p.model: p for p in self.get_products(store_id=source_store_id)}
        target_products = {p.model: p for p in self.get_products(store_id=target_store_id)}
        diffs = {}
        for model, sp in source_products.items():
            tp = target_products.get(model)
            if not tp:
                diffs[model] = {'type': '新增', 'source': sp, 'target': None}
            elif (sp.abbreviations != tp.abbreviations) or (sp.price != tp.price):
                diffs[model] = {'type': '不同', 'source': sp, 'target': tp}
        return diffs

    def copy_products_between_stores_batch(self, source_store_id, overwrite_dict):
        """
        批量将源店产品导入多个目标店。
        :param overwrite_dict: {target_id: {model: True/False}}
        """
        source_products = {p.model: p for p in self.get_products(store_id=source_store_id)}
        for target_id, model_dict in overwrite_dict.items():
            target_products = {p.model: p for p in self.get_products(store_id=target_id)}
            for model, field_dict in model_dict.items():
                sp = source_products[model]
                if model not in target_products:
                    # 目标店没有，直接插入
                    self.add_product(sp.model, sp.abbreviations, sp.price, target_id)
                elif any(field_dict.values()):
                    # 目标店有，按字段覆盖
                    tp = target_products[model]
                    new_abbr = sp.abbreviations if field_dict.get('abbreviations') else tp.abbreviations
                    new_price = sp.price if field_dict.get('price') else tp.price
                    self.update_product(tp.id, sp.model, new_abbr, new_price)
        self.conn.commit() 

    def close(self):
        """关闭数据库连接。"""
        if self.conn:
            self.conn.close()
