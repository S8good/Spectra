# main_acquisition_loop.py
import time
import queue
import threading
import numpy as np
from nanosense.core.controller import FX2000Controller


def acquisition_thread_func(controller: FX2000Controller, data_queue: queue.Queue, stop_event: threading.Event):
    """后台采集线程运行的函数。"""
    print("采集线程已启动...")
    while not stop_event.is_set():
        try:
            wavelengths, spectrum = controller.get_spectrum()
            # 将数据放入队列
            data_queue.put((wavelengths, spectrum))
            time.sleep(0.1)  # 控制采集速率为 10Hz
        except Exception as e:
            print(f"采集线程出错: {e}")
            break
    print("采集线程已停止。")


if __name__ == "__main__":
    # 初始化控制器
    controller = FX2000Controller.connect()

    if controller:
        # 创建线程安全的队列和停止事件
        data_queue = queue.Queue(maxsize=10)
        stop_event = threading.Event()

        # 设置光谱仪参数
        controller.set_integration_time(50)
        controller.set_scans_to_average(3)

        # 创建并启动采集线程
        acquisition_thread = threading.Thread(
            target=acquisition_thread_func,
            args=(controller, data_queue, stop_event)
        )
        acquisition_thread.daemon = True  # 设置为守护线程，主程序退出时自动结束
        acquisition_thread.start()

        print("\n--- 主线程开始处理数据 (按 Ctrl+C 停止) ---\n")
        try:
            while True:
                try:
                    # 从队列中获取数据
                    wavelengths, spectrum = data_queue.get(timeout=1)

                    # 在真实的GUI中，这里会是更新图表的操作
                    # 我们在这里打印摘要信息
                    peak_intensity = np.max(spectrum)
                    peak_wavelength = wavelengths[np.argmax(spectrum)]
                    print(f"\r接收到新光谱: 峰值强度 {peak_intensity:.2f} @ {peak_wavelength:.2f} nm", end="")

                except queue.Empty:
                    # 如果队列为空，什么都不做
                    continue
        except KeyboardInterrupt:
            print("\n接收到手动中断信号。")
        finally:
            print("\n正在停止采集并断开连接...")
            stop_event.set()  # 通知线程停止
            controller.disconnect()
            print("程序已安全退出。")
    else:
        print("无法启动程序，因为硬件连接失败。")