"""
/***************************************************************************
 *
 * 【FN004】施設関連データ作成機能
 *
 ***************************************************************************/
"""

import os
import re
import chardet
from qgis.core import (
    QgsMessageLog,
    Qgis,
    QgsVectorLayer,
    QgsField,
    QgsFeature,
    QgsFeatureRequest,
)
from PyQt5.QtCore import QCoreApplication, QVariant
from .gpkg_manager import GpkgManager

class FacilityDataGenerator:
    """施設関連データ作成機能"""
    FACILITY_TYPES = {
        "行政施設ポイント": 1,
        "医療施設ポイント": 3,
        "福祉施設ポイント": 4,
        "学校ポイント": 6,
        "文化施設ポイント": 7,
    }

    FIELD_MAPPINGS = {
        # 行政施設ポイント
        1: {"name_field": "P05_003", "address_field": "P05_004"},
        # 医療施設ポイント
        3: {"name_field": "P04_002", "address_field": "P04_003"},
        # 福祉施設ポイント
        4: {"name_field": "P14_008", "address_field": "P14_004"},
        # 学校ポイント
        6: {"name_field": "P29_004", "address_field": "P29_005"},
        # 文化施設ポイント
        7: {"name_field": "P27_005", "address_field": "P27_006"},
    }

    def __init__(self, base_path, check_canceled_callback=None):
        # GeoPackageマネージャーを初期化
        self.gpkg_manager = GpkgManager._instance
        # インプットデータパス
        self.base_path = base_path

        self.check_canceled = check_canceled_callback

    def tr(self, message):
        """翻訳用のメソッド"""
        return QCoreApplication.translate(self.__class__.__name__, message)

    def load_facilities(self):
        """施設データ取り込み"""
        try:
            layers = []
            for facility_type, file_type in self.FACILITY_TYPES.items():
                facility_folder = os.path.join(
                    self.base_path, "施設", facility_type
                )
                shp_files = self.__get_shapefiles(facility_folder)

                if not shp_files:
                    msg = self.tr(
                        "The Shapefile for %1 was not found."
                    ).replace("%1", facility_type)

                    QgsMessageLog.logMessage(
                        msg,
                        self.tr("Plugin"),
                        Qgis.Warning,
                    )
                    continue

                if self.check_canceled():
                    return  # キャンセルチェック

                for shp_file in shp_files:
                    year = self.__extract_year_from_path(shp_file)
                    encoding = self.__detect_encoding(shp_file)

                    # Shapefile 読み込み時にエンコーディングを指定
                    layer = QgsVectorLayer(
                        shp_file, os.path.basename(shp_file), "ogr"
                    )
                    layer.setProviderEncoding(encoding)

                    # レイヤの有効性を確認
                    if not layer.isValid():
                        msg = self.tr(
                            "Failed to load layer: %1"
                        ).replace("%1", shp_file)
                        QgsMessageLog.logMessage(
                            msg,
                            self.tr("Plugin"),
                            Qgis.Warning,
                        )

                    layers.append((layer, year, file_type))

                    if self.check_canceled():
                        return  # キャンセルチェック

            # レイヤを結合し、施設データを作成
            facility_layer = self.__create_facilities_layer(layers)

            if not self.gpkg_manager.add_layer(
                facility_layer, "facilities", "都市施設"
            ):
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            data_name = self.tr("facility")
            msg = self.tr(
                "%1 data generation completed."
            ).replace("%1", data_name)

            QgsMessageLog.logMessage(
                msg,
                self.tr("Plugin"),
                Qgis.Info,
            )
            return True

        except Exception as e:
            QgsMessageLog.logMessage(
                self.tr("An error occurred: %1").replace("%1", e),
                self.tr("Plugin"),
                Qgis.Critical,
            )
            return False

    def __get_shapefiles(self, directory):
        """指定されたディレクトリ配下のすべてのShapefile (.shp) を再帰的に取得する"""
        msg = self.tr("Directory: %1").replace("%1", directory)
        QgsMessageLog.logMessage(
            msg,
            self.tr("Plugin"),
            Qgis.Info,
        )

        shp_files = []
        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith(".shp"):
                    shp_files.append(os.path.join(root, file))
        return shp_files

    def __extract_year_from_path(self, file_path):
        """ファイルパスから年度を抽出"""
        try:
            match = re.search(r'(\d{4})年', file_path)
            if match:
                return int(match.group(1))
            else:
                msg = self.tr(
                    "Failed to extract year from file path: %1"
                ).replace(
                    "%1", file_path
                )
                QgsMessageLog.logMessage(
                    msg,
                    self.tr("Plugin"),
                    Qgis.Warning,
                )
                return None
        except Exception as e:
            msg = self.tr(
                "An error occurred during year extraction: %1"
            ).replace(
                "%1", str(e)
            )
            QgsMessageLog.logMessage(
                msg,
                self.tr("Plugin"),
                Qgis.Critical,
            )
            return None

    def __create_facilities_layer(self, layers):
        """複数の施設レイヤを1つの統合レイヤに変換し、商業施設を追加"""
        # 統合レイヤを作成
        fields = [
            QgsField("year", QVariant.Int),
            QgsField("name", QVariant.String),
            QgsField("type", QVariant.Int),
            QgsField("address", QVariant.String),
        ]
        facility_layer = QgsVectorLayer(
            "Point?crs=EPSG:4326", "facilities", "memory"
        )
        provider = facility_layer.dataProvider()
        provider.addAttributes(fields)
        facility_layer.updateFields()

        # レイヤの編集を開始
        facility_layer.startEditing()

        # 施設データの収集と統合
        for layer, year, file_type in layers:
            if self.check_canceled():
                return  # キャンセルチェック
            for feature in layer.getFeatures():
                new_feature = QgsFeature()
                new_feature.setGeometry(feature.geometry())
                new_feature.setFields(facility_layer.fields())

                # フィールドのマッピングを使用して name と address を取得
                if file_type == 4:
                    # 福祉施設ポイントは大分類によって、子育て施設と福祉施設を判別
                    name = (
                        feature["P14_008"]
                        if "P14_008" in feature.fields().names()
                        else None
                    )
                    address = (
                        feature["P14_004"]
                        if "P14_004" in feature.fields().names()
                        else None
                    )
                    type_code = self.__get_welfare_type(feature["P14_005"])
                elif file_type in self.FIELD_MAPPINGS:
                    mapping = self.FIELD_MAPPINGS[file_type]
                    name = (
                        feature[mapping["name_field"]]
                        if mapping["name_field"] in feature.fields().names()
                        else None
                    )
                    address = (
                        feature[mapping["address_field"]]
                        if mapping["address_field"] in feature.fields().names()
                        else None
                    )
                    type_code = file_type
                else:
                    msg = self.tr(
                        "Skipped feature %1. Unknown type: %2."
                    ).replace("%1", str(feature.id())).replace("%2", file_type)

                    QgsMessageLog.logMessage(
                        msg,
                        self.tr("Plugin"),
                        Qgis.Info,
                    )
                    continue

                # フィーチャの属性を設定
                new_feature.setAttribute("year", year)
                new_feature.setAttribute("name", name)
                new_feature.setAttribute("type", type_code)
                new_feature.setAttribute("address", address)
                provider.addFeature(new_feature)

        # 商業施設の情報をfacilitiesレイヤに追加
        buildings_layer = self.gpkg_manager.load_layer(
            'buildings', None, withload_project=False
        )  # buildingsレイヤ
        request = QgsFeatureRequest().setFilterExpression(
            '"usage" = \'商業施設\''
        )  # 使用用途が商業施設のものを抽出
        for feature in buildings_layer.getFeatures(request):
            if self.check_canceled():
                return  # キャンセルチェック
            new_feature = QgsFeature()
            # ポリゴンの中心をポイントとして取得
            centroid = feature.geometry().centroid()
            new_feature.setGeometry(centroid)
            new_feature.setFields(facility_layer.fields())

            # 属性設定
            new_feature.setAttribute("name", None)
            new_feature.setAttribute("address", feature["address"])
            new_feature.setAttribute("year", None)
            new_feature.setAttribute("type", 2)
            provider.addFeature(new_feature)

        # 編集内容をコミットして保存
        facility_layer.commitChanges()
        facility_layer.updateExtents()

        return facility_layer

    def __get_welfare_type(self, data):
        """福祉施設ポイントのP14_005属性に基づいて施設タイプを判別"""
        if data in ('05', '06'):
            return 4  # 子育て施設
        return 5  # 福祉施設（'01', '02', '03', '04', '99'..etc)

    def __detect_encoding(self, file_path):
        """Shapefile に対応する DBF ファイルのエンコーディングを検出"""
        dbf_file = file_path.replace(
            '.shp', '.dbf'
        )  # shpに対応する .dbf ファイルのパス
        if os.path.exists(dbf_file):
            with open(dbf_file, 'rb') as f:
                raw_data = f.read()
                result = chardet.detect(raw_data)
                encoding = result['encoding']
                if encoding == 'MacRoman':
                    msg = self.tr(
                        "%1 was detected. Using SHIFT_JIS for the file %2."
                    ).replace("%1", "MacRoman").replace("%2", dbf_file)
                    QgsMessageLog.logMessage(
                        msg,
                        self.tr("Plugin"),
                        Qgis.Info,
                    )
                    encoding = 'SHIFT_JIS'

                if encoding == 'Windows-1254':
                    msg = self.tr(
                        "%1 was detected. Using SHIFT_JIS for the file %2."
                    ).replace("%1", "Windows-1254").replace("%2", dbf_file)
                    QgsMessageLog.logMessage(
                        msg,
                        self.tr("Plugin"),
                        Qgis.Info,
                    )
                    encoding = 'SHIFT_JIS'
                return encoding if encoding else 'UTF-8'
        else:
            msg = self.tr(
                "No corresponding DBF file was found for the specified path: "
                "%1."
            ).replace("%1", file_path)
            QgsMessageLog.logMessage(
                msg,
                self.tr("Plugin"),
                Qgis.Warning,
            )
            return 'UTF-8'
