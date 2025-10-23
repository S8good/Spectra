import sys
import os
from pathlib import Path


class FX2000Controller:
    """
    光谱仪高级控制器（单例模式）。
    这个类负责与光谱仪硬件（或模拟API）进行交互，并确保在整个程序中只有一个控制器实例。
    """
    _instance = None

    def __init__(self, wrapper_instance, use_real_hardware, device_index=0):
        """
        私有构造函数，不应直接调用。请使用 connect() 方法。
        """
        if FX2000Controller._instance is not None:
            raise Exception("这是一个单例类，请使用 connect() 方法获取实例。")

        self.api_wrapper = wrapper_instance
        self.device_index = device_index
        self.is_real_hardware = use_real_hardware

        self.in_endpoint = None

        # 根据硬件模式获取设备属性
        if self.is_real_hardware:
            self._name = self.api_wrapper.getName(self.device_index)
            self._serial_number = self.api_wrapper.getSerialNumber(self.device_index)
            self._wavelengths = list(self.api_wrapper.getWavelengths(self.device_index))

            # for endpoint in self.api_wrapper.EndPoints:
            #     if endpoint.Address > 0x80 and "Bulk" in str(endpoint.GetType()):
            #         self.in_endpoint = endpoint
            #         print(f"已找到数据输入端点，地址: {hex(self.in_endpoint.Address)}")
            #         break
        else:  # 模拟API的属性是直接访问的
            self._name = self.api_wrapper.getName(self.device_index)
            self._serial_number = self.api_wrapper.getSerialNumber(self.device_index)
            self._wavelengths = self.api_wrapper.wavelengths

        FX2000Controller._instance = self

    #一个中止数据传输的公共方法
    def abort_endpoint_pipe(self):
        """
        强制中止输入端点的数据传输管道。
        这是从不稳定状态中恢复的关键。
        """
        if self.is_real_hardware and self.in_endpoint:
            try:
                print(f"正在中止端点 {hex(self.in_endpoint.Address)} 的数据管道...")
                self.in_endpoint.Abort()
                print("数据管道已中止。")
            except Exception as e:
                print(f"中止数据管道时发生错误: {e}")
        else:
            print("模拟模式或未找到输入端点，无需中止管道。")

    @classmethod
    def connect(cls, use_real_hardware=True, device_index=0):
        """
        连接到光谱仪的工厂方法。
        如果实例已存在，则直接返回；否则，创建新实例。
        :param use_real_hardware:布尔值，True表示连接真实硬件，False表示使用模拟API。
        :param device_index: 要连接的设备索引。
        :return: 控制器实例或None（如果连接失败）。
        """
        if cls._instance is None:
            print(f"首次连接，模式: {'真实硬件' if use_real_hardware else '模拟API'}")

            Wrapper = None
            if use_real_hardware:
                try:
                    import clr
                    # 计算并添加驱动路径
                    driver_path = Path(__file__).resolve().parents[1] / 'drivers'
                    if str(driver_path) not in sys.path:
                        sys.path.append(str(driver_path))
                    os.environ['PATH'] = f"{str(driver_path)};{os.environ['PATH']}"

                    clr.AddReference("IdeaOptics")
                    from IdeaOptics import Wrapper
                    print("已成功加载真实硬件驱动: IdeaOptics.dll")
                except Exception as e:
                    print(f"加载真实硬件驱动失败: {e}，将回退到模拟模式。")
                    from mock_spectrometer_api import Wrapper
                    use_real_hardware = False  # 强制切换模式
            else:
                from mock_spectrometer_api import Wrapper
                print("当前为模拟硬件模式。")

            try:
                api_wrapper = Wrapper()
                device_count = api_wrapper.OpenAllSpectrometers()

                if device_count == 0 and use_real_hardware:
                    print("未能找到任何光谱仪设备。请检查USB连接。")
                    return None

                cls(api_wrapper, use_real_hardware, device_index)
                print(f"已连接到设备: {cls._instance.name} (SN: {cls._instance.serial_number})")

            except Exception as e:
                print(f"硬件连接过程中发生错误: {e}")
                cls._instance = None

        return cls._instance

    @classmethod
    def disconnect(cls):
        """
        【已优化】类方法，用于断开连接并重置单例实例。
        这对于重启或切换硬件模式至关重要。
        """
        if cls._instance is not None:
            try:
                if cls._instance.is_real_hardware and hasattr(cls._instance.api_wrapper, 'closeAllSpectrometers'):
                    # 尝试调用底层的关闭方法（仅对真实硬件）
                    cls._instance.api_wrapper.closeAllSpectrometers()
            except Exception as e:
                print(f"关闭硬件时出错: {e}")
            finally:
                # 【核心】清空已缓存的实例，确保下次connect()可以重新创建
                cls._instance = None
                print("FX2000Controller 实例已重置。")

    @property
    def name(self):
        return self._name

    @property
    def serial_number(self):
        return self._serial_number

    @property
    def wavelengths(self):
        return self._wavelengths

    def set_integration_time(self, time_ms: int):
        """设置光谱仪的积分时间。"""
        self.api_wrapper.setIntegrationTime(self.device_index, time_ms)

    def set_scans_to_average(self, num_scans: int):
        """【新增】设置平均扫描次数。"""
        if hasattr(self.api_wrapper, 'setScansToAverage'):
            self.api_wrapper.setScansToAverage(self.device_index, num_scans)
        else:
            print("警告：当前API不支持设置平均扫描次数。")

    def get_spectrum(self):
        """【已修正】获取一条光谱数据，确保返回值为Numpy数组。"""
        import numpy as np  # Ensure numpy is imported
        spectrum_data = self.api_wrapper.getSpectrum(self.device_index)
        # Ensure both wavelengths and spectrum data are consistently NumPy arrays
        return np.array(self.wavelengths), np.array(list(spectrum_data))