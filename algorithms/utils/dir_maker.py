"""
/***************************************************************************
 *
 * 【FN001】フォルダ生成機能
 * 使用例
 * dir_maker = DirMaker("{ディレクトリパス}")
 * dir_maker.create_structure()
 *
 ***************************************************************************/
"""

import os
from qgis.core import QgsMessageLog, Qgis
from PyQt5.QtCore import QCoreApplication

class DirMaker:
    """フォルダ生成機能"""
    def __init__(self, base_path):
        self.base_path = base_path

    def tr(self, message):
        """翻訳用のメソッド"""
        return QCoreApplication.translate(self.__class__.__name__, message)

    def create_structure(self):
        """フォルダ生成処理"""
        try:
            # 作成するフォルダのリスト
            directories = [
                "ゾーンポリゴン",
                "250mメッシュ",
                "250mメッシュ人口/2010年",
                "250mメッシュ人口/2015年",
                "250mメッシュ人口/2020年",
                "鉄道駅位置",
                "鉄道ネットワーク",
                "道路ネットワーク",
                "施設/行政施設ポイント",
                "施設/医療施設ポイント",
                "施設/福祉施設ポイント",
                "施設/学校ポイント",
                "施設/文化施設ポイント",
                "避難所",
                "バスネットワーク",
                "500mメッシュ別将来人口",
                "ハザードエリア計画規模",
                "ハザードエリア想定最大規模",
                "ハザードエリア高潮浸水想定区域",
                "ハザードエリア津波浸水想定区域",
                "ハザードエリア土砂災害",
                "ハザードエリア氾濫流",
                "誘導区域",
                "交通流動",
                "地価公示",
                "土地利用状況判別",
                "空き家ポイント",
            ]

            for directory in directories:
                dir_path = os.path.join(self.base_path, directory)
                os.makedirs(dir_path, exist_ok=True)

            # 目標人口設定ファイルを作成
            csv_path = os.path.join(
                self.base_path, "population_target_setting.csv"
            )
            with open(csv_path, mode='w', encoding='shift_jis') as file:
                file.write("比較将来年度,目標人口\n")

            # フォルダ構成作成成功のログ出力
            msg = self.tr(
                "Created folder structure at %1."
            ).replace("%1", self.base_path)
            QgsMessageLog.logMessage(
                msg,
                self.tr("Plugin"),
                Qgis.Info,
            )
            return True
        except Exception as e:
            # エラーメッセージのログ出力
            QgsMessageLog.logMessage(
                self.tr("An error occurred: %1").replace("%1", e),
                self.tr("Plugin"),
                Qgis.Critical,
            )
            raise e
