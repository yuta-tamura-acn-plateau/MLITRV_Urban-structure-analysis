"""
/***************************************************************************
 *
 * 【FN005】交通関連データ作成機能
 *
 ***************************************************************************/
"""

import os
import csv
import re

import processing
import chardet
from qgis.core import (
    QgsMessageLog,
    Qgis,
    QgsVectorLayer,
    QgsField,
    QgsFeature,
    QgsPointXY,
    QgsGeometry,
)
from PyQt5.QtCore import QCoreApplication, QVariant

from .gpkg_manager import GpkgManager

class TransportationDataGenerator:
    """交通関連データ作成機能"""
    def __init__(self, base_path, check_canceled_callback=None):
        # GeoPackageマネージャーを初期化
        self.gpkg_manager = GpkgManager._instance
        # インプットデータパス
        self.base_path = base_path

        self.check_canceled = check_canceled_callback

    def tr(self, message):
        """翻訳用のメソッド"""
        return QCoreApplication.translate(self.__class__.__name__, message)

    def load_transportations(self):
        """交通関連データ作成処理"""
        try:
            if self.check_canceled():
                return  # キャンセルチェック
            self.create_road_networks()
            if self.check_canceled():
                return  # キャンセルチェック
            self.create_railway_stations()
            if self.check_canceled():
                return  # キャンセルチェック
            self.create_railway_networks()
            if self.check_canceled():
                return  # キャンセルチェック
            self.create_bus_networks()
            if self.check_canceled():
                return  # キャンセルチェック
            self.create_traffics()
            return True
        except Exception as e:
            QgsMessageLog.logMessage(
                self.tr("An error occurred: %1").replace("%1", e),
                self.tr("Plugin"),
                Qgis.Critical,
            )
            return False

    def create_road_networks(self):
        """道路ネットワーク作成"""
        try:
            # base_path 配下の「道路ネットワーク」フォルダを再帰的に探索してShapefileを収集
            road_network_folder = os.path.join(
                self.base_path, "道路ネットワーク"
            )
            shp_files = self.__get_shapefiles(road_network_folder)

            if not shp_files:
                raise Exception(
                    "交通関連データ作成 道路ネットワークのShapefileが見つかりません。"
                )

            # ゾーンポリゴンを読み込む
            zones_layer = self.gpkg_manager.load_layer(
                'zones', None, withload_project=False
            )

            # レイヤリストを作成
            layers = []
            required_fields = {
                "osm_id",
                "code",
                "fclass",
                "name",
                "ref",
                "oneway",
                "maxspeed",
                "layer",
                "bridge",
                "tunnel",
            }

            for shp_file in shp_files:
                # Shapefile読み込み
                layer = QgsVectorLayer(
                    shp_file, os.path.basename(shp_file), "ogr"
                )

                # レイヤの属性項目チェック
                layer_fields = set(layer.fields().names())
                if required_fields.issubset(layer_fields):
                    layers.append(layer)
                    # 取り込み対象のファイルパスをログ出力
                    msg = self.tr(
                        "Shapefile to be imported: %1"
                    ).replace("%1", shp_file)
                    QgsMessageLog.logMessage(
                        msg,
                        self.tr("Plugin"),
                        Qgis.Info,
                    )

                else:
                    data_name = self.tr("road network")
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

            if not layers:
                # 道路ネットワークのshpファイルが無い場合
                raise Exception(
                    "必要な道路ネットワークのShapefileが見つかりませんでした。"
                )

            merged_layer = self.__merge_layers(layers)

            processing.run("native:createspatialindex",
                           {'INPUT': merged_layer})

            # ゾーンポリゴン範囲と交差する道路のみを抽出
            extracted_layer = processing.run(
                "native:extractbylocation",
                {
                    'INPUT': merged_layer,
                    'PREDICATE': [0],  # intersects
                    'INTERSECT': zones_layer,
                    'OUTPUT': 'TEMPORARY_OUTPUT',
                },
            )['OUTPUT']

            # road_networksレイヤをGeoPackageに保存
            if not self.gpkg_manager.add_layer(
                extracted_layer, "road_networks", "道路ネットワーク"
            ):
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            data_name = self.tr("road network")
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
            # エラーメッセージをログに記録
            QgsMessageLog.logMessage(
                self.tr("An error occurred: %1").replace("%1", e),
                self.tr("Plugin"),
                Qgis.Critical,
            )

            return False

    def create_railway_stations(self):
        """鉄道駅位置データ作成"""
        try:
            # base_path 配下の「鉄道駅位置」フォルダを再帰的に探索してShapefileを収集
            railway_station_folder = os.path.join(self.base_path, "鉄道駅位置")
            shp_files = self.__get_shapefiles(railway_station_folder)

            if not shp_files:
                data_name = self.tr("railway station")
                msg = self.tr(
                    "The Shapefile for %1 was not found."
                ).replace("%1", data_name)
                QgsMessageLog.logMessage(
                    msg,
                    self.tr("Plugin"),
                    Qgis.Warning,
                )
                return False

            # レイヤを格納するリスト
            layers = []

            for shp_file in shp_files:
                year = self.__extract_year_from_path(shp_file)
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
                    "N02_001",
                    "N02_002",
                    "N02_003",
                    "N02_004",
                    "N02_005",
                }  # 必須フィールド
                if not required_fields.issubset(layer_fields):
                    data_name = self.tr("railway station")
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
                    f"MultiLineString?crs={layer.crs().authid()}",
                    "railway_stations",
                    "memory",
                )
                temp_provider = temp_layer.dataProvider()

                # 必要なフィールドを追加
                fields = [
                    QgsField("type", QVariant.String),
                    QgsField("business_type", QVariant.String),
                    QgsField("railway_name", QVariant.String),
                    QgsField("company_name", QVariant.String),
                    QgsField("name", QVariant.String),
                    QgsField("code", QVariant.String),
                    QgsField("group_code", QVariant.String),
                    QgsField("year", QVariant.Int),
                ]
                temp_provider.addAttributes(fields)
                temp_layer.updateFields()

                temp_layer.startEditing()

                for feature in layer.getFeatures():
                    new_feature = QgsFeature()
                    new_feature.setGeometry(feature.geometry())

                    # 属性データ
                    attributes = [
                        feature["N02_001"],  # type
                        feature["N02_002"],  # business_type
                        feature["N02_003"],  # railway_name
                        feature["N02_004"],  # company_name
                        feature["N02_005"],  # name
                        (
                            feature["N02_005c"]
                            if "N02_005c" in layer_fields
                            else None
                        ),  # code
                        (
                            feature["N02_005g"]
                            if "N02_005g" in layer_fields
                            else None
                        ),  # group_code
                        year,  # year
                    ]
                    new_feature.setAttributes(attributes)
                    temp_provider.addFeature(new_feature)

                temp_layer.commitChanges()

                layers.append(temp_layer)

            if not layers:
                raise Exception(
                    "有効な鉄道駅位置データのShapefileが見つかりませんでした。"
                )

            # 複数のレイヤをマージ
            merged_layer = self.__merge_layers(layers)

            # railway_stationsレイヤをGeoPackageに保存
            if not self.gpkg_manager.add_layer(
                merged_layer, "railway_stations", "鉄道駅"
            ):
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            data_name = self.tr("railway station")
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

    def create_railway_networks(self):
        """鉄道ネットワークデータ作成"""
        try:
            # base_path 配下の「鉄道ネットワーク」フォルダを再帰的に探索してShapefileを収集
            railway_network_folder = os.path.join(
                self.base_path, "鉄道ネットワーク"
            )
            shp_files = self.__get_shapefiles(railway_network_folder)

            if not shp_files:
                data_name = self.tr("railway network")
                msg = self.tr(
                    "The Shapefile for %1 was not found."
                ).replace("%1", data_name)
                QgsMessageLog.logMessage(
                    msg,
                    self.tr("Plugin"),
                    Qgis.Warning,
                )
                return False

            # レイヤを格納するリスト
            layers = []

            for shp_file in shp_files:
                year = self.__extract_year_from_path(shp_file)
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
                    "N02_001",
                    "N02_002",
                    "N02_003",
                    "N02_004",
                }  # 必須フィールド
                invalid_fields = (
                    layer_fields - required_fields
                )  # 必要なフィールド以外が含まれているかチェック
                if not required_fields.issubset(layer_fields) or invalid_fields:
                    data_name = self.tr("railway network")
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
                    f"MultiLineString?crs={layer.crs().authid()}",
                    "railway_networks",
                    "memory",
                )
                temp_provider = temp_layer.dataProvider()

                # 必要なフィールドを追加
                fields = [
                    QgsField("type", QVariant.String),
                    QgsField("business_type", QVariant.String),
                    QgsField("name", QVariant.String),
                    QgsField("company_name", QVariant.String),
                    QgsField("year", QVariant.Int),
                ]
                temp_provider.addAttributes(fields)
                temp_layer.updateFields()

                temp_layer.startEditing()

                for feature in layer.getFeatures():
                    new_feature = QgsFeature()
                    new_feature.setGeometry(feature.geometry())

                    # 属性データ
                    attributes = [
                        feature["N02_001"],  # type
                        feature["N02_002"],  # business_type
                        feature["N02_003"],  # name
                        feature["N02_004"],  # company_name
                        year,  # year
                    ]
                    new_feature.setAttributes(attributes)
                    temp_provider.addFeature(new_feature)

                temp_layer.commitChanges()

                layers.append(temp_layer)

            if not layers:
                raise Exception(
                    "有効な鉄道ネットワークのShapefileが見つかりませんでした。"
                )

            # 複数のレイヤをマージ
            merged_layer = self.__merge_layers(layers)

            # railway_networksレイヤをGeoPackageに保存
            if not self.gpkg_manager.add_layer(
                merged_layer, "railway_networks", "鉄道ネットワーク"
            ):
                raise Exception(self.tr("Failed to add layer to GeoPackage."))

            data_name = self.tr("railway network")
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

    def create_bus_networks(self):
        """バスネットワークデータ作成"""
        try:
            # GTFSフォルダからデータ収集
            bus_network_base_folder = os.path.join(
                self.base_path, "バスネットワーク"
            )
            gtfs_folders = [
                f.path
                for f in os.scandir(bus_network_base_folder)
                if f.is_dir()
            ]  # GTFSフォルダリスト

            if not gtfs_folders:
                data_name = self.tr("GTFS folder for the bus network")
                msg = self.tr(
                    "The %1 was not found."
                ).replace("%1", data_name)
                QgsMessageLog.logMessage(
                    msg,
                    self.tr("Plugin"),
                    Qgis.Warning,
                )
                return False

            # バス停位置レイヤ
            stops_layer = QgsVectorLayer(
                "Point?crs=EPSG:4326", "bus_stops", "memory"
            )
            stops_provider = stops_layer.dataProvider()

            # バス停フィールド定義
            stops_provider.addAttributes(
                [
                    QgsField("stop_id", QVariant.String),
                    QgsField("stop_name", QVariant.String),
                    QgsField("stop_lat", QVariant.Double),
                    QgsField("stop_lon", QVariant.Double),
                    QgsField("stop_times_count", QVariant.Int),  # 停車回数
                ]
            )
            stops_layer.updateFields()

            # バスネットワークレイヤ
            bus_network_layer = QgsVectorLayer(
                "MultiLineString?crs=EPSG:4326", "bus_networks", "memory"
            )
            bus_provider = bus_network_layer.dataProvider()

            # バスネットワークのフィールド定義
            bus_provider.addAttributes(
                [
                    QgsField("agency_id", QVariant.String),
                    QgsField("route_id", QVariant.String),
                    QgsField("from_stop_id", QVariant.String),
                    QgsField("to_stop_id", QVariant.String),
                ]
            )
            bus_network_layer.updateFields()

            # 全GTFSフォルダを処理
            for gtfs_folder in gtfs_folders:
                msg = self.tr(
                    "Processing GTFS folder: %1"
                ).replace("%1", gtfs_folder)

                QgsMessageLog.logMessage(
                    msg,
                    self.tr("Plugin"),
                    Qgis.Info,
                )

                stops_file = os.path.join(gtfs_folder, "stops.txt")
                stop_times_file = os.path.join(gtfs_folder, "stop_times.txt")
                routes_file = os.path.join(gtfs_folder, "routes.txt")
                shapes_file = os.path.join(gtfs_folder, "shapes.txt")

                # エンコードの検出
                stops_encoding = self.__detect_encoding(stops_file)
                stop_times_encoding = self.__detect_encoding(stop_times_file)

                # 停車回数を集計
                stop_times_count = {}
                if os.path.exists(stop_times_file):
                    with open(
                        stop_times_file, 'r', encoding=stop_times_encoding
                    ) as stop_times_csv:
                        stop_times_reader = csv.DictReader(stop_times_csv)
                        for row in stop_times_reader:
                            stop_id = row['stop_id']
                            stop_times_count[stop_id] = (
                                stop_times_count.get(stop_id, 0) + 1
                            )

                # stops.txt からバス停の位置を取得
                if os.path.exists(stops_file):
                    with open(
                        stops_file, 'r', encoding=stops_encoding
                    ) as stops_csv:
                        stops_reader = csv.DictReader(stops_csv)
                        for row in stops_reader:
                            stop_id = row['stop_id']
                            stop_name = row['stop_name']
                            stop_lat = float(row['stop_lat'])
                            stop_lon = float(row['stop_lon'])

                            # 停車回数を取得
                            stop_count = stop_times_count.get(stop_id, 0)

                            # フィーチャを作成
                            feature = QgsFeature()
                            point = QgsPointXY(stop_lon, stop_lat)
                            feature.setGeometry(QgsGeometry.fromPointXY(point))
                            feature.setAttributes(
                                [
                                    stop_id,
                                    stop_name,
                                    stop_lat,
                                    stop_lon,
                                    stop_count,
                                ]
                            )
                            stops_provider.addFeature(feature)

                # バスネットワークを生成
                if os.path.exists(routes_file) and os.path.exists(shapes_file):
                    routes = self.__load_csv(routes_file)
                    trips = self.__load_csv(
                        os.path.join(gtfs_folder, "trips.txt")
                    )
                    stop_times = self.__load_csv(stop_times_file)
                    stops = self.__load_csv(stops_file)

                    stop_coords = {
                        stop['stop_id']: (
                            float(stop['stop_lon']),
                            float(stop['stop_lat']),
                        )
                        for stop in stops
                    }

                    # tripごとの処理
                    for trip in trips:
                        trip_id = trip['trip_id']
                        route_id = trip['route_id']
                        # agency_id を routes から取得
                        agency_id = next(
                            (
                                route['agency_id']
                                for route in routes
                                if route['route_id'] == route_id
                            ),
                            None,
                        )

                        # trip_idに対応する停車順序を取得
                        trip_stop_times = [
                            st for st in stop_times if st['trip_id'] == trip_id
                        ]
                        trip_stop_times.sort(
                            key=lambda x: int(x['stop_sequence'])
                        )

                        # 停車区間を結ぶ線を作成
                        for i in range(len(trip_stop_times) - 1):
                            from_stop_id = trip_stop_times[i]['stop_id']
                            to_stop_id = trip_stop_times[i + 1]['stop_id']

                            from_coords = stop_coords.get(from_stop_id)
                            to_coords = stop_coords.get(to_stop_id)

                            if from_coords and to_coords:
                                # LineStringジオメトリ作成
                                line = QgsGeometry.fromPolylineXY(
                                    [
                                        QgsPointXY(
                                            from_coords[0], from_coords[1]
                                        ),
                                        QgsPointXY(to_coords[0], to_coords[1]),
                                    ]
                                )

                                # 新しいフィーチャ作成
                                feature = QgsFeature()
                                feature.setGeometry(line)
                                feature.setAttributes(
                                    [
                                        agency_id,
                                        route_id,
                                        from_stop_id,
                                        to_stop_id,
                                    ]
                                )
                                bus_provider.addFeature(feature)

            stops_layer.commitChanges()
            bus_network_layer.commitChanges()

            # 保存処理
            if not self.gpkg_manager.add_layer(
                stops_layer, "bus_stops", "バス停"
            ):
                raise Exception(
                    "GeoPackageへのバス停レイヤ追加に失敗しました。"
                )
            if not self.gpkg_manager.add_layer(
                bus_network_layer, "bus_networks", "バスネットワーク"
            ):
                raise Exception(
                    "GeoPackageへのバスネットワークレイヤ追加に失敗しました。"
                )

            data_name = self.tr("bus network")
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

    def create_traffics(self):
        """交通流動データ作成"""
        try:
            # base_path 配下の「交通流動」フォルダを再帰的に探索してShapefileを収集
            traffic_flow_folder = os.path.join(self.base_path, "交通流動")
            shp_files = self.__get_shapefiles(traffic_flow_folder)

            if not shp_files:
                raise Exception(self.tr("The %1 layer was not found.")
                    .replace("%1", "traffics"))

            # フィールドマッピング（shpファイルのフィールド名: trafficsレイヤのフィールド名）
            field_mappings = {
                "S05a_001": "urban_area",
                "S05a_002": "survey_year",
                "S05a_003": "occurrence_concentration",
                "S05a_004": "zone_code",
                "S05a_005": "rail_commute_trip_count",
                "S05a_006": "rail_school_trip_count",
                "S05a_007": "rail_leisure_trip_count",
                "S05a_008": "rail_business_trip_count",
                "S05a_009": "rail_home_trip_count",
                "S05a_010": "rail_total_trip_count",
                "S05a_011": "bus_commute_trip_count",
                "S05a_012": "bus_school_trip_count",
                "S05a_013": "bus_leisure_trip_count",
                "S05a_014": "bus_business_trip_count",
                "S05a_015": "bus_home_trip_count",
                "S05a_016": "bus_total_trip_count",
                "S05a_017": "car_commute_trip_count",
                "S05a_018": "car_school_trip_count",
                "S05a_019": "car_leisure_trip_count",
                "S05a_020": "car_business_trip_count",
                "S05a_021": "car_home_trip_count",
                "S05a_022": "car_total_trip_count",
                "S05a_023": "motorcycle_commute_trip_count",
                "S05a_024": "motorcycle_school_trip_count",
                "S05a_025": "motorcycle_leisure_trip_count",
                "S05a_026": "motorcycle_business_trip_count",
                "S05a_027": "motorcycle_home_trip_count",
                "S05a_028": "motorcycle_total_trip_count",
                "S05a_029": "walking_commute_trip_count",
                "S05a_030": "walking_school_trip_count",
                "S05a_031": "walking_leisure_trip_count",
                "S05a_032": "walking_business_trip_count",
                "S05a_033": "walking_home_trip_count",
                "S05a_034": "walking_total_trip_count",
                "S05a_035": "total_trip_count",
            }

            # traffic_flowレイヤの作成
            traffic_flow_layer = QgsVectorLayer(
                "Polygon?crs=EPSG:4326", "traffics", "memory"
            )
            traffic_provider = traffic_flow_layer.dataProvider()

            # フィールド追加
            fields = [
                (
                    QgsField(name, QVariant.Int)
                    if "count" in name
                    else QgsField(name, QVariant.String)
                )
                for name in field_mappings.values()
            ]
            traffic_provider.addAttributes(fields)
            traffic_flow_layer.updateFields()

            # 各Shapefileを処理
            for shp_file in shp_files:
                layer = QgsVectorLayer(
                    shp_file, os.path.basename(shp_file), "ogr"
                )

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

                # フィーチャの追加
                for feature in layer.getFeatures():
                    new_feature = QgsFeature()
                    new_feature.setGeometry(feature.geometry())

                    # マッピングに沿ってフィールドコピー
                    attributes = [
                        feature[field] for field in field_mappings.keys()
                    ]
                    new_feature.setAttributes(attributes)
                    traffic_provider.addFeature(new_feature)

            # trafficsレイヤをGeoPackageに保存
            if not self.gpkg_manager.add_layer(
                traffic_flow_layer, "traffics", "発生集中量"
            ):
                raise Exception(
                    "GeoPackageへのtraffic_flowレイヤ追加に失敗しました。"
                )

            data_name = self.tr("traffic")
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
                "%1", e
            )
            QgsMessageLog.logMessage(
                msg,
                self.tr("Plugin"),
                Qgis.Critical,
            )
            return None

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

    def __load_csv(self, file_path):
        """CSVファイルを読み込む"""
        data = []
        try:
            # ファイルのエンコーディングを検出
            encoding = self.__detect_encoding(file_path)

            # 検出したエンコーディングでファイルを読み込む
            with open(file_path, 'r', encoding=encoding) as csv_file:
                reader = csv.DictReader(csv_file)
                for row in reader:
                    data.append(row)
        except Exception as e:
            msg = self.tr("Failed to load CSV file: %1").replace("%1", e)
            QgsMessageLog.logMessage(
                msg,
                self.tr("Plugin"),
                Qgis.Critical,
            )
        return data
