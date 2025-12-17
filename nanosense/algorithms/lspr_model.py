# nanosense/algorithms/lspr_model.py
"""
LSPR 传感器仿真数据模型
提供微流控阵列仿真、偏移矩阵生成、光谱计算等功能
"""

import numpy as np
from typing import Dict, Tuple, Optional, Any
from scipy.special import erfc
from itertools import product


class SensorModel:
    """LSPR 传感器数据模型"""
    
    def __init__(self, array_size: int = 15):
        """初始化传感器模型
        
        Args:
            array_size: 微流控阵列尺寸（默认 15x15）
        """
        self.array_size = array_size
        self.shift_matrix = None
        self.noise_matrix = None
        
        # 当前配置参数
        self.current_material = 'Au'
        self.current_mode = 'LSPR'
        self.current_concentration = 100.0
        self.current_noise_level = 0.5
        self.current_temperature = 25.0
        
        # 材料参数库
        self.material_params = {
            'Au': {'shift_per_conc': 0.08, 'baseline_shift': 520.0},
            'Ag': {'shift_per_conc': 0.12, 'baseline_shift': 390.0},
            'Au@Ag': {'shift_per_conc': 0.10, 'baseline_shift': 450.0}
        }
        
        # 响应模型：linear 或 sigmoid
        self.response_model = 'linear'
        
        # Hill 方程参数（用于 sigmoid 模型）
        self.hill_params = {
            'K': 50.0,  # 半饱和浓度 (pM)
            'n': 2.0,   # Hill 系数
            'shift_max': 15.0  # 最大偏移 (nm)
        }
    
    def set_response_model(self, model_type: str):
        """设置响应模型类型"""
        self.response_model = model_type
    
    def _concentration_to_shift(self, concentration: float) -> float:
        """将浓度转换为波长偏移（使用当前响应模型）"""
        if self.response_model == 'sigmoid':
            return self._sigmoid_response(concentration)
        else:
            return self._linear_response(concentration)
    
    def _linear_response(self, concentration: float) -> float:
        """线性响应模型"""
        params = self.material_params.get(self.current_material, self.material_params['Au'])
        base = params['baseline_shift']
        shift_per_conc = params['shift_per_conc']
        return base + shift_per_conc * concentration
    
    def _sigmoid_response(self, concentration: float) -> float:
        """S型响应模型（Hill方程）"""
        K = self.hill_params['K']
        n = self.hill_params['n']
        shift_max = self.hill_params['shift_max']
        params = self.material_params.get(self.current_material, self.material_params['Au'])
        base = params['baseline_shift']
        
        # Hill 方程：Shift = Shift_max / (1 + (K/C)^n)
        if concentration <= 0:
            return base
        shift = shift_max / (1.0 + (K / concentration) ** n)
        return base + shift
    
    def _generate_gaussian_distribution_advanced(self, peak_value: float, 
                                                  center_pos: Tuple[float, float] = None) -> np.ndarray:
        """生成高斯空间分布"""
        if center_pos is None:
            center_pos = (self.array_size / 2.0, self.array_size / 2.0)
        
        center_x, center_y = center_pos
        sigma = self.array_size / 4.0
        
        x = np.arange(self.array_size)
        y = np.arange(self.array_size)
        X, Y = np.meshgrid(x, y)
        
        dist = np.sqrt((X - center_x)**2 + (Y - center_y)**2)
        distribution = peak_value * np.exp(-(dist**2) / (2 * sigma**2))
        
        return distribution
    
    def _generate_noise(self, noise_level: float) -> np.ndarray:
        """生成随机噪声"""
        return np.random.normal(0, noise_level, (self.array_size, self.array_size))
    
    def _calculate_temperature_offset(self, temperature: float) -> np.ndarray:
        """计算温度偏移"""
        base_temp = 25.0
        temp_coeff = 0.02  # nm/°C
        offset = (temperature - base_temp) * temp_coeff
        return np.full((self.array_size, self.array_size), offset)
    
    def generate_shift_matrix(self, material: str = 'Au', mode: str = 'LSPR',
                              concentration: float = 100.0, noise_level: float = 0.5,
                              temperature: float = 25.0) -> np.ndarray:
        """生成波长偏移矩阵
        
        Args:
            material: 纳米材料（Au/Ag/Au@Ag）
            mode: 共振模式（LSPR/SLR）
            concentration: 浓度 (pM)
            noise_level: 噪声水平 (0-1)
            temperature: 温度 (°C)
        
        Returns:
            波长偏移矩阵 (15x15)
        """
        self.current_material = material
        self.current_mode = mode
        self.current_concentration = concentration
        self.current_noise_level = noise_level
        self.current_temperature = temperature
        
        # MVP 阶段：基础生成策略
        # 1. 根据浓度生成基础偏移值
        base_shift = self._concentration_to_shift(concentration)
        
        # 2. 生成空间分布（简化的高斯分布）
        shift_base = self._generate_gaussian_distribution_advanced(base_shift)
        
        # 3. 叠加噪声
        noise = self._generate_noise(noise_level)
        
        # 4. 温度影响（可选）
        temp_offset = self._calculate_temperature_offset(temperature)
        
        self.shift_matrix = shift_base + noise + temp_offset
        self.noise_matrix = noise
        
        # 确保所有值非负
        self.shift_matrix = np.maximum(self.shift_matrix, 0)
        
        return self.shift_matrix
    
    def get_statistics(self) -> Dict[str, float]:
        """获取偏移矩阵的统计信息"""
        if self.shift_matrix is None:
            return {'min': 0, 'max': 0, 'mean': 0, 'std': 0}
        
        return {
            'min': float(np.min(self.shift_matrix)),
            'max': float(np.max(self.shift_matrix)),
            'mean': float(np.mean(self.shift_matrix)),
            'std': float(np.std(self.shift_matrix))
        }
    
    def get_spectrum(self, row: int, col: int) -> Dict[str, Any]:
        """获取指定位置的光谱数据
        
        Args:
            row: 行索引 (0-14)
            col: 列索引 (0-14)
        
        Returns:
            包含波长、基线、信号、偏移等数据的字典
        """
        # 波长范围：400-700 nm
        wavelengths = np.linspace(400, 700, 300)
        
        # 获取该位置的偏移值
        if self.shift_matrix is not None and 0 <= row < self.array_size and 0 <= col < self.array_size:
            shift = float(self.shift_matrix[row, col])
        else:
            shift = 0.0
        
        # 生成基线（高斯曲线，中心在 550 nm）
        baseline_center = 550.0
        baseline_sigma = 50.0
        baseline = 1.0 - 0.8 * np.exp(-((wavelengths - baseline_center)**2) / (2 * baseline_sigma**2))
        
        # 生成信号（基线偏移）
        signal = 1.0 - 0.8 * np.exp(-((wavelengths - baseline_center - shift)**2) / (2 * baseline_sigma**2))
        
        return {
            'wavelengths': wavelengths,
            'baseline': baseline,
            'signal': signal,
            'shift': shift,
            'material': self.current_material,
            'mode': self.current_mode,
            'concentration': self.current_concentration
        }
    
    def calculate_sensitivity(self, conc_range: Tuple[float, float]) -> float:
        """计算灵敏度（在给定浓度范围内）
        
        Args:
            conc_range: (低浓度, 高浓度) 元组，单位 pM
        
        Returns:
            灵敏度值 (nm/pM)
        """
        c_low, c_high = conc_range
        shift_low = self._concentration_to_shift(c_low)
        shift_high = self._concentration_to_shift(c_high)
        
        sensitivity = (shift_high - shift_low) / (c_high - c_low)
        return abs(sensitivity)
    
    # ==================== Phase 2 高级功能 ====================
    
    def concentration_sweep_linear(self, start: float = 1.0, end: float = 1000.0, 
                                   num_points: int = 20) -> np.ndarray:
        """生成对数间距的浓度扫描点"""
        return np.logspace(np.log10(start), np.log10(end), num_points)
    
    def concentration_sweep_linear_scale(self, start: float = 1.0, end: float = 1000.0,
                                         num_points: int = 20) -> np.ndarray:
        """生成线性间距的浓度扫描点"""
        return np.linspace(start, end, num_points)
    
    def get_sensitivity_curve(self, concentrations: Optional[np.ndarray] = None) -> Dict[float, float]:
        """获取灵敏度曲线数据 (S = dΔλ/dC)"""
        if concentrations is None:
            concentrations = self.concentration_sweep_linear(1, 1000, 20)
        
        sensitivities = {}
        delta_c = 1.0
        
        for c in concentrations:
            if c - delta_c > 0:
                shift_minus = self._concentration_to_shift(c - delta_c)
                shift_plus = self._concentration_to_shift(c + delta_c)
                s = (shift_plus - shift_minus) / (2 * delta_c)
            else:
                shift_c = self._concentration_to_shift(c)
                shift_c_plus = self._concentration_to_shift(c + delta_c)
                s = (shift_c_plus - shift_c) / delta_c
            
            sensitivities[float(c)] = float(abs(s))
        
        return sensitivities
    
    def fick_diffusion_distribution(self, peak_value: float, diffusion_time: float = 1.0,
                                   diffusion_coeff: float = 1e-5) -> np.ndarray:
        """基于 Fick 扩散方程的浓度梯度分布"""
        center = self.array_size / 2.0
        diffusion_length = np.sqrt(4 * diffusion_coeff * diffusion_time)
        
        x = np.arange(self.array_size)
        y = np.arange(self.array_size)
        X, Y = np.meshgrid(x, y)
        
        dist = np.sqrt((X - center)**2 + (Y - center)**2)
        diffusion = peak_value * erfc(dist / (2 * diffusion_length + 1e-10))
        
        return np.clip(diffusion, 0, peak_value)
    
    def biomarker_gradient_distribution(self, center_conc: float = 100.0,
                                       gradient_type: str = 'exponential') -> np.ndarray:
        """生物标志物浓度梯度分布"""
        center = self.array_size / 2.0
        x = np.arange(self.array_size)
        y = np.arange(self.array_size)
        X, Y = np.meshgrid(x, y)
        
        dist = np.sqrt((X - center)**2 + (Y - center)**2)
        max_dist = np.sqrt(2 * (center**2))
        normalized_dist = dist / max_dist
        
        if gradient_type == 'exponential':
            distribution = center_conc * np.exp(-2 * normalized_dist)
        elif gradient_type == 'linear':
            distribution = center_conc * (1 - normalized_dist)
        elif gradient_type == 'gaussian':
            sigma = 0.3
            distribution = center_conc * np.exp(-(normalized_dist**2) / (2 * sigma**2))
        else:
            sigma = 0.3
            distribution = center_conc * np.exp(-(normalized_dist**2) / (2 * sigma**2))
        
        return np.clip(distribution, 0, center_conc)
    
    def parameter_sweep_multi(self, param_ranges: Dict[str, np.ndarray],
                             fixed_params: Dict[str, Any] = None) -> Dict[str, Any]:
        """多参数空间扫描"""
        if fixed_params is None:
            fixed_params = {}
        
        results = {
            'parameters': param_ranges,
            'fixed_params': fixed_params,
            'sweep_results': []
        }
        
        param_names = list(param_ranges.keys())
        param_values = [param_ranges[name] for name in param_names]
        
        for value_combo in product(*param_values):
            param_dict = {}
            for name, value in zip(param_names, value_combo):
                param_dict[name] = value
            param_dict.update(fixed_params)
            
            if 'concentration' in param_dict:
                concentration = param_dict['concentration']
                noise_level = param_dict.get('noise_level', 0.5)
                material = param_dict.get('material', 'Au')
                mode = param_dict.get('mode', 'LSPR')
                temperature = param_dict.get('temperature', 25.0)
                
                shift_matrix = self.generate_shift_matrix(
                    material=material,
                    mode=mode,
                    concentration=concentration,
                    noise_level=noise_level,
                    temperature=temperature
                )
                
                stats = self.get_statistics()
                sensitivity = self.calculate_sensitivity((concentration*0.5, concentration*2))
                
                results['sweep_results'].append({
                    'parameters': param_dict,
                    'statistics': stats,
                    'sensitivity': sensitivity,
                    'matrix_sum': float(np.sum(shift_matrix))
                })
        
        return results
    
    def find_optimal_parameters(self, objective: str = 'max_sensitivity') -> Dict[str, Any]:
        """搜索最优参数配置"""
        conc_ranges = [(1, 50), (10, 100), (50, 500), (100, 1000)]
        results = {}
        
        for c_low, c_high in conc_ranges:
            s = self.calculate_sensitivity((c_low, c_high))
            range_name = f"{c_low}-{c_high}pM"
            results[range_name] = {
                'sensitivity': s,
                'range': (c_low, c_high),
                'score': s * np.log10(c_high / c_low)
            }
        
        best_range = max(results.items(), key=lambda x: x[1]['score'])
        
        return {
            'objective': objective,
            'optimal_concentration_range': best_range[0],
            'optimal_sensitivity': best_range[1]['sensitivity'],
            'all_results': results
        }
