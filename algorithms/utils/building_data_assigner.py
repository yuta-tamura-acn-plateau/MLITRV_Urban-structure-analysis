"""
/***************************************************************************
 *
 * 【FN006】建築物LOD1へのデータ付与機能
 *
 ***************************************************************************/
"""

import re

import processing
from qgis.core import (
    QgsCoordinateTransform,
    QgsProject,
    QgsFeatureRequest,
    QgsField,
    QgsSpatialIndex,
    QgsVectorLayer,
    Qgis,
    QgsMessageLog,
)
from PyQt5.QtCore import QCoreApplication, QVariant

from .gpkg_manager import GpkgManager


class BuildingDataAssigner:
    """建築物LOD1へのデータ付与機能"""
    def __init__(self, base_path, check_canceled_callback=None):
        self.gpkg_manager = GpkgManager._instance
        self.base_path = base_path
        self.check_canceled = check_canceled_callback

    def tr(self, message):
        """翻訳用のメソッド"""
        return QCoreApplication.translate(self.__class__.__name__, message)

    def exec(self):
        """データ付与処理実行"""
        self.assign_population_to_buildings()
        if self.check_canceled():
            return  # キャンセルチェック
        self.assign_vacant_to_buildings()

    def assign_population_to_buildings(self):
        """人口データの付与"""
        try:
            # buildings と meshes レイヤを取得
            buildings_layer = self.gpkg_manager.load_layer(
                'buildings', None, withload_project=False
            )
            meshes_layer = self.gpkg_manager.load_layer(
                'meshes', None, withload_project=False
            )

            # データソースと一致するレイヤをレイヤパネルから取得
            buildings_layer_uri = buildings_layer.dataProvider().dataSourceUri()
            project = QgsProject.instance()

            # レイヤパネルから一致するレイヤを検索
            buildings_layer = next(
                (
                    layer
                    for layer in project.mapLayers().values()
                    if isinstance(layer, QgsVectorLayer)
                    and layer.dataProvider().dataSourceUri()
                    == buildings_layer_uri
                ),
                None,
            )

            # CRSの違いを考慮
            transform = None
            if buildings_layer.crs() != meshes_layer.crs():
                transform = QgsCoordinateTransform(
                    meshes_layer.crs(),
                    buildings_layer.crs(),
                    QgsProject.instance(),
                )

            # population_fieldsを正規表現でフィルタリング
            attribute_names = [field.name() for field in meshes_layer.fields()]
            regex_pattern = (
                r'^('
                r'20\d{2}_(population|male|female|age_\d{1,2}(_male|_female)?)'
                r')|(future_20\d{2}_PT\w+)$'
            )

            population_fields = [
                attr
                for attr in attribute_names
                if re.match(regex_pattern, attr)
            ]

            # buildingsレイヤにフィールドを追加
            buildings_layer.startEditing()
            for field in population_fields:
                if buildings_layer.fields().indexFromName(field) == -1:
                    buildings_layer.dataProvider().addAttributes(
                        [QgsField(field, QVariant.Double)]
                    )
            buildings_layer.updateFields()

            # 空間インデックスを作成
            spatial_index = QgsSpatialIndex(buildings_layer.getFeatures())

            processed_count = 0  # 按分処理済建物数
            attribute_updates = {}

            # メッシュごとに処理
            for mesh_feature in meshes_layer.getFeatures():
                if self.check_canceled():
                    return  # キャンセルチェック
                mesh_geom = mesh_feature.geometry()

                if transform:
                    mesh_geom.transform(transform)

                # メッシュ内の建物を検索
                building_ids = spatial_index.intersects(
                    mesh_geom.boundingBox())
                if not building_ids:
                    continue

                request = QgsFeatureRequest().setFilterFids(building_ids)
                total_living_area = 0
                buildings_in_mesh = []

                # メッシュ内の建物の居住部分の総床面積を計算
                for building_feature in buildings_layer.getFeatures(request):
                    if self.check_canceled():
                        return  # キャンセルチェック
                    building_geom = building_feature.geometry()

                    # 建物の重心を取得して、メッシュ内に存在するかを確認
                    building_centroid = building_geom.centroid()
                    if mesh_geom.contains(building_centroid):
                        usage = building_feature['usage']

                        # 建築面積（total_floor_area）が10㎡未満ならスキップ
                        total_floor_area = float(
                            building_feature['total_floor_area'] or 0.0
                        )
                        if total_floor_area < 10:
                            continue

                        if usage in [
                            '住宅',
                            '共同住宅',
                            '店舗等併用住宅',
                            '店舗等併用共同住宅',
                            '作業所併用住宅',
                        ]:
                            living_area = self.__calculate_living_area(
                                building_feature
                            )
                            total_living_area += living_area
                            buildings_in_mesh.append(
                                (building_feature, living_area)
                            )

                # 各建物に対して人口を按分して計算
                if total_living_area > 0:
                    if self.check_canceled():
                        return  # キャンセルチェック
                    processed_count += len(buildings_in_mesh)
                    for building_feature, living_area in buildings_in_mesh:
                        building_population = {}

                        for field in population_fields:
                            field_id = buildings_layer.fields().indexFromName(
                                field
                            )  # フィールドIDを取得
                            if field_id == -1:
                                msg = self.tr(
                                    "The field %1 does not exist."
                                ).replace("%1", field)
                                QgsMessageLog.logMessage(
                                    msg,
                                    self.tr("Plugin"),
                                    Qgis.Critical,
                                )
                                continue

                            value = mesh_feature[field]

                            current_value = building_feature[field]
                            if (
                                isinstance(current_value, QVariant)
                                and current_value.isNull()
                            ):
                                current_value = 0
                            else:
                                current_value = float(current_value or 0)

                            value = float(value or 0)

                            # 按分して人口を加算
                            building_population[field_id] = (
                                current_value
                                + value * (living_area / total_living_area)
                            )

                        # 更新データを一時的に保持
                        fid = building_feature.id()
                        if fid not in attribute_updates:
                            attribute_updates[fid] = {}
                        attribute_updates[fid].update(building_population)

            buildings_layer.dataProvider().changeAttributeValues(
                attribute_updates
            )
            buildings_layer.commitChanges()

            msg = self.tr("Completed attaching population to buildings.")
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

    def assign_vacant_to_buildings(self):
        """空き家データの付与"""
        try:
            # buildings と vacancies レイヤを取得
            buildings_layer = self.gpkg_manager.load_layer(
                'buildings', None, withload_project=False
            )
            vacancies_layer = self.gpkg_manager.load_layer(
                'vacancies', None, withload_project=False
            )

            # データソースと一致するレイヤをレイヤパネルから取得
            buildings_layer_uri = buildings_layer.dataProvider().dataSourceUri()
            project = QgsProject.instance()

            # レイヤパネルから一致するレイヤを検索
            buildings_layer = next(
                (
                    layer
                    for layer in project.mapLayers().values()
                    if isinstance(layer, QgsVectorLayer)
                    and layer.dataProvider().dataSourceUri()
                    == buildings_layer_uri
                ),
                None,
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

            # 空き家フラグフィールドを一括追加
            buildings_layer.startEditing()
            for year in unique_years:
                field_name = f"{year}_is_vacancy"
                if buildings_layer.fields().indexFromName(field_name) == -1:
                    buildings_layer.dataProvider().addAttributes(
                        [QgsField(field_name, QVariant.Int)]
                    )
            buildings_layer.updateFields()

            # 各年度ごとの処理
            for year in unique_years:
                if self.check_canceled():
                    return  # キャンセルチェック

                # vacanciesレイヤから該当年度の空き家ポイントを抽出
                target_year = min(
                    [
                        int(y)
                        for y in {
                            f['year']
                            for f in vacancies_layer.getFeatures()
                            if f['year']
                        }
                        if int(y) >= int(year)
                    ],
                    default=None,
                )
                if target_year is None:
                    msg = self.tr(
                        "No vacant house points were found for the year %1."
                    ).replace("%1", str(year))
                    QgsMessageLog.logMessage(
                        msg,
                        self.tr("Plugin"),
                        Qgis.Warning,
                    )
                    continue

                # 該当年度で空き家ポイントレイヤをフィルタリング
                expression = f'"year" = \'{target_year}\''
                filtered_vacancies = processing.run(
                    "native:extractbyexpression",
                    {
                        'INPUT': vacancies_layer,
                        'EXPRESSION': expression,
                        'OUTPUT': 'TEMPORARY_OUTPUT',
                    },
                )['OUTPUT']

                # 建物レイヤに空き家フラグを空間結合で追加
                join_field = f"{year}_is_vacancy"
                joined_layer = processing.run(
                    "native:joinattributesbylocation",
                    {
                        'INPUT': buildings_layer,
                        'JOIN': filtered_vacancies,
                        'PREDICATE': [1],  # contain
                        'JOIN_FIELDS': [],
                        'METHOD': 1,  # 元の建物の属性を更新
                        'DISCARD_NONMATCHING': False,
                        'PREFIX': 'vacancy_',
                        'OUTPUT': 'memory:',
                    },
                )['OUTPUT']

                # 空き家フラグフィールドの更新
                attribute_updates = {}
                for building_feature in joined_layer.getFeatures():
                    fid = building_feature.id()
                    is_vacant = 1 if building_feature['vacancy_year'] else 0
                    attribute_updates[fid] = {
                        buildings_layer.fields().indexFromName(
                            join_field
                        ): is_vacant
                    }

                # 一括で属性を更新
                buildings_layer.dataProvider().changeAttributeValues(
                    attribute_updates
                )

            # コミット
            buildings_layer.commitChanges()
            msg = self.tr("Completed setting vacant house flags.")
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

    def __calculate_living_area(self, building_feature):
        """建物の住居部分床面積を計算する"""
        total_floor_area = float(building_feature['total_floor_area'] or 0.0)
        storeys_above_ground = int(
            building_feature['storeys_above_ground'] or 1
        )
        storeys_below_ground = int(
            building_feature['storeys_below_ground'] or 0
        )
        storeys = storeys_above_ground + storeys_below_ground

        if storeys == 1:
            living_area_ratio = 0.5
        else:
            living_area_ratio = (
                storeys_above_ground - storeys_below_ground - 1
            ) / storeys_above_ground

        living_area = total_floor_area * living_area_ratio
        return living_area
