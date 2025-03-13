"""
/***************************************************************************
 *
 * ゾーンポリゴン作成
 *
 ***************************************************************************/
"""

import os
import processing
import chardet
from qgis.core import (
    QgsMessageLog,
    Qgis,
    QgsVectorLayer,
    QgsField,
    QgsFeature,
    QgsProject,
)
from PyQt5.QtCore import QCoreApplication, QVariant
from .gpkg_manager import GpkgManager


class ZoneDataGenerator:
    """ゾーンポリゴンデータ取り込み・レイヤ作成"""
    def __init__(self, base_path, check_canceled_callback=None):
        # GeoPackageマネージャーを初期化
        self.gpkg_manager = GpkgManager._instance
        # インプットデータパス
        self.base_path = base_path

        self.check_canceled = check_canceled_callback

    def tr(self, message):
        """翻訳用のメソッド"""
        return QCoreApplication.translate(self.__class__.__name__, message)

    def create_zone(self):
        """ゾーンポリゴン 作成"""
        try:
            # base_path 配下の「ゾーンポリゴン」フォルダを再帰的に探索してShapefileを収集
            induction_area_folder = os.path.join(self.base_path, "ゾーンポリゴン")
            shp_files = self.__get_shapefiles(induction_area_folder)

            # プロジェクトのCRSを取得
            project_crs = QgsProject.instance().crs()

            # レイヤを格納するリスト
            layers = []

            for shp_file in shp_files:
                if self.check_canceled():
                    return False  # キャンセルチェック
                encoding = self.__detect_encoding(shp_file)

                # Shapefile 読み込み
                layer = QgsVectorLayer(
                    shp_file,
                    os.path.basename(shp_file),
                    "ogr"
                )
                layer.setProviderEncoding(encoding)

                if not layer.isValid():
                    msg = self.tr(
                        "Failed to load layer: %1"
                    ).replace("%1", shp_file)
                    QgsMessageLog.logMessage(
                        msg,
                        self.tr("Plugin"),
                        Qgis.Warning,
                    )
                    continue

                # プロジェクトのCRSに再投影
                if layer.crs() != project_crs:
                    layer = processing.run("native:reprojectlayer", {
                        'INPUT': layer,
                        'TARGET_CRS': project_crs,
                        'OUTPUT': 'memory:'
                    })['OUTPUT']

                # 一時メモリレイヤを作成し、Shapefileのデータを取り込み
                temp_layer = QgsVectorLayer(
                    f"Polygon?crs={project_crs.authid()}", "zones", "memory"
                )
                temp_provider = temp_layer.dataProvider()

                # 必要なフィールドを追加
                temp_provider.addAttributes([
                    QgsField("key_code", QVariant.String),
                    QgsField("pref", QVariant.String),
                    QgsField("city", QVariant.String),
                    # 必要な他のフィールドを追加...
                ])
                temp_layer.updateFields()

                # フィーチャの追加
                for feature in layer.getFeatures():
                    if self.check_canceled():
                        return False  # キャンセルチェック
                    new_feature = QgsFeature()
                    new_feature.setGeometry(feature.geometry())
                    new_feature.setAttributes([
                        feature["KEY_CODE"],  # key_code
                        feature["PREF"],      # pref
                        feature["CITY"],      # city
                        # 他の属性をマッピング...
                    ])
                    temp_provider.addFeature(new_feature)

                layers.append(temp_layer)

            if not layers:
                data_name = self.tr("zone")
                msg = (
                    self.tr("No valid %1 Shapefile was found.")
                    .replace("%1", data_name)
                )
                QgsMessageLog.logMessage(
                    msg,
                    self.tr("Plugin"),
                    Qgis.Info,
                )
                return False

            # 複数のレイヤをマージ
            merged_layer = self.__merge_layers(layers)

            # 無効なジオメトリを修復
            merged_layer = self.__fix_invalid_geometries(merged_layer)

            # 空間インデックス作成
            processing.run("native:createspatialindex", {'INPUT': merged_layer})

            # zonesレイヤをGeoPackageに保存
            if not self.gpkg_manager.add_layer(merged_layer, "zones", "行政区域"):
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            data_name = self.tr("zone")
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

    def __merge_layers(self, layers):
        """複数のレイヤを1つにマージ"""
        result = processing.run(
            "native:mergevectorlayers",
            {
                'LAYERS': layers,
                'CRS': layers[0].crs().authid(),
                'OUTPUT': 'memory:merged_layer',
            },
        )

        return result['OUTPUT']

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

            msg = self.tr("Detected encoding: %1").replace("%1", encoding)
            QgsMessageLog.logMessage(
                msg,
                self.tr("Plugin"),
                Qgis.Info,
            )
            return encoding if encoding else 'SHIFT_JIS'
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

    def __fix_invalid_geometries(self, layer):
        """Fix invalid geometries in the layer"""
        msg_start = self.tr(
            "Fixing invalid geometries in layer: %1."
        ).replace("%1", layer.name())
        QgsMessageLog.logMessage(
            msg_start,
            self.tr("Plugin"),
            Qgis.Info,
        )
        result = processing.run(
            "native:fixgeometries",
            {'INPUT': layer, 'OUTPUT': 'memory:fixed_layer'},
        )
        msg_complete = self.tr(
            "Completed fixing invalid geometries in layer: %1."
        ).replace("%1", layer.name())
        QgsMessageLog.logMessage(
            msg_complete,
            self.tr("Plugin"),
            Qgis.Info,
        )
        return result['OUTPUT']
