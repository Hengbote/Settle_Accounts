# --- bootstrap: 放在文件最顶部 ---
import os, sys, traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)  # 固定工作目录到脚本所在目录
LOG_FILE = BASE_DIR / "error.log"

# 如果是 pythonw.exe（无控制台），用 python.exe 重新启动自己
try:
    if os.path.basename(sys.executable).lower() == "pythonw.exe":
        console = Path(sys.executable).with_name("python.exe")
        if console.exists():
            os.execv(str(console), [str(console), str(Path(__file__).resolve())])
except Exception:
    pass  # 如果切换失败，继续下面的异常钩子

def _excepthook(exctype, value, tb):
    msg = "".join(traceback.format_exception(exctype, value, tb))
    # 写日志
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass
    # 弹窗（就算没进 mainloop 也能弹出来）
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk(); r.withdraw()
        messagebox.showerror("程序出错", msg)
        r.destroy()
    except Exception:
        pass
    # 有控制台的话再停住
    try:
        if sys.stdin and sys.stdin.isatty():
            input("按回车键退出...")
    except Exception:
        pass
sys.excepthook = _excepthook
# --- bootstrap 结束 ---

# main.py

import tkinter as tk
from app import ProductManagerApp

def main() -> None:
    """
    主函数，初始化并运行产品管理应用程序。
    """
    root = tk.Tk()
    root.title("产品管理系统")  # 设置窗口标题
    root.geometry("800x700")    # 设置初始窗口大小，适当增大以适应更多内容
    root.minsize(600, 700)      # 设置最小窗口大小为600x700

    app = ProductManagerApp(root)

    root.mainloop()

if __name__ == "__main__":
    main()

