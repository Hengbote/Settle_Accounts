# database/models.py

from dataclasses import dataclass

@dataclass
class Store:
    id: int
    name: str

@dataclass
class Product:
    id: int
    model: str
    abbreviations: str
    price: float
    store_id: int
    store_name: str = ""  # 可选，用于全局视图
