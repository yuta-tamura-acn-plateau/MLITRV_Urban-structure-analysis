"""
/***************************************************************************
 *
 * 【FN012】防災関連評価指標算出機能
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
)
from PyQt5.QtCore import QCoreApplication
import processing
from .gpkg_manager import GpkgManager


class DisasterPreventionMetricCalculator:
    """防災関連評価指標算出機能"""
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
            # 計画規模(L1)
            hazard_area_l1_layer = self.gpkg_manager.load_layer(
                'hazard_area_planned_scales', None, withload_project=False
            )
            # 想定最大規模(L2)
            hazard_area_l2_layer = self.gpkg_manager.load_layer(
                'hazard_area_maximum_scales', None, withload_project=False
            )
            # 土砂災害
            hazard_area_landslides_layer = self.gpkg_manager.load_layer(
                'hazard_area_landslides', None, withload_project=False
            )
            # 氾濫流
            hazard_area_floodplains_layer = self.gpkg_manager.load_layer(
                'hazard_area_floodplains', None, withload_project=False
            )
            # 津波
            hazard_area_tsunamis_layer = self.gpkg_manager.load_layer(
                'hazard_area_tsunamis', None, withload_project=False
            )
            # 高潮
            hazard_area_storm_surges_layer = self.gpkg_manager.load_layer(
                'hazard_area_storm_surges', None, withload_project=False
            )
            # 避難施設バッファ
            shelter_buffers_layer = self.gpkg_manager.load_layer(
                'shelter_buffers', None, withload_project=False
            )

            if not buildings_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                                .replace("%1", "buildings_layer"))

            if not hazard_area_l1_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                    .replace("%1", "hazard_area_planned_scales"))

            if not hazard_area_l2_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                    .replace("%1", "hazard_area_maximum_scales"))

            if not hazard_area_landslides_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                                .replace("%1", "hazard_area_landslides"))

            if not hazard_area_floodplains_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                                .replace("%1", "hazard_area_floodplains"))

            if not hazard_area_tsunamis_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                                .replace("%1", "hazard_area_tsunamis"))

            if not hazard_area_storm_surges_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                    .replace("%1", "hazard_area_storm_surges"))

            if not shelter_buffers_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                                .replace("%1", "shelter_buffers"))

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

            # 浸水以外のハザード区域のポリゴンをマージ
            merged_hazard_result = processing.run(
                "native:mergevectorlayers",
                {
                    'LAYERS': [
                        hazard_area_landslides_layer,
                        hazard_area_floodplains_layer,
                        hazard_area_tsunamis_layer,
                        hazard_area_storm_surges_layer,
                    ],
                    'CRS': centroid_layer.crs(),
                    'OUTPUT': 'memory:merged_hazard_area',
                },
            )

            if self.check_canceled():
                return  # キャンセルチェック

            hazard_area_other_layer = merged_hazard_result['OUTPUT']

            del (
                hazard_area_landslides_layer,
                hazard_area_floodplains_layer,
                hazard_area_tsunamis_layer,
                hazard_area_storm_surges_layer,
            )

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

            # 空間インデックス作成（浸水以外）
            processing.run(
                "native:createspatialindex", {'INPUT': hazard_area_other_layer}
            )

            # 空間インデックス作成（避難所）
            processing.run(
                "native:createspatialindex", {'INPUT': shelter_buffers_layer}
            )

            # 空間インデックス作成（L1）
            processing.run(
                "native:createspatialindex", {'INPUT': hazard_area_l1_layer}
            )

            hazard_area_l1_layer = self.gpkg_manager.add_layer(
                hazard_area_l1_layer, "tmp_hazard_area_l1_layer", None, False
            )
            if not hazard_area_l1_layer:
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            if self.check_canceled():
                return  # キャンセルチェック
            # L1範囲の建物を取得
            result = processing.run(
                "native:joinattributesbylocation",
                {
                    'INPUT': centroid_layer,
                    'JOIN': hazard_area_l1_layer,
                    'PREDICATE': [5],  # overlap
                    'JOIN_FIELDS': [],
                    'METHOD': 0,
                    'OUTPUT': 'TEMPORARY_OUTPUT',
                    'DISCARD_NONMATCHING': True,
                    'PREFIX': 'hazard_area_l1_',
                },
            )

            l1_buildings = self.gpkg_manager.add_layer(
                result['OUTPUT'], "tmp_l1_buildings", None, False
            )
            if not l1_buildings:
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            if self.check_canceled():
                return  # キャンセルチェック
            # 空間インデックス作成（L2）
            processing.run(
                "native:createspatialindex", {'INPUT': hazard_area_l2_layer}
            )

            hazard_area_l2_layer = self.gpkg_manager.add_layer(
                hazard_area_l2_layer, "tmp_hazard_area_l2_layer", None, False
            )
            if not hazard_area_l2_layer:
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            if self.check_canceled():
                return  # キャンセルチェック
            # L2範囲の建物を取得
            result = processing.run(
                "native:joinattributesbylocation",
                {
                    'INPUT': centroid_layer,
                    'JOIN': hazard_area_l2_layer,
                    'PREDICATE': [5],  # overlap
                    'JOIN_FIELDS': [],
                    'METHOD': 0,
                    'OUTPUT': 'TEMPORARY_OUTPUT',
                    'DISCARD_NONMATCHING': True,
                    'PREFIX': 'hazard_area_l2_',
                },
            )

            l2_buildings = self.gpkg_manager.add_layer(
                result['OUTPUT'], "tmp_l2_buildings", None, False
            )
            if not l2_buildings:
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            if self.check_canceled():
                return  # キャンセルチェック
            # 浸水以外のハザード区域のポリゴンを1件にマージ
            result = processing.run(
                "native:dissolve",
                {
                    'INPUT': hazard_area_other_layer,
                    'FIELD': [],  # 全てのフィーチャをマージ
                    'OUTPUT': 'TEMPORARY_OUTPUT',
                },
            )

            hazard_area_other_layer = self.gpkg_manager.add_layer(
                result['OUTPUT'], "tmp_hazard_area_other_layer", None, False
            )
            if not hazard_area_other_layer:
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            if self.check_canceled():
                return  # キャンセルチェック
            # 浸水以外のハザード区域内の建物を取得
            result = processing.run(
                "native:joinattributesbylocation",
                {
                    'INPUT': centroid_layer,
                    'JOIN': hazard_area_other_layer,
                    'PREDICATE': [5],  # overlap
                    'JOIN_FIELDS': [],
                    'METHOD': 0,
                    'OUTPUT': 'TEMPORARY_OUTPUT',
                    'DISCARD_NONMATCHING': True,
                    'PREFIX': 'other_hazard_',
                },
            )

            other_buildings = self.gpkg_manager.add_layer(
                result['OUTPUT'], "tmp_other_buildings", None, False
            )
            if not other_buildings:
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            if self.check_canceled():
                return  # キャンセルチェック
            # L1範囲外の建物を選択
            processing.run(
                "native:selectbylocation",
                {
                    'INPUT': centroid_layer,
                    'INTERSECT': l1_buildings,
                    'METHOD': 0,  # Discard matching buildings
                    'PREDICATE': [2],  # disjoint
                },
            )

            # 選択されたフィーチャを一時レイヤとして保存
            result = processing.run(
                "native:saveselectedfeatures",
                {'INPUT': centroid_layer, 'OUTPUT': 'TEMPORARY_OUTPUT'},
            )
            safe_buildings = result['OUTPUT']

            # 空間インデックス作成
            processing.run(
                "native:createspatialindex", {'INPUT': safe_buildings}
            )

            if self.check_canceled():
                return  # キャンセルチェック
            # L2範囲外の建物を選択
            processing.run(
                "native:selectbylocation",
                {
                    'INPUT': safe_buildings,  # L1で除外された建物を入力
                    'INTERSECT': l2_buildings,
                    'METHOD': 0,  # Discard matching buildings
                    'PREDICATE': [2],  # disjoint
                },
            )

            processing.run(
                "native:createspatialindex", {'INPUT': safe_buildings}
            )

            # 再度選択されたフィーチャを保存
            if self.check_canceled():
                return  # キャンセルチェック
            result = processing.run(
                "native:saveselectedfeatures",
                {'INPUT': safe_buildings, 'OUTPUT': 'TEMPORARY_OUTPUT'},
            )
            safe_buildings = result['OUTPUT']

            processing.run(
                "native:createspatialindex", {'INPUT': safe_buildings}
            )

            # 浸水以外のハザード区域外の建物を選択
            if self.check_canceled():
                return  # キャンセルチェック
            processing.run(
                "native:selectbylocation",
                {
                    'INPUT': safe_buildings,  # L2で除外された建物を入力
                    'INTERSECT': other_buildings,
                    'METHOD': 0,  # Discard matching buildings
                    'PREDICATE': [2],  # disjoint
                },
            )

            # 最終的に選択されたフィーチャを保存
            result = processing.run(
                "native:saveselectedfeatures",
                {'INPUT': safe_buildings, 'OUTPUT': 'TEMPORARY_OUTPUT'},
            )

            safe_buildings = self.gpkg_manager.add_layer(
                result['OUTPUT'], "tmp_safe_buildings", None, False
            )
            if not safe_buildings:
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            if self.check_canceled():
                return  # キャンセルチェック
            # 避難可能区域の建物を取得
            result = processing.run(
                "native:joinattributesbylocation",
                {
                    'INPUT': centroid_layer,
                    'JOIN': shelter_buffers_layer,
                    'PREDICATE': [5],  # overlap
                    'JOIN_FIELDS': [],
                    'METHOD': 1,  # 最初に合致した地物の属性のみ
                    'DISCARD_NONMATCHING': True,
                    'PREFIX': 'shelter_buffers_',
                    'OUTPUT': 'TEMPORARY_OUTPUT',
                },
            )

            if self.check_canceled():
                return  # キャンセルチェック
            # GeoPackage に保存
            evacuation_possible_buildings = self.gpkg_manager.add_layer(
                result['OUTPUT'],
                "tmp_evacuation_possible_buildings",
                None,
                False,
            )
            if not evacuation_possible_buildings:
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            for year in unique_years:
                if self.check_canceled():
                    return  # キャンセルチェック
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

                # 浸水以外人口
                sum_result = other_buildings.aggregate(
                    QgsAggregateCalculator.Aggregate.Sum,
                    year_field,
                    QgsAggregateCalculator.AggregateParameters(),
                )
                hazard01_area_pop = (
                    int(sum_result[0]) if sum_result[0] is not None else 0
                )

                # L1浸水区域内人口
                sum_result = l1_buildings.aggregate(
                    QgsAggregateCalculator.Aggregate.Sum,
                    year_field,
                    QgsAggregateCalculator.AggregateParameters(),
                )
                hazard02_area_pop = (
                    int(sum_result[0]) if sum_result[0] is not None else 0
                )

                # L2浸水区域内人口
                sum_result = l2_buildings.aggregate(
                    QgsAggregateCalculator.Aggregate.Sum,
                    year_field,
                    QgsAggregateCalculator.AggregateParameters(),
                )
                hazard03_area_pop = (
                    int(sum_result[0]) if sum_result[0] is not None else 0
                )

                # 安全区域人口
                sum_result = safe_buildings.aggregate(
                    QgsAggregateCalculator.Aggregate.Sum,
                    year_field,
                    QgsAggregateCalculator.AggregateParameters(),
                )
                hazard04_area_pop = (
                    int(sum_result[0]) if sum_result[0] is not None else 0
                )

                # 浸水以外のハザード区域内人口割合
                rate_hazard01_area_pop = (
                    self.round_or_na((hazard01_area_pop / total_pop) * 100, 2)
                    if total_pop > 0
                    else '―'
                )

                # L1浸水区域内人口割合
                rate_hazard02_area_pop = (
                    self.round_or_na((hazard02_area_pop / total_pop) * 100, 2)
                    if total_pop > 0
                    else '―'
                )

                # L2浸水区域内人口割合
                rate_hazard03_area_pop = (
                    self.round_or_na((hazard03_area_pop / total_pop) * 100, 2)
                    if total_pop > 0
                    else '―'
                )

                # 安全区域内人口割合
                rate_hazard04_area_pop = (
                    self.round_or_na((hazard04_area_pop / total_pop) * 100, 2)
                    if total_pop > 0
                    else '―'
                )

                # 避難施設カバー圏人口
                sum_result = evacuation_possible_buildings.aggregate(
                    QgsAggregateCalculator.Aggregate.Sum,
                    year_field,
                    QgsAggregateCalculator.AggregateParameters(),
                )
                evacuation_facility_pop = (
                    int(sum_result[0]) if sum_result[0] is not None else 0
                )

                # 避難施設カバー率
                rate_evacuation_facility_pop = (
                    self.round_or_na(
                        (evacuation_facility_pop / total_pop) * 100, 2
                    )
                    if total_pop > 0
                    else '―'
                )

                # 前年度のデータがあれば、変化率を計算
                if data_list:
                    previous_year_data = data_list[-1]

                    rate_hazard01_area_pop_change = (
                        self.round_or_na(
                            (
                                (
                                    rate_hazard01_area_pop
                                    - previous_year_data[
                                        'Rate_hazard01_Area_Pop'
                                    ]
                                )
                                / previous_year_data['Rate_hazard01_Area_Pop']
                            )
                            * 100,
                            2,
                        )
                        if previous_year_data['Rate_hazard01_Area_Pop'] > 0
                        else '―'
                    )

                    rate_hazard02_area_pop_change = (
                        self.round_or_na(
                            (
                                (
                                    rate_hazard02_area_pop
                                    - previous_year_data[
                                        'Rate_hazard02_Area_Pop'
                                    ]
                                )
                                / previous_year_data['Rate_hazard02_Area_Pop']
                            )
                            * 100,
                            2,
                        )
                        if previous_year_data['Rate_hazard02_Area_Pop'] > 0
                        else '―'
                    )

                    rate_hazard03_area_pop_change = (
                        self.round_or_na(
                            (
                                (
                                    rate_hazard03_area_pop
                                    - previous_year_data[
                                        'Rate_hazard03_Area_Pop'
                                    ]
                                )
                                / previous_year_data['Rate_hazard03_Area_Pop']
                            )
                            * 100,
                            2,
                        )
                        if previous_year_data['Rate_hazard03_Area_Pop'] > 0
                        else '―'
                    )

                    rate_hazard04_area_pop_change = (
                        self.round_or_na(
                            (
                                (
                                    rate_hazard04_area_pop
                                    - previous_year_data[
                                        'Rate_hazard04_Area_Pop'
                                    ]
                                )
                                / previous_year_data['Rate_hazard04_Area_Pop']
                            )
                            * 100,
                            2,
                        )
                        if previous_year_data['Rate_hazard04_Area_Pop'] > 0
                        else '―'
                    )

                    rate_evacuation_facility_pop_change = (
                        self.round_or_na(
                            (
                                (
                                    rate_evacuation_facility_pop
                                    - previous_year_data[
                                        'Rate_Evacuation_Facility_Pop'
                                    ]
                                )
                                / previous_year_data[
                                    'Rate_Evacuation_Facility_Pop'
                                ]
                            )
                            * 100,
                            2,
                        )
                        if previous_year_data['Rate_Evacuation_Facility_Pop']
                        > 0
                        else '―'
                    )

                else:
                    rate_hazard01_area_pop_change = '―'
                    rate_hazard02_area_pop_change = '―'
                    rate_hazard03_area_pop_change = '―'
                    rate_hazard04_area_pop_change = '―'
                    rate_evacuation_facility_pop_change = '―'

                # データを辞書にまとめる
                year_data = {
                    'Year': year,
                    'Total_Pop': total_pop,
                    # 浸水以外のハザード区域内人口
                    'hazard01_Area_Pop': hazard01_area_pop,
                    # L1浸水区域内人口
                    'hazard02_Area_Pop': hazard02_area_pop,
                    # L2浸水区域内人口
                    'hazard03_Area_Pop': hazard03_area_pop,
                    # 安全区域内人口
                    'hazard04_Area_Pop': hazard04_area_pop,
                    # 浸水以外のハザード区域内人口割合
                    'Rate_hazard01_Area_Pop': rate_hazard01_area_pop,
                    # L1浸水区域内人口割合
                    'Rate_hazard02_Area_Pop': rate_hazard02_area_pop,
                    # L2浸水区域内人口割合
                    'Rate_hazard03_Area_Pop': rate_hazard03_area_pop,
                    # 安全区域内人口割合
                    'Rate_hazard04_Area_Pop': rate_hazard04_area_pop,
                    # 浸水以外のハザード区域内人口割合変化率
                    'Rate_hazard01_Area_Pop_Change': rate_hazard01_area_pop_change,
                    # L1浸水区域内人口割合変化率
                    'Rate_hazard02_Area_Pop_Change': rate_hazard02_area_pop_change,
                    # L2浸水区域内人口割合変化率
                    'Rate_hazard03_Area_Pop_Change': rate_hazard03_area_pop_change,
                    # 安全区域内人口割合変化率
                    'Rate_hazard04_Area_Pop_Change': rate_hazard04_area_pop_change,
                    # 避難施設カバー圏人口
                    'Evacuation_Facility_Pop': evacuation_facility_pop,
                    # 避難施設カバー率
                    'Rate_Evacuation_Facility_Pop': rate_evacuation_facility_pop,
                    # 避難施設カバー率の変化
                    'Rate_Evacuation_Facility_Pop_Change': rate_evacuation_facility_pop_change,
                }

                # 辞書をリストに追加
                data_list.append(year_data)

            # ファイルパスを指定してエクスポート
            self.export(
                self.base_path + '\\IF103_防災関連評価指標ファイル.csv',
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
