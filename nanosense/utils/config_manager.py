# nanosense/utils/config_manager.py
import json
import os

# 定义配置文件的标准存储位置 (用户主目录下的 .nanosense 文件夹)
# 这是跨平台的最佳实践，可以避免权限问题
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".nanosense")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

def get_default_settings():
    """返回一个包含所有键的默认设置字典。"""
    return {
        'default_save_path': '',
        'default_load_path': '',
        'analysis_wl_start': 450.0,
        'analysis_wl_end': 750.0,
        'theme': 'dark',  # 添加主题设置，默认为深色主题
        'mock_api_config': {
            "mode": "dynamic",  # 可选 "static", "dynamic", "noisy_baseline"
            "static_peak_pos": 650.0,
            "static_peak_amp": 15000.0,
            "static_peak_width": 10.0,
            "noise_level": 50.0,
            "dynamic_initial_pos": 650.0,
            "dynamic_shift_total": 10.0,
            "dynamic_baseline_duration": 5,
            "dynamic_assoc_duration": 20,
            "dynamic_dissoc_duration": 30
        }
    }

def load_settings():
    """从JSON文件中加载设置。如果文件或目录不存在，则返回一个包含默认值的字典。"""
    defaults = get_default_settings()
    if not os.path.exists(CONFIG_FILE):
        return defaults

    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)
            # 确保所有默认键都存在，以兼容旧的配置文件
            for key, value in defaults.items():
                # 【重要】如果键不存在，则用默认值填充
                settings.setdefault(key, value)
                # 如果键存在，但内部的子键不全（比如旧版config没有dynamic_baseline_duration），也进行填充
                if isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        settings[key].setdefault(sub_key, sub_value)
            return settings
    except (json.JSONDecodeError, IOError) as e:
        print(f"加载配置文件时出错: {e}")
        return defaults # 出错时返回默认值

def save_settings(settings):
    """将设置字典保存到JSON文件。"""
    try:
        # 确保配置目录存在
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4)
    except IOError as e:
        print(f"保存配置文件时出错: {e}")