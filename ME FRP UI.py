import sys
import os
import json
import subprocess
import atexit
import re
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QMessageBox, QDialog, QLineEdit, QFormLayout, QCheckBox, QSizePolicy, QSpacerItem,
    QListWidget, QScrollArea
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer  # 添加 QTimer
from PyQt5.QtGui import QIcon, QFont, QClipboard  # 将 QClipboard 移到这里

# 设置全局字体为微软雅黑
app_font = QFont("Microsoft YaHei")

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frp_tunnels_config.json")
NUM_TUNNELS = 8

# ------------------ Process Management ------------------
def start_frp_process(name, params):
    try:
        # 自动去除以./开头的启动参数
        if params.startswith('./'):
            params = params[2:]
        command = params.split()
        print(f'隧道 {name} 启动中...')
        proc = subprocess.Popen(
            command, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT, 
            bufsize=1, 
            text=True,                 # 替换 universal_newlines=True
            encoding="utf-8",          # 使用 utf-8 编码
            errors="replace"           # 遇到编码错误时进行替换
        )
        # 开启新的输出窗口
        output_win = OutputWindow(name)
        # 创建并启动读取输出的线程
        out_thread = OutputThread(proc)
        out_thread.new_line.connect(output_win.append_line)
        out_thread.start()
        # 保存输出窗口和线程到隧道配置（后续停止时可用）
        print(f'隧道 {name} 启动成功，进程ID: {proc.pid}')
        QMessageBox.information(None, "Success", f"隧道 {name} 启动成功，进程ID: {proc.pid}")
        # 将返回值扩展为字典，包括进程、输出窗口和线程
        return {"proc": proc, "output_win": output_win, "out_thread": out_thread}
    except Exception as e:
        QMessageBox.critical(None, "Error", f"Failed to start frp process: {e}")
        return None

def stop_frp_process(process_info):
    if process_info is not None and "proc" in process_info:
        proc = process_info["proc"]
        proc.terminate()
        if "output_win" in process_info:
            process_info["output_win"].close()

# ------------------ Capsule Style Switch ------------------
class CapsuleSwitch(QCheckBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        # 不显示文字
        self.setText("")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(50, 25)
        self.setStyleSheet("""
            QCheckBox::indicator {
                width: 50px;
                height: 25px;
            }
            QCheckBox::indicator:unchecked {
                border-radius: 12px;
                background-color: #cccccc;
            }
            QCheckBox::indicator:checked {
                border-radius: 12px;
                background-color: #009688;
            }
        """)

# ------------------ Settings Dialog ------------------
class SettingsDialog(QDialog):
    def __init__(self, tunnel_config, parent=None):
        super().__init__(parent)
        self.tunnel_config = tunnel_config
        self.original_desc = tunnel_config.get("desc", "")
        self.setWindowTitle("Tunnel Settings")
        # 添加窗口最小尺寸并设置初始大小
        self.setMinimumSize(400, 200)
        self.resize(400, 200)
        self.init_ui()
    
    def init_ui(self):
        layout = QFormLayout(self)
        
        self.name_edit = QLineEdit(self)
        self.name_edit.setText(self.tunnel_config.get("name", ""))
        layout.addRow("Tunnel Name:", self.name_edit)
        
        self.params_edit = QLineEdit(self)
        self.params_edit.setText(self.tunnel_config.get("params", ""))
        layout.addRow("Start Parameters:", self.params_edit)
        
        self.desc_edit = QLineEdit(self)
        self.desc_edit.setText(self.tunnel_config.get("desc", ""))
        layout.addRow("Description:", self.desc_edit)
        
        # Buttons
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save", self)
        save_btn.clicked.connect(self.on_save)
        btn_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        layout.addRow(btn_layout)
    
    def on_save(self):
        desc_text = self.desc_edit.text()
        if len(desc_text) > 18:
            # 显示警告，且恢复到修改前的文本
            QMessageBox.warning(self, "提示", f"描述最多只能输入18个字！\n修改前的文本：\n{self.original_desc}")
            self.desc_edit.setText(self.original_desc)
            return
        self.tunnel_config["name"] = self.name_edit.text()
        self.tunnel_config["params"] = self.params_edit.text()
        self.tunnel_config["desc"] = self.desc_edit.text()
        self.accept()

# ------------------ Tunnel Widget ------------------
class TunnelWidget(QWidget):
    def __init__(self, idx, tunnel_config, parent=None):
        super().__init__(parent)
        self.idx = idx
        self.tunnel_config = tunnel_config
        self.tunnel_config.setdefault("name", f"Tunnel {idx+1}")
        self.tunnel_config.setdefault("params", "")
        self.tunnel_config.setdefault("desc", "")
        self.tunnel_config.setdefault("process", None)
        self.tunnel_config.setdefault("saved_ip", "")  # 添加保存的IP字段
        self.init_ui()
    
    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        # top row: 隧道名称、胶囊式开关和设置按钮（删除查看输出按钮）
        top_row = QHBoxLayout()
        self.name_label = QLabel(self.tunnel_config["name"], self)
        self.name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        top_row.addWidget(self.name_label)
        
        # 创建胶囊式开关，并屏蔽信号，确保初始状态为未选中
        self.switch = CapsuleSwitch(self)
        self.switch.blockSignals(True)
        self.switch.setChecked(False)
        self.switch.blockSignals(False)
        self.switch.stateChanged.connect(self.on_switch_toggle)
        top_row.addWidget(self.switch)
        
        # settings 按钮
        settings_btn = QPushButton("设置", self)
        settings_btn.clicked.connect(self.open_settings)
        top_row.addWidget(settings_btn)
        
        self.main_layout.addLayout(top_row)
        
        # 描述标签（下方显示，灰色小字体）
        self.desc_label = QLabel(self.tunnel_config["desc"], self)
        self.desc_label.setStyleSheet("color: gray; font-size: 10pt;")
        self.main_layout.addWidget(self.desc_label)
        
        # URL显示区域
        url_layout = QHBoxLayout()
        self.url_display_label = QLabel("", self)
        self.url_display_label.setStyleSheet("color: blue; font-size: 10pt;")
        url_layout.addWidget(self.url_display_label)
        
        # 复制按钮
        self.copy_button = QPushButton("复制", self)
        self.copy_button.setFixedSize(40, 25)
        self.copy_button.setStyleSheet("font-size: 9pt;")
        self.copy_button.clicked.connect(self.copy_url_to_clipboard)
        self.copy_button.setVisible(False)  # 初始隐藏
        url_layout.addWidget(self.copy_button)
        
        self.main_layout.addLayout(url_layout)
        
        # 在初始化时显示保存的IP
        if self.tunnel_config.get("saved_ip"):
            self.url_display_label.setText(self.tunnel_config["saved_ip"])
            self.copy_button.setVisible(True)
    
    def open_settings(self):
        dialog = SettingsDialog(self.tunnel_config, self)
        if dialog.exec_():
            # 更新显示
            self.name_label.setText(self.tunnel_config["name"])
            self.desc_label.setText(self.tunnel_config["desc"])
            # 如果隧道正在运行，重新启动进程
            if self.switch.isChecked():
                if self.tunnel_config.get("process"):
                    stop_frp_process(self.tunnel_config["process"])
                proc = start_frp_process(self.tunnel_config["name"], self.tunnel_config["params"])
                self.tunnel_config["process"] = proc
                # 每次启动后延时1秒更新 URL，且仅更新一次
                QTimer.singleShot(1000, self.update_url)
            save_config()
    
    def on_switch_toggle(self, state):
        if state == Qt.Checked:
            # 开启隧道
            if self.tunnel_config.get("process"):
                stop_frp_process(self.tunnel_config["process"])
            proc = start_frp_process(self.tunnel_config["name"], self.tunnel_config["params"])
            self.tunnel_config["process"] = proc
            # 延时1秒更新 URL，仅更新一次
            QTimer.singleShot(1000, self.update_url)
        else:
            # 关闭隧道
            if self.tunnel_config.get("process"):
                stop_frp_process(self.tunnel_config["process"])
                self.tunnel_config["process"] = None
            QMessageBox.information(self, "隧道已关闭", f"隧道 {self.tunnel_config['name']} 已关闭")
            print(f"隧道 {self.tunnel_config['name']} 已关闭")
        save_config()
    
    def update_url(self):
        process_info = self.tunnel_config.get("process")
        if process_info:
            out_thread = process_info.get("out_thread")
            if out_thread:
                accumulated = out_thread.accumulated
                # 使用更全面的正则表达式来匹配各种URL格式
                # 匹配格式包括：
                # 1. 您可以使用 [IP:端口] 访问您的服务
                # 2. http://IP:端口
                # 3. https://域名:端口
                # 4. IP:端口
                # 5. 域名:端口
                patterns = [
                    r"您可以使用\s*\[([^\]]+)\]\s*访问您的服务",  # 原格式
                    r"(https?://[a-zA-Z0-9\.\-:]+)",           # URL格式
                    r"([a-zA-Z0-9\.\-]+:[0-9]+)",              # IP:端口或域名:端口格式
                    r"([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}:[0-9]+)"  # IP:端口格式
                ]
                
                url = ""
                for pattern in patterns:
                    m = re.search(pattern, accumulated)
                    if m:
                        url = m.group(1)
                        break
                
                if url:
                    self.url_display_label.setText(url)
                    self.copy_button.setVisible(True)  # 显示复制按钮
                    # 保存IP地址
                    self.tunnel_config["saved_ip"] = url
                    save_config()
                else:
                    # 如果没有找到URL，但有保存的IP，则显示保存的IP
                    if self.tunnel_config.get("saved_ip"):
                        self.url_display_label.setText(self.tunnel_config["saved_ip"])
                        self.copy_button.setVisible(True)
                    else:
                        self.url_display_label.setText("")
                        self.copy_button.setVisible(False)

    def copy_url_to_clipboard(self):
        url = self.url_display_label.text()
        if url:
            clipboard = QApplication.clipboard()  # 这行是正确的
            clipboard.setText(url)
            QMessageBox.information(self, "复制成功", "IP已复制到剪贴板")

# ------------------ Output Window and Thread ------------------
class OutputWindow(QDialog):
    def __init__(self, tunnel_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{tunnel_name} - Process Output")
        self.setMinimumSize(500, 400)
        self.list_widget = QListWidget(self)
        layout = QVBoxLayout(self)
        layout.addWidget(self.list_widget)
        self.setLayout(layout)

    def append_line(self, line):
        self.list_widget.addItem(line)
        # 自动滚动到最新
        self.list_widget.scrollToBottom()

class OutputThread(QThread):
    new_line = pyqtSignal(str)

    def __init__(self, process, parent=None):
        super().__init__(parent)
        self.process = process
        self.accumulated = ""  # 新增：累积所有输出

    def run(self):
        if self.process.stdout:
            for line in self.process.stdout:
                line = line.rstrip()
                if line:
                    print(line)  # 保持控制台输出
                    self.accumulated += line + "\n"  # 累积日志
                    self.new_line.emit(line)
        self.process.stdout.close()

# ------------------ Config Management ------------------
def save_config():
    data = {}
    for idx, tunnel in tunnels.items():
        data[idx] = {
            "name": tunnel["name"],
            "params": tunnel["params"],
            "desc": tunnel["desc"],
            "saved_ip": tunnel.get("saved_ip", "")  # 保存IP地址
        }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    for k, tunnel_data in data.items():
        idx = int(k)
        if idx in tunnels:
            tunnels[idx]["name"] = tunnel_data.get("name", f"Tunnel {idx+1}")
            tunnels[idx]["params"] = tunnel_data.get("params", "")
            tunnels[idx]["desc"] = tunnel_data.get("desc", "")
            tunnels[idx]["saved_ip"] = tunnel_data.get("saved_ip", "")  # 加载保存的IP
            # 确保每次加载时隧道 process 为空，不自动启动
            tunnels[idx]["process"] = None

# ------------------ Main Window ------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ME FRP UI")
        # 设置窗口图标，图标文件需位于同一文件夹下
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ME FRP.ico")
        self.setWindowIcon(QIcon(icon_path))
        
        # 创建菜单栏
        self.create_menu()
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)  # 允许滚动区域自动调整大小
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # 禁用水平滚动条
        
        # 创建中央部件并设置为滚动区域的部件
        self.central_widget = QWidget()
        scroll_area.setWidget(self.central_widget)
        self.setCentralWidget(scroll_area)
        
        self.layout = QVBoxLayout(self.central_widget)
        self.tunnel_widgets = {}
        self.init_ui()
        
        # 设置窗口的初始大小
        self.resize(500, 700)  # 调整窗口高度以适应更多内容
    
    def create_menu(self):
        # 创建菜单栏
        menubar = self.menuBar()
        
        # 创建"帮助"菜单
        help_menu = menubar.addMenu('帮助')
        
        # 创建"关于我们"动作
        about_action = help_menu.addAction('关于我们')
        about_action.triggered.connect(self.show_about)
    
    def show_about(self):
        # 创建关于我们的对话框
        about_text = '''ME FRP UI
Maker：True_white_
E-Mail：3885730600@qq.com
Blibili：https://space.bilibili.com/341941896
Version：Release1.0.0
Describe：为ME Frp量身打造的UI，目前功能不全，后续会持续更新
ME Frp Offical Website：https://www.mefrp.com/
Declaration：仅代表个人开发，与ME Frp及其开发者落雪无痕LxHHT无关
Copyright © 2025 True_white_&TIME-TW团队'''
        QMessageBox.about(self, '关于我们', about_text)
    
    def init_ui(self):
        # Create tunnel config storage and UI widgets
        for i in range(NUM_TUNNELS):
            # 初始化默认配置
            tunnel_config = {
                "name": f"Tunnel {i+1}",
                "params": "",
                "desc": "",
                "process": None,
                "saved_ip": ""  # 添加默认的saved_ip字段
            }
            tunnels[i] = tunnel_config
            tunnel_widget = TunnelWidget(i, tunnel_config, self)
            self.tunnel_widgets[i] = tunnel_widget
            self.layout.addWidget(tunnel_widget)
            
            # 分割线
            line = QWidget(self)
            line.setFixedHeight(1)
            line.setStyleSheet("background-color: #cccccc;")
            self.layout.addWidget(line)
        
        # 添加一个弹性空间，使隧道控件位于顶部
        self.layout.addStretch()
        
        load_config()
        # 在加载配置后，更新每个隧道widget的显示
        for i in range(NUM_TUNNELS):
            widget = self.tunnel_widgets[i]
            widget.name_label.setText(tunnels[i]["name"])
            widget.desc_label.setText(tunnels[i]["desc"])
            # 如果有保存的IP地址，则显示
            saved_ip = tunnels[i].get("saved_ip", "")
            if saved_ip:
                widget.url_display_label.setText(saved_ip)
                widget.copy_button.setVisible(True)

    def closeEvent(self, event):
        for i in range(NUM_TUNNELS):
            proc = tunnels[i].get("process")
            if proc:
                stop_frp_process(proc)
        save_config()
        event.accept()

# ------------------ Cleanup Function ------------------
def cleanup():
    # 当程序退出时，关闭所有隧道进程
    for idx in range(NUM_TUNNELS):
        process_info = tunnels.get(idx, {}).get("process")
        if process_info:
            stop_frp_process(process_info)
            print(f"隧道 {tunnels[idx]['name']} 已关闭")

atexit.register(cleanup)

# ------------------ Main ------------------
tunnels = {}
if __name__ == "__main__":
    app = QApplication(sys.argv)
    # 设置全局字体
    app.setFont(app_font)
    main_win = MainWindow()
    main_win.resize(500, 600)
    main_win.show()
    sys.exit(app.exec_())