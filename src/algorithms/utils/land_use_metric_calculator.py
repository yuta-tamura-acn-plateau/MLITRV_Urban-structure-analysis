"""
/***************************************************************************
 *
 * 【FN014】土地利用関連評価指標算出機能
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
    QgsCoordinateReferenceSystem,
    QgsExpression,
    QgsFeatureRequest,
    QgsAggregateCalculator,
)
from PyQt5.QtCore import QCoreApplication
import processing
from .gpkg_manager import GpkgManager


class LandUseMetricCalculator:
    """土地利用関連評価指標算"""
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

            if not buildings_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                    .replace("%1", "buildings"))

            if not induction_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                    .replace("%1", "induction_areas"))

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

            for induction_feature in transformed_layer.getFeatures():
                # 居住誘導区域（type_id=31）
                if induction_feature["type_id"] == 31:
                    # 面積計算 (ヘクタール単位へ変換: 1ヘクタール = 10,000平方メートル)
                    area += induction_feature.geometry().area() / 10000

            area = self.round_or_na(area, 1)

            # 使用用途が住宅の建物を抽出
            expression = (
                '"usage" IN (\'住宅\', \'共同住宅\', \'店舗等併用住宅\', '
                '\'店舗等併用共同住宅\', \'作業所併用住宅\')'
            )

            result = processing.run(
                "native:extractbyexpression",
                {
                    'INPUT': centroid_layer,
                    'EXPRESSION': expression,
                    'OUTPUT': 'TEMPORARY_OUTPUT',
                },
            )

            # 結果をレイヤに追加
            centroid_layer = result['OUTPUT']
            # 空間インデックス作成
            processing.run(
                "native:createspatialindex", {'INPUT': centroid_layer}
            )

            if self.check_canceled():
                return  # キャンセルチェック
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

            for year in unique_years:
                if self.check_canceled():
                    return  # キャンセルチェック

                # 居住誘導区域内の住居総数
                total_number = residential_buildings.featureCount()

                # 空き家数を集計
                vacancy_field = f"{year}_is_vacancy"
                expression_vacancy = QgsExpression(
                    f'"{vacancy_field}" = 1'
                )  # vacancy_fieldを条件にして1のものを抽出
                vacant_matching_features = residential_buildings.getFeatures(
                    QgsFeatureRequest(expression_vacancy)
                )
                vacant_number = sum(1 for _ in vacant_matching_features)

                # 居住誘導区域内の住居床面積を集計
                total_floor_area_result = residential_buildings.aggregate(
                    QgsAggregateCalculator.Aggregate.Sum, 'total_floor_area'
                )
                total_floor_area_m2 = (
                    int(total_floor_area_result[0])
                    if total_floor_area_result[0] is not None
                    else 0
                )
                total_floor_area_ha = (
                    total_floor_area_m2 / 10000
                )  # ヘクタールに変換

                # 空き家の床面積を集計
                expression_vacant_floor_area = QgsExpression(
                    '"vacancy" = \'空き家\''
                )
                vacant_buildings = residential_buildings.getFeatures(
                    QgsFeatureRequest(expression_vacant_floor_area)
                )

                # 空き家の床面積を合計
                vacant_floor_area_m2 = sum(
                    [
                        feature['total_floor_area']
                        for feature in vacant_buildings
                        if feature['total_floor_area'] is not None
                    ]
                )
                vacant_floor_area_ha = (
                    vacant_floor_area_m2 / 10000
                )  # ヘクタールに変換

                # 前年度のデータがあれば、変化率を計算
                if data_list:
                    previous_year_data = data_list[-1]
                    vacant_rate_change = (
                        self.round_or_na(
                            (
                                (vacant_number / total_number)
                                - previous_year_data['Vacant_Rate']
                            )
                            * 100,
                            1,
                        )
                        if total_number > 0
                        else '―'
                    )
                    vacant_rate_floor_change = (
                        self.round_or_na(
                            (
                                (vacant_floor_area_ha / total_floor_area_ha)
                                - previous_year_data['Vacant_Floor_Rate']
                            )
                            * 100,
                            1,
                        )
                        if total_floor_area_ha > 0
                        else '-'
                    )
                else:
                    vacant_rate_change = '―'
                    vacant_rate_floor_change = '-'

                # データを辞書にまとめる
                year_data = {
                    'Year': year,
                    # 居住誘導区域内の住居総数
                    'Total_Number': total_number,
                    # 居住誘導区域内の空き家数
                    'Vacant_Number': vacant_number,
                    # 空き家率
                    'Vacant_Rate': (
                        self.round_or_na(
                            (vacant_number / total_number) * 100, 1
                        )
                        if total_number > 0
                        else '―'
                    ),
                    # 空き家率の変化
                    'Vacant_Rate_Change': vacant_rate_change,
                    # 住居床面積総数
                    'Total_FloorArea': total_floor_area_ha,
                    # 空き家の床面積
                    'Vacant_FloorArea': vacant_floor_area_ha,
                    # 空き家の床面積率
                    'Vacant_Floor_Rate': (
                        self.round_or_na(
                            (vacant_floor_area_ha / total_floor_area_ha) * 100,
                            1,
                        )
                        if total_floor_area_ha > 0
                        else '―'
                    ),
                    # 空き家の床面積率の変化
                    'Vacant_Rate_Floor_Change': vacant_rate_floor_change,
                    # TODO:誘導区域外の宅地開発面積 次年度向け
                    'Development_Area': '-',
                    # TODO:誘導区域外の宅地開発件数 次年度向け
                    'Developments_Number': '-',
                    # 居住誘導区域の面積
                    'Induction_Area': area,
                    # TODO:空地面積  次年度向け
                    'Induction_Vacant_land': '-',
                    # TODO:空地割合 次年度向け
                    'Rate_Induction_Vacant_land': '-',
                }

                # 辞書をリストに追加
                data_list.append(year_data)

            # ファイルパスを指定してエクスポート
            self.export(
                self.base_path + '\\IF105_土地利用関連評価指標ファイル.csv',
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
