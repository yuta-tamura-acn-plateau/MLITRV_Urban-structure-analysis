"""
/***************************************************************************
 *
 * 【FN007】圏域作成機能
 *
 ***************************************************************************/
"""

import os
import traceback
import heapq

import processing
import chardet
from qgis.core import (
    QgsMessageLog,
    Qgis,
    QgsVectorLayer,
    QgsField,
    QgsFeature,
    QgsProject,
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
    QgsGeometry,
    QgsPointXY,
    QgsWkbTypes,
    QgsFeatureRequest,
)
from qgis.analysis import QgsGraphBuilder
from PyQt5.QtCore import QCoreApplication, QVariant
from PyQt5.QtWidgets import QApplication
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from .gpkg_manager import GpkgManager

class AreaDataGenerator:
    """圏域作成機能"""
    def __init__(
        self,
        base_path,
        threshold_bus,
        threshold_railway,
        threshold_shelter,
        check_canceled_callback=None,
    ):
        # GeoPackageマネージャーを初期化
        self.gpkg_manager = GpkgManager._instance
        # インプットデータパス
        self.base_path = base_path
        # 閾値の設定
        self.threshold_bus = float(threshold_bus)
        self.threshold_railway = float(threshold_railway)
        self.threshold_shelter = float(threshold_shelter)

        self.check_canceled = check_canceled_callback

    def tr(self, message):
        """翻訳用のメソッド"""
        return QCoreApplication.translate(self.__class__.__name__, message)

    def create_area_data(self):
        """圏域作成処理"""
        self.create_station_coverage_area()
        if self.check_canceled():
            return  # キャンセルチェック
        self.create_bus_stop_coverage_area()
        if self.check_canceled():
            return  # キャンセルチェック
        self.create_shelter()
        if self.check_canceled():
            return  # キャンセルチェック
        self.create_shelter_area()
        if self.check_canceled():
            return  # キャンセルチェック
        self.create_urban_function_induction_area()
        if self.check_canceled():
            return  # キャンセルチェック
        self.create_urbun_planning_area()
        if self.check_canceled():
            return  # キャンセルチェック
        self.create_land_use_area()
        if self.check_canceled():
            return  # キャンセルチェック
        self.create_hazard_area_planned_scale()
        if self.check_canceled():
            return  # キャンセルチェック
        self.create_hazard_area_max_scale()
        if self.check_canceled():
            return  # キャンセルチェック
        self.create_hazard_area_storm_surge()
        if self.check_canceled():
            return  # キャンセルチェック
        self.create_hazard_area_tsunami()
        if self.check_canceled():
            return  # キャンセルチェック
        self.create_hazard_area_landslide()
        if self.check_canceled():
            return  # キャンセルチェック
        self.create_hazard_area_floodplain()

    def create_station_coverage_area(self):
        """鉄道駅カバー圏域作成"""
        try:
            # railway_stations レイヤを取得
            railway_layer = self.gpkg_manager.load_layer(
                'railway_stations', None, withload_project=False
            )

            if not railway_layer.isValid():
                layer_name = self.tr("railway_stations")
                raise Exception(
                    self.tr(
                        "The %1 layer is invalid."
                    ).replace("%1", layer_name)
                )


            # バッファの距離
            buffer_distance = self.threshold_railway  # 閾値（単位: m）

            # 投影座標系に変換
            target_crs = QgsCoordinateReferenceSystem('EPSG:3857')
            transform = QgsCoordinateTransform(
                railway_layer.crs(), target_crs, QgsProject.instance()
            )

            # railway_stationsレイヤと同じCRSを使用してメモリレイヤを作成
            buffer_layer = QgsVectorLayer(
                f"Polygon?crs={target_crs.authid()}",
                "railway_station_buffers",
                "memory",
            )
            buffer_provider = buffer_layer.dataProvider()

            # railway_stationsの属性を保持、閾値の属性を追加
            buffer_provider.addAttributes(
                railway_layer.fields()
            )  # 駅の既存フィールド
            buffer_provider.addAttributes(
                [QgsField("buffer_distance", QVariant.Double)]
            )  # 閾値フィールド
            buffer_layer.updateFields()

            # フィーチャごとにバッファを作成
            for station in railway_layer.getFeatures():
                station_geom = station.geometry()

                # 座標系変換を適用
                station_geom.transform(transform)

                # 投影座標系でバッファを計算
                buffer_geom = station_geom.buffer(
                    float(buffer_distance), 5
                )  # バッファ作成

                buffer_feature = QgsFeature()
                buffer_feature.setGeometry(buffer_geom)

                # 元の属性をそのままコピー
                station_attributes = station.attributes()
                station_attributes.append(float(buffer_distance))

                # 属性を設定
                buffer_feature.setAttributes(station_attributes)

                # フィーチャを追加
                buffer_provider.addFeature(buffer_feature)

            # GeoPackage に保存
            if not self.gpkg_manager.add_layer(
                buffer_layer, "railway_station_buffers", "鉄道駅カバー圏域"
            ):
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            data_name = self.tr("railway station buffer")
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

    def create_bus_stop_coverage_area(self):
        """バス停カバー圏域作成"""
        try:
            # bus_stops レイヤを取得
            bus_layer = self.gpkg_manager.load_layer(
                'bus_stops', None, withload_project=False
            )

            if not bus_layer.isValid():
                layer_name = self.tr("bus_stops")
                raise Exception(
                    self.tr(
                        "The %1 layer is invalid."
                    ).replace("%1", layer_name)
                )

            # バッファの距離
            buffer_distance = self.threshold_bus  # 閾値（単位: m）

            # 投影座標系に変換
            target_crs = QgsCoordinateReferenceSystem('EPSG:3857')
            transform = QgsCoordinateTransform(
                bus_layer.crs(), target_crs, QgsProject.instance()
            )

            # bus_stopsレイヤと同じCRSを使用してメモリレイヤを作成
            buffer_layer = QgsVectorLayer(
                f"Polygon?crs={target_crs.authid()}",
                "bus_stop_buffers",
                "memory",
            )
            buffer_provider = buffer_layer.dataProvider()

            # bus_stopsの属性を保持、閾値の属性を追加
            buffer_provider.addAttributes(
                bus_layer.fields()
            )  # バス停の既存フィールド
            buffer_provider.addAttributes(
                [QgsField("buffer_distance", QVariant.Double)]
            )  # 閾値フィールド
            buffer_layer.updateFields()

            # フィーチャごとにバッファを作成
            for stop in bus_layer.getFeatures():
                stop_geom = stop.geometry()

                # 座標系変換を適用
                stop_geom.transform(transform)

                # 投影座標系でバッファを計算
                buffer_geom = stop_geom.buffer(
                    float(buffer_distance), 5
                )  # バッファ作成

                buffer_feature = QgsFeature()
                buffer_feature.setGeometry(buffer_geom)

                # 元の属性をそのままコピー
                stop_attributes = stop.attributes()
                stop_attributes.append(float(buffer_distance))

                # 属性を設定
                buffer_feature.setAttributes(stop_attributes)

                # フィーチャを追加
                buffer_provider.addFeature(buffer_feature)

            # GeoPackage に保存
            if not self.gpkg_manager.add_layer(
                buffer_layer, "bus_stop_buffers", "バス停カバー圏域"
            ):
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            data_name = self.tr("bus stop buffer")
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

    def create_shelter(self):
        """避難施設作成"""
        try:
            # base_path 配下の「避難所」フォルダを再帰的に探索してShapefileを収集
            induction_area_folder = os.path.join(self.base_path, "避難所")
            shp_files = self.__get_shapefiles(induction_area_folder)

            # レイヤを格納するリスト
            layers = []

            for shp_file in shp_files:
                encoding = self.__detect_encoding(shp_file)

                # Shapefile 読み込み
                layer = QgsVectorLayer(
                    shp_file, os.path.basename(shp_file), "ogr"
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

                # Shapefileの属性フィールドバリデーション
                layer_fields = set(layer.fields().names())
                required_fields = {
                    "P20_001",
                    "P20_002",
                    "P20_003",
                    "P20_004",
                    "P20_005",
                    "P20_006",
                    "P20_007",
                    "P20_008",
                }

                if not required_fields.issubset(layer_fields):
                    data_name = self.tr("shelter")
                    msg = (
                        self.tr("%1 cannot be loaded as %2 data.")
                        .replace("%1", shp_file)
                        .replace("%2", data_name)
                    )
                    QgsMessageLog.logMessage(
                        msg,
                        self.tr("Plugin"),
                        Qgis.Warning,
                    )
                    continue

                # 一時メモリレイヤを作成し、Shapefileのデータを取り込み
                temp_layer = QgsVectorLayer(
                    f"Point?crs={layer.crs().authid()}", "shelters", "memory"
                )
                temp_provider = temp_layer.dataProvider()

                # 必要なフィールドを追加
                temp_provider.addAttributes(
                    [
                        QgsField("code", QVariant.String),
                        QgsField("name", QVariant.String),
                        QgsField("address", QVariant.String),
                        QgsField("type", QVariant.String),
                        QgsField("capacity", QVariant.Int),
                        QgsField("scale", QVariant.Int),
                        QgsField("earthquake", QVariant.Int),
                        QgsField("tunami", QVariant.Int),
                    ]
                )
                temp_layer.updateFields()

                # フィーチャの追加
                for feature in layer.getFeatures():
                    new_feature = QgsFeature()
                    new_feature.setGeometry(feature.geometry())

                    # 属性データのマッピング
                    attributes = [
                        feature["P20_001"],  # code
                        feature["P20_002"],  # name
                        feature["P20_003"],  # address
                        feature["P20_004"],  # type
                        feature["P20_005"],  # capacity
                        feature["P20_006"],  # scale
                        feature["P20_007"],  # earthquake
                        feature["P20_008"],  # tunami
                    ]
                    new_feature.setAttributes(attributes)
                    temp_provider.addFeature(new_feature)

                layers.append(temp_layer)

            if not layers:
                data_name = self.tr("shelter")
                msg = (
                    self.tr("No valid %1 Shapefile was found.")
                    .replace("%1", data_name)
                )
                QgsMessageLog.logMessage(
                    msg,
                    self.tr("Plugin"),
                    Qgis.Info,
                )

                # 一時メモリレイヤを作成
                temp_layer = QgsVectorLayer(
                    "Polygon", "land_prices", "memory")
                temp_provider = temp_layer.dataProvider()

                # 必要なフィールドを追加
                temp_provider.addAttributes(
                    [
                        QgsField("rank", QVariant.String),
                    ]
                )
                temp_layer.updateFields()
                layers.append(temp_layer)

            # 複数のレイヤをマージ
            merged_layer = self.__merge_layers(layers)

            # sheltersレイヤをGeoPackageに保存
            if not self.gpkg_manager.add_layer(
                merged_layer, "shelters", "避難施設"
            ):
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            data_name = self.tr("shelter")
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

    def create_shelter_area(self):
        """避難施設圏域作成"""
        try:
            # 既存のsheltersレイヤをレイヤパネルから取得
            shelters_layer = self.gpkg_manager.load_layer(
                'shelters', None, withload_project=False
            )
            if not shelters_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                    .replace("%1", "shelters"))

            # 道路ネットワークデータ（ロードネットワークレイヤ）をレイヤパネルから取得
            road_network_layer = self.gpkg_manager.load_layer(
                'road_networks', None, withload_project=False
            )
            if not road_network_layer:
                raise Exception(self.tr("The %1 layer was not found.")
                    .replace("%1", "road_networks"))

            distance = self.threshold_shelter

            # 一時メモリレイヤの作成 (Polygonタイプ)
            tmp_buffer_layer = QgsVectorLayer(
                "Polygon?crs=EPSG:3857", "tmp_shelter_area", "memory"
            )
            temp_buffer_provider = tmp_buffer_layer.dataProvider()
            # 必要なフィールドを追加
            temp_buffer_provider.addAttributes(
                [QgsField("shelter_id", QVariant.String)]
            )
            tmp_buffer_layer.updateFields()

            # shelter_buffersレイヤを作成
            shelter_buffer_layer = QgsVectorLayer(
                "Polygon?crs=EPSG:3857", "shelter_buffers", "memory"
            )
            shelter_buffer_provider = shelter_buffer_layer.dataProvider()
            shelter_buffer_provider.addAttributes(
                [QgsField("shelter_id", QVariant.String)]
            )
            shelter_buffer_layer.updateFields()

            target_crs = QgsCoordinateReferenceSystem("EPSG:3857")

            # 避難所を投影座標系へ変換
            shelters_layer = processing.run(
                "native:reprojectlayer",
                {
                    'INPUT': shelters_layer,
                    'TARGET_CRS': target_crs,  # オブジェクトを使用
                    'OUTPUT': 'memory:',  # 一時メモリレイヤとして出力
                },
            )['OUTPUT']

            if self.check_canceled():
                return  # キャンセルチェック

            # 道路ネットワークを投影座標系へ変換
            road_network_layer = processing.run(
                "native:reprojectlayer",
                {
                    'INPUT': road_network_layer,
                    'TARGET_CRS': target_crs,  # オブジェクトを使用
                    'OUTPUT': 'memory:',  # 一時メモリレイヤとして出力
                },
            )['OUTPUT']

            if self.check_canceled():
                return  # キャンセルチェック

            shelter_count = 0  # 処理した避難所のカウント用変数
            # 各避難施設のフィーチャに対して徒歩圏バッファを作成
            for shelter_feature in shelters_layer.getFeatures():
                shelter_geometry = shelter_feature.geometry()

                # 一時的にバッファを作成
                buffer = shelter_geometry.buffer(distance, segments=8)

                # バッファ内の道路を取得
                request = QgsFeatureRequest().setFilterRect(
                    buffer.boundingBox()
                )
                nearby_roads = road_network_layer.getFeatures(request)
                nearby_roads = list(nearby_roads)

                # 道路ネットワークのノード情報を取得
                crs = road_network_layer.crs()

                node_graph = self.__extract_road_nodes(nearby_roads, crs)

                point_geom = shelter_feature.geometry()
                if point_geom.type() == QgsWkbTypes.PointGeometry:
                    point = shelter_feature.geometry().asPoint()
                else:
                    msg = self.tr(
                        "Shelter geometry is not a Point: %1"
                    ).replace("%1", point_geom.asWkt())
                    QgsMessageLog.logMessage(
                        msg,
                        self.tr("Plugin"),
                        Qgis.Warning,
                    )

                # 避難所の属性 'scale' に基づいて経路開始地点(k)の数を決定
                shelter_scale = shelter_feature['scale']  # 避難所の規模を取得
                k = (
                    1 if shelter_scale == -1 else 3
                )  # 'scale'（施設規模） が -1 なら k=1、それ以外なら k=3 とする

                # 避難所の座標に最も近い道路ノードを取得
                nearest_nodes = self.nearest_point(
                    node_graph, point, k=k
                )  # k に基づいて調整

                # ダイクストラ法を実行し、バッファ範囲を計算
                buffer_distance = 200  # 道路に対して200mのバッファサイズ
                merge_searched_road = self.dijkstra(
                    node_graph, nearest_nodes, distance, [], buffer_distance
                )

                if self.check_canceled():
                    break  # キャンセルチェック

                # ダイクストラで計算されたバッファポリゴンをレイヤに追加
                for buffered_polygon in merge_searched_road:
                    shelter_buffer_feature = QgsFeature()

                    # バッファポリゴンをセット
                    if isinstance(
                        buffered_polygon, Polygon
                    ):  # ポリゴンかどうかをチェック
                        shelter_buffer_feature.setGeometry(
                            QgsGeometry.fromWkt(buffered_polygon.wkt)
                        )
                        shelter_buffer_feature.setAttributes(
                            [str(shelter_feature["fid"])]
                        )
                        shelter_buffer_provider.addFeature(
                            shelter_buffer_feature
                        )
                        shelter_buffer_layer.updateExtents()  # レイヤの範囲を更新
                    else:
                        print(self.tr(
                            "AreaDataGenerator: Buffered object "
                            "is not a polygon."
                        ))

                shelter_count += 1
                if (shelter_count % 100) == 0:
                    QApplication.processEvents()

            # shelter_buffersレイヤをGeoPackageに保存
            if not self.gpkg_manager.add_layer(
                shelter_buffer_layer, "shelter_buffers", "避難施設カバー圏域"
            ):
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            data_name = self.tr("shelter buffer")
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

    def __extract_road_nodes(self, roads, crs):
        """道路ネットワークレイヤからノード情報を抽出し、グラフを構築するメソッド"""

        # グラフビルダーの設定（CRSは道路レイヤと同じ）
        builder = QgsGraphBuilder(crs)

        total_count = 0
        linestring_count = 0
        vertex_map = {}  # 頂点IDを管理するマップ
        vertex_id_counter = 0  # 頂点IDカウンター

        # 道路フィーチャを処理
        for road_feature in roads:
            total_count += 1
            road_geom = road_feature.geometry()

            if road_geom.isEmpty():
                QgsMessageLog.logMessage(
                    self.tr("Empty geometry for road feature."),
                    self.tr("Plugin"),
                    Qgis.Warning,
                )
                continue

            # ジオメトリのタイプを確認
            geom_type = road_geom.wkbType()

            if geom_type in (
                QgsWkbTypes.LineString,
                QgsWkbTypes.MultiLineString,
            ):
                if geom_type == QgsWkbTypes.MultiLineString:
                    lines = road_geom.asMultiPolyline()
                else:
                    lines = [road_geom.asPolyline()]

                # 各ラインの処理
                for line in lines:
                    if len(line) < 2:
                        continue  # ラインが2点未満の場合はスキップ

                    for i in range(len(line) - 1):
                        p1 = QgsPointXY(line[i])
                        p2 = QgsPointXY(line[i + 1])

                        # p1, p2のIDを生成、または既存のIDを取得
                        if p1 not in vertex_map:
                            vertex_map[p1] = vertex_id_counter
                            builder.addVertex(vertex_id_counter, p1)
                            vertex_id_counter += 1
                        if p2 not in vertex_map:
                            vertex_map[p2] = vertex_id_counter
                            builder.addVertex(vertex_id_counter, p2)
                            vertex_id_counter += 1

                        id1 = vertex_map[p1]
                        id2 = vertex_map[p2]

                        # ノード間のエッジを追加
                        builder.addEdge(
                            id1,
                            p1,
                            id2,
                            p2,
                            [QgsGeometry.fromPolylineXY([p1, p2]).length()],
                        )

                        linestring_count += 1
            else:
                msg = self.tr(
                    "Unsupported geometry type: %1"
                ).replace("%1", geom_type)
                QgsMessageLog.logMessage(
                    msg,
                    self.tr("Plugin"),
                    Qgis.Warning,
                )
                continue

        # グラフを作成
        graph = builder.graph()

        return graph  # ノードとエッジが含まれたグラフを返す

    def calculate_meter(self, starting_point, destination):
        """
        starting_point,からdestinationまでの距離を測る
        """
        point_geom = QgsGeometry.fromPointXY(
            QgsPointXY(starting_point[0], starting_point[1])
        )
        dest_geom = QgsGeometry.fromPointXY(
            QgsPointXY(destination[0], destination[1])
        )

        # メートル単位の距離
        distance = point_geom.distance(dest_geom)
        return distance

    def dijkstra(
        self, graph, start_points, max_distance, shelters_inf, buffer_distance
    ):
        """
        ダイクストラ法を使用した開始位置から各ノードへの最短距離の探索
        """
        searched_list = set()
        searched_roads = []
        merge_searched_road = []

        priority_queue = []

        for start in start_points:
            priority_queue.append((0, (start.x(), start.y())))

        heapq.heapify(priority_queue)

        while priority_queue:
            # 最小の値を持つノードを取得
            current_distance, current_node = heapq.heappop(priority_queue)

            # ノードを探索済みリストに追加
            if current_node in searched_list:
                continue
            searched_list.add(current_node)

            # 最大距離を超えた場合の処理
            if current_distance > max_distance:
                continue

            # ノードIDを取得
            vertex_id = graph.findVertex(
                QgsPointXY(current_node[0], current_node[1])
            )
            if vertex_id == -1:
                # ノードが見つからない場合はスキップ
                continue

            # エッジの探索
            for edge_idx in (
                graph.vertex(vertex_id).outgoingEdges()
                + graph.vertex(vertex_id).incomingEdges()
            ):
                edge = graph.edge(edge_idx)
                start_node = graph.vertex(edge.fromVertex()).point()
                end_node = graph.vertex(edge.toVertex()).point()

                # エッジのコストを取得
                length = edge.cost(0)

                next_node = None
                if (current_node[0], current_node[1]) == (
                    start_node.x(),
                    start_node.y(),
                ):
                    next_node = end_node
                elif (current_node[0], current_node[1]) == (
                    end_node.x(),
                    end_node.y(),
                ):
                    next_node = start_node
                else:
                    continue

                # 距離の計算
                new_distance = current_distance + length

                if (
                    next_node not in searched_list
                    and new_distance <= max_distance
                ):
                    heapq.heappush(
                        priority_queue,
                        (new_distance, (next_node.x(), next_node.y())),
                    )

                    # バッファの計算
                    if new_distance <= max_distance:
                        buff = (
                            buffer_distance
                            * (max_distance - new_distance)
                            / max_distance
                        )
                        line = LineString(
                            [
                                QgsPointXY(start_node.x(), start_node.y()),
                                QgsPointXY(end_node.x(), end_node.y()),
                            ]
                        )
                        buffered_line = line.buffer(buff)

                        searched_roads.append(buffered_line)

        # 全ての道路ポリゴンを結合して返す
        merge_searched_road.append(unary_union(searched_roads))
        return merge_searched_road

    def nearest_point(self, node_graph, point, k):
        """
        指定座標からk番目までに近いノードを見つける
        node_graph   : QgsGraph
            ノードデータを持つグラフ
        point        : QgsPointXY
            指定座標
        k            : int
            何番目まで近い点を見つけるか

        return
        nearest_points   : list
            k番目までの近いノード座標
        """
        # 初期値の設定
        nearest = []
        nearest_points = []
        for i in range(k):
            nearest.append(float('inf'))  # 非常に大きい値で初期化
            nearest_points.append(point)

        # ノードリストを取得
        for vertex_id in range(node_graph.vertexCount()):
            node_point = node_graph.vertex(vertex_id).point()
            distance = self.calculate_meter(
                (point.x(), point.y()), (node_point.x(), node_point.y())
            )

            # 一番近い値をk個まで保持
            if distance < max(nearest):
                max_idx = nearest.index(max(nearest))  # 最も遠い現在の値を更新
                nearest[max_idx] = distance
                nearest_points[max_idx] = node_point

        return nearest_points

    def create_urban_function_induction_area(self):
        """都市機能誘導区域/居住誘導区域 作成"""
        try:
            # base_path 配下の「誘導区域」フォルダを再帰的に探索してShapefileを収集
            induction_area_folder = os.path.join(self.base_path, "誘導区域")
            shp_files = self.__get_shapefiles(induction_area_folder)

            if not shp_files:
                data_name = self.tr("induction area")
                msg = (
                    self.tr("No Shapefile found for the %1.")
                    .replace("%1", data_name)
                )
                QgsMessageLog.logMessage(
                    msg,
                    self.tr("Plugin"),
                    Qgis.Warning,
                )
                return False

            # レイヤを格納するリスト
            layers = []

            for shp_file in shp_files:
                if self.check_canceled():
                    return  # キャンセルチェック
                encoding = self.__detect_encoding(shp_file)

                # Shapefile 読み込み
                layer = QgsVectorLayer(
                    shp_file, os.path.basename(shp_file), "ogr"
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

                # Shapefileの属性フィールドバリデーション
                layer_fields = set(layer.fields().names())
                required_fields = {
                    "区域区分",
                    "kubunID",
                    "Pref",
                    "Citycode",
                    "Cityname",
                    "当初決定日",
                    "最終告示日",
                    "決定区分",
                    "決定者",
                    "告示番号S",
                    "告示番号L",
                }

                if not required_fields.issubset(layer_fields):
                    data_name = self.tr("induction area")
                    msg = (
                        self.tr("%1 cannot be loaded as %2 data.")
                        .replace("%1", shp_file)
                        .replace("%2", data_name)
                    )
                    QgsMessageLog.logMessage(
                        msg,
                        self.tr("Plugin"),
                        Qgis.Warning,
                    )
                    continue

                # 一時メモリレイヤを作成し、Shapefileのデータを取り込み
                temp_layer = QgsVectorLayer(
                    f"Polygon?crs={layer.crs().authid()}",
                    "induction_areas",
                    "memory",
                )
                temp_provider = temp_layer.dataProvider()

                # 必要なフィールドを追加
                temp_provider.addAttributes(
                    [
                        QgsField("type", QVariant.String),
                        QgsField("type_id", QVariant.Int),
                        QgsField("prefecture_name", QVariant.String),
                        QgsField("city_code", QVariant.String),
                        QgsField("city_name", QVariant.String),
                        QgsField("first_decision_date", QVariant.String),
                        QgsField("last_decision_date", QVariant.String),
                        QgsField("decision_type", QVariant.Int),
                        QgsField("decider", QVariant.String),
                        QgsField("notice_number_s", QVariant.String),
                        QgsField("notice_number_l", QVariant.String),
                    ]
                )
                temp_layer.updateFields()

                # フィーチャの追加
                for feature in layer.getFeatures():
                    if self.check_canceled():
                        return  # キャンセルチェック
                    new_feature = QgsFeature()
                    new_feature.setGeometry(feature.geometry())

                    # 属性データのマッピング
                    attributes = [
                        feature["区域区分"],  # type
                        feature["kubunID"],  # type_id
                        feature["Pref"],  # prefecture_name
                        feature["Citycode"],  # city_code
                        feature["Cityname"],  # city_name
                        feature["当初決定日"],  # first_decision_date
                        feature["最終告示日"],  # last_decision_date
                        feature["決定区分"],  # decision_type
                        feature["決定者"],  # decider
                        feature["告示番号S"],  # notice_number_s
                        feature["告示番号L"],  # notice_number_l
                    ]
                    new_feature.setAttributes(attributes)
                    temp_provider.addFeature(new_feature)

                layers.append(temp_layer)

            if not layers:
                raise Exception(
                    "有効な立地適正化区域のShapefileが見つかりませんでした。"
                )

            # 複数のレイヤをマージ
            merged_layer = self.__merge_layers(layers)

            # induction_areasレイヤをGeoPackageに保存
            if not self.gpkg_manager.add_layer(
                merged_layer, "induction_areas", "誘導区域"
            ):
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            data_name = self.tr("induction area")
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

    def create_urbun_planning_area(self):
        """都市計画区域 作成"""
        try:
            # base_path 配下の「誘導区域」フォルダを再帰的に探索してShapefileを収集
            induction_area_folder = os.path.join(self.base_path, "誘導区域")
            shp_files = self.__get_shapefiles(induction_area_folder)

            if not shp_files:
                data_name = self.tr("induction area")
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

            # レイヤを格納するリスト
            layers = []

            for shp_file in shp_files:
                if self.check_canceled():
                    return  # キャンセルチェック
                encoding = self.__detect_encoding(shp_file)

                # Shapefile 読み込み
                layer = QgsVectorLayer(
                    shp_file, os.path.basename(shp_file), "ogr"
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

                # Shapefileの属性フィールドバリデーション
                layer_fields = set(layer.fields().names())
                required_fields = {
                    "tokeiname",
                    "Type",
                    "kubunID",
                    "Pref",
                    "Citycode",
                    "Cityname",
                    "当初決定日",
                    "最終告示日",
                    "決定区分",
                    "決定者",
                    "告示番号S",
                    "告示番号L",
                }

                if not required_fields.issubset(layer_fields):
                    data_name = self.tr("urbun planning")
                    msg = (
                        self.tr("%1 cannot be loaded as %2 data.")
                        .replace("%1", shp_file)
                        .replace("%2", data_name)
                    )
                    QgsMessageLog.logMessage(
                        msg,
                        self.tr("Plugin"),
                        Qgis.Warning,
                    )
                    continue

                # 一時メモリレイヤを作成し、Shapefileのデータを取り込み
                temp_layer = QgsVectorLayer(
                    f"Polygon?crs={layer.crs().authid()}",
                    "urbun_plannings",
                    "memory",
                )
                temp_provider = temp_layer.dataProvider()

                # 必要なフィールドを追加
                temp_provider.addAttributes(
                    [
                        QgsField("tokei_name", QVariant.String),
                        QgsField("type", QVariant.String),
                        QgsField("type_id", QVariant.Int),
                        QgsField("prefecture_name", QVariant.String),
                        QgsField("city_code", QVariant.String),
                        QgsField("city_name", QVariant.String),
                        QgsField("first_decision_date", QVariant.String),
                        QgsField("last_decision_date", QVariant.String),
                        QgsField("decision_type", QVariant.Int),
                        QgsField("decider", QVariant.String),
                        QgsField("notice_number_s", QVariant.String),
                        QgsField("notice_number_l", QVariant.String),
                    ]
                )
                temp_layer.updateFields()

                # フィーチャの追加
                for feature in layer.getFeatures():
                    if self.check_canceled():
                        return  # キャンセルチェック
                    new_feature = QgsFeature()
                    new_feature.setGeometry(feature.geometry())

                    # 属性データのマッピング
                    attributes = [
                        feature["tokeiname"],  # tokei_name
                        feature["type"],  # type
                        feature["kubunID"],  # type_id
                        feature["Pref"],  # prefecture_name
                        feature["Citycode"],  # city_code
                        feature["Cityname"],  # city_name
                        feature["当初決定日"],  # first_decision_date
                        feature["最終告示日"],  # last_decision_date
                        feature["決定区分"],  # decision_type
                        feature["決定者"],  # decider
                        feature["告示番号S"],  # notice_number_s
                        feature["告示番号L"],  # notice_number_l
                    ]
                    new_feature.setAttributes(attributes)
                    temp_provider.addFeature(new_feature)

                layers.append(temp_layer)

            if not layers:
                raise Exception(
                    "有効な都市計画区域のShapefileが見つかりませんでした。"
                )

            # 複数のレイヤをマージ
            merged_layer = self.__merge_layers(layers)

            # urbun_planningsレイヤをGeoPackageに保存
            if not self.gpkg_manager.add_layer(
                merged_layer, "urbun_plannings", "都市計画区域"
            ):
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            data_name = self.tr("urbun_planning")
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

    def create_land_use_area(self):
        """用途地域 作成"""
        try:
            # base_path 配下の「誘導区域」フォルダを再帰的に探索してShapefileを収集
            induction_area_folder = os.path.join(self.base_path, "誘導区域")
            shp_files = self.__get_shapefiles(induction_area_folder)

            if not shp_files:
                data_name = self.tr("induction area")
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

            # レイヤを格納するリスト
            layers = []

            for shp_file in shp_files:
                if self.check_canceled():
                    return  # キャンセルチェック
                encoding = self.__detect_encoding(shp_file)

                # Shapefile 読み込み
                layer = QgsVectorLayer(
                    shp_file, os.path.basename(shp_file), "ogr"
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

                # Shapefileの属性フィールドバリデーション
                layer_fields = set(layer.fields().names())
                required_fields = {
                    "用途地域",
                    "YoutoID",
                    "容積率",
                    "建ぺい率",
                    "Pref",
                    "Citycode",
                    "Cityname",
                    "当初決定日",
                    "最終告示日",
                    "決定区分",
                    "決定者",
                    "告示番号S",
                    "告示番号L",
                }

                if not required_fields.issubset(layer_fields):
                    data_name = self.tr("land use area")
                    msg = (
                        self.tr("%1 cannot be loaded as %2 data.")
                        .replace("%1", shp_file)
                        .replace("%2", data_name)
                    )
                    QgsMessageLog.logMessage(
                        msg,
                        self.tr("Plugin"),
                        Qgis.Warning,
                    )
                    continue

                # 一時メモリレイヤを作成し、Shapefileのデータを取り込み
                temp_layer = QgsVectorLayer(
                    f"Polygon?crs={layer.crs().authid()}",
                    "land_use_areas",
                    "memory",
                )
                temp_provider = temp_layer.dataProvider()

                # 必要なフィールドを追加
                temp_provider.addAttributes(
                    [
                        QgsField("type", QVariant.String),
                        QgsField("type_id", QVariant.Int),
                        QgsField("area_ratio", QVariant.String),
                        QgsField("bulding_coverage_ratio", QVariant.String),
                        QgsField("prefecture_name", QVariant.String),
                        QgsField("city_code", QVariant.String),
                        QgsField("city_name", QVariant.String),
                        QgsField("first_decision_date", QVariant.String),
                        QgsField("last_decision_date", QVariant.String),
                        QgsField("decision_type", QVariant.String),
                        QgsField("decider", QVariant.String),
                        QgsField("notice_number_s", QVariant.String),
                        QgsField("notice_number_l", QVariant.String),
                    ]
                )
                temp_layer.updateFields()

                # フィーチャの追加
                for feature in layer.getFeatures():
                    if self.check_canceled():
                        return  # キャンセルチェック
                    new_feature = QgsFeature()
                    new_feature.setGeometry(feature.geometry())

                    # 属性データのマッピング
                    attributes = [
                        feature["用途地域"],  # type
                        feature["YoutoID"],  # type_id
                        feature["容積率"],  # area_ratio
                        feature["建ぺい率"],  # bulding_coverage_ratio
                        feature["Pref"],  # prefecture_name
                        feature["Citycode"],  # city_code
                        feature["Cityname"],  # city_name
                        feature["当初決定日"],  # first_decision_date
                        feature["最終告示日"],  # last_decision_date
                        feature["決定区分"],  # decision_type
                        feature["決定者"],  # decider
                        feature["告示番号S"],  # notice_number_s
                        feature["告示番号L"],  # notice_number_l
                    ]
                    new_feature.setAttributes(attributes)
                    temp_provider.addFeature(new_feature)

                layers.append(temp_layer)

            if not layers:
                raise Exception(
                    "有効な用途地域のShapefileが見つかりませんでした。"
                )

            # 複数のレイヤをマージ
            merged_layer = self.__merge_layers(layers)

            # land_use_areasレイヤをGeoPackageに保存
            if not self.gpkg_manager.add_layer(
                merged_layer, "land_use_areas", "用途地域"
            ):
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            data_name = self.tr("land use area")
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

    def create_hazard_area_planned_scale(self):
        """ハザードエリア計画規模 作成"""
        try:
            # base_path 配下の「ハザードエリア計画規模」フォルダを再帰的に探索してShapefileを収集
            induction_area_folder = os.path.join(
                self.base_path, "ハザードエリア計画規模"
            )
            shp_files = self.__get_shapefiles(induction_area_folder)

            # レイヤを格納するリスト
            layers = []

            for shp_file in shp_files:
                if self.check_canceled():
                    return  # キャンセルチェック
                encoding = self.__detect_encoding(shp_file)

                # Shapefile 読み込み
                layer = QgsVectorLayer(
                    shp_file, os.path.basename(shp_file), "ogr"
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

                # Shapefileの属性フィールドバリデーション
                layer_fields = set(layer.fields().names())
                required_fields = {
                    "A31b_101",
                }

                if not required_fields.issubset(layer_fields):
                    data_name = self.tr("hazard area planned scales")
                    msg = (
                        self.tr("%1 cannot be loaded as %2 data.")
                        .replace("%1", shp_file)
                        .replace("%2", data_name)
                    )
                    QgsMessageLog.logMessage(
                        msg,
                        self.tr("Plugin"),
                        Qgis.Warning,
                    )
                    continue

                # 一時メモリレイヤを作成し、Shapefileのデータを取り込み
                temp_layer = QgsVectorLayer(
                    f"Polygon?crs={layer.crs().authid()}",
                    "hazard_area_planned_scales",
                    "memory",
                )
                temp_provider = temp_layer.dataProvider()

                # 必要なフィールドを追加
                temp_provider.addAttributes(
                    [
                        QgsField("rank", QVariant.String),
                    ]
                )
                temp_layer.updateFields()

                # フィーチャの追加
                for feature in layer.getFeatures():
                    if self.check_canceled():
                        return  # キャンセルチェック
                    new_feature = QgsFeature()
                    new_feature.setGeometry(feature.geometry())

                    # 属性データのマッピング
                    attributes = [
                        feature["A31b_101"],  # rank
                    ]
                    new_feature.setAttributes(attributes)
                    temp_provider.addFeature(new_feature)

                layers.append(temp_layer)

            if not layers:
                data_name = self.tr("hazard area planned scales")
                msg = (
                    self.tr("No valid %1 Shapefile was found.")
                    .replace("%1", data_name)
                )
                QgsMessageLog.logMessage(
                    msg,
                    self.tr("Plugin"),
                    Qgis.Info,
                )

                # 一時メモリレイヤを作成
                temp_layer = QgsVectorLayer(
                    "Polygon", "hazard_area_planned_scales", "memory"
                )
                temp_provider = temp_layer.dataProvider()

                # 必要なフィールドを追加
                temp_provider.addAttributes(
                    [
                        QgsField("rank", QVariant.String),
                    ]
                )
                temp_layer.updateFields()
                layers.append(temp_layer)

            # 複数のレイヤをマージ
            merged_layer = self.__merge_layers(layers)

            # 無効なジオメトリを修正する
            merged_layer = self.__fix_invalid_geometries(merged_layer)

            # 空間インデックス作成
            processing.run("native:createspatialindex",
                           {'INPUT': merged_layer})

            # ゾーンポリゴンを読み込む
            zones_layer = self.gpkg_manager.load_layer(
                'zones', None, withload_project=False
            )

            # ゾーンポリゴン範囲と交差するエリアのみを抽出
            extracted_layer = processing.run(
                "native:extractbylocation",
                {
                    'INPUT': merged_layer,
                    'PREDICATE': [0],  # intersects
                    'INTERSECT': zones_layer,
                    'OUTPUT': 'TEMPORARY_OUTPUT',
                },
            )['OUTPUT']

            # hazard_area_planned_scalesレイヤをGeoPackageに保存
            if not self.gpkg_manager.add_layer(
                extracted_layer,
                "hazard_area_planned_scales",
                "洪水浸水想定区域_計画規模_L1",
            ):
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            data_name = self.tr("hazard area planned scale")
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

    def create_hazard_area_max_scale(self):
        """ハザードエリア想定最大規模 作成"""
        try:
            # base_path 配下の「ハザードエリア想定最大規模」フォルダを再帰的に探索してShapefileを収集
            induction_area_folder = os.path.join(
                self.base_path, "ハザードエリア想定最大規模"
            )
            shp_files = self.__get_shapefiles(induction_area_folder)

            # レイヤを格納するリスト
            layers = []

            for shp_file in shp_files:
                if self.check_canceled():
                    return  # キャンセルチェック
                encoding = self.__detect_encoding(shp_file)

                # Shapefile 読み込み
                layer = QgsVectorLayer(
                    shp_file, os.path.basename(shp_file), "ogr"
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

                # Shapefileの属性フィールドバリデーション
                layer_fields = set(layer.fields().names())
                required_fields = {
                    "A31b_201",
                }

                if not required_fields.issubset(layer_fields):
                    data_name = self.tr("hazard area maximum scale")
                    msg = (
                        self.tr("%1 cannot be loaded as %2 data.")
                        .replace("%1", shp_file)
                        .replace("%2", data_name)
                    )
                    QgsMessageLog.logMessage(
                        msg,
                        self.tr("Plugin"),
                        Qgis.Warning,
                    )
                    continue

                # 一時メモリレイヤを作成し、Shapefileのデータを取り込み
                temp_layer = QgsVectorLayer(
                    f"Polygon?crs={layer.crs().authid()}",
                    "hazard_area_maximum_scales",
                    "memory",
                )
                temp_provider = temp_layer.dataProvider()

                # 必要なフィールドを追加
                temp_provider.addAttributes(
                    [
                        QgsField("rank", QVariant.String),
                    ]
                )
                temp_layer.updateFields()

                # フィーチャの追加
                for feature in layer.getFeatures():
                    if self.check_canceled():
                        return  # キャンセルチェック
                    new_feature = QgsFeature()
                    new_feature.setGeometry(feature.geometry())

                    # 属性データのマッピング
                    attributes = [
                        feature["A31b_201"],  # rank
                    ]
                    new_feature.setAttributes(attributes)
                    temp_provider.addFeature(new_feature)

                layers.append(temp_layer)

            if not layers:
                data_name = self.tr("hazard area maximum scale")
                msg = (
                    self.tr("No valid %1 Shapefile was found.")
                    .replace("%1", data_name)
                )
                QgsMessageLog.logMessage(
                    msg,
                    self.tr("Plugin"),
                    Qgis.Info,
                )

                # 一時メモリレイヤを作成
                temp_layer = QgsVectorLayer(
                    "Polygon", "hazard_area_maximum_scales", "memory"
                )
                temp_provider = temp_layer.dataProvider()

                # 必要なフィールドを追加
                temp_provider.addAttributes(
                    [
                        QgsField("rank", QVariant.String),
                    ]
                )
                temp_layer.updateFields()
                layers.append(temp_layer)

            # 複数のレイヤをマージ
            merged_layer = self.__merge_layers(layers)

            # 無効なジオメトリを修正する
            merged_layer = self.__fix_invalid_geometries(merged_layer)

            # 空間インデックス作成
            processing.run("native:createspatialindex",
                           {'INPUT': merged_layer})

            # ゾーンポリゴンを読み込む
            zones_layer = self.gpkg_manager.load_layer(
                'zones', None, withload_project=False
            )

            # ゾーンポリゴン範囲と交差するエリアのみを抽出
            extracted_layer = processing.run(
                "native:extractbylocation",
                {
                    'INPUT': merged_layer,
                    'PREDICATE': [0],  # intersects
                    'INTERSECT': zones_layer,
                    'OUTPUT': 'TEMPORARY_OUTPUT',
                },
            )['OUTPUT']

            # hazard_area_maximum_scalesレイヤをGeoPackageに保存
            if not self.gpkg_manager.add_layer(
                extracted_layer,
                "hazard_area_maximum_scales",
                "洪水浸水想定区域_想定最大規模_L2",
            ):
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            data_name = self.tr("hazard area maximum scale")
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

    def create_hazard_area_storm_surge(self):
        """ハザードエリア高潮浸水想定区域 作成"""
        try:
            # base_path 配下の「ハザードエリア高潮浸水想定区域」フォルダを再帰的に探索してShapefileを収集
            induction_area_folder = os.path.join(
                self.base_path, "ハザードエリア高潮浸水想定区域"
            )
            shp_files = self.__get_shapefiles(induction_area_folder)

            # レイヤを格納するリスト
            layers = []

            required_fields = {
                "A49_001",
                "A49_002",
                "A49_003",
            }

            for shp_file in shp_files:
                if self.check_canceled():
                    return  # キャンセルチェック
                encoding = self.__detect_encoding(shp_file)

                # Shapefile 読み込み
                layer = QgsVectorLayer(
                    shp_file, os.path.basename(shp_file), "ogr"
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

                # Shapefileの属性フィールドバリデーション
                layer_fields = set(layer.fields().names())
                required_fields = {
                    "A49_001",
                    "A49_002",
                    "A49_003",
                }

                if not required_fields.issubset(layer_fields):
                    data_name = self.tr("hazard area storm surge")
                    msg = (
                        self.tr("%1 cannot be loaded as %2 data.")
                        .replace("%1", shp_file)
                        .replace("%2", data_name)
                    )
                    QgsMessageLog.logMessage(
                        msg,
                        self.tr("Plugin"),
                        Qgis.Warning,
                    )
                    continue

                # 一時メモリレイヤを作成し、Shapefileのデータを取り込み
                temp_layer = QgsVectorLayer(
                    f"Polygon?crs={layer.crs().authid()}",
                    "hazard_area_storm_surges",
                    "memory",
                )
                temp_provider = temp_layer.dataProvider()

                # 必要なフィールドを追加
                temp_provider.addAttributes(
                    [
                        QgsField("prefecture_name", QVariant.String),
                        QgsField("prefecture_code", QVariant.String),
                        QgsField("rank", QVariant.String),
                    ]
                )
                temp_layer.updateFields()

                # フィーチャの追加
                for feature in layer.getFeatures():
                    if self.check_canceled():
                        return  # キャンセルチェック
                    new_feature = QgsFeature()
                    new_feature.setGeometry(feature.geometry())

                    # 属性データのマッピング
                    attributes = [
                        feature["A49_001"],  # prefecture_name
                        feature["A49_002"],  # prefecture_code
                        feature["A49_003"],  # rank
                    ]
                    new_feature.setAttributes(attributes)
                    temp_provider.addFeature(new_feature)

                layers.append(temp_layer)

            if not layers:
                data_name = self.tr("hazard area storm surge")
                msg = (
                    self.tr("No valid %1 Shapefile was found.")
                    .replace("%1", data_name)
                )
                QgsMessageLog.logMessage(
                    msg,
                    self.tr("Plugin"),
                    Qgis.Info,
                )

                # 一時メモリレイヤを作成
                temp_layer = QgsVectorLayer(
                    "Polygon", "hazard_area_storm_surges", "memory"
                )
                temp_provider = temp_layer.dataProvider()

                # 必要なフィールドを追加
                temp_provider.addAttributes(
                    [
                        QgsField("prefecture_name", QVariant.String),
                        QgsField("prefecture_code", QVariant.String),
                        QgsField("rank", QVariant.String),
                    ]
                )
                temp_layer.updateFields()
                layers.append(temp_layer)

            # 複数のレイヤをマージ
            merged_layer = self.__merge_layers(layers)

            # 無効なジオメトリを修正する
            merged_layer = self.__fix_invalid_geometries(merged_layer)

            # 空間インデックス作成
            processing.run("native:createspatialindex",
                           {'INPUT': merged_layer})

            # ゾーンポリゴンを読み込む
            zones_layer = self.gpkg_manager.load_layer(
                'zones', None, withload_project=False
            )

            # ゾーンポリゴン範囲と交差するエリアのみを抽出
            extracted_layer = processing.run(
                "native:extractbylocation",
                {
                    'INPUT': merged_layer,
                    'PREDICATE': [0],  # intersects
                    'INTERSECT': zones_layer,
                    'OUTPUT': 'TEMPORARY_OUTPUT',
                },
            )['OUTPUT']

            # hazard_area_storm_surgesレイヤをGeoPackageに保存
            if not self.gpkg_manager.add_layer(
                extracted_layer, "hazard_area_storm_surges", "高潮浸水想定区域"
            ):
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            data_name = self.tr("hazard area storm surge")
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

    def create_hazard_area_tsunami(self):
        """ハザードエリア津波浸水想定区域 作成"""
        try:
            # base_path 配下の「ハザードエリア津波浸水想定区域」フォルダを再帰的に探索してShapefileを収集
            induction_area_folder = os.path.join(
                self.base_path, "ハザードエリア津波浸水想定区域"
            )
            shp_files = self.__get_shapefiles(induction_area_folder)

            # レイヤを格納するリスト
            layers = []

            for shp_file in shp_files:
                if self.check_canceled():
                    return  # キャンセルチェック
                encoding = self.__detect_encoding(shp_file)

                # Shapefile 読み込み
                layer = QgsVectorLayer(
                    shp_file, os.path.basename(shp_file), "ogr"
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

                # Shapefileの属性フィールドバリデーション
                layer_fields = set(layer.fields().names())
                required_fields = {
                    "A40_001",
                    "A40_002",
                    "A40_003",
                }

                if not required_fields.issubset(layer_fields):
                    data_name = self.tr("hazard area tsunami")
                    msg = (
                        self.tr("%1 cannot be loaded as %2 data.")
                        .replace("%1", shp_file)
                        .replace("%2", data_name)
                    )
                    QgsMessageLog.logMessage(
                        msg,
                        self.tr("Plugin"),
                        Qgis.Warning,
                    )
                    continue

                # 一時メモリレイヤを作成し、Shapefileのデータを取り込み
                temp_layer = QgsVectorLayer(
                    f"Polygon?crs={layer.crs().authid()}",
                    "hazard_area_tsunamis",
                    "memory",
                )
                temp_provider = temp_layer.dataProvider()

                # 必要なフィールドを追加
                temp_provider.addAttributes(
                    [
                        QgsField("prefecture_name", QVariant.String),
                        QgsField("prefecture_code", QVariant.String),
                        QgsField("rank", QVariant.String),
                    ]
                )
                temp_layer.updateFields()

                # フィーチャの追加
                for feature in layer.getFeatures():
                    if self.check_canceled():
                        return  # キャンセルチェック
                    new_feature = QgsFeature()
                    new_feature.setGeometry(feature.geometry())

                    # 属性データのマッピング
                    attributes = [
                        feature["A40_001"],  # prefecture_name
                        feature["A40_002"],  # prefecture_code
                        feature["A40_003"],  # rank
                    ]
                    new_feature.setAttributes(attributes)
                    temp_provider.addFeature(new_feature)

                layers.append(temp_layer)

            if not layers:
                data_name = self.tr("hazard area tsunami")
                msg = (
                    self.tr("No valid %1 Shapefile was found.")
                    .replace("%1", data_name)
                )
                QgsMessageLog.logMessage(
                    msg,
                    self.tr("Plugin"),
                    Qgis.Info,
                )

                # 一時メモリレイヤを作成
                temp_layer = QgsVectorLayer(
                    "Polygon", "hazard_area_tsunamis", "memory"
                )
                temp_provider = temp_layer.dataProvider()

                # 必要なフィールドを追加
                temp_provider.addAttributes(
                    [
                        QgsField("prefecture_name", QVariant.String),
                        QgsField("prefecture_code", QVariant.String),
                        QgsField("rank", QVariant.String),
                    ]
                )
                temp_layer.updateFields()
                layers.append(temp_layer)

            # 複数のレイヤをマージ
            merged_layer = self.__merge_layers(layers)

            # 無効なジオメトリを修正する
            merged_layer = self.__fix_invalid_geometries(merged_layer)

            # 空間インデックス作成
            processing.run("native:createspatialindex",
                           {'INPUT': merged_layer})

            # ゾーンポリゴンを読み込む
            zones_layer = self.gpkg_manager.load_layer(
                'zones', None, withload_project=False
            )

            # ゾーンポリゴン範囲と交差するエリアのみを抽出
            extracted_layer = processing.run(
                "native:extractbylocation",
                {
                    'INPUT': merged_layer,
                    'PREDICATE': [0],  # intersects
                    'INTERSECT': zones_layer,
                    'OUTPUT': 'TEMPORARY_OUTPUT',
                },
            )['OUTPUT']

            # hazard_area_tsunamisレイヤをGeoPackageに保存
            if not self.gpkg_manager.add_layer(
                extracted_layer, "hazard_area_tsunamis", "津波浸水想定区域"
            ):
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            data_name = self.tr("hazard area tsunami")
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

    def create_hazard_area_landslide(self):
        """ハザードエリア土砂災害 作成"""
        try:
            # base_path 配下の「ハザードエリア土砂災害」フォルダを再帰的に探索してShapefileを収集
            induction_area_folder = os.path.join(
                self.base_path, "ハザードエリア土砂災害"
            )
            shp_files = self.__get_shapefiles(induction_area_folder)

            # レイヤを格納するリスト
            layers = []

            for shp_file in shp_files:
                if self.check_canceled():
                    return  # キャンセルチェック
                encoding = self.__detect_encoding(shp_file)

                # Shapefile 読み込み
                layer = QgsVectorLayer(
                    shp_file, os.path.basename(shp_file), "ogr"
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

                # Shapefileの属性フィールドバリデーション
                layer_fields = set(layer.fields().names())
                required_fields = {
                    "A33_001",
                    "A33_002",
                    "A33_004",
                    "A33_005",
                    "A33_006",
                    "A33_007",
                    "A33_008",
                }

                if not required_fields.issubset(layer_fields):
                    data_name = self.tr("shelter")
                    msg = (
                        self.tr("%1 cannot be loaded as %2 data.")
                        .replace("%1", shp_file)
                        .replace("%2", data_name)
                    )
                    QgsMessageLog.logMessage(
                        msg,
                        self.tr("Plugin"),
                        Qgis.Warning,
                    )
                    continue

                # 一時メモリレイヤを作成し、Shapefileのデータを取り込み
                temp_layer = QgsVectorLayer(
                    f"Polygon?crs={layer.crs().authid()}",
                    "hazard_area_landslides",
                    "memory",
                )
                temp_provider = temp_layer.dataProvider()

                # 必要なフィールドを追加
                temp_provider.addAttributes(
                    [
                        QgsField("phenomenon_type", QVariant.String),
                        QgsField("area_type", QVariant.String),
                        QgsField("prefecture_code", QVariant.String),
                        QgsField("area_number", QVariant.String),
                        QgsField("area_name", QVariant.String),
                        QgsField("address", QVariant.String),
                        QgsField("public_date", QVariant.String),
                        QgsField("designated_flag", QVariant.String),
                    ]
                )
                temp_layer.updateFields()

                # フィーチャの追加
                for feature in layer.getFeatures():
                    if self.check_canceled():
                        return  # キャンセルチェック
                    new_feature = QgsFeature()
                    new_feature.setGeometry(feature.geometry())

                    # 属性データのマッピング
                    attributes = [
                        feature["A33_001"],  # phenomenon_type
                        feature["A33_002"],  # area_type
                        feature["A33_004"],  # area_number
                        feature["A33_005"],  # area_name
                        feature["A33_006"],  # address
                        feature["A33_007"],  # public_date
                        feature["A33_008"],  # designated_flag
                    ]
                    new_feature.setAttributes(attributes)
                    temp_provider.addFeature(new_feature)

                layers.append(temp_layer)

            if not layers:
                data_name = self.tr("hazard area landslide")
                msg = (
                    self.tr("No valid %1 Shapefile was found.")
                    .replace("%1", data_name)
                )
                QgsMessageLog.logMessage(
                    msg,
                    self.tr("Plugin"),
                    Qgis.Info,
                )

                # 一時メモリレイヤを作成
                temp_layer = QgsVectorLayer(
                    "Polygon", "hazard_area_landslides", "memory"
                )
                temp_provider = temp_layer.dataProvider()

                # 必要なフィールドを追加
                temp_provider.addAttributes(
                    [
                        QgsField("phenomenon_type", QVariant.String),
                        QgsField("area_type", QVariant.String),
                        QgsField("prefecture_code", QVariant.String),
                        QgsField("area_number", QVariant.String),
                        QgsField("area_name", QVariant.String),
                        QgsField("address", QVariant.String),
                        QgsField("public_date", QVariant.String),
                        QgsField("designated_flag", QVariant.String),
                    ]
                )
                temp_layer.updateFields()
                layers.append(temp_layer)

            # 複数のレイヤをマージ
            merged_layer = self.__merge_layers(layers)

            # 無効なジオメトリを修正する
            merged_layer = self.__fix_invalid_geometries(merged_layer)

            # 空間インデックス作成
            processing.run("native:createspatialindex",
                           {'INPUT': merged_layer})

            # ゾーンポリゴンを読み込む
            zones_layer = self.gpkg_manager.load_layer(
                'zones', None, withload_project=False
            )

            # ゾーンポリゴン範囲と交差するエリアのみを抽出
            extracted_layer = processing.run(
                "native:extractbylocation",
                {
                    'INPUT': merged_layer,
                    'PREDICATE': [0],  # intersects
                    'INTERSECT': zones_layer,
                    'OUTPUT': 'TEMPORARY_OUTPUT',
                },
            )['OUTPUT']

            # hazard_area_landslidesレイヤをGeoPackageに保存
            if not self.gpkg_manager.add_layer(
                extracted_layer, "hazard_area_landslides", "土砂災害警戒区域"
            ):
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            data_name = self.tr("hazard area landslide")
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

    def create_hazard_area_floodplain(self):
        """ハザードエリア氾濫流 作成"""
        try:
            # base_path 配下の「ハザードエリア氾濫流」フォルダを再帰的に探索してShapefileを収集
            induction_area_folder = os.path.join(
                self.base_path, "ハザードエリア氾濫流"
            )
            shp_files = self.__get_shapefiles(induction_area_folder)

            # レイヤを格納するリスト
            layers = []

            for shp_file in shp_files:
                if self.check_canceled():
                    return  # キャンセルチェック
                encoding = self.__detect_encoding(shp_file)

                # Shapefile 読み込み
                layer = QgsVectorLayer(
                    shp_file, os.path.basename(shp_file), "ogr"
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

                # Shapefileの属性フィールドバリデーション
                layer_fields = set(layer.fields().names())
                required_fields = {
                    "A31b_401",
                }

                if not required_fields.issubset(layer_fields):
                    data_name = self.tr("hazard area floodplain")
                    msg = (
                        self.tr("%1 cannot be loaded as %2 data.")
                        .replace("%1", shp_file)
                        .replace("%2", data_name)
                    )
                    QgsMessageLog.logMessage(
                        msg,
                        self.tr("Plugin"),
                        Qgis.Warning,
                    )
                    continue

                # 一時メモリレイヤを作成し、Shapefileのデータを取り込み
                temp_layer = QgsVectorLayer(
                    f"Polygon?crs={layer.crs().authid()}",
                    "hazard_area_floodplains",
                    "memory",
                )
                temp_provider = temp_layer.dataProvider()

                # 必要なフィールドを追加
                temp_provider.addAttributes(
                    [
                        QgsField("rank", QVariant.String),
                    ]
                )
                temp_layer.updateFields()

                # フィーチャの追加
                for feature in layer.getFeatures():
                    if self.check_canceled():
                        return  # キャンセルチェック
                    new_feature = QgsFeature()
                    new_feature.setGeometry(feature.geometry())

                    # 属性データのマッピング
                    attributes = [
                        feature["A31b_401"],  # rank
                    ]
                    new_feature.setAttributes(attributes)
                    temp_provider.addFeature(new_feature)

                layers.append(temp_layer)

            if not layers:
                data_name = self.tr("hazard area floodplain")
                msg = (
                    self.tr("No valid %1 Shapefile was found.")
                    .replace("%1", data_name)
                )
                QgsMessageLog.logMessage(
                    msg,
                    self.tr("Plugin"),
                    Qgis.Info,
                )

                # 一時メモリレイヤを作成
                temp_layer = QgsVectorLayer(
                    "Polygon", "hazard_area_floodplains", "memory"
                )
                temp_provider = temp_layer.dataProvider()

                # 必要なフィールドを追加
                temp_provider.addAttributes(
                    [
                        QgsField("rank", QVariant.String),
                    ]
                )
                temp_layer.updateFields()
                layers.append(temp_layer)

            # 複数のレイヤをマージ
            merged_layer = self.__merge_layers(layers)

            # 無効なジオメトリを修正する
            merged_layer = self.__fix_invalid_geometries(merged_layer)

            # 空間インデックス作成
            processing.run("native:createspatialindex",
                           {'INPUT': merged_layer})

            # ゾーンポリゴンを読み込む
            zones_layer = self.gpkg_manager.load_layer(
                'zones', None, withload_project=False
            )

            # ゾーンポリゴン範囲と交差するエリアのみを抽出
            extracted_layer = processing.run(
                "native:extractbylocation",
                {
                    'INPUT': merged_layer,
                    'PREDICATE': [0],  # intersects
                    'INTERSECT': zones_layer,
                    'OUTPUT': 'TEMPORARY_OUTPUT',
                },
            )['OUTPUT']

            # hazard_area_floodplainsレイヤをGeoPackageに保存
            if not self.gpkg_manager.add_layer(
                extracted_layer,
                "hazard_area_floodplains",
                "洪水浸水想定区域_氾濫流",
            ):
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            data_name = self.tr("hazard area floodplain")
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

                msg = self.tr("Encoding: %1").replace("%1", encoding)
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
