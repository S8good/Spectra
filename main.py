# main.py

import sys
import os
import time

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon
from nanosense.gui.main_window import AppWindow
from nanosense.gui.splash_screen import SplashScreen
from nanosense.gui.welcome_widget import WelcomeWidget
import pyqtgraph as pg

# 设置图表样式
pg.setConfigOption('background', '#1A202C')
pg.setConfigOption('foreground', '#E2E8F0')

# 全局变量，用于持有对窗口的引用，防止被垃圾回收
# 我们现在需要分别管理欢迎页和主程序窗口
welcome_screen = None
main_app_window = None

def show_welcome_screen(use_real_hardware=True):
    """
    创建并显示欢迎/启动器窗口。
    这是程序启动和重启的入口点。
    """
    global welcome_screen
    welcome_screen = WelcomeWidget()
    if use_real_hardware:
        welcome_screen.hardware_mode_combo.setCurrentIndex(0)  # 0 是 "真实硬件"
    else:
        welcome_screen.hardware_mode_combo.setCurrentIndex(1)  # 1 是 "模拟API"

        # 连接信号：当用户在欢迎页选择模式后，启动主程序
    welcome_screen.mode_selected.connect(launch_main_app)
    welcome_screen.show()

def launch_main_app(mode_name, use_real_hardware):
    """
    【已升级】这个函数现在会在硬件连接失败时返回欢迎页，而不是退出。
    """
    global main_app_window, welcome_screen

    # 在尝试连接时，先隐藏欢迎页，避免界面卡顿
    if welcome_screen:
        welcome_screen.hide()

    print(f"接收到启动信号，模式: {mode_name}, 使用真实硬件: {use_real_hardware}")

    main_app_window = AppWindow(use_real_hardware=use_real_hardware)

    # --- 【核心修改】检查硬件连接是否失败 ---
    if main_app_window.controller is None:
        # AppWindow 内部已经弹出了错误提示框，并且会自动关闭
        print("主窗口初始化失败 (硬件连接失败)，正在返回欢迎页...")

        # 重新显示欢迎页
        if welcome_screen:
            welcome_screen.show()
        return  # 终止这次失败的启动尝试

    # --- 如果硬件连接成功，则执行以下代码 ---
    print("硬件连接成功，正在启动主窗口...")
    main_app_window.restart_requested.connect(show_welcome_screen)

    main_app_window.switch_to_initial_view(mode_name)
    main_app_window.show()

    # 成功启动主窗口后，可以彻底关闭欢迎页了
    if welcome_screen:
        welcome_screen.close()
        # 清理引用是个好习惯
        welcome_screen = None

if __name__ == '__main__':
    app = QApplication(sys.argv)
    #设置应用程序图标
    # 这段代码的目的是设置所有窗口左上角和任务栏的图标
    icon_path = os.path.join(os.path.dirname(__file__), 'nanosense', 'gui', 'assets', 'app_icon.ico')
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    else:
        print(f"警告：应用图标文件未找到于 {icon_path}")

    # --- 启动画面逻辑 ---
    # 这部分逻辑可以保持原样，也可以移除以加快调试速度
    splash_image_path = os.path.join(
        os.path.dirname(__file__),
        'nanosense', 'gui', 'assets', 'splash.png'
    )
    if os.path.exists(splash_image_path):
        splash = SplashScreen(splash_image_path)
        splash.show()
        # 在循环中处理UI事件，防止界面冻结
        for i in range(1, 101):
            splash.update_progress(i)
            time.sleep(0.01)  # 再次加速
            app.processEvents()

    # --- 新的启动流程 ---
    # 1. 直接调用函数来显示欢迎窗口
    show_welcome_screen()

    # 2. 如果有启动画面，则在显示欢迎窗口后关闭它
    if 'splash' in locals() and welcome_screen:
        splash.finish(welcome_screen)

    # 3. 启动事件循环
    sys.exit(app.exec_())