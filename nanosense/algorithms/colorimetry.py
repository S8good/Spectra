import numpy as np
import colour
import inspect

def calculate_colorimetric_values(wavelengths, spectral_data, illuminant='D65', observer='2'):
    """
    根据光谱数据计算色度学参数（兼容 colour 0.3.x / 0.4.x 全版本）。
    自动检测函数参数、异常安全，不会影响上层 GUI。
    """
    if wavelengths is None or spectral_data is None or len(wavelengths) < 2:
        return {}

    try:
        # ===== 1. 光谱预处理 =====
        sd = colour.SpectralDistribution(dict(zip(wavelengths, spectral_data)))

        # 插值（兼容不同版本）
        if hasattr(colour, 'SPECTRAL_SHAPE_DEFAULT'):
            sd_interpolated = sd.interpolate(colour.SPECTRAL_SHAPE_DEFAULT)
        else:
            shape = colour.SpectralShape(360, 780, 1)
            sd_interpolated = sd.interpolate(shape)

        # 归一化
        if sd_interpolated.values.max() > 0:
            if hasattr(sd_interpolated, 'normalise'):
                sd_normalized = sd_interpolated.normalise()
            else:
                sd_normalized = sd_interpolated.normalise_maximum()
        else:
            sd_normalized = sd_interpolated

        # ===== 2. 获取光源与观察者 =====
        if hasattr(colour, 'MSDS_CMFS'):
            cmfs = colour.MSDS_CMFS['CIE 1931 2 Degree Standard Observer']
            illuminant_sd = colour.SDS_ILLUMINANTS[illuminant]
        else:
            cmfs = colour.STANDARD_OBSERVERS_CMFS['CIE 1931 2 Degree Standard Observer']
            illuminant_sd = colour.ILLUMINANTS_SDS[illuminant]

        # ===== 3. 计算 XYZ =====
        xyz = colour.sd_to_XYZ(sd_normalized, cmfs, illuminant_sd)

        # ===== 4. 获取参考白点 =====
        if hasattr(colour, 'CCS_ILLUMINANTS'):
            observer_name = 'CIE 1931 2 Degree Standard Observer'
            illuminant_xy = colour.CCS_ILLUMINANTS[observer_name][illuminant]
        else:
            illuminant_xy = colour.ILLUMINANTS[cmfs.name][illuminant]
        xyz_n = colour.xy_to_XYZ(illuminant_xy)

        # ===== 5. CIE Lab =====
        lab_params = inspect.signature(colour.XYZ_to_Lab).parameters
        if 'illuminant' in lab_params:
            lab = colour.XYZ_to_Lab(xyz, illuminant=xyz_n)
        elif 'whitepoint' in lab_params:
            lab = colour.XYZ_to_Lab(xyz, whitepoint=xyz_n)
        else:
            lab = colour.XYZ_to_Lab(xyz, xyz_n)

        # ===== 6. Hunter Lab =====
        try:
            hunter_params = inspect.signature(colour.XYZ_to_Hunter_Lab).parameters
            if 'illuminant' in hunter_params:
                hunter_lab = colour.XYZ_to_Hunter_Lab(xyz, illuminant=xyz_n)
            elif 'whitepoint' in hunter_params:
                hunter_lab = colour.XYZ_to_Hunter_Lab(xyz, whitepoint=xyz_n)
            else:
                hunter_lab = colour.XYZ_to_Hunter_Lab(xyz, xyz_n)
        except Exception as e:
            print(f"警告: Hunter Lab 计算失败 ({e})，结果使用 NaN。")
            hunter_lab = np.array([np.nan, np.nan, np.nan])

        # ===== 7. xy 色度坐标 =====
        xy = colour.XYZ_to_xy(xyz)

        # ===== 8. u,v 及 u',v' =====
        try:
            if hasattr(colour, 'XYZ_to_CIE_1960_uv') and hasattr(colour, 'XYZ_to_CIE_1976_uv'):
                uv = colour.XYZ_to_CIE_1960_uv(xyz)
                uvp = colour.XYZ_to_CIE_1976_uv(xyz)
            elif hasattr(colour, 'XYZ_to_UCS_uv') and hasattr(colour, 'XYZ_to_uvp'):
                uv = colour.XYZ_to_UCS_uv(xyz)
                uvp = colour.XYZ_to_uvp(xyz)
            else:
                # 手动计算公式（通用标准）
                X, Y, Z = xyz
                denom = X + 15 * Y + 3 * Z
                if np.isclose(denom, 0.0):
                    uv = np.array([np.nan, np.nan])
                    uvp = np.array([np.nan, np.nan])
                else:
                    u = (4 * X) / denom
                    v = (6 * Y) / denom
                    uv = np.array([u, v])
                    uvp = np.array([(4 * X) / denom, (9 * Y) / denom])
        except Exception as e:
            print(f"警告: UV 计算失败 ({e})，使用 NaN。")
            uv = np.array([np.nan, np.nan])
            uvp = np.array([np.nan, np.nan])

        # ===== 9. 汇总结果 =====
        results = {
            'X': float(xyz[0]), 'Y': float(xyz[1]), 'Z': float(xyz[2]),
            'x': float(xy[0]), 'y': float(xy[1]),
            'L*': float(lab[0]), 'a*': float(lab[1]), 'b*': float(lab[2]),
            'Hunter L': float(hunter_lab[0]), 'Hunter a': float(hunter_lab[1]), 'Hunter b': float(hunter_lab[2]),
            "u'": float(uvp[0]), "v'": float(uvp[1]),
            'u': float(uv[0]), 'v': float(uv[1]),
        }

        return results

    except Exception as e:
        print(f"色度学计算时发生严重错误: {e}")
        return {}
