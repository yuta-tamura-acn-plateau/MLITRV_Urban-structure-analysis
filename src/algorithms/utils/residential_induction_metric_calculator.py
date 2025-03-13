"""
/***************************************************************************
 *
 * 【FN010】居住誘導関連評価指標算出機能
 *
 ***************************************************************************/
"""

import re
import csv
from qgis.core import (
    QgsMessageLog,
    Qgis,
    QgsAggregateCalculator,
    QgsVectorLayer,
    QgsFeature,
    QgsCoordinateReferenceSystem,
)
from PyQt5.QtCore import QCoreApplication
import processing
from .gpkg_manager import GpkgManager


class ResidentialInductionMetricCalculator:
    """居住誘導関連評価指標算出機能"""
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
            # 誘導区域
            induction_layer = self.gpkg_manager.load_layer(
                'induction_areas', None, withload_project=False
            )
            # 目標人口
            population_target_settings_layer = self.gpkg_manager.load_layer(
                'population_target_settings', None, withload_project=False
            )

            if not buildings_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                    .replace("%1", "buildings"))

            if not induction_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                    .replace("%1", "induction_areas"))

            if not population_target_settings_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                    .replace("%1", "population_target_settings"))

            comparative_year = None
            target_population = None

            feature = next(
                population_target_settings_layer.getFeatures(), None)
            if feature:
                comparative_year = feature['comparative_year']
                target_population = feature['target_population']

                msg = self.tr(
                    "Comparative future year: %1, Target population: %2"
                ).replace("%1", str(comparative_year)).replace(
                    "%2", str(target_population)
                )
                QgsMessageLog.logMessage(
                    msg,
                    self.tr("Plugin"),
                    Qgis.Info,
                )
            else:
                msg = self.tr("Target population data was not found.")
                QgsMessageLog.logMessage(
                    msg,
                    self.tr("Plugin"),
                    Qgis.Warning,
                )

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

            # 空間インデックス作成
            processing.run(
                "native:createspatialindex", {'INPUT': residential_area_layer}
            )

            # CRS変換先（EPSG:3857）
            crs_dest = QgsCoordinateReferenceSystem(
                3857
            )  # メートル単位の座標系 (EPSG:3857)

            # CRS変換
            transformed_layer = processing.run(
                "native:reprojectlayer",
                {
                    'INPUT': induction_layer,
                    'TARGET_CRS': crs_dest,
                    'OUTPUT': 'memory:',  # メモリーレイヤとして変換後のレイヤを保持
                },
            )['OUTPUT']

            # 面積計算
            area = 0  # 居住誘導区域の面積(ha)
            outside_area = 0  # 立地適正化計画区域の面積(ha)

            for induction_feature in transformed_layer.getFeatures():
                # 居住誘導区域（type_id=31）
                if induction_feature["type_id"] == 31:
                    # 面積計算 (ヘクタール単位へ変換: 1ヘクタール = 10,000平方メートル)
                    area += induction_feature.geometry().area() / 10000

                # 立地適正化計画区域（type_id=0）
                if induction_feature["type_id"] == 0:
                    # 面積計算 (ヘクタール単位へ変換)
                    outside_area += induction_feature.geometry().area() / 10000

            area = self.round_or_na(area, 1)
            outside_area = self.round_or_na(outside_area, 1)

            # 居住誘導区域内の建物を取得
            result = processing.run(
                "native:joinattributesbylocation",
                {
                    'INPUT': centroid_layer,
                    'JOIN': residential_area_layer,
                    'PREDICATE': [5],  # overlap
                    'JOIN_FIELDS': [],
                    'METHOD': 0,
                    'OUTPUT': 'TEMPORARY_OUTPUT',
                    'DISCARD_NONMATCHING': True,
                    'PREFIX': 'induction_area_',
                },
            )

            # 結合結果の取得
            residential_buildings = result['OUTPUT']

            for i, year in enumerate(unique_years):
                if self.check_canceled():
                    return  # キャンセルチェック
                area_pop = 0
                outside_area_pop = 0

                year_field = f"{year}_population"

                # 総人口を集計
                total_pop_result = buildings_layer.aggregate(
                    QgsAggregateCalculator.Aggregate.Sum,
                    year_field,
                    QgsAggregateCalculator.AggregateParameters(),
                )
                total_pop = (
                    int(total_pop_result[0])
                    if total_pop_result[0] is not None
                    else 0
                )

                # SUMフィールドの確認
                sum_field_name = f"{year_field}"  # フィールド名
                sum_field_index = residential_buildings.fields().indexFromName(
                    sum_field_name
                )

                # フィールドが存在するか確認
                if sum_field_index == -1:
                    raise Exception(
                        f"集計フィールド {sum_field_name} が見つかりません"
                    )

                # 居住誘導区域内人口
                sum_result = residential_buildings.aggregate(
                    QgsAggregateCalculator.Aggregate.Sum,
                    sum_field_name,
                    QgsAggregateCalculator.AggregateParameters(),
                )
                area_pop = (
                    int(sum_result[0]) if sum_result[0] is not None else 0
                )

                # 居住誘導区域外人口
                outside_area_pop = total_pop - area_pop

                # 居住誘導区域内人口割合（Rate_Pop）と居住誘導区域外人口割合（Outside TheArea_Rate_Pop）
                rate_pop = (
                    self.round_or_na((area_pop / total_pop) * 100, 2)
                    if total_pop > 0
                    else 0
                )
                outside_rate_pop = (
                    self.round_or_na((outside_area_pop / total_pop) * 100, 2)
                    if total_pop > 0
                    else 0
                )

                # 居住誘導区域内と外の人口密度を計算
                pop_area_density = (
                    self.round_or_na(area_pop / area, 2) if area > 0 else '―'
                )  # haあたりの人口密度
                pop_outside_area_density = (
                    self.round_or_na(outside_area_pop / outside_area, 2)
                    if outside_area > 0
                    else '―'
                )

                # 各年齢層のフィールド名を設定
                age_fields = {
                    "Age0-14s": f"{year}_age_0_14",
                    "Age15-64s": f"{year}_age_15_64",
                    "Age65AndOver": f"{year}_age_65_",
                    "Age75AndOver": f"{year}_age_75_total",
                    "Age85AndOver": f"{year}_age_85_total",
                    "Age95AndOver": f"{year}_age_95_total",
                }

                area_pop_by_age = {}
                rate_pop_by_age = {}
                density_pop_by_age = {}
                for age_key, age_field in age_fields.items():
                    # 各年齢層の人口関連計算
                    # 人口
                    age_pop_result = residential_buildings.aggregate(
                        QgsAggregateCalculator.Aggregate.Sum,
                        age_field,
                        QgsAggregateCalculator.AggregateParameters(),
                    )
                    area_pop_by_age[f"Pop_Area_{age_key}"] = (
                        int(age_pop_result[0])
                        if age_pop_result[0] is not None
                        else 0
                    )
                    # 人口割合
                    rate_pop_by_age[f"Rate_Pop_Area_{age_key}"] = (
                        self.round_or_na(
                            (area_pop_by_age[f"Pop_Area_{age_key}"] / total_pop)
                            * 100,
                            2,
                        )
                        if total_pop > 0
                        else '―'
                    )
                    # 人口密度
                    density_pop_by_age[f"Rate_Pop_Area_Density_{age_key}"] = (
                        self.round_or_na(
                            area_pop_by_age[f"Pop_Area_{age_key}"] / area, 1
                        )
                        if area > 0
                        else '―'
                    )

                # 前年度のデータがあれば、変化率を計算
                if data_list:
                    # 前年度のデータを取得
                    previous_year_data = data_list[-1]
                    previous_total_pop = previous_year_data['Total_Pop']
                    # 前年度の居住誘導区域内人口割合を取得
                    previous_rate_pop = previous_year_data['Rate_Pop']
                    # 前年度の居住誘導区域内の人口密度
                    previous_pop_area_density = previous_year_data[
                        'Pop_Area_Density'
                    ]
                    # 前年度の居住誘導区域外の人口密度
                    previous_pop_outside_area_density = previous_year_data[
                        'Pop_Outside TheArea_Density'
                    ]

                    # 総人口の変化率を計算
                    if isinstance(total_pop, (int, float)) and isinstance(
                        previous_total_pop, (int, float)
                    ):
                        rate_pop_change = (
                            self.round_or_na(
                                (
                                    (total_pop - previous_total_pop)
                                    / previous_total_pop
                                )
                                * 100,
                                1,
                            )
                            if previous_total_pop > 0
                            else '―'
                        )
                    else:
                        rate_pop_change = '―'

                    # 居住誘導区域内人口割合の変化率を計算
                    if isinstance(rate_pop, (int, float)) and isinstance(
                        previous_rate_pop, (int, float)
                    ):
                        rate_area_pop_change = (
                            self.round_or_na(
                                (
                                    (rate_pop - previous_rate_pop)
                                    / previous_rate_pop
                                )
                                * 100,
                                1,
                            )
                            if previous_rate_pop > 0
                            else '―'
                        )
                    else:
                        rate_area_pop_change = '―'

                    # 居住誘導区域内人口密度の変化率
                    if isinstance(
                        pop_area_density, (int, float)
                    ) and isinstance(previous_pop_area_density, (int, float)):
                        rate_density_change = (
                            self.round_or_na(
                                (
                                    (
                                        pop_area_density
                                        - previous_pop_area_density
                                    )
                                    / previous_pop_area_density
                                )
                                * 100,
                                1,
                            )
                            if previous_pop_area_density > 0
                            else '―'
                        )
                    else:
                        rate_density_change = '―'

                    # 居住誘導区域外人口密度の変化率
                    if isinstance(
                        pop_outside_area_density, (int, float)
                    ) and isinstance(
                        previous_pop_outside_area_density, (int, float)
                    ):
                        pop_outside_rate_density_change = (
                            self.round_or_na(
                                (
                                    (
                                        pop_outside_area_density
                                        - previous_pop_outside_area_density
                                    )
                                    / previous_pop_outside_area_density
                                )
                                * 100,
                                1,
                            )
                            if previous_pop_outside_area_density > 0
                            else '―'
                        )
                    else:
                        pop_outside_rate_density_change = '―'

                    # 各年齢層の人口割合の変化率と人口密度の変化率
                    rate_pop_area_change_by_age = {}
                    rate_pop_area_density_change_by_age = {}
                    for age_key in age_fields.keys():

                        # 前年度の人口割合を取得
                        previous_rate_pop_by_age = previous_year_data.get(
                            f"Rate_Pop_Area_{age_key}", 0
                        )
                        current_rate_pop_by_age = rate_pop_by_age.get(
                            f"Rate_Pop_Area_{age_key}", 0
                        )

                        # 人口割合の変化率を計算
                        if isinstance(
                            current_rate_pop_by_age, (int, float)
                        ) and isinstance(
                            previous_rate_pop_by_age, (int, float)
                        ):
                            rate_pop_area_change_by_age[
                                f"Rate_Pop_Area_Change_{age_key}"
                            ] = (
                                self.round_or_na(
                                    (
                                        (
                                            current_rate_pop_by_age
                                            - previous_rate_pop_by_age
                                        )
                                        / previous_rate_pop_by_age
                                    )
                                    * 100,
                                    1,
                                )
                                if previous_rate_pop_by_age > 0
                                else '―'
                            )
                        else:
                            rate_pop_area_change_by_age[
                                f"Rate_Pop_Area_Change_{age_key}"
                            ] = '―'

                        # 前年度の人口密度を取得
                        previous_pop_area_density_by_age = (
                            previous_year_data.get(
                                f"Rate_Pop_Area_Density_{age_key}", 0
                            )
                        )
                        current_density_pop_by_age = density_pop_by_age.get(
                            f"Rate_Pop_Area_Density_{age_key}", 0
                        )

                        # 人口密度の変化率を計算
                        if isinstance(
                            current_density_pop_by_age, (int, float)
                        ) and isinstance(
                            previous_pop_area_density_by_age, (int, float)
                        ):
                            rate_pop_area_density_change_by_age[
                                f"Rate_Pop_Area_Change_Density_{age_key}"
                            ] = (
                                self.round_or_na(
                                    (
                                        (
                                            current_density_pop_by_age
                                            - previous_pop_area_density_by_age
                                        )
                                        / previous_pop_area_density_by_age
                                    )
                                    * 100,
                                    1,
                                )
                                if previous_pop_area_density_by_age > 0
                                else '―'
                            )
                        else:
                            rate_pop_area_density_change_by_age[
                                f"Rate_Pop_Area_Change_Density_{age_key}"
                            ] = '―'

                else:
                    rate_pop_change = '―'
                    rate_area_pop_change = '―'
                    rate_density_change = '―'
                    pop_outside_rate_density_change = '―'

                    rate_pop_area_change_by_age = {
                        f"Rate_Pop_Area_Change_{age_key}": '―'
                        for age_key in age_fields.keys()
                    }
                    rate_pop_area_density_change_by_age = {
                        f"Rate_Pop_Area_Change_Density_{age_key}": '―'
                        for age_key in age_fields.keys()
                    }

                # 最後の年度だけ将来人口関連の計算を行う
                if i == len(unique_years) - 1:
                    # 居住誘導区域内将来人口差（p）
                    sum_result = residential_buildings.aggregate(
                        QgsAggregateCalculator.Aggregate.Sum,
                        f"future_{comparative_year}_PT0",
                        QgsAggregateCalculator.AggregateParameters(),
                    )
                    future_area_pop = (
                        int(sum_result[0]) if sum_result[0] is not None else 0
                    )

                    # 現況人口と将来人口から、居住誘導区域内の減少人口：p を求める
                    area_pop_difference = area_pop - future_area_pop

                    # 市内将来人口
                    sum_result = buildings_layer.aggregate(
                        QgsAggregateCalculator.Aggregate.Sum,
                        f"future_{comparative_year}_PT0",
                        QgsAggregateCalculator.AggregateParameters(),
                    )
                    future_total_pop = (
                        int(total_pop_result[0])
                        if total_pop_result[0] is not None
                        else 0
                    )

                    # 市内将来人口と居住誘導区域将来人口から居住誘導区域外の将来人口：rを求める
                    outside_area_future_Pop = future_total_pop - future_area_pop

                    # 誘導目標人口（目標人口と将来人口の差）：Sの割合
                    pop_s = (
                        future_area_pop - target_population
                    )  # S: 目標人口と将来人口の差
                    if target_population > 0:
                        rate_target_pop_difference = (
                            pop_s / target_population
                        ) * 100
                    else:
                        rate_target_pop_difference = '―'

                    # 居住誘導区域の適切さ（S/p）
                    if area_pop_difference != 0:
                        rate_area_appropriateness_sp = (
                            pop_s / area_pop_difference
                        ) * 100
                    else:
                        rate_area_appropriateness_sp = '―'

                    # 居住誘導区域の適切さ（S/r）
                    if outside_area_future_Pop > 0:
                        rate_area_appropriateness_sr = (
                            pop_s / outside_area_future_Pop
                        ) * 100
                    else:
                        rate_area_appropriateness_sr = '―'
                else:
                    # 最終年度以外は '―'
                    area_pop_difference = '―'
                    rate_target_pop_difference = '―'
                    outside_area_future_Pop = '―'
                    rate_area_appropriateness_sp = '―'
                    rate_area_appropriateness_sr = '―'

                # データを辞書にまとめる
                year_data = {
                    'Year': year,
                    'Total_Pop': total_pop,
                    'Area_Pop': area_pop,
                    'Outside TheArea_Pop': outside_area_pop,
                    'Rate_Pop': rate_pop,
                    'Outside TheArea_Rate_Pop': outside_rate_pop,
                    'Rate_Pop_Change': rate_pop_change,
                    'Area': area,
                    'Outside TheArea': outside_area,
                    'Rate_Pop_Change_Change': rate_area_pop_change,
                    'Pop_Area_Density': pop_area_density,
                    'Pop_Outside TheArea_Density': pop_outside_area_density,
                    'Rate_Density_Change': rate_density_change,
                    'Pop_Outside TheArea_Rate_Density_Change': pop_outside_rate_density_change,
                    'Area_Pop_Difference': area_pop_difference,
                    'Outside TheArea_future_Pop': outside_area_future_Pop,
                    'Rate_Target_Pop_Difference': rate_target_pop_difference,
                    'Rate_Area_Appropriateness_Sp': rate_area_appropriateness_sp,
                    'Rate_Area_Appropriateness_Sr': rate_area_appropriateness_sr,
                    'Pop_Area_Age0-14s': area_pop_by_age["Pop_Area_Age0-14s"],
                    'Pop_Area_Age15-64s': area_pop_by_age["Pop_Area_Age15-64s"],
                    'Pop_Area_Age65AndOver': area_pop_by_age[
                        "Pop_Area_Age65AndOver"
                    ],
                    'Pop_Area_Age75AndOver': area_pop_by_age[
                        "Pop_Area_Age75AndOver"
                    ],
                    'Pop_Area_Age85AndOver': area_pop_by_age[
                        "Pop_Area_Age85AndOver"
                    ],
                    'Pop_Area_Age95AndOver': area_pop_by_age[
                        "Pop_Area_Age95AndOver"
                    ],
                    'Rate_Pop_Area_Age0-14s': rate_pop_by_age[
                        "Rate_Pop_Area_Age0-14s"
                    ],
                    'Rate_Pop_Area_Age15-64s': rate_pop_by_age[
                        "Rate_Pop_Area_Age15-64s"
                    ],
                    'Rate_Pop_Area_Age65AndOver': rate_pop_by_age[
                        "Rate_Pop_Area_Age65AndOver"
                    ],
                    'Rate_Pop_Area_Age75AndOver': rate_pop_by_age[
                        "Rate_Pop_Area_Age75AndOver"
                    ],
                    'Rate_Pop_Area_Age85AndOver': rate_pop_by_age[
                        "Rate_Pop_Area_Age85AndOver"
                    ],
                    'Rate_Pop_Area_Age95AndOver': rate_pop_by_age[
                        "Rate_Pop_Area_Age95AndOver"
                    ],
                    # 年代別誘導区域内人口割合の変化
                    **rate_pop_area_change_by_age,
                    # 年代別人口密度
                    **density_pop_by_age,
                    # 年代別人口密度の変化率
                    **rate_pop_area_density_change_by_age,
                }

                # 辞書をリストに追加
                data_list.append(year_data)

            # ファイルパスを指定してエクスポート
            self.export(
                self.base_path + '\\IF101_居住誘導区域関連評価指標ファイル.csv',
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
