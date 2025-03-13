"""
/***************************************************************************
 *
 * 評価指標算出機能
 *
 ***************************************************************************/
"""
from qgis.core import QgsProject, QgsRasterLayer
from PyQt5.QtCore import QThread, pyqtSignal
from ..utils import (
    GpkgManager,
    ZoneDataGenerator,
    VacancyDataGenerator,
    DataLoader,
    PopulationDataGenerator,
    FacilityDataGenerator,
    TransportationDataGenerator,
    BuildingDataAssigner,
    AreaDataGenerator,
    FinancialDataGenerator,
    ResidentialInductionMetricCalculator,
    UrbanFunctionInductionMetricCalculator,
    PublicTransportMetricCalculator,
    FiscalMetricCalculator,
    LandUseMetricCalculator,
    DisasterPreventionMetricCalculator,
)


class MetricCalculationWorker(QThread):
    """
    評価指標算出
    """
    # シグナルを使って進捗と完了を通知
    progress = pyqtSignal(int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(
        self,
        input_folder,
        output_folder,
        threshold_bus,
        threshold_railway,
        threshold_shelter,
    ):
        super().__init__()
        self.input_folder = input_folder
        self.output_folder = output_folder
        self.threshold_bus = threshold_bus
        self.threshold_railway = threshold_railway
        self.threshold_shelter = threshold_shelter
        self.is_canceled = False

    def run(self):
        """
        評価指標算出機能に含まれる各機能を順次実行します。
        """
        try:

            # OpenStreetMapのURL
            osm_url = (
                "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png"
            )
            layer_name = "OpenStreetMap"

            # プロジェクト内に同名のレイヤが存在するか確認
            existing_layer = None
            for layer in QgsProject.instance().mapLayers().values():
                if layer.name() == layer_name:
                    existing_layer = layer
                    break

            if existing_layer:
                print(self.tr("%1 already exists in the layer panel").replace("%1", layer_name))
            else:
                # QgsRasterLayerオブジェクトを作成
                osm_layer = QgsRasterLayer(osm_url, layer_name, "wms")

                if osm_layer.isValid():
                    # レイヤのパイプを取得
                    pipe = osm_layer.pipe()
                    if pipe is None:
                        print(self.tr("Unable to retrieve pipe for OSM layer"))
                    else:
                        # Hue/Saturationフィルターを取得
                        huesaturation_filter = pipe.hueSaturationFilter()
                        if huesaturation_filter:
                            # グレースケールを設定
                            huesaturation_filter.setGrayscaleMode(2)
                            print(self.tr(
                                "Set OSM grayscale mode to GrayscaleLuminosity"
                            ))
                        else:
                            print(self.tr(
                                "Hue/Saturation filter is not available "
                                "for OSM layer"
                            ))

                    # レイヤをプロジェクトに追加
                    QgsProject.instance().addMapLayer(osm_layer)
                    print(self.tr("Added %1 to the layer panel").replace("%1", layer_name))
                else:
                    print(self.tr("Failed to add %1").replace("%1", layer_name))

            # データ作成
            # GeoPackageの初期化
            self.progress.emit(0)
            gpkg_manager = GpkgManager(self.output_folder)
            gpkg_manager.init(self.output_folder)
            gpkg_manager.make_gpkg()
            self.progress.emit(5)

            # ゾーンポリゴン作成
            if not self.check_canceled():
                zone_data_generator = ZoneDataGenerator(
                    self.input_folder, self.check_canceled
                )
                zone_data_generator.create_zone()
                self.progress.emit(10)

            # 空き家データ作成
            if not self.check_canceled():
                vacancy_data_generator = VacancyDataGenerator(
                    self.input_folder, self.check_canceled
                )
                vacancy_data_generator.create_vacancy()
                self.progress.emit(15)

            # データ読み込み機能
            if not self.check_canceled():
                data_loader = DataLoader(self.check_canceled)
                data_loader.load_buildings()
                self.progress.emit(20)

            # 人口データ作成機能
            if not self.check_canceled():
                population_data_generator = PopulationDataGenerator(
                    self.input_folder, self.check_canceled
                )
                population_data_generator.load_population_meshes()
                self.progress.emit(25)

            # 施設関連データ作成機能
            if not self.check_canceled():
                facility_data_generator = FacilityDataGenerator(
                    self.input_folder, self.check_canceled
                )
                facility_data_generator.load_facilities()
                self.progress.emit(30)

            # 交通関連データ作成機能
            if not self.check_canceled():
                transportation_data_generator = TransportationDataGenerator(
                    self.input_folder, self.check_canceled
                )
                transportation_data_generator.load_transportations()
                self.progress.emit(35)

            # 建築物LOD1へのデータ付与機能
            if not self.check_canceled():
                building_data_assigner = BuildingDataAssigner(
                    self.input_folder, self.check_canceled
                )
                building_data_assigner.exec()
                self.progress.emit(40)

            # 圏域作成機能
            if not self.check_canceled():
                area_data_generator = AreaDataGenerator(
                    self.input_folder,
                    self.threshold_bus,
                    self.threshold_railway,
                    self.threshold_shelter,
                    self.check_canceled,
                )
                area_data_generator.create_area_data()
                self.progress.emit(45)

            # 財政関連データ作成機能
            if not self.check_canceled():
                financial_data_generator = FinancialDataGenerator(
                    self.input_folder, self.check_canceled
                )
                financial_data_generator.create_land_price()
                self.progress.emit(50)

            # 評価指標算出
            # 居住誘導関連評価指標算出機能
            if not self.check_canceled():
                calclator = ResidentialInductionMetricCalculator(
                    self.output_folder, self.check_canceled
                )
                calclator.calc()
                self.progress.emit(55)

            # 都市機能誘導関連評価指標算出機能
            if not self.check_canceled():
                calclator = UrbanFunctionInductionMetricCalculator(
                    self.output_folder, self.check_canceled
                )
                calclator.calc()
                self.progress.emit(65)

            # 防災関連評価指標算出機能
            if not self.check_canceled():
                calclator = DisasterPreventionMetricCalculator(
                    self.output_folder, self.check_canceled
                )
                calclator.calc()
                self.progress.emit(75)

            # 公共交通関連評価指標算出機能
            if not self.check_canceled():
                calclator = PublicTransportMetricCalculator(
                    self.output_folder, self.check_canceled
                )
                calclator.calc()
                self.progress.emit(85)

            # 土地利用関連評価指標算出機能
            if not self.check_canceled():
                calclator = LandUseMetricCalculator(
                    self.output_folder, self.check_canceled
                )
                calclator.calc()
                self.progress.emit(95)

            # 財政関連評価指標算出機能
            if not self.check_canceled():
                calclator = FiscalMetricCalculator(
                    self.output_folder, self.check_canceled
                )
                calclator.calc()
                self.progress.emit(100)

            if not self.is_canceled:
                self.finished.emit(self.tr("Processing completed"))
            else:
                self.finished.emit(self.tr("Processing was canceled"))

        except Exception as e:
            msg = self.tr("An error occurred: %1").replace("%1", e)
            self.error.emit(msg)


    def check_canceled(self):
        """キャンセル状態を確認"""
        return self.is_canceled

    def cancel(self):
        """キャンセル"""
        self.is_canceled = True
