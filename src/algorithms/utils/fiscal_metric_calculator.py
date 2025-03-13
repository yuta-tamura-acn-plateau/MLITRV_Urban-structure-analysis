"""
/***************************************************************************
 *
 * 【FN015】財政関連評価指標算出機能
 *
 ***************************************************************************/
"""

import csv
import processing
from qgis.core import QgsMessageLog, Qgis, QgsVectorLayer
from PyQt5.QtCore import QCoreApplication
from .gpkg_manager import GpkgManager


class FiscalMetricCalculator:
    """財政関連評価指標算出機能"""
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
            # 地価公示
            land_prices_layer = self.gpkg_manager.load_layer(
                'land_prices', None, withload_project=False
            )
            # ゾーンポリゴン
            zones_layer = self.gpkg_manager.load_layer(
                'zones', None, withload_project=False
            )
            # 誘導区域
            induction_layer = self.gpkg_manager.load_layer(
                'induction_areas', None, withload_project=False
            )

            if not land_prices_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                                .replace("%1", "land_prices_layer"))

            if not zones_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                                .replace("%1", "zones_layer"))

            if not induction_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                                .replace("%1", "induction_layer"))

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
                "native:createspatialindex", {'INPUT': land_prices_layer}
            )
            processing.run("native:createspatialindex", {'INPUT': zones_layer})

            # ゾーンポリゴン内地価公示を取得
            result = processing.run(
                "native:extractbylocation",
                {
                    'INPUT': land_prices_layer,
                    'PREDICATE': [6],  # within
                    'INTERSECT': zones_layer,
                    'OUTPUT': 'TEMPORARY_OUTPUT',
                },
            )

            target_land_prices = result['OUTPUT']

            # 居住誘導区域内地価公示を取得
            residential_land_prices = processing.run(
                "native:extractbylocation",
                {
                    'INPUT': land_prices_layer,
                    'PREDICATE': [6],  # within
                    'INTERSECT': residential_area_layer,
                    'OUTPUT': 'TEMPORARY_OUTPUT',
                },
            )['OUTPUT']

            # 居住誘導区域外地価公示を取得
            non_residential_land_prices = processing.run(
                "native:difference",
                {
                    'INPUT': target_land_prices,
                    'OVERLAY': residential_area_layer,
                    'OUTPUT': 'TEMPORARY_OUTPUT',
                },
            )['OUTPUT']

            # 年度ごとに集計
            year_field = 'year'
            sum_field = 'public_land_price'
            result_aggregate = processing.run(
                "qgis:statisticsbycategories",
                {
                    'INPUT': target_land_prices,
                    'VALUES_FIELD_NAME': sum_field,
                    'CATEGORIES_FIELD_NAME': year_field,
                    'OUTPUT': 'memory:aggregated_land_prices',
                },
            )

            residential_aggregate = processing.run(
                "qgis:statisticsbycategories",
                {
                    'INPUT': residential_land_prices,
                    'VALUES_FIELD_NAME': sum_field,
                    'CATEGORIES_FIELD_NAME': year_field,
                    'OUTPUT': 'memory:aggregated_residential_land_prices',
                },
            )['OUTPUT']

            non_residential_aggregate = processing.run(
                "qgis:statisticsbycategories",
                {
                    'INPUT': non_residential_land_prices,
                    'VALUES_FIELD_NAME': sum_field,
                    'CATEGORIES_FIELD_NAME': year_field,
                    'OUTPUT': 'memory:aggregated_non_residential_land_prices',
                },
            )['OUTPUT']

            aggregated_layer = result_aggregate['OUTPUT']

            # 結果をデータリストに追加
            data_list = []
            previous_year_totals = {
                "total": None,
                "residential": None,
                "non_residential": None,
            }

            for feature in aggregated_layer.getFeatures():
                year = feature[year_field]
                total_land_price = feature['sum']

                # 前年度からの変化率を計算
                rate_land_price = None
                if previous_year_totals["total"] is not None:
                    if previous_year_totals["total"] > 0:
                        rate_land_price = (
                            (total_land_price - previous_year_totals["total"])
                            / previous_year_totals["total"]
                        ) * 100
                    else:
                        rate_land_price = None
                previous_year_totals["total"] = total_land_price

                # 居住誘導区域内のデータ
                residential_feature = next(
                    (
                        f
                        for f in residential_aggregate.getFeatures()
                        if f[year_field] == year
                    ),
                    None,
                )
                if residential_feature:
                    residential_avg_price = residential_feature['mean']
                    prev_residential_price = previous_year_totals["residential"]
                    if prev_residential_price is not None:
                        residential_rate_change = (
                            (residential_avg_price - prev_residential_price)
                            / prev_residential_price
                        ) * 100
                    else:
                        residential_rate_change = None
                    previous_year_totals["residential"] = residential_avg_price
                else:
                    residential_avg_price = None
                    residential_rate_change = None

                # 居住誘導区域外のデータ
                non_residential_feature = next(
                    (
                        f
                        for f in non_residential_aggregate.getFeatures()
                        if f[year_field] == year
                    ),
                    None,
                )
                if non_residential_feature:
                    non_residential_avg_price = non_residential_feature['mean']
                    prev_non_residential_price = previous_year_totals[
                        "non_residential"
                    ]
                    if prev_non_residential_price is not None:
                        non_residential_rate_change = (
                            (
                                non_residential_avg_price
                                - prev_non_residential_price
                            )
                            / prev_non_residential_price
                        ) * 100
                    else:
                        non_residential_rate_change = None
                    previous_year_totals["non_residential"] = (
                        non_residential_avg_price
                    )
                else:
                    non_residential_avg_price = None
                    non_residential_rate_change = None

                # 出力データを辞書にまとめる
                data = {
                    'Year': year,
                    'Total_Land_Price': int(
                        self.round_or_na(total_land_price, 1)
                    ),
                    'Rate_Land_Price': self.round_or_na(rate_land_price, 1),
                    'Average_Residental_Area_Land_Price': self.round_or_na(
                        residential_avg_price, 1
                    ),
                    'Average_Residental_Area_Outside_Land_Price': self.round_or_na(
                        non_residential_avg_price, 1
                    ),
                    'Rate_Change_Residental_Area_Land_Price': self.round_or_na(
                        residential_rate_change, 1
                    ),
                    'Rate_Change_Residental_Area_Outside_Land_Price': self.round_or_na(
                        non_residential_rate_change, 1
                    ),
                }

                data_list.append(data)

            # ファイルパスを指定してエクスポート
            self.export(
                self.base_path + '\\IF106_財政関連評価指標ファイル.csv',
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
