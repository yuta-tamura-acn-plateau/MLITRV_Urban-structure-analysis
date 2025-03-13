"""
/***************************************************************************
 *
 * GeoPackage 管理
 *
 ***************************************************************************/
"""

import os
from qgis.core import (
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsMessageLog,
    Qgis,
    QgsProject,
)
from PyQt5.QtCore import QCoreApplication
from osgeo import ogr


class GpkgManager:
    """Geopackageファイル管理"""
    _instance = None

    def __new__(
        cls,
        base_path=None,
        gpkg_name="PlateauStatisticsVisualizationPlugin.gpkg",
    ):
        if cls._instance is None:
            cls._instance = super(GpkgManager, cls).__new__(cls)
            cls._instance.base_path = base_path
            cls._instance.gpkg_name = gpkg_name
            cls._instance.geopackage_path = os.path.join(base_path, gpkg_name)
        return cls._instance

    def tr(self, message):
        """翻訳用のメソッド"""
        return QCoreApplication.translate("GpkgManager", message)

    def init(
        self, base_path, gpkg_name="PlateauStatisticsVisualizationPlugin.gpkg"
    ):
        """初期化"""
        # 最初期化
        self.base_path = base_path
        self.gpkg_name = gpkg_name
        self.geopackage_path = os.path.join(base_path, gpkg_name)
        QgsMessageLog.logMessage(
            self.tr(
                "GeoPackage Manager has been reset. New path: %1."
            ).replace("%1", self.geopackage_path),
            self.tr("Plugin"),
            Qgis.Info,
        )

    def make_gpkg(self):
        """GeoPackage作成"""
        try:
            # 既存のGeoPackageから読み込んだレイヤをレイヤパネルから削除
            for layer in QgsProject.instance().mapLayers().values():
                if os.path.normpath(layer.source()).startswith(
                    os.path.normpath(self.geopackage_path)
                ):
                    QgsProject.instance().removeMapLayer(layer)

            # GeoPackageが存在しない場合、新規作成する
            if not os.path.exists(self.geopackage_path):
                # 空のレイヤーを作成してGeoPackageを初期化
                temp_layer = QgsVectorLayer("None", "temp", "memory")
                options = QgsVectorFileWriter.SaveVectorOptions()
                options.driverName = "GPKG"

                # GeoPackageの初期化のために一時レイヤーを書き込む
                error = QgsVectorFileWriter.writeAsVectorFormatV3(
                    temp_layer,
                    self.geopackage_path,
                    QgsProject.instance().transformContext(),
                    options,
                )

                if error[0] != QgsVectorFileWriter.NoError:
                    error_message = self.tr(
                        "Failed to create GeoPackage: %1"
                    ).replace("%1", str(error))
                    raise Exception(error_message)

            # 成功のログ出力
            QgsMessageLog.logMessage(
                self.tr("GeoPackage initialization completed. Path: %1")
                .replace("%1", self.geopackage_path),
                self.tr("Plugin"),
                Qgis.Info,
            )
            return self.geopackage_path

        except Exception as e:
            # エラーメッセージのログ出力
            QgsMessageLog.logMessage(
                self.tr("GeoPackage initialization error: %1").replace("%1", e),
                self.tr("Plugin"),
                Qgis.Critical,
            )
            raise Exception(self.tr("Failed to create GeoPackage.")) from e

    def load_layer(self, layer_name, alias=None, withload_project=True):
        """GeoPackageからレイヤを読み込む"""
        try:
            # GeoPackageからレイヤを読み込み
            uri = f"{self.geopackage_path}|layername={layer_name}"
            display_name = (
                alias if alias else layer_name
            )  # aliasが指定されていればそれを使用
            gpkg_layer = QgsVectorLayer(uri, display_name, "ogr")

            if not gpkg_layer.isValid():
                return None

            if withload_project:
                # レイヤをプロジェクトに追加
                added_layer = QgsProject.instance().addMapLayer(
                    gpkg_layer, False
                )  # Falseでレイヤツリーに自動追加を避ける

                # レイヤツリー追加、可視性をオフに設定
                root = QgsProject.instance().layerTreeRoot()
                layer_tree_layer = root.insertLayer(0, added_layer)
                layer_tree_layer.setItemVisibilityChecked(False)

                QgsMessageLog.logMessage(
                    self.tr("GeoPackage layer %1 added to the layer panel.")
                    .replace("%1", display_name),
                    self.tr("Plugin"),
                    Qgis.Info,
                )
            else:
                QgsMessageLog.logMessage(
                    self.tr("GeoPackage layer %1 loaded.")
                    .replace("%1", layer_name),
                    self.tr("Plugin"),
                    Qgis.Info,
                )

            return gpkg_layer

        except Exception as e:
            QgsMessageLog.logMessage(
                self.tr("Error loading GeoPackage layer: %1")
                .replace("%1", e),
                self.tr("Plugin"),
                Qgis.Critical,
            )
            return None

    def add_layer(self, layer, layer_name, alias=None, withload_project=True):
        """geopackageにレイヤを追加保存"""
        try:
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.actionOnExistingFile = (
                QgsVectorFileWriter.CreateOrOverwriteLayer
            )
            options.fileEncoding = 'UTF-8'
            options.layerName = layer_name

            error = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer,
                self.geopackage_path,
                QgsProject.instance().transformContext(),
                options,
            )

            if error[0] != QgsVectorFileWriter.NoError:
                raise Exception(
                    f"レイヤ {layer_name} の GeoPackage "
                    f"{self.geopackage_path} への保存に失敗しました: "
                    f"{error[1]}"
                )

            QgsMessageLog.logMessage(
                self.tr("Layer %1 added to GeoPackage %2.")
                .replace("%1", layer_name).replace("%2", self.geopackage_path),
                self.tr("Plugin"),
                Qgis.Info,
            )

            # レイヤをレイヤパネルへ追加
            return self.load_layer(layer_name, alias, withload_project)

        except Exception as e:
            QgsMessageLog.logMessage(
                self.tr("An error occurred: %1").replace("%1", e),
                self.tr("Plugin"),
                Qgis.Critical,
            )
            return False

    def delete_layer(self, layer_name):
        """指定したレイヤをGeoPackageから削除"""
        try:
            gpkg = ogr.Open(self.geopackage_path, update=1)

            if gpkg is None:
                raise Exception(
                    f"GeoPackageの読み込みに失敗しました: {self.geopackage_path}"
                )

            if self.load_layer(layer_name, False) is None:
                return

            if gpkg.DeleteLayer(layer_name) != 0:
                msg = self.tr(
                    "Failed to delete layer: %1"
                ).replace("%1", layer_name)
                raise Exception(msg)

            QgsMessageLog.logMessage(
                self.tr("Layer %1 deleted from GeoPackage %2.")
                .replace("%1", layer_name).replace("%2", self.geopackage_path),
                self.tr("Plugin"),
                Qgis.Info,
            )

            gpkg.Close()
            return True

        except Exception as e:
            QgsMessageLog.logMessage(
                self.tr("Error deleting GeoPackage layer: %1").replace("%1", e),
                self.tr("Plugin"),
                Qgis.Critical,
            )
            return False

    def get_layers(self):
        """GeoPackage内のレイヤ名一覧を取得する"""
        layer_names = []

        # GeoPackageを開く
        gpkg = ogr.Open(self.geopackage_path)

        if gpkg is None:
            QgsMessageLog.logMessage(
                self.tr(
                    "Failed to load GeoPackage: %1"
                ).replace("%1", self.geopackage_path),
                self.tr("Plugin"),
                Qgis.Critical,
            )
            return []

        # レイヤ名を取得
        for i in range(gpkg.GetLayerCount()):
            layer = gpkg.GetLayerByIndex(i)
            layer_names.append(layer.GetName())

        # GeoPackageを明示的に閉じる
        gpkg.Close()

        return layer_names
