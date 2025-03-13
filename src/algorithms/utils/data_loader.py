"""
/***************************************************************************
 *
 * 【FN002】データ読み込み機能
 *
 ***************************************************************************/
"""

import re
from qgis.core import (
    QgsProject,
    QgsMessageLog,
    Qgis,
    QgsVectorLayer,
    QgsField,
    QgsFeature,
)
from PyQt5.QtCore import QCoreApplication, QVariant
import processing
from .gpkg_manager import GpkgManager


class DataLoader:
    """データ読み込み機能"""
    def __init__(self, check_canceled_callback=None):
        # GeoPackageマネージャーを初期化
        self.gpkg_manager = GpkgManager._instance

        self.check_canceled = check_canceled_callback

    def tr(self, message):
        """翻訳用のメソッド"""
        return QCoreApplication.translate(self.__class__.__name__, message)

    def load_buildings(self):
        """レイヤパネルの建物レイヤを元にレイヤを生成"""
        try:
            # レイヤパネルから"Building"と"BuildingDetail"レイヤを取得
            building_layers = QgsProject.instance().mapLayersByName("Building")
            building_detail_layers = QgsProject.instance().mapLayersByName(
                "Building / BuildingDetailAttribute"
            )

            # レイヤが存在するかを確認
            if not building_layers or not building_detail_layers:
                layer_name = self.tr("buildings layer")
                raise Exception(
                    self.tr("The %1 was not found.").replace("%1", layer_name)
                )
            # BuildingとBuildingDetailレイヤを取得
            building_layer = building_layers[0]
            building_detail_layer = building_detail_layers[0]

            # BuildingレイヤにBuildingDetailレイヤをLeftJoin
            joined_layer = self.join_with_detail(
                building_layer, building_detail_layer
            )

            # JOINの結果がメモリレイヤとして有効か確認
            if (
                not isinstance(joined_layer, QgsVectorLayer)
                or not joined_layer.isValid()
            ):
                raise Exception(self.tr("Failed to join layers."))

            # RiverFloodingRiskレイヤを収集
            flooding_layers = QgsProject.instance().mapLayers().values()
            river_flooding_risk_layers_l1 = [
                layer
                for layer in flooding_layers
                if "RiverFloodingRisk" in layer.name() and "L1" in layer.name()
            ]
            river_flooding_risk_layers_l2 = [
                layer
                for layer in flooding_layers
                if "RiverFloodingRisk" in layer.name() and "L2" in layer.name()
            ]

            # L1の浸水深を結合
            joined_layer = self.add_flooding_depth(
                joined_layer, river_flooding_risk_layers_l1, "flood_depth_l1"
            )

            # L2の浸水深を結合
            joined_layer = self.add_flooding_depth(
                joined_layer, river_flooding_risk_layers_l2, "flood_depth_l2"
            )

            # フィールド名をスネークケースに変換
            self.convert_fields_to_snake_case(joined_layer)

            # 無効なジオメトリを修正する
            joined_layer = self.__fix_invalid_geometries(joined_layer)

            # GeoPackageに保存
            if not self.gpkg_manager.add_layer(
                joined_layer, "buildings", "建築物"
            ):
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            # 元のBuildingレイヤを非表示にする
            layer_tree = (
                QgsProject.instance()
                .layerTreeRoot()
                .findLayer(building_layer.id())
            )
            if layer_tree:
                layer_tree.setItemVisibilityChecked(False)

            return True

        except Exception as e:
            # エラーメッセージのログ出力
            QgsMessageLog.logMessage(
                self.tr("An error occurred: %1").replace("%1", e),
                self.tr("Plugin"),
                Qgis.Critical,
            )
            raise Exception(self.tr("Failed to load data.")) from e

    def join_with_detail(
        self,
        building_layer,
        detail_layer,
        join_field='parent',
        target_field='id',
    ):
        """BuildingレイヤにBuildingDetailレイヤをLeftJoinする"""
        # processing.runを使用してレイヤを結合する
        result = processing.run(
            "native:joinattributestable",
            {
                'INPUT': building_layer,
                'FIELD': target_field,
                'INPUT_2': detail_layer,
                'FIELD_2': join_field,
                'FIELDS_TO_COPY': detail_layer.fields().names(),
                'METHOD': 0,  # LeftJoin
                'DISCARD_NONMATCHING': False,  # 一致しないレコードも保持する
                'PREFIX': '',
                'OUTPUT': 'memory:',
            },
        )
        return result['OUTPUT']

    def convert_fields_to_snake_case(self, layer: QgsVectorLayer):
        """レイヤ内の全フィールド名をスネークケースに変換"""
        provider = layer.dataProvider()
        for field in layer.fields():
            snake_case_name = self.to_snake_case(field.name())
            provider.renameAttributes(
                {layer.fields().indexOf(field.name()): snake_case_name}
            )
        layer.updateFields()

    def to_snake_case(self, name):
        """フィールド名をスネークケースに変換"""
        name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        name = re.sub('([a-z0-9])([A-Z])', r'\1_\2', name)
        return name.lower()

    def add_flooding_depth(
        self, building_layer, risk_layers, depth_field_name, join_field='parent'
    ):
        """浸水深フィールドを建物レイヤに追加"""
        # リスクレイヤが存在しない場合でも列を追加
        if not risk_layers:
            # フィールドを追加
            building_layer.dataProvider().addAttributes(
                [QgsField(depth_field_name, QVariant.Double)]
            )
            building_layer.updateFields()

            # 何もせずレイヤを返す
            return building_layer

        # リスクレイヤを統合（同じ建物に対して最大浸水深を計算）
        merged_risk_layer = self.merge_risk_layers(risk_layers, join_field)

        # 統合したリスクレイヤを建物レイヤと結合
        result = processing.run(
            "native:joinattributestable",
            {
                'INPUT': building_layer,
                'FIELD': 'id',
                'INPUT_2': merged_risk_layer,
                'FIELD_2': join_field,
                'FIELDS_TO_COPY': ['depth'],  # 浸水深のフィールドのみ結合
                'METHOD': 0,  # Left Join
                'DISCARD_NONMATCHING': False,
                'PREFIX': '',
                'OUTPUT': 'memory:',
            },
        )
        joined_layer = result['OUTPUT']

        # 浸水深のフィールドを追加
        joined_layer.dataProvider().addAttributes(
            [QgsField(depth_field_name, QVariant.Double)]
        )
        joined_layer.updateFields()

        # 全件一括で浸水深を更新
        updates = {}

        for _, feature in enumerate(joined_layer.getFeatures()):
            max_depth = feature['depth']  # 浸水深を取得
            updates[feature.id()] = {
                joined_layer.fields().indexOf(depth_field_name): max_depth
            }

        # 一括更新
        if not joined_layer.dataProvider().changeAttributeValues(updates):
            raise Exception(self.tr("Failed to bulk update features."))

        # 重複フィールド（depth）を削除
        provider = joined_layer.dataProvider()
        fields_to_remove = [
            field.name()
            for field in joined_layer.fields()
            if field.name() in ['depth']
        ]
        provider.deleteAttributes(
            [joined_layer.fields().indexOf(name) for name in fields_to_remove]
        )
        joined_layer.updateFields()

        return joined_layer

    def merge_risk_layers(self, risk_layers, join_field):
        """複数のリスクレイヤを統合し、最大浸水深を計算"""
        risk_features = {}
        for risk_layer in risk_layers:
            for feature in risk_layer.getFeatures():
                parent_id = feature[join_field]
                depth = feature['depth']
                if parent_id in risk_features:
                    # 同じ建物の最大浸水深を保持
                    risk_features[parent_id] = max(
                        risk_features[parent_id], depth
                    )
                else:
                    risk_features[parent_id] = depth

        # 統合レイヤを作成
        merged_layer = QgsVectorLayer(
            "Point?crs=EPSG:4326", "merged_risk_layer", "memory"
        )
        provider = merged_layer.dataProvider()
        # 必要なフィールドのみ設定
        provider.addAttributes(
            [
                QgsField(join_field, QVariant.String),
                QgsField('depth', QVariant.Double),
            ]
        )
        merged_layer.updateFields()

        # 統合データを追加
        new_features = []
        for parent_id, depth in risk_features.items():
            new_feature = QgsFeature()
            new_feature.setAttributes([parent_id, depth])
            new_features.append(new_feature)
        provider.addFeatures(new_features)

        return merged_layer

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
