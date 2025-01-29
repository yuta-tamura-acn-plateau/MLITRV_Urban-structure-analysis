"""
/***************************************************************************
 *
 * 【FN011】都市機能誘導関連評価指標算出機能
 *
 ***************************************************************************/
"""

import re
import csv
from qgis.core import (
    QgsMessageLog,
    Qgis,
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsAggregateCalculator,
    QgsVectorLayer,
    QgsFeature,
    QgsCoordinateReferenceSystem,
)
from PyQt5.QtCore import QCoreApplication
import processing
from .gpkg_manager import GpkgManager


class UrbanFunctionInductionMetricCalculator:
    """都市機能誘導関連評価指標算出機能"""
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
            # 施設
            facilities_layer = self.gpkg_manager.load_layer(
                'facilities', None, withload_project=False
            )

            if not buildings_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                    .replace("%1", "buildings"))

            if not induction_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                    .replace("%1", "induction_areas"))

            if not facilities_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                    .replace("%1", "facilities"))

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

            # 空間インデックス作成
            processing.run(
                "native:createspatialindex", {'INPUT': urban_area_layer}
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

            for induction_feature in transformed_layer.getFeatures():
                # 都市機能誘導区域（type_id=32）
                if induction_feature["type_id"] == 32:
                    # 面積計算 (ヘクタール単位へ変換: 1ヘクタール = 10,000平方メートル)
                    area += induction_feature.geometry().area() / 10000

            area = self.round_or_na(area, 1)

            # 都市機能誘導区域内の建物を取得
            result = processing.run(
                "native:joinattributesbylocation",
                {
                    'INPUT': centroid_layer,
                    'JOIN': urban_area_layer,
                    'PREDICATE': [5],  # overlap
                    'JOIN_FIELDS': [],
                    'METHOD': 0,
                    'OUTPUT': 'TEMPORARY_OUTPUT',
                    'DISCARD_NONMATCHING': True,
                    'PREFIX': 'induction_area_',
                },
            )

            # 結合結果の取得
            urban_buildings = result['OUTPUT']

            buildings_context = QgsExpressionContext()
            buildings_context.appendScopes(
                QgsExpressionContextUtils.globalProjectLayerScopes(
                    buildings_layer
                )
            )

            urban_context = QgsExpressionContext()
            urban_context.appendScopes(
                QgsExpressionContextUtils.globalProjectLayerScopes(
                    urban_buildings
                )
            )

            # 空間インデックス作成(施設)
            processing.run(
                "native:createspatialindex", {'INPUT': facilities_layer}
            )

            # 都市機能誘導区域内の施設を取得
            result = processing.run(
                "native:joinattributesbylocation",
                {
                    'INPUT': facilities_layer,
                    'JOIN': urban_area_layer,
                    'PREDICATE': [5],  # overlap
                    'JOIN_FIELDS': [],
                    'METHOD': 0,
                    'OUTPUT': 'TEMPORARY_OUTPUT',
                    'DISCARD_NONMATCHING': True,
                    'PREFIX': 'induction_area_',
                },
            )

            # 結合結果の取得
            urban_facilities = result['OUTPUT']

            for year in unique_years:
                if self.check_canceled():
                    return  # キャンセルチェック
                area_pop = 0

                year_field = f"{year}_population"

                # 総人口を集計
                total_pop_result = buildings_layer.aggregate(
                    QgsAggregateCalculator.Aggregate.Sum,
                    year_field,
                    QgsAggregateCalculator.AggregateParameters(),
                    buildings_context,
                )
                total_pop = (
                    int(total_pop_result[0])
                    if total_pop_result[0] is not None
                    else 0
                )

                # SUMフィールドの確認
                sum_field_name = f"{year_field}"
                sum_field_index = urban_buildings.fields().indexFromName(
                    sum_field_name
                )

                # フィールドが存在するか確認
                if sum_field_index == -1:
                    raise Exception(
                        f"集計フィールド {sum_field_name} が見つかりません"
                    )

                # 都市機能区域内人口
                sum_result = urban_buildings.aggregate(
                    QgsAggregateCalculator.Aggregate.Sum,
                    sum_field_name,
                    QgsAggregateCalculator.AggregateParameters(),
                    urban_context,
                )
                area_pop = (
                    int(sum_result[0]) if sum_result[0] is not None else 0
                )

                # 各施設種別の市内および都市機能誘導区域内の立地数を集計
                facility_types = [1, 2, 3, 4, 5, 6, 7]  # type属性の定義

                total_qty_facilities = {}
                qty_facilities_in_urban_area = {}
                for facility_type in facility_types:
                    # 市内の各施設種別の立地数をフィルタリングして集計
                    expression = (
                        f'"type" = {facility_type} AND "year" IS NOT NULL'
                    )
                    facilities_layer.selectByExpression(
                        expression, QgsVectorLayer.SetSelection
                    )

                    # フィルタリングされたフィーチャから年度をユニークに取得
                    year_values = set(
                        feature["year"]
                        for feature in facilities_layer.getSelectedFeatures()
                        if feature["year"] is not None
                    )

                    year_num = int(year)
                    # ループ対象の 年度 が存在するかを確認
                    if year_num in year_values:
                        # ループ対象の 年度 が存在する場合は、その 年度 を条件にする
                        expression = (
                            f'"type" = {facility_type} AND "year" = {year}'
                        )
                    elif year_values:
                        # 存在しない場合、過去の年で最も新しい年度を選択
                        closest_year = max(year_values)

                        expression = (
                            f'"type" = {facility_type} '
                            f'AND "year" = {closest_year}'
                        )

                    else:
                        # 年度がない場合、NULL を条件にする
                        expression = (
                            f'"type" = {facility_type} AND "year" IS NULL'
                        )

                    # フィルタに基づいて条件に一致するフィーチャを取得
                    facilities_layer.selectByExpression(
                        expression, QgsVectorLayer.SetSelection
                    )

                    # 一致するフィーチャの数を取得
                    total_qty_facility = facilities_layer.selectedFeatureCount()
                    total_qty_facilities[facility_type] = total_qty_facility

                    # 都市機能誘導区域内の各施設種別の立地数をフィルタリングして集計
                    # 同様に、都市機能誘導区域内のフィーチャをフィルタリング
                    urban_expression = (
                        f'"type" = {facility_type} AND '
                        f'("year" IS NULL OR "year" <= {year})'
                    )

                    # フィルタリングしてフィーチャ数を取得
                    urban_facilities.selectByExpression(
                        urban_expression, QgsVectorLayer.SetSelection
                    )

                    qty_facility_in_urban_area = (
                        urban_facilities.selectedFeatureCount()
                    )
                    qty_facilities_in_urban_area[facility_type] = (
                        qty_facility_in_urban_area
                    )

                # 都市機能誘導区域内人口割合
                rate_pop = (
                    self.round_or_na((area_pop / total_pop) * 100, 2)
                    if total_pop > 0
                    else 0
                )

                # 都市機能誘導区域内人口密度を計算
                pop_area_density = (
                    self.round_or_na(area_pop / area, 2) if area > 0 else '―'
                )  # haあたりの人口密度

                rate_qty_facilities = {}
                rate_qty_change = {}

                # 前年度のデータがあれば、変化率を計算
                if data_list:
                    # 前年度のデータを取得
                    previous_year_data = data_list[-1]
                    previous_total_pop = previous_year_data['Total_Pop']
                    previous_rate_pop = previous_year_data['Rate_Pop']
                    previous_pop_area_density = previous_year_data[
                        'Pop_Area_Density'
                    ]

                    # 総人口の変化率
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

                    # 都市機能誘導区域内人口割合の変化率
                    rate_area_pop_change = (
                        self.round_or_na(
                            ((rate_pop - previous_rate_pop) / previous_rate_pop)
                            * 100,
                            1,
                        )
                        if previous_rate_pop > 0
                        else '―'
                    )

                    # 都市機能誘導区域内人口密度の変化率
                    rate_density_change = (
                        self.round_or_na(
                            (
                                (pop_area_density - previous_pop_area_density)
                                / previous_pop_area_density
                            )
                            * 100,
                            1,
                        )
                        if previous_pop_area_density > 0
                        else '―'
                    )

                    # 施設の変化を算出
                    for facility_type in facility_types:
                        previous_qty_facility = previous_year_data[
                            f'Qty_Facility_{facility_type:02}'
                        ]
                        previous_rate_qty_facility = previous_year_data[
                            f'Rate_Qty_Facility_{facility_type:02}'
                        ]

                        # 立地数の変化率を計算（都市機能誘導区域内）
                        if previous_qty_facility > 0:
                            rate_qty_facility = self.round_or_na(
                                (
                                    (
                                        qty_facilities_in_urban_area[
                                            facility_type
                                        ]
                                        - previous_qty_facility
                                    )
                                    / previous_qty_facility
                                )
                                * 100,
                                2,
                            )
                        else:
                            rate_qty_facility = 0

                        # 前年度の変化率との差を計算
                        if isinstance(previous_rate_qty_facility, (int, float)):
                            rate_qty_change_for_type = self.round_or_na(
                                (
                                    rate_qty_facility
                                    - previous_rate_qty_facility
                                ),
                                2,
                            )
                        else:
                            rate_qty_change_for_type = '―'

                        rate_qty_facilities[facility_type] = rate_qty_facility
                        rate_qty_change[facility_type] = (
                            rate_qty_change_for_type
                        )

                else:
                    rate_pop_change = '―'
                    rate_area_pop_change = '―'
                    rate_density_change = '―'

                    for facility_type in facility_types:
                        rate_qty_facilities[facility_type] = '―'
                        rate_qty_change[facility_type] = '―'

                # データを辞書にまとめる
                year_data = {
                    'Year': year,
                    'Total_Pop': total_pop,
                    'Area_Pop': area_pop,
                    'Rate_Pop': rate_pop,
                    'Rate_Pop_Change': rate_pop_change,
                    'Area': area,
                    'Rate_Pop_Change_Change': rate_area_pop_change,
                    'Pop_Area_Density': pop_area_density,
                    'Rate_Density_Change': rate_density_change,
                }

                # 市内の施設立地総数
                year_data['Total_Qty_Facility_00'] = sum(
                    total_qty_facilities.values()
                )

                # 市内の施設種別立地数
                for facility_type in facility_types:
                    year_data[f'Total_Qty_Facility_{facility_type:02}'] = (
                        total_qty_facilities[facility_type]
                    )

                # 都市機能誘導区域内の施設立地総数
                year_data['Qty_Facility_00'] = sum(
                    qty_facilities_in_urban_area.values()
                )

                # 都市機能誘導区域内の施設種別立地数
                for facility_type in facility_types:
                    year_data[f'Qty_Facility_{facility_type:02}'] = (
                        qty_facilities_in_urban_area[facility_type]
                    )

                # 都市機能誘導区域内の施設種別数の全施設に対する割合
                total_urban_facilities = sum(
                    qty_facilities_in_urban_area.values()
                )  # 都市機能誘導区域内の全施設数
                rate_all_facility_list = []  # 割合のリスト

                if total_urban_facilities > 0:
                    # 各施設種別の割合を計算
                    for facility_type in facility_types:
                        rate_all_facility = self.round_or_na(
                            (
                                qty_facilities_in_urban_area[facility_type]
                                / total_urban_facilities
                            )
                            * 100,
                            2,
                        )
                        rate_all_facility_list.append(rate_all_facility)
                        year_data[f'Rate_ALLFacility_{facility_type:02}'] = (
                            rate_all_facility
                        )

                    # 誤差チェック
                    total_rate = sum(rate_all_facility_list)
                    rounding_error = self.round_or_na(100 - total_rate, 2)

                    # 誤差調整
                    if rounding_error != 0:
                        max_index = rate_all_facility_list.index(
                            max(rate_all_facility_list)
                        )
                        adjusted_value = self.round_or_na(
                            rate_all_facility_list[max_index] + rounding_error,
                            2,
                        )
                        year_data[
                            f'Rate_ALLFacility_{facility_types[max_index]:02}'
                        ] = adjusted_value

                else:
                    # 全施設数が0の場合
                    for facility_type in facility_types:
                        year_data[f'Rate_ALLFacility_{facility_type:02}'] = '―'

                # 前年度からの施設立地数の変化率を計算
                if (
                    len(data_list) > 1
                ):  # データリストに前年度が存在する場合のみ計算
                    previous_year_data = data_list[-1]  # 前年度のデータ
                    previous_qty_facility = previous_year_data[
                        'Qty_Facility_00'
                    ]
                    current_qty_facility = year_data['Qty_Facility_00']

                    if previous_qty_facility > 0:
                        # 前年度との変化率を計算
                        rate_qty_facility_change = self.round_or_na(
                            (
                                (current_qty_facility - previous_qty_facility)
                                / previous_qty_facility
                            )
                            * 100,
                            2,
                        )
                    else:
                        # 前年度の施設数が 0 の場合は変化率を計算できないので '―' にする
                        rate_qty_facility_change = '―'

                    year_data['Rate_Qty_Facility_00'] = (
                        rate_qty_facility_change
                    )
                else:
                    year_data['Rate_Qty_Facility_00'] = '―'

                # 前年度からの施設立地数の変化率
                for facility_type in facility_types:
                    year_data[f'Rate_Qty_Facility_{facility_type:02}'] = (
                        rate_qty_facilities[facility_type]
                    )

                # 前年度からの施設立地数の変化の変化
                for facility_type in facility_types:
                    year_data[
                        f'Rate_Qty_Facility_Change_{facility_type:02}'
                    ] = rate_qty_change[facility_type]

                # TODO:都市機能誘導区域内の施設利用者総数 次年度向け
                year_data['User_Facility_00'] = '―'

                for facility_type in facility_types:
                    # TODO:都市機能誘導区域内の施設種別利用者数 次年度向け
                    year_data[f'User_Facility_{facility_type:02}'] = '―'

                # TODO:前年度からの施設利用者数の変化率 次年度向け
                year_data['Rate_User_Facility_00'] = '―'

                for facility_type in facility_types:
                    # TODO:都市機能誘導区域内の施設種別利用者数の変化 次年度向け
                    year_data[f'Rate_User_Facility_{facility_type:02}'] = '―'

                # 辞書をリストに追加
                data_list.append(year_data)

            # ファイルパスを指定してエクスポート
            self.export(
                self.base_path
                + '\\IF102_都市機能誘導区域関連評価指標ファイル.csv',
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
