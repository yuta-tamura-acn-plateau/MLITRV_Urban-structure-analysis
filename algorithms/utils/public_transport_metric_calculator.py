"""
/***************************************************************************
 *
 * 【FN013】公共交通関連評価指標算出機能
 *
 ***************************************************************************/
"""

import re
import csv
from qgis.core import (
    QgsMessageLog,
    Qgis,
    QgsVectorLayer,
    QgsFeature,
    QgsAggregateCalculator,
)
from PyQt5.QtCore import QCoreApplication
import processing
from .gpkg_manager import GpkgManager


class PublicTransportMetricCalculator:
    """公共交通関連評価指標算出"""
    def __init__(self, base_path, check_canceled_callback=None):
        self.base_path = base_path

        self.check_canceled = check_canceled_callback

        self.gpkg_manager = GpkgManager._instance

    def tr(self, message):
        """翻訳用のメソッド"""
        return QCoreApplication.translate(self.__class__.__name__, message)

    def calc(self):
        """算出処理"""
        try:
            # 建物
            buildings_layer = self.gpkg_manager.load_layer(
                'buildings', None, withload_project=False
            )
            # 都市計画区域
            urbun_plannings_layer = self.gpkg_manager.load_layer(
                'urbun_plannings', None, withload_project=False
            )
            # 用途地域
            land_use_areas_layer = self.gpkg_manager.load_layer(
                'land_use_areas', None, withload_project=False
            )
            # 誘導区域
            induction_layer = self.gpkg_manager.load_layer(
                'induction_areas', None, withload_project=False
            )
            # 鉄道カバー圏域
            railway_station_buffers_layer = self.gpkg_manager.load_layer(
                'railway_station_buffers', None, withload_project=False
            )
            # バスカバー圏域
            bus_stop_buffers_layer = self.gpkg_manager.load_layer(
                'bus_stop_buffers', None, withload_project=False
            )
            # 交通流動
            traffics_layer = self.gpkg_manager.load_layer(
                'traffics', None, withload_project=False
            )

            if not buildings_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                    .replace("%1", "buildings"))
            if not induction_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                    .replace("%1", "induction_areas"))
            if not railway_station_buffers_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                    .replace("%1", "railway_station_buffers"))
            if not bus_stop_buffers_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                    .replace("%1", "bus_stop_buffers"))
            if not traffics_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                    .replace("%1", "traffics"))

            centroid_layer = QgsVectorLayer(
                "Point?crs=" + buildings_layer.crs().authid(),
                "tmp_building_centroids",
                "memory",
            )
            centroid_layer_data = centroid_layer.dataProvider()

            # 元の建物レイヤから属性をコピー
            centroid_layer_data.addAttributes(buildings_layer.fields())
            centroid_layer.updateFields()

            # 建物の重心を計算して一時レイヤに追加
            centroid_features = []
            for building_feature in buildings_layer.getFeatures():
                if self.check_canceled():
                    return  # キャンセルチェック
                centroid_geom = building_feature.geometry().centroid()
                new_feature = QgsFeature()
                new_feature.setGeometry(centroid_geom)
                new_feature.setAttributes(
                    building_feature.attributes()
                )  # 元の属性をコピー
                centroid_features.append(new_feature)

            centroid_layer_data.addFeatures(centroid_features)
            centroid_layer.updateExtents()

            # 空間インデックス作成
            processing.run(
                "native:createspatialindex", {'INPUT': centroid_layer}
            )

            centroid_layer = self.gpkg_manager.add_layer(
                centroid_layer, "tmp_building_centroids", None, False
            )
            if not centroid_layer:
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            # 属性名を取得
            fields = buildings_layer.fields()
            buildings_layer = None

            # 年度情報を取得
            years = set()
            pattern = re.compile(r'^(\d{4})_')

            for field in fields:
                match = pattern.match(field.name())
                if match:
                    years.add(match.group(1))

            # 年度をリスト化してソート
            unique_years = sorted(list(years))

            # データリストを作成
            data_list = []

            # 市内、鉄道カバー圏の建物を取得
            railway_buildings = self.__extract(
                centroid_layer, railway_station_buffers_layer
            )

            # 市内、バスカバー圏の建物を取得
            bus_buildings = self.__extract(
                centroid_layer, bus_stop_buffers_layer
            )

            # 都市計画区域内の建物を取得
            urban_planning_buildings = self.__extract(
                centroid_layer, urbun_plannings_layer
            )
            urbun_plannings_layer = None

            # 都市計画区域内、鉄道カバー圏の建物を取得
            urban_planning_railway_buildings = self.__extract(
                urban_planning_buildings, railway_station_buffers_layer
            )

            # 都市計画区域内、バスカバー圏の建物を取得
            urban_planning_bus_buildings = self.__extract(
                urban_planning_buildings, bus_stop_buffers_layer
            )

            # 居住誘導区域（type_id=31）を取得
            residential_area_layer = QgsVectorLayer(
                "Polygon?crs=" + induction_layer.crs().authid(),
                "residential_area",
                "memory",
            )
            residential_area_data = residential_area_layer.dataProvider()
            residential_area_features = []
            for induction_feature in induction_layer.getFeatures():
                if induction_feature["type_id"] == 31:
                    residential_area_features.append(induction_feature)

            # 新しい一時レイヤに追加
            residential_area_data.addFeatures(residential_area_features)
            residential_area_layer.updateExtents()

            # 居住誘導区域内の建物を取得
            residential_buildings = self.__extract(
                centroid_layer, residential_area_layer
            )
            residential_area_layer = None

            # 居住誘導区域内、鉄道カバー圏の建物を取得
            residential_railway_buildings = self.__extract(
                residential_buildings, railway_station_buffers_layer
            )

            # 居住誘導区域内、バスカバー圏の建物を取得
            residential_bus_buildings = self.__extract(
                residential_buildings, bus_stop_buffers_layer
            )

            # 都市機能誘導区域（type_id=32）を取得
            urban_area_layer = QgsVectorLayer(
                "Polygon?crs=" + induction_layer.crs().authid(),
                "urban_area",
                "memory",
            )
            urban_area_data = urban_area_layer.dataProvider()
            urban_area_features = []
            for induction_feature in induction_layer.getFeatures():
                if induction_feature["type_id"] == 32:
                    urban_area_features.append(induction_feature)

            # 新しい一時レイヤに追加
            urban_area_data.addFeatures(urban_area_features)
            urban_area_layer.updateExtents()

            # 都市機能誘導区域内の建物を取得
            if self.check_canceled():
                return  # キャンセルチェック
            urban_buildings = self.__extract(centroid_layer, urban_area_layer)
            urban_area_layer = None

            # 都市機能誘導区域内、鉄道カバー圏の建物を取得
            if self.check_canceled():
                return  # キャンセルチェック
            urban_railway_buildings = self.__extract(
                urban_buildings, railway_station_buffers_layer
            )

            # 都市機能誘導区域内、バスカバー圏の建物を取得
            if self.check_canceled():
                return  # キャンセルチェック
            urban_bus_buildings = self.__extract(
                urban_buildings, bus_stop_buffers_layer
            )

            # 用途地域内の建物を取得
            if self.check_canceled():
                return  # キャンセルチェック
            land_use_buildings = self.__extract(
                centroid_layer, land_use_areas_layer
            )
            land_use_areas_layer = None

            # 用途地域内、鉄道カバー圏の建物を取得
            if self.check_canceled():
                return  # キャンセルチェック
            land_use_railway_buildings = self.__extract(
                land_use_buildings, railway_station_buffers_layer
            )

            # 用途地域内、バスカバー圏の建物を取得
            if self.check_canceled():
                return  # キャンセルチェック
            land_use_bus_buildings = self.__extract(
                land_use_buildings, bus_stop_buffers_layer
            )

            for year in unique_years:
                if self.check_canceled():
                    return  # キャンセルチェック
                year_field = f"{year}_population"

                # 総人口を集計
                total_pop = self.__aggregate_sum(centroid_layer, year_field)

                # 都市計画区域内の人口
                total_area01_pop = self.__aggregate_sum(
                    urban_planning_buildings, year_field
                )

                # 用途地域内の人口
                total_area02_pop = self.__aggregate_sum(
                    land_use_buildings, year_field
                )

                # 都市機能誘導区域内の人口
                total_area03_pop = self.__aggregate_sum(
                    urban_buildings, year_field
                )

                # 居住誘導区域内の人口
                total_area04_pop = self.__aggregate_sum(
                    residential_buildings, year_field
                )

                if self.check_canceled():
                    return  # キャンセルチェック
                # 鉄道カバー圏人口
                # 市内の鉄道カバー圏人口
                train_area00_pop = self.__aggregate_sum(
                    railway_buildings, year_field
                )
                # 都市計画区域内の鉄道カバー圏人口
                train_area01_pop = self.__aggregate_sum(
                    urban_planning_railway_buildings, year_field
                )
                # 用途地域内の鉄道カバー圏人口
                train_area02_pop = self.__aggregate_sum(
                    land_use_railway_buildings, year_field
                )
                # 都市機能誘導区域内の鉄道カバー圏人口
                train_area03_pop = self.__aggregate_sum(
                    urban_railway_buildings, year_field
                )
                # 居住誘導区域内の鉄道カバー圏人口
                train_area04_pop = self.__aggregate_sum(
                    residential_railway_buildings, year_field
                )

                if self.check_canceled():
                    return  # キャンセルチェック
                # バスカバー圏人口
                # 市内のバスカバー圏人口
                buss_area00_pop = self.__aggregate_sum(
                    bus_buildings, year_field
                )
                # 都市計画区域内のバスカバー圏人口
                buss_area01_pop = self.__aggregate_sum(
                    urban_planning_bus_buildings, year_field
                )
                # 用途地域内のバスカバー圏人口
                buss_area02_pop = self.__aggregate_sum(
                    land_use_bus_buildings, year_field
                )
                # 都市機能誘導区域内のバスカバー圏人口
                buss_area03_pop = self.__aggregate_sum(
                    urban_bus_buildings, year_field
                )
                # 居住誘導区域内のバスカバー圏人口
                buss_area04_pop = self.__aggregate_sum(
                    residential_bus_buildings, year_field
                )

                if self.check_canceled():
                    return  # キャンセルチェック
                # 公共交通カバー圏人口（鉄道 + バス）
                # 市内の公共交通カバー圏人口
                masstra_area00_pop = train_area00_pop + buss_area00_pop
                # 都市計画区域内の公共交通カバー圏人口
                masstra_area01_pop = train_area01_pop + buss_area01_pop
                # 用途地域内の公共交通カバー圏人口
                masstra_area02_pop = train_area02_pop + buss_area02_pop
                # 都市機能誘導区域内の公共交通カバー圏人口
                masstra_area03_pop = train_area03_pop + buss_area03_pop
                # 居住誘導区域内の公共交通カバー圏人口
                masstra_area04_pop = train_area04_pop + buss_area04_pop

                if self.check_canceled():
                    return  # キャンセルチェック
                # 人口割合の計算
                # 市内の鉄道カバー圏人口割合
                rate_train_area00_pop = (
                    (train_area00_pop / total_pop) * 100
                    if total_pop > 0
                    else '―'
                )
                # 市内のバスカバー圏人口割合
                rate_buss_area00_pop = (
                    (buss_area00_pop / total_pop) * 100
                    if total_pop > 0
                    else '―'
                )
                # 市内の公共交通カバー圏人口割合
                rate_masstra_area00_pop = (
                    (masstra_area00_pop / total_pop) * 100
                    if total_pop > 0
                    else '―'
                )

                if self.check_canceled():
                    return  # キャンセルチェック
                # 都市計画区域内の鉄道カバー圏人口割合
                rate_train_area01_pop = (
                    (train_area01_pop / total_area01_pop) * 100
                    if total_area01_pop > 0
                    else '―'
                )
                # 都市計画区域内のバスカバー圏人口割合
                rate_buss_area01_pop = (
                    (buss_area01_pop / total_area01_pop) * 100
                    if total_area01_pop > 0
                    else '―'
                )
                # 都市計画区域内の公共交通カバー圏人口割合
                rate_masstra_area01_pop = (
                    (masstra_area01_pop / total_area01_pop) * 100
                    if total_area01_pop > 0
                    else '―'
                )

                if self.check_canceled():
                    return  # キャンセルチェック
                # 用途地域内の鉄道カバー圏人口割合
                rate_train_area02_pop = (
                    (train_area02_pop / total_area02_pop) * 100
                    if total_area02_pop > 0
                    else '―'
                )
                # 用途地域内のバスカバー圏人口割合
                rate_buss_area02_pop = (
                    (buss_area02_pop / total_area02_pop) * 100
                    if total_area02_pop > 0
                    else '―'
                )
                # 用途地域内の公共交通カバー圏人口割合
                rate_masstra_area02_pop = (
                    (masstra_area02_pop / total_area02_pop) * 100
                    if total_area02_pop > 0
                    else '―'
                )

                if self.check_canceled():
                    return  # キャンセルチェック
                # 都市機能誘導区域内の鉄道カバー圏人口割合
                rate_train_area03_pop = (
                    (train_area03_pop / total_area03_pop) * 100
                    if total_area03_pop > 0
                    else '―'
                )
                # 都市機能誘導区域内のバスカバー圏人口割合
                rate_buss_area03_pop = (
                    (buss_area03_pop / total_area03_pop) * 100
                    if total_area03_pop > 0
                    else '―'
                )
                # 都市機能誘導区域内の公共交通カバー圏人口割合
                rate_masstra_area03_pop = (
                    (masstra_area03_pop / total_area03_pop) * 100
                    if total_area03_pop > 0
                    else '―'
                )

                if self.check_canceled():
                    return  # キャンセルチェック
                # 居住誘導区域内の鉄道カバー圏人口割合
                rate_train_area04_pop = (
                    (train_area04_pop / total_area04_pop) * 100
                    if total_area04_pop > 0
                    else '―'
                )
                # 居住誘導区域内のバスカバー圏人口割合
                rate_buss_area04_pop = (
                    (buss_area04_pop / total_area04_pop) * 100
                    if total_area04_pop > 0
                    else '―'
                )
                # 居住誘導区域内の公共交通カバー圏人口割合
                rate_masstra_area04_pop = (
                    (masstra_area04_pop / total_area04_pop) * 100
                    if total_area04_pop > 0
                    else '―'
                )

                # 交通流動
                condition = f"survey_year = {year}"
                total = self.__aggregate_sum(
                    traffics_layer, 'total_trip_count', condition
                )
                train = self.__aggregate_sum(
                    traffics_layer, 'rail_total_trip_count', condition
                )
                bus = self.__aggregate_sum(
                    traffics_layer, 'bus_total_trip_count', condition
                )

                if total > 0:
                    # 公共交通分担率
                    share_public_transportation = ((train + bus) / total) * 100
                    # 公共交通分担率（鉄道）
                    share_public_transportation_train = (train / total) * 100
                    # 公共交通分担率（バス）
                    share_public_transportation_bus = (bus / total) * 100
                else:
                    share_public_transportation = '―'
                    share_public_transportation_train = '―'
                    share_public_transportation_bus = '―'

                # 前年度のデータがあれば、変化率を計算
                if data_list:
                    previous_year_data = data_list[-1]

                    # 都市計画区域内の鉄道カバー圏人口割合の変化率
                    if isinstance(
                        rate_train_area01_pop, (int, float)
                    ) and isinstance(
                        previous_year_data['Rate_Train_Area01_Pop'],
                        (int, float),
                    ):
                        rate_train_area01_pop_change = (
                            self.round_or_na(
                                (
                                    (
                                        rate_train_area01_pop
                                        - previous_year_data[
                                            'Rate_Train_Area01_Pop'
                                        ]
                                    )
                                    / previous_year_data[
                                        'Rate_Train_Area01_Pop'
                                    ]
                                )
                                * 100,
                                1,
                            )
                            if previous_year_data['Rate_Train_Area01_Pop'] > 0
                            else '―'
                        )
                    else:
                        rate_train_area01_pop_change = '―'

                    # 都市計画区域内のバスカバー圏人口割合の変化率
                    if isinstance(
                        rate_buss_area01_pop, (int, float)
                    ) and isinstance(
                        previous_year_data['Rate_Buss_Area01_Pop'], (
                            int, float)
                    ):
                        rate_buss_area01_pop_change = (
                            self.round_or_na(
                                (
                                    (
                                        rate_buss_area01_pop
                                        - previous_year_data[
                                            'Rate_Buss_Area01_Pop'
                                        ]
                                    )
                                    / previous_year_data['Rate_Buss_Area01_Pop']
                                )
                                * 100,
                                1,
                            )
                            if previous_year_data['Rate_Buss_Area01_Pop'] > 0
                            else '―'
                        )
                    else:
                        rate_buss_area01_pop_change = '―'

                    # 都市計画区域内の公共交通カバー圏人口割合の変化率
                    if isinstance(
                        rate_masstra_area01_pop, (int, float)
                    ) and isinstance(
                        previous_year_data['Rate_MassTra_Area01_Pop'],
                        (int, float),
                    ):
                        rate_masstra_area01_pop_change = (
                            self.round_or_na(
                                (
                                    (
                                        rate_masstra_area01_pop
                                        - previous_year_data[
                                            'Rate_MassTra_Area01_Pop'
                                        ]
                                    )
                                    / previous_year_data[
                                        'Rate_MassTra_Area01_Pop'
                                    ]
                                )
                                * 100,
                                1,
                            )
                            if previous_year_data['Rate_MassTra_Area01_Pop'] > 0
                            else '―'
                        )
                    else:
                        rate_masstra_area01_pop_change = '―'

                    # 用途地域内の鉄道カバー圏人口割合の変化率
                    if isinstance(
                        rate_train_area02_pop, (int, float)
                    ) and isinstance(
                        previous_year_data['Rate_Train_Area02_Pop'],
                        (int, float),
                    ):
                        rate_train_area02_pop_change = (
                            self.round_or_na(
                                (
                                    (
                                        rate_train_area02_pop
                                        - previous_year_data[
                                            'Rate_Train_Area02_Pop'
                                        ]
                                    )
                                    / previous_year_data[
                                        'Rate_Train_Area02_Pop'
                                    ]
                                )
                                * 100,
                                1,
                            )
                            if previous_year_data['Rate_Train_Area02_Pop'] > 0
                            else '―'
                        )
                    else:
                        rate_train_area02_pop_change = '―'

                    # 用途地域内のバスカバー圏人口割合の変化率
                    if isinstance(
                        rate_buss_area02_pop, (int, float)
                    ) and isinstance(
                        previous_year_data['Rate_Buss_Area02_Pop'], (
                            int, float)
                    ):
                        rate_buss_area02_pop_change = (
                            self.round_or_na(
                                (
                                    (
                                        rate_buss_area02_pop
                                        - previous_year_data[
                                            'Rate_Buss_Area02_Pop'
                                        ]
                                    )
                                    / previous_year_data['Rate_Buss_Area02_Pop']
                                )
                                * 100,
                                1,
                            )
                            if previous_year_data['Rate_Buss_Area02_Pop'] > 0
                            else '―'
                        )
                    else:
                        rate_buss_area02_pop_change = '―'

                    # 用途地域内の公共交通カバー圏人口割合の変化率
                    if isinstance(
                        rate_masstra_area02_pop, (int, float)
                    ) and isinstance(
                        previous_year_data['Rate_MassTra_Area02_Pop'],
                        (int, float),
                    ):
                        rate_masstra_area02_pop_change = (
                            self.round_or_na(
                                (
                                    (
                                        rate_masstra_area02_pop
                                        - previous_year_data[
                                            'Rate_MassTra_Area02_Pop'
                                        ]
                                    )
                                    / previous_year_data[
                                        'Rate_MassTra_Area02_Pop'
                                    ]
                                )
                                * 100,
                                1,
                            )
                            if previous_year_data['Rate_MassTra_Area02_Pop'] > 0
                            else '―'
                        )
                    else:
                        rate_masstra_area02_pop_change = '―'

                    # 都市機能誘導区域内の鉄道カバー圏人口割合の変化率
                    if isinstance(
                        rate_train_area03_pop, (int, float)
                    ) and isinstance(
                        previous_year_data['Rate_Train_Area03_Pop'],
                        (int, float),
                    ):
                        rate_train_area03_pop_change = (
                            self.round_or_na(
                                (
                                    (
                                        rate_train_area03_pop
                                        - previous_year_data[
                                            'Rate_Train_Area03_Pop'
                                        ]
                                    )
                                    / previous_year_data[
                                        'Rate_Train_Area03_Pop'
                                    ]
                                )
                                * 100,
                                1,
                            )
                            if previous_year_data['Rate_Train_Area03_Pop'] > 0
                            else '―'
                        )
                    else:
                        rate_train_area03_pop_change = '―'

                    # 都市機能誘導区域内のバスカバー圏人口割合の変化率
                    if isinstance(
                        rate_buss_area03_pop, (int, float)
                    ) and isinstance(
                        previous_year_data['Rate_Buss_Area03_Pop'], (
                            int, float)
                    ):
                        rate_buss_area03_pop_change = (
                            self.round_or_na(
                                (
                                    (
                                        rate_buss_area03_pop
                                        - previous_year_data[
                                            'Rate_Buss_Area03_Pop'
                                        ]
                                    )
                                    / previous_year_data['Rate_Buss_Area03_Pop']
                                )
                                * 100,
                                1,
                            )
                            if previous_year_data['Rate_Buss_Area03_Pop'] > 0
                            else '―'
                        )
                    else:
                        rate_buss_area03_pop_change = '―'

                    # 都市機能誘導区域内の公共交通カバー圏人口割合の変化率
                    if isinstance(
                        rate_masstra_area03_pop, (int, float)
                    ) and isinstance(
                        previous_year_data['Rate_MassTra_Area03_Pop'],
                        (int, float),
                    ):
                        rate_masstra_area03_pop_change = (
                            self.round_or_na(
                                (
                                    (
                                        rate_masstra_area03_pop
                                        - previous_year_data[
                                            'Rate_MassTra_Area03_Pop'
                                        ]
                                    )
                                    / previous_year_data[
                                        'Rate_MassTra_Area03_Pop'
                                    ]
                                )
                                * 100,
                                1,
                            )
                            if previous_year_data['Rate_MassTra_Area03_Pop'] > 0
                            else '―'
                        )
                    else:
                        rate_masstra_area03_pop_change = '―'

                    # 居住誘導区域内の鉄道カバー圏人口割合の変化率
                    if isinstance(
                        rate_train_area04_pop, (int, float)
                    ) and isinstance(
                        previous_year_data['Rate_Train_Area04_Pop'],
                        (int, float),
                    ):
                        rate_train_area04_pop_change = (
                            self.round_or_na(
                                (
                                    (
                                        rate_train_area04_pop
                                        - previous_year_data[
                                            'Rate_Train_Area04_Pop'
                                        ]
                                    )
                                    / previous_year_data[
                                        'Rate_Train_Area04_Pop'
                                    ]
                                )
                                * 100,
                                1,
                            )
                            if previous_year_data['Rate_Train_Area04_Pop'] > 0
                            else '―'
                        )
                    else:
                        rate_train_area04_pop_change = '―'

                    # 居住誘導区域内のバスカバー圏人口割合の変化率
                    if isinstance(
                        rate_buss_area04_pop, (int, float)
                    ) and isinstance(
                        previous_year_data['Rate_Buss_Area04_Pop'], (
                            int, float)
                    ):
                        rate_buss_area04_pop_change = (
                            self.round_or_na(
                                (
                                    (
                                        rate_buss_area04_pop
                                        - previous_year_data[
                                            'Rate_Buss_Area04_Pop'
                                        ]
                                    )
                                    / previous_year_data['Rate_Buss_Area04_Pop']
                                )
                                * 100,
                                1,
                            )
                            if previous_year_data['Rate_Buss_Area04_Pop'] > 0
                            else '―'
                        )
                    else:
                        rate_buss_area04_pop_change = '―'

                    # 居住誘導区域内の公共交通カバー圏人口割合の変化率
                    if isinstance(
                        rate_masstra_area04_pop, (int, float)
                    ) and isinstance(
                        previous_year_data['Rate_MassTra_Area04_Pop'],
                        (int, float),
                    ):
                        rate_masstra_area04_pop_change = (
                            self.round_or_na(
                                (
                                    (
                                        rate_masstra_area04_pop
                                        - previous_year_data[
                                            'Rate_MassTra_Area04_Pop'
                                        ]
                                    )
                                    / previous_year_data[
                                        'Rate_MassTra_Area04_Pop'
                                    ]
                                )
                                * 100,
                                1,
                            )
                            if previous_year_data['Rate_MassTra_Area04_Pop'] > 0
                            else '―'
                        )
                    else:
                        rate_masstra_area04_pop_change = '―'

                else:
                    rate_train_area01_pop_change = '―'
                    rate_buss_area01_pop_change = '―'
                    rate_masstra_area01_pop_change = '―'
                    rate_train_area02_pop_change = '―'
                    rate_buss_area02_pop_change = '―'
                    rate_masstra_area02_pop_change = '―'
                    rate_train_area03_pop_change = '―'
                    rate_buss_area03_pop_change = '―'
                    rate_masstra_area03_pop_change = '―'
                    rate_train_area04_pop_change = '―'
                    rate_buss_area04_pop_change = '―'
                    rate_masstra_area04_pop_change = '―'

                # データを辞書にまとめる
                year_data = {
                    # 年度
                    'Year': year,
                    # 市内総人口
                    'Total_Pop': total_pop,
                    # 市内の鉄道カバー圏人口
                    'Train_Area00_Pop': train_area00_pop,
                    # 市内のバスカバー圏人口
                    'Buss_Area00_Pop': buss_area00_pop,
                    # 市内の公共交通カバー圏人口
                    'MassTra_Area00_Pop': masstra_area00_pop,
                    # 都市計画区域内の人口
                    'Total_Area01_Pop': total_area01_pop,
                    # 都市計画区域内の鉄道カバー圏人口
                    'Train_Area01_Pop': train_area01_pop,
                    # 都市計画区域内のバスカバー圏人口
                    'Buss_Area01_Pop': buss_area01_pop,
                    # 都市計画区域内の公共交通カバー圏人口
                    'MassTra_Area01_Pop': masstra_area01_pop,
                    # 用途地域内の人口
                    'Total_Area02_Pop': total_area02_pop,
                    # 用途地域内の鉄道カバー圏人口
                    'Train_Area02_Pop': train_area02_pop,
                    # 用途地域内のバスカバー圏人口
                    'Buss_Area02_Pop': buss_area02_pop,
                    # 用途地域内の公共交通カバー圏人口
                    'MassTra_Area02_Pop': masstra_area02_pop,
                    # 都市機能誘導区域内の人口
                    'Total_Area03_Pop': total_area03_pop,
                    # 都市機能誘導区域内の鉄道カバー圏人口
                    'Train_Area03_Pop': train_area03_pop,
                    # 都市機能誘導区域内のバスカバー圏人口
                    'Buss_Area03_Pop': buss_area03_pop,
                    # 都市機能誘導区域内の公共交通カバー圏人口
                    'MassTra_Area03_Pop': masstra_area03_pop,
                    # 居住誘導区域内の人口
                    'Total_Area04_Pop': total_area04_pop,
                    # 居住誘導区域内の鉄道カバー圏人口
                    'Train_Area04_Pop': train_area04_pop,
                    # 居住誘導区域内のバスカバー圏人口
                    'Buss_Area04_Pop': buss_area04_pop,
                    # 居住誘導区域内の公共交通カバー圏人口
                    'MassTra_Area04_Pop': masstra_area04_pop,
                    # 市内の鉄道カバー圏人口割合
                    'Rate_Train_Area00_Pop': rate_train_area00_pop,
                    # 市内のバスカバー圏人口割合
                    'Rate_Buss_Area00_Pop': rate_buss_area00_pop,
                    # 市内の公共交通カバー圏人口割合
                    'Rate_MassTra_Area00_Pop': rate_masstra_area00_pop,
                    # 都市計画区域内の鉄道カバー圏人口割合
                    'Rate_Train_Area01_Pop': rate_train_area01_pop,
                    # 都市計画区域内のバスカバー圏人口割合
                    'Rate_Buss_Area01_Pop': rate_buss_area01_pop,
                    # 都市計画区域内の公共交通カバー圏人口割合
                    'Rate_MassTra_Area01_Pop': rate_masstra_area01_pop,
                    # 用途地域内の鉄道カバー圏人口割合
                    'Rate_Train_Area02_Pop': rate_train_area02_pop,
                    # 用途地域内のバスカバー圏人口割合
                    'Rate_Buss_Area02_Pop': rate_buss_area02_pop,
                    # 用途地域内の公共交通カバー圏人口割合
                    'Rate_MassTra_Area02_Pop': rate_masstra_area02_pop,
                    # 都市機能誘導区域内の鉄道カバー圏人口割合
                    'Rate_Train_Area03_Pop': rate_train_area03_pop,
                    # 都市機能誘導区域内のバスカバー圏人口割合
                    'Rate_Buss_Area03_Pop': rate_buss_area03_pop,
                    # 都市機能誘導区域内の公共交通カバー圏人口割合
                    'Rate_MassTra_Area03_Pop': rate_masstra_area03_pop,
                    # 居住誘導区域内の鉄道カバー圏人口割合
                    'Rate_Train_Area04_Pop': rate_train_area04_pop,
                    # 居住誘導区域内のバスカバー圏人口割合
                    'Rate_Buss_Area04_Pop': rate_buss_area04_pop,
                    # 居住誘導区域内の公共交通カバー圏人口割合
                    'Rate_MassTra_Area04_Pop': rate_masstra_area04_pop,
                    # 都市計画区域内の鉄道カバー圏人口割合の変化率
                    'Rate_Train_Area01_Pop_Change': rate_train_area01_pop_change,
                    # 都市計画区域内のバスカバー圏人口割合の変化率
                    'Rate_Buss_Area01_Pop_Change': rate_buss_area01_pop_change,
                    # 都市計画区域内の公共交通カバー圏人口割合の変化率
                    'Rate_MassTra_Area01_Pop_Change': rate_masstra_area01_pop_change,
                    # 用途地域内の鉄道カバー圏人口割合の変化率
                    'Rate_Train_Area02_Pop_Change': rate_train_area02_pop_change,
                    # 用途地域内のバスカバー圏人口割合の変化率
                    'Rate_Buss_Area02_Pop_Change': rate_buss_area02_pop_change,
                    # 用途地域内の公共交通カバー圏人口割合の変化率
                    'Rate_MassTra_Area02_Pop_Change': rate_masstra_area02_pop_change,
                    # 都市機能誘導区域内の鉄道カバー圏人口割合の変化率
                    'Rate_Train_Area03_Pop_Change': rate_train_area03_pop_change,
                    # 都市機能誘導区域内のバスカバー圏人口割合の変化率
                    'Rate_Buss_Area03_Pop_Change': rate_buss_area03_pop_change,
                    # 都市機能誘導区域内の公共交通カバー圏人口割合の変化率
                    'Rate_MassTra_Area03_Pop_Change': rate_masstra_area03_pop_change,
                    # 居住誘導区域内の鉄道カバー圏人口割合の変化率
                    'Rate_Train_Area04_Pop_Change': rate_train_area04_pop_change,
                    # 居住誘導区域内のバスカバー圏人口割合の変化率
                    'Rate_Buss_Area04_Pop_Change': rate_buss_area04_pop_change,
                    # 居住誘導区域内の公共交通カバー圏人口割合の変化率
                    'Rate_MassTra_Area04_Pop_Change': rate_masstra_area04_pop_change,
                    # 公共交通分担率
                    'Share_Public_Transportation': share_public_transportation,
                    # 公共交通分担率（鉄道）
                    'Share_Public_Transportation_Train': share_public_transportation_train,
                    # 公共交通分担率（バス）
                    'Share_Public_Transportation_Bus': share_public_transportation_bus,
                }

                # 辞書をリストに追加
                data_list.append(year_data)

            # ファイルパスを指定してエクスポート
            self.export(
                self.base_path + '\\IF104_公共交通関連評価指標ファイル.csv',
                data_list,
            )

            return

        except Exception as e:
            # エラーメッセージのログ出力
            QgsMessageLog.logMessage(
                self.tr("An error occurred: %1").replace("%1", e),
                self.tr("Plugin"),
                Qgis.Critical,
            )
            raise e

    def export(self, file_path, data):
        """エクスポート処理"""
        try:
            if not data:
                raise Exception(self.tr("The data to export is empty."))

            # データ項目からヘッダーを取得
            headers = list(data[0].keys())

            # CSVファイル書き込み
            with open(
                file_path, mode='w', newline='', encoding='utf-8'
            ) as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=headers)
                writer.writeheader()

                for row in data:
                    writer.writerow(row)

            msg = self.tr(
                "File export completed: %1."
            ).replace("%1", file_path)
            QgsMessageLog.logMessage(
                msg,
                self.tr("Plugin"),
                Qgis.Info,
            )
            return True
        except Exception as e:
            # エラーメッセージのログ出力
            msg = self.tr(
                "An error occurred during file export: %1."
            ).replace("%1", e)
            QgsMessageLog.logMessage(
                msg,
                self.tr("Plugin"),
                Qgis.Critical,
            )
            raise e

    def round_or_na(self, value, decimal_places, threshold=None):
        """丸め処理"""
        if value is None or (threshold is not None and value <= threshold):
            return '―'
        else:
            return round(value, decimal_places)

    def __extract(self, target_layer, buffer_layer):
        """バッファレイヤ内に存在するフィーチャを抽出"""
        # 空間インデックスの作成
        processing.run("native:createspatialindex", {'INPUT': target_layer})
        processing.run("native:createspatialindex", {'INPUT': buffer_layer})

        # バッファ内のフィーチャを抽出
        result = processing.run(
            "native:extractbylocation",
            {
                'INPUT': target_layer,
                'PREDICATE': [6],  # within
                'INTERSECT': buffer_layer,
                'OUTPUT': 'TEMPORARY_OUTPUT',
            },
        )['OUTPUT']

        return result

    def __aggregate_sum(self, target_layer, sum_field, condition=None):
        """
        条件に基づいて集計を行う
        :param target_layer: 対象のレイヤ
        :param sum_field: 集計するフィールド名
        :param condition: フィルタリングする条件 (QgsExpression 形式の条件式)
        :return: 集計結果
        """
        # 条件がある場合はフィルタリング
        if condition is not None:
            # フィルタリングされたレイヤを作成
            target_layer.setSubsetString(condition)

        # 集計
        result = target_layer.aggregate(
            QgsAggregateCalculator.Aggregate.Sum, sum_field
        )
        result = int(result[0]) if result[0] is not None else 0

        # フィルタ解除
        if condition is not None:
            target_layer.setSubsetString('')

        return result
