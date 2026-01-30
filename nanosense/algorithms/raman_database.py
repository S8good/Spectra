# nanosense/algorithms/raman_database.py

import numpy as np

class RamanDatabase:
    """
    拉曼特征峰数据库类，用于存储和查询常见物质的拉曼特征峰。
    """
    
    def __init__(self):
        """
        初始化拉曼特征峰数据库
        """
        # 常见物质的拉曼特征峰数据库 (波数 cm⁻¹)
        self.database = {
            "Rhodamine 6G": {
                "peaks": [612, 774, 1184, 1311, 1362, 1510, 1650],
                "intensities": [1.0, 0.8, 0.6, 0.9, 1.0, 0.7, 0.8],
                "description": "常用的SERS探针分子",
                "excitation_wavelength": 785
            },
            "Crystal Violet": {
                "peaks": [421, 800, 1178, 1372, 1588],
                "intensities": [0.5, 0.3, 0.4, 1.0, 0.8],
                "description": "三苯甲烷染料",
                "excitation_wavelength": 785
            },
            "Phenylalanine": {
                "peaks": [621, 1003, 1033, 1208, 1603],
                "intensities": [0.4, 1.0, 0.8, 0.5, 0.6],
                "description": "氨基酸",
                "excitation_wavelength": 785
            },
            "Benzoic Acid": {
                "peaks": [625, 1001, 1183, 1285, 1601],
                "intensities": [0.3, 1.0, 0.4, 0.5, 0.6],
                "description": "芳香族羧酸",
                "excitation_wavelength": 785
            },
            "Naphthalene": {
                "peaks": [515, 763, 1380, 1500, 1580],
                "intensities": [0.4, 1.0, 0.6, 0.7, 0.8],
                "description": "多环芳烃",
                "excitation_wavelength": 785
            },
            "Polystyrene": {
                "peaks": [620, 760, 1001, 1155, 1450, 1603],
                "intensities": [0.3, 0.4, 1.0, 0.8, 0.5, 0.7],
                "description": "聚合物标准物质",
                "excitation_wavelength": 785
            },
            "Glucose": {
                "peaks": [490, 720, 915, 1125, 1360, 1450],
                "intensities": [0.4, 0.5, 1.0, 0.8, 0.6, 0.7],
                "description": "单糖",
                "excitation_wavelength": 785
            },
            "Lactate": {
                "peaks": [835, 1045, 1120, 1275, 1435],
                "intensities": [0.6, 1.0, 0.8, 0.5, 0.7],
                "description": "乳酸盐",
                "excitation_wavelength": 785
            },
            "Urea": {
                "peaks": [586, 1008, 1150, 1450],
                "intensities": [0.5, 1.0, 0.7, 0.6],
                "description": "含氮化合物",
                "excitation_wavelength": 785
            },
            "Water": {
                "peaks": [1640],
                "intensities": [1.0],
                "description": "水分子",
                "excitation_wavelength": 785
            }
        }
    
    def get_all_substances(self):
        """
        获取数据库中所有物质的名称
        
        返回:
        list: 物质名称列表
        """
        return list(self.database.keys())
    
    def get_substance_peaks(self, substance_name):
        """
        获取指定物质的拉曼特征峰
        
        参数:
        substance_name: str，物质名称
        
        返回:
        dict: 包含特征峰信息的字典，或None如果物质不存在
        """
        if substance_name in self.database:
            return self.database[substance_name]
        return None
    
    def search_by_peak_range(self, min_wavenumber, max_wavenumber):
        """
        根据波数范围搜索物质
        
        参数:
        min_wavenumber: float，最小波数
        max_wavenumber: float，最大波数
        
        返回:
        dict: 包含匹配物质及其特征峰的字典
        """
        matches = {}
        
        for substance, info in self.database.items():
            peaks = info["peaks"]
            # 检查是否有峰在指定范围内
            peaks_in_range = [peak for peak in peaks if min_wavenumber <= peak <= max_wavenumber]
            if peaks_in_range:
                matches[substance] = {
                    "peaks": peaks_in_range,
                    "intensities": [info["intensities"][i] for i, peak in enumerate(info["peaks"]) if min_wavenumber <= peak <= max_wavenumber],
                    "description": info["description"]
                }
        
        return matches
    
    def match_peaks(self, measured_peaks, tolerance=5.0):
        """
        将测量的峰与数据库中的物质进行匹配
        
        参数:
        measured_peaks: list，测量的峰位列表
        tolerance: float，峰位匹配的容差 (cm⁻¹)
        
        返回:
        list: 匹配结果列表，按匹配度排序
        """
        matches = []
        
        for substance, info in self.database.items():
            reference_peaks = info["peaks"]
            
            # 计算匹配分数
            matched_peaks = 0
            total_peaks = len(reference_peaks)
            
            for measured_peak in measured_peaks:
                for reference_peak in reference_peaks:
                    if abs(measured_peak - reference_peak) <= tolerance:
                        matched_peaks += 1
                        break
            
            # 计算匹配度
            match_score = matched_peaks / total_peaks if total_peaks > 0 else 0
            
            if match_score > 0:
                matches.append({
                    "substance": substance,
                    "match_score": match_score,
                    "matched_peaks": matched_peaks,
                    "total_peaks": total_peaks,
                    "reference_peaks": reference_peaks,
                    "description": info["description"]
                })
        
        # 按匹配度排序
        matches.sort(key=lambda x: x["match_score"], reverse=True)
        
        return matches
    
    def add_substance(self, name, peaks, intensities=None, description="", excitation_wavelength=785):
        """
        添加新物质到数据库
        
        参数:
        name: str，物质名称
        peaks: list，特征峰列表 (cm⁻¹)
        intensities: list，相对强度列表
        description: str，物质描述
        excitation_wavelength: float，激发波长 (nm)
        """
        if intensities is None:
            intensities = [1.0] * len(peaks)
        
        self.database[name] = {
            "peaks": peaks,
            "intensities": intensities,
            "description": description,
            "excitation_wavelength": excitation_wavelength
        }
        
    def remove_substance(self, name):
        """
        从数据库中移除物质
        
        参数:
        name: str，物质名称
        """
        if name in self.database:
            del self.database[name]
    
    def get_similar_substances(self, substance_name):
        """
        获取与指定物质相似的其他物质
        
        参数:
        substance_name: str，物质名称
        
        返回:
        list: 相似物质列表
        """
        if substance_name not in self.database:
            return []
        
        target_peaks = self.database[substance_name]["peaks"]
        similar_substances = []
        
        for name, info in self.database.items():
            if name == substance_name:
                continue
            
            peaks = info["peaks"]
            # 计算峰位相似度
            common_peaks = 0
            for peak in peaks:
                for target_peak in target_peaks:
                    if abs(peak - target_peak) <= 10.0:  # 10 cm⁻¹容差
                        common_peaks += 1
                        break
            
            similarity = common_peaks / max(len(peaks), len(target_peaks))
            if similarity > 0.3:  # 相似度阈值
                similar_substances.append({
                    "name": name,
                    "similarity": similarity,
                    "description": info["description"]
                })
        
        # 按相似度排序
        similar_substances.sort(key=lambda x: x["similarity"], reverse=True)
        
        return similar_substances


def create_raman_database():
    """
    创建拉曼特征峰数据库实例
    
    返回:
    RamanDatabase: 拉曼特征峰数据库实例
    """
    return RamanDatabase()


def search_raman_substances_by_peaks(peaks, tolerance=5.0):
    """
    根据测量的峰位搜索可能的物质
    
    参数:
    peaks: list，测量的峰位列表 (cm⁻¹)
    tolerance: float，峰位匹配的容差 (cm⁻¹)
    
    返回:
    list: 匹配物质列表，按匹配度排序
    """
    db = create_raman_database()
    return db.match_peaks(peaks, tolerance)


def get_raman_substance_info(substance_name):
    """
    获取指定物质的详细信息
    
    参数:
    substance_name: str，物质名称
    
    返回:
    dict: 物质信息字典
    """
    db = create_raman_database()
    return db.get_substance_peaks(substance_name)


def get_all_raman_substances():
    """
    获取所有可用的拉曼物质
    
    返回:
    list: 物质名称列表
    """
    db = create_raman_database()
    return db.get_all_substances()
